"""Record the real OpenWand Rewrite overlay following a LibreOffice Writer selection."""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

import psutil
import win32con
import win32gui
from PIL import ImageGrab

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.platform_utils import send_keys  # noqa: E402
from runtime.workers import native_host  # noqa: E402
from scripts.smoke_rewrite_hotkey_live import (  # noqa: E402
    _capture_windows_region,
    _type_ascii,
    _ui_worker_pids,
    _visible_windows_for_pids,
    _window_class_name,
)

SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
FIXTURE = PROJECT_ROOT / "testlab" / "rewrite_overlay_scroll_smoke.txt"


def _wait_writer_window() -> int:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        matches: list[int] = []

        def visit(hwnd: int, _extra: object, matches: list[int] = matches) -> None:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd).casefold()
            if "rewrite_overlay_scroll_smoke" not in title:
                return
            pid_value = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
            pid = int(pid_value.value or 0)
            try:
                name = psutil.Process(pid).name().casefold()
            except Exception:
                return
            if "soffice" in name:
                matches.append(int(hwnd))

        win32gui.EnumWindows(visit, None)
        if len(matches) == 1:
            return matches[0]
        time.sleep(0.2)
    raise RuntimeError("LibreOffice Writer did not expose the fixture window")


def _popup_candidate(existing: set[int], ui_pids: set[int]) -> int:
    for hwnd in _visible_windows_for_pids(ctypes.windll.user32, ui_pids) - existing:
        title = win32gui.GetWindowText(hwnd).strip().casefold()
        class_name = _window_class_name(ctypes.windll.user32, hwnd).casefold()
        if title == "comment" or "rewriteannotationpopup" in class_name:
            return int(hwnd)
    return 0


def _capture(hwnd: int, output: Path) -> str:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(output, "PNG")
    return str(output.resolve())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if not SOFFICE.is_file():
        print(json.dumps({"verified": False, "not_installed": str(SOFFICE)}, indent=2))
        return 2
    profile = PROJECT_ROOT / ".tmp" / f"writer-overlay-profile-{int(time.time())}"
    subprocess.Popen(
        [
            str(SOFFICE),
            "--writer",
            "--norestore",
            "--nolockcheck",
            f"-env:UserInstallation={profile.resolve().as_uri()}",
            str(FIXTURE.resolve()),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    hwnd = _wait_writer_window()
    popup = 0
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        if not native_host._win_restore_foreground(hwnd):
            raise RuntimeError("Could not foreground Writer")
        time.sleep(1.0)
        send_keys("ctrl+f")
        _type_ascii(ctypes.windll.user32, "rough sentence")
        send_keys("enter")
        send_keys("escape")
        time.sleep(0.5)
        before = _capture(hwnd, args.output / "writer-selection-before-overlay.png")
        ui_pids = _ui_worker_pids()
        existing = _visible_windows_for_pids(ctypes.windll.user32, ui_pids)
        send_keys("ctrl+2")
        deadline = time.monotonic() + 18.0
        while time.monotonic() < deadline and not popup:
            time.sleep(0.1)
            popup = _popup_candidate(existing, ui_pids)
        if not popup:
            raise RuntimeError("OpenWand did not show the Rewrite popup for Writer")
        attached = _capture_windows_region((hwnd, popup), args.output / "writer-overlay-attached.png")

        native_host._win_restore_foreground(hwnd)
        send_keys("pagedown")
        send_keys("pagedown")
        time.sleep(2.5)
        hidden = not bool(win32gui.IsWindowVisible(popup))
        offscreen = _capture(hwnd, args.output / "writer-selection-offscreen-overlay-hidden.png")

        send_keys("home")
        time.sleep(2.5)
        returned = bool(win32gui.IsWindowVisible(popup))
        returned_image = (
            _capture_windows_region((hwnd, popup), args.output / "writer-overlay-returned.png")
            if returned
            else ""
        )
        result = {
            "verified": bool(hidden and returned),
            "before": before,
            "attached": attached,
            "hidden_when_selection_offscreen": hidden,
            "offscreen": offscreen,
            "returned_visible": returned,
            "returned": returned_image,
        }
        print(json.dumps(result, indent=2))
        return 0 if result["verified"] else 1
    finally:
        if popup and win32gui.IsWindow(popup):
            win32gui.PostMessage(popup, win32con.WM_CLOSE, 0, 0)
        if win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


if __name__ == "__main__":
    raise SystemExit(main())
