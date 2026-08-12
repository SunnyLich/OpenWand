"""Closed, versioned capabilities for reviewed presentation edits."""

from __future__ import annotations

from core.actions.contracts import ActionCapability, ActionRisk
from core.actions.registry import ActionRegistry

CREATE_SLIDE = "presentation.create_slide@1"
RESTYLE_SLIDE = "presentation.restyle_slide@1"
UPSERT_SPEAKER_NOTES = "presentation.upsert_speaker_notes@1"

LAYOUT_PRESETS = ("title_body", "section_header", "two_column", "blank")
STYLE_PRESETS = ("clean_light", "clean_dark", "executive_blue", "warm_minimal")


def presentation_capabilities(backend: str = "") -> tuple[ActionCapability, ...]:
    """Return bounded operations supported by the selected official API surface."""
    capabilities = (
        ActionCapability(
            type=CREATE_SLIDE,
            app="presentation",
            title="Create slide",
            description="Create one slide from exact reviewed title and body text.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "maxLength": 200},
                    "body": {"type": "string", "maxLength": 8_000},
                    "layout": {"type": "string", "enum": list(LAYOUT_PRESETS)},
                    "position": {"type": "string", "enum": ["after_selected", "end"]},
                },
                "required": ["title", "body", "layout", "position"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=RESTYLE_SLIDE,
            app="presentation",
            title="Restyle selected slide",
            description="Apply one OpenWand-owned visual preset while preserving slide content.",
            input_schema={
                "type": "object",
                "properties": {
                    "slide_id": {"type": "string", "maxLength": 200},
                    "preset": {"type": "string", "enum": list(STYLE_PRESETS)},
                    "preserve_content": {"type": "boolean"},
                },
                "required": ["slide_id", "preset", "preserve_content"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=UPSERT_SPEAKER_NOTES,
            app="presentation",
            title="Add or update speaker notes",
            description="Set the exact reviewed speaker notes on the selected slide.",
            input_schema={
                "type": "object",
                "properties": {
                    "slide_id": {"type": "string", "maxLength": 200},
                    "notes": {"type": "string", "maxLength": 12_000},
                },
                "required": ["slide_id", "notes"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )
    # PowerPoint's currently documented Office.js surface does not expose a
    # supported speaker-notes mutation. Never offer a tool the bridge cannot
    # execute truthfully. Desktop COM and Google Slides REST support all three.
    if backend == "powerpoint_officejs":
        return tuple(item for item in capabilities if item.type != UPSERT_SPEAKER_NOTES)
    return capabilities


def presentation_registry() -> ActionRegistry:
    """Return a fresh allow-list for presentation plan validation."""
    return ActionRegistry(presentation_capabilities())
