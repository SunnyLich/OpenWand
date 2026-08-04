"""Build exact VS Code replacement plans from model output."""

from __future__ import annotations

import uuid

from core.actions.adapters.vscode.capabilities import REPLACE_FILE, REPLACE_SELECTION
from core.actions.adapters.vscode.snapshot import VSCodeSnapshot
from core.actions.contracts import ActionOperation, ActionPlan, ActionRisk


def build_replace_selection_plan(
    snapshot: VSCodeSnapshot,
    replacement_text: str,
    *,
    summary: str = "Fix the selected code",
) -> ActionPlan:
    """Create one immutable replacement plan for the captured file range."""
    if not str(replacement_text or "").strip():
        raise ValueError("The model returned an empty code replacement.")
    if len(replacement_text) > 24_000:
        raise ValueError("The first VS Code action supports replacements up to 24,000 characters.")
    if replacement_text == snapshot.selected_text:
        raise ValueError("The model did not propose a code change.")
    clean_summary = " ".join(str(summary or "").split())[:180] or "Fix the selected code"
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="vscode",
        target=snapshot.target,
        summary=clean_summary,
        operations=(
            ActionOperation(
                id="replace_selection",
                type=REPLACE_SELECTION,
                args={
                    "start": snapshot.selection_start,
                    "end": snapshot.selection_end,
                    "expected_selection_sha256": snapshot.selection_fingerprint,
                    "replacement_text": replacement_text,
                },
            ),
        ),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )


def build_replace_file_plan(
    snapshot: VSCodeSnapshot,
    replacement_text: str,
    *,
    summary: str = "Fill the empty saved file",
) -> ActionPlan:
    """Create an immutable whole-file insertion for an exact empty saved file."""
    if not snapshot.is_whole_file or snapshot.text:
        raise ValueError("This action requires an empty saved file.")
    if not str(replacement_text or "").strip():
        raise ValueError("The model returned empty file content.")
    if len(replacement_text) > 24_000:
        raise ValueError("The first VS Code action supports replacements up to 24,000 characters.")
    clean_summary = " ".join(str(summary or "").split())[:180] or "Fill the empty saved file"
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="vscode",
        target=snapshot.target,
        summary=clean_summary,
        operations=(
            ActionOperation(
                id="replace_file",
                type=REPLACE_FILE,
                args={
                    "expected_file_sha256": snapshot.fingerprint,
                    "replacement_text": replacement_text,
                },
            ),
        ),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )
