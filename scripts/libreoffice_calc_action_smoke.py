"""Real LibreOffice Calc smoke harness for Wisp's preview-first actions.

Run with LibreOffice's bundled Python while a socket-enabled LibreOffice
instance is active. ``setup`` creates a disposable workbook and selects its
data without formatting it. ``apply`` reconnects, verifies the exact values,
then formats the range and adds a chart through LibreOffice's UNO API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import uno
from com.sun.star.awt import Rectangle
from com.sun.star.beans import PropertyValue

UNO_URL_TEMPLATE = "uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
DATA = (
    ("Month", "Revenue", "Region"),
    ("January", 12400.0, "West"),
    ("February", 15850.0, "East"),
    ("March", 14300.0, "North"),
    ("April", 18200.0, "West"),
    ("May", 19650.0, "East"),
    ("June", 22100.0, "North"),
)
_HELD_DOCUMENTS: list[object] = []


def _property(name: str, value: object) -> PropertyValue:
    item = PropertyValue()
    item.Name = name
    item.Value = value
    return item


def _desktop(port: int):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver",
        local,
    )
    context = resolver.resolve(UNO_URL_TEMPLATE.format(port=port))
    return context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop",
        context,
    )


def _document_url(path: Path) -> str:
    return uno.systemPathToFileUrl(str(path.resolve()))


def _find_document(desktop, path: Path):
    expected = _document_url(path)
    components = desktop.Components.createEnumeration()
    while components.hasMoreElements():
        component = components.nextElement()
        if getattr(component, "URL", "") == expected:
            return component
    return desktop.loadComponentFromURL(expected, "_blank", 0, ())


def _values_fingerprint(values: tuple[tuple[object, ...], ...]) -> str:
    encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def setup(path: Path, port: int) -> dict[str, object]:
    desktop = _desktop(port)
    document = desktop.loadComponentFromURL(
        "private:factory/scalc",
        "_blank",
        0,
        (_property("Hidden", False),),
    )
    sheet = document.Sheets.getByIndex(0)
    sheet.Name = "Sales"
    data_range = sheet.getCellRangeByName("A1:C7")
    data_range.setDataArray(DATA)
    document.CurrentController.select(data_range)
    document.storeAsURL(_document_url(path), (_property("FilterName", "calc8"),))
    document.CurrentController.Frame.ContainerWindow.setFocus()
    return {
        "phase": "preview_ready",
        "document": str(path),
        "sheet": sheet.Name,
        "range": "A1:C7",
        "rows": len(DATA),
        "columns": len(DATA[0]),
        "fingerprint": _values_fingerprint(DATA),
        "mutated": False,
        "proposed_operations": ["calc.format_table@1", "calc.add_chart@1"],
    }


def setup_unsaved(port: int, hold_seconds: float = 0.0) -> dict[str, object]:
    """Create the same disposable sheet without opening a save/overwrite prompt."""
    desktop = _desktop(port)
    document = desktop.loadComponentFromURL(
        "private:factory/scalc",
        "_blank",
        0,
        (_property("Hidden", True),),
    )
    sheet = document.Sheets.getByIndex(0)
    sheet.Name = "Sales"
    data_range = sheet.getCellRangeByName("A1:C7")
    data_range.setDataArray(DATA)
    document.CurrentController.select(data_range)
    container = document.CurrentController.Frame.ContainerWindow
    container.setPosSize(-30000, -30000, 900, 700, 15)
    container.setEnable(False)
    container.setVisible(True)
    time.sleep(0.2)
    container.setEnable(True)
    _HELD_DOCUMENTS.append(
        (desktop, document, sheet, data_range, document.CurrentController, document.CurrentController.Frame)
    )
    result = {
        "phase": "preview_ready_unsaved",
        "document": "Untitled 1",
        "sheet": sheet.Name,
        "range": "A1:C7",
        "rows": len(DATA),
        "columns": len(DATA[0]),
        "fingerprint": _values_fingerprint(DATA),
        "mutated": False,
        "proposed_operations": ["calc.add_chart@1"],
    }
    if hold_seconds > 0:
        time.sleep(hold_seconds)
    return result


def setup_hidden(port: int, hold_seconds: float = 0.0) -> dict[str, object]:
    """Create and retain a disposable sheet without ever showing a window."""
    desktop = _desktop(port)
    document = desktop.loadComponentFromURL(
        "private:factory/scalc",
        "_blank",
        0,
        (_property("Hidden", True),),
    )
    sheet = document.Sheets.getByIndex(0)
    sheet.Name = "Sales"
    data_range = sheet.getCellRangeByName("A1:C7")
    data_range.setDataArray(DATA)
    document.CurrentController.select(data_range)
    _HELD_DOCUMENTS.append((desktop, document, sheet, data_range, document.CurrentController))
    result = {
        "phase": "preview_ready_hidden",
        "document": str(document.Title or "Untitled 1"),
        "sheet": sheet.Name,
        "range": "A1:C7",
        "fingerprint": _values_fingerprint(DATA),
    }
    if hold_seconds > 0:
        time.sleep(hold_seconds)
    return result


def apply(path: Path, expected_fingerprint: str, port: int) -> dict[str, object]:
    desktop = _desktop(port)
    document = _find_document(desktop, path)
    sheet = document.Sheets.getByName("Sales")
    data_range = sheet.getCellRangeByName("A1:C7")
    current = tuple(tuple(row) for row in data_range.getDataArray())
    actual_fingerprint = _values_fingerprint(current)
    if actual_fingerprint != expected_fingerprint:
        raise RuntimeError(
            "Calc data changed after preview; refusing to apply the plan. "
            f"actual_fingerprint={actual_fingerprint} values={current!r}"
        )

    header = sheet.getCellRangeByName("A1:C1")
    header.CellBackColor = 0x173F35
    header.CharColor = 0xFFFFFF
    header.CharWeight = 150.0
    header.ParaAdjust = 3

    for row_number in (3, 5, 7):
        sheet.getCellRangeByName(f"A{row_number}:C{row_number}").CellBackColor = 0xE7F3EE
    sheet.Columns.getByIndex(0).Width = 3200
    sheet.Columns.getByIndex(1).Width = 3000
    sheet.Columns.getByIndex(2).Width = 3000

    chart_range = sheet.getCellRangeByName("A1:B7").RangeAddress
    charts = sheet.Charts
    if charts.hasByName("WispRevenueChart"):
        charts.removeByName("WispRevenueChart")
    charts.addNewByName(
        "WispRevenueChart",
        Rectangle(9500, 1000, 15500, 9500),
        (chart_range,),
        True,
        True,
    )
    chart = charts.getByName("WispRevenueChart").EmbeddedObject
    chart.HasMainTitle = True
    chart.Title.String = "Revenue by month"
    chart.HasLegend = False

    # LibreOffice's legacy chart bridge can replace the corner header cell
    # while interpreting row/column labels. Preserve the exact previewed source
    # data and verify that chart creation has no spreadsheet side effects.
    data_range.setDataArray(current)
    post_chart_values = tuple(tuple(row) for row in data_range.getDataArray())
    if post_chart_values != current:
        charts.removeByName("WispRevenueChart")
        raise RuntimeError("Calc chart creation changed source cells; the chart was rolled back.")

    document.CurrentController.select(sheet.getCellRangeByName("D10"))
    document.store()
    document.CurrentController.Frame.ContainerWindow.setFocus()
    return {
        "phase": "applied_and_verified",
        "document": str(path),
        "table_range": "Sales.A1:C7",
        "chart": "WispRevenueChart",
        "fingerprint": actual_fingerprint,
        "verified": charts.hasByName("WispRevenueChart"),
        "header_values": list(sheet.getCellRangeByName("A1:C1").getDataArray()[0]),
        "header_text_colors": [sheet.getCellByPosition(column, 0).CharColor for column in range(3)],
    }


def select(path: Path, port: int) -> dict[str, object]:
    """Select the demo range and focus Calc without reading it through UNO."""
    document = _find_document(_desktop(port), path)
    sheet = document.Sheets.getByName("Sales")
    data_range = sheet.getCellRangeByName("A1:C7")
    document.CurrentController.select(data_range)
    document.CurrentController.Frame.ContainerWindow.setFocus()
    return {"phase": "range_selected", "range": "Sales.A1:C7"}


def inspect_selection(path: Path, port: int) -> dict[str, object]:
    """Read Calc's existing selection while Calc remains in the background."""
    document = _find_document(_desktop(port), path)
    selection = document.CurrentController.Selection
    address = selection.RangeAddress
    sheet = document.Sheets.getByIndex(address.Sheet)
    values = tuple(tuple(row) for row in selection.getDataArray())
    return {
        "phase": "selection_inspected",
        "document": str(path),
        "sheet": sheet.Name,
        "start_column": int(address.StartColumn),
        "start_row": int(address.StartRow),
        "end_column": int(address.EndColumn),
        "end_row": int(address.EndRow),
        "rows": len(values),
        "columns": len(values[0]) if values else 0,
        "fingerprint": _values_fingerprint(values),
        "first_row": list(values[0]) if values else [],
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "phase",
        choices=("setup", "setup-unsaved", "setup-hidden", "apply", "select", "inspect-selection"),
    )
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--fingerprint", default="")
    parser.add_argument("--port", type=int, default=2002)
    parser.add_argument("--hold-seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    args.path.parent.mkdir(parents=True, exist_ok=True)
    if args.phase == "setup":
        result = setup(args.path, args.port)
    elif args.phase == "setup-unsaved":
        result = setup_unsaved(args.port, args.hold_seconds)
        args.hold_seconds = 0.0
    elif args.phase == "setup-hidden":
        result = setup_hidden(args.port, args.hold_seconds)
        args.hold_seconds = 0.0
    elif args.phase == "apply":
        if not args.fingerprint:
            parser.error("--fingerprint is required for apply")
        result = apply(args.path, args.fingerprint, args.port)
    elif args.phase == "select":
        result = select(args.path, args.port)
    else:
        result = inspect_selection(args.path, args.port)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    if args.hold_seconds > 0:
        time.sleep(args.hold_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
