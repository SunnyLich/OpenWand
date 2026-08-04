"""Tests for private action timing telemetry."""

from __future__ import annotations

import json
from pathlib import Path

from core.actions.telemetry import ActionTrace


def test_action_trace_persists_content_free_stage_events(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "action-timings.jsonl"
    monkeypatch.setenv("WISP_ACTION_TRACE_PATH", str(path))
    trace = ActionTrace(
        "vscode.code_change",
        app="vscode",
        started_unix_ns=1_800_000_000_000_000_000,
        trace_id="trace-1",
    )
    trace.mark_at(
        "model_completed",
        1_800_000_001_250_000_000,
        replacement_chars=91,
    )
    trace.finish("applied", verification_count=3)

    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [event["stage"] for event in events] == ["started", "model_completed", "finished"]
    assert events[1]["elapsed_ms"] == 1250.0
    assert events[-1]["status"] == "applied"
    serialized = path.read_text(encoding="utf-8")
    assert "prompt" not in serialized
    assert "replacement_text" not in serialized


def test_action_trace_can_use_an_in_memory_sink() -> None:
    events: list[dict] = []
    trace = ActionTrace("calc.add_chart", app="libreoffice_calc", sink=events.append)
    trace.mark("preview_raised_topmost", operation_count=1)
    trace.finish("cancelled")
    trace.finish("applied")

    assert [event["stage"] for event in events] == ["started", "preview_raised_topmost", "finished"]
    assert events[-1]["status"] == "cancelled"


def test_unwritable_trace_path_never_blocks_an_action(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WISP_ACTION_TRACE_PATH", str(tmp_path))

    trace = ActionTrace("calc.add_chart", app="libreoffice_calc")
    trace.finish("applied")
