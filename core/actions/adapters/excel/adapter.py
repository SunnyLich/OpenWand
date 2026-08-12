"""Preview-first execution through the active Windows Excel object model."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Any

from core.actions.adapters.excel.capabilities import (
    ADD_CHART,
    CLEAN_RANGE,
    CREATE_TABLE,
    SORT_RANGE,
    excel_capabilities,
    excel_registry,
)
from core.actions.adapters.excel.plans import (
    _reviewed_cleanup_changes,
    sort_column_index,
    sorted_excel_values,
    valid_excel_object_name,
)
from core.actions.adapters.excel.preview import render_excel_preview
from core.actions.adapters.excel.snapshot import ExcelSnapshot, capture_excel_snapshot
from core.actions.contracts import (
    ActionCapability,
    ActionExecutionResult,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ValidationIssue,
)
from core.actions.errors import ActionUnavailableError, ActionValidationError

ApplicationProvider = Callable[[], Any]

_CHART_TYPES = {
    "column": 51,  # xlColumnClustered
    "line": 4,  # xlLine
    "bar": 57,  # xlBarClustered
    "pie": 5,  # xlPie
}


class ExcelActionAdapter:
    """Inspect, preview, and mutate only the active desktop Excel target."""

    def __init__(self, application_provider: ApplicationProvider | None = None) -> None:
        self._application_provider = application_provider or _active_excel_application
        self._registry = excel_registry()
        self._idempotent_results: dict[str, ActionExecutionResult] = {}

    def detect(self) -> bool:
        """Return whether a running Excel instance has an active workbook."""
        try:
            application = self._application_provider()
            return getattr(application, "ActiveWorkbook", None) is not None
        except Exception:
            return False

    def capabilities(self) -> tuple[ActionCapability, ...]:
        """Return only action types this executor can actually perform."""
        return excel_capabilities()

    def snapshot(self) -> ExcelSnapshot:
        """Read the active target without changing Excel."""
        return capture_excel_snapshot(self._application_provider())

    def validate(self, plan: ActionPlan, snapshot: ExcelSnapshot) -> tuple[ValidationIssue, ...]:
        """Validate contracts, freshness, safe names, and dependency ordering."""
        issues = list(self._registry.validate_plan(plan))
        if plan.app != "excel":
            issues.append(ValidationIssue("wrong_adapter", "The Excel adapter can only run Excel plans."))
        if plan.target.locator != snapshot.target.locator:
            issues.append(
                ValidationIssue("target_changed", "The active workbook, worksheet, or selection has changed.")
            )
        if plan.target.version != snapshot.fingerprint:
            issues.append(ValidationIssue("target_stale", "The selected Excel data has changed since the preview."))

        for operation in plan.operations:
            name = operation.args.get("name")
            if isinstance(name, str) and not valid_excel_object_name(name):
                issues.append(
                    ValidationIssue("unsafe_object_name", f"Unsafe Excel object name: {name!r}.", operation.id)
                )
            if operation.type == CREATE_TABLE and isinstance(name, str):
                if name.casefold() in {item.casefold() for item in snapshot.table_names}:
                    issues.append(
                        ValidationIssue("table_exists", f"An Excel table named {name!r} already exists.", operation.id)
                    )
            if operation.type == ADD_CHART and isinstance(name, str):
                if name.casefold() in {item.casefold() for item in snapshot.chart_names}:
                    issues.append(
                        ValidationIssue("chart_exists", f"An Excel chart named {name!r} already exists.", operation.id)
                    )
            if operation.type == SORT_RANGE:
                try:
                    sort_column_index(snapshot, str(operation.args.get("column_header") or ""))
                    sorted_excel_values(
                        snapshot,
                        column_header=str(operation.args.get("column_header") or ""),
                        direction=str(operation.args.get("direction") or ""),
                    )
                except ValueError as exc:
                    issues.append(ValidationIssue("invalid_sort", str(exc), operation.id))
            if operation.type == CLEAN_RANGE:
                if str(operation.args.get("range") or "") != snapshot.selection_address:
                    issues.append(
                        ValidationIssue("cleanup_range_changed", "The reviewed cleanup range no longer matches.", operation.id)
                    )
                    continue
                changes = operation.args.get("changes")
                if not isinstance(changes, (list, tuple)):
                    issues.append(
                        ValidationIssue("invalid_cleanup", "Cleanup changes must be a structured list.", operation.id)
                    )
                    continue
                try:
                    expected = _reviewed_cleanup_changes(snapshot, changes)
                except ValueError as exc:
                    issues.append(ValidationIssue("invalid_cleanup", str(exc), operation.id))
                else:
                    if tuple(changes) != expected:
                        issues.append(
                            ValidationIssue(
                                "cleanup_snapshot_mismatch",
                                "A cleanup cell no longer matches the exact reviewed before-content.",
                                operation.id,
                            )
                        )
        issues.extend(_dependency_issues(plan.operations))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: ExcelSnapshot) -> ActionPreview:
        """Render the exact plan only after deterministic validation passes."""
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_excel_preview(plan, snapshot)

    def execute(
        self,
        plan: ActionPlan,
        *,
        confirmed: bool,
        idempotency_key: str,
    ) -> ActionExecutionResult:
        """Execute a fresh, confirmed plan once and verify created Excel objects."""
        if plan.requires_confirmation and not confirmed:
            raise ActionValidationError(
                (ValidationIssue("confirmation_required", "Review and confirm the Excel preview before applying."),)
            )
        if not idempotency_key.strip():
            raise ActionValidationError(
                (ValidationIssue("idempotency_required", "An idempotency key is required before applying."),)
            )
        cached = self._idempotent_results.get(idempotency_key)
        if cached is not None:
            return cached

        application = self._application_provider()
        current = capture_excel_snapshot(application)
        issues = self.validate(plan, current)
        if issues:
            raise ActionValidationError(issues)

        worksheet = application.ActiveSheet
        created: list[dict[str, str]] = []
        journal: list[dict[str, Any]] = []
        verified: list[str] = []
        for operation in _ordered_operations(plan.operations):
            if operation.type == CREATE_TABLE:
                table = self._create_table(worksheet, operation)
                name = str(table.Name)
                created.append({"kind": "table", "name": name})
                journal.append(
                    {
                        "kind": "table",
                        "name": name,
                        "worksheet": current.worksheet_name,
                        "rollback": "not_supported",
                    }
                )
            elif operation.type == ADD_CHART:
                chart = self._add_chart(worksheet, operation)
                name = str(chart.Name)
                created.append({"kind": "chart", "name": name})
                journal.append(
                    {
                        "kind": "chart",
                        "name": name,
                        "worksheet": current.worksheet_name,
                        "rollback": "delete_created_object",
                    }
                )
            elif operation.type == SORT_RANGE:
                expected = sorted_excel_values(
                    current,
                    column_header=str(operation.args["column_header"]),
                    direction=str(operation.args["direction"]),
                )
                self._sort_range(worksheet, current, operation)
                after = capture_excel_snapshot(application)
                if after.values != expected:
                    _restore_excel_snapshot(application, worksheet, current)
                    raise RuntimeError("Excel did not retain the exact reviewed row order.")
                header = str(operation.args["column_header"])
                created.append({"kind": "sorted_range", "name": current.selection_address})
                journal.append(
                    {
                        "kind": "sorted_range",
                        "name": current.selection_address,
                        "worksheet": current.worksheet_name,
                        "rollback": "verified_snapshot_restore_on_failure",
                    }
                )
                verified.append(f"Verified complete-row sort by {header}.")
            elif operation.type == CLEAN_RANGE:
                changes = tuple(operation.args["changes"])
                applied = 0
                try:
                    source = worksheet.Range(current.selection_address)
                    for change in changes:
                        cell = _range_cell(source, int(change["row_offset"]) + 1, int(change["column_offset"]) + 1)
                        _write_excel_cell(cell, str(change["after_kind"]), change.get("after_value"))
                        applied += 1
                    after = capture_excel_snapshot(application)
                    if not _cleanup_readback_matches(current, after, changes):
                        raise RuntimeError("Excel did not retain the exact reviewed cleanup contents.")
                except Exception:
                    try:
                        _restore_excel_snapshot(application, worksheet, current)
                    except Exception as restore_error:
                        raise RuntimeError(
                            "Excel cleanup verification failed and OpenWand could not restore the captured range."
                        ) from restore_error
                    raise
                created.append({"kind": "cleaned_range", "name": current.selection_address})
                journal.append(
                    {
                        "kind": "cell_cleanup",
                        "name": current.selection_address,
                        "worksheet": current.worksheet_name,
                        "writes": applied,
                        "rollback": "verified_snapshot_restore_on_failure",
                    }
                )
                verified.append(f"Verified {applied} exact cell replacement{'s' if applied != 1 else ''}.")
            else:
                raise ActionValidationError(
                    (ValidationIssue("unsupported_action", f"Unsupported action type: {operation.type}."),)
                )

        object_changes = [item for item in created if item["kind"] in {"table", "chart"}]
        verified.extend(self._verify_created(worksheet, object_changes))
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message=f"Applied {len(created)} Excel change{'s' if len(created) != 1 else ''}.",
            created=tuple(created),
            journal=tuple(journal),
            verification=tuple(verified),
        )
        self._idempotent_results[idempotency_key] = result
        return result

    @staticmethod
    def _create_table(worksheet: Any, operation: ActionOperation) -> Any:
        source_range = worksheet.Range(str(operation.args["range"]))
        header_mode = 1 if bool(operation.args["has_headers"]) else 2
        table = worksheet.ListObjects.Add(
            SourceType=1,
            Source=source_range,
            XlListObjectHasHeaders=header_mode,
        )
        table.Name = str(operation.args["name"])
        return table

    @staticmethod
    def _add_chart(worksheet: Any, operation: ActionOperation) -> Any:
        source_name = str(operation.args["source"])
        source = _table_range(worksheet.ListObjects, source_name)
        if source is None:
            source = worksheet.Range(source_name)

        chart_objects = worksheet.ChartObjects()
        chart_object = chart_objects.Add(
            float(getattr(source, "Left", 0.0)) + float(getattr(source, "Width", 420.0)) + 24.0,
            float(getattr(source, "Top", 0.0)),
            480.0,
            280.0,
        )
        chart_object.Name = str(operation.args["name"])
        chart = chart_object.Chart
        # Use the first column as categories and only numeric columns as
        # series. Passing a mixed table directly can make Excel select the last
        # text column as a zero-valued series while still retaining a chart
        # object, which is not meaningful verification.
        chart.SetSourceData(_numeric_chart_source(worksheet, source), 2)  # xlColumns
        chart.ChartType = _CHART_TYPES[str(operation.args["kind"])]
        title = str(operation.args.get("title") or "").strip()
        if title:
            chart.HasTitle = True
            chart.ChartTitle.Text = title
        return chart_object

    @staticmethod
    def _sort_range(worksheet: Any, snapshot: ExcelSnapshot, operation: ActionOperation) -> None:
        source = worksheet.Range(snapshot.selection_address)
        column_index = sort_column_index(snapshot, str(operation.args["column_header"])) + 1
        columns = getattr(source, "Columns", None)
        if columns is None:
            raise RuntimeError("Excel did not expose the selected range columns.")
        key_range = columns(column_index) if callable(columns) else columns.Item(column_index)
        order = 1 if str(operation.args["direction"]).casefold() == "ascending" else 2
        source.Sort(Key1=key_range, Order1=order, Header=1, Orientation=1)

    @staticmethod
    def _verify_created(worksheet: Any, created: list[dict[str, str]]) -> tuple[str, ...]:
        table_names = {name.casefold() for name in _collection_names(worksheet.ListObjects)}
        chart_names = {name.casefold() for name in _collection_names(worksheet.ChartObjects())}
        verified: list[str] = []
        for item in created:
            names = table_names if item["kind"] == "table" else chart_names
            if item["name"].casefold() not in names:
                raise RuntimeError(f"Excel did not retain the created {item['kind']} {item['name']!r}.")
            verified.append(f"Verified {item['kind']} {item['name']}.")
        return tuple(verified)


def _active_excel_application() -> Any:
    """Attach to desktop Excel without launching a new instance."""
    if sys.platform != "win32":
        raise ActionUnavailableError("The first Excel action adapter is available on Windows only.")
    try:
        import pythoncom  # type: ignore[import-not-found]
        import win32com.client  # type: ignore[import-not-found]

        pythoncom.CoInitialize()
        return win32com.client.GetActiveObject("Excel.Application")
    except Exception as exc:
        raise ActionUnavailableError("Open Excel and select the range you want OpenWand to use.") from exc


def _table_range(collection: Any, name: str) -> Any | None:
    """Resolve a table by case-insensitive name without accepting model code."""
    for index in range(1, int(getattr(collection, "Count", 0) or 0) + 1):
        item = collection.Item(index)
        if str(item.Name).casefold() == name.casefold():
            return item.Range
    return None


def _numeric_chart_source(worksheet: Any, source: Any) -> Any:
    """Return categories plus numeric series from one rectangular range."""
    values = getattr(source, "Value2", None)
    if not isinstance(values, tuple) or len(values) < 2:
        return source
    rows = tuple(row if isinstance(row, tuple) else (row,) for row in values)
    if not rows or len(rows[0]) < 2:
        return source
    width = len(rows[0])
    numeric_columns = []
    for column in range(1, width):
        data = [row[column] for row in rows[1:] if len(row) > column]
        nonempty = [value for value in data if value not in (None, "")]
        if nonempty and all(isinstance(value, int | float) and not isinstance(value, bool) for value in nonempty):
            numeric_columns.append(column)
    if not numeric_columns:
        return source
    first_row = int(getattr(source, "Row", 1) or 1)
    first_column = int(getattr(source, "Column", 1) or 1)
    last_row = first_row + len(rows) - 1
    columns = (0, *numeric_columns)
    areas = [
        f"{_column_name(first_column + offset)}{first_row}:{_column_name(first_column + offset)}{last_row}"
        for offset in columns
    ]
    return worksheet.Range(",".join(areas))


def _column_name(index: int) -> str:
    """Return a one-based Excel column name without using the active sheet."""
    if index < 1:
        raise ValueError("Excel column indices are one-based.")
    result = ""
    value = index
    while value:
        value, remainder = divmod(value - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _collection_names(collection: Any) -> tuple[str, ...]:
    """Return names from a one-based Excel collection."""
    return tuple(
        str(collection.Item(index).Name)
        for index in range(1, int(getattr(collection, "Count", 0) or 0) + 1)
    )


def _range_cell(source: Any, row: int, column: int) -> Any:
    cells = getattr(source, "Cells", None)
    if cells is None:
        raise RuntimeError("Excel did not expose cells inside the reviewed range.")
    return cells(row, column) if callable(cells) else cells.Item(row, column)


def _write_excel_cell(cell: Any, kind: str, value: Any) -> None:
    if kind == "formula":
        try:
            cell.Formula2 = value
        except Exception:
            cell.Formula = value
    else:
        cell.Value2 = value


def _cleanup_readback_matches(
    before: ExcelSnapshot,
    after: ExcelSnapshot,
    changes: tuple[dict[str, Any], ...],
) -> bool:
    if before.target.locator != after.target.locator:
        return False
    changed = {(int(item["row_offset"]), int(item["column_offset"])): item for item in changes}
    for row in range(before.row_count):
        for column in range(before.column_count):
            change = changed.get((row, column))
            if change is None:
                if before.formulas[row][column] != after.formulas[row][column]:
                    return False
                if not before.formulas[row][column] and before.values[row][column] != after.values[row][column]:
                    return False
            elif change["after_kind"] == "formula":
                if after.formulas[row][column] != change["after_value"]:
                    return False
            elif after.formulas[row][column] or after.values[row][column] != change["after_value"]:
                return False
    return True


def _restore_excel_snapshot(application: Any, worksheet: Any, snapshot: ExcelSnapshot) -> None:
    """Restore the exact captured range after a failed automation write."""
    source = worksheet.Range(snapshot.selection_address)
    has_formulas = any(formula for row in snapshot.formulas for formula in row)
    if has_formulas:
        matrix = tuple(
            tuple(
                snapshot.formulas[row][column] or snapshot.values[row][column]
                for column in range(snapshot.column_count)
            )
            for row in range(snapshot.row_count)
        )
        payload: Any = matrix[0][0] if snapshot.row_count == snapshot.column_count == 1 else matrix
        try:
            source.Formula2 = payload
        except Exception:
            source.Formula = payload
    else:
        payload = (
            snapshot.values[0][0]
            if snapshot.row_count == snapshot.column_count == 1
            else snapshot.values
        )
        source.Value2 = payload
    restored = capture_excel_snapshot(application)
    if restored.values != snapshot.values or restored.formulas != snapshot.formulas:
        raise RuntimeError("Excel did not restore the exact captured values and formulas.")


def _dependency_issues(operations: tuple[ActionOperation, ...]) -> tuple[ValidationIssue, ...]:
    """Reject dependency cycles before anything reaches Excel."""
    try:
        _ordered_operations(operations)
    except ValueError as exc:
        return (ValidationIssue("dependency_cycle", str(exc)),)
    return ()


def _ordered_operations(operations: tuple[ActionOperation, ...]) -> tuple[ActionOperation, ...]:
    """Return a stable topological order for the small action graph."""
    remaining = {operation.id: operation for operation in operations}
    completed: set[str] = set()
    ordered: list[ActionOperation] = []
    while remaining:
        ready = [
            operation
            for operation in operations
            if operation.id in remaining and set(operation.depends_on).issubset(completed)
        ]
        if not ready:
            raise ValueError("The action plan contains a dependency cycle.")
        for operation in ready:
            ordered.append(operation)
            completed.add(operation.id)
            remaining.pop(operation.id)
    return tuple(ordered)
