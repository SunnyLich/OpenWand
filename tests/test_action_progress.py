"""Tests for the shared truthful action-progress state machine."""

from __future__ import annotations

import pytest

from core.actions.progress import ActionProgress, ActionProgressStage


def test_action_progress_is_monotonic_replaceable_and_content_free() -> None:
    updates = []
    telemetry = []
    progress = ActionProgress(
        "vscode.code_change",
        app="vscode",
        sink=updates.append,
        telemetry=telemetry.append,
    )

    first = progress.advance(ActionProgressStage.READING, " Reading   the saved file... ")
    second = progress.advance(ActionProgressStage.PLANNING, "Drafting the exact change...")
    final = progress.advance(ActionProgressStage.COMPLETE, "Change applied and verified.")

    assert [item.stage for item in updates] == ["reading", "planning", "complete"]
    assert [item.sequence for item in updates] == [1, 2, 3]
    assert first.text == "Reading the saved file..."
    assert second.to_dict()["action_id"] == "vscode.code_change"
    assert final.terminal is True
    assert telemetry == updates
    assert not any("prompt" in item.to_dict() for item in updates)


def test_action_progress_refuses_regression_or_updates_after_terminal() -> None:
    progress = ActionProgress("calc.add_chart", app="libreoffice_calc", sink=lambda _update: None)
    progress.advance(ActionProgressStage.VALIDATING, "Checking the chart operation...")

    with pytest.raises(ValueError, match="cannot move backwards"):
        progress.advance(ActionProgressStage.READING, "Reading again...")

    progress.advance(ActionProgressStage.FAILED, "The action stopped safely.")
    with pytest.raises(RuntimeError, match="already terminal"):
        progress.advance(ActionProgressStage.COMPLETE, "Done.")
