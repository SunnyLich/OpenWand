"""Capture one visible Windows application window by title fragment."""

from __future__ import annotations

import argparse
import ctypes
import time
from ctypes import wintypes
from pathlib import Path

import psutil
import win32gui
import win32ui
from PIL import Image


def _window_by_title(fragment: str, process_name: str = "") -> int:
    wanted = str(fragment or "").casefold()
    wanted_process = str(process_name or "").strip().casefold()
    matches: list[tuple[int, int]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = int(ctypes.windll.user32.GetWindowTextLengthW(hwnd) or 0)
        if not length:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        owner_pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        try:
            owner_name = str(psutil.Process(int(owner_pid.value)).name() or "").casefold()
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            owner_name = ""
        process_matches = not wanted_process or owner_name == wanted_process
        if process_matches and wanted in buffer.value.casefold():
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            matches.append((max(0, right - left) * max(0, bottom - top), int(hwnd)))
        return True

    ctypes.windll.user32.EnumWindows(callback_type(callback), 0)
    if not matches:
        raise RuntimeError(f"No visible window title contained {fragment!r}.")
    return max(matches)[1]


def capture(title: str, output: Path, process_name: str = "") -> Path:
    hwnd = _window_by_title(title, process_name)
    ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    ctypes.windll.user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
    ctypes.windll.user32.BringWindowToTop(hwnd)
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(1.0)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError("The target window has an invalid capture rectangle.")
    window_dc = win32gui.GetWindowDC(hwnd)
    source_dc = win32ui.CreateDCFromHandle(window_dc)
    target_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(source_dc, width, height)
    target_dc.SelectObject(bitmap)
    try:
        rendered = ctypes.windll.user32.PrintWindow(hwnd, target_dc.GetSafeHdc(), 2)
        if not rendered:
            raise RuntimeError("Windows PrintWindow could not render the target app.")
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
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        target_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--process", default="")
    args = parser.parse_args()
    print(capture(args.title, args.output, args.process))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
