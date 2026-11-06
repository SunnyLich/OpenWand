"""User input and visible observations for the real Agent Team windows."""

from __future__ import annotations


def surfaces(host):
    from PySide6.QtWidgets import QApplication

    from ui.agent.task_window import AgentRunHistoryWindow, AgentRunWindow, AgentTaskDialog

    widgets = QApplication.topLevelWidgets()
    task = next((w for w in widgets if isinstance(w, AgentTaskDialog) and w.isVisible()), None)
    run = next((w for w in reversed(widgets) if isinstance(w, AgentRunWindow) and w.isVisible()), None)
    history = next((w for w in widgets if isinstance(w, AgentRunHistoryWindow) and w.isVisible()), None)
    # macOS uses a different real activity window, with the same visible final
    # report. Observe it rather than substituting the Windows/Linux window.
    alternate = getattr(host, "_agent_run_dialog", None)
    if run is None and alternate is not None and alternate.dialog.isVisible():
        run = alternate
    alternate_history = getattr(host, "_agent_history_dialog", None)
    if history is None and alternate_history is not None and alternate_history.dialog.isVisible():
        history = alternate_history
    return task, run, history


def act(host, action, params, *, click, type_text, select, button):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QCheckBox, QComboBox, QSpinBox

    task, run, history = surfaces(host)
    if action == "agent_field":
        field = getattr(task, params["field"])
        if not field.isVisible() and task.advanced_panel.isAncestorOf(field):
            click(button(task, "Advanced Settings"))
        if isinstance(field, QCheckBox):
            if field.isChecked() != params["value"]:
                click(field)
        elif isinstance(field, QComboBox):
            select(field, params["value"])
        elif isinstance(field, QSpinBox):
            type_text(field.lineEdit(), str(params["value"]))
            QTest.keyClick(field, Qt.Key.Key_Tab)
        else:
            type_text(field, params["value"])
    elif action == "agent_button":
        target = task if params.get("kind", "task") == "task" else getattr(history, "dialog", history) if params["kind"] == "history" else getattr(run, "dialog", run)
        click(button(target, params["text"]))
    elif action == "agent_history_select":
        matches = [history.run_list.item(i) for i in range(history.run_list.count()) if params["title"] in history.run_list.item(i).text()]
        assert len(matches) == 1, "Expected one matching retained agent run"
        item = matches[0]
        history.run_list.scrollToItem(item)
        QTest.mouseClick(history.run_list.viewport(), Qt.MouseButton.LeftButton, pos=history.run_list.visualItemRect(item).center())
    elif action == "agent_history_tab":
        tabs = history.tabs
        index = next(i for i in range(tabs.count()) if tabs.tabText(i) == params["text"])
        QTest.mouseClick(tabs.tabBar(), Qt.MouseButton.LeftButton, pos=tabs.tabBar().tabRect(index).center())
    elif action == "agent_close_all":
        if task is not None:
            click(button(task, "Cancel"))
        if run is not None:
            click(button(getattr(run, "dialog", run), "Close"))
        if history is not None:
            click(button(getattr(history, "dialog", history), "Close"))
    else:
        raise ValueError(f"Unknown agent input: {action}")


def observe(host):
    task, run, history = surfaces(host)
    result = {}
    if task is not None:
        result["agent_task"] = {"title": task.title_edit.text(), "objective": task.objective_edit.toPlainText(),
                                "scope": task.scope_edit.text(), "provider": task.provider_combo.currentData(),
                                "model": task.model_edit.currentText(), "agents": task.agent_list.count(),
                                "parallel_briefing": task.parallel_briefing.isChecked(),
                                "max_turns": task.max_turns.value()}
    if run is not None:
        status = getattr(run, "status_lbl", None) or getattr(run, "status_label", None)
        result["agent_run"] = {"title": getattr(run, "dialog", run).windowTitle(), "run_dir": str(getattr(run, "_run_dir", "") or ""),
                               "status": status.text(), "final": run.final_view.toPlainText(),
                               "cancel_enabled": run.cancel_btn.isEnabled()}
    if history is not None:
        view = history.tabs.currentWidget()
        result["agent_history"] = {"runs": [history.run_list.item(i).text() for i in range(history.run_list.count())],
                                   "tab": history.tabs.tabText(history.tabs.currentIndex()), "text": view.toPlainText()}
    return result
