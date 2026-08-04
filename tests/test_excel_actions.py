"""Contract and fake-object-model tests for the first Excel action slice."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.actions.adapters.excel import ExcelActionAdapter, build_table_chart_plan
from core.actions.adapters.excel.capabilities import excel_registry
from core.actions.contracts import ActionOperation
from core.actions.errors import ActionValidationError
from ui.addon_presentations import sanitize_presentation_html


class _Count:
    def __init__(self, count: int) -> None:
        self.Count = count


class FakeRange:
    def __init__(self, address: str, values: tuple[tuple[object, ...], ...]) -> None:
        self._address = address
        self.Value2 = values[0][0] if len(values) == 1 and len(values[0]) == 1 else values
        self.Rows = _Count(len(values))
        self.Columns = _Count(len(values[0]))
        self.Left = 12.0
        self.Top = 18.0
        self.Width = 320.0
        self.Row = 1
        self.Column = 1

    def Address(self, _row_absolute: bool, _column_absolute: bool) -> str:
        return self._address


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
