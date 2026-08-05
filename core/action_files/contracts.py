"""Serializable contracts for the action-file catalogue.

One action is a pair of files: ``name.toml`` describes it, and an optional
``name.py`` beside it holds the code. The description is pure data, so nothing
can run while a menu is being drawn; the script is imported only when the
action is chosen, behind its label and its confirm.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class Access(StrEnum):
    """Self-declared access shown as a coloured tag beside an action.

    Nothing is enforced. The label describes what an honest file does; a file
    that lies is not prevented from lying. See private/ACTION_FILES_PLAN.md.
    """

    TEXT = "text"
    FILES = "files"
    INTERNET = "internet"
    PROGRAMS = "programs"


#: Severity order, lowest first. A row shows the highest colour it declares.
ACCESS_SEVERITY: dict[Access, int] = {
    Access.TEXT: 0,
    Access.FILES: 1,
    Access.INTERNET: 1,
    Access.PROGRAMS: 2,
}

#: Colour shown for each severity level.
ACCESS_COLOUR: dict[int, str] = {0: "green", 1: "amber", 2: "red"}

#: The overlay's numbered context toggles, in the order they are painted.
#: Callers store their state keyed by id, never by position, so a number
#: always means the same source. A caller that switches only some of them on
#: leaves gaps in the numbering rather than sliding the rest up.
CONTEXT_SOURCES: tuple[str, ...] = (
    "ambient",
    "browser",
    "selection",
    "clipboard",
    "screenshot",
    "github",
    "memory",
    "files",
)


@dataclass(frozen=True)
class LoadIssue:
    """One problem found while reading the catalogue.

    Issues never raise. A broken file is reported and skipped so one bad
    action cannot stop the menu from being drawn.
    """

    path: str
    code: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible issue."""
        return asdict(self)


@dataclass(frozen=True)
class ActionFile:
    """One action, read from a single Python file without executing it."""

    path: str
    name: str
    label: str
    hint: str = ""
    prompt: str = ""
    context: tuple[str, ...] = ()
    #: None means "use the caller's setting"; the file only overrides when set.
    paste_back: bool | None = None
    run_script_first: bool = False
    access: tuple[Access, ...] = ()
    capability: str = ""
    planner: str = ""
    #: True when a script file sits beside this action's .toml.
    has_code: bool = False
    script_path: str = ""
    template: str = ""

    @property
    def severity(self) -> int:
        """Return the highest access severity this action declares."""
        return max((ACCESS_SEVERITY[item] for item in self.access), default=0)

    @property
    def colour(self) -> str:
        """Return the colour for this action's access tag."""
        return ACCESS_COLOUR[self.severity]

    @property
    def runs_in_process(self) -> bool:
        """Return whether this action can run inline on the UI side.

        Prompt-only actions carry no code, so there is nothing to isolate and
        no reason to pay for starting a process.
        """
        return not self.has_code

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible action for IPC and the picker."""
        value = asdict(self)
        value["access"] = [item.value for item in self.access]
        value["colour"] = self.colour
        value["severity"] = self.severity
        return value


@dataclass(frozen=True)
class BoundAction:
    """One action as it appears in a menu, with its assigned letter.

    ``key`` is empty for a file present in the folder but absent from
    keys.json. Those still appear and stay clickable.
    """

    key: str
    action: ActionFile

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible bound action."""
        return {"key": self.key, "action": self.action.to_dict()}


@dataclass(frozen=True)
class CallerDef:
    """One caller folder: a hotkey, its settings, and its actions."""

    folder: str
    hotkey: str = ""
    hotkey_2: str = ""
    label: str = ""
    enabled: bool = True
    settings: dict[str, Any] = field(default_factory=dict)
    actions: tuple[BoundAction, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible caller."""
        return {
            "folder": self.folder,
            "hotkey": self.hotkey,
            "hotkey_2": self.hotkey_2,
            "label": self.label,
            "enabled": self.enabled,
            "settings": dict(self.settings),
            "actions": [item.to_dict() for item in self.actions],
        }


@dataclass(frozen=True)
class AppMatch:
    """What an app folder looks for in the captured foreground window."""

    process: tuple[str, ...] = ()
    title: tuple[str, ...] = ()
    url: tuple[str, ...] = ()

    def matches(self, surface: dict[str, Any]) -> bool:
        """Return whether this matcher owns the captured surface.

        Any single hit wins. Process names compare whole, title and url
        compare as substrings, and everything is case-insensitive.
        """
        process = str(surface.get("process_name") or "").strip().casefold()
        if process and process in self.process:
            return True
        title = str(surface.get("title") or surface.get("name") or "").casefold()
        if title and any(needle in title for needle in self.title):
            return True
        url = str(surface.get("browser_url") or surface.get("url") or "").casefold()
        return bool(url) and any(needle in url for needle in self.url)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible matcher."""
        return asdict(self)


@dataclass(frozen=True)
class AppDef:
    """One app folder: what it matches, and the actions it contributes."""

    folder: str
    display_name: str
    match: AppMatch
    actions: tuple[BoundAction, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible app definition."""
        return {
            "folder": self.folder,
            "display_name": self.display_name,
            "match": self.match.to_dict(),
            "actions": [item.to_dict() for item in self.actions],
        }


@dataclass(frozen=True)
class ActionCatalog:
    """Everything read from one callers/ tree."""

    root: str
    callers: tuple[CallerDef, ...] = ()
    apps: tuple[AppDef, ...] = ()
    issues: tuple[LoadIssue, ...] = ()

    def detect_app(self, surface: dict[str, Any] | None) -> AppDef | None:
        """Return the app folder owning the captured surface, if any."""
        value = surface if isinstance(surface, dict) else {}
        for app in self.apps:
            if app.match.matches(value):
                return app
        return None

    def caller(self, folder: str) -> CallerDef | None:
        """Return one caller folder by name."""
        return next((item for item in self.callers if item.folder == folder), None)

    def menu_for(self, folder: str, surface: dict[str, Any] | None = None) -> tuple[BoundAction, ...]:
        """Return the rows shown when this caller opens over that surface.

        The caller's own actions come first and keep their letters. An app
        action whose letter is already taken is still shown, without one, so
        an assigned key never changes meaning depending on the focused app.
        """
        caller = self.caller(folder)
        if caller is None:
            return ()
        rows = list(caller.actions)
        app = self.detect_app(surface)
        if app is None:
            return tuple(rows)
        taken = {item.key for item in rows if item.key}
        for item in app.actions:
            key = "" if item.key in taken else item.key
            if key:
                taken.add(key)
            rows.append(BoundAction(key=key, action=item.action))
        return tuple(rows)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible catalogue."""
        return {
            "root": self.root,
            "callers": [item.to_dict() for item in self.callers],
            "apps": [item.to_dict() for item in self.apps],
            "issues": [item.to_dict() for item in self.issues],
        }
