"""Live exact Rewrite smoke test for ordinary Chrome, Edge, and Firefox windows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

import win32api
import win32con
import win32gui
from PIL import ImageGrab

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.platform_utils import send_keys  # noqa: E402
from runtime.workers import native_host  # noqa: E402
from scripts.capture_window import _window_by_title  # noqa: E402

PAGE = (PROJECT_ROOT / "testlab" / "rewrite_browser_smoke.html").resolve().as_uri()
TITLE = "OpenWand Ordinary Browser Rewrite Smoke"

BROWSERS = {
    "chrome": {
        "executable": Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        "process": "chrome.exe",
        "arguments": lambda profile: [
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--disable-extensions",
            "--new-window",
            PAGE,
        ],
    },
    "edge": {
        "executable": Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        "process": "msedge.exe",
        "arguments": lambda profile: [
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--disable-extensions",
            "--new-window",
            PAGE,
        ],
    },
    "firefox": {
        "executable": Path(r"C:\Program Files\Mozilla Firefox\firefox.exe"),
        "process": "firefox.exe",
        "arguments": lambda profile: ["-profile", str(profile), "-new-window", PAGE],
    },
}


def _wait_window(process_name: str) -> int:
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline:
        try:
            return _window_by_title(TITLE, process_name)
        except RuntimeError:
            time.sleep(0.25)
    raise RuntimeError(f"{process_name} did not expose the ordinary test window.")


def _capture(hwnd: int, output: Path) -> None:
    if not native_host._win_restore_foreground(hwnd):
        raise RuntimeError("Could not focus the browser for evidence capture.")
    time.sleep(0.4)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    output.parent.mkdir(parents=True, exist_ok=True)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(output, "PNG")


def _select_fixture_text(hwnd: int) -> None:
    """Make the same selection a user would make before pressing Rewrite."""
    left, top, _right, _bottom = win32gui.GetWindowRect(hwnd)
    win32api.SetCursorPos((left + 220, top + 300))
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.15)
    send_keys("home")
    send_keys("right")
    send_keys("right")
    for _index in range(5):
        send_keys("shift+right")
    time.sleep(0.2)


def _readback() -> str:
    import comtypes.gen.UIAutomationClient as uiac  # type: ignore

    element = native_host._focus_cache["element"]
    raw_pattern = element.GetCurrentPattern(native_host._UIA_TEXT_PATTERN_ID)
    pattern = raw_pattern.QueryInterface(uiac.IUIAutomationTextPattern)
    return str(pattern.DocumentRange.GetText(-1) or "")


def _smoke(name: str, config: dict, output: Path) -> dict:
    executable = Path(config["executable"])
    if not executable.exists():
        return {"verified": False, "not_installed": True, "path": str(executable)}
    profile = PROJECT_ROOT / ".tmp" / f"{name}-ordinary-rewrite-profile"
    profile.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(
        [str(executable), *config["arguments"](profile)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    hwnd = _wait_window(str(config["process"]))
    popup: tk.Tk | None = None
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        if not native_host._win_restore_foreground(hwnd):
            raise RuntimeError("Could not focus the ordinary browser test window.")
        time.sleep(1.0)
        _select_fixture_text(hwnd)
        debug_selection = output / f"{name}_ordinary_selection_debug.png"
        _capture(hwnd, debug_selection)
        snapshot = native_host.context_snapshot(
            include_clipboard=False,
            include_selection=True,
            capture_focus=True,
        )
        copied_selection = str(snapshot.get("selected_text") or "")
        token = int(snapshot.get("focus_token") or 0)
        selected = str(native_host._focus_cache.get("selected_text") or "")
        if not token or selected != "rough":
            raise RuntimeError(
                "UI Automation did not bind the page selection "
                f"(selected={selected!r}, clipboard={copied_selection!r}, screenshot={debug_selection})."
            )
        before = output / f"{name}_ordinary_before.png"
        after = output / f"{name}_ordinary_after.png"
        _capture(hwnd, before)

        popup = tk.Tk()
        popup.title("OpenWand Rewrite Popup Focus Test")
        popup.geometry("360x120+80+80")
        tk.Label(popup, text="Rewrite proposal ready", padx=30, pady=30).pack()
        popup.attributes("-topmost", True)
        popup.update()
        popup.focus_force()
        popup.update()
        result = native_host._win_uia_apply_selected_text(token, "clear", restore_clipboard=True)
        readback = _readback()
        popup.destroy()
        popup = None
        _capture(hwnd, after)
        return {
            "verified": bool(result.get("ok") and readback == "A clear sentence."),
            "method": str(result.get("method") or ""),
            "readback": readback,
            "clipboard_restored": bool(result.get("clipboard_restored")),
            "focus_restored": bool(result.get("focus_restored")),
            "before": str(before),
            "after": str(after),
            "error": str(result.get("error") or ""),
        }
    finally:
        if popup is not None:
            popup.destroy()
        if win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "rewrite_exact_evidence",
    )
    parser.add_argument("--browser", action="append", choices=tuple(BROWSERS), default=[])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    names = args.browser or list(BROWSERS)
    results: dict[str, dict] = {}
    for name in names:
        try:
            results[name] = _smoke(name, BROWSERS[name], args.output)
        except Exception as exc:  # noqa: BLE001 - report each installed browser independently
            results[name] = {"verified": False, "error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(results, indent=2))
    installed = [item for item in results.values() if not item.get("not_installed")]
    return 0 if installed and all(item.get("verified") for item in installed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
