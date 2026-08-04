"""Background LibreOffice Calc selection reader used by Wisp's native worker."""

from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import re
import sys
import time
from ctypes import wintypes
from typing import Any

import pyperclip

from core.system import clipboard_lock

_CALC_PROCESSES = {"soffice", "soffice.exe", "soffice.bin", "scalc", "scalc.exe"}
_CELL_RANGE = re.compile(r"^\$?[A-Z]{1,3}\$?\d+(?::\$?[A-Z]{1,3}\$?\d+)?$")
_COPY_NAMES = {
    "copy",
    "copiar",
    "copier",
    "copia",
    "kopieren",
    "kopiuj",
    "копировать",
    "複製",
    "复制",
    "コピー",
    "복사",
}


def is_calc_app(active_app: dict[str, Any] | None) -> bool:
    """Return whether a captured application identity belongs to Calc."""
    app = active_app if isinstance(active_app, dict) else {}
    process = str(app.get("process_name") or "").strip().casefold()
    title = " ".join(str(app.get("name") or app.get("title") or "").split()).casefold()
    calc_title = "calc" in title or "libreoffice 試算表" in title or "libreoffice 电子表格" in title
    return process in _CALC_PROCESSES and calc_title


class CalcSelectionReader:
    """Read the captured Calc window without activating or unminimizing it."""

    def __init__(self, *, timeout: float = 1.0) -> None:
        self.timeout = timeout

    def inspect_target(self, active_app: dict[str, Any]) -> dict[str, Any]:
        """Return the selected cell address without copying or changing Calc."""
        if not is_calc_app(active_app):
            return {}
        if sys.platform != "win32":
            raise RuntimeError("Background Calc selection capture is currently available on Windows only.")
        hwnd = int(active_app.get("window_id") or 0)
        if not hwnd or not ctypes.windll.user32.IsWindow(hwnd):
            raise RuntimeError("The Calc window captured by the hotkey is no longer available.")
        expected_pid = int(active_app.get("pid") or 0)
        actual_pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(actual_pid))
        if expected_pid and int(actual_pid.value or 0) != expected_pid:
            raise RuntimeError("The captured Calc window now belongs to a different process.")

        import comtypes.gen.UIAutomationClient as uiac  # type: ignore[import-not-found]

        from core.capture import _get_uia

        uia = _get_uia()
        if uia is None:
            raise RuntimeError("Windows UI Automation is unavailable.")
        root = uia.ElementFromHandle(hwnd)
        if root is None:
            raise RuntimeError("Windows could not inspect the captured Calc window.")

        address = self._selection_address(uia, root, uiac)
        return {
            "app": "libreoffice_calc",
            "document_title": str(active_app.get("name") or active_app.get("title") or ""),
            "window_id": hwnd,
            "pid": int(actual_pid.value or expected_pid or 0),
            "range": address,
            "capture_method": "windows_uia_name_box",
        }

    def inspect_selection(self, active_app: dict[str, Any]) -> dict[str, Any]:
        """Return the selected cell address and copied values through legacy UIA."""
        target = self.inspect_target(active_app)
        if not target:
            return {}

        import comtypes.gen.UIAutomationClient as uiac  # type: ignore[import-not-found]

        from core.capture import _clipboard_sequence_number, _get_uia, _safe_get_clipboard

        uia = _get_uia()
        if uia is None:
            raise RuntimeError("Windows UI Automation is unavailable.")
        root = uia.ElementFromHandle(int(target["window_id"]))
        if root is None:
            raise RuntimeError("Windows could not inspect the captured Calc window.")
        copy_button = self._copy_button(uia, root, uiac)
        copied = self._invoke_copy(
            copy_button,
            uiac,
            _safe_get_clipboard,
            _clipboard_sequence_number,
        )
        rows = tuple(tuple(cell for cell in row) for row in csv.reader(io.StringIO(copied), delimiter="\t"))
        if not rows:
            raise RuntimeError("Calc returned an empty selected range.")
        width = len(rows[0])
        if width < 1 or any(len(row) != width for row in rows):
            raise RuntimeError("Calc returned a non-rectangular selection.")
        payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
        return {
            **target,
            "rows": len(rows),
            "columns": width,
            "values": rows,
            "selected_text": copied,
            "fingerprint": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "capture_method": "windows_uia_name_box+background_copy",
        }

    @staticmethod
    def _selection_address(uia: Any, root: Any, uiac: Any) -> str:
        """Read Calc's name box, which exposes the selected range by window handle."""
        true_condition = uia.CreateTrueCondition()
        descendants = root.FindAll(uiac.TreeScope_Descendants, true_condition)
        for index in range(min(int(getattr(descendants, "Length", 0) or 0), 600)):
            element = descendants.GetElement(index)
            try:
                name = str(element.CurrentName or "").strip().upper()
                control_type = int(element.CurrentControlType or 0)
            except Exception:
                continue
            if control_type in {50003, 50004} and _CELL_RANGE.fullmatch(name):
                return name.replace("$", "")
        raise RuntimeError("Calc did not expose the selected cell address.")

    @staticmethod
    def _copy_button(uia: Any, root: Any, uiac: Any) -> Any:
        """Find Calc's semantic Copy button in supported UI languages."""
        condition = uia.CreatePropertyCondition(30003, 50000)  # Button
        buttons = root.FindAll(uiac.TreeScope_Descendants, condition)
        for index in range(int(getattr(buttons, "Length", 0) or 0)):
            element = buttons.GetElement(index)
            try:
                if str(element.CurrentName or "").strip().casefold() in _COPY_NAMES:
                    return element
            except Exception:
                continue
        raise RuntimeError("Calc's accessible Copy command was not found.")

    def _invoke_copy(
        self,
        copy_button: Any,
        uiac: Any,
        clipboard_getter: Any,
        sequence_getter: Any,
    ) -> str:
        """Invoke background Copy and restore the user's clipboard exactly."""
        with clipboard_lock.held():
            previous = clipboard_getter()
            before = sequence_getter()
            copied = ""
            try:
                raw = copy_button.GetCurrentPattern(10000)  # InvokePattern
                invoke = raw.QueryInterface(uiac.IUIAutomationInvokePattern)
                invoke.Invoke()
                deadline = time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    time.sleep(0.025)
                    after = sequence_getter()
                    if before is not None and after == before:
                        continue
                    copied = (clipboard_getter() or "").strip()
                    if copied:
                        break
            finally:
                _restore_clipboard(previous)
        if not copied:
            raise RuntimeError("Calc's background Copy command returned no text.")
        return copied


def _restore_clipboard(previous: str | None) -> None:
    """Restore clipboard text, including an originally empty clipboard."""
    if previous is not None:
        pyperclip.copy(previous)
        return
    try:
        import win32clipboard  # type: ignore[import-not-found]

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
        finally:
            win32clipboard.CloseClipboard()
    except Exception:
        pass
