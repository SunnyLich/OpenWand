"""Immutable saved-file snapshot for a VS Code selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.actions.contracts import ActionTarget


@dataclass(frozen=True)
class VSCodeSnapshot:
    """Exact active file and selected range captured for one preview."""

    file_path: str
    display_name: str
    window_id: int
    pid: int
    text: str
    selected_text: str
    selection_start: int
    selection_end: int
    fingerprint: str
    selection_fingerprint: str
    has_utf8_bom: bool = False
    is_whole_file: bool = False

    @property
    def target(self) -> ActionTarget:
        return ActionTarget(
            app="vscode",
            display_name=self.display_name or Path(self.file_path).name,
            locator={
                "path": self.file_path,
                "window_id": str(self.window_id),
                "pid": str(self.pid),
                "start": str(self.selection_start),
                "end": str(self.selection_end),
                "selection_sha256": self.selection_fingerprint,
                "utf8_bom": "1" if self.has_utf8_bom else "0",
                "kind": "saved_empty_file" if self.is_whole_file else "saved_file",
            },
            version=self.fingerprint,
        )

    def to_selection_dict(self) -> dict[str, Any]:
        """Return the bounded IPC form consumed by the supervisor."""
        return {
            "app": "vscode",
            "file_path": self.file_path,
            "display_name": self.display_name,
            "window_id": self.window_id,
            "pid": self.pid,
            "text": self.text,
            "selected_text": self.selected_text,
            "selection_start": self.selection_start,
            "selection_end": self.selection_end,
            "fingerprint": self.fingerprint,
            "selection_fingerprint": self.selection_fingerprint,
            "has_utf8_bom": self.has_utf8_bom,
            "is_whole_file": self.is_whole_file,
        }

    @classmethod
    def from_selection(cls, value: dict[str, Any]) -> VSCodeSnapshot:
        """Build a validated snapshot from the native worker payload."""
        path = str(value.get("file_path") or "").strip()
        text = str(value.get("text") or "")
        selected = str(value.get("selected_text") or "")
        start = int(value.get("selection_start") or 0)
        end = int(value.get("selection_end") or 0)
        fingerprint = str(value.get("fingerprint") or "").strip()
        selection_fingerprint = str(value.get("selection_fingerprint") or "").strip()
        if not path or not fingerprint or not selection_fingerprint:
            raise ValueError("VS Code file identity is incomplete.")
        is_whole_file = bool(value.get("is_whole_file"))
        invalid_selection = (
            start < 0
            or end < start
            or end > len(text)
            or (not is_whole_file and (not selected.strip() or end <= start))
            or (is_whole_file and (text or selected or start != 0 or end != 0))
        )
        if invalid_selection:
            raise ValueError("VS Code needs one non-empty selected code block.")
        if text[start:end] != selected:
            raise ValueError("The selected code does not match the saved file snapshot.")
        return cls(
            file_path=path,
            display_name=str(value.get("display_name") or Path(path).name),
            window_id=int(value.get("window_id") or 0),
            pid=int(value.get("pid") or 0),
            text=text,
            selected_text=selected,
            selection_start=start,
            selection_end=end,
            fingerprint=fingerprint,
            selection_fingerprint=selection_fingerprint,
            has_utf8_bom=bool(value.get("has_utf8_bom")),
            is_whole_file=is_whole_file,
        )
