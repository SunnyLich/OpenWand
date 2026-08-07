"""Disposable live Writer/Impress exact Rewrite smoke test for LibreOffice Python."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import uno  # type: ignore[import-not-found]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.helpers import calc_uno_action as calc_actions  # noqa: E402
from runtime.helpers import libreoffice_rewrite as rewrite  # noqa: E402


def _property(name: str, value):
    item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
    item.Name = name
    item.Value = value
    return item


def _set_title(document, title: str) -> str:
    """Give the disposable document a capture-safe, unique window title."""
    try:
        document.setTitle(title)
    except Exception:
        try:
            document.Title = title
        except Exception:
            pass
    return str(document.Title or title)


def _close_document(document) -> None:
    """Close a disposable smoke document without masking its test result."""
    try:
        document.setModified(False)
    except Exception:
        pass
    try:
        document.close(True)
    except Exception:
        try:
            document.dispose()
        except Exception:
            pass


def _capture(title: str, output: Path) -> None:
    time.sleep(0.8)
    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
            str(PROJECT_ROOT / "scripts" / "capture_window.py"),
            "--title",
            title,
            "--output",
            str(output),
            "--process",
            "soffice.bin",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())


def _writer_smoke(desktop, pipe_name: str, port: int, output: Path) -> dict:
    document = desktop.loadComponentFromURL("private:factory/swriter", "_blank", 0, ())
    try:
        capture_title = _set_title(document, "Wisp Rewrite Writer Smoke")
        document.Text.String = "A rough sentence."
        cursor = document.Text.createTextCursor()
        cursor.gotoStart(False)
        cursor.goRight(2, False)
        cursor.goRight(5, True)
        document.CurrentController.select(cursor)
        title = str(document.Title or "Untitled")
        _capture(capture_title, output / "writer_before.png")
        snapshot = rewrite._writer_snapshot(document, "rough")
        result = rewrite.apply(
            pipe_name,
            {"snapshot": snapshot, "replacement_text": "clear"},
            port=port,
        )
        readback = str(document.Text.String or "")
        _capture(capture_title, output / "writer_after.png")
        return {
            "verified": bool(result.get("ok") and readback == "A clear sentence."),
            "title": title,
            "readback": readback,
            "before": str(output / "writer_before.png"),
            "after": str(output / "writer_after.png"),
        }
    finally:
        _close_document(document)


def _impress_smoke(desktop, pipe_name: str, port: int, output: Path) -> dict:
    document = desktop.loadComponentFromURL(
        "private:factory/simpress",
        "_blank",
        0,
        (_property("Hidden", False),),
    )
    try:
        capture_title = _set_title(document, "Wisp Rewrite Impress Smoke")
        page = document.DrawPages.getByIndex(0)
        shape = document.createInstance("com.sun.star.drawing.TextShape")
        position = uno.createUnoStruct("com.sun.star.awt.Point")
        position.X, position.Y = 2500, 2500
        size = uno.createUnoStruct("com.sun.star.awt.Size")
        size.Width, size.Height = 18000, 3500
        shape.Position = position
        shape.Size = size
        page.add(shape)
        shape.String = "Revenue was good"
        document.CurrentController.setCurrentPage(page)
        document.CurrentController.select(shape)
        _capture(capture_title, output / "impress_before.png")
        snapshot = rewrite._impress_snapshot(document, "good")
        result = rewrite.apply(
            pipe_name,
            {"snapshot": snapshot, "replacement_text": "strong"},
            port=port,
        )
        readback = str(shape.String or "")
        _capture(capture_title, output / "impress_after.png")
        return {
            "verified": bool(result.get("ok") and readback == "Revenue was strong"),
            "readback": readback,
            "before": str(output / "impress_before.png"),
            "after": str(output / "impress_after.png"),
        }
    finally:
        _close_document(document)


def _calc_smoke(desktop, pipe_name: str, port: int, output: Path) -> dict:
    document = desktop.loadComponentFromURL("private:factory/scalc", "_blank", 0, ())
    try:
        capture_title = _set_title(document, "Wisp Rewrite Calc Smoke")
        sheet = document.Sheets.getByIndex(0)
        cell = sheet.getCellRangeByName("A1")
        cell.setString("rough")
        document.CurrentController.select(cell)
        title = str(document.Title or "Untitled")
        _capture(capture_title, output / "calc_before.png")
        snapshot = calc_actions.snapshot_range(
            port=port,
            pipe_name=pipe_name,
            title=title,
            address="A1",
        )
        result = calc_actions.apply_clean_range(
            port=port,
            pipe_name=pipe_name,
            title=title,
            address="A1",
            fingerprint=str(snapshot["fingerprint"]),
            changes=[
                {
                    "row_offset": 0,
                    "column_offset": 0,
                    "before_kind": "value",
                    "before_value": "rough",
                    "after_kind": "value",
                    "after_value": "clear",
                    "replace_formula": False,
                }
            ],
        )
        readback = str(cell.getString() or "")
        _capture(capture_title, output / "calc_after.png")
        return {
            "verified": bool(result.get("ok") and readback == "clear"),
            "readback": readback,
            "before": str(output / "calc_before.png"),
            "after": str(output / "calc_after.png"),
        }
    finally:
        _close_document(document)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    endpoint = parser.add_mutually_exclusive_group(required=True)
    endpoint.add_argument("--pipe", default="")
    endpoint.add_argument("--port", type=int, default=0)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    desktop = rewrite._desktop(args.pipe, args.port)
    anchor = desktop.loadComponentFromURL(
        "private:factory/swriter",
        "_blank",
        0,
        (_property("Hidden", True),),
    )
    results = {}
    try:
        for name, smoke in (
            ("writer", _writer_smoke),
            ("impress", _impress_smoke),
            ("calc", _calc_smoke),
        ):
            try:
                results[name] = smoke(desktop, args.pipe, args.port, args.output)
            except Exception as exc:
                results[name] = {"verified": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            anchor.close(True)
        except Exception:
            pass
        try:
            desktop.terminate()
        except Exception:
            # Closing the final Calc document can dispose an isolated desktop
            # before the explicit termination call reaches it.
            pass
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item.get("verified") for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
