"""Deterministic plan builders for fast, common Excel requests."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Sequence
from typing import Any, cast

from core.actions.adapters.excel.capabilities import ADD_CHART, CLEAN_RANGE, CREATE_TABLE
from core.actions.adapters.excel.snapshot import ExcelSnapshot
from core.actions.contracts import ActionOperation, ActionPlan, ActionRisk


def build_table_chart_plan(
    snapshot: ExcelSnapshot,
    *,
    include_chart: bool = True,
    chart_kind: str = "column",
    chart_title: str = "",
) -> ActionPlan:
    """Build the first fast path without requiring a second model call."""
    table_name = _available_name("WispTable", snapshot.table_names)
    operations = [
        ActionOperation(
            id="create_table",
            type=CREATE_TABLE,
            args={
                "range": snapshot.selection_address,
                "name": table_name,
                "has_headers": True,
            },
        )
    ]
    if include_chart:
        operations.append(
            ActionOperation(
                id="add_chart",
                type=ADD_CHART,
                args={
                    "source": table_name,
                    "name": _available_name("WispChart", snapshot.chart_names),
                    "kind": chart_kind,
                    "title": chart_title or "Chart from selected data",
                },
                depends_on=("create_table",),
            )
        )
    summary = "Turn the selected range into a table"
    if include_chart:
        summary += f" and add a {chart_kind} chart"
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="excel",
        target=snapshot.target,
        summary=summary,
        operations=tuple(operations),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )


def build_cleanup_plan(
    snapshot: ExcelSnapshot,
    changes: Sequence[dict[str, Any]],
) -> ActionPlan:
    """Bind concrete cleanup proposals to exact captured Excel cell contents."""
    reviewed = _reviewed_cleanup_changes(snapshot, changes)
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="excel",
        target=snapshot.target,
        summary=f"Apply {len(reviewed)} reviewed cleanup change{'s' if len(reviewed) != 1 else ''}",
        operations=(
            ActionOperation(
                id="clean_range",
                type=CLEAN_RANGE,
                args={"range": snapshot.selection_address, "changes": reviewed},
            ),
        ),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )


def _reviewed_cleanup_changes(
    snapshot: ExcelSnapshot,
    changes: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if not snapshot.formula_capture_complete:
        raise ValueError("Excel must expose complete formula identity before cell cleanup can run.")
    if not 1 <= len(changes) <= 32:
        raise ValueError("Review between 1 and 32 cell cleanup changes at a time.")
    reviewed: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for proposal in changes:
        if not isinstance(proposal, dict):
            raise ValueError("Each cleanup change must be a structured cell proposal.")
        row = proposal.get("row_offset")
        column = proposal.get("column_offset")
        if (
            not isinstance(row, int)
            or isinstance(row, bool)
            or not isinstance(column, int)
            or isinstance(column, bool)
            or not 0 <= row < snapshot.row_count
            or not 0 <= column < snapshot.column_count
        ):
            raise ValueError("A cleanup change targets a cell outside the captured Excel range.")
        if (row, column) in seen:
            raise ValueError("A cell can appear only once in a reviewed cleanup plan.")
        seen.add((row, column))
        after_kind = str(proposal.get("after_kind") or "value").strip().casefold()
        after_value = proposal.get("after_value")
        _validate_after_content(after_kind, after_value)
        before_formula = snapshot.formulas[row][column]
        before_kind = "formula" if before_formula.startswith("=") else "value"
        before_value = before_formula if before_kind == "formula" else snapshot.values[row][column]
        replace_formula = proposal.get("replace_formula") is True
        if before_kind == "formula" and after_kind == "value" and not replace_formula:
            raise ValueError("Replacing a formula with a value must be explicitly reviewed.")
        if before_kind == after_kind and before_value == after_value:
            raise ValueError("A reviewed cleanup change must alter the captured cell content.")
        reviewed.append(
            {
                "row_offset": row,
                "column_offset": column,
                "before_kind": before_kind,
                "before_value": before_value,
                "after_kind": after_kind,
                "after_value": after_value,
                "replace_formula": replace_formula,
            }
        )
    return tuple(reviewed)


def _validate_after_content(kind: str, value: Any) -> None:
    if kind not in {"value", "formula"}:
        raise ValueError("Cleanup content must be a typed value or formula.")
    if kind == "formula":
        if not isinstance(value, str) or not value.startswith("=") or len(value) > 512:
            raise ValueError("A reviewed cleanup formula must start with '=' and be at most 512 characters.")
        return
    if not (value is None or isinstance(value, str | int | float | bool)):
        raise ValueError("A reviewed cleanup value must be a JSON scalar.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("A reviewed cleanup number must be finite.")
    if isinstance(value, str) and value.startswith("="):
        raise ValueError("Formula text must use the explicit formula content type.")
    if isinstance(value, str) and len(value) > 500:
        raise ValueError("A reviewed cleanup value is too long.")


def _available_name(prefix: str, existing_names: tuple[str, ...]) -> str:
    """Return a stable Excel object name that is not already in use."""
    existing = {name.casefold() for name in existing_names}
    if prefix.casefold() not in existing:
        return prefix
    index = 2
    while f"{prefix}{index}".casefold() in existing:
        index += 1
    return f"{prefix}{index}"


def valid_excel_object_name(name: str) -> bool:
    """Conservatively accept safe table/chart names generated by Wisp."""
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{0,254}", name))


def sort_column_index(snapshot: ExcelSnapshot, column_header: str) -> int:
    """Resolve one unique header to a zero-based column index."""
    if not snapshot.values:
        raise ValueError("The selected Excel range is empty.")
    wanted = str(column_header or "").strip().casefold()
    headers = [str(value or "").strip().casefold() for value in snapshot.values[0]]
    matches = [index for index, value in enumerate(headers) if value and value == wanted]
    if len(matches) != 1:
        raise ValueError("Choose one unique, non-empty header from the selected Excel range.")
    return matches[0]


def sorted_excel_values(
    snapshot: ExcelSnapshot,
    *,
    column_header: str,
    direction: str,
) -> tuple[tuple[object, ...], ...]:
    """Return the exact stable row order shown in preview and verified after Apply."""
    index = sort_column_index(snapshot, column_header)
    normalized_direction = str(direction or "").strip().casefold()
    if normalized_direction not in {"ascending", "descending"}:
        raise ValueError("Excel sort direction must be ascending or descending.")
    if len(snapshot.values) < 2:
        raise ValueError("Select a header row and at least one Excel data row.")

    rows = list(snapshot.values[1:])
    populated = [row for row in rows if row[index] not in (None, "")]
    empty = [row for row in rows if row[index] in (None, "")]
    values = [row[index] for row in populated]
    numeric_flags = [
        isinstance(value, int | float) and not isinstance(value, bool) for value in values
    ]
    if any(numeric_flags) and not all(numeric_flags):
        raise ValueError("Choose an Excel sort column containing one consistent value type.")
    numeric = bool(values) and all(numeric_flags)

    def key(row: tuple[object, ...]) -> float | str:
        value = row[index]
        return float(cast(int | float, value)) if numeric else str(value).casefold()

    populated.sort(key=key, reverse=normalized_direction == "descending")
    return (snapshot.values[0], *populated, *empty)
