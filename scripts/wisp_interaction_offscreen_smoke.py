"""Exercise semantic UIA editing in a Wisp-owned off-screen form without OS input."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _child(handshake: Path) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QCheckBox, QFormLayout, QLineEdit, QWidget

    app = QApplication(["wisp-offscreen-interaction-smoke"])
    form = QWidget(None)
    form.setWindowTitle("Wisp semantic interaction smoke")
    form.setWindowFlags(
        Qt.WindowType.Tool
        | Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowDoesNotAcceptFocus
    )
    form.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    layout = QFormLayout(form)
    display_name = QLineEdit("Before", form)
    display_name.setObjectName("wispSmokeDisplayName")
    display_name.setAccessibleName("Display name")
    hints = QCheckBox("Enable hints", form)
    hints.setObjectName("wispSmokeEnableHints")
    hints.setAccessibleName("Enable hints")
    layout.addRow("Display name", display_name)
    layout.addRow(hints)
    form.resize(360, 140)

    virtual = app.primaryScreen().virtualGeometry()
    form.move(virtual.right() + 1200, virtual.bottom() + 1200)
    form.show()
    app.processEvents()
    hwnd = int(form.winId())
    if sys.platform == "win32":
        # Preserve the off-screen placement and explicitly prohibit activation.
        ctypes.windll.user32.SetWindowPos(hwnd, 0, form.x(), form.y(), form.width(), form.height(), 0x0010)
    handshake.write_text(json.dumps({"hwnd": hwnd, "pid": os.getpid()}), encoding="utf-8")
    return app.exec()


def _cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def _parent() -> int:
    if sys.platform != "win32":
        print(json.dumps({"ok": False, "error": "This smoke experiment is Windows-only."}))
        return 2

    from core.actions.interaction import (
        InteractionDriver,
        OperationType,
        SemanticOperation,
        StateCondition,
        StateField,
        WindowsUIAutomationBackend,
    )

    user32 = ctypes.windll.user32
    foreground_before = int(user32.GetForegroundWindow())
    cursor_before = _cursor_position()
    child: subprocess.Popen[str] | None = None
    hwnd = 0
    with tempfile.TemporaryDirectory(prefix="wisp-interaction-smoke-") as temp_dir:
        handshake = Path(temp_dir) / "window.json"
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "windows"
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--child", str(handshake)],
            cwd=REPO_ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )
        try:
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline and not handshake.is_file():
                if child.poll() is not None:
                    break
                time.sleep(0.05)
            if not handshake.is_file():
                error = child.stderr.read() if child.stderr is not None else ""
                print(json.dumps({"ok": False, "error": error.strip() or "The test form did not start."}))
                return 1

            details = json.loads(handshake.read_text(encoding="utf-8"))
            hwnd = int(details["hwnd"])
            backend = WindowsUIAutomationBackend(mutation_process_ids={int(details["pid"])})
            snapshots = backend.inspect_window(hwnd, max_depth=6, max_nodes=80)
            display = next(
                item
                for item in snapshots
                if item["role"] == "edit" and item["name"] == "Display name"
            )
            hints = next(
                item
                for item in snapshots
                if item["role"] == "checkbox" and item["name"] == "Enable hints"
            )
            driver = InteractionDriver((backend,))
            value_receipt = driver.execute(
                SemanticOperation(
                    "set-display-name",
                    OperationType.SET_VALUE,
                    display["locator"],
                    {"value": "Changed semantically"},
                    preconditions=(StateCondition(StateField.VALUE, "Before"),),
                )
            )
            toggle_receipt = driver.execute(
                SemanticOperation(
                    "enable-hints",
                    OperationType.TOGGLE,
                    hints["locator"],
                    {"state": True},
                )
            )
            foreground_after = int(user32.GetForegroundWindow())
            cursor_after = _cursor_position()
            virtual_left = int(user32.GetSystemMetrics(76))
            virtual_top = int(user32.GetSystemMetrics(77))
            virtual_right = virtual_left + int(user32.GetSystemMetrics(78))
            virtual_bottom = virtual_top + int(user32.GetSystemMetrics(79))
            bounds = display["locator"].bounds
            result = {
                "ok": True,
                "window_offscreen": bool(
                    bounds.x >= virtual_right
                    or bounds.y >= virtual_bottom
                    or bounds.x + bounds.width <= virtual_left
                    or bounds.y + bounds.height <= virtual_top
                ),
                "focus_unchanged": foreground_after == foreground_before,
                "cursor_unchanged": cursor_after == cursor_before,
                "physical_input_used": False,
                "value_method": value_receipt.output.get("semantic_method"),
                "toggle_method": toggle_receipt.output.get("semantic_method"),
                "editable_values_redacted_in_inspection": display["value"] == "<redacted>",
            }
            print(json.dumps(result, ensure_ascii=False))
            return 0 if all((result["focus_unchanged"], result["cursor_unchanged"])) else 1
        finally:
            if hwnd:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE for our own child window.
            if child is not None:
                try:
                    child.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=3.0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    args = parser.parse_args()
    return _child(args.child) if args.child else _parent()


if __name__ == "__main__":
    raise SystemExit(main())
