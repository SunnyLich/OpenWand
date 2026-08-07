"""Run Wisp's real Calc chart route against an already off-screen test window."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
from pathlib import Path
from typing import Any

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hwnd", type=int, required=True)
    parser.add_argument("--pid", type=int, required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import config
    from runtime.supervisor.flows import FlowController
    from runtime.workers import native_host

    user32 = ctypes.windll.user32
    if not user32.IsWindow(args.hwnd):
        raise RuntimeError("The off-screen Calc test window is not available.")
    active_app = {
        "name": "Untitled 1 — LibreOffice Calc",
        "process_name": "soffice.bin",
        "pid": args.pid,
        "window_id": args.hwnd,
    }
    foreground_before = int(user32.GetForegroundWindow())
    preview_payload: dict[str, Any] = {}

    def snapshot(_params: dict[str, Any]) -> dict[str, Any]:
        return {
            "platform": "win32",
            "active_app": active_app,
            "selected_text": "",
            "clipboard_text": "",
            "app_selection_deferred": True,
        }

    def preview(params: dict[str, Any]) -> dict[str, Any]:
        preview_payload.update(params)
        return {"approved": True, "surface": "offscreen_contract_test"}

    native = Worker(
        {
            "native.context.snapshot": snapshot,
            "native.context.app_selection": lambda params: native_host.context_app_selection(
                params.get("active_app")
            ),
            "native.action.calc.apply": lambda params: native_host.action_calc_apply(**params),
        }
    )
    ui = Worker(
        {
            "ui.show_intent": lambda _params: {},
            "ui.action.preview.request": preview,
            "ui.reply.notice": lambda _params: {},
        }
    )
    brain = Worker()
    audio = Worker()
    flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
    flow.start()

    old_rows = list(config.CALLER_ROWS)
    try:
        config.CALLER_ROWS[:] = [
            {
                "label": "Calc action test",
                "paste_back": True,
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
        flow.intent_chosen("create a graph")
    finally:
        config.CALLER_ROWS[:] = old_rows

    foreground_after = int(user32.GetForegroundWindow())
    apply_calls = [call for call in native.calls if call["method"] == "native.action.calc.apply"]
    rewrite_calls = [call for call in brain.calls if call["method"] in {"brain.rewrite", "brain.query"}]
    notices = [
        call["params"].get("text")
        for call in ui.calls
        if call["method"] == "ui.reply.notice"
    ]
    result = {
        "flow": "Wisp FlowController.intent_chosen",
        "intent": "create a graph",
        "preview_rendered": bool(preview_payload.get("html")),
        "preview_contains_range": "A1:C7" in str(preview_payload.get("html") or ""),
        "approved": True,
        "apply_called": len(apply_calls) == 1,
        "apply_response": apply_calls[-1].get("result") if apply_calls else {},
        "model_or_rewrite_calls": len(rewrite_calls),
        "foreground_before": foreground_before,
        "foreground_after": foreground_after,
        "focus_unchanged": foreground_before == foreground_after,
        "notices": notices,
    }
    print(json.dumps(result, ensure_ascii=False))
    applied = bool((result.get("apply_response") or {}).get("ok"))
    return 0 if result["apply_called"] and applied and not rewrite_calls and result["focus_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
