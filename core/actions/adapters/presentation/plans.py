"""Deterministic plan builders for reviewed presentation operations."""

from __future__ import annotations

import uuid

from core.actions.adapters.presentation.capabilities import (
    CREATE_SLIDE,
    RESTYLE_SLIDE,
    UPSERT_SPEAKER_NOTES,
)
from core.actions.adapters.presentation.snapshot import PresentationSnapshot
from core.actions.contracts import ActionOperation, ActionPlan, ActionRisk


def build_create_slide_plan(
    snapshot: PresentationSnapshot,
    *,
    title: str,
    body: str,
    layout: str = "title_body",
    position: str = "after_selected",
) -> ActionPlan:
    """Build a plan containing the exact reviewed new-slide content."""
    if position == "after_selected" and not snapshot.selected_slide_id:
        position = "end"
    return _one_operation_plan(
        snapshot,
        CREATE_SLIDE,
        {"title": title, "body": body, "layout": layout, "position": position},
        f"Create slide: {title or 'Untitled slide'}",
    )


def build_restyle_slide_plan(snapshot: PresentationSnapshot, *, preset: str) -> ActionPlan:
    """Build a content-preserving preset change for the selected slide."""
    if not snapshot.selected_slide_id:
        raise ValueError("Select one slide before asking OpenWand to restyle it.")
    return _one_operation_plan(
        snapshot,
        RESTYLE_SLIDE,
        {"slide_id": snapshot.selected_slide_id, "preset": preset, "preserve_content": True},
        f"Restyle selected slide with {preset.replace('_', ' ')}",
    )


def build_speaker_notes_plan(snapshot: PresentationSnapshot, *, notes: str) -> ActionPlan:
    """Build an exact speaker-notes replacement for the selected slide."""
    if not snapshot.selected_slide_id:
        raise ValueError("Select one slide before adding speaker notes.")
    return _one_operation_plan(
        snapshot,
        UPSERT_SPEAKER_NOTES,
        {"slide_id": snapshot.selected_slide_id, "notes": notes},
        "Add or update speaker notes",
    )


def _one_operation_plan(
    snapshot: PresentationSnapshot,
    operation_type: str,
    args: dict,
    summary: str,
) -> ActionPlan:
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="presentation",
        target=snapshot.target,
        summary=summary,
        operations=(ActionOperation(id="presentation_change", type=operation_type, args=args),),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )
