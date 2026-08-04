"""Private, content-free timing traces for preview-first app actions."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_TRACE_PATH_ENV = "WISP_ACTION_TRACE_PATH"
_MAX_TRACE_BYTES = 5 * 1024 * 1024
_TRACE_BACKUPS = 3
_WRITE_LOCK = threading.Lock()


def _iso_time(unix_ns: int) -> str:
    return datetime.fromtimestamp(unix_ns / 1_000_000_000, tz=UTC).isoformat(timespec="milliseconds")


def _rotate_if_needed(path: Path) -> None:
    try:
        if path.stat().st_size < _MAX_TRACE_BYTES:
            return
    except OSError:
        return
    oldest = path.with_suffix(path.suffix + f".{_TRACE_BACKUPS}")
    oldest.unlink(missing_ok=True)
    for index in range(_TRACE_BACKUPS - 1, 0, -1):
        source = path.with_suffix(path.suffix + f".{index}")
        if source.exists():
            source.replace(path.with_suffix(path.suffix + f".{index + 1}"))
    path.replace(path.with_suffix(path.suffix + ".1"))


def _persist_event(event: dict[str, Any]) -> None:
    raw_path = str(os.environ.get(_TRACE_PATH_ENV) or "").strip()
    if not raw_path:
        return
    path = Path(raw_path).expanduser()
    line = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with _WRITE_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(path)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError:
            # Diagnostics are best-effort. A locked or unwritable log must never
            # prevent a reviewed application action from running.
            return


class ActionTrace:
    """Write one structured event per action stage without recording user content."""

    def __init__(
        self,
        action: str,
        *,
        app: str,
        started_unix_ns: int = 0,
        sink: Callable[[dict[str, Any]], None] | None = None,
        trace_id: str = "",
    ) -> None:
        self.trace_id = trace_id or uuid.uuid4().hex
        self.action = str(action)
        self.app = str(app)
        self.started_unix_ns = int(started_unix_ns or time.time_ns())
        self._sink = sink or _persist_event
        self._sequence = 0
        self._finished = False
        self.mark_at("started", self.started_unix_ns)

    def mark(self, stage: str, **fields: Any) -> dict[str, Any]:
        return self.mark_at(stage, time.time_ns(), **fields)

    def mark_at(self, stage: str, unix_ns: int, **fields: Any) -> dict[str, Any]:
        when = int(unix_ns or time.time_ns())
        self._sequence += 1
        event = {
            "schema": "wisp.action_trace@1",
            "trace_id": self.trace_id,
            "seq": self._sequence,
            "action": self.action,
            "app": self.app,
            "stage": str(stage),
            "at": _iso_time(when),
            "elapsed_ms": round(max(0, when - self.started_unix_ns) / 1_000_000, 3),
        }
        event.update(fields)
        self._sink(event)
        return event

    def finish(self, status: str, **fields: Any) -> dict[str, Any]:
        if self._finished:
            return {}
        self._finished = True
        return self.mark("finished", status=str(status), **fields)
