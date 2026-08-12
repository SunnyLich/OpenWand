"""Focusless live-editor transport for OpenWand-managed VS Code instances."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class VSCodeDevToolsTarget:
    port: int
    title: str
    websocket_url: str


class _CdpClient:
    def __init__(self, target: VSCodeDevToolsTarget) -> None:
        from websockets.sync.client import connect

        self._socket = connect(
            target.websocket_url,
            origin=f"http://127.0.0.1:{target.port}",
            open_timeout=3.0,
            close_timeout=1.0,
        )
        self._sequence = 0

    def close(self) -> None:
        self._socket.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sequence += 1
        request_id = self._sequence
        self._socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            payload = json.loads(self._socket.recv(timeout=10.0))
            if payload.get("id") != request_id:
                continue
            if payload.get("error"):
                raise RuntimeError(f"VS Code DevTools {method} failed: {payload['error']}")
            return dict(payload.get("result") or {})

    def evaluate(self, expression: str) -> Any:
        payload = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return ((payload.get("result") or {}).get("value"))


class VSCodeDevToolsAdapter:
    """Insert into the focused Monaco editor through a private localhost CDP endpoint."""

    def _managed_ports(self) -> set[int]:
        import psutil

        ports: set[int] = set()
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                if str(process.info.get("name") or "").casefold() != "code.exe":
                    continue
                command_line = " ".join(process.info.get("cmdline") or [])
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
            match = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", command_line)
            if match and int(match.group(1)) > 0:
                ports.add(int(match.group(1)))
        return ports

    @staticmethod
    def _targets_for_port(port: int) -> list[VSCodeDevToolsTarget]:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.0) as response:
            rows = json.loads(response.read().decode("utf-8"))
        targets: list[VSCodeDevToolsTarget] = []
        for row in rows if isinstance(rows, list) else []:
            url = str(row.get("webSocketDebuggerUrl") or "")
            parsed = urlparse(url)
            if row.get("type") != "page" or parsed.scheme not in {"ws", "wss"}:
                continue
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                continue
            targets.append(
                VSCodeDevToolsTarget(
                    port=port,
                    title=str(row.get("title") or ""),
                    websocket_url=url,
                )
            )
        return targets

    def discover(self, active_app: dict[str, Any] | None = None) -> VSCodeDevToolsTarget:
        expected_title = " ".join(str((active_app or {}).get("name") or "").casefold().split())
        targets: list[VSCodeDevToolsTarget] = []
        for port in sorted(self._managed_ports()):
            try:
                targets.extend(self._targets_for_port(port))
            except Exception:
                continue
        if expected_title:
            exact = [target for target in targets if " ".join(target.title.casefold().split()) == expected_title]
            if len(exact) == 1:
                return exact[0]
        vscode_targets = [target for target in targets if "visual studio code" in target.title.casefold()]
        if len(vscode_targets) == 1:
            return vscode_targets[0]
        if not vscode_targets:
            raise RuntimeError(
                "This VS Code window was not launched with OpenWand's private editor API enabled."
            )
        raise RuntimeError("OpenWand could not identify one unique managed VS Code editor window.")

    def apply_text(
        self,
        text: str,
        active_app: dict[str, Any] | None = None,
        *,
        editor_point: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        replacement = str(text or "")
        if not replacement:
            return {"ok": False, "method": "vscode-devtools", "error": "empty editor replacement"}
        target = self.discover(active_app)
        client = _CdpClient(target)
        try:
            client.call("Runtime.enable")
            # DevTools input is delivered only to the active Electron page.
            # In OpenWand's isolated desktop this activates VS Code on that hidden
            # desktop, never the user's visible desktop or physical cursor.
            client.call("Page.bringToFront")
            point = editor_point if isinstance(editor_point, dict) else {}
            if point.get("x") is not None and point.get("y") is not None:
                x, y = float(point["x"]), float(point["y"])
                client.call(
                    "Input.dispatchMouseEvent",
                    {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1},
                )
                client.call(
                    "Input.dispatchMouseEvent",
                    {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1},
                )
            client.evaluate(
                """
                (() => {
                  let active = document.activeElement;
                  if (!active?.matches?.('textarea.inputarea')) {
                    const candidate = document.querySelector(
                      'textarea.inputarea[aria-label*="Editor content"], '
                      + '.monaco-editor.focused textarea.inputarea'
                    );
                    candidate?.focus?.({preventScroll: true});
                    active = document.activeElement;
                  }
                  const editor = active?.closest?.('.monaco-editor')
                    || active?.parentElement?.closest?.('.monaco-editor');
                  return {textarea: !!active?.matches?.('textarea.inputarea'), editor: !!editor,
                          inMainEditor: /editor content/i.test(active?.getAttribute?.('aria-label') || '')
                            || !!active?.closest?.('.part.editor'),
                          tag: active?.tagName || '', className: active?.className || ''};
                })()
                """
            )
            encoded_replacement = json.dumps(replacement)
            dom_insert = client.evaluate(
                f"""
                (() => {{
                  const textarea = document.activeElement?.matches?.('textarea.inputarea')
                    ? document.activeElement
                    : document.querySelector(
                        '.monaco-editor.focused textarea.inputarea, '
                        + 'textarea.inputarea[aria-label*="Editor content"]'
                      );
                  if (!textarea) return {{ok: false, reason: 'no editor textarea'}};
                  textarea.focus({{preventScroll: true}});
                  const value = {encoded_replacement};
                  const setter = Object.getOwnPropertyDescriptor(
                    HTMLTextAreaElement.prototype, 'value'
                  )?.set;
                  setter?.call(textarea, value);
                  textarea.selectionStart = textarea.selectionEnd = value.length;
                  textarea.dispatchEvent(new InputEvent('input', {{
                    bubbles: true,
                    composed: true,
                    data: value,
                    inputType: 'insertText'
                  }}));
                  return {{ok: true, active: document.activeElement === textarea}};
                }})()
                """
            )

            def verify_visible(timeout: float) -> bool:
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    visible = str(
                        client.evaluate(
                            "[...document.querySelectorAll('.monaco-editor.focused .view-lines, "
                            ".monaco-editor .view-lines')].map(node => node.innerText).join('\\n')"
                        )
                        or ""
                    ).replace("\u00a0", " ")
                    if replacement in visible:
                        return True
                    time.sleep(0.05)
                return False

            verified = bool((dom_insert or {}).get("ok")) and verify_visible(1.0)
            if not verified:
                client.call("Input.insertText", {"text": replacement})
                verified = verify_visible(2.0)
            if not verified:
                raise RuntimeError("VS Code did not verify the reviewed text in the live editor.")
            return {
                "ok": True,
                "method": "vscode-devtools",
                "activated": False,
                "confirmed": True,
                "text_verified": True,
                "target_title": target.title,
                "target_port": target.port,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001 - return a controlled native failure
            return {
                "ok": False,
                "method": "vscode-devtools",
                "activated": False,
                "confirmed": False,
                "text_verified": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        finally:
            client.close()
