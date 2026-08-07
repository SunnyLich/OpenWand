"""Prove Calc selection copy through background UIA InvokePattern."""

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

_COPY_NAMES = {"copy", "複製", "复制", "copier", "copiar"}


def _find_window(title_contains: str) -> int:
    user32 = ctypes.windll.user32
    matches: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        length = int(user32.GetWindowTextLengthW(hwnd) or 0)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        if title_contains.casefold() in buffer.value.casefold():
            matches.append(int(hwnd))
            return False
        return True

    user32.EnumWindows(callback, 0)
    return matches[0] if matches else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    import comtypes.gen.UIAutomationClient as uiac  # type: ignore
    import pyperclip

    from core.capture import _clipboard_sequence_number, _get_uia, _safe_get_clipboard
    from core.system import clipboard_lock

    hwnd = _find_window(args.title)
    uia = _get_uia()
    root = uia.ElementFromHandle(hwnd)
    buttons = root.FindAll(4, uia.CreatePropertyCondition(30003, 50000))
    copy_button = None
    for index in range(int(buttons.Length)):
        element = buttons.GetElement(index)
        if str(element.CurrentName or "").strip().casefold() in _COPY_NAMES:
            copy_button = element
            break
    if copy_button is None:
        raise RuntimeError("Copy button not found")

    with clipboard_lock.held():
        previous = _safe_get_clipboard()
        before = _clipboard_sequence_number()
        raw = copy_button.GetCurrentPattern(10000)
        invoke = raw.QueryInterface(uiac.IUIAutomationInvokePattern)
        invoke.Invoke()
        deadline = time.monotonic() + 1.0
        copied = ""
        while time.monotonic() < deadline:
            time.sleep(0.04)
            after = _clipboard_sequence_number()
            if before is None or after != before:
                copied = (_safe_get_clipboard() or "").strip()
                if copied:
                    break
        if previous is not None:
            pyperclip.copy(previous)
    print(json.dumps({"hwnd": hwnd, "copied": copied, "chars": len(copied)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
