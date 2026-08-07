"""Declarative action catalogue for isolated addons.

Addon action files describe surfaces exposed by an addon's existing Python
host.  Reading them never imports addon code; the host remains responsible for
executors, schemas, permissions, dependencies, and lifecycle.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.action_files.contracts import ACCESS_COLOUR, ACCESS_SEVERITY, Access, LoadIssue

ADDON_ACTIONS_DIR = "actions"
ADDON_ACTION_KINDS = frozenset({
    "intent",
    "tool",
    "tool_provider",
    "response_transform",
    "message_action",
})
_STRING_FIELDS = frozenset({"id", "kind", "label", "hint", "handler", "prompt", "caller", "key"})
_KNOWN_FIELDS = _STRING_FIELDS | {"access", "enabled"}


@dataclass(frozen=True)
class AddonActionFile:
    """One data-only declaration for an addon-provided action surface."""

    path: str
    id: str
    kind: str
    label: str
    hint: str = ""
    handler: str = ""
    prompt: str = ""
    caller: str = "all"
    key: str = ""
    access: tuple[Access, ...] = ()
    enabled: bool = True

    @property
    def severity(self) -> int:
        """Return the highest declared access severity."""
        return max((ACCESS_SEVERITY[item] for item in self.access), default=0)

    @property
    def colour(self) -> str:
        """Return the display colour for the declared access."""
        return ACCESS_COLOUR[self.severity]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible descriptor."""
        value = asdict(self)
        value["access"] = [item.value for item in self.access]
        value["severity"] = self.severity
        value["colour"] = self.colour
        return value


def _text(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    return value.strip() if isinstance(value, str) else ""


def parse_addon_action_file(path: Path | str) -> tuple[AddonActionFile | None, tuple[LoadIssue, ...]]:
    """Read one addon action TOML without importing the addon."""
    target = Path(path)
    display = str(target)
    try:
        values = tomllib.loads(target.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        return None, (LoadIssue(display, "unreadable", f"Could not read the file: {exc}"),)
    except tomllib.TOMLDecodeError as exc:
        return None, (LoadIssue(display, "bad_toml", f"This file is not valid TOML: {exc}"),)

    issues: list[LoadIssue] = []
    for key in sorted(set(values) - _KNOWN_FIELDS):
        issues.append(LoadIssue(display, "unknown_field", f"{key!r} is not an addon action setting."))
    for key in _STRING_FIELDS:
        if key in values and not isinstance(values[key], str):
            issues.append(LoadIssue(display, "wrong_type", f"{key} must be text."))
    if "enabled" in values and not isinstance(values["enabled"], bool):
        issues.append(LoadIssue(display, "wrong_type", "enabled must be true or false."))
    raw_access = values.get("access") or []
    if "access" in values and not (
        isinstance(raw_access, list) and all(isinstance(item, str) for item in raw_access)
    ):
        issues.append(LoadIssue(display, "wrong_type", "access must be a list of text values."))
        raw_access = []

    action_id = _text(values, "id") or target.stem
    kind = _text(values, "kind").casefold()
    label = _text(values, "label")
    handler = _text(values, "handler") or action_id
    if not kind:
        issues.append(LoadIssue(display, "no_kind", "An addon action needs a kind."))
    elif kind not in ADDON_ACTION_KINDS:
        allowed = ", ".join(sorted(ADDON_ACTION_KINDS))
        issues.append(LoadIssue(display, "unknown_kind", f"Unknown kind {kind!r}. Allowed: {allowed}."))
    if not label:
        issues.append(LoadIssue(display, "no_label", "An addon action needs a label."))

    access: list[Access] = []
    for item in raw_access:
        try:
            access.append(Access(item.strip().casefold()))
        except ValueError:
            allowed = ", ".join(sorted(entry.value for entry in Access))
            issues.append(LoadIssue(display, "unknown_access", f"Unknown access {item!r}. Allowed: {allowed}."))

    if kind == "intent" and not _text(values, "prompt") and not handler:
        issues.append(LoadIssue(display, "does_nothing", "An intent needs a prompt or handler."))
    fatal = {"no_kind", "unknown_kind", "no_label", "does_nothing"}
    if any(issue.code in fatal for issue in issues):
        return None, tuple(issues)
    return AddonActionFile(
        path=display,
        id=action_id,
        kind=kind,
        label=label,
        hint=_text(values, "hint"),
        handler=handler,
        prompt=_text(values, "prompt"),
        caller=_text(values, "caller") or "all",
        key=_text(values, "key"),
        access=tuple(dict.fromkeys(access)),
        enabled=values["enabled"] if isinstance(values.get("enabled"), bool) else True,
    ), tuple(issues)


def load_addon_actions(folder: Path | str) -> tuple[tuple[AddonActionFile, ...], tuple[LoadIssue, ...]]:
    """Load the optional ``actions/*.toml`` catalogue for one addon."""
    root = Path(folder) / ADDON_ACTIONS_DIR
    if not root.is_dir():
        return (), ()
    actions: list[AddonActionFile] = []
    issues: list[LoadIssue] = []
    seen: set[str] = set()
    for path in sorted(root.glob("*.toml"), key=lambda item: item.name.casefold()):
        action, found = parse_addon_action_file(path)
        issues.extend(found)
        if action is None:
            continue
        if action.id in seen:
            issues.append(LoadIssue(str(path), "duplicate_id", f"Duplicate addon action id {action.id!r}."))
            continue
        seen.add(action.id)
        actions.append(action)
    return tuple(actions), tuple(issues)
