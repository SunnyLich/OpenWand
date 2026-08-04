"""Capture a real Wisp VS Code action timeline without touching the desktop."""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["QT_QPA_PLATFORM"] = "offscreen"

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class Worker:
    def __init__(self, handlers: dict[str, Any] | None = None) -> None:
        self.handlers = handlers or {}
        self.events: dict[str, list[Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def call(self, method: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> Any:
        payload = params or {}
        entry = {"method": method, "params": payload}
        self.calls.append(entry)
        handler = self.handlers.get(method)
        result = handler(payload) if handler else {}
        entry["result"] = result
        return result

    def on_event(self, event: str, handler: Any) -> None:
        self.events.setdefault(event, []).append(handler)


class OffscreenCaptureUI(Worker):
    """Marshal supervisor UI calls onto Qt's main thread and capture each state."""

    def __init__(self, output_dir: Path, started_ns: int) -> None:
        super().__init__()
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication
        from ui.bubble import SpeechBubble

        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        for font_path in (
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\seguisb.ttf",
            r"C:\Windows\Fonts\consola.ttf",
        ):
            if Path(font_path).is_file():
                QFontDatabase.addApplicationFont(font_path)
        self.output_dir = output_dir
        self.started_ns = started_ns
        self.timeline: list[dict[str, Any]] = []
        self.pending: queue.Queue[tuple[str, dict[str, Any], threading.Event, dict[str, Any]]] = queue.Queue()
        self.main_thread = threading.current_thread()
        self.bubble = SpeechBubble()

    def call(self, method: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> Any:
        payload = dict(params or {})
        self.calls.append({"method": method, "params": payload})
        if threading.current_thread() is self.main_thread:
            return self._dispatch(method, payload)
        done = threading.Event()
        result: dict[str, Any] = {}
        self.pending.put((method, payload, done, result))
        if not done.wait(60.0):
            raise TimeoutError(f"offscreen UI call timed out: {method}")
        if "error" in result:
            raise result["error"]
        return result.get("value", {})

    def drain(self) -> None:
        while True:
            try:
                method, payload, done, result = self.pending.get_nowait()
            except queue.Empty:
                return
            try:
                result["value"] = self._dispatch(method, payload)
            except Exception as exc:  # noqa: BLE001 - return to the flow thread
                result["error"] = exc
            finally:
                done.set()

    def _dispatch(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        if method == "ui.reply.reset":
            self.bubble.clear()
            return {"reset": True}
        if method == "ui.reply.thinking":
            self.bubble.show_progress("Thinking...")
            self._capture_widget(self.bubble, "thinking", "Thinking")
            return {"shown": True}
        if method == "ui.action.progress":
            text = str(payload.get("text") or "")
            stage = str(payload.get("stage") or "progress")
            sequence = int(payload.get("sequence") or 0)
            self.bubble.show_progress(text)
            self._capture_widget(self.bubble, stage, f"{stage} #{sequence}")
            return {"shown": True, "stage": stage, "sequence": sequence}
        if method == "ui.action.preview.request":
            self._capture_preview(payload)
            return {
                "approved": True,
                "surface": "offscreen_capture",
                "show_called_at_unix_ns": time.time_ns(),
                "topmost_at_unix_ns": time.time_ns(),
                "decided_at_unix_ns": time.time_ns(),
                "decision_wait_ms": 0.0,
            }
        if method == "ui.notice":
            text = str(payload.get("text") or "")
            if text:
                self.bubble.show_notice(text, timeout_ms=0)
                self._capture_widget(self.bubble, "notice", "Final notice")
            return {"shown": bool(text)}
        return {}

    def _capture_preview(self, payload: dict[str, Any]) -> None:
        from PySide6.QtWidgets import QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget
        from ui.addon_presentations import presentation_document
        from ui.shared.theme import theme_colors

        colors = theme_colors(True)
        palette = {
            "bg": colors["bg"],
            "text": colors["text"],
            "muted": colors["text_dim"],
            "line": colors["border"],
            "accent": colors["accent"],
            "warm": "#f0ae72",
            "warm_soft": "#3c2b25",
            "soft": colors["accent_hint"],
            "code": "#15171c",
            "code_text": "#eff6ff",
        }
        root = QWidget()
        root.setStyleSheet(f"background: {colors['bg']}; color: {colors['text']};")
        layout = QVBoxLayout(root)
        title = QLabel(str(payload.get("title") or "Review action"), root)
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)
        preview = QTextBrowser(root)
        preview.setOpenExternalLinks(False)
        preview.setHtml(
            presentation_document(str(payload.get("html") or ""), palette, 15)
        )
        preview.setStyleSheet("border: 1px solid #2b2e38; background: #1b1e27;")
        layout.addWidget(preview, 1)
        buttons = QWidget(root)
        button_layout = QVBoxLayout(buttons)
        apply_button = QPushButton("Apply (automatically approved for this disposable file)", buttons)
        apply_button.setEnabled(False)
        button_layout.addWidget(apply_button)
        layout.addWidget(buttons)
        root.resize(900, 720)
        root.show()
        # The off-screen fallback still completes layout on queued Qt events.
        for _index in range(3):
            self.app.processEvents()
            time.sleep(0.05)
        root.repaint()
        self.app.processEvents()
        self._capture_widget(root, "preview", "HTML/CSS preview (off-screen fallback)")
        root.close()
        root.deleteLater()
        self.app.processEvents()

    def _capture_widget(self, widget: Any, stage: str, label: str) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter

        widget.show()
        self.app.processEvents()
        elapsed_ms = round((time.perf_counter_ns() - self.started_ns) / 1_000_000, 3)
        captured_at = datetime.now(UTC).isoformat(timespec="milliseconds")
        pixmap = widget.grab()
        banner_height = 72
        width = max(760, pixmap.width())
        height = banner_height + pixmap.height()
        image = QImage(width, height, QImage.Format.Format_ARGB32)
        image.fill(QColor("#101218"))
        painter = QPainter(image)
        painter.setPen(QColor("#f3f4ff"))
        painter.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        painter.drawText(20, 28, f"{label}  |  +{elapsed_ms:.3f} ms")
        painter.setPen(QColor("#a9adc2"))
        painter.setFont(QFont("Consolas", 9))
        painter.drawText(20, 53, captured_at)
        painter.drawPixmap((width - pixmap.width()) // 2, banner_height, pixmap)
        painter.end()
        index = len(self.timeline) + 1
        safe_stage = "".join(char if char.isalnum() else "_" for char in stage).strip("_")
        filename = f"{index:02d}_{int(elapsed_ms):06d}ms_{safe_stage}.png"
        path = self.output_dir / filename
        if not image.save(str(path), "PNG"):
            raise RuntimeError(f"could not save {path}")
        self.timeline.append(
            {
                "index": index,
                "stage": stage,
                "label": label,
                "elapsed_ms": elapsed_ms,
                "captured_at": captured_at,
                "file": filename,
                "width": image.width(),
                "height": image.height(),
            }
        )

    def save_timeline(self) -> None:
        (self.output_dir / "timeline.json").write_text(
            json.dumps(self.timeline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines = ["# Off-screen Wisp live-progress capture", ""]
        for item in self.timeline:
            lines.append(
                f"- {item['index']:02d}. `{item['stage']}` at +{item['elapsed_ms']:.3f} ms "
                f"({item['captured_at']}) — `{item['file']}`"
            )
        (self.output_dir / "timeline.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def save_contact_sheet(self) -> Path:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QFont, QImage, QPainter

        images = [QImage(str(self.output_dir / item["file"])) for item in self.timeline]
        cell_width = 620
        cell_height = 430
        columns = 2
        rows = (len(images) + columns - 1) // columns
        sheet = QImage(columns * cell_width, rows * cell_height, QImage.Format.Format_ARGB32)
        sheet.fill(QColor("#0b0d12"))
        painter = QPainter(sheet)
        painter.setFont(QFont("Segoe UI", 9))
        for index, source in enumerate(images):
            scaled = source.scaled(
                cell_width - 20,
                cell_height - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (index % columns) * cell_width + (cell_width - scaled.width()) // 2
            y = (index // columns) * cell_height + (cell_height - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        painter.end()
        path = self.output_dir / "contact-sheet.png"
        if not sheet.save(str(path), "PNG"):
            raise RuntimeError("could not save contact sheet")
        return path


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--contact-sheet-only", action="store_true")
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    if args.contact_sheet_only:
        timeline_path = output_dir / "timeline.json"
        if not timeline_path.is_file():
            raise FileNotFoundError(f"timeline not found: {timeline_path}")
        capture_ui = OffscreenCaptureUI(output_dir, time.perf_counter_ns())
        capture_ui.timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        print(str(capture_ui.save_contact_sheet()))
        return 0
    if output_dir.exists():
        raise FileExistsError(f"capture output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    test_file = output_dir / "wisp_live_progress_test.py"
    test_file.write_text("def add_one(value): return value\n", encoding="utf-8")
    os.environ["WISP_ACTION_TRACE_PATH"] = str(output_dir / "action-timings.jsonl")

    from PySide6.QtCore import QTimer
    from runtime.supervisor.flows import FlowController, PendingInvocation
    from runtime.supervisor.ipc import WorkerClient, default_specs
    from runtime.workers import native_host

    started_ns = time.perf_counter_ns()
    ui = OffscreenCaptureUI(output_dir, started_ns)
    native = Worker(
        {
            "native.action.vscode.snapshot": lambda params: native_host.action_vscode_snapshot(**params),
            "native.action.vscode.apply": lambda params: native_host.action_vscode_apply(**params),
        }
    )
    audio = Worker()
    brain = WorkerClient(default_specs()["brain"])
    result_box: dict[str, Any] = {}

    def run_flow() -> None:
        try:
            flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
            flow.start(prewarm=False)
            now = time.time_ns()
            pending = PendingInvocation(
                caller_idx=0,
                caller={"paste_back": True, "context_clipboard": False},
                context={
                    "platform": "win32",
                    "active_app": {
                        "name": "wisp_live_progress_test.py - Visual Studio Code",
                        "process_name": "Code.exe",
                        "pid": os.getpid(),
                        "window_id": 0,
                        "document_path": str(test_file),
                    },
                    "selected_text": "def add_one(value): return value",
                    "clipboard_text": "",
                },
                invoked_at_unix_ns=now,
                initial_context_at_unix_ns=now,
                intent_shown_at_unix_ns=now,
                context_ready_at_unix_ns=now,
            )
            pending.context_ready.set()
            flow._pending = pending
            flow.intent_chosen("Fix this function so add_one returns the input plus one. Keep it concise.")
            result_box["ok"] = test_file.read_text(encoding="utf-8") == "def add_one(value): return value + 1\n"
            result_box["content"] = test_file.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - report after the Qt loop exits
            result_box["error"] = f"{type(exc).__name__}: {exc}"

    worker = threading.Thread(target=run_flow, name="wisp-offscreen-flow", daemon=True)
    worker.start()
    pump = QTimer()
    pump.timeout.connect(ui.drain)
    pump.start(10)

    def finish_when_done() -> None:
        if worker.is_alive() or not ui.pending.empty():
            return
        ui.app.quit()

    finish_timer = QTimer()
    finish_timer.timeout.connect(finish_when_done)
    finish_timer.start(20)
    ui.app.exec()
    worker.join(timeout=10.0)
    ui.drain()
    brain.shutdown()
    ui.save_timeline()
    contact_sheet = ui.save_contact_sheet()
    test_file.unlink(missing_ok=True)
    result_box["timeline"] = ui.timeline
    result_box["contact_sheet"] = str(contact_sheet)
    print(json.dumps(result_box, ensure_ascii=False))
    return 0 if result_box.get("ok") and not result_box.get("error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
