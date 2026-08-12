"""Real OpenWand model -> preview -> focusless VS Code live API smoke."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
for entry in (ROOT, SCRIPT_DIR):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from test_openwand_vscode_background_desktop import (  # noqa: E402
    parent,
    stage,
    terminate_profile_processes,
    wait_for_code_window,
    windows,
)
from test_openwand_vscode_cdp_real import Cdp, reserve_port, wait_for_target  # noqa: E402


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


def inner() -> int:
    from core.actions.adapters.vscode import VSCodeDevToolsAdapter
    from runtime.supervisor.flows import FlowController, PendingInvocation
    from runtime.supervisor.ipc import WorkerClient, default_specs

    executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    port = reserve_port()
    result: dict[str, Any] = {"isolated_desktop": True, "transport": "vscode-devtools"}
    with tempfile.TemporaryDirectory(prefix="openwand-vscode-cdp-flow-") as profile:
        stage("isolated_launch", profile=profile, port=port)
        process = subprocess.Popen(
            [
                str(executable),
                "--new-window",
                "--disable-extensions",
                "--disable-updates",
                "--user-data-dir",
                profile,
                f"--remote-debugging-port={port}",
                f"--remote-allow-origins=http://127.0.0.1:{port}",
                "-",
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        brain = None
        client = None
        try:
            hwnd, title = wait_for_code_window()
            deadline = time.monotonic() + 15.0
            while not (title.startswith("\u25cf") or "code-stdin" in title.casefold()) and time.monotonic() < deadline:
                time.sleep(0.2)
                title = windows().get(hwnd, title)
            target = wait_for_target(port)
            client = Cdp(str(target["webSocketDebuggerUrl"]), f"http://127.0.0.1:{port}")
            client.call("Runtime.enable")
            editor = None
            deadline = time.monotonic() + 12.0
            while time.monotonic() < deadline:
                editor = client.evaluate(
                    """
                    (() => {
                      const nodes = [...document.querySelectorAll('.monaco-editor')];
                      const node = nodes.find(item => item.querySelector('textarea.inputarea'))
                        || nodes.find(item => item.getBoundingClientRect().width > 100);
                      if (!node) return null;
                      const rect = node.getBoundingClientRect();
                      return {x: rect.x + rect.width * .45, y: rect.y + rect.height * .35};
                    })()
                    """
                )
                if editor:
                    break
                time.sleep(0.2)
            if not editor:
                raise RuntimeError("Monaco did not become API-addressable")
            # A brand-new disposable profile can show a delayed sign-in layer
            # over Monaco. Dismiss it through the API so the smoke represents
            # an established user profile with an exposed editor.
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                dismissed = bool(
                    client.evaluate(
                        """
                        (() => {
                          const button = [...document.querySelectorAll('button, a')]
                            .find(node => /continue without signing in/i.test(node.innerText || ''));
                          if (!button) return false;
                          button.click();
                          return true;
                        })()
                        """
                    )
                )
                if dismissed:
                    time.sleep(0.4)
                    break
                time.sleep(0.1)
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": editor["x"], "y": editor["y"], "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": editor["x"], "y": editor["y"], "button": "left", "clickCount": 1})
            stage("api_ready", hwnd=hwnd, title=title)

            adapter = VSCodeDevToolsAdapter()
            native = Worker(
                {
                    "native.action.vscode.live_apply": lambda params: adapter.apply_text(
                        str(params.get("text") or ""),
                        params.get("active_app") or {},
                        editor_point=params.get("editor_point") or {},
                    )
                }
            )
            ui = Worker({"ui.action.preview.request": lambda _params: {"approved": True}})
            audio = Worker()
            brain = WorkerClient(default_specs()["brain"])
            flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
            flow.start(prewarm=False)
            now = time.time_ns()
            active_app = {
                "name": "Untitled-1 - Visual Studio Code",
                "process_name": "Code.exe",
                "pid": int(process.pid),
                "window_id": hwnd,
            }
            pending = PendingInvocation(
                caller_idx=0,
                caller={"paste_back": True, "context_clipboard": False},
                context={
                    "platform": "win32",
                    "active_app": active_app,
                    "selected_text": "",
                    "clipboard_text": "",
                    "focus_token": 1,
                    "editor_point": {"x": float(editor["x"]), "y": float(editor["y"])},
                },
                paste_target_pid=int(process.pid),
                invoked_at_unix_ns=now,
                initial_context_at_unix_ns=now,
                intent_shown_at_unix_ns=now,
                context_ready_at_unix_ns=now,
            )
            pending.context_ready.set()
            flow._pending = pending
            flow.intent_chosen(
                "Create a tiny Python function named openwand_api_test that returns the string 'api works'."
            )
            previews = [call for call in ui.calls if call["method"] == "ui.action.preview.request"]
            applies = [call for call in native.calls if call["method"] == "native.action.vscode.live_apply"]
            logical_text = str(
                client.evaluate(
                    "[...document.querySelectorAll('.monaco-editor .view-lines')].map(node => node.innerText).join('\\n')"
                )
                or ""
            ).replace("\u00a0", " ")
            result.update(
                {
                    "model_called": True,
                    "preview_called": bool(previews),
                    "preview_has_diff": bool(previews and "openwand_api_test" in str(previews[-1]["params"].get("html") or "")),
                    "api_apply_called": bool(applies),
                    "api_apply_response": applies[-1].get("result") if applies else {},
                    "logical_text": logical_text,
                    "text_verified": "openwand_api_test" in logical_text and "api works" in logical_text,
                }
            )
            stage(
                "flow_verified",
                preview_called=result["preview_called"],
                apply_ok=bool((result["api_apply_response"] or {}).get("ok")),
                text_verified=result["text_verified"],
            )
        finally:
            if brain is not None:
                brain.shutdown()
            if client is not None:
                client.close()
            result["owned_processes_cleaned"] = terminate_profile_processes(profile)
            if process.poll() is None:
                process.terminate()
            stage("cleanup_finished", owned_processes=result["owned_processes_cleaned"])
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
    passed = all(
        (
            result.get("model_called"),
            result.get("preview_called"),
            result.get("preview_has_diff"),
            result.get("api_apply_called"),
            (result.get("api_apply_response") or {}).get("ok"),
            result.get("text_verified"),
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    raise SystemExit(inner() if "--inner" in sys.argv else parent(Path(__file__), "--inner"))
