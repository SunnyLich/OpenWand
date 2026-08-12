"""Real OpenWand model -> preview -> managed Chrome form API smoke."""

from __future__ import annotations

import base64
import json
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

from test_openwand_vscode_background_desktop import parent, stage, terminate_profile_processes  # noqa: E402
from test_openwand_vscode_cdp_flow_real import Worker  # noqa: E402
from test_openwand_vscode_cdp_real import Cdp, reserve_port  # noqa: E402

from core.actions.adapters.browser import BrowserActionAdapter  # noqa: E402


def inner() -> int:
    from runtime.supervisor.flows import FlowController, PendingInvocation
    from runtime.supervisor.ipc import WorkerClient, default_specs
    from runtime.workers import native_host

    executable = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    fixture = ROOT / "scripts" / "fixtures" / "browser_form.html"
    screenshot = ROOT / ".codex_tmp" / "chrome-form-api-after.png"
    screenshot.parent.mkdir(parents=True, exist_ok=True)
    if not executable.is_file():
        raise FileNotFoundError(executable)
    port = reserve_port()
    session_token = secrets.token_hex(24)
    result: dict[str, Any] = {
        "isolated_desktop": True,
        "transport": "chrome-devtools-protocol",
        "screenshot": str(screenshot),
    }
    with tempfile.TemporaryDirectory(prefix="openwand-chrome-form-flow-") as profile:
        stage("isolated_launch", profile=profile, port=port)
        process = subprocess.Popen(
            [
                str(executable),
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}",
                f"--remote-allow-origins=http://127.0.0.1:{port}",
                f"--openwand-managed-session={session_token}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-sync",
                "--disable-background-networking",
                "--new-window",
                fixture.as_uri(),
            ],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        brain = None
        verifier = None
        try:
            adapter = BrowserActionAdapter(session_token=session_token)
            deadline = time.monotonic() + 25.0
            snapshot = None
            last_error = ""
            active_app = {
                "name": "OpenWand Browser Action Test - Google Chrome",
                "process_name": "chrome.exe",
                "pid": int(process.pid),
                "window_id": 0,
                "browser_url": fixture.as_uri(),
            }
            while time.monotonic() < deadline:
                try:
                    snapshot = adapter.inspect_form(active_app)
                    if len(snapshot.fields) == 3:
                        break
                except Exception as exc:  # noqa: BLE001 - Chrome is still starting
                    last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(0.1)
            if snapshot is None or len(snapshot.fields) != 3:
                raise RuntimeError(f"Chrome form API did not become ready: {last_error}")
            stage("api_ready", title=snapshot.title, url=snapshot.url, fields=len(snapshot.fields))

            native_host._browser_action_adapter = adapter
            native = Worker(
                {
                    "native.action.browser.form_snapshot": lambda params: native_host.action_browser_form_snapshot(
                        params.get("active_app") or {}
                    ),
                    "native.action.browser.form_apply": lambda params: native_host.action_browser_form_apply(
                        plan=params.get("plan") or {},
                        confirmed=bool(params.get("confirmed")),
                        idempotency_key=str(params.get("idempotency_key") or ""),
                    ),
                }
            )
            ui = Worker(
                {
                    "ui.action.preview.request": lambda _params: {"approved": True},
                    # The smoke uses only synthetic contact data. Authorize that
                    # exact test payload so the real privacy gate is exercised
                    # and resolved instead of silently bypassed.
                    "ui.privacy.review.request": lambda _params: {
                        "approved": True,
                        "decision": "full",
                    },
                }
            )
            audio = Worker()
            brain = WorkerClient(default_specs()["brain"])
            flow = FlowController(native=native, ui=ui, brain=brain, audio=audio, run_async=False)
            flow.start(prewarm=False)
            now = time.time_ns()
            pending = PendingInvocation(
                caller_idx=0,
                caller={"paste_back": True, "context_clipboard": False},
                context={
                    "platform": "win32",
                    "active_app": active_app,
                    "browser_url": snapshot.url,
                    "selected_text": "",
                    "clipboard_text": "",
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
                "Fill this form with full name Sunny OpenWand, email sunny@example.test, and country tw."
            )

            previews = [call for call in ui.calls if call["method"] == "ui.action.preview.request"]
            applies = [call for call in native.calls if call["method"] == "native.action.browser.form_apply"]
            progress_calls = [call["params"] for call in ui.calls if call["method"] == "ui.action.progress"]
            notices = [call["params"] for call in ui.calls if call["method"] == "ui.reply.notice"]
            after = adapter.inspect_form(active_app)
            values = {field.selector: field.value for field in after.fields}
            target = adapter.discover(active_app)
            verifier = Cdp(target.websocket_url, f"http://127.0.0.1:{target.port}")
            verifier.call("Runtime.enable")
            submits = verifier.evaluate("document.querySelector('#contact-form')?.dataset.submits || '0'")
            capture = verifier.call("Page.captureScreenshot", {"format": "png", "fromSurface": True})
            screenshot.write_bytes(base64.b64decode(str(capture.get("data") or "")))
            result.update(
                {
                    "model_called": True,
                    "preview_called": bool(previews),
                    "preview_has_values": bool(
                        previews
                        and "Sunny OpenWand" in str(previews[-1]["params"].get("html") or "")
                        and "sunny@example.test" in str(previews[-1]["params"].get("html") or "")
                    ),
                    "api_apply_called": bool(applies),
                    "api_apply_response": applies[-1].get("result") if applies else {},
                    "progress": progress_calls,
                    "notices": notices,
                    "values": values,
                    "submit_count": str(submits),
                    "values_verified": (
                        values.get("#full-name") == "Sunny OpenWand"
                        and values.get("#email") == "sunny@example.test"
                        and values.get("#country") == "tw"
                    ),
                    "not_submitted": str(submits) == "0",
                    "screenshot_bytes": screenshot.stat().st_size if screenshot.is_file() else 0,
                }
            )
            stage(
                "flow_verified",
                preview_called=result["preview_called"],
                apply_ok=bool((result["api_apply_response"] or {}).get("ok")),
                values_verified=result["values_verified"],
                not_submitted=result["not_submitted"],
            )
        finally:
            native_host._browser_action_adapter = None
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
            result.get("preview_has_values"),
            result.get("api_apply_called"),
            (result.get("api_apply_response") or {}).get("ok"),
            result.get("values_verified"),
            result.get("not_submitted"),
            result.get("screenshot_bytes"),
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    raise SystemExit(inner() if "--inner" in sys.argv else parent(Path(__file__), "--inner"))
