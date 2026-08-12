"""Manual real-desktop check of OpenWand's current Calc selection capture path."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

def _find_window(title_contains: str) -> int:
    user32 = ctypes.windll.user32
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        if length < 1:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        if title_contains.casefold() in buffer.value.casefold():
            matches.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else 0


def main() -> int:
    from core.capture import _get_selected_text_uia, get_selected_text
    from core.platform_utils import get_foreground_window, get_window_pid, get_window_title

    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--minimize-only", action="store_true")
    args = parser.parse_args()

    hwnd = _find_window(args.title)
    if not hwnd:
        raise RuntimeError(f"No visible Calc window contains {args.title!r}.")
    user32 = ctypes.windll.user32
    if args.minimize_only:
        user32.ShowWindow(hwnd, 6)
        print(json.dumps({"target_hwnd": hwnd, "minimized": bool(user32.IsIconic(hwnd))}))
        return 0
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    foreground = int(get_foreground_window() or 0)
    uia = _get_selected_text_uia()
    captured = get_selected_text()
    print(
        json.dumps(
            {
                "target_hwnd": hwnd,
                "foreground_hwnd": foreground,
                "foreground_title": get_window_title(foreground),
                "foreground_pid": get_window_pid(foreground),
                "target_focused": foreground == hwnd,
                "uia": uia,
                "openwand_capture": captured,
                "chars": len(captured or ""),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
