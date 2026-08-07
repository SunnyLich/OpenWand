"""Bounded, read-only snapshots of the active desktop Excel selection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from core.actions.contracts import ActionTarget
from core.actions.errors import ActionUnavailableError

MAX_ACTION_CELLS = 10_000
PREVIEW_ROWS = 12
PREVIEW_COLUMNS = 8
FORMULA_CONTEXT_MAX_CELLS = 32
FORMULA_CONTEXT_CHAR_BUDGET = 16_000
CONTEXT_CELL_CHAR_LIMIT = 1_000
SELECTED_TEXT_CHAR_LIMIT = 20_000

_UNKNOWN = object()


@dataclass(frozen=True)
class ExcelSnapshot:
    """Complete values for a bounded selection plus app-owned object names."""

    workbook_name: str
    workbook_path: str
    worksheet_name: str
    selection_address: str
    row_count: int
    column_count: int
    values: tuple[tuple[Any, ...], ...]
    formulas: tuple[tuple[str, ...], ...]
    formula_capture_complete: bool
    selection_row: int
    selection_column: int
    table_names: tuple[str, ...]
    chart_names: tuple[str, ...]
    fingerprint: str

    @property
    def target(self) -> ActionTarget:
        """Return the action target embedded into plans and previews."""
        return ActionTarget(
            app="excel",
            display_name=f"{self.workbook_name} · {self.worksheet_name}!{self.selection_address}",
            locator={
                "workbook": self.workbook_path or self.workbook_name,
                "worksheet": self.worksheet_name,
                "range": self.selection_address,
            },
            version=self.fingerprint,
        )

    @property
    def preview_values(self) -> tuple[tuple[Any, ...], ...]:
        """Return a small display slice while retaining all values for freshness."""
        return tuple(row[:PREVIEW_COLUMNS] for row in self.values[:PREVIEW_ROWS])

    @property
    def preview_formulas(self) -> tuple[tuple[str, ...], ...]:
        """Return formula text aligned with ``preview_values``; constants are empty."""
        return tuple(row[:PREVIEW_COLUMNS] for row in self.formulas[:PREVIEW_ROWS])

    @property
    def context_display_values(self) -> tuple[tuple[Any, ...], ...]:
        """Return a character-bounded display grid safe for a model context payload."""
        return tuple(
            tuple(_bounded_context_value(cell) for cell in row)
            for row in self.preview_values
        )

    @property
    def context_formulas(self) -> tuple[tuple[str | None, ...], ...]:
        """Return a character-bounded formula grid aligned with display context."""
        return tuple(
            tuple(
                _bounded_context_value(formula) if formula else None
                for formula in row
            )
            for row in self.preview_formulas
        )

    @property
    def formula_count(self) -> int:
        """Return the number of cells positively identified as formulas."""
        return sum(bool(formula) for row in self.formulas for formula in row)

    def formula_context(self) -> dict[str, Any]:
        """Return bounded, explicit formula context for read-only model prompts."""
        cells: list[dict[str, Any]] = []
        remaining_chars = FORMULA_CONTEXT_CHAR_BUDGET
        for row_offset, row in enumerate(self.formulas):
            for column_offset, formula in enumerate(row):
                if not formula or len(cells) >= FORMULA_CONTEXT_MAX_CELLS:
                    continue
                if remaining_chars <= 0:
                    continue
                excerpt = formula[:remaining_chars]
                cells.append(
                    {
                        "address": _cell_address(
                            self.selection_row + row_offset,
                            self.selection_column + column_offset,
                        ),
                        "formula": excerpt,
                        "formula_length": len(formula),
                        "formula_truncated": len(excerpt) < len(formula),
                        "displayed_value": _bounded_context_value(
                            self.values[row_offset][column_offset]
                        ),
                    }
                )
                remaining_chars -= len(excerpt)

        count = self.formula_count
        cell_count = self.row_count * self.column_count
        if not self.formula_capture_complete:
            status = "incomplete"
            note = "Excel did not expose formula identity for every candidate cell."
        elif count == 0:
            status = "no_formula"
            note = "The selected cell or range contains no formulas."
        elif count == 1 and cell_count == 1:
            status = "single_cell_formula"
            note = "The selected cell contains one formula."
        elif count == 1:
            status = "single_formula_in_range"
            note = "The selected range contains one formula and one or more non-formula cells."
        else:
            status = "multiple_formulas"
            note = f"The selected range contains {count} formulas; do not describe them as one formula."
        return {
            "status": status,
            "capture_complete": self.formula_capture_complete,
            "formula_count": count,
            "selected_cell_count": cell_count,
            "cells": cells,
            "omitted_formula_count": max(0, count - len(cells)),
            "note": note,
        }

    def selected_text(self) -> str:
        """Return a bounded, explicit text rendering for ordinary answer queries."""
        formula_context = self.formula_context()
        lines = [
            f"Excel selection: {self.worksheet_name}!{self.selection_address}",
            f"Formula status: {formula_context['status']}",
            str(formula_context["note"]),
        ]
        cells = formula_context["cells"]
        if cells:
            for cell in cells:
                lines.append(
                    f"{cell['address']} formula: "
                    f"{json.dumps(cell['formula'], ensure_ascii=False)}; displayed value: "
                    f"{json.dumps(_bounded_context_value(cell['displayed_value']), ensure_ascii=False)}"
                )
            omitted = int(formula_context["omitted_formula_count"])
            if omitted:
                lines.append(f"{omitted} additional formulas were omitted from this bounded context.")
        else:
            lines.append(
                "Displayed values (bounded preview): "
                + json.dumps(self.context_display_values, ensure_ascii=False)
            )
        text = "\n".join(lines)
        if len(text) <= SELECTED_TEXT_CHAR_LIMIT:
            return text
        return (
            text[:SELECTED_TEXT_CHAR_LIMIT]
            + f"\n[Selection context truncated at {SELECTED_TEXT_CHAR_LIMIT:,} characters.]"
        )


def capture_excel_snapshot(application: Any) -> ExcelSnapshot:
    """Capture the active selection using only Excel object-model reads."""
    workbook = getattr(application, "ActiveWorkbook", None)
    worksheet = getattr(application, "ActiveSheet", None)
    selection = getattr(application, "Selection", None)
    if workbook is None or worksheet is None or selection is None:
        raise ActionUnavailableError("Excel has no active workbook, worksheet, or selection.")

    workbook_name = str(getattr(workbook, "Name", "") or "")
    workbook_path = str(getattr(workbook, "FullName", "") or workbook_name)
    worksheet_name = str(getattr(worksheet, "Name", "") or "")
    if not workbook_name or not worksheet_name:
        raise ActionUnavailableError("Excel's active workbook or worksheet could not be identified.")

    row_count = int(getattr(getattr(selection, "Rows", None), "Count", 0) or 0)
    column_count = int(getattr(getattr(selection, "Columns", None), "Count", 0) or 0)
    cell_count = row_count * column_count
    if cell_count < 1:
        raise ActionUnavailableError("Select at least one Excel cell.")
    if cell_count > MAX_ACTION_CELLS:
        raise ActionUnavailableError(
            f"The selection contains {cell_count:,} cells; the first Excel action release is limited "
            f"to {MAX_ACTION_CELLS:,} cells."
        )

    address = _range_address(selection)
    values = _normalise_values(getattr(selection, "Value2", None), row_count, column_count)
    formula_source, formula_source_available = _formula_source(selection)
    formulas, formula_capture_complete = _normalise_formulas(
        selection,
        formula_source,
        row_count,
        column_count,
        source_available=formula_source_available,
    )
    selection_row = int(getattr(selection, "Row", 0) or 0)
    selection_column = int(getattr(selection, "Column", 0) or 0)
    if selection_row < 1 or selection_column < 1:
        formula_capture_complete = False
        selection_row = max(1, selection_row)
        selection_column = max(1, selection_column)
    table_names = _workbook_table_names(workbook)
    chart_names = _chart_names(worksheet)
    fingerprint = _fingerprint(
        workbook_path,
        worksheet_name,
        address,
        row_count,
        column_count,
        values,
        formulas,
        formula_capture_complete,
        table_names,
        chart_names,
    )
    return ExcelSnapshot(
        workbook_name=workbook_name,
        workbook_path=workbook_path,
        worksheet_name=worksheet_name,
        selection_address=address,
        row_count=row_count,
        column_count=column_count,
        values=values,
        formulas=formulas,
        formula_capture_complete=formula_capture_complete,
        selection_row=selection_row,
        selection_column=selection_column,
        table_names=table_names,
        chart_names=chart_names,
        fingerprint=fingerprint,
    )


def _normalise_values(value: Any, rows: int, columns: int) -> tuple[tuple[Any, ...], ...]:
    """Normalise Excel's scalar/tuple Value2 variants into a rectangular tuple."""
    if rows == 1 and columns == 1:
        return ((_json_cell(value),),)
    if rows == 1 and isinstance(value, tuple) and (not value or not isinstance(value[0], tuple)):
        return (tuple(_json_cell(cell) for cell in value),)
    if not isinstance(value, tuple):
        raise ActionUnavailableError("Excel returned an unreadable selection.")
    normalised = tuple(
        tuple(_json_cell(cell) for cell in (row if isinstance(row, tuple) else (row,)))
        for row in value
    )
    if len(normalised) != rows or any(len(row) != columns for row in normalised):
        raise ActionUnavailableError("Excel returned a selection with unexpected dimensions.")
    return normalised


def _formula_source(selection: Any) -> tuple[Any, bool]:
    """Read modern formula text first, falling back for older Excel versions."""
    for property_name in ("Formula2", "Formula"):
        try:
            return getattr(selection, property_name), True
        except (AttributeError, OSError):
            continue
        except Exception:  # noqa: BLE001 - a COM property can fail independently of Value2
            continue
    return None, False


def _normalise_formulas(
    selection: Any,
    value: Any,
    rows: int,
    columns: int,
    *,
    source_available: bool,
) -> tuple[tuple[tuple[str, ...], ...], bool]:
    """Capture formula text while distinguishing constants and literal ``=`` text."""
    empty = tuple(tuple("" for _column in range(columns)) for _row in range(rows))
    if not source_available:
        return empty, False
    try:
        raw = _normalise_values(value, rows, columns)
    except ActionUnavailableError:
        return empty, False

    aggregate = _has_formula(selection)
    if aggregate is False:
        return empty, True

    formulas: list[list[str]] = [["" for _column in range(columns)] for _row in range(rows)]
    complete = True
    for row_index, row in enumerate(raw, start=1):
        for column_index, cell in enumerate(row, start=1):
            formula = cell if isinstance(cell, str) and cell.startswith("=") else None
            if aggregate is True:
                if formula is None:
                    complete = False
                else:
                    formulas[row_index - 1][column_index - 1] = formula
                continue
            if formula is None:
                continue
            cell_state = _cell_has_formula(selection, row_index, column_index)
            if cell_state is True:
                formulas[row_index - 1][column_index - 1] = formula
            elif cell_state is _UNKNOWN:
                complete = False

    if aggregate is None and not any(formula for row in formulas for formula in row):
        # A mixed aggregate promises at least one formula. If none were
        # identified, the detailed COM reads were not trustworthy enough.
        complete = False
    return tuple(tuple(row) for row in formulas), complete


def _has_formula(value: Any) -> bool | None | object:
    """Return Excel's true/false/mixed formula state without guessing."""
    try:
        state = value.HasFormula
    except Exception:  # noqa: BLE001 - optional COM metadata
        return _UNKNOWN
    if state is True or state is False or state is None:
        return state
    return _UNKNOWN


def _cell_has_formula(selection: Any, row: int, column: int) -> bool | object:
    """Resolve ambiguous formula-like text with one exact cell read."""
    try:
        return True if selection.Cells.Item(row, column).HasFormula is True else False
    except Exception:  # noqa: BLE001 - optional COM metadata
        return _UNKNOWN


def _cell_address(row: int, column: int) -> str:
    """Return an A1 cell address from one-based row and column numbers."""
    letters = ""
    current = column
    while current:
        current, remainder = divmod(current - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return f"{letters}{row}"


def _range_address(selection: Any) -> str:
    """Read a relative address from both generated and late-bound COM proxies."""
    address = getattr(selection, "Address", "")
    if callable(address):
        return str(address(False, False))
    getter = getattr(selection, "GetAddress", None)
    if callable(getter):
        try:
            return str(getter(RowAbsolute=False, ColumnAbsolute=False))
        except TypeError:
            return str(getter(False, False))
    # Late-bound pywin32 may materialize Address as a string property before
    # generated wrappers are available. Normalize absolute markers locally;
    # the captured workbook/sheet identity and fingerprint still bind target.
    text = str(address or "").strip()
    if text:
        return text.replace("$", "")
    raise ActionUnavailableError("Excel did not expose the selected range address.")


def _json_cell(value: Any) -> Any:
    """Keep common Value2 values stable and stringify unusual COM values."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _bounded_context_value(value: Any) -> Any:
    """Bound cell strings without changing numeric, boolean, or null values."""
    if not isinstance(value, str) or len(value) <= CONTEXT_CELL_CHAR_LIMIT:
        return value
    omitted = len(value) - CONTEXT_CELL_CHAR_LIMIT
    return f"{value[:CONTEXT_CELL_CHAR_LIMIT]}… [{omitted:,} characters omitted]"


def _collection_names(collection: Any) -> tuple[str, ...]:
    """Read names from a one-based Excel collection."""
    if collection is None:
        return ()
    count = int(getattr(collection, "Count", 0) or 0)
    return tuple(str(collection.Item(index).Name) for index in range(1, count + 1))


def _workbook_table_names(workbook: Any) -> tuple[str, ...]:
    """Read every table name because Excel requires names to be workbook-unique."""
    worksheets = getattr(workbook, "Worksheets", None)
    if worksheets is None:
        return ()
    names: list[str] = []
    for index in range(1, int(getattr(worksheets, "Count", 0) or 0) + 1):
        sheet = worksheets.Item(index)
        names.extend(_collection_names(getattr(sheet, "ListObjects", None)))
    return tuple(names)


def _chart_names(worksheet: Any) -> tuple[str, ...]:
    """Read names from the worksheet's ChartObjects collection."""
    chart_objects = worksheet.ChartObjects()
    return _collection_names(chart_objects)


def _fingerprint(*parts: Any) -> str:
    """Hash the exact bounded target state used for the action decision."""
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
