"""Conservative planning for independent Virtual Workspace file tasks.

This module does not start workers.  It only recognizes a deliberately small
objective format that a caller may safely opt into parallelizing.  Returning
``None`` means "run this objective normally".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>\S.*)\s*$")
_DEPENDENCY_RE = re.compile(
    r"\b(?:"
    r"after|before|then|depends?|depending|dependency|subsequently|finally|"
    r"once|based\s+on|derived\s+from|"
    r"using\s+(?:the\s+)?(?:output|result|contents?|data)\b|"
    r"from\s+(?:the\s+)?(?:output|result)\b|"
    r"when\s+.+\b(?:done|finished|complete[ds]?)\b"
    r")",
    re.IGNORECASE,
)
_SECOND_ACTION_RE = re.compile(
    r"(?:\band\b|;|\.)\s*(?:also\s+)?"
    r"(?:create|write|edit|update|generate|make|delete|remove|rename|move|copy)\b",
    re.IGNORECASE,
)
_PATH_TOKEN = r"[A-Za-z_][A-Za-z0-9_.-]*(?:/[A-Za-z_][A-Za-z0-9_.-]*)*"
_WRAPPED_PATH = rf"(?:`[^`]+`|'[^']+'|\"[^\"]+\"|{_PATH_TOKEN})"
_ACTION_RE = re.compile(
    rf"^(?:create|write|edit|update|generate|make)\s+(?:"
    rf"(?:a|an)\s+(?:new\s+)?file\s+(?:named|called)\s+(?P<named>{_WRAPPED_PATH})|"
    rf"(?:the\s+)?(?:file\s+)?(?P<direct>{_WRAPPED_PATH})"
    rf")(?:\s|$)",
    re.IGNORECASE,
)
_QUOTED_RE = re.compile(r"`([^`]+)`|'([^']+)'|\"([^\"]+)\"")
_BARE_FILENAME_RE = re.compile(
    rf"(?<![A-Za-z0-9_./:-])({_PATH_TOKEN}\.[A-Za-z][A-Za-z0-9_.-]*)(?![A-Za-z0-9_./-])"
)
_SAFE_PART_RE = re.compile(r"^[A-Za-z0-9_. -]+$")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class WorkspaceFileTask:
    """One independent objective with its exclusive workspace target."""

    objective: str
    target_path: str


def split_independent_workspace_objective(
    objective: str,
) -> tuple[WorkspaceFileTask, ...] | None:
    """Split a strict 2-6 item file checklist, or refuse with ``None``.

    Accepted input consists entirely of numbered or bulleted lines. Each line
    must begin with a file-writing verb and name exactly one safe relative file.
    This intentionally prefers false negatives over unsafe parallel work.
    """
    if not isinstance(objective, str) or "\x00" in objective:
        return None
    lines = [line for line in objective.splitlines() if line.strip()]
    if not 2 <= len(lines) <= 6:
        return None

    tasks: list[WorkspaceFileTask] = []
    seen_targets: set[str] = set()
    for line in lines:
        bullet = _BULLET_RE.fullmatch(line)
        if bullet is None:
            return None
        body = bullet.group("body").strip()
        if _DEPENDENCY_RE.search(body) or _SECOND_ACTION_RE.search(body):
            return None
        action = _ACTION_RE.match(body)
        if action is None:
            return None
        target = _action_target(action)
        if target is None:
            return None
        safe_target = _safe_relative_filename(target)
        if safe_target is None:
            return None

        mentioned = _mentioned_filenames(body)
        if len(mentioned) != 1 or mentioned[0].casefold() != safe_target.casefold():
            return None
        identity = safe_target.casefold()
        if identity in seen_targets:
            return None
        seen_targets.add(identity)
        tasks.append(WorkspaceFileTask(objective=body, target_path=safe_target))
    return tuple(tasks)


def _action_target(match: re.Match[str]) -> str | None:
    value = match.group("named") or match.group("direct")
    if not value:
        return None
    value = value.strip()
    if len(value) >= 2 and (value[0], value[-1]) in {("`", "`"), ("'", "'"), ('"', '"')}:
        value = value[1:-1].strip()
    return value or None


def _safe_relative_filename(value: str) -> str | None:
    if not value or len(value) > 240 or "\\" in value or ":" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or not 1 <= len(path.parts) <= 12:
        return None
    for part in path.parts:
        if (
            part in {"", ".", ".."}
            or not _SAFE_PART_RE.fullmatch(part)
            or part.endswith((" ", "."))
            or part.split(".", 1)[0].upper() in _WINDOWS_RESERVED
        ):
            return None
    name = path.name
    if name.startswith(".") or "." not in name or name.endswith("."):
        return None
    return path.as_posix()


def _mentioned_filenames(text: str) -> list[str]:
    """Extract explicit filename-like mentions without double-counting quotes."""
    found: list[tuple[int, str]] = []
    quoted_spans: list[tuple[int, int]] = []
    for match in _QUOTED_RE.finditer(text):
        quoted_spans.append(match.span())
        value = next((group for group in match.groups() if group is not None), "").strip()
        safe = _safe_relative_filename(value)
        if safe is not None:
            found.append((match.start(), safe))
    for match in _BARE_FILENAME_RE.finditer(text):
        if any(start <= match.start() < end for start, end in quoted_spans):
            continue
        safe = _safe_relative_filename(match.group(1))
        if safe is not None:
            found.append((match.start(), safe))
    return [value for _position, value in sorted(found)]


__all__ = ["WorkspaceFileTask", "split_independent_workspace_objective"]
