"""Real disposable VS Code Untitled insertion smoke using Wisp's captured range."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _stage(name: str, **data: Any) -> None:
    print(json.dumps({"stage": name, **data}, ensure_ascii=False), flush=True)


class Worker:
    def __init__(self, handlers=None, stream_handlers=None) -> None:
        self.handlers = handlers or {}
        self.stream_handlers = stream_handlers or {}
        self.calls: list[dict[str, Any]] = []
        self.events: dict[str, list[Any]] = {}

    def call(self, method, params=None, *, on_event=None, **_kwargs):
        payload = params or {}
        self.calls.append({"method": method, "params": payload})
        if method in self.stream_handlers:
            return self.stream_handlers[method](payload, on_event or (lambda *_args: None))
        handler = self.handlers.get(method)
        return handler(payload) if handler else {}

    def on_event(self, event, handler):
        self.events.setdefault(event, []).append(handler)


def _windows() -> dict[int, str]:
    user32 = ctypes.windll.user32
    output: dict[int, str] = {}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length:
            value = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, value, len(value))
            output[int(hwnd)] = value.value
        return True

    user32.EnumWindows(callback, 0)
    return output


def _wait_new_window(before: set[int], process: subprocess.Popen, timeout: float = 45.0) -> tuple[int, str]:
    import psutil

    deadline = time.monotonic() + timeout
    last_new: dict[int, str] = {}
    while time.monotonic() < deadline:
        try:
            root = psutil.Process(process.pid)
            pids = {process.pid, *(child.pid for child in root.children(recursive=True))}
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pids = {process.pid}
        last_new = {hwnd: title for hwnd, title in _windows().items() if hwnd not in before}
        for hwnd, title in last_new.items():
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids or "visual studio code" in title.casefold():
                return hwnd, title
        # The Windows CLI is only a launcher and may exit successfully before
        # the isolated Electron window appears.
        time.sleep(0.1)
    raise RuntimeError(f"Disposable VS Code window did not appear; new windows={last_new!r}")


def _window_title(hwnd: int) -> str:
    user32 = ctypes.windll.user32
    length = int(user32.GetWindowTextLengthW(hwnd) or 0)
    value = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, value, len(value))
    return value.value


def _force_foreground(hwnd: int) -> bool:
    """Temporarily focus the disposable off-screen window for Ctrl+N/caret capture."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    foreground = int(user32.GetForegroundWindow() or 0)
    foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None) or 0)
    target_thread = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
    current_thread = int(kernel32.GetCurrentThreadId() or 0)
    attached_foreground = False
    attached_target = False
    try:
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
        if target_thread and target_thread not in {current_thread, foreground_thread}:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        user32.ShowWindow(hwnd, 9)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetFocus(hwnd)
    finally:
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)
        if attached_foreground:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if int(user32.GetForegroundWindow() or 0) == hwnd:
            return True
        time.sleep(0.05)
    return False


def _send_ctrl_n_native() -> None:
    """Issue Ctrl+N with Win32 virtual-key events for test setup only."""
    user32 = ctypes.windll.user32
    key_up = 0x0002
    user32.keybd_event(0x11, 0, 0, 0)  # Ctrl down
    time.sleep(0.03)
    user32.keybd_event(0x4E, 0, 0, 0)  # N down
    user32.keybd_event(0x4E, 0, key_up, 0)
    user32.keybd_event(0x11, 0, key_up, 0)


def _invoke_vscode_new_text_file(hwnd: int) -> bool:
    """Create an Untitled editor through VS Code's exposed UIA menu."""
    import comtypes.client

    comtypes.client.GetModule("UIAutomationCore.dll")
    import comtypes.gen.UIAutomationClient as uiac  # type: ignore

    uia = comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=uiac.IUIAutomation,
    )
    window = uia.ElementFromHandle(hwnd)
    name_property = getattr(uiac, "UIA_NamePropertyId", 30005)
    descendants = getattr(uiac, "TreeScope_Descendants", 4)
    invoke_id = getattr(uiac, "UIA_InvokePatternId", 10000)

    def activate(element, *, expand: bool = False) -> bool:
        attempts = (
            (
                getattr(uiac, "UIA_ExpandCollapsePatternId", 10005),
                uiac.IUIAutomationExpandCollapsePattern,
                "Expand" if expand else "Collapse",
            ),
            (invoke_id, uiac.IUIAutomationInvokePattern, "Invoke"),
            (
                getattr(uiac, "UIA_LegacyIAccessiblePatternId", 10018),
                uiac.IUIAutomationLegacyIAccessiblePattern,
                "DoDefaultAction",
            ),
        )
        for pattern_id, interface, method in attempts:
            try:
                pattern = element.GetCurrentPattern(pattern_id).QueryInterface(interface)
                getattr(pattern, method)()
                return True
            except Exception:
                continue
        try:
            element.SetFocus()
            send_keys("enter")
            return True
        except Exception:
            return False

    file_menu = window.FindFirst(descendants, uia.CreatePropertyCondition(name_property, "File"))
    if file_menu is None:
        return False
    if not activate(file_menu, expand=True):
        return False
    time.sleep(0.25)

    root = uia.GetRootElement()
    elements = root.FindAll(descendants, uia.CreateTrueCondition())
    for index in range(elements.Length):
        element = elements.GetElement(index)
        try:
            name = str(element.CurrentName or "")
        except Exception:
            continue
        if name.casefold().startswith("new text file"):
            return activate(element)
    return False


def _document_text() -> str:
    from runtime.workers import native_host

    element = native_host._focus_cache.get("element")
    if element is None:
        return ""
    import comtypes.gen.UIAutomationClient as uiac  # type: ignore

    raw = element.GetCurrentPattern(native_host._UIA_TEXT_PATTERN_ID)
    pattern = raw.QueryInterface(uiac.IUIAutomationTextPattern)
    return str(pattern.DocumentRange.GetText(-1) or "")


def main() -> int:
    if sys.platform != "win32":
        raise RuntimeError("Windows only")
    from core.platform_utils import get_foreground_window, send_keys, set_foreground_window
    from runtime.supervisor.flows import FlowController, PendingInvocation
    from runtime.workers import native_host

    code = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"
    if not code.exists():
        raise FileNotFoundError(code)
    user32 = ctypes.windll.user32
    original_foreground = int(get_foreground_window() or 0)
    original_clipboard = str(native_host.clipboard_get().get("text") or "")
    marker = f'print("Wisp Untitled real smoke {time.time_ns()}")'
    result: dict[str, Any] = {
        "original_foreground": original_foreground,
        "marker": marker,
    }

    with tempfile.TemporaryDirectory(prefix="wisp-vscode-untitled-") as temp_dir:
        _stage("launching", profile=temp_dir)
        before = set(_windows())
        process = subprocess.Popen(
            [
                "cmd.exe",
                "/d",
                "/c",
                "call",
                str(code),
                "--new-window",
                "--disable-extensions",
                "--disable-updates",
                "--user-data-dir",
                temp_dir,
            ],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        hwnd = 0
        try:
            hwnd, initial_title = _wait_new_window(before, process)
            _stage("window_found", hwnd=hwnd, title=initial_title)
            # Chromium can ignore accelerated keys when its entire window is
            # outside the virtual desktop. Keep it visually absent by making
            # it fully transparent while it is briefly positioned on-screen.
            original_ex_style = int(user32.GetWindowLongW(hwnd, -20))
            user32.SetWindowLongW(hwnd, -20, original_ex_style | 0x00080000)
            user32.SetLayeredWindowAttributes(hwnd, 0, 0, 0x00000002)
            user32.SetWindowPos(hwnd, 0, 100, 100, 1000, 760, 0x0040)
            if not _force_foreground(hwnd):
                raise RuntimeError("Could not focus the invisible disposable VS Code window")
            time.sleep(1.5)
            _send_ctrl_n_native()
            deadline = time.monotonic() + 12.0
            title = _window_title(hwnd)
            while "untitled" not in title.casefold() and time.monotonic() < deadline:
                time.sleep(0.2)
                title = _window_title(hwnd)
            if "untitled" not in title.casefold():
                _force_foreground(hwnd)
                _send_ctrl_n_native()
                time.sleep(1.0)
                title = _window_title(hwnd)
            if "untitled" not in title.casefold():
                raise RuntimeError(f"Ctrl+N did not create an Untitled tab: {title!r}")
            user32.SetWindowPos(hwnd, 0, -20000, -20000, 1000, 760, 0x0010 | 0x0040)
            user32.SetLayeredWindowAttributes(hwnd, 0, 255, 0x00000002)
            user32.SetWindowLongW(hwnd, -20, original_ex_style)
            _stage("untitled_ready", title=title)
            token = native_host._win_uia_capture_focus()
            if not token:
                raise RuntimeError("Wisp did not capture the real collapsed Monaco caret")
            set_foreground_window(original_foreground)
            time.sleep(0.2)
            _stage("target_captured", token=token, collapsed=bool(native_host._focus_cache.get("collapsed")))

            native = Worker(
                {
                    "native.paste_text": lambda params: native_host.paste_text(**params),
                }
            )
            ui = Worker(
                {
                    "ui.action.preview.request": lambda _params: {"approved": True},
                }
            )

            def rewrite(_params, on_event):
                on_event("rewrite.first_activity", {}, 1)
                return {"text": marker, "visible_text": "Created the disposable smoke-test line."}

            brain = Worker(stream_handlers={"brain.rewrite": rewrite})
            flow = FlowController(native=native, ui=ui, brain=brain, audio=Worker(), run_async=False)
            flow.start(prewarm=False)
            pending = PendingInvocation(
                caller_idx=0,
                caller={"paste_back": True, "context_clipboard": False},
                context={
                    "platform": "win32",
                    "active_app": {
                        "name": title,
                        "process_name": "Code.exe",
                        "pid": process.pid,
                        "window_id": hwnd,
                    },
                    "selected_text": "",
                    "clipboard_text": "",
                    "focus_token": token,
                },
                paste_target_pid=process.pid,
            )
            pending.context_ready.set()
            flow._pending = pending
            flow.intent_chosen("Create one disposable Python print statement")
            _stage("flow_finished")

            document_text = _document_text()
            foreground_after_apply = int(get_foreground_window() or 0)
            final_clipboard = str(native_host.clipboard_get().get("text") or "")
            if not _force_foreground(hwnd):
                raise RuntimeError("Could not focus the disposable window for exact readback")
            send_keys("ctrl+a")
            time.sleep(0.1)
            send_keys("ctrl+c")
            time.sleep(0.25)
            copied_text = str(native_host.clipboard_get().get("text") or "")
            set_foreground_window(original_foreground)
            time.sleep(0.15)
            preview_calls = [item for item in ui.calls if item["method"] == "ui.action.preview.request"]
            paste_calls = [item for item in native.calls if item["method"] == "native.paste_text"]
            result.update(
                {
                    "hwnd": hwnd,
                    "initial_title": initial_title,
                    "untitled_title": title,
                    "focus_token": token,
                    "collapsed": bool(native_host._focus_cache.get("collapsed")),
                    "preview_called": bool(preview_calls),
                    "preview_has_marker": bool(preview_calls and marker in preview_calls[-1]["params"].get("html", "")),
                    "paste_called": bool(paste_calls),
                    "document_text": document_text,
                    "copied_text": copied_text,
                    "text_verified": marker in copied_text,
                    "foreground_after_apply": foreground_after_apply,
                    "focus_restored": foreground_after_apply == original_foreground,
                    "clipboard_restored": final_clipboard == original_clipboard,
                    "progress": [
                        item["params"].get("stage")
                        for item in ui.calls
                        if item["method"] == "ui.action.progress"
                    ],
                }
            )
            _stage(
                "verified",
                text_verified=result["text_verified"],
                focus_restored=result["focus_restored"],
                clipboard_restored=result["clipboard_restored"],
            )
        finally:
            set_foreground_window(original_foreground)
            native_host.clipboard_set(original_clipboard)
            # Never close a modified Untitled editor through the UI: that would
            # legitimately show a Save/Don't Save prompt. This profile is owned
            # by the smoke test, so terminate only processes whose command line
            # contains its unique temporary profile path.
            import psutil

            owned = []
            for candidate in psutil.process_iter(["pid", "cmdline"]):
                try:
                    command_line = " ".join(candidate.info.get("cmdline") or [])
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
                if temp_dir.casefold() in command_line.casefold():
                    owned.append(candidate)
            for candidate in sorted(owned, key=lambda item: item.pid, reverse=True):
                try:
                    candidate.terminate()
                except psutil.NoSuchProcess:
                    pass
            _gone, alive = psutil.wait_procs(owned, timeout=5.0)
            for candidate in alive:
                try:
                    candidate.kill()
                except psutil.NoSuchProcess:
                    pass
            if process.poll() is None:
                process.terminate()
            _stage("cleanup_finished", owned_processes=len(owned))

    print(json.dumps(result, indent=2, ensure_ascii=False))
    passed = all(
        (
            result.get("collapsed"),
            result.get("preview_called"),
            result.get("preview_has_marker"),
            result.get("paste_called"),
            result.get("text_verified"),
            result.get("focus_restored"),
            result.get("clipboard_restored"),
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
