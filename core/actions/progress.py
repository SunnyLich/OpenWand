"""Truthful, user-visible progress state for preview-first app actions."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ActionProgressStage(StrEnum):
    """Ordered public stages shared by every action adapter."""

    TARGETING = "targeting"
    READING = "reading"
    PLANNING = "planning"
    VALIDATING = "validating"
    PREPARING_PREVIEW = "preparing_preview"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"


_ORDER = {
    ActionProgressStage.TARGETING: 10,
    ActionProgressStage.READING: 20,
    ActionProgressStage.PLANNING: 30,
    ActionProgressStage.VALIDATING: 40,
    ActionProgressStage.PREPARING_PREVIEW: 50,
    ActionProgressStage.AWAITING_APPROVAL: 60,
    ActionProgressStage.APPLYING: 70,
    ActionProgressStage.VERIFYING: 80,
    ActionProgressStage.COMPLETE: 90,
    ActionProgressStage.CANCELLED: 90,
    ActionProgressStage.FAILED: 90,
}
_TERMINAL = {
    ActionProgressStage.COMPLETE,
    ActionProgressStage.CANCELLED,
    ActionProgressStage.FAILED,
}


@dataclass(frozen=True, slots=True)
class ActionProgressUpdate:
    """One content-free progress update suitable for UI IPC and telemetry."""

    action_id: str
    app: str
    stage: str
    text: str
    sequence: int
    terminal: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionProgress:
    """Enforce monotonic action stages and publish one replaceable status line."""

    def __init__(
        self,
        action_id: str,
        *,
        app: str,
        sink: Callable[[ActionProgressUpdate], None],
        telemetry: Callable[[ActionProgressUpdate], None] | None = None,
    ) -> None:
        self.action_id = str(action_id)
        self.app = str(app)
        self._sink = sink
        self._telemetry = telemetry
        self._stage: ActionProgressStage | None = None
        self._sequence = 0
        self._lock = threading.Lock()

    @property
    def stage(self) -> ActionProgressStage | None:
        with self._lock:
            return self._stage

    def advance(self, stage: ActionProgressStage | str, text: str) -> ActionProgressUpdate:
        next_stage = ActionProgressStage(stage)
        clean_text = " ".join(str(text or "").split()).strip()
        if not clean_text:
            raise ValueError("action progress text is required")
        with self._lock:
            if self._stage in _TERMINAL:
                raise RuntimeError("action progress is already terminal")
            if self._stage is not None and _ORDER[next_stage] < _ORDER[self._stage]:
                raise ValueError(f"action progress cannot move backwards: {self._stage} -> {next_stage}")

            self._stage = next_stage
            self._sequence += 1
            update = ActionProgressUpdate(
                action_id=self.action_id,
                app=self.app,
                stage=next_stage.value,
                text=clean_text,
                sequence=self._sequence,
                terminal=next_stage in _TERMINAL,
            )
        if self._telemetry is not None:
            self._telemetry(update)
        self._sink(update)
        return update


__all__ = ["ActionProgress", "ActionProgressStage", "ActionProgressUpdate"]
