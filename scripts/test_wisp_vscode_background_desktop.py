"""Real VS Code background-input smoke on an isolated Windows desktop."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def stage(name: str, **values) -> None:
    print(json.dumps({"stage": name, **values}, ensure_ascii=True), flush=True)


def windows() -> dict[int, str]:
    user32 = ctypes.windll.user32
    found: dict[int, str] = {}
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _lparam):
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length:
            value = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, value, len(value))
            found[int(hwnd)] = value.value
        return True

    user32.EnumWindows(callback, 0)
    return found


def child_window_classes(hwnd: int) -> list[dict[str, object]]:
    user32 = ctypes.windll.user32
    found: list[dict[str, object]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(child, _lparam):
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(child, class_name, len(class_name))
        found.append({"hwnd": int(child), "class": class_name.value})
        return True

    user32.EnumChildWindows(hwnd, callback, 0)
    return found


def post_background_editor_click(hwnd: int) -> dict[str, object]:
    """Post a cursor-free click near the editor center to one renderer HWND."""
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return {"ok": False, "error": "GetClientRect failed"}
    width = max(1, int(rect.right - rect.left))
    height = max(1, int(rect.bottom - rect.top))
    x = int(width * 0.45)
    y = int(height * 0.35)
    lparam = ((y & 0xFFFF) << 16) | (x & 0xFFFF)
    sent = all(
        (
            bool(user32.PostMessageW(hwnd, 0x0200, 0, lparam)),
            bool(user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam)),
            bool(user32.PostMessageW(hwnd, 0x0202, 0, lparam)),
        )
    )
    return {"ok": sent, "x": x, "y": y, "width": width, "height": height}


def wait_for_code_window(timeout: float = 45.0) -> tuple[int, str]:
    deadline = time.monotonic() + timeout
    seen: dict[int, str] = {}
    while time.monotonic() < deadline:
        seen = windows()
        for hwnd, title in seen.items():
            if "visual studio code" in title.casefold():
                return hwnd, title
        time.sleep(0.1)
    raise RuntimeError(f"isolated VS Code window did not appear: {seen!r}")


def terminate_profile_processes(profile: str) -> int:
    import psutil

    owned = []
    for candidate in psutil.process_iter(["pid", "cmdline"]):
        try:
            command_line = " ".join(candidate.info.get("cmdline") or [])
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if profile.casefold() in command_line.casefold():
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
    return len(owned)


def capture_monaco_from_window(hwnd: int) -> int:
    """Capture a TextPattern selection by exact window handle on a hidden desktop."""
    import comtypes.client
    from runtime.workers import native_host

    comtypes.client.GetModule("UIAutomationCore.dll")
    import comtypes.gen.UIAutomationClient as uiac  # type: ignore

    uia = comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}",
        interface=uiac.IUIAutomation,
    )
    root = uia.ElementFromHandle(hwnd)
    descendants = getattr(uiac, "TreeScope_Descendants", 4)
    control_type_property = getattr(uiac, "UIA_ControlTypePropertyId", 30003)
    document_type = getattr(uiac, "UIA_DocumentControlTypeId", 50030)
    documents = root.FindAll(
        descendants,
        uia.CreatePropertyCondition(control_type_property, document_type),
    )
    candidates = [documents.GetElement(index) for index in range(documents.Length)]
    if not candidates:
        all_elements = root.FindAll(descendants, uia.CreateTrueCondition())
        candidates = [all_elements.GetElement(index) for index in range(all_elements.Length)]

    user32 = ctypes.windll.user32
    thread_id = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)

    class GuiThreadInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("hwndActive", wintypes.HWND),
            ("hwndFocus", wintypes.HWND),
            ("hwndCapture", wintypes.HWND),
            ("hwndMenuOwner", wintypes.HWND),
            ("hwndMoveSize", wintypes.HWND),
            ("hwndCaret", wintypes.HWND),
            ("rcCaret", wintypes.RECT),
        ]

    info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
    user32.GetGUIThreadInfo(thread_id, ctypes.byref(info))
    input_hwnd = int(info.hwndFocus or info.hwndCaret or hwnd)
    for child in child_window_classes(hwnd):
        if str(child.get("class") or "") == "Chrome_RenderWidgetHostHWND":
            input_hwnd = int(child.get("hwnd") or input_hwnd)
            break
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(input_hwnd, ctypes.byref(pid))

    for element in candidates:
        try:
            raw = element.GetCurrentPattern(native_host._UIA_TEXT_PATTERN_ID)
            pattern = raw.QueryInterface(uiac.IUIAutomationTextPattern)
            selections = pattern.GetSelection()
            if selections.Length <= 0:
                continue
            text_range = selections.GetElement(0)
        except Exception:
            continue
        native_host._focus_seq += 1
        native_host._focus_cache.clear()
        native_host._focus_cache.update(
            {
                "token": native_host._focus_seq,
                "kind": "win-uia",
                "element": element,
                "range": text_range,
                "collapsed": True,
                "input_hwnd": input_hwnd,
                "root_hwnd": hwnd,
                "target_pid": int(pid.value),
            }
        )
        return native_host._focus_seq
    return 0


def inner() -> int:
    from runtime.workers import native_host

    executable = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe"
    if not executable.is_file():
        raise FileNotFoundError(executable)
    marker = f'print("Wisp background smoke {time.time_ns()}")'
    result = {"marker": marker, "isolated_desktop": True}
    with tempfile.TemporaryDirectory(prefix="wisp-vscode-background-") as profile:
        stage("isolated_launch", profile=profile)
        process = subprocess.Popen(
            [
                str(executable),
                "--new-window",
                "--disable-extensions",
                "--disable-updates",
                "--user-data-dir",
                profile,
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
            while "code-stdin" not in title.casefold() and time.monotonic() < deadline:
                time.sleep(0.2)
                title = windows().get(hwnd, title)
            stage("editor_ready", hwnd=hwnd, title=title)

            token = 0
            for _attempt in range(20):
                token = capture_monaco_from_window(hwnd)
                if token:
                    break
                time.sleep(0.25)
            if not token:
                raise RuntimeError("could not capture Monaco on the isolated desktop")
            cache = native_host._focus_cache
            children = child_window_classes(hwnd)
            stage(
                "target_captured",
                token=token,
                input_hwnd=int(cache.get("input_hwnd") or 0),
                root_hwnd=int(cache.get("root_hwnd") or 0),
                collapsed=bool(cache.get("collapsed")),
                child_windows=children,
            )
            foreground_before = int(ctypes.windll.user32.GetForegroundWindow() or 0)
            background_click = post_background_editor_click(int(cache.get("input_hwnd") or 0))
            time.sleep(0.15)
            applied = native_host._win_uia_apply_selected_text(token, marker)
            foreground_after = int(ctypes.windll.user32.GetForegroundWindow() or 0)
            time.sleep(0.75)

            element = cache.get("element")
            import comtypes.gen.UIAutomationClient as uiac  # type: ignore

            raw = element.GetCurrentPattern(native_host._UIA_TEXT_PATTERN_ID)
            pattern = raw.QueryInterface(uiac.IUIAutomationTextPattern)
            document_text = str(pattern.DocumentRange.GetText(-1) or "")
            result.update(
                {
                    "title": title,
                    "focus_token": token,
                    "collapsed": bool(cache.get("collapsed")),
                    "input_hwnd": int(cache.get("input_hwnd") or 0),
                    "background_click": background_click,
                    "apply": applied,
                    "document_text": document_text,
                    "text_verified": marker in document_text,
                    "hidden_desktop_foreground_unchanged": foreground_before == foreground_after,
                }
            )
            stage(
                "verified",
                apply_ok=bool(applied.get("ok")),
                text_verified=result["text_verified"],
                foreground_unchanged=result["hidden_desktop_foreground_unchanged"],
            )
        finally:
            result["owned_processes_cleaned"] = terminate_profile_processes(profile)
            if process.poll() is None:
                process.terminate()
            stage("cleanup_finished", owned_processes=result["owned_processes_cleaned"])
    print(json.dumps(result, ensure_ascii=True, indent=2), flush=True)
    return 0 if all(
        (
            result.get("text_verified"),
            result.get("hidden_desktop_foreground_unchanged"),
            (result.get("apply") or {}).get("ok"),
            (result.get("apply") or {}).get("activated") is False,
        )
    ) else 1


def parent(child_script: Path | None = None, inner_argument: str = "--inner") -> int:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    desktop_name = f"WispBackgroundTest-{uuid.uuid4().hex}"
    desktop_access = 0x000F01FF
    user32.CreateDesktopW.restype = wintypes.HANDLE
    desktop = user32.CreateDesktopW(desktop_name, None, None, 0, desktop_access, None)
    if not desktop:
        raise ctypes.WinError()

    class StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class ProcessInformation(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    startup = StartupInfo(cb=ctypes.sizeof(StartupInfo), lpDesktop=desktop_name)
    startup.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
    startup.hStdInput = kernel32.GetStdHandle(-10)
    startup.hStdOutput = kernel32.GetStdHandle(-11)
    startup.hStdError = kernel32.GetStdHandle(-12)
    info = ProcessInformation()
    child_script = Path(child_script or __file__).resolve()
    command = ctypes.create_unicode_buffer(
        subprocess.list2cmdline([sys.executable, str(child_script), inner_argument])
    )
    stage("desktop_created", desktop=desktop_name)
    created = kernel32.CreateProcessW(
        None,
        command,
        None,
        None,
        True,
        0x00000400,  # CREATE_UNICODE_ENVIRONMENT
        None,
        str(ROOT),
        ctypes.byref(startup),
        ctypes.byref(info),
    )
    if not created:
        user32.CloseDesktop(desktop)
        raise ctypes.WinError()
    try:
        wait_result = kernel32.WaitForSingleObject(info.hProcess, 90000)
        if wait_result != 0:
            kernel32.TerminateProcess(info.hProcess, 2)
            raise TimeoutError("isolated desktop smoke timed out")
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(exit_code))
        return int(exit_code.value)
    finally:
        kernel32.CloseHandle(info.hThread)
        kernel32.CloseHandle(info.hProcess)
        user32.CloseDesktop(desktop)
        stage("desktop_closed", desktop=desktop_name)


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Windows only")
    raise SystemExit(inner() if "--inner" in sys.argv else parent())
