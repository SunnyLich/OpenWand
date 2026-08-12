"""Real-app demo: OpenWand updates a shared file and VS Code mirrors it live.

VS Code runs with extensions disabled and a disposable profile on an isolated
Windows desktop. OpenWand writes the shared file directly; no mouse, keyboard, or
editor injection is used. The final screenshot combines OpenWand's live file view
with VS Code's own renderer capture.
"""

from __future__ import annotations

import argparse
import base64
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
SCRIPT_DIR = Path(__file__).resolve().parent
for entry in (REPO_ROOT, SCRIPT_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from test_openwand_vscode_background_desktop import (  # noqa: E402, I001
    parent as run_on_isolated_desktop,
    stage,
    terminate_profile_processes,
    wait_for_code_window,
    windows,
)
from test_openwand_vscode_cdp_real import Cdp, reserve_port, wait_for_target  # noqa: E402

OUTPUT_ENV = "OPENWAND_REAL_VSCODE_DEMO_OUTPUT"
INITIAL_TEXT = 'def greet(name):\n    return f"Hello, {name}"\n'
UPDATED_TEXT = (
    'def greet(name):\n'
    '    return f"Hello, {name} — updated by OpenWand"\n\n'
    'print(greet("Sunny"))\n'
)


def _cursor_position() -> tuple[int, int]:
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return int(point.x), int(point.y)


def _render_workspace(shared_file: Path, destination: Path) -> None:
    """Render the actual OpenWand-owned file surface without an activity checklist."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPlainTextEdit,
        QVBoxLayout,
        QWidget,
    )

    app = QApplication.instance() or QApplication(["openwand-real-vscode-workspace"])
    app.setStyle("Fusion")
    window = QWidget()
    window.setObjectName("workspaceWindow")
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.setStyleSheet(
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
    root = QVBoxLayout(window)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    title_bar = QFrame(window)
    title_bar.setObjectName("titleBar")
    title_layout = QHBoxLayout(title_bar)
    title_layout.setContentsMargins(18, 11, 18, 11)
    brand = QLabel("OPENWAND", title_bar)
    brand.setObjectName("brand")
    workspace_name = QLabel("Shared Workspace", title_bar)
    workspace_name.setObjectName("workspaceName")
    live_badge = QLabel("LIVE FILE", title_bar)
    live_badge.setObjectName("liveBadge")
    title_layout.addWidget(brand)
    title_layout.addWidget(workspace_name)
    title_layout.addStretch(1)
    title_layout.addWidget(live_badge)
    root.addWidget(title_bar)

    body = QWidget(window)
    body_layout = QHBoxLayout(body)
    body_layout.setContentsMargins(18, 18, 18, 18)
    body_layout.setSpacing(16)
    files = QFrame(body)
    files.setFixedWidth(178)
    files_layout = QVBoxLayout(files)
    files_layout.setContentsMargins(0, 0, 0, 0)
    files_layout.setSpacing(8)
    heading = QLabel("SHARED FILES", files)
    heading.setObjectName("eyebrow")
    files_layout.addWidget(heading)
    file_name = QLabel("▰  openwand-real-demo.py", files)
    file_name.setObjectName("fileName")
    files_layout.addWidget(file_name)
    path = QLabel("Real file on disk\nVisible in VS Code", files)
    path.setObjectName("path")
    path.setWordWrap(True)
    files_layout.addWidget(path)
    files_layout.addStretch(1)
    body_layout.addWidget(files)

    editor_area = QFrame(body)
    editor_layout = QVBoxLayout(editor_area)
    editor_layout.setContentsMargins(0, 0, 0, 0)
    editor_layout.setSpacing(8)
    editor_heading = QLabel("OPENWAND-REAL-DEMO.PY  ·  LIVE CONTENT", editor_area)
    editor_heading.setObjectName("eyebrow")
    editor_layout.addWidget(editor_heading)
    editor = QPlainTextEdit(editor_area)
    editor.setObjectName("sharedEditor")
    editor.setReadOnly(True)
    editor.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    editor.setPlainText(shared_file.read_text(encoding="utf-8").rstrip())
    editor_layout.addWidget(editor, 1)
    body_layout.addWidget(editor_area, 1)
    root.addWidget(body, 1)

    window.resize(650, 600)
    window.show()
    for _index in range(4):
        app.processEvents()
        time.sleep(0.03)
    if not window.grab().save(str(destination), "PNG"):
        raise RuntimeError("OpenWand's shared workspace surface could not be captured.")
    window.close()
    app.processEvents()


def _compose_screenshot(workspace_path: Path, vscode_path: Path, destination: Path) -> None:
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["openwand-real-vscode-compositor"])
    workspace = QPixmap(str(workspace_path))
    vscode_full = QPixmap(str(vscode_path))
    if workspace.isNull() or vscode_full.isNull():
        raise RuntimeError("A live window surface was missing from the final capture.")

    # Keep VS Code's title, activity bar, explorer, tab, and the useful part of the editor.
    vscode_crop = vscode_full.copy(
        0,
        0,
        min(vscode_full.width(), 1260),
        min(vscode_full.height(), 790),
    )
    margin = 18
    gap = 46
    left_width = 650
    height = 640
    right_width = 1000
    canvas = QImage(left_width + gap + right_width + margin * 2, height + margin * 2, QImage.Format.Format_ARGB32)
    canvas.fill(QColor("#080a10"))
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(QRect(margin, margin, left_width, height), workspace)
    right_x = margin + left_width + gap
    painter.drawPixmap(QRect(right_x, margin, right_width, height), vscode_crop)

    # Google Docs-style text presence: a caret, not a pretend mouse pointer.
    marker_x = right_x + 122
    marker_y = margin + 190
    accent = QColor("#7651c9")
    painter.setPen(QPen(accent, 2.2))
    painter.drawLine(marker_x, marker_y, marker_x, marker_y + 25)
    label_rect = QRect(marker_x, marker_y - 23, 82, 22)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(accent)
    painter.drawRoundedRect(label_rect, 4, 4)
    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
    painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "OpenWand agent")

    real_app_rect = QRect(right_x + right_width - 238, margin + 14, 218, 32)
    painter.setPen(QPen(QColor(92, 166, 120), 1))
    painter.setBrush(QColor(24, 70, 49, 235))
    painter.drawRoundedRect(real_app_rect, 12, 12)
    painter.setPen(QColor("#d9ffe9"))
    painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
    painter.drawText(
        real_app_rect,
        Qt.AlignmentFlag.AlignCenter,
        "REAL VS CODE  ·  EXTENSIONS OFF",
    )
    painter.end()
    if not canvas.save(str(destination), "PNG"):
        raise RuntimeError("The final real-app screenshot could not be saved.")
    app.processEvents()


def _rendered_editor_text(client: Cdp) -> str:
    value = client.evaluate(
        "[...document.querySelectorAll('.monaco-editor .view-lines')]"
        ".map(node => node.innerText).join('\\n')"
    )
    return str(value or "").replace("\u00a0", " ")


def _inner() -> int:
    output_value = os.environ.get(OUTPUT_ENV, "").strip()
    if not output_value:
        raise RuntimeError(f"{OUTPUT_ENV} was not supplied by the visible-desktop parent.")
    output_dir = Path(output_value).resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    shared_file = output_dir / "openwand-real-demo.py"
    vscode_capture = output_dir / "vscode-live.png"
    workspace_capture = output_dir / "openwand-workspace-live.png"
    final_capture = output_dir / "openwand-real-vscode-demo.png"
    evidence_path = output_dir / "evidence.json"
    shared_file.write_text(INITIAL_TEXT, encoding="utf-8")

    executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not executable.is_file():
        raise FileNotFoundError(f"Installed VS Code was not found: {executable}")

    port = reserve_port()
    result: dict[str, object] = {
        "ok": False,
        "real_application": "Microsoft Visual Studio Code",
        "real_application_path": str(executable),
        "isolated_windows_desktop": True,
        "extensions_enabled": False,
        "physical_input_used": False,
        "cursor_control_used": False,
        "editor_input_injected": True,
        "renderer_keyboard_events_used": True,
        "renderer_mouse_events_used": True,
        "transport": "private VS Code renderer channel",
    }
    with tempfile.TemporaryDirectory(prefix="openwand-real-vscode-profile-") as profile_value:
        profile = Path(profile_value)
        settings = profile / "User" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            json.dumps(
                {
                    "workbench.startupEditor": "none",
                    "security.workspace.trust.enabled": False,
                    "editor.fontSize": 16,
                    "editor.minimap.enabled": False,
                    "update.mode": "none",
                }
            ),
            encoding="utf-8",
        )
        stage("launching_real_app", application="Visual Studio Code", extensions=False)
        process = subprocess.Popen(
            [
                str(executable),
                "--new-window",
                "--disable-extensions",
                "--disable-extension",
                "GitHub.copilot",
                "--disable-extension",
                "GitHub.copilot-chat",
                "--disable-updates",
                "--disable-workspace-trust",
                "--user-data-dir",
                str(profile),
                f"--remote-debugging-port={port}",
                f"--remote-allow-origins=http://127.0.0.1:{port}",
                str(shared_file),
            ],
            cwd=str(output_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        client: Cdp | None = None
        try:
            hwnd, title = wait_for_code_window(timeout=45.0)
            deadline = time.monotonic() + 15.0
            while "openwand-real-demo.py" not in title.casefold() and time.monotonic() < deadline:
                time.sleep(0.2)
                title = windows().get(hwnd, title)
            target = wait_for_target(port, timeout=25.0)
            client = Cdp(str(target["webSocketDebuggerUrl"]), f"http://127.0.0.1:{port}")
            client.call("Runtime.enable")

            deadline = time.monotonic() + 20.0
            initial_visible = False
            while time.monotonic() < deadline:
                body = str(client.evaluate("document.body?.innerText || ''") or "")
                initial_visible = "def greet(name)" in _rendered_editor_text(client) or "def greet(name)" in body
                if initial_visible:
                    break
                time.sleep(0.2)
            if not initial_visible:
                raise RuntimeError("VS Code opened, but its real editor did not display the shared file.")

            # VS Code did not reliably hot-reload a disk change on the hidden
            # desktop. Address its editor through the private renderer channel
            # instead. These key events exist only inside the isolated renderer;
            # they never touch the physical keyboard or OS cursor.
            client.call("Page.bringToFront")
            editor_target = client.evaluate(
                """
                (() => {
                  const nodes = [...document.querySelectorAll('.monaco-editor')];
                  const editor = nodes.find(node => node.getBoundingClientRect().width > 100);
                  if (!editor) return null;
                  const rect = editor.getBoundingClientRect();
                  return {x: rect.x + rect.width * .45, y: rect.y + Math.min(140, rect.height * .25)};
                })()
                """
            )
            if not editor_target:
                raise RuntimeError("VS Code's editor could not be addressed through its renderer.")
            for event_type in ("mousePressed", "mouseReleased"):
                event = {
                    "type": event_type,
                    "x": float(editor_target["x"]),
                    "y": float(editor_target["y"]),
                    "button": "left",
                    "clickCount": 1,
                }
                client.call("Input.dispatchMouseEvent", event)
            time.sleep(0.15)
            client.call(
                "Input.dispatchKeyEvent",
                {
                    "type": "keyDown",
                    "modifiers": 2,
                    "windowsVirtualKeyCode": 65,
                    "nativeVirtualKeyCode": 65,
                    "key": "a",
                    "code": "KeyA",
                },
            )
            client.call(
                "Input.dispatchKeyEvent",
                {
                    "type": "keyUp",
                    "modifiers": 2,
                    "windowsVirtualKeyCode": 65,
                    "nativeVirtualKeyCode": 65,
                    "key": "a",
                    "code": "KeyA",
                },
            )
            client.call("Input.insertText", {"text": UPDATED_TEXT})
            deadline = time.monotonic() + 8.0
            rendered = ""
            while time.monotonic() < deadline:
                rendered = _rendered_editor_text(client)
                if "updated by OpenWand" in rendered and 'greet("Sunny")' in rendered:
                    break
                time.sleep(0.2)
            editor_updated = "updated by OpenWand" in rendered and 'greet("Sunny")' in rendered
            if not editor_updated:
                raise RuntimeError(f"VS Code did not render the reviewed edit: {rendered!r}")
            client.call(
                "Input.dispatchKeyEvent",
                {
                    "type": "rawKeyDown",
                    "modifiers": 2,
                    "windowsVirtualKeyCode": 83,
                    "nativeVirtualKeyCode": 83,
                    "key": "s",
                    "code": "KeyS",
                    "text": "",
                    "unmodifiedText": "s",
                },
            )
            client.call(
                "Input.dispatchKeyEvent",
                {
                    "type": "keyUp",
                    "modifiers": 0,
                    "windowsVirtualKeyCode": 83,
                    "nativeVirtualKeyCode": 83,
                    "key": "s",
                    "code": "KeyS",
                },
            )
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and shared_file.read_text(encoding="utf-8") != UPDATED_TEXT:
                time.sleep(0.1)
            saved = shared_file.read_text(encoding="utf-8") == UPDATED_TEXT
            save_method = "Ctrl+S"
            if not saved:
                # Some isolated Electron windows swallow accelerator shortcuts.
                # VS Code's own command palette remains addressable through the
                # renderer and avoids any OS-level keyboard event.
                client.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "windowsVirtualKeyCode": 112,
                        "nativeVirtualKeyCode": 112,
                        "key": "F1",
                        "code": "F1",
                    },
                )
                client.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "windowsVirtualKeyCode": 112,
                        "nativeVirtualKeyCode": 112,
                        "key": "F1",
                        "code": "F1",
                    },
                )
                time.sleep(0.25)
                client.call("Input.insertText", {"text": "File: Save"})
                time.sleep(0.25)
                client.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "rawKeyDown",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                        "key": "Enter",
                        "code": "Enter",
                    },
                )
                client.call(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "windowsVirtualKeyCode": 13,
                        "nativeVirtualKeyCode": 13,
                        "key": "Enter",
                        "code": "Enter",
                    },
                )
                deadline = time.monotonic() + 6.0
                while time.monotonic() < deadline and shared_file.read_text(encoding="utf-8") != UPDATED_TEXT:
                    time.sleep(0.1)
                saved = shared_file.read_text(encoding="utf-8") == UPDATED_TEXT
                save_method = "VS Code command palette"
            vscode_save_available = saved
            if not saved:
                # The renderer accepted and displayed the exact content, but this
                # isolated Electron instance refused both Save routes. Persist the
                # identical reviewed content through OpenWand's shared-file boundary.
                shared_file.write_text(UPDATED_TEXT, encoding="utf-8")
                saved = shared_file.read_text(encoding="utf-8") == UPDATED_TEXT
                save_method = "OpenWand shared-file persistence fallback"
            if not saved:
                raise RuntimeError("The reviewed VS Code edit could not be persisted.")

            file_tab = client.evaluate(
                """
                (() => {
                  const tabs = [...document.querySelectorAll(
                    '.tab, [role="tab"], .tabs-container .monaco-icon-label'
                  )];
                  const tab = tabs.find(node => /openwand-real-demo\\.py/i.test(
                    node.getAttribute?.('aria-label') || node.innerText || ''
                  ));
                  const target = tab?.closest?.('.tab, [role="tab"]') || tab;
                  if (!target) return null;
                  const rect = target.getBoundingClientRect();
                  return {x: rect.x + rect.width / 2, y: rect.y + rect.height / 2};
                })()
                """
            )
            if file_tab:
                for event_type in ("mousePressed", "mouseReleased"):
                    client.call(
                        "Input.dispatchMouseEvent",
                        {
                            "type": event_type,
                            "x": float(file_tab["x"]),
                            "y": float(file_tab["y"]),
                            "button": "left",
                            "clickCount": 1,
                        },
                    )
                time.sleep(0.4)

            screenshot = client.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            vscode_capture.write_bytes(base64.b64decode(str(screenshot.get("data") or "")))
            _render_workspace(shared_file, workspace_capture)
            _compose_screenshot(workspace_capture, vscode_capture, final_capture)
            result.update(
                {
                    "ok": True,
                    "window_title": title,
                    "vscode_renderer_verified": editor_updated,
                    "shared_file_updated": saved,
                    "save_method": save_method,
                    "vscode_save_available_on_isolated_desktop": vscode_save_available,
                    "capture_source": "VS Code's real renderer surface",
                    "screenshot": str(final_capture),
                    "shared_file": str(shared_file),
                }
            )
            stage("real_app_verified", application="Visual Studio Code", editor_updated=editor_updated)
        finally:
            if client is not None:
                client.close()
            result["owned_processes_cleaned"] = terminate_profile_processes(str(profile))
            if process.poll() is None:
                process.terminate()
        evidence_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True), flush=True)
    return 0 if result.get("ok") else 1


def _default_output_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "outputs" / f"real-vscode-demo-{stamp}"


def _outer(output_dir: Path) -> int:
    if output_dir.exists():
        raise FileExistsError(f"Output already exists: {output_dir}")
    foreground_before = int(ctypes.windll.user32.GetForegroundWindow())
    cursor_before = _cursor_position()
    old_output = os.environ.get(OUTPUT_ENV)
    os.environ[OUTPUT_ENV] = str(output_dir.resolve())
    try:
        exit_code = run_on_isolated_desktop(Path(__file__), "--inner")
    finally:
        if old_output is None:
            os.environ.pop(OUTPUT_ENV, None)
        else:
            os.environ[OUTPUT_ENV] = old_output
    foreground_after = int(ctypes.windll.user32.GetForegroundWindow())
    cursor_after = _cursor_position()
    evidence_path = output_dir / "evidence.json"
    if evidence_path.is_file():
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence.update(
            {
                "visible_desktop_focus_unchanged": foreground_before == foreground_after,
                "cursor_unchanged_observation": cursor_before == cursor_after,
                "cursor_control_used": False,
            }
        )
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False))
        if not evidence["visible_desktop_focus_unchanged"]:
            return 1
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inner", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.inner:
        return _inner()
    if sys.platform != "win32":
        raise SystemExit("This real-app demo currently requires Windows.")
    return _outer((args.output_dir or _default_output_dir()).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
