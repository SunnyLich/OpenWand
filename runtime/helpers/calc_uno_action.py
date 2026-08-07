"""Focusless Calc chart mutation run by LibreOffice's bundled Python."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import sys

import uno


def _desktop(*, port: int = 0, pipe_name: str = ""):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local
    )
    if pipe_name:
        endpoint = f"uno:pipe,name={pipe_name};urp;StarOffice.ComponentContext"
    elif port > 0:
        endpoint = f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
    else:
        raise RuntimeError("No LibreOffice automation endpoint was supplied.")
    context = resolver.resolve(endpoint)
    return context.ServiceManager.createInstanceWithContext(
        "com.sun.star.frame.Desktop", context
    )


def _base_title(value: str) -> str:
    text = " ".join(str(value or "").split())
    return re.sub(r"\s+(?:—|-)\s+LibreOffice.*$", "", text, flags=re.IGNORECASE).casefold()


def _find_document(desktop, title: str):
    expected = _base_title(title)
    matches = []
    enumeration = desktop.Components.createEnumeration()
    while enumeration.hasMoreElements():
        component = enumeration.nextElement()
        if not hasattr(component, "Sheets"):
            continue
        if _base_title(getattr(component, "Title", "")) == expected:
            matches.append(component)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one matching Calc document, found {len(matches)}.")
    return matches[0]


def _cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _fingerprint(values, formulas=None) -> str:
    rows = tuple(tuple(_cell_text(cell) for cell in row) for row in values)
    formula_rows = tuple(
        tuple(_cell_text(cell) for cell in row)
        for row in (formulas if formulas is not None else values)
    )
    payload = json.dumps(
        {"values": rows, "formulas": formula_rows},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def probe(*, port: int, pipe_name: str) -> dict:
    """Prove that the endpoint resolves to a live LibreOffice desktop."""
    desktop = _desktop(port=port, pipe_name=pipe_name)
    component = desktop.getCurrentComponent()
    return {
        "ok": True,
        "connected": True,
        "title": str(getattr(component, "Title", "") or ""),
        "calc": bool(component is not None and hasattr(component, "Sheets")),
    }


def snapshot_range(*, port: int, pipe_name: str, title: str, address: str) -> dict:
    """Capture display values and a typed UNO fingerprint without changing Calc."""
    user32 = ctypes.windll.user32
    foreground_before = int(user32.GetForegroundWindow())
    document = _find_document(_desktop(port=port, pipe_name=pipe_name), title)
    sheet = document.CurrentController.ActiveSheet
    source = sheet.getCellRangeByName(address)
    current = tuple(tuple(row) for row in source.getDataArray())
    formulas = tuple(tuple(row) for row in source.getFormulaArray())
    display_values = tuple(
        tuple(
            str(source.getCellByPosition(column, row).getString() or "")
            for column in range(len(current[row]))
        )
        for row in range(len(current))
    )
    foreground_after = int(user32.GetForegroundWindow())
    if foreground_after != foreground_before:
        raise RuntimeError("Calc took focus while Wisp was reading the reviewed range.")
    return {
        "ok": True,
        "document_title": str(getattr(document, "Title", "") or ""),
        "range": address,
        "rows": len(current),
        "columns": len(current[0]) if current else 0,
        "values": display_values,
        # Keep the exact typed values Calc will give the chart. Display text
        # may contain currency symbols or localized separators.
        "typed_values": current,
        "formulas": formulas,
        "fingerprint": _fingerprint(current, formulas),
        "focus_unchanged": True,
    }


def apply_chart(
    *,
    port: int,
    pipe_name: str,
    title: str,
    address: str,
    fingerprint: str,
    chart_title: str,
) -> dict:
    user32 = ctypes.windll.user32
    foreground_before = int(user32.GetForegroundWindow())
    document = _find_document(_desktop(port=port, pipe_name=pipe_name), title)
    sheet = document.CurrentController.ActiveSheet
    source = sheet.getCellRangeByName(address)
    current = tuple(tuple(row) for row in source.getDataArray())
    formulas = tuple(tuple(row) for row in source.getFormulaArray())
    if _fingerprint(current, formulas) != fingerprint:
        raise RuntimeError("Calc data changed after the preview; refusing to apply.")

    charts = sheet.Charts
    index = 1
    name = "WispChart"
    while charts.hasByName(name):
        index += 1
        name = f"WispChart{index}"
    rectangle = uno.createUnoStruct("com.sun.star.awt.Rectangle")
    rectangle.X = 9500
    rectangle.Y = 1000
    rectangle.Width = 15500
    rectangle.Height = 9500
    charts.addNewByName(name, rectangle, (source.RangeAddress,), True, True)
    chart = charts.getByName(name).EmbeddedObject
    chart.HasMainTitle = True
    chart.Title.String = chart_title or "Chart from selected data"

    if tuple(tuple(row) for row in source.getDataArray()) != current:
        charts.removeByName(name)
        raise RuntimeError("Calc changed source cells; Wisp rolled the chart back.")
    foreground_after = int(user32.GetForegroundWindow())
    if foreground_after != foreground_before:
        charts.removeByName(name)
        raise RuntimeError("Calc tried to take focus; Wisp rolled the chart back.")
    if not charts.hasByName(name):
        raise RuntimeError("Calc did not retain the new chart.")
    return {
        "ok": True,
        "name": name,
        "message": f"Created a vertical bar chart from {address}.",
        "verification": [
            "Chart exists in the matching open Calc document.",
            "Source cells match the preview fingerprint.",
            "Foreground focus did not change.",
        ],
        "focus_unchanged": True,
    }


def _undo_manager(document):
    manager = document.getUndoManager()
    if manager is None:
        raise RuntimeError("Calc did not expose its undo manager.")
    return manager


def _rollback_latest(manager, source, before) -> None:
    if not manager.isUndoPossible():
        raise RuntimeError("Calc could not roll back the failed action.")
    manager.undo()
    if tuple(tuple(row) for row in source.getDataArray()) != before:
        raise RuntimeError("Calc rollback did not restore the selected cells.")


def _format_state(source, row_count: int, column_count: int):
    header = tuple(
        (
            int(source.getCellByPosition(column, 0).CellBackColor),
            int(source.getCellByPosition(column, 0).CharColor),
            float(source.getCellByPosition(column, 0).CharWeight),
        )
        for column in range(column_count)
    )
    widths = tuple(int(source.Columns.getByIndex(column).Width) for column in range(column_count))
    number_formats = tuple(
        tuple(int(source.getCellByPosition(column, row).NumberFormat) for column in range(column_count))
        for row in range(row_count)
    )
    return header, widths, number_formats


def apply_format_table(
    *,
    port: int,
    pipe_name: str,
    title: str,
    address: str,
    fingerprint: str,
    has_header: bool,
) -> dict:
    """Apply presentation-only table formatting and verify cell contents."""
    user32 = ctypes.windll.user32
    foreground_before = int(user32.GetForegroundWindow())
    document = _find_document(_desktop(port=port, pipe_name=pipe_name), title)
    sheet = document.CurrentController.ActiveSheet
    source = sheet.getCellRangeByName(address)
    before = tuple(tuple(row) for row in source.getDataArray())
    before_formulas = tuple(tuple(row) for row in source.getFormulaArray())
    if _fingerprint(before, before_formulas) != fingerprint:
        raise RuntimeError("Calc data changed after the preview; refusing to apply.")
    before_format_state = _format_state(source, len(before), len(before[0]))

    manager = _undo_manager(document)
    context_open = False
    mutated = False
    try:
        manager.enterUndoContext("Wisp: clean up table")
        context_open = True
        if has_header:
            header = source.getCellRangeByPosition(0, 0, len(before[0]) - 1, 0)
            mutated = True
            header.CellBackColor = 0x2F6F7E
            header.CharColor = 0xFFFFFF
            header.CharWeight = 150.0
        mutated = True
        source.Columns.OptimalWidth = True
        manager.leaveUndoContext()
        context_open = False

        if tuple(tuple(row) for row in source.getDataArray()) != before:
            raise RuntimeError("Calc changed cell contents while formatting the table.")
        if tuple(tuple(row) for row in source.getFormulaArray()) != before_formulas:
            raise RuntimeError("Calc changed formulas while formatting the table.")
        after_format_state = _format_state(source, len(before), len(before[0]))
        if after_format_state[2] != before_format_state[2]:
            raise RuntimeError("Calc changed number formats while formatting the table.")
        if has_header:
            verified_header = source.getCellRangeByPosition(0, 0, len(before[0]) - 1, 0)
            if int(verified_header.CellBackColor) != 0x2F6F7E or float(verified_header.CharWeight) < 140:
                raise RuntimeError("Calc did not retain the reviewed header formatting.")
        foreground_after = int(user32.GetForegroundWindow())
        if foreground_after != foreground_before:
            raise RuntimeError("Calc took focus while formatting the table.")
    except Exception as original_error:
        if context_open:
            manager.leaveUndoContext()
        if mutated:
            _rollback_latest(manager, source, before)
            if tuple(tuple(row) for row in source.getFormulaArray()) != before_formulas:
                raise RuntimeError("Calc rollback did not restore the selected formulas.") from original_error
            if _format_state(source, len(before), len(before[0])) != before_format_state:
                raise RuntimeError(
                    "Calc rollback did not restore the previous table formatting."
                ) from original_error
        raise

    return {
        "ok": True,
        "message": f"Formatted {address} as a clean table without changing its contents.",
        "journal": [{"kind": "formatting", "range": address, "rollback": "calc_undo"}],
        "verification": [
            "Cell values and formulas still match the preview fingerprint.",
            "Reviewed header and column sizing were retained.",
            "Foreground focus did not change.",
        ],
        "focus_unchanged": True,
    }


def _sort_rows(values, column: int, descending: bool):
    header = values[:1]
    rows = list(values[1:])

    def key(row):
        value = row[column]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return 0, float(value)
        return 1, str(value).casefold()

    rows.sort(key=key, reverse=descending)
    return tuple(header) + tuple(rows)


def apply_sort_range(
    *,
    port: int,
    pipe_name: str,
    title: str,
    address: str,
    fingerprint: str,
    sort_column: int,
    descending: bool,
    has_header: bool,
) -> dict:
    """Sort complete selected rows by one selected column and verify the order."""
    user32 = ctypes.windll.user32
    foreground_before = int(user32.GetForegroundWindow())
    document = _find_document(_desktop(port=port, pipe_name=pipe_name), title)
    sheet = document.CurrentController.ActiveSheet
    source = sheet.getCellRangeByName(address)
    before = tuple(tuple(row) for row in source.getDataArray())
    before_formulas = tuple(tuple(row) for row in source.getFormulaArray())
    if _fingerprint(before, before_formulas) != fingerprint:
        raise RuntimeError("Calc data changed after the preview; refusing to apply.")
    if not has_header or len(before) < 2 or not before[0] or not 0 <= sort_column < len(before[0]):
        raise RuntimeError("The reviewed sort range or header is invalid.")
    if any(str(formula).startswith("=") for row in before_formulas[1:] for formula in row):
        raise RuntimeError("Sorting selected rows containing formulas is not yet supported safely.")
    expected = _sort_rows(before, sort_column, descending)

    descriptor = list(source.createSortDescriptor())
    sort_field = uno.createUnoStruct("com.sun.star.table.TableSortField")
    sort_field.Field = sort_column
    sort_field.IsAscending = not descending
    for prop in descriptor:
        if prop.Name == "ContainsHeader":
            prop.Value = True
        elif prop.Name in {"SortColumns", "IsSortColumns"}:
            prop.Value = False
        elif prop.Name == "SortAscending":
            prop.Value = not descending
        elif prop.Name == "SortFields":
            prop.Value = uno.Any("[]com.sun.star.table.TableSortField", (sort_field,))

    manager = _undo_manager(document)
    context_open = False
    mutated = False
    try:
        manager.enterUndoContext("Wisp: sort selected rows")
        context_open = True
        mutated = True
        source.sort(tuple(descriptor))
        manager.leaveUndoContext()
        context_open = False
        after = tuple(tuple(row) for row in source.getDataArray())
        if after != expected:
            raise RuntimeError("Calc produced a different row order than the approved preview.")
        foreground_after = int(user32.GetForegroundWindow())
        if foreground_after != foreground_before:
            raise RuntimeError("Calc took focus while sorting the selected rows.")
    except Exception:
        if context_open:
            manager.leaveUndoContext()
        if mutated:
            _rollback_latest(manager, source, before)
        raise

    direction = "descending" if descending else "ascending"
    return {
        "ok": True,
        "message": f"Sorted {address} by the reviewed column in {direction} order.",
        "journal": [{"kind": "row_sort", "range": address, "rollback": "calc_undo"}],
        "verification": [
            "Complete rows match the approved preview order.",
            "The header row stayed in place.",
            "Foreground focus did not change.",
        ],
        "focus_unchanged": True,
    }


def _content_at(values, formulas, row: int, column: int):
    formula = formulas[row][column]
    if isinstance(formula, str) and formula.startswith("="):
        return "formula", formula
    return "value", values[row][column]


def _set_cell_content(cell, kind: str, value) -> None:
    if kind == "formula":
        cell.setFormula(value)
    elif value is None or value == "":
        cell.setString("")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        cell.setValue(float(value))
    elif isinstance(value, str):
        cell.setString(value)
    else:
        raise RuntimeError("A reviewed Calc cleanup value has an unsupported type.")


def _cleanup_readback_matches(before, before_formulas, after, after_formulas, changes) -> bool:
    changed = {
        (int(item["row_offset"]), int(item["column_offset"])): item
        for item in changes
    }
    for row in range(len(before)):
        for column in range(len(before[row])):
            change = changed.get((row, column))
            before_kind, _before_content = _content_at(before, before_formulas, row, column)
            after_kind, after_content = _content_at(after, after_formulas, row, column)
            if change is None:
                if before_formulas[row][column] != after_formulas[row][column]:
                    return False
                if before_kind == "value" and before[row][column] != after[row][column]:
                    return False
            elif after_kind != change["after_kind"]:
                return False
            elif change["after_kind"] == "value" and change["after_value"] is None:
                if after_content not in (None, ""):
                    return False
            elif after_content != change["after_value"]:
                return False
    return True


def apply_clean_range(
    *,
    port: int,
    pipe_name: str,
    title: str,
    address: str,
    fingerprint: str,
    changes,
) -> dict:
    """Apply one exact cell cleanup set inside a single native Calc undo context."""
    user32 = ctypes.windll.user32
    foreground_before = int(user32.GetForegroundWindow())
    document = _find_document(_desktop(port=port, pipe_name=pipe_name), title)
    sheet = document.CurrentController.ActiveSheet
    source = sheet.getCellRangeByName(address)
    before = tuple(tuple(row) for row in source.getDataArray())
    before_formulas = tuple(tuple(row) for row in source.getFormulaArray())
    if _fingerprint(before, before_formulas) != fingerprint:
        raise RuntimeError("Calc data changed after the preview; refusing to apply.")
    if not isinstance(changes, list) or not 1 <= len(changes) <= 32:
        raise RuntimeError("Calc cleanup requires between 1 and 32 reviewed cell changes.")

    seen = set()
    for change in changes:
        if not isinstance(change, dict):
            raise RuntimeError("Each Calc cleanup change must be structured.")
        row = change.get("row_offset")
        column = change.get("column_offset")
        if (
            not isinstance(row, int)
            or isinstance(row, bool)
            or not isinstance(column, int)
            or isinstance(column, bool)
            or not 0 <= row < len(before)
            or not 0 <= column < len(before[0])
            or (row, column) in seen
        ):
            raise RuntimeError("A reviewed Calc cleanup target is invalid or duplicated.")
        seen.add((row, column))
        before_kind, before_value = _content_at(before, before_formulas, row, column)
        if change.get("before_kind") != before_kind or change.get("before_value") != before_value:
            raise RuntimeError("A Calc cleanup cell no longer matches its reviewed before-content.")
        after_kind = change.get("after_kind")
        after_value = change.get("after_value")
        if after_kind not in {"value", "formula"}:
            raise RuntimeError("A reviewed Calc cleanup content type is invalid.")
        if after_kind == "formula" and (
            not isinstance(after_value, str)
            or not after_value.startswith("=")
            or len(after_value) > 512
        ):
            raise RuntimeError("A reviewed Calc cleanup formula is invalid.")
        if before_kind == "formula" and after_kind == "value" and change.get("replace_formula") is not True:
            raise RuntimeError("Replacing a Calc formula with a value was not explicitly reviewed.")

    manager = _undo_manager(document)
    context_open = False
    mutated = False
    try:
        manager.enterUndoContext("Wisp: apply reviewed cell cleanup")
        context_open = True
        for change in changes:
            cell = source.getCellByPosition(change["column_offset"], change["row_offset"])
            mutated = True
            _set_cell_content(cell, change["after_kind"], change.get("after_value"))
        manager.leaveUndoContext()
        context_open = False

        after = tuple(tuple(row) for row in source.getDataArray())
        after_formulas = tuple(tuple(row) for row in source.getFormulaArray())
        if not _cleanup_readback_matches(before, before_formulas, after, after_formulas, changes):
            raise RuntimeError("Calc did not retain the exact reviewed cleanup contents.")
        if int(user32.GetForegroundWindow()) != foreground_before:
            raise RuntimeError("Calc took focus while applying the reviewed cleanup.")
    except Exception as original_error:
        if context_open:
            manager.leaveUndoContext()
        if mutated:
            _rollback_latest(manager, source, before)
            if tuple(tuple(row) for row in source.getFormulaArray()) != before_formulas:
                raise RuntimeError("Calc cleanup rollback did not restore formulas.") from original_error
        raise

    return {
        "ok": True,
        "message": f"Applied {len(changes)} reviewed cell cleanup changes in {address}.",
        "journal": [{"kind": "cell_cleanup", "range": address, "rollback": "calc_undo"}],
        "verification": [
            "Every reviewed cell matches its exact proposed content.",
            "Every unreviewed value and formula in the selected range is unchanged.",
            "The cleanup is one native Calc Undo item and foreground focus did not change.",
        ],
        "focus_unchanged": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--port", type=int, default=0)
    endpoint.add_argument("--pipe", dest="pipe_name", default="")
    parser.add_argument("--mode", choices=("apply", "probe", "snapshot"), default="apply")
    parser.add_argument(
        "--action",
        choices=("chart", "format_table", "sort_range", "clean_range"),
        default="chart",
    )
    parser.add_argument("--title", default="")
    parser.add_argument("--range", dest="address", default="")
    parser.add_argument("--fingerprint", default="")
    parser.add_argument("--chart-title", default="")
    parser.add_argument("--has-header", choices=("true", "false"), default="true")
    parser.add_argument("--sort-column", type=int, default=0)
    parser.add_argument("--sort-direction", choices=("ascending", "descending"), default="ascending")
    parser.add_argument("--changes-json", default="[]")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if args.mode == "probe":
            result = probe(port=args.port, pipe_name=args.pipe_name)
        elif args.mode == "snapshot":
            if not args.title or not args.address:
                raise ValueError("Snapshot mode requires title and range.")
            result = snapshot_range(
                port=args.port,
                pipe_name=args.pipe_name,
                title=args.title,
                address=args.address,
            )
        elif args.action == "chart":
            if not args.title or not args.address or not args.fingerprint:
                raise ValueError("Apply mode requires title, range, and fingerprint.")
            result = apply_chart(
                port=args.port,
                pipe_name=args.pipe_name,
                title=args.title,
                address=args.address,
                fingerprint=args.fingerprint,
                chart_title=args.chart_title,
            )
        elif args.action == "format_table":
            result = apply_format_table(
                port=args.port,
                pipe_name=args.pipe_name,
                title=args.title,
                address=args.address,
                fingerprint=args.fingerprint,
                has_header=args.has_header == "true",
            )
        elif args.action == "sort_range":
            result = apply_sort_range(
                port=args.port,
                pipe_name=args.pipe_name,
                title=args.title,
                address=args.address,
                fingerprint=args.fingerprint,
                sort_column=args.sort_column,
                descending=args.sort_direction == "descending",
                has_header=args.has_header == "true",
            )
        else:
            result = apply_clean_range(
                port=args.port,
                pipe_name=args.pipe_name,
                title=args.title,
                address=args.address,
                fingerprint=args.fingerprint,
                changes=json.loads(args.changes_json),
            )
    except Exception as exc:  # noqa: BLE001 - executable JSON boundary
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
