"""Isolated end-to-end acceptance runner for chat-delegated background work.

This is launched in a fresh Python process so every OpenWand path resolves beneath
the supplied temporary directory. A tiny local OpenAI-compatible endpoint
drives a real chat tool call; the detached worker uses OpenWand's existing scripted
Agent Team seam to make the filesystem result deterministic.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


def _agent_script(output_name: str) -> list[dict[str, Any]]:
    return [
        {
            "thought": "Assign the requested implementation.",
            "status": "continue",
            "next_agent": "Builder",
            "reason": "The builder owns the file change.",
            "tool_calls": [
                {
                    "tool": "send_message",
                    "args": {
                        "to": "Builder",
                        "message": f"Create {output_name}, then ask Reviewer to verify it.",
                    },
                }
            ],
            "final": None,
        },
        {
            "thought": "Create the requested acceptance module.",
            "status": "continue",
            "next_agent": "Reviewer",
            "reason": "The file is ready for verification.",
            "tool_calls": [
                {
                    "tool": "create_file",
                    "args": {
                        "path": output_name,
                        "content": (
                            "def acceptance_marker() -> str:\n"
                            "    return \"openwand-background-task-e2e\"\n"
                        ),
                    },
                },
                {
                    "tool": "send_message",
                    "args": {
                        "to": "Reviewer",
                        "message": f"Compile-check {output_name}.",
                    },
                },
            ],
            "final": None,
        },
        {
            "thought": "Verify the generated module with the local interpreter.",
            "status": "continue",
            "next_agent": "Coordinator",
            "reason": "The coordinator can close the verified task.",
            "tool_calls": [
                {
                    "tool": "run_command",
                    "args": {"args": [sys.executable, "-m", "py_compile", output_name]},
                },
                {
                    "tool": "send_message",
                    "args": {
                        "to": "Coordinator",
                        "message": f"{output_name} compiled successfully.",
                    },
                },
            ],
            "final": None,
        },
        {
            "thought": "The implementation and independent verification are complete.",
            "status": "complete",
            "next_agent": "same",
            "reason": "The requested file exists and compilation passed.",
            "tool_calls": [],
            "final": (
                f"Created {output_name}; verified openwand-background-task-e2e "
                "with Python bytecode compilation."
            ),
        },
    ]


class _ChatModelServer:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.requests: list[dict[str, Any]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                length = int(self.headers.get("Content-Length", "0") or 0)
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.requests.append(body)
                if body.get("stream"):
                    self._write_tool_stream(body)
                else:
                    self._write_final_response(body)

            def _write_tool_stream(self, body: dict[str, Any]) -> None:
                arguments = json.dumps(
                    {
                        "objective": (
                            "Create background_acceptance_output.py with an acceptance_marker "
                            "function and compile-check it."
                        ),
                        "title": "Background task acceptance",
                        "folder": str(owner.workspace),
                    }
                )
                chunks = [
                    {
                        "id": "chatcmpl-background-e2e",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": str(body.get("model") or "openwand-test-model"),
                        "choices": [
                            {
                                "index": 0,
                                "delta": {
                                    "role": "assistant",
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": "call-background-e2e",
                                            "type": "function",
                                            "function": {
                                                "name": "delegate_background_task",
                                                "arguments": arguments,
                                            },
                                        }
                                    ],
                                },
                                "finish_reason": None,
                            }
                        ],
                    },
                    {
                        "id": "chatcmpl-background-e2e",
                        "object": "chat.completion.chunk",
                        "created": int(time.time()),
                        "model": str(body.get("model") or "openwand-test-model"),
                        "choices": [
                            {
                                "index": 0,
                                "delta": {},
                                "finish_reason": "tool_calls",
                            }
                        ],
                    },
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                for chunk in chunks:
                    self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()

            def _write_final_response(self, body: dict[str, Any]) -> None:
                payload = {
                    "id": "chatcmpl-background-e2e-final",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": str(body.get("model") or "openwand-test-model"),
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "The background task is running and will report here.",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def start(self) -> None:
        self.thread.start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class _BoundaryWorker:
    def on_event(self, _event: str, _handler) -> None:
        return

    def call(self, _method: str, _params=None, **_kwargs):
        return {}


def _configure_environment(root: Path, workspace: Path, script_path: Path, base_url: str) -> None:
    repo = Path(__file__).resolve().parents[2]
    python_path = os.pathsep.join([str(repo), str(repo / "runtime" / "brain")])
    for path in (repo, repo / "runtime" / "brain"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    values = {
        "OPENWAND_DATA_ROOT": str(root / "data"),
        "OPENWAND_USER_DATA_DIR": str(root / "user-data"),
        "OPENWAND_RUN_LOG_DIR": str(root / "logs"),
        "OPENWAND_ADDONS_DIR": str(root / "addons"),
        "OPENWAND_BRAIN_AGENT_TEST_SCRIPT": str(script_path),
        "LLM_PROVIDER": "custom",
        "LLM_MODEL": "openwand-test-model",
        "CHAT_LLM_PROVIDER": "custom",
        "CHAT_LLM_MODEL": "openwand-test-model",
        "CUSTOM_API_KEY": "local-acceptance-key",
        "CUSTOM_BASE_URL": base_url,
        "PROFILE_COUNT": "0",
        "SETTINGS_PROFILE": "default",
        "ACTIVE_PROFILE": "default",
        "TOOL_FILE_ROOTS": str(workspace),
        "CHAT_EXECUTION_MODE": "openwand",
        "CHAT_CONVERSATION_OWNER": "openwand",
        "PRIVACY_MODE": "builtin",
        "MEMORY_AUTO_CONSOLIDATE": "0",
        "QT_QPA_PLATFORM": "offscreen",
        "OPENWAND_UI_DEBUG_METHODS": "1",
        "PYTHONPATH": python_path,
    }
    os.environ.update(values)


def run(root: Path) -> dict[str, Any]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    output_name = "background_acceptance_output.py"
    script_path = root / "agent-script.json"
    script_path.write_text(
        json.dumps(_agent_script(output_name), indent=2),
        encoding="utf-8",
    )
    server = _ChatModelServer(workspace)
    server.start()
    _configure_environment(root, workspace, script_path, server.base_url)

    from runtime.supervisor.flows import FlowController
    from runtime.supervisor.ipc import WorkerClient, WorkerSpec

    shared_env = dict(os.environ)
    ui = WorkerClient(
        WorkerSpec(
            "ui",
            "runtime.workers.ui_host",
            "ui",
            env={**shared_env, "QT_QPA_PLATFORM": "offscreen"},
        )
    )
    brain = WorkerClient(
        WorkerSpec("brain", "runtime.workers.brain_host", "brain", env=shared_env)
    )
    boundary = _BoundaryWorker()
    flow = FlowController(native=boundary, ui=ui, brain=brain, audio=boundary, run_async=False)
    policy = {
        "context_ambient": False,
        "context_documents_mode": "off",
        "context_browser_mode": "off",
        "context_github_mode": "off",
        "context_memory_mode": "off",
        "context_screenshot": "off",
        "file_access": "auto",
    }
    prompt = "Please do this substantial coding task in the background and let me keep chatting."
    try:
        flow.start()
        started = ui.call(
            "ui.chat.begin_conversation",
            {"user": prompt, "context_policy": policy},
            timeout=20,
        )
        conversation_id = str(started.get("conversation_id") or "")
        if not conversation_id:
            raise AssertionError(f"conversation did not start: {started!r}")
        flow.chat_request(
            {
                "request_id": "background-task-e2e",
                "conversation_id": conversation_id,
                "messages": [{"role": "user", "content": prompt}],
                "context_policy": policy,
            }
        )

        deadline = time.monotonic() + 45
        history: dict[str, Any] = {}
        background_message: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            history = ui.call("ui.chat.active_history", timeout=20)
            background_message = next(
                (
                    message
                    for message in history.get("history", [])
                    if isinstance(message, dict)
                    and "Background task finished" in str(message.get("content") or "")
                ),
                None,
            )
            if background_message is not None and (workspace / output_name).is_file():
                break
            time.sleep(0.1)
        if background_message is None:
            raise AssertionError(f"background result did not reach the chat: {history!r}")

        output_path = workspace / output_name
        content = output_path.read_text(encoding="utf-8")
        if "openwand-background-task-e2e" not in content:
            raise AssertionError(f"detached worker wrote unexpected content: {content!r}")
        jobs = sorted(
            path
            for path in (root / "data" / "memory" / "agent_runs" / "background_jobs").glob("job-*.json")
            if not path.name.endswith(".spec.json")
        )
        if len(jobs) != 1:
            raise AssertionError(f"expected one persisted background job, found {jobs!r}")
        state = json.loads(jobs[0].read_text(encoding="utf-8"))
        if state.get("status") != "completed" or not state.get("delivered_at"):
            raise AssertionError(f"job did not complete and deliver: {state!r}")
        if len(server.requests) < 2:
            raise AssertionError("the real chat tool loop did not make both provider rounds")
        offered = server.requests[0].get("tools") or []
        tool_names = {
            str((tool.get("function") or {}).get("name") or "")
            for tool in offered
            if isinstance(tool, dict)
        }
        if "delegate_background_task" not in tool_names:
            raise AssertionError(f"background tool was not offered to the model: {tool_names!r}")
        return {
            "conversation_id": conversation_id,
            "job_id": state.get("job_id"),
            "job_status": state.get("status"),
            "delivered": bool(state.get("delivered_at")),
            "output_path": str(output_path),
            "provider_rounds": len(server.requests),
            "tool_offered": "delegate_background_task" in tool_names,
            "chat_result": str(background_message.get("content") or ""),
        }
    finally:
        brain.shutdown()
        ui.shutdown()
        server.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    result = run(Path(args.root).resolve())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
