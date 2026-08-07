"""Fast deterministic action plans for common LibreOffice Calc requests."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from typing import Any

from core.actions.adapters.calc.capabilities import ADD_CHART, CLEAN_RANGE, FORMAT_TABLE, SORT_RANGE
from core.actions.adapters.calc.snapshot import CalcSnapshot
from core.actions.contracts import ActionOperation, ActionPlan, ActionRisk


def build_chart_plan(snapshot: CalcSnapshot, *, title: str = "Chart from selected data") -> ActionPlan:
    """Build the first Calc action without waiting for another model request."""
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="libreoffice_calc",
        target=snapshot.target,
        summary=f"Add a vertical bar chart from {snapshot.selection_address}",
        operations=(
            ActionOperation(
                id="add_chart",
                type=ADD_CHART,
                args={
                    "range": snapshot.selection_address,
                    "kind": "column",
                    "title": title[:120],
                },
            ),
        ),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )


def build_cleanup_plan(
    snapshot: CalcSnapshot,
    changes: Sequence[dict[str, Any]],
) -> ActionPlan:
    """Bind concrete cleanup proposals to exact captured Calc cell contents."""
    reviewed = _reviewed_cleanup_changes(snapshot, changes)
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="libreoffice_calc",
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
    snapshot: CalcSnapshot,
    changes: Sequence[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
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
            raise ValueError("A cleanup change targets a cell outside the captured Calc range.")
        if (row, column) in seen:
            raise ValueError("A cell can appear only once in a reviewed cleanup plan.")
        seen.add((row, column))
        after_kind = str(proposal.get("after_kind") or "value").strip().casefold()
        after_value = proposal.get("after_value")
        _validate_after_content(after_kind, after_value)
        before_formula = snapshot.formulas[row][column]
        before_kind = "formula" if before_formula.startswith("=") else "value"
        before_value = before_formula if before_kind == "formula" else snapshot.typed_values[row][column]
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
    if isinstance(value, bool) or not (value is None or isinstance(value, str | int | float)):
        raise ValueError("A reviewed Calc cleanup value must be blank, text, or numeric.")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("A reviewed cleanup number must be finite.")
    if isinstance(value, str) and len(value) > 500:
        raise ValueError("A reviewed cleanup value is too long.")


def build_format_table_plan(snapshot: CalcSnapshot, *, has_header: bool = True) -> ActionPlan:
    """Build a bounded formatting plan that never changes cell contents."""
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="libreoffice_calc",
        target=snapshot.target,
        summary=f"Clean up the table in {snapshot.selection_address}",
        operations=(
            ActionOperation(
                id="format_table",
                type=FORMAT_TABLE,
                args={
                    "range": snapshot.selection_address,
                    "has_header": bool(has_header),
                    "preset": "clean_table",
                },
            ),
        ),
        risk=ActionRisk.LOW,
        requires_confirmation=True,
    )


def build_sort_range_plan(
    snapshot: CalcSnapshot,
    *,
    column_label: str,
    direction: str = "ascending",
) -> ActionPlan:
    """Build a row sort plan using an exact header from the captured range."""
    if snapshot.row_count < 2 or snapshot.column_count < 1:
        raise ValueError("Sorting requires a header row and at least one data row.")
    headers = [str(value).strip() for value in snapshot.values[0]]
    matches = [index for index, header in enumerate(headers) if header == str(column_label).strip()]
    if len(matches) != 1:
        raise ValueError("The sort column must match one unique selected header exactly.")
    normalized_direction = str(direction).strip().lower()
    if normalized_direction not in {"ascending", "descending"}:
        raise ValueError("Sort direction must be ascending or descending.")
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="libreoffice_calc",
        target=snapshot.target,
        summary=f"Sort {snapshot.selection_address} by {headers[matches[0]]} ({normalized_direction})",
        operations=(
            ActionOperation(
                id="sort_range",
                type=SORT_RANGE,
                args={
                    "range": snapshot.selection_address,
                    "column_index": matches[0],
                    "column_label": headers[matches[0]],
                    "direction": normalized_direction,
                    "has_header": True,
                },
            ),
        ),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )
