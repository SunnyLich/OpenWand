"""Walk a callers/ tree and build the action catalogue.

Nothing here executes action code, and nothing here could: an action's
description is a .toml data file, and its optional .py script is never touched
until the action is chosen. A broken action is reported and skipped rather
than stopping the menu from being drawn.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from core.action_files.contracts import (
    CONTEXT_SOURCES,
    ActionCatalog,
    ActionFile,
    AppDef,
    AppMatch,
    BoundAction,
    CallerDef,
    LoadIssue,
)
from core.action_files.parse import ACTION_SUFFIX, SCRIPT_SUFFIX, parse_action_file

CALLERS_FILE = "callers.toml"
CALLER_FILE = "caller.toml"
KEYS_FILE = "keys.toml"
APP_FILE = "app.toml"
APPS_DIR = "app"

#: Structural files share the action suffix, so they must never be read as
#: actions themselves.
RESERVED_NAMES = frozenset((CALLERS_FILE, CALLER_FILE, KEYS_FILE, APP_FILE))


def _read_toml(path: Path, issues: list[LoadIssue]) -> dict[str, Any] | None:
    """Return a parsed TOML table, or None with an issue recorded."""
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as exc:
        issues.append(LoadIssue(str(path), "unreadable", f"Could not read the file: {exc}"))
        return None
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        issues.append(LoadIssue(str(path), "bad_toml", f"This file is not valid TOML: {exc}"))
        return None


def _action_paths(folder: Path) -> list[Path]:
    """Return the action description files in one folder, ignoring helpers."""
    return sorted(
        path
        for path in folder.glob(f"*{ACTION_SUFFIX}")
        if not path.name.startswith(("_", ".")) and path.name not in RESERVED_NAMES
    )


def _orphan_scripts(folder: Path, issues: list[LoadIssue]) -> None:
    """Report a script whose description file is missing.

    An action is a .toml plus an optional .py of the same name. Renaming one
    and not the other would otherwise detach them silently, and the action
    would quietly stop running its code.
    """
    for script in sorted(folder.glob(f"*{SCRIPT_SUFFIX}")):
        if script.name.startswith(("_", ".")):
            continue
        if not script.with_suffix(ACTION_SUFFIX).is_file():
            issues.append(
                LoadIssue(
                    str(script),
                    "orphan_script",
                    f"There is no {script.stem}{ACTION_SUFFIX} beside this script, so nothing runs it.",
                )
            )


def _valid_key(key: str) -> bool:
    """Return whether a menu letter is usable."""
    return len(key) == 1 and key.isalnum()


def _bind(folder: Path, issues: list[LoadIssue]) -> tuple[BoundAction, ...]:
    """Read one folder's actions and attach the letters from keys.toml.

    Files listed in keys.toml come first in listed order. Anything else in the
    folder follows alphabetically with no letter, so dropping a file in always
    puts it on screen.
    """
    parsed: dict[str, ActionFile] = {}
    for path in _action_paths(folder):
        action, action_issues = parse_action_file(path)
        issues.extend(action_issues)
        if action is not None:
            parsed[path.stem] = action
    _orphan_scripts(folder, issues)

    bindings = _read_toml(folder / KEYS_FILE, issues)
    rows: list[BoundAction] = []
    used: set[str] = set()

    if isinstance(bindings, dict):
        for raw_key, raw_name in bindings.items():
            key = str(raw_key).strip().casefold()
            name = Path(str(raw_name).strip()).stem
            where = str(folder / KEYS_FILE)
            if not _valid_key(key):
                issues.append(LoadIssue(where, "bad_key", f"{raw_key!r} is not a single letter or digit."))
                continue
            if key in used:
                issues.append(LoadIssue(where, "duplicate_key", f"{key!r} is bound more than once."))
                continue
            action = parsed.get(name)
            if action is None:
                issues.append(LoadIssue(where, "missing_action", f"{key!r} points at {name!r}, which is not here."))
                continue
            used.add(key)
            rows.append(BoundAction(key=key, action=action))
    elif bindings is not None:
        issues.append(LoadIssue(str(folder / KEYS_FILE), "bad_toml", "keys.toml must be a table of key to action name."))

    bound = {Path(item.action.path).stem for item in rows}
    for name, action in parsed.items():
        if name not in bound:
            rows.append(BoundAction(key="", action=action))
    return tuple(rows)


def _caller(root: Path, entry: dict[str, Any], issues: list[LoadIssue]) -> CallerDef | None:
    """Build one caller from its callers.toml entry and its folder."""
    name = str(entry.get("folder") or "").strip()
    if not name:
        issues.append(LoadIssue(str(root / CALLERS_FILE), "no_folder", "A caller entry needs a folder name."))
        return None
    folder = root / name
    if not folder.is_dir():
        issues.append(LoadIssue(str(root / CALLERS_FILE), "missing_folder", f"There is no {name!r} folder."))
        return None

    settings = _read_toml(folder / CALLER_FILE, issues)
    settings = dict(settings) if isinstance(settings, dict) else {}
    context = settings.get("context")
    if isinstance(context, dict):
        for source in sorted(set(context) - set(CONTEXT_SOURCES)):
            known = ", ".join(CONTEXT_SOURCES)
            issues.append(
                LoadIssue(
                    str(folder / CALLER_FILE),
                    "unknown_context",
                    f"{source!r} is not a context source. Known sources: {known}.",
                )
            )
    hotkey = str(entry.get("hotkey") or "").strip()
    if not hotkey:
        issues.append(LoadIssue(str(folder), "no_hotkey", f"{name!r} has no hotkey, so nothing can open it."))

    return CallerDef(
        folder=name,
        hotkey=hotkey,
        hotkey_2=str(entry.get("hotkey_2") or "").strip(),
        label=str(settings.get("label") or entry.get("label") or name),
        enabled=bool(entry.get("enabled", True)),
        settings=settings,
        actions=_bind(folder, issues),
    )


def _app(folder: Path, issues: list[LoadIssue]) -> tuple[AppDef | None, int]:
    """Build one app folder and its detection priority."""
    manifest = _read_toml(folder / APP_FILE, issues)
    if not isinstance(manifest, dict):
        if manifest is None and not (folder / APP_FILE).exists():
            issues.append(LoadIssue(str(folder), "no_app_file", f"{folder.name!r} has no {APP_FILE}."))
        return None, 0

    raw = manifest.get("match")
    raw = raw if isinstance(raw, dict) else {}

    def entries(key: str) -> tuple[str, ...]:
        value = raw.get(key)
        if not isinstance(value, list | tuple):
            return ()
        return tuple(
            item.strip().casefold() for item in value if isinstance(item, str) and item.strip()
        )

    match = AppMatch(process=entries("process"), title=entries("title"), url=entries("url"))
    if not (match.process or match.title or match.url):
        issues.append(
            LoadIssue(str(folder / APP_FILE), "no_match", "An app folder needs at least one process, title, or url.")
        )
        return None, 0

    priority = manifest.get("priority")
    app = AppDef(
        folder=folder.name,
        display_name=str(manifest.get("display_name") or folder.name),
        match=match,
        actions=_bind(folder, issues),
    )
    return app, priority if isinstance(priority, int) else 0


def load_catalog(root: Path | str) -> ActionCatalog:
    """Read a whole callers/ tree. Never raises; problems come back as issues."""
    base = Path(root)
    issues: list[LoadIssue] = []
    if not base.is_dir():
        return ActionCatalog(
            root=str(base),
            issues=(LoadIssue(str(base), "no_root", "The actions folder does not exist."),),
        )

    manifest = _read_toml(base / CALLERS_FILE, issues)
    entries: list[dict[str, Any]] = []
    if isinstance(manifest, dict):
        raw = manifest.get("callers")
        if isinstance(raw, list):
            entries = [item for item in raw if isinstance(item, dict)]
        else:
            issues.append(LoadIssue(str(base / CALLERS_FILE), "bad_toml", "callers.toml needs a [[callers]] entry for each folder."))
    elif manifest is not None:
        issues.append(LoadIssue(str(base / CALLERS_FILE), "bad_toml", "callers.toml must be a table."))
    elif not (base / CALLERS_FILE).exists():
        issues.append(LoadIssue(str(base / CALLERS_FILE), "no_callers_file", "There is no callers.toml."))

    callers = tuple(
        caller for caller in (_caller(base, entry, issues) for entry in entries) if caller is not None
    )

    ranked: list[tuple[int, str, AppDef]] = []
    apps_dir = base / APPS_DIR
    if apps_dir.is_dir():
        for folder in sorted(path for path in apps_dir.iterdir() if path.is_dir()):
            app, priority = _app(folder, issues)
            if app is not None:
                ranked.append((priority, folder.name, app))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    return ActionCatalog(
        root=str(base),
        callers=callers,
        apps=tuple(item[2] for item in ranked),
        issues=tuple(issues),
    )


def lookup_report(catalog: ActionCatalog) -> str:
    """Render the generated app lookup table for people to read.

    This is a report, not a source. The catalogue is always built from the
    folders, so this cannot go stale the way a hand-maintained index would.
    """
    lines = [
        "# Generated app lookup",
        "",
        f"Built from {catalog.root}. Do not edit; this file is rewritten on load.",
        "",
    ]
    if not catalog.apps:
        lines.append("No app folders found.")
        return "\n".join(lines) + "\n"
    for app in catalog.apps:
        lines.append(f"## {app.display_name}  (app/{app.folder})")
        for field_name, values in (
            ("process", app.match.process),
            ("title", app.match.title),
            ("url", app.match.url),
        ):
            if values:
                lines.append(f"- {field_name}: {', '.join(values)}")
        for item in app.actions:
            key = item.key or "-"
            lines.append(f"  [{key}] {item.action.label}")
        lines.append("")
    return "\n".join(lines) + "\n"
