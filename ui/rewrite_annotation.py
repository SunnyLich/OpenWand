"""App-attached composer and delayed-edit proposal UI for Rewrite mode."""

from __future__ import annotations

import difflib
import html
import os
import re
import sys
import time
import uuid

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QRegion
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
from ui.shared.theme import theme_colors

_POPUP_WIDTH = 390
_BALLOON_SIZE = 44
_SOURCE_POLL_MS = 250
_ANCHOR_POLL_MS = 200
_FOCUS_CLAIM_INTERVAL_MS = 40
_FOCUS_CLAIM_TIMEOUT_MS = 1_200
_FOCUS_STABLE_SAMPLES = 3


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
        self.setObjectName("rewriteAnnotationPopup")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("QWidget#rewriteAnnotationPopup { background: transparent; }")
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
        self._anchor_timer.setInterval(_ANCHOR_POLL_MS)
        self._anchor_timer.timeout.connect(self._request_anchor_refresh)
        self._anchor_timer.start()
        # A top-level Qt.Tool can be shown before Windows completes the native
        # foreground transition. One activateWindow()/setFocus() pair then
        # leaves the editor selection active, so the user's first keystrokes
        # replace source text instead of entering the comment. Keep a bounded
        # verifier alive until the popup has owned keyboard focus for several
        # consecutive event-loop samples.
        self._focus_claim_started = 0.0
        self._focus_claim_attempts = 0
        self._focus_stable_samples = 0
        self._focus_claim_timer = QTimer(self)
        self._focus_claim_timer.setInterval(_FOCUS_CLAIM_INTERVAL_MS)
        self._focus_claim_timer.timeout.connect(self._focus_claim_tick)

    def _build_panel(self) -> QWidget:
        c = theme_colors()
        accent_fill = c["accent_fill"]
        panel = QFrame()
        panel.setObjectName("rewriteAnnotationPanel")
        panel.setStyleSheet(
            f"QFrame#rewriteAnnotationPanel {{ background:{c['surface']}; border:1px solid {c['border']}; "
            "border-radius:12px; }"
            f"QLabel {{ color:{c['text']}; }}"
            f"QPlainTextEdit {{ background:{c['well']}; color:{c['text']}; border:1px solid {c['border']}; "
            "border-radius:8px; padding:7px; }"
            f"QPlainTextEdit:focus {{ border-color:{c['accent']}; }}"
            f"QCheckBox {{ color:{c['label']}; }}"
            f"QPushButton {{ background:{c['well']}; color:{c['accent']}; border:1px solid {c['well']}; border-radius:7px; "
            "padding:6px 11px; font-weight:600; }"
            f"QPushButton:hover {{ background:{c['button_hover']}; border-color:{c['button_hover']}; }}"
            f"QPushButton#primary {{ background:{accent_fill}; color:{c['on_accent']}; border-color:{accent_fill}; }}"
            f"QPushButton#primary:hover {{ background:{c['accent_fill_hover']}; }}"
            f"QPushButton#dangerClose {{ background:{c['well']}; color:{c['label']}; border:1px solid {c['border']}; "
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
        self._status.setStyleSheet(f"color:{c['text_dim']};")
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
        self._hint.setStyleSheet(f"color:{c['text_dim']}; font-size:9px;")
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
            f"background:{c['well']}; color:{c['text']}; border:1px solid {c['border']}; "
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
        c = theme_colors()
        accent_fill = c["accent_fill"]
        shell = QWidget()
        shell.setObjectName("processingBalloonShell")
        shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        shell.setStyleSheet("QWidget#processingBalloonShell { background: transparent; }")
        shell.setFixedSize(_BALLOON_SIZE, _BALLOON_SIZE)
        layout = QVBoxLayout(shell)
        layout.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("")
        button.setObjectName("processingBalloon")
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(_BALLOON_SIZE, _BALLOON_SIZE)
        button.setToolTip(t("Rewrite is processing"))
        button.setStyleSheet(
            f"QPushButton {{ background:{accent_fill}; border:2px solid {c['accent']}; "
            "border-radius:22px; padding:0; outline:none; }"
            f"QPushButton:hover {{ background:{c['accent_fill_hover']}; }}"
        )
        number = QLabel(str(self.display_number), button)
        number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        number.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        number.setGeometry(0, 0, _BALLOON_SIZE, _BALLOON_SIZE)
        number.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        number.setStyleSheet(
            f"QLabel {{ background:transparent; color:{c['on_accent']}; border:none; }}"
        )
        button.clicked.connect(self._open_processing)
        layout.addWidget(button)
        self._balloon_button = button
        self._balloon_number = number
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
        self._start_composer_focus_claim()

    def show_processing(self, *, display_number: int | None = None) -> None:
        self._stop_composer_focus_claim()
        if display_number is not None:
            self.display_number = max(1, int(display_number or 1))
            self._balloon_number.setText(str(self.display_number))
        self.state = "processing"
        self._stack.setCurrentWidget(self._balloon)
        self.setFixedSize(_BALLOON_SIZE, _BALLOON_SIZE)
        # The application-wide QWidget background otherwise paints the
        # transparent top-level corners. Clip the native tool window itself so
        # the processing badge is a real circle, never a black square holding
        # a circular icon.
        self.setMask(QRegion(self.rect(), QRegion.RegionType.Ellipse))
        self._desired_visible = True
        self._sync_to_source_window()
        self.raise_()

    def show_held(self) -> None:
        """Hide a saved comment until the shared Send all control dispatches it."""
        self._stop_composer_focus_claim()
        self.state = "held"
        self._desired_visible = False
        self.hide()

    def show_proposal(self, replacement_text: str, *, copy_only: bool = False) -> None:
        self._stop_composer_focus_claim()
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
        self._start_composer_focus_claim()

    def _start_composer_focus_claim(self) -> None:
        """Claim and verify keyboard focus while the native popup is settling."""
        self._focus_claim_started = time.monotonic()
        self._focus_claim_attempts = 0
        self._focus_stable_samples = 0
        if not self._focus_claim_timer.isActive():
            self._focus_claim_timer.start()
        self._focus_claim_tick()

    def _stop_composer_focus_claim(self) -> None:
        self._focus_claim_timer.stop()
        self._focus_stable_samples = 0

    def _composer_has_keyboard_focus(self) -> bool:
        return bool(self.isActiveWindow() and self._comment.hasFocus())

    def _focus_claim_tick(self) -> None:
        if self.state not in {"composing", "failed"} or not self._desired_visible:
            self._stop_composer_focus_claim()
            return
        source_visible, _source_rect = self._source_window_state()
        if source_visible is False:
            # The user moved to another application while the initial popup was
            # settling. Do not turn the bounded repair into ongoing focus theft.
            self._stop_composer_focus_claim()
            return
        elapsed_ms = (time.monotonic() - self._focus_claim_started) * 1_000
        if elapsed_ms >= _FOCUS_CLAIM_TIMEOUT_MS:
            self._stop_composer_focus_claim()
            return
        if self._composer_has_keyboard_focus():
            self._focus_stable_samples += 1
            if self._focus_stable_samples >= _FOCUS_STABLE_SAMPLES:
                self._stop_composer_focus_claim()
            return
        self._focus_stable_samples = 0
        self._focus_claim_attempts += 1
        self._activate_composer()

    def _activate_composer(self) -> None:
        """Request both Qt and native foreground activation for the comment field."""
        if not self.isVisible():
            self._sync_to_source_window()
        self.raise_()
        self._request_native_foreground()
        self.activateWindow()
        handle = self.windowHandle()
        if handle is not None:
            handle.requestActivate()
        self._comment.setFocus(Qt.FocusReason.PopupFocusReason)

    def _request_native_foreground(self) -> bool:
        """Ask Windows to finish the user-initiated popup activation."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.AttachThreadInput.argtypes = [
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.BOOL,
            ]
            user32.AttachThreadInput.restype = wintypes.BOOL
            user32.BringWindowToTop.argtypes = [wintypes.HWND]
            user32.BringWindowToTop.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            kernel32.GetCurrentThreadId.argtypes = []
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            hwnd = int(self.winId())
            foreground = int(user32.GetForegroundWindow() or 0)
            if foreground == hwnd:
                return True
            current_thread = int(kernel32.GetCurrentThreadId() or 0)
            foreground_thread = int(
                user32.GetWindowThreadProcessId(wintypes.HWND(foreground), None) or 0
            )
            attached = False
            try:
                if foreground_thread and foreground_thread != current_thread:
                    attached = bool(
                        user32.AttachThreadInput(current_thread, foreground_thread, True)
                    )
                user32.BringWindowToTop(wintypes.HWND(hwnd))
                user32.SetForegroundWindow(wintypes.HWND(hwnd))
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            return int(user32.GetForegroundWindow() or 0) == hwnd
        except Exception:
            return False

    def _set_compose_controls_visible(self, visible: bool) -> None:
        for widget in (self._comment, self._include_document, self._hint, self._hold, self._send):
            widget.setVisible(visible)

    def _resize_panel_to_content(self) -> None:
        """Restore panel sizing after balloon mode and follow growing editors."""
        if not hasattr(self, "_panel") or self._stack.currentWidget() is not self._panel:
            return
        self.clearMask()
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
        self._status.setText(t("OpenWand is preparing the proposed rewrite."))
        self._status.setStyleSheet(f"color:{theme_colors()['text_dim']};")
        self._status.show()
        self._stack.setCurrentWidget(self._panel)
        self._resize_panel_to_content()
        self._sync_to_source_window()
        self.raise_()

    def remove(self) -> None:
        self._desired_visible = False
        self._stop_composer_focus_claim()
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
            user32.IsWindow.argtypes = [wintypes.HWND]
            user32.IsWindow.restype = wintypes.BOOL
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.IsIconic.argtypes = [wintypes.HWND]
            user32.IsIconic.restype = wintypes.BOOL
            user32.GetForegroundWindow.argtypes = []
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            user32.GetWindowRect.restype = wintypes.BOOL
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
