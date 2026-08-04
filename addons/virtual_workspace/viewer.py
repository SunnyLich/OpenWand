"""Authenticated loopback IPC bridge for Wisp's native workspace window."""
from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class ViewerServer:
    """Expose workspace state to Wisp's native UI process on loopback only."""

    def __init__(
        self,
        snapshot: Callable[[], dict[str, Any]],
        control: Callable[[str], dict[str, Any]],
        read_text: Callable[[str], dict[str, Any]],
        read_preview: Callable[[str], dict[str, Any]],
        check_file: Callable[[str], dict[str, Any]],
        task_scope: Callable[[], dict[str, Any]],
        record_event: Callable[[dict[str, Any]], dict[str, Any]],
        save_user_text: Callable[[str, str, int], dict[str, Any]],
        apply_user_file_operation: Callable[[str, str, str, str], dict[str, Any]],
    ) -> None:
        self._snapshot = snapshot
        self._control = control
        self._read_text = read_text
        self._read_preview = read_preview
        self._check_file = check_file
        self._task_scope = task_scope
        self._record_event = record_event
        self._save_user_text = save_user_text
        self._apply_user_file_operation = apply_user_file_operation
        self._token = secrets.token_urlsafe(32)
        self._server: _LoopbackServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        """Return the authenticated endpoint consumed by Wisp's native window."""
        if self._server is None:
            raise RuntimeError("workspace bridge is not running")
        port = int(self._server.server_address[1])
        return f"http://127.0.0.1:{port}/?token={quote(self._token)}"

    def start(self) -> None:
        """Bind to IPv4 loopback and start the daemon request thread."""
        if self._server is not None:
            return
        server = _LoopbackServer(("127.0.0.1", 0), self._handler_type())
        thread = threading.Thread(
            target=server.serve_forever,
            name="wisp-workspace-bridge",
            daemon=True,
        )
        self._server = server
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        """Stop the bridge without deleting session data."""
        server, self._server = self._server, None
        thread, self._thread = self._thread, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "WispWorkspaceBridge/1"
            sys_version = ""

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlsplit(self.path)
                if parsed.path not in {
                    "/api/state",
                    "/api/file",
                    "/api/preview",
                    "/api/task-scope",
                }:
                    self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                if not self._authorized():
                    self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                try:
                    if parsed.path == "/api/state":
                        self._send_json(owner._snapshot())
                        return
                    if parsed.path == "/api/task-scope":
                        self._send_json(owner._task_scope())
                        return
                    path = str((parse_qs(parsed.query).get("path") or [""])[0])
                    result = (
                        owner._read_preview(path)
                        if parsed.path == "/api/preview"
                        else owner._read_text(path)
                    )
                    self._send_json(result)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

            def do_POST(self) -> None:  # noqa: N802
                route = urlsplit(self.path).path
                if route not in {
                    "/api/control",
                    "/api/event",
                    "/api/check",
                    "/api/save",
                    "/api/files",
                }:
                    self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return
                if not self._authorized():
                    self._send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 2 or length > 16_384:
                        raise ValueError("invalid body")
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(body, dict):
                        raise ValueError("body must be an object")
                    if route == "/api/control":
                        result = owner._control(str(body.get("action") or ""))
                    elif route == "/api/check":
                        result = owner._check_file(str(body.get("path") or ""))
                    elif route == "/api/save":
                        result = owner._save_user_text(
                            str(body.get("path") or ""),
                            str(body.get("text") or ""),
                            int(body.get("expected_modified_ns") or 0),
                        )
                    elif route == "/api/files":
                        result = owner._apply_user_file_operation(
                            str(body.get("action") or ""),
                            str(body.get("path") or ""),
                            str(body.get("name") or ""),
                            str(body.get("kind") or "file"),
                        )
                    else:
                        result = owner._record_event(body)
                    self._send_json(result)
                except Exception as exc:
                    self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

            def log_message(self, _format: str, *args: Any) -> None:
                return

            def _authorized(self) -> bool:
                supplied = self.headers.get("Authorization", "")
                return secrets.compare_digest(supplied, f"Bearer {owner._token}")

            def _send_json(
                self,
                value: dict[str, Any],
                status: HTTPStatus = HTTPStatus.OK,
            ) -> None:
                payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                    # The native window may close while an asynchronous progress
                    # event is being acknowledged.  The event was already recorded.
                    return

        return Handler
