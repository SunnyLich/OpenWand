"""Shared-runner provider for the active desktop Excel workbook."""

from __future__ import annotations

import uuid
from typing import Any

from core.actions.adapters.excel.adapter import ExcelActionAdapter
from core.actions.adapters.excel.capabilities import ADD_CHART, CLEAN_RANGE, CREATE_TABLE, SORT_RANGE
from core.actions.adapters.excel.plans import build_cleanup_plan, sorted_excel_values
from core.actions.contracts import (
    ActionCapability,
    ActionExecutionResult,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ValidationIssue,
)


class ExcelRuntimeProvider:
    """Adapt Excel's object model to the invariant ActionRunner hooks."""

    id = "excel"
    app = "excel"
    display_name = "Microsoft Excel"

    def __init__(self, adapter: ExcelActionAdapter | None = None) -> None:
        self._adapter = adapter or ExcelActionAdapter()

    @staticmethod
    def detects(context: dict[str, Any]) -> bool:
        active = context.get("active_app")
        app = active if isinstance(active, dict) else context
        process = str(app.get("process_name") or "").strip().casefold()
        bundle = str(app.get("bundle_id") or "").strip().casefold()
        return process in {"excel.exe", "microsoft excel", "excel"} or bundle == "com.microsoft.excel"

    def snapshot(self, context: dict[str, Any]) -> Any:
        del context
        return self._adapter.snapshot()

    def capabilities(self, snapshot: Any) -> tuple[ActionCapability, ...]:
        del snapshot
        return self._adapter.capabilities()

    @staticmethod
    def answer_context(snapshot: Any) -> dict[str, Any]:
        """Return bounded structured selection data for read-only app prompts."""
        return {
            "app": "excel",
            "document_name": snapshot.workbook_name,
            "sheet_name": snapshot.worksheet_name,
            "selection_address": snapshot.selection_address,
            "row_count": snapshot.row_count,
            "column_count": snapshot.column_count,
            "displayed_values": [list(row) for row in snapshot.context_display_values],
            "formulas": [list(row) for row in snapshot.context_formulas],
            "formula_context": snapshot.formula_context(),
            "selected_text": snapshot.selected_text(),
            "fingerprint": snapshot.fingerprint,
        }

    @staticmethod
    def planner_context(snapshot: Any) -> dict[str, Any]:
        answer_context = ExcelRuntimeProvider.answer_context(snapshot)
        return {
            **answer_context,
            # Preserve the established typed-action planning field names.
            "workbook": snapshot.workbook_name,
            "worksheet": snapshot.worksheet_name,
            "selection": snapshot.selection_address,
            "values": [list(row) for row in snapshot.preview_values],
            "table_names": list(snapshot.table_names),
            "chart_names": list(snapshot.chart_names),
        }

    @staticmethod
    def build_plan(
        capability: ActionCapability,
        arguments: dict[str, Any],
        snapshot: Any,
        visible_text: str,
    ) -> ActionPlan:
        del visible_text
        if capability.type == CREATE_TABLE:
            summary = f"Create Excel table {arguments.get('name') or ''}".strip()
        elif capability.type == ADD_CHART:
            summary = f"Create {arguments.get('kind') or 'column'} chart {arguments.get('name') or ''}".strip()
        elif capability.type == SORT_RANGE:
            header = str(arguments.get("column_header") or "").strip()
            direction = str(arguments.get("direction") or "ascending").strip().casefold()
            sorted_excel_values(snapshot, column_header=header, direction=direction)
            if direction not in {"ascending", "descending"}:
                raise ValueError("Excel sort direction must be ascending or descending.")
            summary = f"Sort the selected rows by {header} ({direction})"
        elif capability.type == CLEAN_RANGE:
            changes = arguments.get("changes")
            if not isinstance(changes, (list, tuple)):
                raise ValueError("Excel cleanup requires concrete structured cell changes.")
            return build_cleanup_plan(snapshot, changes)
        else:
            raise ValueError("This Excel operation is not registered.")
        return ActionPlan(
            plan_id=uuid.uuid4().hex,
            app="excel",
            target=snapshot.target,
            summary=summary,
            operations=(
                ActionOperation(
                    id=capability.type.split(".", 1)[1].split("@", 1)[0],
                    type=capability.type,
                    args=dict(arguments),
                ),
            ),
            risk=capability.risk,
            requires_confirmation=True,
        )

    def validate(self, plan: ActionPlan, snapshot: Any) -> tuple[ValidationIssue, ...]:
        return self._adapter.validate(plan, snapshot)

    def render_preview(self, plan: ActionPlan, snapshot: Any) -> ActionPreview:
        return self._adapter.render_preview(plan, snapshot)

    def execute(
        self,
        plan: ActionPlan,
        *,
        confirmed: bool,
        idempotency_key: str,
    ) -> ActionExecutionResult:
        return self._adapter.execute(plan, confirmed=confirmed, idempotency_key=idempotency_key)

    @staticmethod
    def verify(plan: ActionPlan, result: ActionExecutionResult) -> tuple[ValidationIssue, ...]:
        del plan
        if result.status != "applied" or not result.verification:
            return (ValidationIssue("unverified_result", "Excel did not return a verified result."),)
        return ()

    @staticmethod
    def rollback(plan: ActionPlan, result: ActionExecutionResult) -> ActionExecutionResult | None:
        del plan, result
        # The current adapter reports partial reversibility in its preview and
        # never promises rollback for table creation.
        return None


__all__ = ["ExcelRuntimeProvider"]
