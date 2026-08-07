"""Exercise Wisp's VS Code intent route with the configured model and no GUI focus."""

from __future__ import annotations

import ctypes
import json
import sys
import tempfile
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


class BrainRecorder:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.calls: list[str] = []

    def on_event(self, event: str, handler: Any) -> None:
        self.client.on_event(event, handler)

    def call(self, method: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        self.calls.append(method)
        return self.client.call(method, params, **kwargs)

    def call_with_events(self, method: str, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        self.calls.append(method)
        return self.client.call_with_events(method, params, **kwargs)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import config
    from runtime.supervisor.flows import FlowController
    from runtime.supervisor.ipc import WorkerClient, default_specs
    from runtime.workers import native_host

    foreground_before = int(ctypes.windll.user32.GetForegroundWindow())
    brain_client = WorkerClient(default_specs()["brain"])
    brain = BrainRecorder(brain_client)
    preview_payload: dict[str, Any] = {}
    old_rows = list(config.CALLER_ROWS)
    try:
        with tempfile.TemporaryDirectory(prefix="wisp-vscode-smoke-") as temp_dir:
            path = Path(temp_dir) / "demo.py"
            original = "def add_one(value):\n    return value\n"
            selected = "def add_one(value):\n    return value"
            path.write_text(original, encoding="utf-8")
            active_app = {
                "name": "demo.py - wisp-smoke - Visual Studio Code",
                "process_name": "Code.exe",
                "pid": 0,
                "window_id": 0,
                "document_path": str(path),
            }

            def preview(params: dict[str, Any]) -> dict[str, Any]:
                preview_payload.update(params)
                return {"approved": True, "surface": "offscreen_contract_test"}

            native = Worker(
                {
                    "native.context.snapshot": lambda _params: {
                        "platform": "win32",
                        "active_app": active_app,
                        "selected_text": selected,
                        "clipboard_text": "",
                        "app_selection_deferred": False,
                    },
                    "native.action.vscode.snapshot": lambda params: native_host.action_vscode_snapshot(**params),
                    "native.action.vscode.apply": lambda params: native_host.action_vscode_apply(**params),
                }
            )
            ui = Worker(
                {
                    "ui.show_intent": lambda _params: {},
                    "ui.action.preview.request": preview,
                    "ui.reply.notice": lambda _params: {},
                }
            )
            audio = Worker()
            flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
            flow.start(prewarm=False)
            config.CALLER_ROWS[:] = [
                {
                    "label": "VS Code action test",
                    "paste_back": True,
                    "context_ambient": False,
                    "context_documents_mode": "off",
                    "context_browser_mode": "off",
                    "context_memory_mode": "off",
                    "context_screenshot": "off",
                    "context_clipboard": False,
                    "intents": [],
                }
            ]
            flow.begin_caller(0)
            flow.intent_chosen("Fix this function so add_one returns the input value plus one.")
            final_text = path.read_text(encoding="utf-8")
            apply_calls = [call for call in native.calls if call["method"] == "native.action.vscode.apply"]
            paste_calls = [call for call in native.calls if call["method"] == "native.paste_text"]

        foreground_after = int(ctypes.windll.user32.GetForegroundWindow())
        result = {
            "flow": "Wisp FlowController.intent_chosen",
            "model_called": "brain.rewrite" in brain.calls,
            "preview_rendered": bool(preview_payload.get("html")),
            "preview_has_diff": "data-language=\"diff\"" in str(preview_payload.get("html") or ""),
            "apply_called": len(apply_calls) == 1,
            "apply_response": apply_calls[-1].get("result") if apply_calls else {},
            "direct_paste_calls": len(paste_calls),
            "file_changed": final_text != original,
            "foreground_before": foreground_before,
            "foreground_after": foreground_after,
            "focus_unchanged": foreground_before == foreground_after,
        }
        print(json.dumps(result, ensure_ascii=False))
        applied = bool((result.get("apply_response") or {}).get("ok"))
        return 0 if all((result["model_called"], result["preview_rendered"], result["preview_has_diff"], result["apply_called"], applied, result["file_changed"], result["focus_unchanged"], not result["direct_paste_calls"])) else 1
    finally:
        config.CALLER_ROWS[:] = old_rows
        brain_client.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
