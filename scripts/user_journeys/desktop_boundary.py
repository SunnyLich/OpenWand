"""Synthetic external desktop input; never inspect the developer's desktop.

The real native worker and IPC still run. Hosted Qt input exercises OpenWand's
widgets, while personal windows, clipboard, captures and paste are excluded.
Native desktop integration requires its separately documented acceptance run.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def document_context():
    """Provide open-document text without inspecting the user's open apps."""
    state = Path(os.environ["OPENWAND_E2E_STATE"]).resolve()
    if not (state / ".user-journey-state").is_file():
        raise RuntimeError("Document fixtures require marked disposable state")
    text = "E2E_DOCUMENT_CONTEXT: a synthetic acceptance document."
    return text, {"paths": [], "path_chars": 0, "window_labels": ["OpenWand acceptance document"],
                  "window_chars": len(text), "window_candidates": [], "external_boundary": "synthetic desktop input"}


def handlers(existing=()):
    """Expose only deterministic OS context in a marked acceptance process."""
    state = Path(os.environ["OPENWAND_E2E_STATE"]).resolve()
    if not (state / ".user-journey-state").is_file():
        raise RuntimeError("Desktop fixtures require marked disposable state")

    def snapshot(include_clipboard=True, include_selection=True, include_active_window_text=False,
                 include_browser_content=False, include_browser_url=False, **_params):
        url = "https://example.invalid/openwand-acceptance" if include_browser_url or include_browser_content else ""
        return {
            "platform": sys.platform,
            "active_app": {"name": "OpenWand acceptance document", "process_name": "openwand-e2e", "pid": 0, "window_id": 0},
            "document_window": {}, "selected_text": "E2E_SELECTED_TEXT" if include_selection else "",
            "stale_selected_text": "", "selected_paths": [],
            "clipboard_text": "E2E_CLIPBOARD_TEXT" if include_clipboard else "",
            "active_window_text": "E2E_WINDOW_TEXT" if include_active_window_text else "",
            "browser_url": url, "browser_hwnd": 0, "browser_app": "",
            "browser_content": "E2E_BROWSER_PAGE" if include_browser_content else "", "browser_pages": [],
            "screen_size": {"width": 1280, "height": 720}, "focus_token": 0, "captured_at": time.time(),
            "debug": {"external_boundary": "synthetic desktop input"},
        }

    def unavailable(**_params):
        raise RuntimeError("Physical desktop actions require isolated native acceptance; hosted journeys must not access a personal desktop")

    return {
        "native.context.snapshot": snapshot, "native.context.await_selection": snapshot,
        "native.context.app_selection": lambda **_params: {"supported": False, "selection": {}},
        "native.context.browser_content": lambda **_params: {"url": "https://example.invalid/openwand-acceptance", "content": "E2E_BROWSER_PAGE", "hwnd": 0},
        "native.clipboard.get": lambda **_params: {"text": "E2E_CLIPBOARD_TEXT"},
        **{name: unavailable for name in ("native.capture.fullscreen", "native.capture.region", "native.clipboard.set", "native.paste_text", "native.undo_edit")},
        **{name: unavailable for name in existing if name.startswith(("native.action.", "native.selection."))},
    }
