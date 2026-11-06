"""An explicitly simulated provider at the HTTP boundary, outside OpenWand.

No model callback, UI object, worker, IPC handler, or persistence function is
patched. Requests must arrive through the production SDK over a real socket.
The response repeats a request-specific marker, so a hard-coded UI answer cannot
pass. Live provider verification is reported separately from this fixture.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class ProviderServer:
    def __init__(self, evidence_path: Path | None = None, *, break_response=False):
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        self.agent_calls: dict[str, int] = {}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):  # noqa: N802 - HTTP server interface
                self._journey_record = None
                self.reply({"object": "list", "data": [{"id": name, "object": "model"} for name in ("journey-model", "journey-discovered-model")]})

            def complete_record(self):
                record = getattr(self, "_journey_record", None)
                if record is not None:
                    with owner.lock:
                        record["response_finished_monotonic_ns"] = time.monotonic_ns()
                        if evidence_path is not None:
                            temporary = evidence_path.with_suffix(".tmp")
                            temporary.write_text(json.dumps(owner.requests, indent=2), encoding="utf-8")
                            temporary.replace(evidence_path)

            def reply(self, value, status=200):
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                self.complete_record()

            def do_POST(self):  # noqa: N802 - HTTP server interface
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                messages = payload.get("messages", payload.get("input", []))
                user_turns = [item.get("content", "") for item in messages if isinstance(item, dict) and item.get("role") == "user"]
                prompt = json.dumps(user_turns, ensure_ascii=False)
                latest_prompt = json.dumps(user_turns[-1] if user_turns else "")
                credential = "e2e-wizard-credential" if "E2E_ONBOARDING_PROMPT" in latest_prompt else "e2e-disposable-credential"
                authenticated = self.headers.get("Authorization") == "Bearer " + credential
                # Keep only synthetic request data. Authentication headers are
                # excluded; record only whether the expected fake key arrived.
                with owner.lock:
                    self._journey_record = {"path": self.path, "payload": payload, "authenticated": authenticated,
                                            "received_monotonic_ns": time.monotonic_ns()}
                    owner.requests.append(self._journey_record)
                    if evidence_path is not None:
                        temporary = evidence_path.with_suffix(".tmp")
                        temporary.write_text(json.dumps(owner.requests, indent=2), encoding="utf-8")
                        temporary.replace(evidence_path)
                if not authenticated:
                    self.reply({"error": {"message": "Journey credential rejected", "type": "authentication_error"}}, 401)
                    return
                if "E2E_FORCE_ERROR" in latest_prompt or payload.get("model") == "journey-unavailable":
                    self.reply({"error": {"message": "Journey provider temporarily unavailable", "type": "server_error"}}, 503)
                    return
                # These are deterministic model decisions at the external HTTP
                # boundary. The fixture never reads or writes the target files;
                # OpenWand's real tool loop, permissions and approval UI must do it.
                workspace = evidence_path.parent / "state" / "file-scope" if evidence_path else None
                tool_requests = {
                    "E2E_TOOL_READ": ("read_file", {"path": "readme.txt"}),
                    "E2E_TOOL_CREATE_AUTO": ("create_file", {"path": "automatic.txt", "content": "E2E_AUTOMATIC_FILE_CONTENT\n"}),
                    "E2E_TOOL_CREATE_APPROVE": ("create_file", {"path": "approved.txt", "content": "E2E_APPROVED_FILE_CONTENT\n"}),
                    "E2E_TOOL_CREATE_DECLINE": ("create_file", {"path": "declined.txt", "content": "E2E_MUST_NOT_BE_WRITTEN\n"}),
                    "E2E_TOOL_ESCAPE": ("create_file", {"path": "../outside-root.txt", "content": "E2E_MUST_STAY_INSIDE_ROOT\n"}),
                    "E2E_TOOL_BLOCKED": ("read_file", {"path": "private.secret"}),
                    "E2E_TOOL_WRITE": ("write_file", {"path": "automatic.txt", "content": "E2E_REPLACED_FILE_CONTENT\n"}),
                    "E2E_MEMORY_SAVE": ("memory_save", {"text": "E2E model memory: the release animal is an otter.", "scope": "project"}),
                    "E2E_MEMORY_SEARCH": ("memory_search", {"query": "release animal otter", "top_k": 5}),
                    "E2E_ADDON_TOOL": ("journey_addon_echo", {"text": "controlled payload"}),
                    "E2E_WORKSPACE_START": ("virtual_workspace_start", {}),
                    "E2E_WORKSPACE_DISABLED_WRITE": ("virtual_workspace_write_text", {"path": "must-not-exist.txt", "text": "E2E_FORBIDDEN_WORKSPACE_FILE"}),
                    "E2E_WORKSPACE_STOP": ("virtual_workspace_stop", {}),
                }
                last_user_index = max((i for i, item in enumerate(messages) if item.get("role") == "user"), default=-1)
                tool_results = [item.get("content", "") for item in messages[last_user_index + 1:] if item.get("role") == "tool"]
                offered = {item.get("function", {}).get("name") for item in payload.get("tools", [])}
                requested = next((value for marker, value in tool_requests.items() if marker in latest_prompt), None)
                if requested and not tool_results and requested[0] in offered:
                    name, arguments = requested
                    arguments = dict(arguments)
                    if workspace is not None and name in {"read_file", "write_file", "create_file"}:
                        arguments["root"] = str(workspace)
                    call = {"id": "call-journey", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}
                    if not payload.get("stream"):
                        self.reply({"id": "journey", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": None, "tool_calls": [call]}, "finish_reason": "tool_calls"}]})
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    delta = {"tool_calls": [{"index": 0, **call}]}
                    chunk = {"id": "journey", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                    end = {"id": "journey", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]}
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: " + json.dumps(end) + "\n\ndata: [DONE]\n\n").encode())
                    self.wfile.flush()
                    self.complete_record()
                    return
                # Echo user context, not the secret-bearing request headers.
                # Code formatting preserves marker underscores in the rendered
                # UI. Echo user turns only, never the app's hidden system prompt.
                answer = "Journey response:\n\n```text\n" + prompt + ("\nTool results: " + json.dumps(tool_results) if tool_results else "") + "\n```"
                if "E2E_SLOW_ICON_PROMPT" in latest_prompt:
                    # Give the real parser/renderers sustained ordinary prose
                    # before the fenced markers. Partial display must not rely
                    # on a single short frame between network completion events.
                    answer = answer.replace("Journey response:\n\n", "Journey response:\n\n" + "The controlled reply is arriving gradually. " * 12 + "\n\n", 1)
                # Agent tasks use their production JSON protocol, independently
                # of Chat's native function-call loop. Only the model's decisions
                # are controlled; the real runner must route and execute them.
                agent_marker = next((marker for marker in ("E2E_AGENT_SMOKE", "E2E_AGENT_TEAM_WRITE", "E2E_AGENT_ASK_APPROVE", "E2E_AGENT_ASK_DECLINE", "E2E_SLOW_AGENT_CANCEL") if marker in latest_prompt), None)
                if agent_marker:
                    with owner.lock:
                        turn = owner.agent_calls[agent_marker] = owner.agent_calls.get(agent_marker, 0) + 1
                    decision = {"thought": "Controlled acceptance model decision.", "status": "done", "next_agent": "Coordinator", "reason": "The requested acceptance work is complete.", "tool_calls": [], "final": "E2E_AGENT_SUCCESS: the controlled task finished."}
                    if agent_marker in {"E2E_AGENT_TEAM_WRITE", "E2E_AGENT_ASK_APPROVE", "E2E_AGENT_ASK_DECLINE"} and turn < 4:
                        decision.update(status="ready_for_review" if turn == 2 else "continue", next_agent={1: "Builder", 2: "Reviewer", 3: "Coordinator"}[turn], final=None)
                        if turn == 2:
                            name = {"E2E_AGENT_TEAM_WRITE": "e2e-agent-output.txt", "E2E_AGENT_ASK_APPROVE": "approved-agent.txt", "E2E_AGENT_ASK_DECLINE": "declined-agent.txt"}[agent_marker]
                            decision["tool_calls"] = [{"tool": "create_file", "args": {"path": name, "content": "E2E_AGENT_CREATED_FILE\n"}}]
                    if agent_marker == "E2E_AGENT_ASK_DECLINE" and turn >= 4:
                        decision["final"] = "E2E_AGENT_DECLINED_FILE: the user declined this write."
                    if agent_marker == "E2E_SLOW_AGENT_CANCEL":
                        decision["thought"] = "A deliberately slow, cancellable model response. " * 100
                    answer = json.dumps(decision)
                if break_response:
                    answer = "Intentionally uncorrelated provider response"
                self._journey_record["response_variant"] = "unrelated" if break_response else "agent protocol" if agent_marker else "echo"
                if not payload.get("stream"):
                    self.reply({"id": "journey", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                pieces = [answer[i:i + 48] for i in range(0, len(answer), 48)]
                try:
                    for piece in pieces:
                        chunk = {"id": "journey", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
                        self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                        self.wfile.flush()
                        time.sleep(0.025 if "E2E_SLOW" not in prompt else 0.3)
                    chunk = {"id": "journey", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                    self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # Cancellation is a user action, not a server crash.
                self.complete_record()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
