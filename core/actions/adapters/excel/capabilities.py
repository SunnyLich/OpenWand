"""Versioned capabilities initially exposed by the Excel adapter."""

from __future__ import annotations

from core.actions.contracts import ActionCapability, ActionRisk
from core.actions.registry import ActionRegistry

CREATE_TABLE = "excel.create_table@1"
ADD_CHART = "excel.add_chart@1"
SORT_RANGE = "excel.sort_range@1"
CLEAN_RANGE = "excel.clean_range@1"


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
        ActionCapability(
            type=SORT_RANGE,
            app="excel",
            title="Sort selected Excel rows",
            description=(
                "Sort the complete selected rows by one unique header while preserving every cell value."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "column_header": {"type": "string"},
                    "direction": {"type": "string", "enum": ["ascending", "descending"]},
                },
                "required": ["column_header", "direction"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=CLEAN_RANGE,
            app="excel",
            title="Apply reviewed cleanup",
            description=(
                "Apply an exact, reviewed set of cell replacements inside the captured range."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "range": {"type": "string"},
                    "changes": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 32,
                        "items": {
                            "type": "object",
                            "properties": {
                                "row_offset": {"type": "integer", "minimum": 0},
                                "column_offset": {"type": "integer", "minimum": 0},
                                "after_kind": {"type": "string", "enum": ["value", "formula"]},
                                "after_value": {},
                                "replace_formula": {"type": "boolean"},
                            },
                            "required": ["row_offset", "column_offset", "after_kind", "after_value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["changes"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )


def excel_registry() -> ActionRegistry:
    """Build the built-in Excel action registry."""
    return ActionRegistry(excel_capabilities())
