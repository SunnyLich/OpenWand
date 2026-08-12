"""Live VS Code saved-file exact Rewrite smoke test with screenshots."""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.actions.adapters.vscode import (  # noqa: E402
    VSCodeActionAdapter,
    VSCodeSelectionReader,
    build_replace_selection_plan,
)
from scripts.capture_window import _window_by_title, capture  # noqa: E402


def _await_window(title: str, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return _window_by_title(title, "Code.exe")
        except RuntimeError:
            time.sleep(0.25)
    raise RuntimeError("The isolated VS Code smoke window did not appear.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "rewrite_exact_evidence",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / "openwand_rewrite_smoke.py"
    source.write_text(
        'def greeting():\n    message = "rough value"\n    return message\n',
        encoding="utf-8",
    )
    executable = Path.home() / "AppData" / "Local" / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not executable.is_file():
        raise RuntimeError("VS Code is not installed in its standard user location.")
    subprocess.Popen(
        [
            str(executable),
            "--new-window",
            "--disable-extensions",
            "--user-data-dir",
            str(PROJECT_ROOT / ".tmp" / "vscode-rewrite-profile"),
            "--extensions-dir",
            str(PROJECT_ROOT / ".tmp" / "vscode-rewrite-extensions"),
            str(source),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    hwnd = _await_window(source.name)
    try:
        capture(source.name, args.output / "vscode_before.png", "Code.exe")
        active_app = {
            "process_name": "Code.exe",
            "name": f"{source.name} - Visual Studio Code",
            "document_path": str(source),
            "window_id": hwnd,
        }
        snapshot = VSCodeSelectionReader().inspect_selection(active_app, "rough value")
        plan = build_replace_selection_plan(snapshot, "clear value")
        result = VSCodeActionAdapter().execute(
            plan,
            confirmed=True,
            idempotency_key="vscode-rewrite-smoke",
        )
        deadline = time.monotonic() + 8.0
        while "clear value" not in source.read_text(encoding="utf-8") and time.monotonic() < deadline:
            time.sleep(0.1)
        time.sleep(1.0)
        capture(source.name, args.output / "vscode_after.png", "Code.exe")
        readback = source.read_text(encoding="utf-8")
        payload = {
            "verified": bool(result.status == "applied" and '"clear value"' in readback),
            "readback": readback,
            "before": str(args.output / "vscode_before.png"),
            "after": str(args.output / "vscode_after.png"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["verified"] else 1
    finally:
        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE on only the test window


if __name__ == "__main__":
    raise SystemExit(main())
