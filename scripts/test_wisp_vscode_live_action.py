"""Run Wisp's real model and interactive preview against one open VS Code buffer."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
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
    parser.add_argument("--title", required=True)
    parser.add_argument("--document-path", default="")
    parser.add_argument("--selected-text", default="")
    parser.add_argument("--selected-line", type=int, default=0)
    parser.add_argument(
        "--prompt",
        default=(
            "Create a tiny Python example that defines greet(name), returns a friendly greeting, "
            "and prints greet('Wisp')."
        ),
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    from runtime.supervisor.flows import FlowController, PendingInvocation
    from runtime.supervisor.ipc import WorkerClient, default_specs
    from runtime.workers import native_host
    from core.system.paths import USER_DATA_DIR

    os.environ.setdefault(
        "WISP_ACTION_TRACE_PATH",
        str(USER_DATA_DIR / "logs" / "action-timings.jsonl"),
    )

    if not ctypes.windll.user32.IsWindow(args.hwnd):
        raise RuntimeError("The requested VS Code window no longer exists.")
    selected_text = args.selected_text
    if args.selected_line:
        document_lines = Path(args.document_path).read_text(encoding="utf-8").splitlines()
        if args.selected_line < 1 or args.selected_line > len(document_lines):
            raise ValueError("--selected-line is outside the saved file.")
        selected_text = document_lines[args.selected_line - 1]

    active_app = {
        "name": args.title,
        "process_name": "Code.exe",
        "pid": args.pid,
        "window_id": args.hwnd,
        "document_path": args.document_path,
    }
    native = Worker(
        {
            "native.action.vscode.snapshot": lambda params: native_host.action_vscode_snapshot(**params),
            "native.action.vscode.apply": lambda params: native_host.action_vscode_apply(**params),
        }
    )
    audio = Worker()
    specs = default_specs()
    brain = WorkerClient(specs["brain"])
    ui = WorkerClient(specs["ui"])
    try:
        flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
        flow.start(prewarm=False)
        invoked_at_unix_ns = time.time_ns()
        pending = PendingInvocation(
            caller_idx=0,
            caller={"paste_back": True, "context_clipboard": False},
            context={
                "platform": "win32",
                "active_app": active_app,
                "selected_text": selected_text,
                "clipboard_text": "",
            },
            invoked_at_unix_ns=invoked_at_unix_ns,
            initial_context_at_unix_ns=time.time_ns(),
            intent_shown_at_unix_ns=time.time_ns(),
            context_ready_at_unix_ns=time.time_ns(),
        )
        pending.context_ready.set()
        flow._pending = pending
        flow.intent_chosen(args.prompt)
        apply_calls = [call for call in native.calls if call["method"] == "native.action.vscode.apply"]
        snapshot_calls = [call for call in native.calls if call["method"] == "native.action.vscode.snapshot"]
        result = {
            "snapshot": snapshot_calls[-1].get("result") if snapshot_calls else {},
            "apply_called": bool(apply_calls),
            "apply_response": apply_calls[-1].get("result") if apply_calls else {},
        }
        print(json.dumps(result, ensure_ascii=False))
        if not apply_calls:
            return 2
        return 0 if bool((result["apply_response"] or {}).get("ok")) else 1
    finally:
        brain.shutdown()
        ui.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
