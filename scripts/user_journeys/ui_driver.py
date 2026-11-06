"""User input and read-only observations inside the real UI worker.

This opt-in driver locates the production widgets and delivers Qt mouse/key
events. It must never call send, save, model, storage, or error handlers itself.
Business logic continues through the application's normal signals and workers.
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def dispatch(host, action: str, **params):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QKeySequence, QPalette
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QLabel,
        QLineEdit,
        QPushButton,
        QRadioButton,
        QScrollArea,
        QTextEdit,
    )

    from scripts.user_journeys.dialog_driver import watch_unexpected_dialogs
    from ui.settings_panel import dialog as settings_module

    watch_unexpected_dialogs(host)

    def click(widget):
        assert widget is not None, "User control was not found"
        parent = widget.parentWidget()
        while parent:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(widget)
            parent = parent.parentWidget()
        assert widget.isVisible(), f"User control is hidden: {widget.objectName()}"
        assert widget.isEnabled(), f"User control is disabled: {widget.objectName()}"
        if isinstance(widget, (QCheckBox, QRadioButton)):
            # A wide layout can extend beyond a checkbox's clickable label.
            # Click the actual indicator, then let its normal signal run.
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton, pos=QPoint(8, widget.height() // 2))
        else:
            QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    def type_text(widget, value):
        click(widget)
        QTest.keySequence(widget, QKeySequence(QKeySequence.StandardKey.SelectAll))
        QTest.keyClick(widget, Qt.Key.Key_Backspace)
        for index, line in enumerate(value.split("\n")):
            if index:
                # Enter may submit a chat. Shift+Enter inserts the intended
                # line break while the user is still composing this value.
                QTest.keyClick(widget, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
            # QTest's ASCII key helper cannot represent an IME's committed
            # Unicode text. Deliver that input event as a user's IME would.
            if line.isascii():
                QTest.keyClicks(widget, line)
            else:
                from PySide6.QtGui import QInputMethodEvent
                event = QInputMethodEvent()
                event.setCommitString(line)
                QApplication.sendEvent(widget, event)

    def select(combo, value):
        index = combo.findData(value)
        if index < 0:
            index = combo.findText(value)
        assert index >= 0, f"User option {value!r} is absent"
        # Keyboard navigation changes the real combo without activating a
        # dialog's default Next button as an extra Return key could do.
        parent = combo.parentWidget()
        while parent:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(combo)
            parent = parent.parentWidget()
        QTest.qWait(10)  # Let newly added route rows receive their show/layout events.
        assert combo.isVisible() and combo.isEnabled(), f"Provider/model selector is unavailable (visible={combo.isVisible()}, enabled={combo.isEnabled()})"
        item = combo.model().index(index, combo.modelColumn())
        assert item.flags() & Qt.ItemFlag.ItemIsEnabled, f"User option {value!r} is disabled"
        combo.setFocus()
        for _ in range(combo.count() + 1):
            if combo.currentIndex() == index:
                break
            key = Qt.Key.Key_Down if combo.currentIndex() < index else Qt.Key.Key_Up
            QTest.keyClick(combo, key)
        assert combo.currentIndex() == index, f"Could not select {value!r}"

    def button(parent, text):
        matches = [w for w in parent.findChildren(QPushButton) if w.isVisible() and w.window() is parent.window() and w.text().replace("&", "") == text]
        assert len(matches) == 1, f"Expected one visible {text!r} button, found {len(matches)}"
        return matches[0]

    settings = getattr(settings_module, "_settings_dialog", None)
    chat = getattr(host, "_chat", None)
    wizard = getattr(host, "_onboarding", None)
    if action == "wizard_field":
        widget = getattr(wizard, "_" + params["field"])
        if isinstance(widget, QComboBox):
            if widget.isEditable() and params.get("typed"):
                type_text(widget.lineEdit(), params["value"])
            else:
                select(widget, params["value"])
        elif isinstance(widget, QLineEdit):
            type_text(widget, params["value"])
        else:
            click(widget)
            assert widget.isChecked() == bool(params["value"]), "Wizard choice did not change"
    elif action == "wizard_button":
        click(getattr(wizard, "_" + params["button"]))
    elif action == "tray":
        # Trigger the actual tray QAction; its normal handler opens the window.
        overlay = host._overlay
        choices = [item for item in overlay._tray_menu.actions() if item.text().replace("&", "") == params["label"]]
        assert len(choices) == 1, f"Tray item {params['label']!r} is absent"
        QTimer.singleShot(0, choices[0].trigger)
    elif action == "settings_page":
        nav = settings._settings_nav

        def normalize(value):
            return " ".join(value.replace("&", "").split())
        matches = [i for i in range(nav.count()) if normalize(nav.item(i).text()) == normalize(params["page"])]
        assert len(matches) == 1, f"Settings page {params['page']!r} is absent"
        QTest.mouseClick(nav.viewport(), Qt.MouseButton.LeftButton, pos=nav.visualItemRect(nav.item(matches[0])).center())
    elif action == "settings_button":
        click(button(settings, params["text"]))
    elif action == "settings_search":
        type_text(settings.findChild(QLineEdit, "settingsSearch"), params["text"])
    elif action == "connection":
        row = settings._api_key_rows[int(params.get("index", -1))]
        field = params["field"]
        if isinstance(row[field], QComboBox):
            select(row[field], params["value"])
        else:
            type_text(row[field], params["value"])
    elif action == "route":
        section = params.get("section", "LLM")
        click(settings._model_route_buttons[section])
        row = settings._model_section_rows[section][int(params.get("index", 0))]
        if params["field"] == "provider":
            select(row["api_key_combo"], params["value"])
        else:
            select(row["model_combo"], settings_module._CUSTOM_MODEL_SENTINEL)
            type_text(row["model_edit"], params["value"])
    elif action == "settings_field":
        widget = settings._fields[params["field"]]
        if isinstance(widget, QComboBox):
            select(widget, params["value"])
        elif isinstance(widget, (QLineEdit, QTextEdit)):
            type_text(widget, params["value"])
        else:
            if widget.isChecked() != bool(params["value"]):
                click(widget)
            assert widget.isChecked() == bool(params["value"]), "Settings checkbox did not change"
    elif action == "chat_type":
        type_text(chat._input, params["text"])
    elif action == "chat_send":
        click(chat._send_btn)
    elif action == "bubble_stop":
        bubble = host._bubble
        assert bubble.isVisible() and bubble._close_cancels, "No user-cancellable reply bubble is visible"
        QTest.mouseClick(bubble, Qt.MouseButton.LeftButton, pos=bubble._close_rect().center())
    elif action == "chat_key":
        key = getattr(Qt.Key, "Key_" + params["key"])
        modifier = Qt.KeyboardModifier.ControlModifier if params.get("control") else Qt.KeyboardModifier.ShiftModifier if params.get("shift") else Qt.KeyboardModifier.NoModifier
        QTest.keyClick(chat._input, key, modifier)
    elif action == "chat_new":
        chat.activateWindow()
        click(chat._input)
        QTest.qWait(10)
        QTest.keySequence(chat, QKeySequence(QKeySequence.StandardKey.New))
    elif action == "chat_close":
        chat.close()
    elif action == "chat_search":
        type_text(chat._history_search, params["text"])
    elif action == "chat_history":
        matches = [button for index, button in chat._sidebar_btns if index == params["index"]]
        assert len(matches) == 1, "Conversation history row is absent"
        click(matches[0])
    elif action == "memory_add":
        from ui.memory_viewer import MemoryPanel
        panels = [w for w in QApplication.allWidgets() if isinstance(w, MemoryPanel) and w.isVisible()]
        assert len(panels) == 1
        type_text(panels[0]._add_text, params["text"])
        click(button(panels[0], "Add"))
    elif action == "memory_refresh":
        from ui.memory_viewer import MemoryPanel
        panels = [w for w in QApplication.allWidgets() if isinstance(w, MemoryPanel) and w.isVisible()]
        assert len(panels) == 1
        click(panels[0]._refresh_btn)
    elif action == "chat_menu":
        click(chat._composer_menu_btn)
        menu = QApplication.activePopupWidget()
        matches = [item for item in menu.actions() if item.text().replace("&", "") == params["text"]]
        assert len(matches) == 1, "Chat menu action is absent"
        matches[0].trigger()
        menu.close()
    elif action == "chat_context":
        if not chat._context_policy_panel.isVisible():
            click(chat._composer_menu_btn)
            menu = QApplication.activePopupWidget()
            matches = [item for item in menu.actions() if item.text() == "Context controls"]
            assert len(matches) == 1
            matches[0].trigger()
            menu.close()
        click(chat._context_controls[params["source"]])
        menu = QApplication.activePopupWidget()
        matches = [item for item in menu.actions() if item.data() == params["value"]]
        assert len(matches) == 1, "Context choice is absent"
        matches[0].trigger()
        menu.close()
    elif action == "chat_drop":
        from PySide6.QtCore import QMimeData, QPoint, QPointF, QUrl
        from PySide6.QtGui import QDragEnterEvent, QDropEvent
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(path) for path in params.get("paths", [params.get("path", "")])])
        enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(chat, enter)
        assert enter.isAccepted(), "Chat refused the user's file drag"
        drop = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(chat, drop)
        assert drop.isAccepted(), "Chat refused the user's file drop"
    elif action == "close_auxiliary":
        for widget in QApplication.topLevelWidgets():
            if widget.isVisible() and widget is not host._overlay and widget is not getattr(host, "_bubble", None):
                widget.close()
    elif action == "snapshot":
        pass
    elif action.startswith("extended."):
        from scripts.user_journeys.ui_extensions import act
        act(host, action, params, click=click, type_text=type_text, select=select, button=button)
    else:
        raise ValueError(f"Unknown user input action: {action}")

    # Observations are read-only. They never complete a request or write stores.
    windows = [w for w in QApplication.topLevelWidgets() if w.isVisible()]
    snapshot = {"windows": [type(w).__name__ for w in windows], "titles": [w.windowTitle() for w in windows]}
    snapshot["window_buttons"] = {w.windowTitle(): [b.text() for b in w.findChildren(QPushButton) if b.isVisible()] for w in windows if w.windowTitle()}
    snapshot["theme_background"] = QApplication.palette().color(QPalette.ColorRole.Window).name()
    from scripts.user_journeys.ui_extensions import observe
    snapshot["extended"] = observe(host)
    if wizard is not None and wizard.isVisible():
        snapshot["wizard"] = {"page": wizard._pages.currentIndex(), "next_enabled": wizard._next.isEnabled(), "next_text": wizard._next.text()}
    if settings is not None and settings.isVisible():
        snapshot["settings"] = {
            "page": settings._settings_nav.item(settings._tabs.currentIndex()).text(),
            "pages": [settings._settings_nav.item(index).text() for index in range(settings._settings_nav.count())],
            "save_enabled": settings._apply_btn.isEnabled(),
            "connections": [{"provider": r["provider"].currentData(), "alias": r["alias"].text(), "id": r.get("connection_id", ""), "visible": r["widget"].isVisible()} for r in settings._api_key_rows],
            "routes": {key: [{"provider": r["api_key_combo"].currentData(), "model": settings._model_value(r)} for r in rows] for key, rows in settings._model_section_rows.items()},
            "status": settings._status_lbl.text(),
        }
    if chat is not None and chat.isVisible():
        from ui.chat_window import _MessageTextView
        snapshot["chat"] = {
            "streaming": chat._streaming,
            "send_enabled": chat._send_btn.isEnabled(),
            "input": chat._input.toPlainText(),
            "messages": [w.toPlainText() for w in chat.findChildren(_MessageTextView) if w.isVisible()],
            "pending_attachments": len(getattr(chat, "_pending_attachments", [])),
            "history_visible": [button.text() for _, button in chat._sidebar_btns if button.isVisible()],
            "history_indices": [index for index, button in chat._sidebar_btns if button.isVisible()],
            "labels": [label.text() for label in chat.findChildren(QLabel) if label.isVisible()],
        }
    from ui.memory_viewer import MemoryPanel, _FactRow
    panels = [w for w in QApplication.allWidgets() if isinstance(w, MemoryPanel) and w.isVisible()]
    if panels:
        snapshot["memory"] = {"loading": panels[0]._loading, "facts": [row._text_edit.text() for row in panels[0].findChildren(_FactRow)]}
    snapshot["observed_monotonic_ns"] = time.monotonic_ns()
    # Screenshots are captured from actual windows, including failure states.
    if params.get("capture"):
        evidence_root = Path(os.environ["OPENWAND_E2E_OUTPUT"]).resolve() / "screenshots"
        evidence_root.mkdir(parents=True, exist_ok=True)
        snapshot["screenshots"] = []
        for index, widget in enumerate(windows):
            pixmap = widget.grab()
            if pixmap.isNull():
                continue  # Native tooltip/menu windows can have no Qt backing image.
            name = f"{params['capture']}-{index}.png"
            assert pixmap.save(str(evidence_root / name)), "Screenshot capture failed"
            snapshot["screenshots"].append("screenshots/" + name)
        assert snapshot["screenshots"], "No application window could be captured"
    return snapshot
