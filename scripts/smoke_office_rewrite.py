"""Run a disposable live COM smoke test for exact Office Rewrite on Windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.rewrite_office import (  # noqa: E402 - script bootstraps repository imports
    PowerPointRewriteClient,
    WordRewriteClient,
    build_powerpoint_rewrite_plan,
    build_word_rewrite_plan,
)


def _capture(title: str, process: str, output: Path) -> None:
    completed = subprocess.run(
        [
            str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"),
            str(PROJECT_ROOT / "scripts" / "capture_window.py"),
            "--title",
            title,
            "--process",
            process,
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


def _word_smoke(win32com: Any, output: Path) -> dict[str, Any]:
    application = win32com.client.DispatchEx("Word.Application")
    document = None
    try:
        application.Visible = True
        document = application.Documents.Add()
        document.Content.Text = "A rough sentence."
        document.Range(2, 7).Select()
        _capture(str(document.Name), "WINWORD.EXE", output / "word_before.png")
        client = WordRewriteClient(lambda: application)
        snapshot = client.inspect_selection(
            {"process_name": "winword.exe", "name": "Document - Microsoft Word"}
        )
        applied = client.apply(build_word_rewrite_plan(snapshot, "clear"))
        readback = str(document.Content.Text or "").rstrip("\r\x07")
        _capture(str(document.Name), "WINWORD.EXE", output / "word_after.png")
        return {
            "applied": applied,
            "selected": snapshot.selected_text,
            "readback": readback,
            "verified": readback == "A clear sentence.",
            "before": str(output / "word_before.png"),
            "after": str(output / "word_after.png"),
        }
    finally:
        if document is not None:
            document.Close(0)
        application.Quit()


def _powerpoint_smoke(win32com: Any, output: Path) -> dict[str, Any]:
    application = win32com.client.DispatchEx("PowerPoint.Application")
    presentation = None
    try:
        application.Visible = True
        presentation = application.Presentations.Add()
        slide = presentation.Slides.Add(1, 12)
        shape = slide.Shapes.AddTextbox(1, 40, 40, 600, 100)
        shape.TextFrame.TextRange.Text = "Revenue was good"
        shape.TextFrame.TextRange.Characters(13, 4).Select()
        _capture(
            str(presentation.Name),
            "POWERPNT.EXE",
            output / "powerpoint_before.png",
        )
        client = PowerPointRewriteClient(lambda: application)
        snapshot = client.inspect_selection(
            {"process_name": "powerpnt.exe", "name": "Presentation - PowerPoint"}
        )
        applied = client.apply(build_powerpoint_rewrite_plan(snapshot, "strong"))
        readback = str(shape.TextFrame.TextRange.Text or "")
        _capture(
            str(presentation.Name),
            "POWERPNT.EXE",
            output / "powerpoint_after.png",
        )
        return {
            "applied": applied,
            "selected": snapshot.selected_text,
            "readback": readback,
            "verified": readback == "Revenue was strong",
            "before": str(output / "powerpoint_before.png"),
            "after": str(output / "powerpoint_after.png"),
        }
    finally:
        if presentation is not None:
            presentation.Close()
        application.Quit()


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
        print(json.dumps({"error": "Windows is required."}))
        return 2
    import pythoncom  # type: ignore[import-not-found]
    import win32com  # type: ignore[import-not-found]
    import win32com.client  # type: ignore[import-not-found]

    pythoncom.CoInitialize()
    results: dict[str, Any] = {}
    for name, smoke in (("word", _word_smoke), ("powerpoint", _powerpoint_smoke)):
        try:
            results[name] = smoke(win32com, args.output)
        except Exception as exc:  # noqa: BLE001 - smoke test reports both apps
            results[name] = {"verified": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(bool(value.get("verified")) for value in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
