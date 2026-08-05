"""Read one action's definition file.

An action is a pair: ``name.toml`` describes it, and an optional ``name.py``
beside it holds the code. The description file is data and contains nothing
runnable, so drawing a menu cannot execute anything — the guarantee comes from
the file format, not from this reader being careful.

The script is only imported when the action is actually chosen.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from core.action_files.contracts import Access, ActionFile, LoadIssue

ACTION_SUFFIX = ".toml"
SCRIPT_SUFFIX = ".py"

_STRING_FIELDS = ("label", "hint", "prompt", "capability", "planner", "template")
_LIST_FIELDS = ("context", "access")
_KNOWN_FIELDS = frozenset(
    (*_STRING_FIELDS, *_LIST_FIELDS, "paste_back", "run_script_first")
)


def _string(values: dict[str, Any], key: str) -> str:
    """Return one string field, or an empty string when absent."""
    value = values.get(key)
    return value.strip() if isinstance(value, str) else ""


def _optional_bool(values: dict[str, Any], key: str) -> bool | None:
    """Return one boolean field, or None when the file does not set it."""
    value = values.get(key)
    return bool(value) if isinstance(value, bool) else None


def script_for(path: Path) -> Path:
    """Return the script path that would pair with one action file."""
    return path.with_suffix(SCRIPT_SUFFIX)


def parse_action_file(path: Path | str) -> tuple[ActionFile | None, tuple[LoadIssue, ...]]:
    """Read one action file. Returns the action, or None plus the reasons why not."""
    target = Path(path)
    display = str(target)
    try:
        source = target.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return None, (LoadIssue(display, "unreadable", f"Could not read the file: {exc}"),)

    try:
        values = tomllib.loads(source)
    except tomllib.TOMLDecodeError as exc:
        return None, (LoadIssue(display, "bad_toml", f"This file is not valid TOML: {exc}"),)

    issues: list[LoadIssue] = []

    for key in sorted(set(values) - _KNOWN_FIELDS):
        issues.append(LoadIssue(display, "unknown_field", f"{key!r} is not an action setting."))
    for key in _STRING_FIELDS:
        if key in values and not isinstance(values[key], str):
            issues.append(LoadIssue(display, "wrong_type", f"{key} must be text."))
    for key in ("paste_back", "run_script_first"):
        if key in values and not isinstance(values[key], bool):
            issues.append(LoadIssue(display, "wrong_type", f"{key} must be true or false."))
    for key in _LIST_FIELDS:
        value = values.get(key)
        if key in values and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            issues.append(LoadIssue(display, "wrong_type", f"{key} must be a list of text values."))

    template = _string(values, "template")
    label = _string(values, "label")
    if not label and not template:
        issues.append(
            LoadIssue(display, "no_label", "An action needs a label, or a template for built-ins.")
        )

    access: list[Access] = []
    for item in values.get("access") or ():
        if not isinstance(item, str):
            continue
        try:
            access.append(Access(item.strip().casefold()))
        except ValueError:
            allowed = ", ".join(sorted(entry.value for entry in Access))
            issues.append(LoadIssue(display, "unknown_access", f"Unknown access {item!r}. Allowed: {allowed}."))

    context = tuple(
        item.strip() for item in (values.get("context") or ()) if isinstance(item, str) and item.strip()
    )
    prompt = _string(values, "prompt")
    capability = _string(values, "capability")
    planner = _string(values, "planner")

    script = script_for(target)
    has_code = script.is_file()

    if planner and not capability:
        issues.append(LoadIssue(display, "planner_without_capability", "planner needs a capability to plan for."))
    if capability and not planner:
        issues.append(LoadIssue(display, "capability_without_planner", "capability needs a planner to fill it in."))
    if _optional_bool(values, "run_script_first") is not None and not has_code:
        issues.append(
            LoadIssue(display, "no_script", f"run_script_first is set, but there is no {script.name}.")
        )
    if not prompt and not has_code and not capability and not template:
        issues.append(
            LoadIssue(display, "does_nothing", f"An action needs a prompt, a capability, or a {script.name}.")
        )

    if any(issue.code in {"no_label", "does_nothing"} for issue in issues):
        return None, tuple(issues)

    action = ActionFile(
        path=display,
        name=target.stem,
        label=label,
        hint=_string(values, "hint"),
        prompt=prompt,
        context=context,
        paste_back=_optional_bool(values, "paste_back"),
        run_script_first=bool(values.get("run_script_first")),
        access=tuple(dict.fromkeys(access)),
        capability=capability,
        planner=planner,
        has_code=has_code,
        script_path=str(script) if has_code else "",
        template=template,
    )
    return action, tuple(issues)
