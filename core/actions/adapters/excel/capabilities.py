"""Versioned capabilities initially exposed by the Excel adapter."""

from __future__ import annotations

from core.actions.contracts import ActionCapability, ActionRisk
from core.actions.registry import ActionRegistry

CREATE_TABLE = "excel.create_table@1"
ADD_CHART = "excel.add_chart@1"


def excel_capabilities() -> tuple[ActionCapability, ...]:
    """Return the allow-listed operations the first Excel adapter supports."""
    return (
        ActionCapability(
            type=CREATE_TABLE,
            app="excel",
            title="Create Excel table",
            description="Turn one range in the active worksheet into an Excel table.",
            input_schema={
                "type": "object",
                "properties": {
                    "range": {"type": "string"},
                    "name": {"type": "string"},
                    "has_headers": {"type": "boolean"},
                },
                "required": ["range", "name", "has_headers"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=False,
        ),
        ActionCapability(
            type=ADD_CHART,
            app="excel",
            title="Add Excel chart",
            description="Create a chart using a range or table in the active worksheet.",
            input_schema={
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": ["column", "line", "bar", "pie"]},
                    "title": {"type": "string"},
                },
                "required": ["source", "name", "kind", "title"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )


def excel_registry() -> ActionRegistry:
    """Build the built-in Excel action registry."""
    return ActionRegistry(excel_capabilities())
