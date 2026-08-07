"""Exercise the running Wisp Rewrite flow through its real Windows hotkey.

This is intentionally a live smoke test: it creates a disposable RichEdit
document, highlights text, presses the configured Rewrite shortcut, and waits
for the running Wisp UI worker to create a new Comment popup.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil
import win32gui
import win32ui
from PIL import Image, ImageGrab

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.workers import native_host  # noqa: E402

WM_CLOSE = 0x0010
WM_SETTEXT = 0x000C
EM_SETSEL = 0x00B1
EM_GETSEL = 0x00B0
EM_LINESCROLL = 0x00B6
SW_SHOW = 5
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_OVERLAPPEDWINDOW = 0x00CF0000
ES_MULTILINE = 0x0004
ES_AUTOVSCROLL = 0x0040
VK_CONTROL = 0x11
VK_RETURN = 0x0D
VK_SHIFT = 0x10
KEYEVENTF_KEYUP = 0x0002
PM_REMOVE = 0x0001


def _visible_windows_with_title(user32, title: str) -> set[int]:
    matches: set[int] = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if buffer.value.strip().casefold() == title.strip().casefold():
            matches.add(int(hwnd))
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return matches


def _ui_worker_pids() -> set[int]:
    pids: set[int] = set()
    for process in psutil.process_iter(["pid", "cmdline"]):
        command = " ".join(process.info.get("cmdline") or [])
        if "runtime.workers.ui_host" in command:
            pids.add(int(process.info["pid"]))
    return pids


def _visible_windows_for_pids(user32, pids: set[int]) -> set[int]:
    matches: set[int] = set()
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) in pids:
            matches.add(int(hwnd))
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return matches


def _window_class_name(user32, hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    if not user32.GetClassNameW(hwnd, buffer, len(buffer)):
        return ""
    return buffer.value


def _capture_window(hwnd: int, output: Path) -> str:
    """Render one test or popup window without changing its size or focus."""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError("The live smoke window has an invalid rectangle")
    window_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    target_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    target_dc.SelectObject(bitmap)
    try:
        if not ctypes.windll.user32.PrintWindow(hwnd, target_dc.GetSafeHdc(), 2):
            raise RuntimeError("Windows PrintWindow could not render the live smoke window")
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (info["bmWidth"], info["bmHeight"]),
            bits,
            "raw",
            "BGRX",
            0,
            1,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        image.save(output, "PNG")
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        target_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    return str(output.resolve())


def _capture_windows_region(handles: tuple[int, ...], output: Path) -> str:
    rects = [win32gui.GetWindowRect(hwnd) for hwnd in handles if win32gui.IsWindow(hwnd)]
    if not rects:
        raise RuntimeError("No live windows were available for the evidence image")
    padding = 20
    left = min(rect[0] for rect in rects) - padding
    top = min(rect[1] for rect in rects) - padding
    right = max(rect[2] for rect in rects) + padding
    bottom = max(rect[3] for rect in rects) + padding
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(output, "PNG")
    return str(output.resolve())


def _press_ctrl_digit(user32, digit: int) -> None:
    vk = ord(str(digit))
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def _type_ascii(user32, value: str) -> None:
    for character in value:
        scan = int(user32.VkKeyScanW(ord(character)))
        if scan == -1:
            raise RuntimeError(f"Windows could not map test character {character!r}")
        virtual_key = scan & 0xFF
        needs_shift = bool((scan >> 8) & 1)
        if needs_shift:
            user32.keybd_event(VK_SHIFT, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, 0, 0)
        user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)
        if needs_shift:
            user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.008)


def _press_enter(user32) -> None:
    user32.keybd_event(VK_RETURN, 0, 0, 0)
    user32.keybd_event(VK_RETURN, 0, KEYEVENTF_KEYUP, 0)


def _selection_offsets(user32, hwnd: int) -> tuple[int, int]:
    start = wintypes.DWORD()
    end = wintypes.DWORD()
    user32.SendMessageW(hwnd, EM_GETSEL, ctypes.byref(start), ctypes.byref(end))
    return int(start.value), int(end.value)


def _pump_for(user32, seconds: float) -> None:
    """Keep the disposable window responsive to Wisp's cross-process reads."""
    message = wintypes.MSG()
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        time.sleep(0.005)


def _force_foreground(user32, hwnd: int, focused_child: int) -> bool:
    """Give the disposable test window the foreground using thread attachment."""
    foreground = int(user32.GetForegroundWindow() or 0)
    current_tid = int(ctypes.windll.kernel32.GetCurrentThreadId() or 0)
    foreground_tid = int(user32.GetWindowThreadProcessId(foreground, None) or 0) if foreground else 0
    attached = False
    try:
        if foreground_tid and foreground_tid != current_tid:
            attached = bool(user32.AttachThreadInput(current_tid, foreground_tid, True))
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(focused_child)
    finally:
        if attached:
            user32.AttachThreadInput(current_tid, foreground_tid, False)
    return int(user32.GetForegroundWindow() or 0) == int(hwnd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--digit", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--keep-popup", action="store_true")
    parser.add_argument("--scroll-test", action="store_true")
    parser.add_argument("--balloon-test", action="store_true")
    parser.add_argument("--screenshot-dir", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        print(json.dumps({"verified": False, "skipped": "Windows only"}, indent=2))
        return 2

    # Qt's UI worker is per-monitor-DPI-aware. Match it before creating the
    # source window or asking GetWindowRect/PrintWindow for physical pixels;
    # otherwise Windows virtualizes the popup rectangle and the evidence image
    # crops its right and bottom edges even when the real popup is intact.
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    ctypes.WinDLL("Msftedit.dll")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.CreateWindowExW.argtypes = (
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    )
    previous_foreground = int(user32.GetForegroundWindow() or 0)
    existing_popups = _visible_windows_with_title(user32, "Comment")
    ui_worker_pids = _ui_worker_pids()
    existing_ui_windows = _visible_windows_for_pids(user32, ui_worker_pids)
    parent = user32.CreateWindowExW(
        0,
        "STATIC",
        "Wisp live Rewrite smoke document",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        140,
        140,
        760,
        420,
        None,
        None,
        None,
        None,
    )
    control_class = "EDIT" if args.scroll_test else "RICHEDIT50W"
    child = user32.CreateWindowExW(
        0,
        control_class,
        "",
        WS_CHILD | WS_VISIBLE | ES_MULTILINE | ES_AUTOVSCROLL,
        18,
        18,
        706,
        330,
        parent,
        None,
        None,
        None,
    )
    if not parent or not child:
        if parent:
            user32.DestroyWindow(parent)
        raise RuntimeError("Windows could not create the live RichEdit smoke window")

    popup = 0
    before_screenshot = ""
    popup_screenshot = ""
    combined_screenshot = ""
    balloon_screenshot = ""
    started = time.monotonic()
    try:
        if args.scroll_test:
            lines = [f"Line {index:02d}: ordinary scrolling test content." for index in range(30)]
            lines[7] = "Line 07: a rough sentence selected for the live Wisp Rewrite test."
            source_text = "\r\n".join(lines)
        else:
            source_text = "A rough sentence selected for the live Wisp Rewrite test."
        selected_text = "rough sentence"
        selection_start = source_text.index(selected_text)
        selection_end = selection_start + len(selected_text)
        user32.SendMessageW(child, WM_SETTEXT, 0, ctypes.c_wchar_p(source_text))
        foreground_ready = _force_foreground(user32, int(parent), int(child))
        if not foreground_ready:
            raise RuntimeError(
                "Windows refused to foreground the disposable Rewrite smoke document"
            )
        # Set the selection after activation because some RichEdit versions
        # collapse a programmatic range when they receive their first focus.
        user32.SendMessageW(child, EM_SETSEL, selection_start, selection_end)
        _pump_for(user32, 0.35)
        selection_before_hotkey = _selection_offsets(user32, int(child))
        if args.screenshot_dir:
            before_screenshot = _capture_window(
                int(parent), args.screenshot_dir / "rewrite-before.png"
            )
        # The desktop shell or another foreground app can reclaim focus while
        # evidence is rendered. Reassert the disposable editor immediately
        # before the global hotkey and restore the exact selected range.
        foreground_ready = _force_foreground(user32, int(parent), int(child))
        user32.SendMessageW(child, EM_SETSEL, selection_start, selection_end)
        _pump_for(user32, 0.08)
        if not foreground_ready or int(user32.GetForegroundWindow() or 0) != int(parent):
            raise RuntimeError("The disposable Rewrite document lost focus before Ctrl+2")
        _press_ctrl_digit(user32, args.digit)
        selection_after_hotkey = _selection_offsets(user32, int(child))
        deadline = time.monotonic() + max(1.0, args.timeout)
        while time.monotonic() < deadline:
            _pump_for(user32, 0.02)
            titled_candidates = _visible_windows_with_title(user32, "Comment") - existing_popups
            current_ui_windows = _visible_windows_for_pids(user32, ui_worker_pids)
            class_candidates = {
                hwnd
                for hwnd in current_ui_windows - existing_ui_windows
                if "rewriteannotationpopup" in _window_class_name(user32, hwnd).casefold()
            }
            geometry_candidates = set()
            for hwnd in current_ui_windows - existing_ui_windows:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width = int(right - left)
                height = int(bottom - top)
                if 300 <= width <= 520 and 150 <= height <= 420:
                    geometry_candidates.add(hwnd)
            candidates = titled_candidates | class_candidates | geometry_candidates
            if candidates:
                popup = next(iter(candidates))
                if args.screenshot_dir:
                    _pump_for(user32, 0.1)
                    popup_screenshot = _capture_window(
                        popup, args.screenshot_dir / "rewrite-comment-popup.png"
                    )
                    combined_screenshot = _capture_windows_region(
                        (int(parent), popup),
                        args.screenshot_dir / "rewrite-popup-near-selection.png",
                    )
                break
            _pump_for(user32, 0.08)
        balloon_detected = False
        if popup and args.balloon_test:
            user32.ShowWindow(popup, SW_SHOW)
            user32.BringWindowToTop(popup)
            user32.SetForegroundWindow(popup)
            _pump_for(user32, 0.12)
            if int(user32.GetForegroundWindow() or 0) != popup:
                raise RuntimeError("Windows refused to foreground the live Comment popup")
            _type_ascii(user32, "make concise")
            _press_enter(user32)
            balloon_deadline = time.monotonic() + 3.0
            while time.monotonic() < balloon_deadline:
                _pump_for(user32, 0.04)
                left, top, right, bottom = win32gui.GetWindowRect(popup)
                if right - left <= 100 and bottom - top <= 100:
                    balloon_detected = True
                    if args.screenshot_dir:
                        balloon_screenshot = _capture_windows_region(
                            (int(parent), popup),
                            args.screenshot_dir / "rewrite-balloon-near-selection.png",
                        )
                    break
                _pump_for(user32, 0.04)
        elapsed_ms = round((time.monotonic() - started) * 1000, 1)
        scroll_result: dict[str, object] = {}
        if popup and args.scroll_test:
            document_units = len(source_text.encode("utf-16-le")) // 2
            native_anchor_initial = native_host._win_edit_selection_screen_rect(
                int(child),
                class_name=control_class,
                selection_end=selection_end,
                document_units=document_units,
            )
            initial_rect = tuple(int(value) for value in win32gui.GetWindowRect(popup))
            user32.SendMessageW(child, EM_LINESCROLL, 0, 4)
            native_anchor_moved = native_host._win_edit_selection_screen_rect(
                int(child),
                class_name=control_class,
                selection_end=selection_end,
                document_units=document_units,
            )
            moved_rect = initial_rect
            move_deadline = time.monotonic() + 4.0
            while time.monotonic() < move_deadline:
                _pump_for(user32, 0.05)
                moved_rect = tuple(int(value) for value in win32gui.GetWindowRect(popup))
                if moved_rect[1] <= initial_rect[1] - 30:
                    break
            moved_screenshot = ""
            if args.screenshot_dir and user32.IsWindowVisible(popup):
                moved_screenshot = _capture_window(
                    popup,
                    args.screenshot_dir / "rewrite-popup-after-scroll.png",
                )
                _capture_windows_region(
                    (int(parent), popup),
                    args.screenshot_dir / "rewrite-popup-near-selection-after-scroll.png",
                )

            user32.SendMessageW(child, EM_LINESCROLL, 0, 14)
            native_anchor_offscreen = native_host._win_edit_selection_screen_rect(
                int(child),
                class_name=control_class,
                selection_end=selection_end,
                document_units=document_units,
            )
            hidden_deadline = time.monotonic() + 4.0
            while time.monotonic() < hidden_deadline and user32.IsWindowVisible(popup):
                _pump_for(user32, 0.05)
            hidden_offscreen = not bool(user32.IsWindowVisible(popup))

            user32.SendMessageW(child, EM_LINESCROLL, 0, -18)
            return_deadline = time.monotonic() + 4.0
            while time.monotonic() < return_deadline and not user32.IsWindowVisible(popup):
                _pump_for(user32, 0.05)
            returned_visible = bool(user32.IsWindowVisible(popup))
            returned_rect = (
                tuple(int(value) for value in win32gui.GetWindowRect(popup))
                if returned_visible
                else ()
            )
            moved_delta_y = moved_rect[1] - initial_rect[1]
            returned_delta_y = returned_rect[1] - initial_rect[1] if returned_rect else None
            scroll_result = {
                "initial_popup_rect": initial_rect,
                "native_anchor_initial": native_anchor_initial,
                "native_anchor_moved": native_anchor_moved,
                "native_anchor_offscreen": native_anchor_offscreen,
                "moved_popup_rect": moved_rect,
                "moved_delta_y": moved_delta_y,
                "hidden_when_selection_offscreen": hidden_offscreen,
                "returned_visible": returned_visible,
                "returned_popup_rect": returned_rect,
                "returned_delta_y": returned_delta_y,
                "moved_screenshot": moved_screenshot,
                "verified": bool(
                    moved_delta_y <= -30
                    and hidden_offscreen
                    and returned_visible
                    and returned_delta_y is not None
                    and abs(returned_delta_y) <= 8
                    and (not args.balloon_test or balloon_detected)
                ),
            }
        result = {
            "verified": bool(popup and (not args.scroll_test or scroll_result.get("verified"))),
            "hotkey": f"ctrl+{args.digit}",
            "source_window": int(parent),
            "foreground_verified": foreground_ready,
            "selected_text": selected_text,
            "selection_before_hotkey": selection_before_hotkey,
            "selection_after_hotkey": selection_after_hotkey,
            "popup_window": int(popup),
            "elapsed_ms": elapsed_ms,
            "before_screenshot": before_screenshot,
            "popup_screenshot": popup_screenshot,
            "combined_screenshot": combined_screenshot,
            "balloon_detected": balloon_detected,
            "balloon_screenshot": balloon_screenshot,
            "reason": "Comment popup appeared" if popup else "No new Comment popup appeared",
            "scroll": scroll_result,
        }
        print(json.dumps(result, indent=2))
        return 0 if result["verified"] else 1
    finally:
        if popup and not args.keep_popup:
            user32.PostMessageW(popup, WM_CLOSE, 0, 0)
        user32.DestroyWindow(parent)
        if previous_foreground and user32.IsWindow(previous_foreground):
            user32.SetForegroundWindow(previous_foreground)


if __name__ == "__main__":
    raise SystemExit(main())
