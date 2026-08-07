"""Comment-preserving Settings edits for a live callers tree."""

from __future__ import annotations

import re
import shutil
import time
import tomllib
from pathlib import Path
from typing import Any

from core.action_files.loader import CALLER_FILE, CALLERS_FILE, KEYS_FILE

_ASSIGNMENT = re.compile(
    r'^(?P<indent>\s*)(?P<key>"(?:\\.|[^"])*"|[A-Za-z0-9_.-]+)(?P<space>\s*)=(?P<rest>.*)$'
)
_BARE_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _toml_key(value: str) -> str:
    return value if _BARE_KEY.fullmatch(value) else _toml_string(value)


def _assignment_key(match: re.Match[str]) -> str:
    raw = match.group("key")
    if not raw.startswith('"'):
        return raw
    try:
        return next(iter(tomllib.loads(f"{raw} = true")))
    except (StopIteration, tomllib.TOMLDecodeError):
        return raw.strip('"')


def _literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    return _toml_string(str(value))


def _comment_suffix(text: str) -> str:
    """Return an inline TOML comment without mistaking hashes inside strings."""
    quote = ""
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if char in {'"', "'"}:
            quote = "" if quote == char else char if not quote else quote
            continue
        if char == "#" and not quote:
            return " " + text[index:].strip()
    return ""


def update_toml_values(
    path: Path,
    updates: dict[str, Any],
    *,
    section: str = "",
    remove: set[str] | None = None,
) -> None:
    """Surgically update keys in one TOML table while retaining comments."""
    source = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    lines = source.splitlines()
    wanted = dict(updates)
    remove = set(remove or ())
    active = section == ""
    section_seen = active
    insert_at = len(lines)
    output: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if active:
                insert_at = len(output)
            active = stripped == f"[{section}]" if section else False
            section_seen = section_seen or active
        match = _ASSIGNMENT.match(line) if active else None
        key = _assignment_key(match) if match else ""
        if key in remove:
            continue
        if key in wanted and match is not None:
            suffix = _comment_suffix(match.group("rest"))
            output.append(
                f"{match.group('indent')}{_toml_key(key)}{match.group('space')}= "
                f"{_literal(wanted.pop(key))}{suffix}"
            )
            continue
        output.append(line)
    if active:
        insert_at = len(output)
    additions = [f"{_toml_key(key)} = {_literal(value)}" for key, value in wanted.items()]
    if additions:
        if not section_seen and section:
            if output and output[-1].strip():
                output.append("")
            output.append(f"[{section}]")
            output.extend(additions)
        else:
            output[insert_at:insert_at] = additions
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")
    return slug or fallback


def _unique_name(folder: Path, label: str) -> str:
    base = _slug(label, "action")
    name = base
    index = 2
    while (folder / f"{name}.toml").exists():
        name = f"{base}_{index}"
        index += 1
    return name


def _trash(root: Path, target: Path) -> None:
    if not target.exists():
        return
    destination = root / ".trash" / time.strftime("%Y%m%d-%H%M%S") / target.relative_to(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(target), str(destination))


def _write_keys(path: Path, actions: list[dict[str, Any]]) -> None:
    source = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    suffixes: dict[str, str] = {}
    for line in source.splitlines():
        match = _ASSIGNMENT.match(line)
        if match is None:
            continue
        try:
            parsed = tomllib.loads(line)
        except tomllib.TOMLDecodeError:
            continue
        value = parsed.get(_assignment_key(match))
        if isinstance(value, str):
            suffixes[value] = _comment_suffix(match.group("rest"))
    comments = [line for line in source.splitlines() if not _ASSIGNMENT.match(line)]
    bindings = [
        (
            f"{str(item.get('key') or '').strip().casefold()} = "
            f"{_toml_string(str(item['name']))}{suffixes.get(str(item['name']), '')}"
        )
        for item in actions
        if str(item.get("key") or "").strip()
    ]
    path.write_text("\n".join([*comments, *bindings]).rstrip() + "\n", encoding="utf-8")


def _updated_block(lines: list[str], updates: dict[str, Any]) -> list[str]:
    wanted = dict(updates)
    output: list[str] = []
    for line in lines:
        match = _ASSIGNMENT.match(line)
        key = _assignment_key(match) if match else ""
        if match is not None and key in wanted:
            suffix = _comment_suffix(match.group("rest"))
            output.append(
                f"{match.group('indent')}{_toml_key(key)}{match.group('space')}= "
                f"{_literal(wanted.pop(key))}{suffix}"
            )
        else:
            output.append(line)
    output.extend(f"{_toml_key(key)} = {_literal(value)}" for key, value in wanted.items())
    return output


def _table_keys(path: Path, section: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        values = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    table = values.get(section)
    return set(table) if isinstance(table, dict) else set()


def _write_callers_manifest(root: Path, callers: list[dict[str, Any]]) -> None:
    """Rewrite caller order while preserving comments in retained blocks."""
    path = root / CALLERS_FILE
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    starts = [index for index, line in enumerate(lines) if line.strip() == "[[callers]]"]
    prefix = lines[: starts[0]] if starts else ["# Which folder opens on which hotkey, in the order they are shown.", ""]
    blocks: dict[str, list[str]] = {}
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = lines[start:end]
        try:
            parsed = tomllib.loads("\n".join(block))
            entries = parsed.get("callers") if isinstance(parsed, dict) else None
            folder = str(entries[0].get("folder") or "") if isinstance(entries, list) and entries else ""
        except tomllib.TOMLDecodeError:
            folder = ""
        if folder:
            blocks[folder] = block

    output = list(prefix)
    if output and output[-1].strip():
        output.append("")
    for caller in callers:
        folder = str(caller["folder"])
        block = blocks.get(folder, ["[[callers]]"])
        output.extend(
            _updated_block(
                block,
                {
                    "folder": folder,
                    "hotkey": str(caller.get("hotkey") or ""),
                    "hotkey_2": str(caller.get("hotkey_2") or ""),
                    "enabled": bool(caller.get("enabled", True)),
                },
            )
        )
        if output and output[-1].strip():
            output.append("")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def save_callers(root: Path, callers: list[dict[str, Any]]) -> None:
    """Persist Settings' caller model into files, retaining user comments."""
    root.mkdir(parents=True, exist_ok=True)
    existing_folders = {
        path.name for path in root.iterdir() if path.is_dir() and path.name not in {"app", ".trash"}
    }
    used_folders: set[str] = set()
    manifest_callers: list[dict[str, Any]] = []
    for index, caller in enumerate(callers, 1):
        folder_name = str(caller.get("folder") or "").strip()
        if not folder_name:
            folder_name = _slug(str(caller.get("label") or ""), f"caller_{index}")
        base_name = folder_name
        suffix = 2
        while folder_name in used_folders:
            folder_name = f"{base_name}_{suffix}"
            suffix += 1
        used_folders.add(folder_name)
        folder = root / folder_name
        folder.mkdir(parents=True, exist_ok=True)
        manifest_callers.append({**caller, "folder": folder_name})
        update_toml_values(
            folder / CALLER_FILE,
            {
                "label": str(caller.get("label") or folder_name),
                "paste_back": bool(caller.get("paste_back")),
                "custom_key": str(caller.get("custom_key") or "s"),
                "custom_label": str(caller.get("custom_label") or ""),
                "space_starts_new_chat": bool(caller.get("space_starts_new_chat", True)),
                "file_access": str(caller.get("file_access") or "off"),
            },
        )
        caller_path = folder / CALLER_FILE
        update_toml_values(caller_path, dict(caller.get("context") or {}), section="context")
        tools = {str(key): str(value) for key, value in dict(caller.get("tools") or {}).items()}
        update_toml_values(
            caller_path,
            tools,
            section="tools",
            remove=_table_keys(caller_path, "tools") - set(tools),
        )

        actions = list(caller.get("actions") or [])
        for action in actions:
            name = str(action.get("name") or "").strip()
            if not name:
                name = _unique_name(folder, str(action.get("label") or ""))
                action["name"] = name
            path = folder / f"{name}.toml"
            if bool(action.get("preserve_template")):
                update_toml_values(path, {"enabled": bool(action.get("enabled", True))})
            else:
                updates = {
                    "label": str(action.get("label") or name),
                    "prompt": str(action.get("prompt") or ""),
                    "enabled": bool(action.get("enabled", True)),
                }
                if not path.exists():
                    updates["access"] = list(action.get("access") or ["text"])
                if action.get("hint"):
                    updates["hint"] = str(action.get("hint") or "")
                update_toml_values(path, updates)
        # Only remove actions that the editor actually loaded and the user
        # explicitly deleted.  Unknown or temporarily-invalid TOML files remain
        # untouched so opening Settings cannot destroy hand-authored work.
        for removed_name in caller.get("removed_actions") or []:
            path = folder / f"{removed_name}.toml"
            _trash(root, path)
            script = path.with_suffix(".py")
            if script.exists():
                _trash(root, script)
        _write_keys(folder / KEYS_FILE, actions)

    for folder_name in existing_folders - used_folders:
        _trash(root, root / folder_name)
    _write_callers_manifest(root, manifest_callers)


__all__ = ["save_callers", "update_toml_values"]
