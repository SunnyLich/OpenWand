"""Visible no-focus demo of Wisp editing a file shared with a separate app.

The demo intentionally uses Windows UI Automation rather than mouse or keyboard
input.  It opens two non-activating windows, edits the accessible text field in
the separate process, mirrors the resulting file in a Wisp-owned workspace, and
captures evidence without changing the real cursor position.
"""

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
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TARGET_TEXT = (
    "Wisp changed this shared file. Your mouse and keyboard stayed yours."
)


def _cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def _foreground_window() -> int:
    return int(ctypes.windll.user32.GetForegroundWindow())


def _show_without_activation(widget, x: int, y: int, width: int, height: int) -> None:
    """Show one of our demo windows while explicitly prohibiting activation."""
    widget.setGeometry(x, y, width, height)
    widget.show()
    hwnd = int(widget.winId())
    if sys.platform != "win32":
        return
    user32 = ctypes.windll.user32
    get_window_long = user32.GetWindowLongPtrW
    set_window_long = user32.SetWindowLongPtrW
    exstyle = int(get_window_long(hwnd, -20))
    # WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    set_window_long(hwnd, -20, exstyle | 0x00000080 | 0x08000000)
    # HWND_TOPMOST, SWP_NOACTIVATE | SWP_SHOWWINDOW
    user32.SetWindowPos(hwnd, -1, x, y, width, height, 0x0010 | 0x0040)


def _window_flags(Qt):
    return (
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.WindowDoesNotAcceptFocus
    )


def _run_external_app(
    handshake: Path,
    shared_file: Path,
    live_capture: Path,
    geometry: tuple[int, int, int, int],
) -> int:
    """Run the independent, accessibility-enabled target application."""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication(["wisp-presence-external-app"])
    app.setStyle("Fusion")
    window = QWidget(None)
    window.setWindowTitle("PlainText - shared-note.txt")
    window.setWindowFlags(_window_flags(Qt))
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.setStyleSheet(
        """
        QWidget#externalWindow { background: #f7f7f9; border: 1px solid #b9bdc9; }
        QFrame#titleBar { background: #eceef3; border: 0; border-bottom: 1px solid #c9ccd5; }
        QLabel#appTitle { color: #242631; font: 600 13px 'Segoe UI'; }
        QLabel#filePath { color: #6b6f7d; font: 11px 'Segoe UI'; }
        QLabel#appBadge { color: #265c43; background: #dff3e8; border: 1px solid #b5dfc8;
                          border-radius: 10px; padding: 3px 9px; font: 600 9px 'Segoe UI'; }
        QLabel#section { color: #5e6370; font: 600 10px 'Segoe UI'; }
        QLabel#hint { color: #777c88; font: 10px 'Segoe UI'; }
        QLabel#saved { color: #276847; font: 600 10px 'Segoe UI'; }
        QLineEdit#documentEditor { background: white; color: #20232a; border: 1px solid #aeb4c2;
                                   border-radius: 5px; padding: 14px; font: 14px 'Segoe UI'; }
        """
    )
    window.setObjectName("externalWindow")
    root = QVBoxLayout(window)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    title_bar = QFrame(window)
    title_bar.setObjectName("titleBar")
    title_layout = QHBoxLayout(title_bar)
    title_layout.setContentsMargins(18, 11, 18, 11)
    app_title = QLabel("PlainText", title_bar)
    app_title.setObjectName("appTitle")
    path_label = QLabel("shared-note.txt", title_bar)
    path_label.setObjectName("filePath")
    badge = QLabel("NO EXTENSION", title_bar)
    badge.setObjectName("appBadge")
    title_layout.addWidget(app_title)
    title_layout.addWidget(path_label)
    title_layout.addStretch(1)
    title_layout.addWidget(badge)
    root.addWidget(title_bar)

    content = QWidget(window)
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(26, 24, 26, 26)
    content_layout.setSpacing(12)
    section = QLabel("DOCUMENT CONTENTS", content)
    section.setObjectName("section")
    content_layout.addWidget(section)
    editor = QLineEdit("Waiting for Wisp to update the shared file...", content)
    editor.setObjectName("documentEditor")
    editor.setAccessibleName("Document contents")
    editor.setMinimumHeight(58)
    editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    content_layout.addWidget(editor)
    hint = QLabel(
        "This is another process. Wisp talks to its standard Windows accessibility interface.",
        content,
    )
    hint.setWordWrap(True)
    hint.setObjectName("hint")
    content_layout.addWidget(hint)
    content_layout.addStretch(1)
    saved = QLabel("Ready · file is shared on disk", content)
    saved.setObjectName("saved")
    content_layout.addWidget(saved)
    root.addWidget(content, 1)

    def save_text(value: str) -> None:
        shared_file.write_text(value + "\n", encoding="utf-8")
        saved.setText("Saved just now · visible to Wisp")
        QTimer.singleShot(0, lambda: editor.setCursorPosition(0))
        if value == TARGET_TEXT:
            QTimer.singleShot(250, lambda: window.grab().save(str(live_capture), "PNG"))

    editor.textChanged.connect(save_text)
    save_text(editor.text())
    _show_without_activation(window, *geometry)
    app.processEvents()
    handshake.write_text(
        json.dumps({"hwnd": int(window.winId()), "pid": os.getpid()}),
        encoding="utf-8",
    )
    return app.exec()


class DemoResult:
    def __init__(self) -> None:
        self.exit_code = 1
        self.payload: dict[str, object] = {}


def _run_parent(output_directory: Path) -> int:
    if sys.platform != "win32":
        print(json.dumps({"ok": False, "error": "This visual demo currently requires Windows."}))
        return 2

    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QVBoxLayout,
        QWidget,
    )

    from core.actions.interaction import (
        Bounds,
        InteractionDriver,
        OperationType,
        SemanticOperation,
        StateCondition,
        StateField,
        WindowsUIAutomationBackend,
    )
    from ui.ghost_cursor import GhostCursorOverlay

    class WorkspaceWindow(QWidget):
        def __init__(self, shared_file: Path) -> None:
            super().__init__(None)
            self.shared_file = shared_file
            self.setWindowTitle("Wisp Shared Workspace")
            self.setWindowFlags(_window_flags(Qt))
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.setObjectName("workspaceWindow")
            self.setStyleSheet(
                """
                QWidget#workspaceWindow { background: #10131b; border: 1px solid #34394a; }
                QFrame#titleBar { background: #171b27; border: 0; border-bottom: 1px solid #30364a; }
                QLabel#brand { color: #f3efff; font: 700 13px 'Segoe UI'; }
                QLabel#workspaceName { color: #a8adc0; font: 11px 'Segoe UI'; }
                QLabel#liveBadge { color: #d9ffe9; background: #164a36; border: 1px solid #2b7255;
                                   border-radius: 10px; padding: 3px 9px; font: 600 9px 'Segoe UI'; }
                QLabel#eyebrow { color: #8f96aa; font: 600 9px 'Segoe UI'; }
                QLabel#fileName { color: #f5f2ff; background: #25213a; border-left: 3px solid #a663ff;
                                  padding: 10px; font: 600 11px 'Segoe UI'; }
                QLabel#path { color: #767e94; font: 9px 'Segoe UI'; }
                QPlainTextEdit#sharedEditor { background: #0c0f16; color: #e8eaf0; border: 1px solid #32384a;
                                              border-radius: 5px; padding: 13px; font: 12px 'Cascadia Mono'; }
                """
            )
            root = QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)

            title_bar = QFrame(self)
            title_bar.setObjectName("titleBar")
            title_layout = QHBoxLayout(title_bar)
            title_layout.setContentsMargins(18, 11, 18, 11)
            brand = QLabel("WISP", title_bar)
            brand.setObjectName("brand")
            workspace_name = QLabel("Shared Workspace", title_bar)
            workspace_name.setObjectName("workspaceName")
            badge = QLabel("LIVE FILE", title_bar)
            badge.setObjectName("liveBadge")
            title_layout.addWidget(brand)
            title_layout.addWidget(workspace_name)
            title_layout.addStretch(1)
            title_layout.addWidget(badge)
            root.addWidget(title_bar)

            body = QWidget(self)
            body_layout = QHBoxLayout(body)
            body_layout.setContentsMargins(18, 18, 18, 18)
            body_layout.setSpacing(16)

            files = QFrame(body)
            files.setFixedWidth(190)
            files_layout = QVBoxLayout(files)
            files_layout.setContentsMargins(0, 0, 0, 0)
            files_layout.setSpacing(8)
            files_heading = QLabel("SHARED FILES", files)
            files_heading.setObjectName("eyebrow")
            files_layout.addWidget(files_heading)
            file_name = QLabel("▰  shared-note.txt", files)
            file_name.setObjectName("fileName")
            files_layout.addWidget(file_name)
            path = QLabel("Real file on disk\nAuto-refresh enabled", files)
            path.setObjectName("path")
            path.setWordWrap(True)
            files_layout.addWidget(path)
            files_layout.addStretch(1)
            body_layout.addWidget(files)

            center = QFrame(body)
            center_layout = QVBoxLayout(center)
            center_layout.setContentsMargins(0, 0, 0, 0)
            center_layout.setSpacing(8)
            editor_heading = QLabel("SHARED-NOTE.TXT  ·  LIVE CONTENT", center)
            editor_heading.setObjectName("eyebrow")
            center_layout.addWidget(editor_heading)
            self.editor = QPlainTextEdit(center)
            self.editor.setObjectName("sharedEditor")
            self.editor.setReadOnly(True)
            self.editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            center_layout.addWidget(self.editor, 1)
            body_layout.addWidget(center, 1)

            root.addWidget(body, 1)

        def refresh(self) -> None:
            text = self.shared_file.read_text(encoding="utf-8").rstrip()
            self.editor.setPlainText(text)

    output_directory.mkdir(parents=True, exist_ok=False)
    shared_file = output_directory / "shared-note.txt"
    external_capture = output_directory / "external-app-live.png"
    screenshot_file = output_directory / "wisp-shared-presence-demo.png"
    evidence_file = output_directory / "evidence.json"

    app = QApplication(["wisp-shared-presence-demo"])
    app.setStyle("Fusion")
    screen = app.primaryScreen()
    available = screen.availableGeometry()
    margin = 28
    gap = 46
    height = min(610, available.height() - margin * 2)
    workspace_width = min(760, max(590, (available.width() - gap - margin * 2) * 55 // 100))
    external_width = min(610, available.width() - workspace_width - gap - margin * 2)
    external_width = max(480, external_width)
    total_width = workspace_width + gap + external_width
    start_x = available.x() + max(margin, (available.width() - total_width) // 2)
    start_y = available.y() + max(margin, (available.height() - height) // 2)
    workspace_geometry = (start_x, start_y, workspace_width, height)
    external_geometry = (start_x + workspace_width + gap, start_y + 70, external_width, height - 140)

    foreground_before = _foreground_window()
    cursor_before = _cursor_position()
    focus_checkpoints = [foreground_before]
    child: subprocess.Popen[str] | None = None
    child_hwnd = 0
    result = DemoResult()

    with tempfile.TemporaryDirectory(prefix="wisp-presence-demo-") as temp_dir:
        handshake = Path(temp_dir) / "external-window.json"
        environment = dict(os.environ)
        environment["QT_QPA_PLATFORM"] = "windows"
        child = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--external-app",
                str(handshake),
                str(shared_file),
                str(external_capture),
                *(str(value) for value in external_geometry),
            ],
            cwd=REPO_ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
        )
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline and not handshake.is_file():
                if child.poll() is not None:
                    break
                time.sleep(0.05)
            if not handshake.is_file():
                error = child.stderr.read() if child.stderr is not None else ""
                raise RuntimeError(error.strip() or "The external demo app did not start.")

            child_details = json.loads(handshake.read_text(encoding="utf-8"))
            child_hwnd = int(child_details["hwnd"])
            child_pid = int(child_details["pid"])
            focus_checkpoints.append(_foreground_window())

            workspace = WorkspaceWindow(shared_file)
            _show_without_activation(workspace, *workspace_geometry)
            app.processEvents()
            workspace.refresh()
            focus_checkpoints.append(_foreground_window())

            backend = WindowsUIAutomationBackend(mutation_process_ids={child_pid})
            snapshots = backend.inspect_window(child_hwnd, max_depth=7, max_nodes=120)
            target = next(
                item
                for item in snapshots
                if item["role"] == "edit" and item["name"] == "Document contents"
            )
            driver = InteractionDriver((backend,))
            receipt = driver.execute(
                SemanticOperation(
                    "update-shared-note",
                    OperationType.SET_VALUE,
                    target["locator"],
                    {"value": TARGET_TEXT},
                    preconditions=(
                        StateCondition(
                            StateField.VALUE,
                            "Waiting for Wisp to update the shared file...",
                        ),
                    ),
                )
            )
            focus_checkpoints.append(_foreground_window())

            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                app.processEvents()
                if (
                    shared_file.is_file()
                    and shared_file.read_text(encoding="utf-8").rstrip() == TARGET_TEXT
                    and external_capture.is_file()
                ):
                    break
                time.sleep(0.05)
            workspace.refresh()

            locator_bounds = target["locator"].bounds
            if locator_bounds is None:
                raise RuntimeError("The external app did not expose screen bounds for its editor.")
            presence = GhostCursorOverlay()
            marker_bounds = Bounds(
                locator_bounds.x + 18,
                locator_bounds.y + max(1, locator_bounds.height // 2 - 2),
                4,
                4,
            )
            presence.show_text_caret(marker_bounds, "Wisp agent")
            app.processEvents()
            focus_checkpoints.append(_foreground_window())

            # Give the window compositor enough time to paint both processes and the overlay.
            paint_deadline = time.monotonic() + 0.9
            while time.monotonic() < paint_deadline:
                app.processEvents()
                time.sleep(0.02)

            if not external_capture.is_file():
                raise RuntimeError("The external app did not provide its live painted surface.")
            origin_x = min(workspace_geometry[0], external_geometry[0]) - 12
            origin_y = min(workspace_geometry[1], external_geometry[1]) - 12
            canvas_width = (
                max(
                    workspace_geometry[0] + workspace_geometry[2],
                    external_geometry[0] + external_geometry[2],
                )
                - origin_x
                + 12
            )
            canvas_height = (
                max(
                    workspace_geometry[1] + workspace_geometry[3],
                    external_geometry[1] + external_geometry[3],
                )
                - origin_y
                + 12
            )
            pixmap = QPixmap(canvas_width, canvas_height)
            pixmap.fill(QColor("#080a10"))
            painter = QPainter(pixmap)
            painter.drawPixmap(
                QRect(
                    workspace_geometry[0] - origin_x,
                    workspace_geometry[1] - origin_y,
                    workspace_geometry[2],
                    workspace_geometry[3],
                ),
                workspace.grab(),
            )
            painter.drawPixmap(
                QRect(
                    external_geometry[0] - origin_x,
                    external_geometry[1] - origin_y,
                    external_geometry[2],
                    external_geometry[3],
                ),
                QPixmap(str(external_capture)),
            )
            painter.drawPixmap(
                QRect(presence.x() - origin_x, presence.y() - origin_y, presence.width(), presence.height()),
                presence.grab(),
            )
            painter.end()
            if pixmap.isNull() or not pixmap.save(str(screenshot_file), "PNG"):
                raise RuntimeError("The completed demo could not be captured.")
            focus_checkpoints.append(_foreground_window())

            cursor_after = _cursor_position()
            foreground_after = _foreground_window()
            payload = {
                "ok": True,
                "focus_unchanged": all(item == foreground_before for item in focus_checkpoints)
                and foreground_after == foreground_before,
                "cursor_unchanged": cursor_after == cursor_before,
                "cursor_control_used": False,
                "physical_input_used": False,
                "separate_process": child_pid != os.getpid(),
                "extension_installed": False,
                "semantic_method": receipt.output.get("semantic_method"),
                "shared_file_updated": shared_file.read_text(encoding="utf-8").rstrip() == TARGET_TEXT,
                "screenshot_capture": "live window surfaces only",
                "screenshot": str(screenshot_file.resolve()),
                "shared_file": str(shared_file.resolve()),
            }
            evidence_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            result.payload = payload
            result.exit_code = 0 if all(
                (
                    payload["focus_unchanged"],
                    payload["shared_file_updated"],
                )
            ) else 1
            presence.clear()
            presence.close()
            workspace.close()
            app.processEvents()
        except Exception as exc:
            result.payload = {"ok": False, "error": str(exc), "output_directory": str(output_directory)}
            evidence_file.write_text(json.dumps(result.payload, indent=2), encoding="utf-8")
        finally:
            if child_hwnd:
                ctypes.windll.user32.PostMessageW(child_hwnd, 0x0010, 0, 0)
            if child is not None:
                try:
                    child.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait(timeout=3.0)

    print(json.dumps(result.payload, ensure_ascii=False))
    return result.exit_code


def _new_output_directory(requested: Path | None) -> Path:
    if requested is not None:
        return requested.resolve()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return (REPO_ROOT / "outputs" / f"presence-demo-{stamp}").resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--external-app",
        nargs=7,
        metavar=("HANDSHAKE", "FILE", "CAPTURE", "X", "Y", "W", "H"),
    )
    args = parser.parse_args()
    if args.external_app:
        handshake, shared_file, live_capture, x, y, width, height = args.external_app
        return _run_external_app(
            Path(handshake),
            Path(shared_file),
            Path(live_capture),
            (int(x), int(y), int(width), int(height)),
        )
    return _run_parent(_new_output_directory(args.output_dir))


if __name__ == "__main__":
    raise SystemExit(main())
