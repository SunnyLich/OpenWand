"""Keep every top-level window for one test process outside all monitor bounds."""

from __future__ import annotations

import argparse
import ctypes
import time
from ctypes import wintypes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--no-activate", action="store_true")
    args = parser.parse_args()
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def guard_window(hwnd: int) -> None:
        if not hwnd:
            return
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value or 0) != args.pid:
            return
        if args.no_activate:
            style = int(user32.GetWindowLongW(hwnd, -20))
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000)  # WS_EX_NOACTIVATE
        # SWP_NOACTIVATE | SWP_NOOWNERZORDER
        user32.SetWindowPos(hwnd, 0, -30000, -30000, 900, 700, 0x0210)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        guard_window(hwnd)
        return True

    event_callback_type = ctypes.WINFUNCTYPE(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD,
    )

    @event_callback_type
    def on_window_event(_hook, _event, hwnd, _object_id, _child_id, _thread_id, _event_time) -> None:
        guard_window(hwnd)

    hooks = []
    if args.no_activate:
        for event in (0x8000, 0x8002):  # EVENT_OBJECT_CREATE, EVENT_OBJECT_SHOW
            hook = user32.SetWinEventHook(event, event, 0, on_window_event, args.pid, 0, 0)
            if hook:
                hooks.append(hook)

    deadline = time.monotonic() + max(1.0, args.duration)
    message = wintypes.MSG()
    try:
        while time.monotonic() < deadline:
            user32.EnumWindows(callback, 0)
            while user32.PeekMessageW(ctypes.byref(message), 0, 0, 0, 1):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
            time.sleep(0.001)
    finally:
        for hook in hooks:
            user32.UnhookWinEvent(hook)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
