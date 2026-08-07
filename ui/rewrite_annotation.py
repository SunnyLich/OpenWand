"""App-attached composer and delayed-edit proposal UI for Rewrite mode."""

from __future__ import annotations

import difflib
import html
import os
import re
import sys
import uuid

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from ui.i18n import t

_POPUP_WIDTH = 390
_BALLOON_SIZE = 44
_SOURCE_POLL_MS = 250


def _word_tokens(value: str) -> list[str]:
    """Split text while retaining whitespace and punctuation for inline diffs."""
    return re.findall(r"\s+|[\w]+|[^\w\s]", str(value or ""), flags=re.UNICODE)


def inline_diff_html(original: str, replacement: str) -> str:
    """Render a safe word-level red/green delayed-edit diff."""
    before = _word_tokens(original)
    after = _word_tokens(replacement)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    parts: list[str] = []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == "equal":
            parts.append(html.escape("".join(before[a0:a1])))
        if tag in {"delete", "replace"}:
            deleted = html.escape("".join(before[a0:a1]))
            if deleted:
                parts.append(
                    '<span style="color:#ff6b6b;text-decoration:line-through;">'
                    f"{deleted}</span>"
                )
        if tag in {"insert", "replace"}:
            added = html.escape("".join(after[b0:b1]))
            if added:
                parts.append(f'<span style="color:#51cf66;">{added}</span>')
    return "".join(parts).replace("\n", "<br>")


class _SubmitEdit(QPlainTextEdit):
    """Multiline editor where Enter submits and Shift+Enter inserts a newline."""

    submit_requested = Signal(bool)  # force whole-document context
    height_changed = Signal()

    def __init__(
        self,
        *,
        minimum_height: int = 66,
        maximum_height: int = 220,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._minimum_editor_height = max(40, int(minimum_height))
        self._maximum_editor_height = max(
            self._minimum_editor_height,
            int(maximum_height),
        )
        self._resizing_to_document = False
        self.setFixedHeight(self._minimum_editor_height)
        self.textChanged.connect(self._resize_to_document)

    def _resize_to_document(self) -> None:
        """Grow with wrapped content, then scroll after reaching a safe maximum."""
        if self._resizing_to_document:
            return
        self._resizing_to_document = True
        try:
            document = self.document()
            available_width = max(40, self.viewport().width() - 4)
            visual_lines = 0
            block = document.firstBlock()
            metrics = self.fontMetrics()
            while block.isValid():
                line_width = max(1, metrics.horizontalAdvance(block.text()))
                visual_lines += max(1, (line_width + available_width - 1) // available_width)
                block = block.next()
            content_height = visual_lines * metrics.lineSpacing()
            target = max(
                self._minimum_editor_height,
                min(self._maximum_editor_height, content_height + self.frameWidth() * 2 + 14),
            )
            self.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded
                if target >= self._maximum_editor_height and content_height + 14 > target
                else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            if target != self.height():
                self.setFixedHeight(target)
                self.height_changed.emit()
        finally:
            self._resizing_to_document = False

    def resizeEvent(self, event):  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._resize_to_document()

    def keyPressEvent(self, event):  # noqa: N802 - Qt API
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            modifiers = event.modifiers()
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            self.submit_requested.emit(bool(modifiers & Qt.KeyboardModifier.ControlModifier))
            event.accept()
            return
        super().keyPressEvent(event)


class RewriteAnnotationPopup(QWidget):
    """One selected target's comment, processing balloon, and edit proposal."""

    submitted = Signal(str, str, bool)  # annotation id, comment, include document
    held = Signal(str, str, bool)  # annotation id, comment, include document
    cancel_requested = Signal(str)
    accept_requested = Signal(str, str)
    declined = Signal(str)
    revision_requested = Signal(str, str)
    anchor_refresh_requested = Signal(str)

    def __init__(
        self,
        *,
        annotation_id: str | None = None,
        display_number: int = 1,
        selected_text: str = "",
        source_window_id: int = 0,
        source_pid: int = 0,
        source_label: str = "",
        selection_rect: dict[str, float] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.annotation_id = str(annotation_id or uuid.uuid4().hex)
        self.display_number = max(1, int(display_number or 1))
        self.selected_text = str(selected_text or "")
        self.source_window_id = int(source_window_id or 0)
        self.source_pid = int(source_pid or 0)
        self.source_label = str(source_label or "")
        self.selection_rect = self._normalized_rect(selection_rect)
        self._anchor_visible = True
        self._source_origin_rect: QRect | None = None
        self.state = "composing"
        self.replacement_text = ""
        self._desired_visible = True
        self._copy_only = False
        # Choose the side using the full composer width and keep it for this
        # annotation's whole lifetime. Otherwise collapsing from 390 px to the
        # 44 px balloon can make the popup jump across the selected text.
        self._selection_anchor_side: str | None = None

        self.setWindowTitle(t("Comment"))
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_POPUP_WIDTH)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._panel = self._build_panel()
        self._balloon = self._build_balloon()
        self._stack.addWidget(self._panel)
        self._stack.addWidget(self._balloon)
        self._stack.setCurrentWidget(self._panel)

        self._source_timer = QTimer(self)
        self._source_timer.setInterval(_SOURCE_POLL_MS)
        self._source_timer.timeout.connect(self._sync_to_source_window)
        self._source_timer.start()
        self._anchor_timer = QTimer(self)
        self._anchor_timer.setInterval(400)
        self._anchor_timer.timeout.connect(self._request_anchor_refresh)
        self._anchor_timer.start()

    def _build_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("rewriteAnnotationPanel")
        panel.setStyleSheet(
            "QFrame#rewriteAnnotationPanel { background:#20222b; border:1px solid #45495a; "
            "border-radius:12px; }"
            "QLabel { color:#f1f3f5; }"
            "QPlainTextEdit { background:#15171e; color:#f8f9fa; border:1px solid #45495a; "
            "border-radius:8px; padding:7px; }"
            "QCheckBox { color:#ced4da; }"
            "QPushButton { background:#343847; color:#f8f9fa; border:none; border-radius:7px; "
            "padding:6px 11px; }"
            "QPushButton:hover { background:#454b60; }"
            "QPushButton#primary { background:#3b82f6; }"
            "QPushButton#dangerClose { background:#343847; border:1px solid #747b91; "
            "border-radius:12px; padding:0px; font-weight:700; }"
        )
        root = QVBoxLayout(panel)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        self._title = QLabel(t("Comment"))
        self._title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title_row.addWidget(self._title)
        title_row.addStretch(1)
        self._close = QPushButton("×")
        self._close.setObjectName("dangerClose")
        self._close.setFixedSize(24, 24)
        self._close.setToolTip(t("Cancel and remove"))
        self._close.clicked.connect(self._close_clicked)
        title_row.addWidget(self._close)
        root.addLayout(title_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#adb5bd;")
        self._status.hide()
        root.addWidget(self._status)

        self._comment = _SubmitEdit(minimum_height=78, maximum_height=220)
        self._comment.setObjectName("commentInput")
        self._comment.setPlaceholderText(t("Describe how this selection should change…"))
        self._comment.submit_requested.connect(self._submit)
        self._comment.height_changed.connect(self._resize_panel_to_content)
        root.addWidget(self._comment)

        self._include_document = QCheckBox(t("Include whole document"))
        root.addWidget(self._include_document)

        compose_footer = QHBoxLayout()
        self._hint = QLabel(t("Enter: Send   ·   Ctrl+Enter: Include document   ·   Shift+Enter: New line"))
        self._hint.setStyleSheet("color:#868e96; font-size:9px;")
        self._hint.setWordWrap(True)
        compose_footer.addWidget(self._hint, 1)
        compose_actions = QVBoxLayout()
        compose_actions.setContentsMargins(0, 0, 0, 0)
        compose_actions.setSpacing(5)
        self._hold = QPushButton(t("Hold"))
        self._hold.setToolTip(t("Keep this comment and send it later with Send all comments"))
        self._hold.clicked.connect(self._hold_comment)
        compose_actions.addWidget(self._hold)
        self._send = QPushButton(t("Send"))
        self._send.setObjectName("primary")
        self._send.clicked.connect(lambda: self._submit(False))
        compose_actions.addWidget(self._send)
        compose_footer.addLayout(compose_actions)
        root.addLayout(compose_footer)

        self._diff = QLabel("")
        self._diff.setObjectName("rewriteDiff")
        self._diff.setTextFormat(Qt.TextFormat.RichText)
        self._diff.setWordWrap(True)
        self._diff.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._diff.setStyleSheet(
            "background:#15171e; color:#f1f3f5; border:1px solid #45495a; "
            "border-radius:8px; padding:9px;"
        )
        self._diff.hide()
        root.addWidget(self._diff)

        self._proposal_actions = QWidget()
        proposal_actions = QHBoxLayout(self._proposal_actions)
        proposal_actions.setContentsMargins(0, 0, 0, 0)
        self._accept = QPushButton(t("Accept"))
        self._accept.setObjectName("primary")
        self._accept.clicked.connect(self._accept_clicked)
        self._decline = QPushButton(t("Decline"))
        self._decline.clicked.connect(self._decline_clicked)
        proposal_actions.addWidget(self._accept)
        proposal_actions.addWidget(self._decline)
        proposal_actions.addStretch(1)
        self._proposal_actions.hide()
        root.addWidget(self._proposal_actions)

        self._revision = _SubmitEdit(minimum_height=66, maximum_height=180)
        self._revision.setObjectName("revisionInput")
        self._revision.setPlaceholderText(t("Ask for a different revision…"))
        self._revision.submit_requested.connect(lambda _force: self._revise())
        self._revision.height_changed.connect(self._resize_panel_to_content)
        self._revision.hide()
        root.addWidget(self._revision)

        self._revision_footer = QWidget()
        revision_footer = QHBoxLayout(self._revision_footer)
        revision_footer.setContentsMargins(0, 0, 0, 0)
        revision_footer.addStretch(1)
        revise_button = QPushButton(t("Revise"))
        revise_button.clicked.connect(self._revise)
        revision_footer.addWidget(revise_button)
        self._revision_footer.hide()
        root.addWidget(self._revision_footer)
        return panel

    def _build_balloon(self) -> QWidget:
        shell = QWidget()
        shell.setFixedSize(_BALLOON_SIZE, _BALLOON_SIZE)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton(str(self.display_number))
        button.setObjectName("processingBalloon")
        button.setFixedSize(_BALLOON_SIZE, _BALLOON_SIZE)
        button.setToolTip(t("Rewrite is processing"))
        button.setStyleSheet(
            "QPushButton { background:#3b82f6; color:white; border:2px solid #93c5fd; "
            "border-radius:22px; font-size:20px; font-weight:700; padding:0; }"
            "QPushButton:hover { background:#2563eb; }"
        )
        button.clicked.connect(self._open_processing)
        layout.addWidget(button)
        self._balloon_button = button
        return shell

    def show_composer(self) -> None:
        self.state = "composing"
        self._set_compose_controls_visible(True)
        self._diff.hide()
        self._proposal_actions.hide()
        self._revision.hide()
        self._revision_footer.hide()
        self._status.hide()
        self._stack.setCurrentWidget(self._panel)
        self._resize_panel_to_content()
        self._desired_visible = True
        self._sync_to_source_window()
        self.raise_()
        self.activateWindow()
        self._comment.setFocus(Qt.FocusReason.PopupFocusReason)

    def show_processing(self) -> None:
        self.state = "processing"
        self._stack.setCurrentWidget(self._balloon)
        self.setFixedSize(_BALLOON_SIZE, _BALLOON_SIZE)
        self._desired_visible = True
        self._sync_to_source_window()
        self.raise_()

    def show_held(self) -> None:
        """Hide a saved comment until the shared Send all control dispatches it."""
        self.state = "held"
        self._desired_visible = False
        self.hide()

    def show_proposal(self, replacement_text: str, *, copy_only: bool = False) -> None:
        self.state = "proposal"
        self.replacement_text = str(replacement_text or "")
        self._copy_only = bool(copy_only)
        self._title.setText(t("Proposed edit"))
        self._set_compose_controls_visible(False)
        self._status.hide()
        self._diff.setText(inline_diff_html(self.selected_text, self.replacement_text))
        self._diff.show()
        self._accept.setText(t("Copy") if self._copy_only else t("Accept"))
        self._proposal_actions.show()
        self._revision.show()
        self._revision_footer.show()
        self._stack.setCurrentWidget(self._panel)
        self._resize_panel_to_content()
        self._desired_visible = True
        self._sync_to_source_window()
        self.raise_()

    def show_failure(self, message: str) -> None:
        self.state = "failed"
        self._title.setText(t("Comment"))
        self._set_compose_controls_visible(True)
        self._status.setText(str(message or t("Rewrite failed. You can retry.")))
        self._status.setStyleSheet("color:#ff8787;")
        self._status.show()
        self._stack.setCurrentWidget(self._panel)
        self._resize_panel_to_content()
        self._desired_visible = True
        self._sync_to_source_window()
        self.raise_()

    def _set_compose_controls_visible(self, visible: bool) -> None:
        for widget in (self._comment, self._include_document, self._hint, self._hold, self._send):
            widget.setVisible(visible)

    def _resize_panel_to_content(self) -> None:
        """Restore panel sizing after balloon mode and follow growing editors."""
        if not hasattr(self, "_panel") or self._stack.currentWidget() is not self._panel:
            return
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        available_height = screen.availableGeometry().height() if screen else 900
        maximum_height = max(280, int(available_height * 0.75))
        # Fully clear the 44x44 balloon constraints before expanding. Explicitly
        # resetting both dimensions avoids stale Win32 MINMAXINFO constraints on
        # high-DPI displays after a processing balloon becomes a proposal.
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16_777_215, 16_777_215)
        self.setMinimumHeight(0)
        self.setMaximumHeight(maximum_height)
        self.setFixedWidth(_POPUP_WIDTH)
        # QFrame.adjustSize() is allowed to widen the child to its unwrapped
        # sizeHint even though the top-level popup is fixed at 390 px. That
        # silently clips the circular X and the right-hand action buttons. Keep
        # the panel width constrained first, then ask its layout for the height
        # required at that exact width (including wrapped hint/status labels).
        self._panel.setFixedWidth(_POPUP_WIDTH)
        panel_layout = self._panel.layout()
        panel_layout.invalidate()
        panel_layout.activate()
        desired_height = int(panel_layout.totalHeightForWidth(_POPUP_WIDTH))
        if desired_height <= 0:
            desired_height = int(panel_layout.sizeHint().height())
        desired_height = max(1, min(maximum_height, desired_height))
        self._panel.setFixedHeight(desired_height)
        self.setFixedSize(_POPUP_WIDTH, desired_height)

    def _submit(self, force_document: bool) -> None:
        comment = self._comment.toPlainText().strip()
        if not comment:
            self._comment.setFocus()
            return
        include_document = bool(force_document or self._include_document.isChecked())
        self.submitted.emit(self.annotation_id, comment, include_document)
        self.show_processing()

    def _hold_comment(self) -> None:
        comment = self._comment.toPlainText().strip()
        if not comment:
            self._comment.setFocus()
            return
        include_document = bool(self._include_document.isChecked())
        self.held.emit(self.annotation_id, comment, include_document)
        self.show_held()

    def _revise(self) -> None:
        prompt = self._revision.toPlainText().strip()
        if not prompt:
            self._revision.setFocus()
            return
        self.revision_requested.emit(self.annotation_id, prompt)
        self._revision.clear()
        self.show_processing()

    def _accept_clicked(self) -> None:
        self._hide_for_terminal_action()
        self.accept_requested.emit(self.annotation_id, self.replacement_text)

    def _decline_clicked(self) -> None:
        self._hide_for_terminal_action()
        self.declined.emit(self.annotation_id)

    def _hide_for_terminal_action(self) -> None:
        """Hide immediately; a failed apply can explicitly show the proposal again."""
        self._desired_visible = False
        self.hide()

    def _close_clicked(self) -> None:
        self._hide_for_terminal_action()
        if self.state == "processing":
            self.cancel_requested.emit(self.annotation_id)
        else:
            self.declined.emit(self.annotation_id)

    def _open_processing(self) -> None:
        if self.state != "processing":
            return
        self._title.setText(t("Preparing edit…"))
        self._set_compose_controls_visible(False)
        self._diff.hide()
        self._proposal_actions.hide()
        self._revision.hide()
        self._revision_footer.hide()
        self._status.setText(t("Wisp is preparing the proposed rewrite."))
        self._status.setStyleSheet("color:#adb5bd;")
        self._status.show()
        self._stack.setCurrentWidget(self._panel)
        self._resize_panel_to_content()
        self._sync_to_source_window()
        self.raise_()

    def remove(self) -> None:
        self._desired_visible = False
        self._source_timer.stop()
        self._anchor_timer.stop()
        self.close()
        self.deleteLater()

    def update_selection_anchor(
        self,
        selection_rect: dict[str, float] | None,
        *,
        visible: bool = True,
    ) -> None:
        """Apply a refreshed accessibility/native range after document scrolling."""
        if not visible:
            self._anchor_visible = False
            self.hide()
            return
        rect = self._normalized_rect(selection_rect)
        if rect is None:
            return
        self.selection_rect = rect
        self._anchor_visible = True
        self._sync_to_source_window()

    def _request_anchor_refresh(self) -> None:
        if not self._desired_visible or not self.source_window_id:
            return
        self.anchor_refresh_requested.emit(self.annotation_id)

    def _sync_to_source_window(self) -> None:
        visible, source_rect = self._source_window_state()
        if not self._desired_visible:
            self.hide()
            return
        if not self._anchor_visible:
            self.hide()
            return
        if visible is False:
            self.hide()
            return
        anchor_rect = self._selection_anchor_for_source(source_rect)
        self._position_for_rect(anchor_rect or source_rect, selection_anchor=anchor_rect is not None)
        if not self.isVisible():
            self.show()

    def _selection_anchor_for_source(self, source_rect: QRect | None) -> QRect | None:
        """Move the captured selection with its source window without visual scanning."""
        if self.selection_rect is None:
            return None
        anchor = QRect(self.selection_rect)
        if source_rect is not None:
            if self._source_origin_rect is None:
                self._source_origin_rect = QRect(source_rect)
            anchor.translate(
                source_rect.left() - self._source_origin_rect.left(),
                source_rect.top() - self._source_origin_rect.top(),
            )
        return anchor

    def _position_for_rect(self, source_rect: QRect | None, *, selection_anchor: bool = False) -> None:
        screen = QApplication.screenAt(source_rect.center()) if source_rect else QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QApplication.primaryScreen().availableGeometry()
        width = self.width()
        height = self.height()
        if source_rect and selection_anchor:
            if self._selection_anchor_side is None:
                right_x = source_rect.x() + source_rect.width() + 10
                self._selection_anchor_side = (
                    "right" if right_x + _POPUP_WIDTH <= available.right() else "left"
                )
            # QRect.right() is inclusive; x + width is the first pixel after
            # the selection, which keeps the requested ten-pixel gap exact.
            if self._selection_anchor_side == "left":
                x = source_rect.left() - width - 10
            else:
                x = source_rect.x() + source_rect.width() + 10
            y = source_rect.top() - 12
        elif source_rect:
            x = source_rect.right() - width - 18
            y = source_rect.top() + 72
        else:
            x = available.right() - width - 20
            y = available.bottom() - height - 20
        x = max(available.left(), min(x, available.right() - width))
        y = max(available.top(), min(y, available.bottom() - height))
        self.move(x, y)

    @staticmethod
    def _normalized_rect(value: dict[str, float] | None) -> QRect | None:
        if not isinstance(value, dict):
            return None
        try:
            left = int(round(float(value.get("left") or 0)))
            top = int(round(float(value.get("top") or 0)))
            width = int(round(float(value.get("width") or 0)))
            height = int(round(float(value.get("height") or 0)))
        except (TypeError, ValueError, OverflowError):
            return None
        if width <= 0 or height <= 0:
            return None
        return QRect(left, top, width, height)

    def _source_window_state(self) -> tuple[bool | None, QRect | None]:
        if sys.platform != "win32" or not self.source_window_id:
            return None, None
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = int(self.source_window_id)
            if not user32.IsWindow(hwnd):
                return False, None
            if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return False, None
            foreground = int(user32.GetForegroundWindow() or 0)
            foreground_pid = wintypes.DWORD()
            if foreground:
                user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
            source_is_active = bool(
                foreground == hwnd
                or int(foreground_pid.value or 0) == int(self.source_pid or 0)
                or int(foreground_pid.value or 0) == os.getpid()
            )
            if not source_is_active:
                return False, None
            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True, None
            return True, QRect(
                int(rect.left),
                int(rect.top),
                max(1, int(rect.right - rect.left)),
                max(1, int(rect.bottom - rect.top)),
            )
        except Exception:
            return None, None
