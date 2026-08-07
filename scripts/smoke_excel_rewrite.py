"""Disposable live Excel exact-cell Rewrite smoke test with screenshots."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.actions.adapters.excel import ExcelActionAdapter  # noqa: E402
from core.actions.adapters.excel.plans import build_cleanup_plan  # noqa: E402
from core.rewrite_spreadsheets import spreadsheet_rewrite_changes  # noqa: E402


def _capture(title: str, output: Path) -> None:
    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
            str(PROJECT_ROOT / "scripts" / "capture_window.py"),
            "--title",
            title,
            "--process",
            "EXCEL.EXE",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "rewrite_exact_evidence",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        return 2
    import pythoncom  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    application = win32com.client.DispatchEx("Excel.Application")
    workbook = None
    try:
        application.Visible = True
        workbook = application.Workbooks.Add()
        worksheet = workbook.ActiveSheet
        worksheet.Range("A1").Value2 = "rough"
        worksheet.Range("A1").Select()
        _capture(str(workbook.Name), args.output / "excel_before.png")
        adapter = ExcelActionAdapter(lambda: application)
        snapshot = adapter.snapshot()
        changes = spreadsheet_rewrite_changes(
            snapshot.values,
            snapshot.formulas,
            "clear",
            allow_boolean_values=True,
        )
        plan = build_cleanup_plan(snapshot, changes)
        result = adapter.execute(plan, confirmed=True, idempotency_key="excel-rewrite-smoke")
        readback = str(worksheet.Range("A1").Value2 or "")
        _capture(str(workbook.Name), args.output / "excel_after.png")
        payload = {
            "verified": bool(result.status == "applied" and result.verification and readback == "clear"),
            "readback": readback,
            "before": str(args.output / "excel_before.png"),
            "after": str(args.output / "excel_after.png"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["verified"] else 1
    finally:
        if workbook is not None:
            workbook.Close(False)
        application.Quit()


if __name__ == "__main__":
    raise SystemExit(main())
