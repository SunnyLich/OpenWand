"""Exercise OpenWand's WordPad adapter against a real Windows RichEdit control."""

from __future__ import annotations

import ctypes
import json
import sys
from ctypes import wintypes
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.workers import native_host  # noqa: E402


def main() -> int:
    if sys.platform != "win32":
        print(json.dumps({"verified": False, "skipped": "Windows only"}, indent=2))
        return 2
    ctypes.WinDLL("Msftedit.dll")
    user32 = ctypes.windll.user32
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
    parent = user32.CreateWindowExW(
        0,
        "STATIC",
        "OpenWand hidden WordPad contract",
        0,
        0,
        0,
        640,
        480,
        None,
        None,
        None,
        None,
    )
    child = user32.CreateWindowExW(
        0,
        "RICHEDIT50W",
        "",
        0x40000000 | 0x0004 | 0x0040,  # WS_CHILD | ES_MULTILINE | ES_AUTOVSCROLL
        0,
        0,
        620,
        460,
        parent,
        None,
        None,
        None,
    )
    if not parent or not child:
        if parent:
            user32.DestroyWindow(parent)
        raise RuntimeError("Windows could not create the hidden RichEdit test control")
    old_cache = dict(native_host._focus_cache)
    try:
        user32.SendMessageW(child, 0x000C, 0, ctypes.c_wchar_p("A rough sentence."))  # WM_SETTEXT
        user32.SendMessageW(child, native_host._EM_SETSEL, 2, 7)
        before = native_host._win_edit_control_snapshot(int(child))
        if not before:
            raise RuntimeError("OpenWand could not bind the real RICHEDIT50W selection")
        native_host._focus_cache.clear()
        native_host._focus_cache.update(before)
        native_host._focus_cache.update({"token": 991, "kind": "win-edit"})
        result = native_host._win_edit_apply_selected_text(991, "two words")
        after = native_host._win_edit_control_snapshot(int(child), require_selection=False)
        selection_rect = before.get("selection_rect")
        verified = bool(
            result.get("ok")
            and after.get("document_text") == "A two words sentence."
            and isinstance(selection_rect, dict)
            and float(selection_rect.get("height") or 0) > 0
        )
        print(
            json.dumps(
                {
                    "verified": verified,
                    "control_class": before.get("class_name"),
                    "before": before.get("document_text"),
                    "selected": before.get("selected_text"),
                    "selection_rect": selection_rect,
                    "after": after.get("document_text"),
                    "method": result.get("method"),
                    "clipboard_restored": result.get("clipboard_restored"),
                    "foreground_unchanged": result.get("foreground_unchanged"),
                    "text_verified": result.get("text_verified"),
                    "error": result.get("error"),
                },
                indent=2,
            )
        )
        return 0 if verified else 1
    finally:
        native_host._focus_cache.clear()
        native_host._focus_cache.update(old_cache)
        user32.DestroyWindow(parent)


if __name__ == "__main__":
    raise SystemExit(main())
