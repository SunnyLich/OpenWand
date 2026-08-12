"""Versioned LibreOffice Calc capabilities implemented by OpenWand."""

from __future__ import annotations

from core.actions.contracts import ActionCapability, ActionRisk

ADD_CHART = "calc.add_chart@1"
FORMAT_TABLE = "calc.format_table@1"
SORT_RANGE = "calc.sort_range@1"
CLEAN_RANGE = "calc.clean_range@1"


def calc_capabilities() -> tuple[ActionCapability, ...]:
    """Return the Calc operations the background accessibility adapter supports."""
    return (
        ActionCapability(
            type=ADD_CHART,
            app="libreoffice_calc",
            title="Add chart",
            description="Add a vertical bar chart from the currently selected cell range.",
            input_schema={
                "type": "object",
                "required": ["range", "kind", "title"],
                "properties": {
                    "range": {"type": "string"},
                    "kind": {"const": "column"},
                    "title": {"type": "string", "maxLength": 120},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=FORMAT_TABLE,
            app="libreoffice_calc",
            title="Clean up table",
            description="Format the selected cells as a readable table without changing their values or number formats.",
            input_schema={
                "type": "object",
                "required": ["range", "has_header", "preset"],
                "properties": {
                    "range": {"type": "string"},
                    "has_header": {"type": "boolean"},
                    "preset": {"const": "clean_table"},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.LOW,
            reversible=True,
        ),
        ActionCapability(
            type=SORT_RANGE,
            app="libreoffice_calc",
            title="Sort rows",
            description="Sort the selected rows by one exact selected column while keeping each row together.",
            input_schema={
                "type": "object",
                "required": ["range", "column_index", "column_label", "direction", "has_header"],
                "properties": {
                    "range": {"type": "string"},
                    "column_index": {"type": "integer", "minimum": 0},
                    "column_label": {"type": "string"},
                    "direction": {"type": "string", "enum": ["ascending", "descending"]},
                    "has_header": {"const": True},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=CLEAN_RANGE,
            app="libreoffice_calc",
            title="Apply reviewed cleanup",
            description=(
                "Apply an exact, reviewed set of cell replacements inside the captured range."
            ),
            input_schema={
                "type": "object",
                "required": ["changes"],
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
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )
