"""Run OpenWand's real intent-context flow against a live minimized Calc window."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _find_window(title_contains: str) -> int:
    user32 = ctypes.windll.user32
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        if title_contains.casefold() in buffer.value.casefold():
            matches.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else 0


class Worker:
    def __init__(self, handlers: dict[str, Any] | None = None) -> None:
        self.handlers = handlers or {}
        self.events: dict[str, list[Any]] = {}
        self.calls: list[dict[str, Any]] = []

    def call(self, method: str, params: dict[str, Any] | None = None, **_kwargs: Any) -> Any:
        payload = params or {}
        self.calls.append({"method": method, "params": payload})
        handler = self.handlers.get(method)
        return handler(payload) if handler else {}

    def on_event(self, event: str, handler: Any) -> None:
        self.events.setdefault(event, []).append(handler)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import config
    from core.platform_utils import get_window_pid
    from runtime.supervisor.flows import FlowController
    from runtime.workers.native_host import context_app_selection

    hwnd = _find_window(args.title)
    if not hwnd:
        raise RuntimeError("The disposable Calc window was not found.")
    active_app = {
        "name": f"{args.title}.ods — LibreOffice Calc",
        "process_name": "soffice.bin",
        "pid": int(get_window_pid(hwnd) or 0),
        "window_id": hwnd,
    }
    overlay_shown = False
    app_read_after_overlay = False

    def snapshot(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "platform": "win32",
            "active_app": active_app,
            "selected_text": "",
            "clipboard_text": "",
            "app_selection_deferred": True,
        }

    def show_intent(_params: dict[str, Any]) -> dict[str, Any]:
        nonlocal overlay_shown
        overlay_shown = True
        return {}

    def read_app_selection(params: dict[str, Any]) -> dict[str, Any]:
        nonlocal app_read_after_overlay
        app_read_after_overlay = overlay_shown
        return context_app_selection(params.get("active_app"))

    native = Worker(
        {
            "native.context.snapshot": snapshot,
            "native.context.app_selection": read_app_selection,
        }
    )
    ui = Worker({"ui.show_intent": show_intent})
    brain = Worker()
    audio = Worker()
    flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
    flow.start()

    old_rows = list(config.CALLER_ROWS)
    try:
        config.CALLER_ROWS[:] = [
            {
                "label": "Calc action test",
                "paste_back": False,
                "context_ambient": True,
                "context_documents_mode": "off",
                "context_browser_mode": "off",
                "context_memory_mode": "off",
                "context_screenshot": "off",
                "context_clipboard": False,
                "intents": [],
            }
        ]
        flow.begin_caller(0)
    finally:
        config.CALLER_ROWS[:] = old_rows

    context_updates = [call for call in ui.calls if call["method"] == "ui.intent.context_items"]
    if not context_updates:
        raise RuntimeError("OpenWand did not publish intent context items.")
    items = context_updates[-1]["params"].get("context_items") or []
    selection_chip = next(item for item in items if item.get("id") == "selection")
    pending = flow._pending  # noqa: SLF001 - live contract harness
    app_selection = pending.context.get("app_selection") if pending else {}
    print(
        json.dumps(
            {
                "flow": "OpenWand FlowController.begin_caller",
                "overlay_shown": overlay_shown,
                "app_read_after_overlay": app_read_after_overlay,
                "selection_chip": selection_chip,
                "app_selection": app_selection,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
