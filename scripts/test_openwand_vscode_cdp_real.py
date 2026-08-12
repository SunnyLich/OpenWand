"""Real focusless VS Code Untitled edit through a private DevTools API."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from test_openwand_vscode_background_desktop import (  # noqa: E402
    parent,
    stage,
    terminate_profile_processes,
    wait_for_code_window,
    windows,
)


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


def wait_for_target(port: int, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.0) as response:
                targets = json.loads(response.read().decode("utf-8"))
            pages = [item for item in targets if item.get("type") == "page" and item.get("webSocketDebuggerUrl")]
            for page in pages:
                if "visual studio code" in str(page.get("title") or "").casefold():
                    return page
            if pages:
                return pages[0]
        except Exception as exc:  # noqa: BLE001 - endpoint is still starting
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.1)
    raise RuntimeError(f"VS Code DevTools target did not appear: {last_error}")


class Cdp:
    def __init__(self, url: str, origin: str) -> None:
        from websockets.sync.client import connect

        self.socket = connect(url, origin=origin, open_timeout=5.0, close_timeout=2.0)
        self.sequence = 0

    def close(self) -> None:
        self.socket.close()

    def call(self, method: str, params: dict | None = None) -> dict:
        self.sequence += 1
        request_id = self.sequence
        self.socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.socket.recv(timeout=10.0))
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return dict(message.get("result") or {})

    def evaluate(self, expression: str):
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        return ((result.get("result") or {}).get("value"))


def inner() -> int:
    executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    marker = f'print("OpenWand VS Code API smoke {time.time_ns()}")'
    result: dict = {"marker": marker, "isolated_desktop": True, "transport": "cdp"}
    port = reserve_port()
    with tempfile.TemporaryDirectory(prefix="openwand-vscode-cdp-") as profile:
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
        try:
            hwnd, title = wait_for_code_window()
            deadline = time.monotonic() + 15.0
            while "visual studio code" in title.casefold() and time.monotonic() < deadline:
                if title.startswith("\u25cf") or "code-stdin" in title.casefold():
                    break
                time.sleep(0.2)
                title = windows().get(hwnd, title)
            target = wait_for_target(port)
            stage("api_connected", hwnd=hwnd, title=title, target_title=target.get("title"))
            client = Cdp(str(target["webSocketDebuggerUrl"]), f"http://127.0.0.1:{port}")
            try:
                client.call("Runtime.enable")
                result["renderer_globals"] = client.evaluate(
                    """
                    ({monaco: typeof globalThis.monaco,
                      amdRequire: typeof globalThis.require,
                      amdDefine: typeof globalThis.define,
                      vscode: typeof globalThis.vscode,
                      electron: typeof globalThis.electron})
                    """
                )
                result["vscode_bridge"] = client.evaluate(
                    """
                    (() => {
                      const bridge = globalThis.vscode;
                      if (!bridge) return null;
                      const describe = value => {
                        if (value == null) return String(value);
                        const type = typeof value;
                        if (type !== 'object' && type !== 'function') return type;
                        try { return Object.getOwnPropertyNames(value).slice(0, 80); }
                        catch (_) { return type; }
                      };
                      const keys = Object.getOwnPropertyNames(bridge);
                      return {
                        keys,
                        members: Object.fromEntries(keys.map(key => [key, describe(bridge[key])]))
                      };
                    })()
                    """
                )
                editor = None
                dom_status = None
                deadline = time.monotonic() + 12.0
                while time.monotonic() < deadline:
                    dom_status = client.evaluate(
                        """
                        (() => {
                          const nodes = [...document.querySelectorAll('.monaco-editor')];
                          const textareas = [...document.querySelectorAll('textarea')];
                          const candidate = nodes.find(node => node.querySelector('textarea.inputarea'))
                            || nodes.find(node => node.getBoundingClientRect().width > 100);
                          let editor = null;
                          if (candidate) {
                            const rect = candidate.getBoundingClientRect();
                            editor = {x: rect.x + rect.width * 0.45, y: rect.y + rect.height * 0.35,
                                      width: rect.width, height: rect.height};
                          }
                          return {editor, readyState: document.readyState, monacoCount: nodes.length,
                                  textareaCount: textareas.length,
                                  textareaClasses: textareas.map(node => node.className).slice(0, 10),
                                  bodyText: (document.body?.innerText || '').slice(0, 500)};
                        })()
                        """
                    )
                    editor = (dom_status or {}).get("editor") if isinstance(dom_status, dict) else None
                    if editor:
                        break
                    time.sleep(0.2)
                if not editor:
                    raise RuntimeError(f"Monaco editor DOM was not found through the API: {dom_status!r}")
                x, y = float(editor["x"]), float(editor["y"])
                client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
                client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
                client.call("Input.insertText", {"text": marker})
                deadline = time.monotonic() + 2.0
                rendered_text = ""
                logical_text = ""
                while time.monotonic() < deadline:
                    rendered_text = str(
                        client.evaluate(
                            "[...document.querySelectorAll('.monaco-editor .view-lines')].map(node => node.innerText).join('\\n')"
                        )
                        or ""
                    )
                    logical_text = rendered_text.replace("\u00a0", " ")
                    if marker in logical_text:
                        break
                    time.sleep(0.1)
                result.update(
                    {
                        "hwnd": hwnd,
                        "title": title,
                        "target_title": target.get("title"),
                        "editor_rect": editor,
                        "rendered_text": rendered_text,
                        "logical_text": logical_text,
                        "text_verified": marker in logical_text,
                    }
                )
                stage("verified", text_verified=result["text_verified"])
            finally:
                client.close()
        finally:
            result["owned_processes_cleaned"] = terminate_profile_processes(profile)
            if process.poll() is None:
                process.terminate()
            stage("cleanup_finished", owned_processes=result["owned_processes_cleaned"])
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
    return 0 if result.get("text_verified") else 1


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    raise SystemExit(inner() if "--inner" in sys.argv else parent(Path(__file__), "--inner"))
