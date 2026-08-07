"""Run the real Rewrite popup and supervisor event flow on Qt's isolated surface."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import config  # noqa: E402
from runtime.supervisor.flows import FlowController  # noqa: E402
from ui.i18n import set_language  # noqa: E402
from ui.overlay import IconOverlay, OverlaySignals  # noqa: E402
from ui.rewrite_annotation import RewriteAnnotationPopup  # noqa: E402


class Worker:
    """Small synchronous IPC stand-in used at the real supervisor boundary."""

    def __init__(self, handlers: dict[str, Any] | None = None) -> None:
        self.handlers = handlers or {}
        self.events: dict[str, list[Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def on_event(self, event: str, handler) -> None:
        self.events.setdefault(event, []).append(handler)

    def emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        for handler in list(self.events.get(event, [])):
            handler(data or {}, None)

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        wait: bool = True,
    ) -> Any:
        del timeout, wait
        payload = params or {}
        self.calls.append({"method": method, "params": payload})
        return self.handlers.get(method, lambda _params: {})(payload)

    def call_with_events(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        on_event,
        on_started=None,
    ) -> Any:
        del timeout
        payload = params or {}
        self.calls.append({"method": method, "params": payload})
        if on_started is not None:
            on_started(len(self.calls))
        return self.handlers.get(method, lambda _params, _on_event: {})(payload, on_event)


class RewriteUiBridge(Worker):
    """Render the production popup while speaking the same UI IPC methods."""

    def __init__(self, app: QApplication, output: Path) -> None:
        super().__init__()
        self.app = app
        self.output = output
        self.popup: RewriteAnnotationPopup | None = None

    def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
        wait: bool = True,
    ) -> Any:
        del timeout, wait
        payload = params or {}
        self.calls.append({"method": method, "params": payload})
        if method == "ui.rewrite.annotation.show":
            popup = RewriteAnnotationPopup(
                annotation_id=str(payload.get("annotation_id") or ""),
                display_number=max(1, int(payload.get("display_number") or 1)),
                selected_text=str(payload.get("selected_text") or ""),
                source_window_id=0,
                source_pid=int(payload.get("source_pid") or 0),
                source_label=str(payload.get("source_label") or ""),
                selection_rect=payload.get("selection_rect"),
            )
            popup.submitted.connect(
                lambda item_id, comment, include_document: QTimer.singleShot(
                    180,
                    lambda: self.emit(
                        "ui.rewrite.annotation.submitted",
                        {
                            "annotation_id": item_id,
                            "comment": comment,
                            "include_document": include_document,
                        },
                    ),
                )
            )
            popup.accept_requested.connect(
                lambda item_id, _replacement: QTimer.singleShot(
                    0,
                    lambda: self.emit(
                        "ui.rewrite.annotation.accepted",
                        {"annotation_id": item_id},
                    ),
                )
            )
            popup.cancel_requested.connect(
                lambda item_id: self.emit(
                    "ui.rewrite.annotation.cancelled",
                    {"annotation_id": item_id},
                )
            )
            popup.declined.connect(
                lambda item_id: self.emit(
                    "ui.rewrite.annotation.declined",
                    {"annotation_id": item_id},
                )
            )
            popup.revision_requested.connect(
                lambda item_id, feedback: self.emit(
                    "ui.rewrite.annotation.revision_requested",
                    {"annotation_id": item_id, "feedback": feedback},
                )
            )
            self.popup = popup
            popup.show_composer()
            self.app.processEvents()
            return {"shown": True}
        if method == "ui.rewrite.annotation.processing" and self.popup is not None:
            self.popup.show_processing()
            self.app.processEvents()
            return {"updated": True, "state": "processing"}
        if method == "ui.rewrite.annotation.proposal" and self.popup is not None:
            self.popup.show_proposal(
                str(payload.get("replacement_text") or ""),
                copy_only=bool(payload.get("copy_only")),
            )
            self.app.processEvents()
            return {"updated": True, "state": "proposal"}
        if method == "ui.rewrite.annotation.failure" and self.popup is not None:
            self.popup.show_failure(str(payload.get("message") or ""))
            self.app.processEvents()
            return {"updated": True, "state": "failed"}
        if method == "ui.rewrite.annotation.remove" and self.popup is not None:
            popup = self.popup
            self.popup = None
            popup.remove()
            self.app.processEvents()
            return {"removed": True}
        return {}

    def capture(self, name: str) -> Path:
        if self.popup is None:
            raise RuntimeError("The production Rewrite popup has not been created.")
        self.app.processEvents()
        target = self.output / name
        if not self.popup.grab().save(str(target), "PNG"):
            raise RuntimeError(f"Could not capture {name}.")
        return target


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "rewrite_exact_evidence",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["wisp-rewrite-isolated-smoke"])
    font_family = "Sans Serif"
    for font_path in (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "seguisb.ttf",
    ):
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            if families:
                font_family = families[0]
    old_language = str(getattr(config, "APP_LANGUAGE", "") or "")
    config.APP_LANGUAGE = "en"
    set_language("en", app=app)
    app.setFont(QFont(font_family, 10))
    browser_state = {"text": "A rough sentence."}

    def context(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "platform": "win32",
            "selected_text": "rough",
            "active_app": {
                "name": "Ordinary browser test - Google Chrome",
                "process_name": "chrome.exe",
                "pid": 7300,
                "window_id": 0,
            },
            "focus_token": 41,
            "selection_rect": {"left": 120, "top": 180, "width": 76, "height": 24},
            "screen_size": {"width": 1920, "height": 1080},
        }

    def paste(params: dict[str, Any]) -> dict[str, Any]:
        if int(params.get("focus_token") or 0) != 41 or browser_state["text"] != "A rough sentence.":
            return {"ok": False, "error": "stale isolated browser selection"}
        browser_state["text"] = browser_state["text"].replace("rough", str(params.get("text") or ""), 1)
        return {
            "ok": browser_state["text"] == "A clear sentence.",
            "method": "isolated-uia-contract",
            "clipboard_restored": True,
            "focus_restored": True,
        }

    native = Worker(
        {
            "native.context.snapshot": context,
            "native.action.browser.rewrite_snapshot": lambda _params: {
                "ok": False,
                "error": "ordinary browser uses the accessibility selection",
            },
            "native.paste_text": paste,
        }
    )
    ui = RewriteUiBridge(app, args.output)

    def rewrite(_params: dict[str, Any], on_event) -> dict[str, Any]:
        on_event("reply.done", {"text": "clear"}, 1)
        return {"text": "clear"}

    brain = Worker({"brain.rewrite": rewrite})
    audio = Worker()
    old_rows = list(config.CALLER_ROWS)
    config.CALLER_ROWS[:] = [
        {
            "paste_back": True,
            "context_clipboard": False,
            "context_documents": False,
            "context_tools": False,
            "context_screenshot": "off",
            "context_memory_mode": "off",
        }
    ]
    try:
        flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
        flow.start(prewarm=False)
        native.emit("native.hotkey", {"kind": "caller", "index": 0})
        if ui.popup is None:
            raise RuntimeError("The internal hotkey event did not open the real Rewrite popup.")
        ui.popup._comment.setPlainText("Make this clearer")
        app.processEvents()
        composer = ui.capture("rewrite_ui_composer.png")
        QTest.keyClick(ui.popup._comment, Qt.Key.Key_Return)
        app.processEvents()
        processing = ui.capture("rewrite_ui_processing_balloon.png")
        QTest.qWait(260)
        app.processEvents()
        if ui.popup.state != "proposal":
            raise RuntimeError(f"Expected proposal state, got {ui.popup.state!r}.")
        proposal = ui.capture("rewrite_ui_proposal.png")
        ui.popup._accept.click()
        QTest.qWait(30)
        app.processEvents()
        overlay = IconOverlay(OverlaySignals())
        overlay.set_held_rewrite_count(2)
        app.processEvents()
        button = overlay._rewrite_batch_button
        icon = overlay._icon_label
        left = min(button.x(), icon.x())
        top = min(button.y(), icon.y())
        right = max(button.x() + button.width(), icon.x() + icon.width())
        bottom = max(button.y() + button.height(), icon.y() + icon.height())
        batch_pixmap = QPixmap(right - left, bottom - top)
        batch_pixmap.fill(QColor("#111318"))
        painter = QPainter(batch_pixmap)
        painter.drawPixmap(button.x() - left, button.y() - top, button.grab())
        painter.drawPixmap(icon.x() - left, icon.y() - top, icon.grab())
        painter.end()
        batch_control = args.output / "rewrite_ui_send_all_comments.png"
        if not batch_pixmap.save(str(batch_control), "PNG"):
            raise RuntimeError("Could not capture the shared Send all comments control.")
        overlay.close()
        app.processEvents()
        accepted = browser_state["text"] == "A clear sentence."
        result = {
            "verified": accepted,
            "browser_text": browser_state["text"],
            "composer": str(composer),
            "processing": str(processing),
            "proposal": str(proposal),
            "send_all_comments": str(batch_control),
            "popup_removed": not bool(flow._rewrite_annotations),
            "native_apply_calls": len(
                [item for item in native.calls if item["method"] == "native.paste_text"]
            ),
        }
        print(json.dumps(result, indent=2))
        return 0 if accepted and result["popup_removed"] else 1
    finally:
        config.CALLER_ROWS[:] = old_rows
        config.APP_LANGUAGE = old_language
        set_language(old_language or None, app=app)
        if ui.popup is not None:
            ui.popup.remove()
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())
