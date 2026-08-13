"""Focused safety tests for reviewed Excel and Calc cell cleanup execution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.actions.adapters.calc import CalcActionAdapter, CalcSnapshot
from core.actions.adapters.calc.plans import build_cleanup_plan as build_calc_cleanup_plan
from core.actions.adapters.excel import ExcelActionAdapter, ExcelRuntimeProvider
from core.actions.adapters.excel.capabilities import CLEAN_RANGE as EXCEL_CLEAN_RANGE
from core.actions.adapters.excel.plans import build_cleanup_plan as build_excel_cleanup_plan
from core.actions.errors import ActionValidationError


class _Count:
    def __init__(self, count: int) -> None:
        self.Count = count


class _EmptyCollection:
    Count = 0

    def Item(self, _index: int):
        raise IndexError


class _ExcelCell:
    def __init__(self, source: _ExcelRange, row: int, column: int) -> None:
        self.source = source
        self.row = row
        self.column = column

    @property
    def Value2(self):
        return self.source.values[self.row][self.column]

    @Value2.setter
    def Value2(self, value) -> None:
        self.source.application.record_undo()
        self.source.values[self.row][self.column] = value
        self.source.formulas[self.row][self.column] = ""
        self.source.maybe_corrupt()

    @property
    def Formula2(self):
        return self.source.formulas[self.row][self.column]

    @property
    def HasFormula(self) -> bool:
        return bool(self.source.formulas[self.row][self.column])

    @Formula2.setter
    def Formula2(self, value) -> None:
        self.source.application.record_undo()
        self.source.formulas[self.row][self.column] = value
        self.source.values[self.row][self.column] = 999.0
        self.source.maybe_corrupt()


class _ExcelCells:
    def __init__(self, source: _ExcelRange) -> None:
        self.source = source

    def __call__(self, row: int, column: int) -> _ExcelCell:
        return _ExcelCell(self.source, row - 1, column - 1)

    def Item(self, row: int, column: int) -> _ExcelCell:
        return self(row, column)


class _ExcelRange:
    def __init__(self, application: _ExcelApplication) -> None:
        self.application = application
        self.values = [
            ["Name", "Amount", "Double"],
            [" Alice ", 5.0, 10.0],
            ["Bob", "12", 24.0],
        ]
        self.formulas = [
            ["", "", ""],
            ["", "", "=B2*2"],
            ["", "", "=B3*2"],
        ]
        self.Rows = _Count(3)
        self.Columns = _Count(3)
        self.Cells = _ExcelCells(self)
        self.HasFormula = None
        self.Row = 1
        self.Column = 1
        self.corrupt_after_write = False

    def Address(self, _row_absolute: bool, _column_absolute: bool) -> str:
        return "A1:C3"

    @property
    def Value2(self):
        return tuple(tuple(row) for row in self.values)

    @property
    def Formula2(self):
        return tuple(
            tuple(formula or self.values[row][column] for column, formula in enumerate(formula_row))
            for row, formula_row in enumerate(self.formulas)
        )

    @Formula2.setter
    def Formula2(self, value) -> None:
        rows = ((value,),) if not isinstance(value, tuple) else value
        for row_index, row in enumerate(rows):
            cells = row if isinstance(row, tuple) else (row,)
            for column_index, cell in enumerate(cells):
                if isinstance(cell, str) and cell.startswith("="):
                    self.formulas[row_index][column_index] = cell
                else:
                    self.formulas[row_index][column_index] = ""
                    self.values[row_index][column_index] = cell

    def maybe_corrupt(self) -> None:
        if self.corrupt_after_write:
            self.values[2][0] = "unexpected"


class _ExcelWorksheet:
    Name = "Export"

    def __init__(self, source: _ExcelRange) -> None:
        self.source = source
        self.ListObjects = _EmptyCollection()

    def Range(self, address: str) -> _ExcelRange:
        assert address == "A1:C3"
        return self.source

    @staticmethod
    def ChartObjects() -> _EmptyCollection:
        return _EmptyCollection()


class _ExcelApplication:
    def __init__(self) -> None:
        self.undo_stack: list[tuple[list[list[object]], list[list[str]]]] = []
        self.undo_count = 0
        self.Selection = _ExcelRange(self)
        self.ActiveSheet = _ExcelWorksheet(self.Selection)
        worksheets = SimpleNamespace(Count=1, Item=lambda _index: self.ActiveSheet)
        self.ActiveWorkbook = SimpleNamespace(Name="Export.xlsx", FullName="C:/Export.xlsx", Worksheets=worksheets)

    def record_undo(self) -> None:
        self.undo_stack.append((
            [list(row) for row in self.Selection.values],
            [list(row) for row in self.Selection.formulas],
        ))

    def Undo(self) -> None:
        self.undo_count += 1
        values, formulas = self.undo_stack.pop()
        self.Selection.values = values
        self.Selection.formulas = formulas


def test_excel_cleanup_preview_executes_exact_cells_and_preserves_formulas() -> None:
    excel = _ExcelApplication()
    provider = ExcelRuntimeProvider(ExcelActionAdapter(lambda: excel))
    snapshot = provider.snapshot({})
    capability = next(item for item in provider.capabilities(snapshot) if item.type == EXCEL_CLEAN_RANGE)
    plan = provider.build_plan(
        capability,
        {"changes": [
            {"row_offset": 1, "column_offset": 0, "after_kind": "value", "after_value": "Alice"},
            {"row_offset": 2, "column_offset": 1, "after_kind": "value", "after_value": 12.0},
        ]},
        snapshot,
        "",
    )

    preview = provider.render_preview(plan, snapshot)
    assert "A2" in preview.html and "B3" in preview.html
    assert " Alice " in preview.html and "Alice" in preview.html
    assert plan.operations[0].args["changes"][0]["before_value"] == " Alice "

    result = provider.execute(plan, confirmed=True, idempotency_key="excel-cleanup")

    assert excel.Selection.values[1][0] == "Alice"
    assert excel.Selection.values[2][1] == 12.0
    assert excel.Selection.formulas[1][2] == "=B2*2"
    assert excel.Selection.formulas[2][2] == "=B3*2"
    assert result.journal[0]["rollback"] == "verified_snapshot_restore_on_failure"
    assert result.verification == ("Verified 2 exact cell replacements.",)


def test_excel_cleanup_rejects_formula_replacement_without_explicit_review() -> None:
    excel = _ExcelApplication()
    snapshot = ExcelActionAdapter(lambda: excel).snapshot()

    with pytest.raises(ValueError, match="explicitly reviewed"):
        build_excel_cleanup_plan(snapshot, [{
            "row_offset": 1,
            "column_offset": 2,
            "after_kind": "value",
            "after_value": 10.0,
        }])


def test_excel_cleanup_rejects_stale_target_and_rolls_back_bad_readback() -> None:
    excel = _ExcelApplication()
    adapter = ExcelActionAdapter(lambda: excel)
    snapshot = adapter.snapshot()
    plan = build_excel_cleanup_plan(snapshot, [{
        "row_offset": 1,
        "column_offset": 0,
        "after_kind": "value",
        "after_value": "Alice",
    }])
    excel.Selection.values[1][1] = 6.0
    with pytest.raises(ActionValidationError, match="changed since the preview"):
        adapter.execute(plan, confirmed=True, idempotency_key="stale-cleanup")

    excel = _ExcelApplication()
    adapter = ExcelActionAdapter(lambda: excel)
    snapshot = adapter.snapshot()
    plan = build_excel_cleanup_plan(snapshot, [{
        "row_offset": 1,
        "column_offset": 0,
        "after_kind": "value",
        "after_value": "Alice",
    }])
    excel.Selection.corrupt_after_write = True
    with pytest.raises(RuntimeError, match="exact reviewed cleanup"):
        adapter.execute(plan, confirmed=True, idempotency_key="bad-cleanup")
    assert excel.undo_count == 0
    assert excel.Selection.values[1][0] == " Alice "
    assert excel.Selection.values[2][0] == "Bob"


def _calc_selection(*, fingerprint: str = "calc-fingerprint") -> dict:
    return {
        "document_title": "Export.ods - LibreOffice Calc",
        "window_id": 777,
        "pid": 42,
        "range": "A1:C3",
        "values": (("Name", "Amount", "Double"), (" Alice ", "5", "10"), ("Bob", "12", "24")),
        "typed_values": (("Name", "Amount", "Double"), (" Alice ", 5.0, 10.0), ("Bob", "12", 24.0)),
        "formulas": (("Name", "Amount", "Double"), (" Alice ", "5", "=B2*2"), ("Bob", "12", "=B3*2")),
        "fingerprint": fingerprint,
    }


def test_calc_cleanup_plan_preview_and_adapter_revalidation_are_exact() -> None:
    selection = _calc_selection()
    snapshot = CalcSnapshot.from_selection(selection)
    plan = build_calc_cleanup_plan(snapshot, [{
        "row_offset": 1,
        "column_offset": 0,
        "after_kind": "value",
        "after_value": "Alice",
    }])
    adapter = CalcActionAdapter(action_executor=lambda _plan: {"verification": ["Verified"]})

    preview = adapter.render_preview(plan, snapshot)
    assert " Alice " in preview.html and "Alice" in preview.html
    assert "Every other selected value and formula stays unchanged" in preview.html

    changed = _calc_selection(fingerprint="changed")

    class Reader:
        @staticmethod
        def inspect_selection(_active_app):
            return changed

    with pytest.raises(ActionValidationError, match="changed after the preview"):
        CalcActionAdapter(reader=Reader(), action_executor=lambda _plan: {}).execute(
            plan, confirmed=True, idempotency_key="stale-calc-cleanup"
        )


class _CalcUndoManager:
    def __init__(self, source: _CalcRange) -> None:
        self.source = source
        self.before = None
        self.contexts: list[str] = []
        self.undo_count = 0

    def enterUndoContext(self, title: str) -> None:
        self.contexts.append(title)
        self.before = self.source.copy_state()

    @staticmethod
    def leaveUndoContext() -> None:
        return None

    def isUndoPossible(self) -> bool:
        return self.before is not None

    def undo(self) -> None:
        self.undo_count += 1
        self.source.restore_state(self.before)


class _CalcCell:
    def __init__(self, source: _CalcRange, column: int, row: int) -> None:
        self.source = source
        self.column = column
        self.row = row

    def setString(self, value: str) -> None:
        self.source.values[self.row][self.column] = value
        self.source.formulas[self.row][self.column] = value
        self.source.maybe_corrupt()

    def setValue(self, value: float) -> None:
        self.source.values[self.row][self.column] = value
        self.source.formulas[self.row][self.column] = str(value)
        self.source.maybe_corrupt()

    def setFormula(self, value: str) -> None:
        self.source.values[self.row][self.column] = 999.0
        self.source.formulas[self.row][self.column] = value
        self.source.maybe_corrupt()


class _CalcRange:
    def __init__(self) -> None:
        self.values = [["Name", "Amount", "Double"], [" Alice ", 5.0, 10.0], ["Bob", "12", 24.0]]
        self.formulas = [["Name", "Amount", "Double"], [" Alice ", "5", "=B2*2"], ["Bob", "12", "=B3*2"]]
        self.corrupt = False

    def copy_state(self):
        return ([list(row) for row in self.values], [list(row) for row in self.formulas])

    def restore_state(self, state) -> None:
        self.values, self.formulas = ([list(row) for row in state[0]], [list(row) for row in state[1]])

    def getDataArray(self):
        return tuple(tuple(row) for row in self.values)

    def getFormulaArray(self):
        return tuple(tuple(row) for row in self.formulas)

    def getCellByPosition(self, column: int, row: int) -> _CalcCell:
        return _CalcCell(self, column, row)

    def maybe_corrupt(self) -> None:
        if self.corrupt:
            self.values[2][0] = "unexpected"


def _load_calc_helper(monkeypatch):
    monkeypatch.setitem(sys.modules, "uno", SimpleNamespace())
    helper = Path(__file__).resolve().parents[1] / "runtime" / "helpers" / "calc_uno_action.py"
    spec = importlib.util.spec_from_file_location("_openwand_test_calc_cleanup_helper", helper)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_calc_uno_cleanup_is_one_undo_item_and_rolls_back_verification_failure(monkeypatch) -> None:
    helper = _load_calc_helper(monkeypatch)
    source = _CalcRange()
    manager = _CalcUndoManager(source)
    document = SimpleNamespace(
        CurrentController=SimpleNamespace(ActiveSheet=SimpleNamespace(getCellRangeByName=lambda _address: source)),
        getUndoManager=lambda: manager,
    )
    monkeypatch.setattr(helper, "_desktop", lambda **_kwargs: object())
    monkeypatch.setattr(helper, "_find_document", lambda _desktop, _title: document)
    monkeypatch.setattr(
        helper,
        "ctypes",
        SimpleNamespace(
            windll=SimpleNamespace(
                user32=SimpleNamespace(GetForegroundWindow=lambda: 100),
            )
        ),
    )
    fingerprint = helper._fingerprint(source.getDataArray(), source.getFormulaArray())
    change = {
        "row_offset": 1,
        "column_offset": 0,
        "before_kind": "value",
        "before_value": " Alice ",
        "after_kind": "value",
        "after_value": "Alice",
        "replace_formula": False,
    }

    result = helper.apply_clean_range(
        port=0, pipe_name="pipe", title="Export.ods", address="A1:C3",
        fingerprint=fingerprint, changes=[change],
    )
    assert result["ok"] is True
    assert manager.contexts == ["OpenWand: apply reviewed cell cleanup"]
    assert source.values[1][0] == "Alice"
    assert source.formulas[1][2] == "=B2*2"

    source = _CalcRange()
    source.corrupt = True
    manager = _CalcUndoManager(source)
    document.getUndoManager = lambda: manager
    document.CurrentController.ActiveSheet.getCellRangeByName = lambda _address: source
    fingerprint = helper._fingerprint(source.getDataArray(), source.getFormulaArray())
    with pytest.raises(RuntimeError, match="exact reviewed cleanup"):
        helper.apply_clean_range(
            port=0, pipe_name="pipe", title="Export.ods", address="A1:C3",
            fingerprint=fingerprint, changes=[change],
        )
    assert manager.undo_count == 1
    assert source.values[1][0] == " Alice "
    assert source.values[2][0] == "Bob"
