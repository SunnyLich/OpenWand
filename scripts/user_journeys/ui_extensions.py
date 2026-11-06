"""Additional input actions and observations for connected product journeys."""

from __future__ import annotations


def act(host, action, params, *, click, type_text, select, button):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton

    from ui.memory_viewer import MemoryPanel, _FactRow
    from ui.settings_panel import dialog as settings_module

    settings = getattr(settings_module, "_settings_dialog", None)
    chat = getattr(host, "_chat", None)
    action = action.removeprefix("extended.")
    if action == "recover_ui":
        # Cancel transient UI through real input before the next independent
        # story. Never accept an unknown confirmation or call a send handler.
        for _ in range(3):
            transient = QApplication.activePopupWidget() or QApplication.activeModalWidget()
            if transient is None:
                break
            QTest.keyClick(transient, Qt.Key.Key_Escape)
            QTest.qWait(30)
        if settings is not None and settings.isVisible():
            click(button(settings, "Cancel"))
        for child in [*getattr(host, "_addon_settings_dialogs", {}).values(), *getattr(host, "_addon_log_dialogs", {}).values()]:
            if child.isVisible():
                click(button(child, "Close"))
        addon_manager = getattr(host, "_addons_dialog", None)
        if addon_manager is not None and addon_manager.isVisible():
            click(button(addon_manager, "Close"))
        bubble = getattr(host, "_bubble", None)
        if bubble is not None and bubble.isVisible() and bubble._close_cancels:
            QTest.mouseClick(bubble, Qt.MouseButton.LeftButton, pos=bubble._close_rect().center())
        timer = getattr(host, "_journey_dialog_timer", None)
        if timer is not None:
            timer.stop()
        host._journey_dialog_plans = []
        host._journey_dialog_errors = []
        host._journey_dialog_events = []
    elif action.startswith("workspace_"):
        from scripts.user_journeys.workspace_driver import act as workspace_act
        workspace_act(host, action, params, click=click, type_text=type_text, button=button)
    elif action.startswith("agent_"):
        from scripts.user_journeys.agent_driver import act as agent_act
        agent_act(host, action, params, click=click, type_text=type_text, select=select, button=button)
    elif action == "dialogs":
        from scripts.user_journeys.dialog_driver import queue_dialogs
        queue_dialogs(host, params["plans"], click=click, type_text=type_text, select=select)
    elif action == "settings_profile_menu":
        click(settings._profiles_btn)
    elif action == "chatgpt_sign_in":
        click(settings._cgpt_login_btn)
    elif action == "floating_icon":
        click(host._overlay._icon_label)
    elif action == "intent_new":
        intent = host._intent
        intent.activateWindow()
        QTest.qWait(20)
        if intent.conversation_choice().get("mode") != "new":
            assert not intent._conversation_mode_rect.isEmpty(), "New/continue selector is not visible"
            QTest.mouseClick(intent, Qt.MouseButton.LeftButton, pos=intent._conversation_mode_rect.center())
    elif action == "intent_choice":
        intent = host._intent
        indices = [i for i, row in enumerate(intent._rows) if row["is_custom"]] if params.get("custom") else [i for i, row in enumerate(intent._rows) if row["label"] == params["label"]]
        assert len(indices) == 1, "Expected one matching visible intent action"
        row_index = indices[0]
        assert intent._rows[row_index].get("available", True), "Intent action is unavailable"
        if params.get("keyboard"):
            intent.activateWindow()
            QTest.keyClick(intent, getattr(Qt.Key, "Key_" + intent._rows[row_index]["glyph"]))
        else:
            # Paint creates the row's hit area. Refuse an empty or clipped
            # target instead of accidentally clicking a different control.
            rect = intent._row_rects[row_index]
            assert not rect.isEmpty() and intent.rect().contains(rect), "Intent row has no visible click target"
            QTest.mouseClick(intent, Qt.MouseButton.LeftButton, pos=rect.center())
    elif action == "intent_type":
        type_text(host._intent._input_line, params["text"])
    elif action == "intent_enter":
        QTest.keyClick(host._intent._input_line, Qt.Key.Key_Return)
    elif action == "intent_escape":
        QTest.keyClick(host._intent, Qt.Key.Key_Escape)
    elif action == "bubble_open_chat":
        click(host._bubble._text_view)
    elif action == "connection_search":
        type_text(settings._connections_search, params["value"])
    elif action == "connection_filter":
        select(settings._connections_filter, params["value"])
    elif action == "connections_toggle":
        click(settings._connections_show_more_btn)
    elif action == "connection_remove":
        row = settings._api_key_rows[params["index"]]
        click(button(row["widget"], "✕"))
    elif action == "route_button":
        section = params.get("section", "LLM")
        click(settings._model_route_buttons[section])
        row_index = params.get("index", 0)
        rows = settings._model_section_rows[section]
        if params["operation"] == "add":
            click(settings._model_route_add_buttons[section])
        elif params["operation"] == "remove":
            click(button(rows[row_index]["widget"], "✕"))
        elif params["operation"] == "refresh":
            click(rows[row_index]["refresh_btn"])
        elif params["operation"] == "apply_all":
            click(button(settings._model_route_cards[section], "Apply to all"))
        else:
            raise ValueError("Unknown route control")
    elif action == "conversation_menu":
        matches = [b for index, b in chat._sidebar_btns if index == params["index"]]
        assert len(matches) == 1
        row = matches[0].parentWidget()
        options = [b for b in row.findChildren(QPushButton) if b.toolTip() == "Conversation options"]
        assert len(options) == 1
        click(options[0])
    elif action == "project":
        if params.get("new"):
            # New project is an action, not a persistent selection. Cancelling
            # its dialog legitimately restores the previous item; choose it
            # once instead of trying to force the action to remain selected.
            click(chat._project_combo)
            QTest.keyClick(chat._project_combo, Qt.Key.Key_End)
            QTest.keyClick(chat._project_combo, Qt.Key.Key_Return)
        else:
            select(chat._project_combo, params["value"])
    elif action == "message_menu":
        buttons = [b for b in chat.findChildren(QPushButton) if b.isVisible() and b.toolTip() == "Message options"]
        click(buttons[params.get("index", -1)])
    elif action == "chat_button":
        click(button(chat, params["text"]))
    elif action == "choose_attachment":
        click(chat._attach_btn)
    elif action == "clear_attachments":
        click(chat.findChild(QPushButton, "clearPendingAttachments"))
    elif action == "new_chat_button":
        click(chat._new_chat_btn)
    elif action == "zoom":
        chat.activateWindow()
        click(chat._input)
        QTest.qWait(20)
        QTest.keyClick(chat, getattr(Qt.Key, "Key_" + params["key"]), Qt.KeyboardModifier.ControlModifier)
    elif action == "model_test":
        section = params["section"]
        click(settings._model_route_buttons[section])
        name = {"LLM": "Chat model", "VISION_LLM": "Image model", "MEMORY_LLM": "Memory model"}[section]
        click(button(settings._model_route_cards[section], "Test " + name))
    elif action == "shortcut_search":
        type_text(settings._shortcut_search, params["value"])
    elif action == "profile_wizard_escape":
        QTest.keyClick(settings._profile_setup_wizard, Qt.Key.Key_Escape)
    elif action in {"addon_button", "addon_enabled"}:
        from PySide6.QtWidgets import QCheckBox, QFrame, QLabel
        parent = host._addons_dialog
        if params.get("name"):
            cards = [card for card in parent.findChildren(QFrame, "addonCard") if any(label.text() == params["name"] for label in card.findChildren(QLabel))]
            assert len(cards) == 1, "Expected one installed addon card"
            parent = cards[0]
        if action == "addon_enabled":
            check = next(w for w in parent.findChildren(QCheckBox) if w.text() == "Enabled")
            if check.isChecked() != params["value"]:
                click(check)
        else:
            click(button(parent, params["text"]))
    elif action in {"addon_setting", "addon_child_close"}:
        from PySide6.QtWidgets import QCheckBox, QComboBox, QFormLayout
        child = (host._addon_settings_dialogs if params.get("kind", "settings") == "settings" else host._addon_log_dialogs)[params["id"]]
        if action == "addon_child_close":
            click(button(child, "Close"))
        else:
            fields = [form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
                      for form in child.findChildren(QFormLayout) for row in range(form.rowCount())
                      if form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().text() == params["label"]]
            assert len(fields) == 1, "Expected one labelled addon setting"
            field = fields[0]
            if isinstance(field, QCheckBox):
                if field.isChecked() != params["value"]:
                    click(field)
            elif isinstance(field, QComboBox):
                select(field, params["value"])
            else:
                type_text(field, params["value"])
                QTest.keyClick(field, Qt.Key.Key_Tab)
    elif action == "settings_folder_add":
        click(settings._fields["TOOL_FILE_ROOTS"]._add_button)
    elif action == "settings_folder_remove_all":
        editor = settings._fields["TOOL_FILE_ROOTS"]
        click(editor._list)
        QTest.keyClick(editor._list, Qt.Key.Key_Home)
        QTest.keyClick(editor._list, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        click(editor._remove_button)
    elif action in {"memory_edit", "memory_scope", "memory_delete", "memory_add_scope"}:
        panels = [w for w in QApplication.allWidgets() if isinstance(w, MemoryPanel) and w.isVisible()]
        assert len(panels) == 1
        panel = panels[0]
        if action == "memory_add_scope":
            select(panel._add_cat, params["value"])
        else:
            rows = [r for r in panel.findChildren(_FactRow) if params["match"] in r._text_edit.text()]
            assert len(rows) == 1, "Expected one matching visible memory fact"
            row = rows[0]
            if action == "memory_edit":
                type_text(row._text_edit, params["value"])
                QTest.keyClick(row._text_edit, Qt.Key.Key_Tab)
            elif action == "memory_scope":
                select(row._proj_combo, params["value"])
            else:
                click(button(row, "X"))
    elif action == "approval":
        from PySide6.QtWidgets import QFrame
        panels = [w for w in chat.findChildren(QFrame, "liveFileApprovalPanel") if w.isVisible()]
        assert len(panels) == 1
        click(button(panels[0], params["choice"]))
    else:
        raise ValueError(f"Unknown extended user action: {action}")


def observe(host):
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFrame,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QToolButton,
    )
    from shiboken6 import isValid

    from ui.memory_viewer import MemoryPanel, _FactRow
    from ui.settings_panel import dialog as settings_module

    output = {
        "dialog_events": getattr(host, "_journey_dialog_events", []),
        "dialog_pending": len(getattr(host, "_journey_dialog_plans", [])),
        "dialog_errors": getattr(host, "_journey_dialog_errors", []),
    }
    from scripts.user_journeys.agent_driver import observe as observe_agents
    output.update(observe_agents(host))
    from scripts.user_journeys.workspace_driver import observe as observe_workspace
    output.update(observe_workspace(host))
    overlay = getattr(host, "_overlay", None)
    tray = getattr(overlay, "_tray_menu", None)
    output["tray_labels"] = [action.text() for action in tray.actions() if action.text()] if tray is not None else []
    addons = getattr(host, "_addons_dialog", None)
    if addons is not None and isValid(addons) and addons.isVisible():
        output["addons"] = [{"labels": [label.text() for label in card.findChildren(QLabel)],
                             "buttons": [b.text() for b in card.findChildren(QPushButton) if b.isVisible()],
                             "enabled": next((b.isChecked() for b in card.findChildren(QCheckBox) if b.text() == "Enabled"), None)}
                            for card in addons.findChildren(QFrame, "addonCard")]
    from PySide6.QtWidgets import QFormLayout, QTextEdit
    output["addon_settings"] = {}
    for name, child in getattr(host, "_addon_settings_dialogs", {}).items():
        if not isValid(child) or not child.isVisible():
            continue
        values = {}
        for form in child.findChildren(QFormLayout):
            for row in range(form.rowCount()):
                label = form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().text()
                field = form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget()
                values[label] = field.isChecked() if isinstance(field, QCheckBox) else field.currentText() if isinstance(field, QComboBox) else field.text()
        output["addon_settings"][name] = values
    output["addon_logs"] = {name: child.findChild(QTextEdit).toPlainText() for name, child in getattr(host, "_addon_log_dialogs", {}).items() if isValid(child) and child.isVisible()}
    intent = getattr(host, "_intent", None)
    if intent is not None and isValid(intent) and intent.isVisible():
        output["intent"] = {"enabled": intent.isEnabled(), "focus_deferred": intent._focus_deferred,
                            "active": intent.isActiveWindow(), "focused": intent.hasFocus(),
                            "handled": intent._handled, "selection_pending": intent._selection_pending_idx,
                            "input_visible": intent._input_line.isVisible(), "text": intent._input_line.toPlainText(),
                            "rows": [{"label": r["label"], "prompt": r["prompt"], "glyph": r["glyph"], "custom": r["is_custom"]} for r in intent._rows],
                            "conversation_choice": intent.conversation_choice(), "selector": {"visible": intent._show_conversation_selector, "rect": list(intent._conversation_mode_rect.getRect()), "size": [intent.width(), intent.height()]}}
    bubble = getattr(host, "_bubble", None)
    reply = getattr(host, "_reply_response", None)
    external = getattr(host, "_external_reply_stream", None)
    output["reply_state"] = {"id": getattr(reply, "id", ""), "phase": getattr(reply, "phase", ""), "chars": len(getattr(reply, "reply_text", "")),
                             "external_index": external.get("conversation_index") if isinstance(external, dict) else None,
                             "bubble_visible": bool(bubble is not None and isValid(bubble) and bubble.isVisible()),
                             "bubble_response_id": getattr(getattr(bubble, "_response_state", None), "id", "")}
    if bubble is not None and isValid(bubble) and bubble.isVisible():
        response = getattr(bubble, "_response_state", None)
        output["bubble"] = {"text": bubble._text_view.toPlainText() if bubble._text_view.isVisible() else "", "full_text": bubble._full_text,
                            "phase": getattr(response, "phase", ""), "response_id": getattr(response, "id", "")}
    chat = getattr(host, "_chat", None)
    if chat is not None:
        output["chat_details"] = {"font_scale": chat._font_scale, "input_font": chat._input.styleSheet(),
                                  "pending_names": list(chat._pending_attachment_labels),
                                  "pending_image": bool(chat._pending_attachment_image_b64 or any(ref.get("kind") == "image" for ref in chat._pending_attachments)),
                                  "thumbnail_visible": chat._attachment_thumbnail.isVisible(),
                                  "attachment_preview_visible": chat._attachment_preview.isVisible()}
        output["conversations"] = [{"id": c.get("id"), "title": c.get("title_override", ""), "pinned": c.get("pinned", False), "project_id": c.get("project_id"), "messages": len(c.get("messages", [])), "policy": c.get("context_policy", {})} for c in chat._conversations]
        output["active_conversation"] = chat._active_idx
        output["projects"] = [{"id": p.get("id"), "name": p.get("name")} for p in chat._projects]
        output["project"] = chat._project_combo.currentData()
        output["approvals"] = [{"text": [w.text() for w in frame.findChildren(QLabel)], "buttons": [w.text() for w in frame.findChildren(QPushButton) if w.isVisible()]} for frame in chat.findChildren(QFrame, "liveFileApprovalPanel") if frame.isVisible()]
        output["error_details"] = [w.toPlainText() for w in chat.findChildren(QPlainTextEdit, "providerErrorDetailsText") if w.isVisible()]
        output["error_toggles"] = len([w for w in chat.findChildren(QToolButton, "providerErrorDetailsToggle") if w.isVisible()])
    settings = getattr(settings_module, "_settings_dialog", None)
    if settings is not None and settings.isVisible():
        wizard = getattr(settings, "_profile_setup_wizard", None)
        output["profile_wizard"] = {"visible": bool(wizard is not None and isValid(wizard) and wizard.isVisible())}
        output["shortcuts"] = [{"title": row["title_label"].text(), "description": row["description"], "visible": row["widget"].isVisible()} for row in settings._shortcut_rows]
        output["field_values"] = {
            name: widget.currentData() if isinstance(widget, QComboBox) else widget.isChecked() if isinstance(widget, QCheckBox) else widget.text()
            for name, widget in settings._fields.items() if widget.isVisible()
            and (isinstance(widget, (QComboBox, QCheckBox)) or isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.EchoMode.Normal)
        }
        output["profile"] = settings._profiles_btn.text()
        output["chatgpt_oauth"] = {"status": settings._chatgpt_status_lbl.text(), "detail": settings._chatgpt_message_lbl.text(), "login_enabled": settings._cgpt_login_btn.isEnabled()}
        output["file_roots"] = settings._fields["TOOL_FILE_ROOTS"].paths()
        output["saved_profiles"] = [settings._env.get(f"PROFILE_{i}_LABEL", "") for i in range(1, int(settings._env.get("PROFILE_COUNT", "0") or "0") + 1)]
        output["visible_pages"] = [settings._settings_nav.item(i).text() for i in range(settings._settings_nav.count()) if not settings._settings_nav.item(i).isHidden()]
        output["connections"] = [{"id": r.get("connection_id", ""), "address": r["custom_address"].text(), "alias": r["alias"].text(), "visible": r["widget"].isVisible()} for r in settings._api_key_rows]
        output["route_details"] = {key: [{"models": [r["model_combo"].itemData(i) for i in range(r["model_combo"].count())], "refresh_busy": not r["refresh_btn"].isEnabled()} for r in rows] for key, rows in settings._model_section_rows.items()}
        output["model_test_status"] = {key: getattr(settings, f"_{key}_test_status_lbl").text() for key in ("llm", "vision", "memory")}
        output["model_test_styles"] = {key: getattr(settings, f"_{key}_test_status_lbl").styleSheet() for key in ("llm", "vision", "memory")}
        output["fields"] = {name: widget.text() for name, widget in settings._fields.items() if isinstance(widget, QLineEdit) and widget.echoMode() == QLineEdit.EchoMode.Normal and widget.isVisible()}
    panels = [w for w in QApplication.allWidgets() if isinstance(w, MemoryPanel) and w.isVisible()]
    if panels:
        output["memory_rows"] = [{"text": r._text_edit.text(), "project": r._proj_combo.currentData()} for r in panels[0].findChildren(_FactRow)]
    return output
