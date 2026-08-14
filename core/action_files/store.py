"""Live, user-writable action catalogue and legacy runtime adapters."""

from __future__ import annotations

import shutil
import sys
import threading
import tomllib
from pathlib import Path
from typing import Any

from core.action_files.contracts import ActionCatalog, AppDef, CallerDef
from core.action_files.edit import update_toml_values
from core.action_files.loader import load_catalog
from core.action_files.templates import resolve_catalog
from core.system.env_utils import normalize_file_access_mode
from core.system.paths import CALLERS_DIR, SHIPPED_CALLERS_DIR

_LEGACY_SPREADSHEET_PICKER_PRIMITIVES = {
    "calc.add_chart@1",
    "calc.format_table@1",
    "calc.sort_range@1",
    "excel.add_chart@1",
    "excel.create_table@1",
    "excel.sort_range@1",
}
_LEGACY_SPREADSHEET_PICKER_ACTIONS = {"analyze_selection", "calc.analyze_selection"}
_SPREADSHEET_CLEANUP_UPGRADES = {
    "excel": ("excel.clean_range@1", "excel_plan_clean_range"),
    "libreoffice_calc": ("calc.clean_range@1", "calc_plan_clean_range"),
}
_LEGACY_EXPLAIN_FORMULA_COPY = (
    "Explain the selected formula",
    "Describe its inputs and logic, then flag likely mistakes",
    (
        "Explain the selected spreadsheet formula in plain language, including its inputs, logic, and output. "
        "Flag broken references, risky assumptions, or inconsistencies with neighboring formulas. If no formula "
        "text is available, say exactly what the user needs to select. Do not change any cells."
    ),
)
_EXPLAIN_FORMULA_COPY = (
    "Explain formula",
    _LEGACY_EXPLAIN_FORMULA_COPY[1],
    _LEGACY_EXPLAIN_FORMULA_COPY[2],
)


def _tree_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap signature for files that can affect a catalogue."""
    if not root.is_dir():
        return ()
    rows: list[tuple[str, int, int]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.casefold() not in {".toml", ".py"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append((path.relative_to(root).as_posix(), stat.st_mtime_ns, stat.st_size))
    return tuple(sorted(rows))


class ActionCatalogStore:
    """Seed and reload one live callers tree without restarting OpenWand."""

    def __init__(self, live_root: Path, shipped_root: Path) -> None:
        self.live_root = Path(live_root)
        self.shipped_root = Path(shipped_root)
        self._lock = threading.RLock()
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._catalog: ActionCatalog | None = None

    def ensure_seeded(self) -> Path:
        """Seed defaults and add newly shipped actions without replacing user edits."""
        if self.live_root.is_dir():
            try:
                self._merge_missing_shipped_files()
            except OSError:
                # Existing user files remain the authoritative fallback when
                # an installed or portable tree is temporarily read-only.
                pass
            return self.live_root
        try:
            self.live_root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.shipped_root, self.live_root)
            return self.live_root
        except OSError:
            # Read-only or unusually locked-down launches still get the shipped
            # actions; Settings can explain that edits are unavailable there.
            return self.shipped_root

    def _merge_missing_shipped_files(self) -> None:
        """Copy upgrade additions while preserving every existing user file."""
        if not self.shipped_root.is_dir():
            return
        key_files: list[tuple[Path, Path]] = []
        for source in self.shipped_root.rglob("*"):
            if not source.is_file():
                continue
            target = self.live_root / source.relative_to(self.shipped_root)
            if source.name.casefold() == "keys.toml" and target.is_file():
                key_files.append((source, target))
                continue
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        for source, target in key_files:
            self._merge_missing_key_bindings(source, target)

    @staticmethod
    def _merge_missing_key_bindings(source: Path, target: Path) -> None:
        """Append bindings for new shipped actions without changing user keys."""
        try:
            shipped = tomllib.loads(source.read_text(encoding="utf-8"))
            live = tomllib.loads(target.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return
        shipped_bindings = {
            str(key).strip(): str(value).strip()
            for key, value in shipped.items()
            if isinstance(key, str) and isinstance(value, str) and str(key).strip() and str(value).strip()
        }
        live_bindings = {
            str(key).strip(): str(value).strip()
            for key, value in live.items()
            if isinstance(key, str) and isinstance(value, str) and str(key).strip() and str(value).strip()
        }
        used_keys = {key.casefold() for key in live_bindings}
        bound_actions = {value.casefold() for value in live_bindings.values()}
        additions: dict[str, str] = {}
        for preferred_key, action_name in shipped_bindings.items():
            if action_name.casefold() in bound_actions:
                continue
            candidates = (preferred_key, *action_name.replace("_", ""), *"abcdefghijklmnopqrstuvwxyz123456789")
            key = next((item for item in candidates if item.casefold() not in used_keys), "")
            if not key:
                continue
            additions[key] = action_name
            used_keys.add(key.casefold())
            bound_actions.add(action_name.casefold())
        if additions:
            update_toml_values(target, additions)

    def catalog(self, language: str | None = None) -> ActionCatalog:
        """Return the current catalogue, reloading only after a tree change."""
        with self._lock:
            root = self.ensure_seeded()
            signature = _tree_signature(root)
            if self._catalog is None or signature != self._signature or self._catalog.root != str(root):
                self._catalog = load_catalog(root)
                self._signature = signature
            return resolve_catalog(self._catalog, language)

    def invalidate(self) -> None:
        """Force the next access to reload the catalogue."""
        with self._lock:
            self._signature = None


_DEFAULT_STORE = ActionCatalogStore(CALLERS_DIR, SHIPPED_CALLERS_DIR)
_STORES: dict[str, ActionCatalogStore] = {str(CALLERS_DIR): _DEFAULT_STORE}


def _active_store() -> ActionCatalogStore:
    """Return the store beside the active settings file.

    Normal launches resolve to ``CALLERS_DIR``.  Keeping the root adjacent to
    an explicitly redirected settings file also makes portable profiles and
    isolated acceptance runs use one coherent source of truth.
    """
    root = CALLERS_DIR
    config = sys.modules.get("config")
    env_file = getattr(config, "_ENV_FILE", None) if config is not None else None
    if env_file:
        root = Path(env_file).parent / "callers"
    key = str(root)
    store = _STORES.get(key)
    if store is None:
        store = ActionCatalogStore(root, SHIPPED_CALLERS_DIR)
        _STORES[key] = store
    return store


def live_catalog(language: str | None = None) -> ActionCatalog:
    """Return OpenWand's default live catalogue."""
    return _active_store().catalog(language)


def invalidate_live_catalog() -> None:
    """Force a reload after Settings writes action files."""
    _active_store().invalidate()


def _context_mode(value: Any) -> str:
    mode = str(value or "off").strip().casefold()
    return mode if mode in {"off", "on", "model"} else "off"


def caller_row(caller: CallerDef) -> dict[str, Any]:
    """Adapt a file-backed caller to the policy shape used by current flows."""
    settings = dict(caller.settings)
    raw_context = settings.get("context")
    context = dict(raw_context) if isinstance(raw_context, dict) else {}
    ambient = _context_mode(context.get("ambient"))
    browser = _context_mode(context.get("browser"))
    screenshot = _context_mode(context.get("screenshot"))
    github = _context_mode(context.get("github"))
    memory = _context_mode(context.get("memory"))
    files = _context_mode(context.get("files"))
    legacy_file_access = "off" if files == "off" else ("ask" if files == "on" else "auto")
    file_access = normalize_file_access_mode(settings.get("file_access"), legacy_file_access)
    raw_tools = settings.get("tools")
    intents = []
    for item in caller.actions:
        action = item.action
        intents.append(
            {
                "key": item.key,
                "label": action.label,
                "hint": action.hint,
                "prompt": action.prompt,
                "enabled": action.enabled,
                "action_file": action.to_dict(),
            }
        )
    hotkey = caller.hotkey
    hotkey_2 = caller.hotkey_2
    if sys.platform != "win32":
        # The shipped Windows defaults use Ctrl+Q.  Preserve the existing
        # cross-platform safety rule so a first-run caller never replaces the
        # conventional Quit shortcut on macOS or Linux.
        replacements = {
            "ctrl+q": "ctrl+alt+space",
            "ctrl+shift+q": "ctrl+alt+shift+space",
        }
        hotkey = replacements.get(hotkey.casefold(), hotkey)
        hotkey_2 = replacements.get(hotkey_2.casefold(), hotkey_2)
    return {
        "folder": caller.folder,
        "profile": str(settings.get("profile") or "default"),
        "hotkey": hotkey,
        "hotkey_2": hotkey_2,
        "enabled": caller.enabled,
        "label": caller.label,
        "paste_back": bool(settings.get("paste_back", False)),
        "custom_key": str(settings.get("custom_key") or "s"),
        "custom_label": str(settings.get("custom_label") or ""),
        "space_starts_new_chat": bool(settings.get("space_starts_new_chat", True)),
        "context_ambient": ambient != "off",
        "context_documents": ambient == "on",
        "context_tools": any(mode == "model" for mode in (ambient, browser, github, memory)),
        "context_documents_mode": "auto" if ambient == "on" else ambient,
        "context_browser_mode": "auto" if browser == "on" else browser,
        "context_github_mode": "auto" if github == "on" else github,
        "context_memory_mode": "on" if memory == "on" else memory,
        "context_screenshot": "auto" if screenshot == "on" else screenshot,
        "context_clipboard": _context_mode(context.get("clipboard")) != "off",
        "_context_selection_enabled": _context_mode(context.get("selection")) != "off",
        "file_access": file_access,
        "tools": dict(raw_tools) if isinstance(raw_tools, dict) else {},
        "intents": intents,
    }


def caller_rows(language: str | None = None) -> list[dict[str, Any]]:
    """Return all live callers in the compatibility runtime shape."""
    return [caller_row(caller) for caller in live_catalog(language).callers]


def configured_caller_rows(config: Any) -> list[dict[str, Any]]:
    """Refresh config-backed rows unless a caller explicitly overrode them.

    Tests and a few internal call sites temporarily replace ``config.CALLER_ROWS``
    in place. Keeping that narrow compatibility makes the runtime easy to test
    while normal launches still re-read file changes every time a picker opens.
    """
    current = getattr(config, "CALLER_ROWS", None)
    published = getattr(config, "ACTION_FILE_CALLER_ROWS", None)
    if isinstance(current, list) and (
        not isinstance(published, list) or current != published
    ):
        return current
    rows = caller_rows(getattr(config, "ASSISTANT_LANGUAGE", None))
    if isinstance(current, list):
        current[:] = rows
        result = current
    else:
        result = rows
        config.CALLER_ROWS = result
    config.ACTION_FILE_CALLER_ROWS = [dict(row) for row in rows]
    return result


def _active_surface(context: dict[str, Any] | None) -> dict[str, Any]:
    value = context if isinstance(context, dict) else {}
    active = value.get("active_app")
    surface = dict(active) if isinstance(active, dict) else dict(value)
    if value.get("browser_url"):
        surface["browser_url"] = str(value.get("browser_url") or "")
    return surface


def app_picker_context(context: dict[str, Any] | None, language: str | None = None) -> dict[str, Any]:
    """Return picker-safe metadata for the app folder matching a snapshot."""
    app = live_catalog(language).detect_app(_active_surface(context))
    return _app_picker_context(app) if app is not None else {}


def action_runtime_route(
    app_folder: str,
    action_name: str,
    capability: str,
    planner: str,
    *,
    label: str = "",
    hint: str = "",
    prompt: str = "",
) -> tuple[str, str]:
    """Return the trusted route, including narrow compatibility upgrades."""
    legacy_cleanup = (
        action_name == "clean_export"
        and not capability
        and label == "Clean up this export"
        and hint == "Find cleanup problems and propose exact, reviewable fixes"
        and "do not change cells until a reviewed cleanup capability is available" in prompt
    )
    if legacy_cleanup:
        return _SPREADSHEET_CLEANUP_UPGRADES.get(app_folder, ("", ""))
    return capability, planner


def action_runtime_copy(
    app_folder: str,
    action_name: str,
    label: str,
    hint: str,
    prompt: str,
) -> tuple[str, str, str]:
    """Upgrade unchanged stock wording while preserving user-authored copy."""
    current = (label, hint, prompt)
    if (
        app_folder in {"excel", "libreoffice_calc"}
        and action_name == "explain_formula"
        and current == _LEGACY_EXPLAIN_FORMULA_COPY
    ):
        return _EXPLAIN_FORMULA_COPY
    return current


def _app_picker_context(app: AppDef) -> dict[str, Any]:
    suggestions: list[dict[str, Any]] = []
    for item in app.actions:
        action = item.action
        if not action.enabled:
            continue
        label, hint, prompt = action_runtime_copy(
            app.folder,
            action.name,
            action.label,
            action.hint,
            action.prompt,
        )
        capability, planner = action_runtime_route(
            app.folder,
            action.name,
            action.capability,
            action.planner,
            label=label,
            hint=hint,
            prompt=prompt,
        )
        legacy_cleanup_upgrade = bool(capability and not action.capability)
        # Existing live trees predate the reviewed cleanup capability. Keep
        # user-authored labels/prompts intact while upgrading this one shipped
        # action's trusted runtime route without overwriting the local TOML.
        suggestions.append(
            {
                "id": action.name,
                "label": label,
                "hint": hint,
                "prompt": prompt,
                "preferred_key": item.key,
                "mode": "action" if capability else "file" if action.has_code else "answer",
                "capability_type": capability,
                "planning_tool": planner,
                "available": action.available,
                "unavailable_reason": action.unavailable_reason,
                "show_in_picker": (
                    action.show_in_picker
                    and action.capability not in _LEGACY_SPREADSHEET_PICKER_PRIMITIVES
                    and action.name not in _LEGACY_SPREADSHEET_PICKER_ACTIONS
                ),
                "access": ["files"] if legacy_cleanup_upgrade else [entry.value for entry in action.access],
                "access_colour": "amber" if legacy_cleanup_upgrade else action.colour,
                "action_file": action.to_dict(),
            }
        )
    return {
        "id": app.folder,
        "app": app.app,
        "display_name": app.display_name,
        "suggested_intents": suggestions,
    }


__all__ = [
    "ActionCatalogStore",
    "action_runtime_copy",
    "action_runtime_route",
    "app_picker_context",
    "caller_row",
    "caller_rows",
    "configured_caller_rows",
    "invalidate_live_catalog",
    "live_catalog",
]
