"""Real OpenWand model -> preview -> official VS Code Extension API smoke."""

from __future__ import annotations

import json
import os
import secrets
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
from test_openwand_vscode_cdp_flow_real import Worker  # noqa: E402
from test_openwand_vscode_cdp_real import Cdp, reserve_port, wait_for_target  # noqa: E402

from core.actions.adapters.vscode import VSCodeExtensionAPIAdapter, VSCodeExtensionEndpoint  # noqa: E402


def inner() -> int:
    from runtime.supervisor.flows import FlowController, PendingInvocation
    from runtime.supervisor.ipc import WorkerClient, default_specs
    from runtime.workers import native_host

    executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    bridge_path = ROOT / "runtime" / "helpers" / "vscode_bridge"
    if not executable.is_file():
        raise FileNotFoundError(executable)

    devtools_port = reserve_port()
    bridge_port = reserve_port()
    token = secrets.token_hex(32)
    endpoint = VSCodeExtensionEndpoint(port=bridge_port, token=token)
    result: dict[str, Any] = {
        "isolated_desktop": True,
        "transport": "official-vscode-extension-api",
    }
    with tempfile.TemporaryDirectory(prefix="openwand-vscode-extension-flow-") as profile:
        launch_env = os.environ.copy()
        launch_env["OPENWAND_VSCODE_BRIDGE_PORT"] = str(bridge_port)
        launch_env["OPENWAND_VSCODE_BRIDGE_TOKEN"] = token
        stage("isolated_launch", profile=profile, devtools_port=devtools_port, bridge_port=bridge_port)
        process = subprocess.Popen(
            [
                str(executable),
                "--new-window",
                "--disable-updates",
                "--disable-workspace-trust",
                "--user-data-dir",
                profile,
                f"--extensionDevelopmentPath={bridge_path}",
                f"--remote-debugging-port={devtools_port}",
                f"--remote-allow-origins=http://127.0.0.1:{devtools_port}",
                "-",
            ],
            cwd=str(ROOT),
            env=launch_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        brain = None
        verifier = None
        try:
            hwnd, title = wait_for_code_window()
            deadline = time.monotonic() + 15.0
            while not (title.startswith("\u25cf") or "extension development host" in title.casefold()) and time.monotonic() < deadline:
                time.sleep(0.2)
                title = windows().get(hwnd, title)

            adapter = VSCodeExtensionAPIAdapter(endpoint)
            health: dict[str, Any] | None = None
            last_health_error = ""
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                try:
                    health = adapter.health()
                    if health.get("ok"):
                        break
                except Exception as exc:  # noqa: BLE001 - bridge is still activating
                    last_health_error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.1)
            if not health or not health.get("ok"):
                raise RuntimeError(f"VS Code Extension API bridge did not start: {last_health_error}")

            target = wait_for_target(devtools_port)
            verifier = Cdp(str(target["webSocketDebuggerUrl"]), f"http://127.0.0.1:{devtools_port}")
            verifier.call("Runtime.enable")
            stage("official_api_ready", hwnd=hwnd, title=title)

            native_host._vscode_extension_api_adapter = adapter
            native = Worker(
                {
                    "native.action.vscode.live_apply": lambda params: native_host.action_vscode_live_apply(
                        text=str(params.get("text") or ""),
                        active_app=params.get("active_app") or {},
                        editor_point=params.get("editor_point") or {},
                        confirmed=bool(params.get("confirmed")),
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
                # The disposable stdin editor is an Untitled buffer, while an
                # Extension Development Host omits "Untitled-1" from its OS
                # window title. Feed the normal captured title into the flow.
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
                verifier.evaluate(
                    "[...document.querySelectorAll('.monaco-editor .view-lines')].map(node => node.innerText).join('\\n')"
                )
                or ""
            ).replace("\u00a0", " ")
            result.update(
                {
                    "bridge_health": health,
                    "model_called": True,
                    "preview_called": bool(previews),
                    "preview_has_diff": bool(
                        previews and "openwand_api_test" in str(previews[-1]["params"].get("html") or "")
                    ),
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
            try:
                native_host._vscode_extension_api_adapter = None
            except UnboundLocalError:
                pass
            if brain is not None:
                brain.shutdown()
            if verifier is not None:
                verifier.close()
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
