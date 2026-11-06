"""Complete actual modal dialogs using queued user input, never fake results.

Qt can run a nested event loop while a native-looking dialog is open. A timer
lets the acceptance driver type and click during that loop, as a user would.
Unexpected dialogs are never accepted, and every choice is recorded.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path


def watch_unexpected_dialogs(host):
    """Cancel an unplanned modal safely so later independent stories can run."""
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QLabel, QMessageBox

    if getattr(host, "_journey_modal_watch", None) is not None:
        return
    timer = QTimer(QApplication.instance())
    timer.setInterval(100)
    host._journey_modal_watch = timer
    seen = [None, 0.0]

    def inspect():
        modal = QApplication.activeModalWidget()
        if not isinstance(modal, (QFileDialog, QInputDialog, QMessageBox)) or getattr(host, "_journey_dialog_plans", []):
            seen[:] = [None, 0.0]
            return
        if seen[0] is not modal:
            seen[:] = [modal, time.monotonic()]
            return
        if time.monotonic() - seen[1] < 2:
            return
        labels = [label.text() for label in modal.findChildren(QLabel)]
        errors = getattr(host, "_journey_dialog_errors", [])
        errors.append(f"Unexpected modal {modal.windowTitle()!r}, labels={labels}; cancelled with Escape")
        host._journey_dialog_errors = errors
        # Escape is a user cancellation, never approval of an unknown choice.
        QTest.keyClick(modal, Qt.Key.Key_Escape)
        seen[:] = [None, 0.0]

    timer.timeout.connect(inspect)
    timer.start()


def queue_dialogs(host, plans, *, click, type_text, select):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialogButtonBox,
        QFileDialog,
        QFrame,
        QInputDialog,
        QLabel,
        QLineEdit,
        QMenu,
        QPushButton,
        QTextEdit,
    )

    assert not getattr(host, "_journey_dialog_plans", []), "A previous dialog plan is still pending"
    host._journey_dialog_plans = [dict(plan) for plan in plans]
    host._journey_dialog_deadline = time.monotonic() + 20
    host._journey_dialog_events = []
    host._journey_dialog_errors = []
    old_timer = getattr(host, "_journey_dialog_timer", None)
    if old_timer is not None:
        old_timer.stop()
    # The real QFileDialog is used in Qt mode; native OS dialogs remain outside
    # what an offscreen hosted run can certify. No chooser return is supplied.
    if any(plan["kind"] == "file" for plan in plans):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    timer = QTimer(QApplication.instance())
    timer.setInterval(40)
    host._journey_dialog_timer = timer

    def advance():
        # Typing emits real Qt events and can re-enter this timer. Do not
        # prepare the same dialog twice while its text is still being entered.
        if getattr(host, "_journey_dialog_preparing", False):
            return
        if not host._journey_dialog_plans:
            timer.stop()
            return
        plan = host._journey_dialog_plans[0]
        dialog = QApplication.activePopupWidget() if plan["kind"] == "menu" else QApplication.activeModalWidget()
        if plan["kind"] == "approval":
            chat = getattr(host, "_chat", None)
            panels = [] if chat is None else [w for w in chat.findChildren(QFrame, "liveFileApprovalPanel") if w.isVisible()]
            dialog = panels[0] if len(panels) == 1 else None
        elif plan["kind"] == "agent_approval":
            from scripts.user_journeys.agent_driver import surfaces
            _task, run, _history = surfaces(host)
            dialog = getattr(run, "approval_panel", None)
        if time.monotonic() > host._journey_dialog_deadline:
            controls = [] if dialog is None else [(w.text(), w.isEnabled()) for w in dialog.findChildren(QPushButton) if w.isVisible()]
            fields = [] if dialog is None else [(w.objectName(), w.text()) for w in dialog.findChildren(QLineEdit) if w.isVisible()]
            host._journey_dialog_errors.append(f"Dialog timed out for {plan}; buttons={controls}; fields={fields}")
            timer.stop()
            if dialog is not None and dialog.isVisible():
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            return
        if dialog is None or not dialog.isVisible() or (plan.get("title") and plan["title"] not in dialog.windowTitle()):
            if time.monotonic() > host._journey_dialog_deadline:
                title = dialog.windowTitle() if dialog is not None else "no dialog"
                host._journey_dialog_errors.append(f"Expected {plan}, observed {title!r}")
                timer.stop()
            return
        host._journey_dialog_preparing = True
        try:
            event = {"kind": plan["kind"], "title": dialog.windowTitle(), "choice": plan.get("button", plan.get("value", ""))}
            if plan["kind"] == "menu":
                assert isinstance(dialog, QMenu), "Expected the real popup menu"
                choices = [action for action in dialog.actions() if action.text().replace("&", "") == plan["value"]]
                assert len(choices) == 1, f"Menu choice absent: {plan['value']!r}; found {[a.text() for a in dialog.actions()]}"
                action = choices[0]
                assert action.isEnabled(), "The user's menu choice is disabled"
                if action.menu() is not None:
                    # Opening an actual submenu is UI navigation, not a call to
                    # its business handler. The next timer step selects a row.
                    def next_click():
                        action.menu().popup(dialog.mapToGlobal(dialog.actionGeometry(action).topRight()))
                else:
                    point = dialog.actionGeometry(action).center()
                    def next_click():
                        QTest.mouseClick(dialog, Qt.MouseButton.LeftButton, pos=point)
            else:
                if plan["kind"] == "input":
                    assert isinstance(dialog, QInputDialog), "Expected the real name/choice dialog"
                    if "value" in plan:
                        combo = next((w for w in dialog.findChildren(QComboBox) if w.isVisible()), None)
                        if combo is not None and not combo.isEditable():
                            select(combo, plan["value"])
                        else:
                            editor = next(w for w in dialog.findChildren(QLineEdit) if w.isVisible())
                            type_text(editor, plan["value"])
                elif plan["kind"] == "file":
                    assert isinstance(dialog, QFileDialog), "Expected the real file chooser"
                    if not plan.get("entered"):
                        QTest.qWait(150)  # Let the chooser finish restoring its initial directory.
                        editor = dialog.findChild(QLineEdit, "fileNameEdit")
                        type_text(editor, plan["value"])
                        plan["entered"] = True
                    QTest.qWait(100)  # QFileSystemModel resolves typed paths asynchronously.
                # Read review text before clicking, for independent assertions
                # about what the user was shown and what was approved.
                event["text"] = [w.toPlainText() for w in dialog.findChildren(QTextEdit) if w.isVisible()]
                event["labels"] = [w.text() for w in dialog.findChildren(QLabel) if w.isVisible()]
                if plan["kind"] in {"approval", "agent_approval"}:
                    # Observe the actual preview and disk before this user's
                    # choice can release the worker's blocked write operation.
                    target = Path(plan["absent_path"]).resolve()
                    import os
                    state = Path(os.environ["OPENWAND_E2E_STATE"]).resolve()
                    assert target.is_relative_to(state), "Approval evidence must use disposable files"
                    event["target_existed_before_choice"] = target.exists()
                    assert not target.exists(), "A proposed write happened before approval"
                    event["labels"] = [w.text() for w in dialog.findChildren(QLabel) if w.isVisible()]
                    name = plan["capture"] + "-preview.png"
                    destination = Path(os.environ["OPENWAND_E2E_OUTPUT"]) / "screenshots" / name
                    destination.parent.mkdir(exist_ok=True)
                    assert dialog.window().grab().save(str(destination)), "Approval preview screenshot failed"
                    event["screenshot"] = "screenshots/" + name
                buttons = [w for w in dialog.findChildren(QPushButton) if w.isVisible() and w.text().replace("&", "") == plan.get("button", "OK")]
                if not buttons and plan["kind"] == "file":
                    box = dialog.findChild(QDialogButtonBox)
                    buttons = [b for b in box.buttons() if b.isVisible() and box.buttonRole(b) == QDialogButtonBox.ButtonRole.AcceptRole]
                assert len(buttons) == 1, f"Expected one {plan.get('button', 'OK')!r} button in {dialog.windowTitle()!r}"
                if not buttons[0].isEnabled():
                    return
                if plan["kind"] == "file":
                    def next_click():
                        # Return commits a typed path through the chooser's
                        # default Open/Choose action. A second Return confirms
                        # completion or a folder navigation when necessary.
                        editor = dialog.findChild(QLineEdit, "fileNameEdit")
                        for _ in range(2):
                            QTest.keyClick(editor, Qt.Key.Key_Return)
                            if not dialog.isVisible():
                                break
                            QTest.qWait(50)
                else:
                    def next_click():
                        click(buttons[0])
            event["completed"] = False
            host._journey_dialog_events.append(event)
            host._journey_dialog_plans.pop(0)
            host._journey_dialog_deadline = time.monotonic() + 20
            # Defer the click so the timer is free to drive a second dialog
            # opened synchronously by the first one's normal signal handler.
            def perform_click():
                try:
                    next_click()
                    if plan["kind"] == "file":
                        assert not dialog.isVisible(), f"File chooser did not close; selected paths: {dialog.selectedFiles()}"
                    event["completed"] = True
                except Exception as error:
                    host._journey_dialog_errors.append(f"{error}\n{traceback.format_exc()}")
                    if dialog.isVisible():
                        QTest.keyClick(dialog, Qt.Key.Key_Escape)
            if plan["kind"] == "menu":
                QTimer.singleShot(0, perform_click)
            else:
                # Qt's static modal helpers can dispose child buttons when
                # this timer returns; click while the real dialog owns them.
                perform_click()
        except Exception as error:
            host._journey_dialog_errors.append(f"{error}\n{traceback.format_exc()}")
            timer.stop()
            if dialog.isVisible():
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
        finally:
            host._journey_dialog_preparing = False

    timer.timeout.connect(advance)
    timer.start()
