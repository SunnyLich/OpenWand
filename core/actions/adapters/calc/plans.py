"""Fast deterministic action plans for common LibreOffice Calc requests."""

from __future__ import annotations

import uuid

from core.actions.adapters.calc.capabilities import ADD_CHART, FORMAT_TABLE, SORT_RANGE
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
