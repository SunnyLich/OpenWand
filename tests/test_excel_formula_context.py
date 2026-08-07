"""Focused tests for truthful, bounded Excel formula context."""

from __future__ import annotations

from typing import Any

from core.actions.adapters.excel.runtime import ExcelRuntimeProvider
from core.actions.adapters.excel.snapshot import capture_excel_snapshot


class _Count:
    def __init__(self, count: int) -> None:
        self.Count = count


class _NamedCollection:
    Count = 0

    def Item(self, _index: int) -> Any:
        raise IndexError


class _Cell:
    def __init__(self, has_formula: bool) -> None:
        self.HasFormula = has_formula


class _Cells:
    def __init__(self, formula_flags: tuple[tuple[bool, ...], ...]) -> None:
        self._formula_flags = formula_flags

    def Item(self, row: int, column: int) -> _Cell:
        return _Cell(self._formula_flags[row - 1][column - 1])


class _Range:
    def __init__(
        self,
        *,
        values: tuple[tuple[Any, ...], ...],
        formulas: tuple[tuple[Any, ...], ...],
        formula_flags: tuple[tuple[bool, ...], ...],
        address: str = "B10",
        row: int = 10,
        column: int = 2,
    ) -> None:
        self.Rows = _Count(len(values))
        self.Columns = _Count(len(values[0]))
        self.Value2 = values[0][0] if len(values) == 1 and len(values[0]) == 1 else values
        self.Formula2 = formulas[0][0] if len(formulas) == 1 and len(formulas[0]) == 1 else formulas
        flags = [flag for formula_row in formula_flags for flag in formula_row]
        self.HasFormula = flags[0] if all(flag == flags[0] for flag in flags) else None
        self.Cells = _Cells(formula_flags)
        self.Row = row
        self.Column = column
        self._address = address

    def Address(self, _row_absolute: bool, _column_absolute: bool) -> str:
        return self._address


class _Worksheet:
    Name = "Metrics"
    ListObjects = _NamedCollection()

    @staticmethod
    def ChartObjects() -> _NamedCollection:
        return _NamedCollection()


class _Worksheets:
    Count = 1

    @staticmethod
    def Item(_index: int) -> _Worksheet:
        return _Worksheet()


class _Workbook:
    Name = "Metrics.xlsx"
    FullName = r"C:\Data\Metrics.xlsx"
    Worksheets = _Worksheets()


class _Excel:
    ActiveWorkbook = _Workbook()
    ActiveSheet = _Worksheet()

    def __init__(self, selection: _Range) -> None:
        self.Selection = selection


def _capture(
    *,
    values: tuple[tuple[Any, ...], ...],
    formulas: tuple[tuple[Any, ...], ...],
    formula_flags: tuple[tuple[bool, ...], ...],
    address: str = "B10",
    row: int = 10,
    column: int = 2,
):
    return capture_excel_snapshot(
        _Excel(
            _Range(
                values=values,
                formulas=formulas,
                formula_flags=formula_flags,
                address=address,
                row=row,
                column=column,
            )
        )
    )


def test_single_cell_formula_preserves_formula_and_displayed_value() -> None:
    snapshot = _capture(
        values=((42,),),
        formulas=(("=SUM(A1:A3)",),),
        formula_flags=((True,),),
    )

    assert snapshot.values == ((42,),)
    assert snapshot.formulas == (("=SUM(A1:A3)",),)
    assert snapshot.formula_context() == {
        "status": "single_cell_formula",
        "capture_complete": True,
        "formula_count": 1,
        "selected_cell_count": 1,
        "cells": [
            {
                "address": "B10",
                "formula": "=SUM(A1:A3)",
                "formula_length": 11,
                "formula_truncated": False,
                "displayed_value": 42,
            }
        ],
        "omitted_formula_count": 0,
        "note": "The selected cell contains one formula.",
    }


def test_no_formula_does_not_mislabel_literal_equals_text() -> None:
    snapshot = _capture(
        values=(("=Not a formula",),),
        formulas=(("=Not a formula",),),
        formula_flags=((False,),),
    )

    assert snapshot.formulas == (("",),)
    assert snapshot.formula_context()["status"] == "no_formula"
    assert snapshot.formula_context()["cells"] == []


def test_mixed_range_checks_formula_like_cells_and_reports_one_formula_truthfully() -> None:
    snapshot = _capture(
        values=((1, 2), ("=literal", 4)),
        formulas=((1, "=A1*2"), ("=literal", 4)),
        formula_flags=((False, True), (False, False)),
        address="D4:E5",
        row=4,
        column=4,
    )

    assert snapshot.formulas == (("", "=A1*2"), ("", ""))
    context = snapshot.formula_context()
    assert context["status"] == "single_formula_in_range"
    assert context["formula_count"] == 1
    assert context["selected_cell_count"] == 4
    assert context["cells"] == [
        {
            "address": "E4",
            "formula": "=A1*2",
            "formula_length": 5,
            "formula_truncated": False,
            "displayed_value": 2,
        }
    ]


def test_formula_text_participates_in_fingerprint_even_when_value_is_unchanged() -> None:
    first = _capture(
        values=((2,),),
        formulas=(("=1+1",),),
        formula_flags=((True,),),
    )
    second = _capture(
        values=((2,),),
        formulas=(("=4/2",),),
        formula_flags=((True,),),
    )

    assert first.values == second.values
    assert first.fingerprint != second.fingerprint


def test_multiple_selected_formulas_are_not_described_as_one_formula() -> None:
    snapshot = _capture(
        values=((2, 3),),
        formulas=(("=1+1", "=1+2"),),
        formula_flags=((True, True),),
        address="C7:D7",
        row=7,
        column=3,
    )

    context = snapshot.formula_context()

    assert context["status"] == "multiple_formulas"
    assert context["formula_count"] == 2
    assert [cell["address"] for cell in context["cells"]] == ["C7", "D7"]
    assert "do not describe them as one formula" in context["note"]


def test_runtime_context_labels_displayed_values_and_formula_state_separately() -> None:
    snapshot = _capture(
        values=((10, 20),),
        formulas=((10, "=A1*2"),),
        formula_flags=((False, True),),
        address="A1:B1",
        row=1,
        column=1,
    )

    context = ExcelRuntimeProvider.planner_context(snapshot)

    assert context["values"] == [[10, 20]]
    assert context["displayed_values"] == [[10, 20]]
    assert context["formulas"] == [[None, "=A1*2"]]
    assert context["formula_context"]["cells"][0]["address"] == "B1"
    assert context["formula_context"]["cells"][0]["displayed_value"] == 20
    assert "Formula status: single_formula_in_range" in context["selected_text"]
    assert 'B1 formula: "=A1*2"; displayed value: 20' in context["selected_text"]


def test_missing_formula_metadata_is_explicit_instead_of_guessing() -> None:
    selection = _Range(
        values=((7,),),
        formulas=((7,),),
        formula_flags=((False,),),
    )
    del selection.Formula2
    del selection.HasFormula

    snapshot = capture_excel_snapshot(_Excel(selection))

    assert snapshot.values == ((7,),)
    assert snapshot.formulas == (("",),)
    assert snapshot.formula_context()["status"] == "incomplete"
    assert snapshot.formula_context()["capture_complete"] is False
