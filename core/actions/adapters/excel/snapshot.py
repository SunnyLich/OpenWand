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
    table_names = _workbook_table_names(workbook)
    chart_names = _chart_names(worksheet)
    fingerprint = _fingerprint(
        workbook_path,
        worksheet_name,
        address,
        row_count,
        column_count,
        values,
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
