"""Inspect LibreOffice Calc's background UIA patterns for integration work."""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    hwnd = _find_window(args.title)
    if not hwnd:
        raise RuntimeError("Calc window not found")

    import comtypes.gen.UIAutomationClient as uiac  # type: ignore

    from core.capture import _get_uia

    uia = _get_uia()
    root = uia.ElementFromHandle(hwnd)
    elements = root.FindAll(4, uia.CreateTrueCondition())  # TreeScope_Descendants
    rows = []
    for index in range(min(int(elements.Length), 4000)):
        element = elements.GetElement(index)
        try:
            legacy_shortcut = ""
            try:
                raw_legacy = element.GetCurrentPattern(10018)
                if raw_legacy is not None:
                    legacy = raw_legacy.QueryInterface(uiac.IUIAutomationLegacyIAccessiblePattern)
                    legacy_shortcut = str(legacy.CurrentKeyboardShortcut or "")
            except Exception:
                pass
            row = {
                "index": index,
                "name": str(element.CurrentName or ""),
                "type": int(element.CurrentControlType or 0),
                "class": str(element.CurrentClassName or ""),
                "automation_id": str(element.CurrentAutomationId or ""),
                "accelerator": str(element.CurrentAcceleratorKey or ""),
                "access_key": str(element.CurrentAccessKey or ""),
                "legacy_shortcut": legacy_shortcut,
                "enabled": bool(element.CurrentIsEnabled),
                "offscreen": bool(element.CurrentIsOffscreen),
                "selection": bool(element.GetCurrentPropertyValue(30038)),
                "selection_item": bool(element.GetCurrentPropertyValue(30037)),
                "grid": bool(element.GetCurrentPropertyValue(30031)),
                "grid_item": bool(element.GetCurrentPropertyValue(30030)),
                "table": bool(element.GetCurrentPropertyValue(30039)),
                "table_item": bool(element.GetCurrentPropertyValue(30040)),
                "legacy": bool(element.GetCurrentPropertyValue(30090)),
            }
        except Exception:
            continue
        if any((row["selection"], row["selection_item"], row["grid"], row["grid_item"], row["table"], row["table_item"])):
            rows.append(row)
        elif row["name"] and row["type"] in {50029, 50030, 50033, 50036}:
            rows.append(row)
    print(json.dumps({"hwnd": hwnd, "count": int(elements.Length), "interesting": rows}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
