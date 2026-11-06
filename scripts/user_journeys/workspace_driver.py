"""Operate the real Shared Workspace window and its actual file explorer."""

from __future__ import annotations


def act(host, action, params, *, click, type_text, button):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    window = host._virtual_workspace_window
    assert window is not None and window.isVisible(), "Shared Workspace is not visible"
    tree = window._desktop._icons
    if action in {"workspace_menu", "workspace_open", "workspace_key"}:
        item = tree.item_for_path(params["path"]) if params.get("path") else tree.topLevelItem(0)
        assert item is not None, "The user's workspace file is absent"
        tree.scrollToItem(item)
        point = tree.visualItemRect(item).center()
        QTest.mouseClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        if action == "workspace_menu":
            event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, point, tree.viewport().mapToGlobal(point))
            QApplication.sendEvent(tree.viewport(), event)
        elif action == "workspace_open":
            # Qt's Return-to-activate behavior differs on macOS. A normal
            # file double-click is the same user action on every platform.
            QTest.mouseDClick(tree.viewport(), Qt.MouseButton.LeftButton, pos=point)
        else:
            QTest.keyClick(tree, getattr(Qt.Key, "Key_" + params["key"]))
    elif action == "workspace_edit":
        type_text(window._desktop._document, params["text"])
    elif action == "workspace_save":
        click(window._desktop._save)
    elif action == "workspace_start_task":
        click(window._start)
    elif action == "workspace_close":
        window.close()
    else:
        raise ValueError(f"Unknown Shared Workspace input: {action}")


def observe(host):
    from shiboken6 import isValid

    window = getattr(host, "_virtual_workspace_window", None)
    if window is None or not isValid(window) or not window.isVisible():
        return {}
    desktop = window._desktop
    return {"workspace": {
        "scope": window._scope_folder,
        "tree_ready": desktop._icons.topLevelItemCount() > 0,
        "entries": list(desktop._icons._items_by_path),
        "selected": desktop._icons.current_path(),
        "document": desktop._document.toPlainText() if desktop._document.isVisible() else "",
        "editor_title": desktop._editor_title.text(),
        "editor_visible": desktop._document.isVisible(),
        "save_enabled": desktop._save.isEnabled(),
        "notice": window._notice.text(),
        "connection": window._connection.text(),
        "start_enabled": window._start.isEnabled(),
        "paused": bool(window._last_state.get("paused")),
    }}
