"""Contract and fake-object-model tests for the first Excel action slice."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.actions.adapters.excel import ExcelActionAdapter, ExcelRuntimeProvider, build_table_chart_plan
from core.actions.adapters.excel.capabilities import ADD_CHART, SORT_RANGE, excel_registry
from core.actions.contracts import ActionOperation
from core.actions.errors import ActionValidationError
from ui.addon_presentations import sanitize_presentation_html


class _Count:
    def __init__(self, count: int) -> None:
        self.Count = count


class FakeRange:
    def __init__(self, address: str, values: tuple[tuple[object, ...], ...]) -> None:
        self._address = address
        self._values = values
        self.Value2 = values[0][0] if len(values) == 1 and len(values[0]) == 1 else values
        self.Rows = _Count(len(values))
        self.Columns = _Count(len(values[0]))
        self.Left = 12.0
        self.Top = 18.0
        self.Width = 320.0
        self.Row = 1
        self.Column = 1
        self.Columns = _FakeRangeColumns(self)

    def Address(self, _row_absolute: bool, _column_absolute: bool) -> str:
        return self._address

    def Sort(self, **kwargs: object) -> None:
        key_range = kwargs["Key1"]
        assert isinstance(key_range, _FakeColumnRange)
        column_index = key_range.column_index - 1
        reverse = int(kwargs["Order1"]) == 2
        header, *rows = self._values
        numeric = all(
            isinstance(row[column_index], int | float) and not isinstance(row[column_index], bool)
            for row in rows
            if row[column_index] not in (None, "")
        )

        def key(row: tuple[object, ...]) -> float | str:
            value = row[column_index]
            return float(value) if numeric else str(value).casefold()

        populated = [row for row in rows if row[column_index] not in (None, "")]
        empty = [row for row in rows if row[column_index] in (None, "")]
        self._values = (header, *sorted(populated, key=key, reverse=reverse), *empty)
        self.Value2 = self._values


class _FakeColumnRange:
    def __init__(self, column_index: int) -> None:
        self.column_index = column_index


class _FakeRangeColumns:
    def __init__(self, source: FakeRange) -> None:
        self._source = source

    def __call__(self, column_index: int) -> _FakeColumnRange:
        assert 1 <= column_index <= self._source.Columns.Count
        return _FakeColumnRange(column_index)

    @property
    def Count(self) -> int:
        return self._source.Columns.Count if self._source.Columns is not self else len(self._source._values[0])


class FakeListObject:
    def __init__(self, source_range: FakeRange) -> None:
        self.Name = "Table1"
        self.Range = source_range


class FakeListObjects:
    def __init__(self) -> None:
        self._items: list[FakeListObject] = []

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, index: int) -> FakeListObject:
        return self._items[index - 1]

    def Add(self, **kwargs: object) -> FakeListObject:
        item = FakeListObject(kwargs["Source"])  # type: ignore[arg-type]
        self._items.append(item)
        return item


class FakeChartTitle:
    Text = ""


class FakeChart:
    def __init__(self) -> None:
        self.ChartType = 0
        self.HasTitle = False
        self.ChartTitle = FakeChartTitle()
        self.source: FakeRange | None = None
        self.plot_by = 0

    def SetSourceData(self, source: FakeRange, plot_by: int) -> None:
        self.source = source
        self.plot_by = plot_by


class FakeChartObject:
    def __init__(self) -> None:
        self.Name = "Chart 1"
        self.Chart = FakeChart()


class FakeChartObjects:
    def __init__(self) -> None:
        self._items: list[FakeChartObject] = []

    @property
    def Count(self) -> int:
        return len(self._items)

    def Item(self, index: int) -> FakeChartObject:
        return self._items[index - 1]

    def Add(self, _left: float, _top: float, _width: float, _height: float) -> FakeChartObject:
        item = FakeChartObject()
        self._items.append(item)
        return item


class FakeWorksheet:
    def __init__(self, selection: FakeRange) -> None:
        self.Name = "Sales"
        self.ListObjects = FakeListObjects()
        self._charts = FakeChartObjects()
        self._selection = selection
        self.requested_ranges: list[str] = []

    def Range(self, address: str) -> FakeRange:
        self.requested_ranges.append(address)
        assert address in {self._selection._address, "A1:A3,B1:B3"}
        return self._selection

    def ChartObjects(self) -> FakeChartObjects:
        return self._charts


class FakeWorksheets:
    def __init__(self, worksheet: FakeWorksheet) -> None:
        self._worksheet = worksheet
        self.Count = 1

    def Item(self, _index: int) -> FakeWorksheet:
        return self._worksheet


class FakeWorkbook:
    def __init__(self, worksheet: FakeWorksheet) -> None:
        self.Name = "Q2 Sales.xlsx"
        self.FullName = r"C:\Work\Q2 Sales.xlsx"
        self.Worksheets = FakeWorksheets(worksheet)


class FakeExcel:
    def __init__(self) -> None:
        self.Selection = FakeRange(
            "A1:C3",
            (
                ("Month", "Revenue", "Region"),
                ("Jan", 1200, "West"),
                ("Feb", 1700, "East"),
            ),
        )
        self.ActiveSheet = FakeWorksheet(self.Selection)
        self.ActiveWorkbook = FakeWorkbook(self.ActiveSheet)
        self._undo_values = self.Selection._values
        self.undo_count = 0

    def Undo(self) -> None:
        self.undo_count += 1
        self.Selection._values = self._undo_values
        self.Selection.Value2 = self._undo_values


def test_excel_preview_uses_real_snapshot_without_mutating_excel() -> None:
    excel = FakeExcel()
    adapter = ExcelActionAdapter(lambda: excel)

    snapshot = adapter.snapshot()
    plan = build_table_chart_plan(snapshot, chart_title="Revenue by month")
    preview = adapter.render_preview(plan, snapshot)

    assert "action-focus-preview" in preview.html
    assert "Nothing has changed" not in preview.html
    assert sanitize_presentation_html(preview.html) == preview.html
    assert "Q2 Sales.xlsx" in preview.html
    assert "Month" in preview.html
    assert len(preview.details) == 2
    assert excel.ActiveSheet.ListObjects.Count == 0
    assert excel.ActiveSheet.ChartObjects().Count == 0


def test_excel_execute_creates_table_and_chart_once_then_verifies() -> None:
    excel = FakeExcel()
    adapter = ExcelActionAdapter(lambda: excel)
    plan = build_table_chart_plan(adapter.snapshot(), chart_title="Revenue by month")

    result = adapter.execute(plan, confirmed=True, idempotency_key="apply-1")
    repeated = adapter.execute(plan, confirmed=True, idempotency_key="apply-1")

    assert result is repeated
    assert result.status == "applied"
    assert result.created == (
        {"kind": "table", "name": "WispTable"},
        {"kind": "chart", "name": "WispChart"},
    )
    assert len(result.verification) == 2
    assert excel.ActiveSheet.ListObjects.Count == 1
    assert excel.ActiveSheet.ChartObjects().Count == 1
    assert excel.ActiveSheet.ChartObjects().Item(1).Chart.ChartType == 51
    assert excel.ActiveSheet.ChartObjects().Item(1).Chart.plot_by == 2
    assert "A1:A3,B1:B3" in excel.ActiveSheet.requested_ranges
    assert excel.ActiveSheet.ChartObjects().Item(1).Chart.ChartTitle.Text == "Revenue by month"


def test_excel_execute_requires_confirmation() -> None:
    excel = FakeExcel()
    adapter = ExcelActionAdapter(lambda: excel)
    plan = build_table_chart_plan(adapter.snapshot())

    with pytest.raises(ActionValidationError, match="confirm"):
        adapter.execute(plan, confirmed=False, idempotency_key="apply-1")

    assert excel.ActiveSheet.ListObjects.Count == 0


def test_excel_execute_rejects_selection_changed_after_preview() -> None:
    excel = FakeExcel()
    adapter = ExcelActionAdapter(lambda: excel)
    plan = build_table_chart_plan(adapter.snapshot())
    excel.Selection.Value2 = (
        ("Month", "Revenue", "Region"),
        ("Jan", 9999, "West"),
        ("Feb", 1700, "East"),
    )

    with pytest.raises(ActionValidationError, match="changed since the preview"):
        adapter.execute(plan, confirmed=True, idempotency_key="apply-1")

    assert excel.ActiveSheet.ListObjects.Count == 0


def test_registry_rejects_unknown_arguments_and_dependency_cycles() -> None:
    excel = FakeExcel()
    adapter = ExcelActionAdapter(lambda: excel)
    plan = build_table_chart_plan(adapter.snapshot())
    first = replace(plan.operations[0], args={**plan.operations[0].args, "macro": "run me"})
    second = replace(plan.operations[1], depends_on=("create_table", "add_chart"))
    unsafe = replace(plan, operations=(first, second))

    issues = adapter.validate(unsafe, adapter.snapshot())

    assert {issue.code for issue in issues} >= {"unknown_argument", "self_dependency", "dependency_cycle"}


def test_registry_requires_versioned_action_types() -> None:
    registry = excel_registry()
    capability = registry.capabilities_for("excel")[0]

    with pytest.raises(ValueError, match="invalid action type"):
        registry.register(replace(capability, type="excel.raw_vba"))


def test_registry_rejects_model_invented_operation() -> None:
    excel = FakeExcel()
    adapter = ExcelActionAdapter(lambda: excel)
    plan = build_table_chart_plan(adapter.snapshot(), include_chart=False)
    invented = replace(
        plan,
        operations=(ActionOperation(id="macro", type="excel.run_vba@1", args={"code": "..."}),),
    )

    issues = adapter.validate(invented, adapter.snapshot())

    assert any(issue.code == "unsupported_action" for issue in issues)


def test_excel_snapshot_accepts_late_bound_address_property() -> None:
    excel = FakeExcel()
    excel.Selection.Address = "$A$1:$C$3"

    snapshot = ExcelActionAdapter(lambda: excel).snapshot()

    assert snapshot.selection_address == "A1:C3"


def test_excel_runtime_provider_builds_previews_and_verifies_execution() -> None:
    excel = FakeExcel()
    provider = ExcelRuntimeProvider(ExcelActionAdapter(lambda: excel))
    context = {"active_app": {"process_name": "EXCEL.EXE", "name": "Q2 Sales.xlsx - Excel"}}

    assert provider.detects(context)
    snapshot = provider.snapshot(context)
    capability = next(item for item in provider.capabilities(snapshot) if item.type == ADD_CHART)
    plan = provider.build_plan(
        capability,
        {"source": "A1:C3", "name": "WispChart", "kind": "column", "title": "Revenue"},
        snapshot,
        "",
    )
    preview = provider.render_preview(plan, snapshot)

    assert preview.plan_id == plan.plan_id
    assert excel.ActiveSheet.ChartObjects().Count == 0
    result = provider.execute(plan, confirmed=True, idempotency_key="runtime-chart")
    assert provider.verify(plan, result) == ()
    assert excel.ActiveSheet.ChartObjects().Count == 1


def test_excel_sort_previews_complete_rows_then_applies_and_verifies_exact_order() -> None:
    excel = FakeExcel()
    provider = ExcelRuntimeProvider(ExcelActionAdapter(lambda: excel))
    context = {"active_app": {"process_name": "excel.exe"}}
    snapshot = provider.snapshot(context)
    capability = next(item for item in provider.capabilities(snapshot) if item.type == SORT_RANGE)
    plan = provider.build_plan(
        capability,
        {"column_header": "Revenue", "direction": "descending"},
        snapshot,
        "",
    )

    preview = provider.render_preview(plan, snapshot)

    assert "Proposed order" in preview.html
    assert preview.html.index("Feb") < preview.html.index("Jan")
    assert excel.Selection.Value2[1][0] == "Jan"

    result = provider.execute(plan, confirmed=True, idempotency_key="runtime-sort")

    assert result.created == ({"kind": "sorted_range", "name": "A1:C3"},)
    assert result.verification == ("Verified complete-row sort by Revenue.",)
    assert excel.Selection.Value2 == (
        ("Month", "Revenue", "Region"),
        ("Feb", 1700, "East"),
        ("Jan", 1200, "West"),
    )
    assert provider.verify(plan, result) == ()


def test_excel_sort_rejects_a_missing_or_duplicate_header() -> None:
    excel = FakeExcel()
    provider = ExcelRuntimeProvider(ExcelActionAdapter(lambda: excel))
    snapshot = provider.snapshot({})
    capability = next(item for item in provider.capabilities(snapshot) if item.type == SORT_RANGE)

    with pytest.raises(ValueError, match="unique"):
        provider.build_plan(
            capability,
            {"column_header": "Missing", "direction": "ascending"},
            snapshot,
            "",
        )

    excel.Selection._values = (
        ("Month", "Revenue", "Region"),
        ("Jan", 1200, "West"),
        ("Feb", "unknown", "East"),
    )
    excel.Selection.Value2 = excel.Selection._values
    mixed_snapshot = provider.snapshot({})
    with pytest.raises(ValueError, match="consistent value type"):
        provider.build_plan(
            capability,
            {"column_header": "Revenue", "direction": "ascending"},
            mixed_snapshot,
            "",
        )


def test_excel_sort_restores_snapshot_before_rejecting_a_verification_mismatch() -> None:
    excel = FakeExcel()
    provider = ExcelRuntimeProvider(ExcelActionAdapter(lambda: excel))
    snapshot = provider.snapshot({})
    capability = next(item for item in provider.capabilities(snapshot) if item.type == SORT_RANGE)
    plan = provider.build_plan(
        capability,
        {"column_header": "Revenue", "direction": "descending"},
        snapshot,
        "",
    )

    excel.Selection.Sort = lambda **_kwargs: setattr(
        excel.Selection,
        "Value2",
        (
            ("Month", "Revenue", "Region"),
            ("Jan", 9999, "West"),
            ("Feb", 1700, "East"),
        ),
    )

    with pytest.raises(RuntimeError, match="reviewed row order"):
        provider.execute(plan, confirmed=True, idempotency_key="bad-sort")

    assert excel.undo_count == 0
    assert excel.Selection.Value2 == excel._undo_values
