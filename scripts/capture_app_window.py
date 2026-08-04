"""Capture one visible Windows application window to PNG for manual smoke evidence."""

from __future__ import annotations

import argparse
import ctypes
import sys
from ctypes import wintypes
from pathlib import Path


def _visible_windows() -> list[tuple[int, str]]:
    user32 = ctypes.windll.user32
    windows: list[tuple[int, str]] = []
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
        windows.append((int(hwnd), buffer.value))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows only")

    windows = _visible_windows()
    hwnd = next((hwnd for hwnd, title in windows if args.title.casefold() in title.casefold()), 0)
    if not hwnd:
        visible = ", ".join(repr(title) for _hwnd, title in windows[:30])
        raise RuntimeError(f"No visible window contains {args.title!r}. Visible titles: {visible}")
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)

    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Could not read application window bounds.")

    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    center = QPoint(int((rect.left + rect.right) / 2), int((rect.top + rect.bottom) / 2))
    screen = QApplication.screenAt(center) or QApplication.primaryScreen()
    if screen is None:
        raise RuntimeError("No screen is available for capture.")
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def capture() -> None:
        image = screen.grabWindow(
            hwnd,
            0,
            0,
            int(rect.right - rect.left),
            int(rect.bottom - rect.top),
        )
        if image.isNull() or not image.save(str(args.output)):
            raise RuntimeError("Window capture failed.")
        app.quit()

    QTimer.singleShot(500, capture)
    app.exec()
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
