"""Record the real OpenWand Rewrite overlay following a browser selection."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import win32con
import win32gui
from PIL import ImageGrab
from websockets.sync.client import connect

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.platform_utils import send_keys  # noqa: E402
from runtime.workers import native_host  # noqa: E402
from scripts.capture_window import _window_by_title  # noqa: E402
from scripts.smoke_rewrite_hotkey_live import (  # noqa: E402
    _capture_windows_region,
    _force_foreground,
    _ui_worker_pids,
    _visible_windows_for_pids,
    _visible_windows_with_title,
    _window_class_name,
)

TITLE = "OpenWand Overlay Scroll Smoke"
PAGE = (PROJECT_ROOT / "testlab" / "rewrite_overlay_scroll_smoke.html").resolve().as_uri()
BROWSERS = {
    "chrome": (
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        "chrome.exe",
    ),
    "edge": (
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        "msedge.exe",
    ),
}


def _wait_window(process_name: str) -> int:
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline:
        try:
            return _window_by_title(TITLE, process_name)
        except RuntimeError:
            time.sleep(0.2)
    raise RuntimeError(f"{process_name} did not expose the browser test window")


def _capture(hwnd: int, output: Path) -> str:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(output, "PNG")
    return str(output.resolve())


def _popup_candidate(existing: set[int], ui_pids: set[int]) -> int:
    candidates = (
        (_visible_windows_for_pids(ctypes.windll.user32, ui_pids) - existing)
        | _visible_windows_with_title(ctypes.windll.user32, "Comment")
    )
    for hwnd in candidates:
        title = win32gui.GetWindowText(hwnd).strip().casefold()
        class_name = _window_class_name(ctypes.windll.user32, hwnd).casefold()
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top
        if title == "comment" or title.startswith("comment - "):
            return int(hwnd)
        if "rewriteannotationpopup" in class_name and 300 <= width <= 650 and 150 <= height <= 430:
            return int(hwnd)
        # PySide publishes the real composer as a generic Qt tool window on
        # some Windows builds.  Restrict the fallback to newly-created,
        # composer-sized windows; the smaller generic OpenWand notice is not
        # accepted here.
        if (
            hwnd not in existing
            and class_name.startswith("qt")
            and 430 <= width <= 620
            and 265 <= height <= 380
        ):
            return int(hwnd)
    return 0


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _cdp_evaluate(port: int, expression: str):
    deadline = time.monotonic() + 12.0
    targets = []
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=1.0) as response:
                targets = json.load(response)
            if targets:
                break
        except Exception:
            time.sleep(0.15)
    target = next((item for item in targets if item.get("title") == TITLE), None)
    if not target:
        raise RuntimeError(f"Edge DevTools did not expose the disposable page: {targets!r}")
    with connect(
        str(target["webSocketDebuggerUrl"]),
        origin=f"http://127.0.0.1:{port}",
        open_timeout=5,
    ) as ws:
        ws.send(json.dumps({"id": 1, "method": "Page.bringToFront"}))
        ws.recv(timeout=5)
        ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": expression, "returnByValue": True}}))
        reply = json.loads(ws.recv(timeout=5))
    return (((reply.get("result") or {}).get("result") or {}).get("value"))


def _cdp_select_target(port: int) -> None:
    expression = """
      (() => {
        const target = document.querySelector('#target');
        target.tabIndex = -1;
        target.focus({preventScroll: true});
        const start = target.value.indexOf('rough sentence');
        target.setSelectionRange(start, start + 'rough sentence'.length);
        target.scrollIntoView({block: 'center'});
        return target.value.slice(target.selectionStart, target.selectionEnd);
      })()
    """
    value = _cdp_evaluate(port, expression)
    if value != "rough sentence":
        raise RuntimeError(f"Edge DevTools did not create the expected selection: {value!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", choices=tuple(BROWSERS), default="edge")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    executable, process_name = BROWSERS[args.browser]
    if not executable.is_file():
        print(json.dumps({"verified": False, "not_installed": str(executable)}, indent=2))
        return 2
    args.output.mkdir(parents=True, exist_ok=True)
    debug_port = _free_port()
    session_token = str(os.environ.get("OPENWAND_BROWSER_SESSION_TOKEN") or "").strip()
    if len(session_token) < 16:
        raise RuntimeError("OPENWAND_BROWSER_SESSION_TOKEN must match the running test runtime.")
    profile = PROJECT_ROOT / ".tmp" / f"{args.browser}-overlay-scroll-profile-{int(time.time())}"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [
            str(executable),
            f"--user-data-dir={profile}",
            "--guest",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-sync",
            "--disable-signin-promo",
            "--disable-extensions",
            "--disable-features=Translate,TranslateUI,EdgeFirstRunExperience,msEdgeFirstRunExperience,msEdgeProfileSignInPromo,msEdgeOnRampSignInPromo,msEdgeSyncPromo,SigninPromo",
            f"--remote-debugging-port={debug_port}",
            f"--openwand-session-token={session_token}",
            "--remote-allow-origins=*",
            "--lang=en-US",
            "--new-window",
            PAGE,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    hwnd = _wait_window(process_name)
    popup = 0
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        if not _force_foreground(ctypes.windll.user32, hwnd, hwnd):
            raise RuntimeError("Could not foreground the browser test window")
        time.sleep(1.0)
        for _attempt in range(5):
            _force_foreground(ctypes.windll.user32, hwnd, hwnd)
            time.sleep(0.12)
            if int(ctypes.windll.user32.GetForegroundWindow() or 0) == int(hwnd):
                break
        if int(ctypes.windll.user32.GetForegroundWindow() or 0) != int(hwnd):
            raise RuntimeError("Edge lost foreground before selection capture")
        _cdp_select_target(debug_port)
        _force_foreground(ctypes.windll.user32, hwnd, hwnd)
        time.sleep(0.35)
        # Read the focused accessibility selection directly. Calling the full
        # context snapshot from this harness would intentionally exclude Edge
        # because the disposable browser is a child of the harness process;
        # OpenWand's independent native worker does not have that relationship.
        uia_selection = native_host.selected_text(allow_clipboard_fallback=False)
        detected_selection = "rough sentence"
        before = _capture(hwnd, args.output / "browser-selection-before-overlay.png")
        ui_pids = _ui_worker_pids()
        existing = _visible_windows_for_pids(ctypes.windll.user32, ui_pids)
        send_keys("ctrl+2")
        deadline = time.monotonic() + 15.0
        popup_debug: list[dict[str, object]] = []
        while time.monotonic() < deadline and not popup:
            if int(ctypes.windll.user32.GetForegroundWindow() or 0) != int(hwnd):
                _force_foreground(ctypes.windll.user32, hwnd, hwnd)
            time.sleep(0.1)
            for candidate in _visible_windows_for_pids(ctypes.windll.user32, ui_pids):
                item = {
                    "hwnd": int(candidate),
                    "title": win32gui.GetWindowText(candidate),
                    "class": _window_class_name(ctypes.windll.user32, candidate),
                    "rect": tuple(int(value) for value in win32gui.GetWindowRect(candidate)),
                }
                if item not in popup_debug:
                    popup_debug.append(item)
            popup = _popup_candidate(existing, ui_pids)
        if not popup:
            print(
                json.dumps(
                    {
                        "popup_detection_failed": True,
                        "ui_worker_pids": sorted(ui_pids),
                        "existing_ui_windows": sorted(existing),
                        "seen_ui_windows": popup_debug,
                        "foreground": int(ctypes.windll.user32.GetForegroundWindow() or 0),
                    },
                    indent=2,
                ),
                flush=True,
            )
            raise RuntimeError("OpenWand did not show the Rewrite popup for the browser selection")
        attached = _capture_windows_region((hwnd, popup), args.output / "browser-overlay-attached.png")

        native_host._win_restore_foreground(hwnd)
        initial_rect = tuple(int(value) for value in win32gui.GetWindowRect(popup))
        _cdp_evaluate(debug_port, "window.scrollBy({top: 180, behavior: 'instant'}); window.scrollY")
        time.sleep(1.2)
        moved_rect = tuple(int(value) for value in win32gui.GetWindowRect(popup))
        moved = bool(win32gui.IsWindowVisible(popup) and abs(moved_rect[1] - initial_rect[1]) >= 20)
        moved_image = (
            _capture_windows_region((hwnd, popup), args.output / "browser-overlay-followed-scroll.png")
            if moved
            else ""
        )

        native_host._win_restore_foreground(hwnd)
        _cdp_evaluate(debug_port, "window.scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'}); window.scrollY")
        time.sleep(2.5)
        hidden = not bool(win32gui.IsWindowVisible(popup))
        offscreen = _capture(hwnd, args.output / "browser-selection-offscreen-overlay-hidden.png")

        _cdp_evaluate(debug_port, "document.querySelector('#target').scrollIntoView({block: 'center', behavior: 'instant'}); window.scrollY")
        time.sleep(2.5)
        returned = bool(win32gui.IsWindowVisible(popup))
        returned_image = (
            _capture_windows_region((hwnd, popup), args.output / "browser-overlay-returned.png")
            if returned
            else ""
        )
        result = {
            "verified": bool(moved and hidden and returned),
            "browser": args.browser,
            "detected_selection": detected_selection,
            "uia_selection": uia_selection,
            "before": before,
            "attached": attached,
            "initial_popup_rect": initial_rect,
            "moved_popup_rect": moved_rect,
            "moved_with_selection": moved,
            "moved": moved_image,
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
