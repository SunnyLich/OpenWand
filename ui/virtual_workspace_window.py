"""Native graphical desktop for Wisp's isolated Virtual Workspace addon."""
from __future__ import annotations

import base64
import difflib
import json
import re
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from PySide6.QtCore import (
    QByteArray,
    QPoint,
    QProcess,
    QRect,
    Qt,
    QTimer,
    QUrl,
    QUrlQuery,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QShortcut,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.shared.window_utils import enable_standard_window_controls, fit_window_to_screen
from ui.workspace_activity import WISP_ACTIVITY_STYLE, WorkspaceActivityItem, WorkspaceActivityList
from ui.workspace_file_tree import WorkspaceFileTree
from ui.workspace_previews import WorkspacePreview, preview_kind_for_path

_POLL_MS = 350
_MAX_TASK_CHARS = 8_000
_MAX_DRAFT_CHARS = 256 * 1024


def _validated_endpoint(raw_url: str) -> tuple[str, str]:
    """Return a loopback base URL and token or reject the addon payload."""
    value = str(raw_url or "").strip()
    if not value or len(value) > 4096 or any(char in value for char in ("\x00", "\r", "\n")):
        raise ValueError("invalid workspace endpoint")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid workspace endpoint") from exc
    token = (parse_qs(parsed.query).get("token") or [""])[0]
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1 <= port <= 65535
        or len(token) < 24
        or len(token) > 256
    ):
        raise ValueError("workspace endpoint must be authenticated IPv4 loopback")
    return f"http://127.0.0.1:{port}", token


class VirtualPointer(QWidget):
    """Compact mouse-only pointer or collaborative text caret."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._label = ""
        self._mode = ""
        self._target: QPoint | None = None
        self._caret_visible = True
        self._blink = QTimer(self)
        self._blink.setInterval(520)
        self._blink.timeout.connect(self._toggle_caret)
        self.setFixedSize(126, 50)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    @property
    def mode(self) -> str:
        return self._mode

    def point_to(self, target: QPoint, label: str = "Wisp") -> None:
        """Show an ordinary pointer only when an agent mouse event occurred."""
        self._mode = "mouse"
        self._label = str(label or "Wisp").strip()[:18]
        self._target = QPoint(max(4, target.x()), max(4, target.y()))
        self._blink.stop()
        self.move(self._target)
        self.show()
        self.raise_()
        self.update()

    def show_caret(self, target: QPoint, label: str = "Wisp agent") -> None:
        """Show a Google Docs-style blinking caret at agent text focus."""
        self._mode = "text"
        self._label = str(label or "Wisp agent").strip()[:20]
        self._target = QPoint(max(4, target.x()), max(4, target.y()))
        self._caret_visible = True
        self.move(self._target - QPoint(5, 25))
        self._blink.start()
        self.show()
        self.raise_()
        self.update()

    def hide(self) -> None:  # noqa: A003 - QWidget API
        self._blink.stop()
        self._mode = ""
        self._target = None
        super().hide()

    def _toggle_caret(self) -> None:
        if self._mode != "text":
            self._blink.stop()
            return
        self._caret_visible = not self._caret_visible
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802, ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._mode == "mouse":
            arrow = QPainterPath()
            arrow.moveTo(3, 2)
            arrow.lineTo(3, 23)
            arrow.lineTo(8, 18)
            arrow.lineTo(12, 27)
            arrow.lineTo(17, 25)
            arrow.lineTo(13, 16)
            arrow.lineTo(21, 16)
            arrow.closeSubpath()
            painter.fillPath(arrow, QColor("#f7f7f8"))
            painter.setPen(QPen(QColor("#202124"), 1.4))
            painter.drawPath(arrow)
            label_rect = QRect(24, 5, 50, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(46, 48, 55, 238))
            painter.drawRoundedRect(label_rect, 5, 5)
            painter.setPen(QColor("#f5f5f6"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, "Wisp")
        elif self._mode == "text":
            accent = QColor("#7651c9")
            label_rect = QRect(0, 0, 82, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(label_rect, 4, 4)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self._label or "Wisp agent")
            if self._caret_visible:
                painter.setPen(QPen(accent, 2.2))
                painter.drawLine(5, 23, 5, 48)


class VirtualDesktop(QWidget):
    """A shared-files surface with a persistent document preview."""

    def __init__(
        self,
        *,
        on_open_file: Callable[[str, bool], None],
        on_save_file: Callable[[str, str, int], None],
        on_activity: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_open_file = on_open_file
        self._on_save_file = on_save_file
        self._on_activity = on_activity
        self._entries: list[dict[str, Any]] = []
        self._items_by_path: dict[str, Any] = {}
        self._active_path = ""
        self._active_modified_ns = 0
        self._saved_text = ""
        self._incoming_text = ""
        self._preview_source_text = ""
        self._loading_document = False
        self._change_by_path: dict[str, str] = {}
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(22)
        self._typing_timer.timeout.connect(self._typing_tick)
        self._typing_text = ""
        self._typing_index = 0
        self._typing_step = 1
        self._active_draft_agent = ""

        self.setObjectName("virtualScreen")
        self.setMinimumHeight(470)
        self._build()

    @property
    def items_by_path(self) -> dict[str, Any]:
        return self._items_by_path

    @property
    def pointer(self) -> VirtualPointer:
        return self._pointer

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("desktopBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 0, 12, 0)
        name = QLabel("SHARED WORKSPACE")
        name.setObjectName("desktopBrand")
        bar_layout.addWidget(name)
        bar_layout.addStretch()
        self._status = QLabel("Ready")
        self._status.setObjectName("desktopStatus")
        bar_layout.addWidget(self._status)
        self._clock = QLabel()
        self._clock.setObjectName("desktopClock")
        bar_layout.addWidget(self._clock)
        layout.addWidget(bar)

        self._body = QFrame()
        self._body.setObjectName("desktopBody")
        body_layout = QHBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        files_panel = QFrame()
        files_panel.setObjectName("sharedFilesPanel")
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(12, 13, 12, 12)
        files_layout.setSpacing(8)
        self._icons = WorkspaceFileTree()
        self._icons.setObjectName("desktopIcons")
        self._icons.file_activated.connect(lambda path: self._on_open_file(path, False))
        files_layout.addWidget(self._icons, 1)
        files_panel.setFixedWidth(260)
        body_layout.addWidget(files_panel)

        layout.addWidget(self._body, 1)

        self._editor = QFrame()
        self._editor.setObjectName("virtualWindow")
        editor_layout = QVBoxLayout(self._editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        title_bar = QFrame()
        title_bar.setObjectName("virtualTitleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 4, 7, 4)
        self._editor_title = QLabel("Document")
        self._editor_title.setObjectName("virtualTitle")
        title_layout.addWidget(self._editor_title)
        title_layout.addStretch()
        self._edit_mode = QPushButton("Edit")
        self._edit_mode.setObjectName("editorMode")
        self._edit_mode.setCheckable(True)
        self._edit_mode.setChecked(True)
        self._edit_mode.clicked.connect(self._show_editor_mode)
        title_layout.addWidget(self._edit_mode)
        self._preview_mode = QPushButton("Preview")
        self._preview_mode.setObjectName("editorMode")
        self._preview_mode.clicked.connect(self._show_preview_mode)
        title_layout.addWidget(self._preview_mode)
        self._save = QPushButton("Save")
        self._save.setObjectName("editorSave")
        self._save.setEnabled(False)
        self._save.clicked.connect(self.save_user_changes)
        title_layout.addWidget(self._save)
        editor_layout.addWidget(title_bar)
        self._preview = WorkspacePreview()
        self._document = self._preview.text_editor
        self._document.setObjectName("virtualEditor")
        self._document.setReadOnly(False)
        self._document.textChanged.connect(self._document_changed)
        self._save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self._document)
        self._save_shortcut.activated.connect(self.save_user_changes)
        editor_layout.addWidget(self._preview, 1)
        body_layout.addWidget(self._editor, 1)

        self._hint = QLabel(
            "Start a task below. The file Wisp creates will open here.",
            self._document.viewport(),
        )
        self._hint.setObjectName("desktopHint")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setWordWrap(True)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._pointer = VirtualPointer(self._body)
        clock_timer = QTimer(self)
        clock_timer.setInterval(1_000)
        clock_timer.timeout.connect(self._update_clock)
        clock_timer.start()
        self._update_clock()

    def replace_entries(
        self,
        entries: list[dict[str, Any]],
        changes: dict[str, str] | None = None,
    ) -> None:
        """Render the files available to both the user and Wisp."""
        change_map = {
            str(path): str(change)
            for path, change in (changes or {}).items()
            if str(path) and str(change) in {"created", "edited", "deleted"}
        }
        enriched = [
            {**dict(item), "change": change_map.get(str(item.get("path") or ""), "")}
            for item in entries
            if isinstance(item, dict)
        ]
        live_paths = {str(item.get("path") or "") for item in enriched}
        enriched.extend(
            {
                "path": path,
                "kind": "file",
                "original_kind": "file",
                "change": "deleted",
                "tombstone": True,
            }
            for path, change in change_map.items()
            if change == "deleted" and path not in live_paths
        )
        signature = [
            (
                str(item.get("path") or ""),
                str(item.get("kind") or ""),
                int(item.get("bytes") or 0),
                str(item.get("change") or ""),
            )
            for item in enriched
            if isinstance(item, dict)
        ]
        old_signature = [
            (
                str(item.get("path") or ""),
                str(item.get("kind") or ""),
                int(item.get("bytes") or 0),
                str(item.get("change") or ""),
            )
            for item in self._entries
        ]
        if signature == old_signature:
            return
        self._entries = enriched
        self._change_by_path = change_map
        self._icons.set_entries(enriched)
        self._items_by_path = {
            str(entry.get("path") or ""): self._icons.item_for_path(str(entry.get("path") or ""))
            for entry in enriched
            if str(entry.get("path") or "")
        }
        if self._active_path and change_map.get(self._active_path) == "deleted":
            self._editor_title.setText(f"{self._active_path} · deleted by Wisp")
            self._highlight_agent_changes(
                self._document.toPlainText(),
                self._document.toPlainText(),
                "deleted",
            )
            self._document.setReadOnly(True)
            self._save.setEnabled(False)
            self.set_status("This file was deleted by Wisp")
        self._hint.setVisible(not self._items_by_path)
        QTimer.singleShot(0, self._position_hint)

    def set_status(self, text: str) -> None:
        self._status.setText(str(text or "Ready")[:90])

    def show_waiting(self, seconds: int) -> None:
        """Report waiting without pretending that the agent is using a mouse."""
        self.set_status(f"Waiting for model response · {seconds}s")
        self._pointer.hide()

    def set_cursor(self, cursor: dict[str, Any] | None) -> None:
        if not isinstance(cursor, dict) or not cursor.get("visible"):
            self._pointer.hide()
            return
        path = str(cursor.get("path") or "")
        kind = str(cursor.get("kind") or "")

        def move() -> None:
            if kind == "text":
                # The caret is positioned precisely after the file opens.
                self._pointer.hide()
                if self._editor.isVisible():
                    self._position_pointer_in_editor()
                return
            if kind != "mouse":
                self._pointer.hide()
                return
            item = self._items_by_path.get(path)
            if item is None:
                self._pointer.point_to(QPoint(34, 58), "Wisp")
                return
            rect = self._icons.visualItemRect(item)
            target = self._icons.viewport().mapTo(self._body, rect.center())
            target += QPoint(10, -8)
            self._pointer.point_to(target, "Wisp")

        QTimer.singleShot(0, move)

    def open_document(self, path: str, text: str, *, animate: bool) -> bool:
        """Show a document and optionally replay the write so it is observable."""
        del animate
        previous = self._saved_text if path == self._active_path else ""
        if path == self._active_path and self._save.isEnabled() and text != self._document.toPlainText():
            self._incoming_text = text
            self.set_status("Wisp changed this file while you are editing · your text is preserved")
            return False
        self._active_draft_agent = ""
        self._active_path = path
        self._editor_title.setText(path)
        self._pointer.raise_()
        self._hint.hide()
        self._typing_timer.stop()
        self._loading_document = True
        try:
            self._document.setReadOnly(False)
            self._preview.show_editor_content(path, text)
        finally:
            self._loading_document = False
        self._saved_text = text
        self._preview_source_text = text
        self._incoming_text = ""
        self._save.setEnabled(False)
        self._edit_mode.setChecked(True)
        self._highlight_agent_changes(previous, text, self._change_by_path.get(path, ""))
        QTimer.singleShot(0, self._position_pointer_in_editor)
        return True

    def open_preview(
        self,
        path: str,
        data: bytes,
        *,
        animate: bool,
        modified_ns: int = 0,
    ) -> None:
        """Open bounded bytes from the authenticated preview endpoint."""
        self._active_draft_agent = ""
        kind = preview_kind_for_path(path)
        if kind in {"text", "markdown", "html", "csv"}:
            opened = self.open_document(
                path,
                data.decode("utf-8", errors="replace"),
                animate=animate,
            )
            if opened:
                self._active_modified_ns = int(modified_ns or 0)
            return
        self._typing_timer.stop()
        self._editor_title.setText(path)
        self._hint.hide()
        shown_kind = self._preview.show_content(path, data)
        self._pointer.hide()
        self.set_status(f"Previewing {shown_kind}")

    def show_live_draft(self, agent: str, path: str, content: str) -> bool:
        """Render one worker's actual streamed draft without flickering between workers."""
        clean_agent = str(agent or "Wisp")[:80]
        if self._active_draft_agent and self._active_draft_agent != clean_agent:
            return False
        if path == self._active_path and self._save.isEnabled():
            self._incoming_text = content
            self.set_status(f"{clean_agent} has a live draft · your unsaved text is preserved")
            return False
        self._active_draft_agent = clean_agent
        self._typing_timer.stop()
        previous = self._saved_text if path == self._active_path else ""
        self._active_path = path
        self._preview_source_text = content
        self._editor_title.setText(f"{path} · live draft")
        self._hint.hide()
        self._loading_document = True
        try:
            shown_kind = self._preview.show_editor_content(path, content)
        finally:
            self._loading_document = False
        self.set_status(f"Drafting {path} · {len(content):,} chars")
        self._highlight_agent_changes(previous, content, self._change_by_path.get(path, "created"))
        if shown_kind == "text":
            cursor = self._document.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._document.setTextCursor(cursor)
            QTimer.singleShot(0, self._position_pointer_in_editor)
        else:
            self._pointer.hide()
        return True

    def save_user_changes(self) -> None:
        """Send the visible user's raw text through optimistic workspace saving."""
        if not self._active_path or not self._save.isEnabled():
            return
        self._on_save_file(
            self._active_path,
            self._document.toPlainText(),
            self._active_modified_ns,
        )

    def mark_user_save_complete(self, modified_ns: int) -> None:
        """Accept a confirmed save without waiting for the next state poll."""
        self._active_modified_ns = int(modified_ns or 0)
        self._saved_text = self._document.toPlainText()
        self._incoming_text = ""
        self._save.setEnabled(False)
        self.set_status("Your changes were saved")

    def mark_user_save_failed(self, message: str) -> None:
        """Keep unsaved text visible when optimistic concurrency rejects a save."""
        self._save.setEnabled(True)
        self.set_status(str(message or "Could not save your changes"))

    def _document_changed(self) -> None:
        if self._loading_document or not self._active_path:
            return
        self._save.setEnabled(self._document.toPlainText() != self._saved_text)
        if self._save.isEnabled():
            self._pointer.hide()
            self.set_status("You are editing · Ctrl+S to save")

    def _show_editor_mode(self) -> None:
        if not self._active_path:
            return
        text = (
            self._document.toPlainText()
            if self._preview.active_kind == "text"
            else self._preview_source_text
        )
        self._loading_document = True
        try:
            self._preview.show_editor_content(self._active_path, text)
        finally:
            self._loading_document = False
        self._edit_mode.setChecked(True)

    def _show_preview_mode(self) -> None:
        if not self._active_path:
            return
        text = self._document.toPlainText()
        self._preview_source_text = text
        shown = self._preview.show_content(self._active_path, text)
        self._edit_mode.setChecked(shown == "text")
        self.set_status(f"Previewing {shown}")
        self._pointer.hide()

    def _highlight_agent_changes(self, before: str, after: str, change: str) -> None:
        """Keep created/edited/deleted line evidence visible after fast writes."""
        selections: list[Any] = []

        def select_line(index: int, color: str) -> None:
            block = self._document.document().findBlockByNumber(max(0, index))
            if not block.isValid():
                block = self._document.document().lastBlock()
            selection = QTextEdit.ExtraSelection()
            selection.cursor = QTextCursor(block)
            selection.format = QTextCharFormat()
            selection.format.setBackground(QColor(color))
            selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
            selections.append(selection)

        after_lines = after.splitlines() or [""]
        if change == "created" or not before:
            for index in range(len(after_lines)):
                select_line(index, "#153a66")
        elif change == "edited":
            before_lines = before.splitlines()
            matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
            for opcode, _a1, _a2, b1, b2 in matcher.get_opcodes():
                if opcode in {"replace", "insert"}:
                    for index in range(b1, max(b1 + 1, b2)):
                        select_line(index, "#5a390d")
                elif opcode == "delete":
                    select_line(min(b1, len(after_lines) - 1), "#572126")
        elif change == "deleted":
            for index in range(len(after_lines)):
                select_line(index, "#572126")
        self._document.setExtraSelections(selections)

    def _typing_tick(self) -> None:
        self._typing_index = min(len(self._typing_text), self._typing_index + self._typing_step)
        self._document.setPlainText(self._typing_text[: self._typing_index])
        cursor = self._document.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._document.setTextCursor(cursor)
        if self._typing_index >= len(self._typing_text):
            self._typing_timer.stop()
            self.set_status("File updated")
        self._position_pointer_in_editor()

    def _position_pointer_in_editor(self) -> None:
        if not self._editor.isVisible() or self._preview.active_kind != "text":
            self._pointer.hide()
            return
        caret = self._document.cursorRect()
        target = self._document.mapTo(self._body, caret.topLeft())
        self._pointer.show_caret(target, "Wisp agent")

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        self._position_hint()

    def _position_hint(self) -> None:
        viewport = self._document.viewport().rect()
        self._hint.setGeometry(viewport.adjusted(60, 60, -60, -60))

    def _update_clock(self) -> None:
        self._clock.setText(datetime.now().strftime("%H:%M"))


class VirtualWorkspaceWindow(QDialog):
    """A visible shared workspace backed by an addon-owned filesystem session."""

    def __init__(
        self,
        endpoint: str,
        parent: QWidget | None = None,
        *,
        on_start_task: Callable[[str, str], None] | None = None,
        on_agent_control: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_url, self._token = _validated_endpoint(endpoint)
        self._on_start_task = on_start_task
        self._on_agent_control = on_agent_control
        self._network = QNetworkAccessManager(self)
        self._pending_state: QNetworkReply | None = None
        self._pending_scope: QNetworkReply | None = None
        self._pending_file: QNetworkReply | None = None
        self._pending_check: QNetworkReply | None = None
        self._pending_save: QNetworkReply | None = None
        self._pending_file_operation: QNetworkReply | None = None
        self._pending_file_path = ""
        self._pending_check_path = ""
        self._pending_file_animate = False
        self._queued_file_request: tuple[str, bool] | None = None
        self._queued_check_path = ""
        self._entry_signature: tuple[tuple[Any, ...], ...] = ()
        self._operation_signature: tuple[str, ...] = ()
        self._activity_items: dict[str, WorkspaceActivityItem] = {}
        self._cursor_signature: tuple[Any, ...] = ()
        self._last_state: dict[str, Any] = {}
        self._scope_folder = ""
        self._task_running = False
        self._task_paused = False
        self._pause_requested = False
        self._task_stopping = False
        self._stop_requested = False
        self._task_started_monotonic = 0.0
        self._last_agent_event_monotonic = 0.0
        self._agent_connected = False
        self._wait_notices: set[int] = set()
        self._select_after_refresh = ""

        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Wisp Shared Workspace")
        self.setModal(False)
        enable_standard_window_controls(self)
        self._build_ui()
        fit_window_to_screen(self, preferred_width=1240, preferred_height=820)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_MS)
        self._poll_timer.timeout.connect(self.refresh)
        self._poll_timer.start()
        self._task_timer = QTimer(self)
        self._task_timer.setInterval(1_000)
        self._task_timer.timeout.connect(self._task_tick)
        self._task_timer.start()
        QTimer.singleShot(0, self.refresh)

    @property
    def endpoint_base(self) -> str:
        """Return the non-secret endpoint identity used for window reuse."""
        return self._base_url

    def _build_ui(self) -> None:
        self.setStyleSheet(
            WISP_ACTIVITY_STYLE
            +
            "QDialog { background: #090b10; color: #eef0f6; }"
            "QFrame#composer { background: #11141c; "
            "border: 1px solid #292e3a; border-radius: 11px; }"
            "QFrame#activityPanel { background: #0d1017; border: 0; "
            "border-left: 1px solid #292e3a; }"
            "QLabel#eyebrow { color: #9ca4b8; font-size: 9px; font-weight: 700; }"
            "QLabel#title { color: #f2f4fa; font-size: 19px; font-weight: 700; }"
            "QLabel#connection { color: #bca4f4; font-weight: 700; padding: 4px 8px; }"
            "QLabel#notice { color: #d7c8ff; }"
            "QPushButton { background: #181c26; color: #e8eaf1; border: 1px solid #3a4050; "
            "border-radius: 7px; padding: 8px 12px; }"
            "QPushButton:hover { border-color: #9b73ef; background: #202532; }"
            "QPushButton#primary { background: #7548d8; border-color: #9c76ee; font-weight: 700; }"
            "QPushButton#danger { color: #ffc5cb; }"
            "QPushButton:disabled { color: #676d7c; border-color: #292d38; background: #141720; }"
            "QTextEdit { background: #0c0f16; color: #f1f2f7; border: 1px solid #343948; "
            "border-radius: 8px; padding: 9px; selection-background-color: #7046cc; }"
            "QWidget#virtualScreen { border: 1px solid #3c3650; border-radius: 12px; "
            "background: #111624; }"
            "QFrame#desktopBar { min-height: 38px; max-height: 38px; background: #111522; "
            "border-bottom: 1px solid #302b40; }"
            "QLabel#desktopBrand { color: #d9ccff; font-weight: 800; font-size: 10px; }"
            "QLabel#desktopPath { color: #8790a4; padding-left: 8px; }"
            "QLabel#desktopStatus { color: #c7b4fb; padding-right: 10px; }"
            "QLabel#desktopClock { color: white; font-weight: 700; }"
            "QFrame#desktopBody { background: #0c1018; }"
            "QFrame#sharedFilesPanel { background: #11151f; border-right: 1px solid #302b40; }"
            "QTreeWidget#desktopIcons { background: transparent; border: 0; color: white; outline: 0; }"
            "QTreeWidget#desktopIcons::item { min-height: 25px; }"
            "QTreeWidget#desktopIcons::item:selected { background: #453374; }"
            "QLabel#desktopHint { color: #858995; font-size: 16px; }"
            "QFrame#virtualWindow { background: #11151f; border: 0; }"
            "QFrame#virtualTitleBar { background: #171b26; border: 0; border-bottom: 1px solid #302b40; }"
            "QLabel#virtualTitle { color: #f2edff; font-weight: 700; }"
            "QPushButton#windowClose { padding: 0; border: 0; background: transparent; font-size: 17px; }"
            "QPlainTextEdit#virtualEditor { background: #0c1018; color: #dfe5f2; border: 0; "
            "font-family: 'Cascadia Mono', Consolas, monospace; font-size: 12px; padding: 12px; }"
            "QTextBrowser#workspaceRichPreview { background: #0c1018; color: #dfe5f2; border: 0; "
            "padding: 14px; selection-background-color: #7046cc; }"
            "QScrollArea#workspaceImagePreview, QPdfView#workspacePdfPreview { background: #0c1018; border: 0; }"
            "QSplitter::handle { background: #292e3a; border-radius: 2px; }"
            "QSplitter::handle:hover { background: #8059d8; }"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._connection = QLabel()
        self._connection.hide()

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        self._desktop = VirtualDesktop(
            on_open_file=self._request_file,
            on_save_file=self._save_file,
            on_activity=lambda: None,
        )
        self._desktop._icons.file_operation_requested.connect(self._file_operation)
        self._desktop._icons.refresh_requested.connect(self.refresh)
        self._desktop._icons.reveal_requested.connect(self._reveal_in_system)
        self._desktop._icons.open_external_requested.connect(self._open_in_default_app)
        self._activity_panel = self._build_activity_panel()
        self._splitter.addWidget(self._desktop)
        self._splitter.addWidget(self._activity_panel)
        self._splitter.setStretchFactor(0, 1)
        self._splitter.setStretchFactor(1, 0)
        self._activity_panel.setMinimumWidth(260)
        self._activity_panel.setMaximumWidth(620)
        self._activity_panel.show()
        QTimer.singleShot(0, lambda: self._splitter.setSizes([900, 320]))
        content_layout.addWidget(self._splitter, 1)
        root.addWidget(content, 1)

        composer = QFrame()
        composer.setObjectName("composer")
        composer_layout = QVBoxLayout(composer)
        composer_layout.setContentsMargins(13, 10, 13, 11)
        composer_layout.setSpacing(7)
        prompt_row = QHBoxLayout()
        prompt_label = QLabel("ASK WISP TO WORK IN THESE FILES")
        prompt_label.setObjectName("eyebrow")
        prompt_row.addWidget(prompt_label)
        prompt_row.addStretch()
        self._notice = QLabel("Connecting to the isolated session…")
        self._notice.setObjectName("notice")
        prompt_row.addWidget(self._notice)
        composer_layout.addLayout(prompt_row)
        task_row = QHBoxLayout()
        self._task = QTextEdit()
        self._task.setAcceptRichText(False)
        self._task.setPlaceholderText(
            "Example: Create a project folder, write a short README, and add a notes file."
        )
        self._task.setFixedHeight(68)
        task_row.addWidget(self._task, 1)
        buttons = QVBoxLayout()
        self._start = QPushButton("Start task")
        self._start.setObjectName("primary")
        self._start.setEnabled(False)
        self._start.clicked.connect(self._start_task)
        self._pause = QPushButton("Pause")
        self._pause.hide()
        self._pause.clicked.connect(lambda: self._control("pause"))
        self._cancel = QPushButton("Stop")
        self._cancel.setObjectName("danger")
        self._cancel.hide()
        self._cancel.clicked.connect(self._stop_task)
        buttons.addWidget(self._start)
        buttons.addWidget(self._pause)
        buttons.addWidget(self._cancel)
        task_row.addLayout(buttons)
        composer_layout.addLayout(task_row)
        root.addWidget(composer)

    def _build_activity_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("activityPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        label = QLabel("ACTIVITY")
        label.setObjectName("eyebrow")
        layout.addWidget(label)
        self._activity = WorkspaceActivityList(newest_first=True)
        layout.addWidget(self._activity, 1)
        return panel

    def refresh(self) -> None:
        """Request one state snapshot without blocking the Qt event loop."""
        if self._pending_state is not None:
            return
        reply = self._network.get(self._request("/api/state"))
        self._pending_state = reply
        reply.finished.connect(lambda current=reply: self._state_finished(current))

    def _request(self, path: str) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(self._base_url + path))
        request.setRawHeader(b"Authorization", f"Bearer {self._token}".encode())
        request.setRawHeader(b"Cache-Control", b"no-store")
        return request

    def _state_finished(self, reply: QNetworkReply) -> None:
        if reply is self._pending_state:
            self._pending_state = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._set_offline(reply.errorString())
                return
            state = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if not isinstance(state, dict):
                raise ValueError("invalid workspace state")
            self._render(state)
            if not self._scope_folder and self._pending_scope is None:
                self._request_task_scope()
        except Exception as exc:
            self._set_offline(str(exc))
        finally:
            reply.deleteLater()

    def _render(self, state: dict[str, Any]) -> None:
        self._last_state = dict(state)
        self._connection.setText("● Live")
        entries = [item for item in (state.get("entries") or []) if isinstance(item, dict)]
        changes = state.get("changes") if isinstance(state.get("changes"), dict) else {}
        self._desktop.replace_entries(entries, changes)
        if self._select_after_refresh and self._desktop._icons.select_path(self._select_after_refresh):
            self._select_after_refresh = ""
        cursor = state.get("cursor") if isinstance(state.get("cursor"), dict) else {}
        self._render_operations(list(state.get("operations") or []))
        self._sync_task_controls()
        if not self._task_running and not self._task_stopping:
            self._notice.setText("Ready for a task")
        cursor_signature = (
            str(cursor.get("path") or ""),
            str(cursor.get("label") or ""),
            str(cursor.get("kind") or ""),
            float(cursor.get("time") or 0),
        )
        if cursor_signature != self._cursor_signature:
            self._cursor_signature = cursor_signature
            self._desktop.set_cursor(cursor)
            path, _label, kind, _timestamp = cursor_signature
            if path and kind == "text":
                self._request_file(path, True)

    def _render_operations(self, operations: list[dict[str, Any]]) -> None:
        signature = tuple(str(item.get("id") or "") for item in operations if isinstance(item, dict))
        if signature == self._operation_signature:
            return
        self._operation_signature = signature
        for operation in operations[-2_000:]:
            if not isinstance(operation, dict):
                continue
            event_id = str(operation.get("id") or "")
            timestamp = float(operation.get("time") or 0)
            stamp = datetime.fromtimestamp(timestamp).strftime("%H:%M:%S") if timestamp else "--:--:--"
            self._add_activity_item(
                event_id,
                f"{stamp}  {operation.get('message') or 'Activity'}",
                detail=json.dumps(operation, indent=2, ensure_ascii=False),
                kind=str(operation.get("kind") or "activity"),
            )

    def _request_file(self, path: str, animate: bool = False) -> None:
        if not path:
            return
        if self._pending_file is not None:
            self._queued_file_request = (path, bool(animate))
            return
        url = QUrl(self._base_url + "/api/preview")
        query = QUrlQuery()
        query.addQueryItem("path", path)
        url.setQuery(query)
        request = QNetworkRequest(url)
        request.setRawHeader(b"Authorization", f"Bearer {self._token}".encode())
        request.setRawHeader(b"Cache-Control", b"no-store")
        reply = self._network.get(request)
        self._pending_file = reply
        self._pending_file_path = path
        self._pending_file_animate = bool(animate)
        reply.finished.connect(lambda current=reply: self._file_finished(current))

    def _request_task_scope(self) -> None:
        reply = self._network.get(self._request("/api/task-scope"))
        self._pending_scope = reply
        reply.finished.connect(lambda current=reply: self._scope_finished(current))

    def _scope_finished(self, reply: QNetworkReply) -> None:
        if reply is self._pending_scope:
            self._pending_scope = None
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if isinstance(payload, dict):
                self._scope_folder = str(payload.get("scope_folder") or "")
                self._desktop._icons.set_workspace_root(self._scope_folder)
                self._sync_task_controls()
        finally:
            reply.deleteLater()

    def _file_finished(self, reply: QNetworkReply) -> None:
        path = self._pending_file_path
        animate = self._pending_file_animate
        if reply is self._pending_file:
            self._pending_file = None
            self._pending_file_path = ""
            self._pending_file_animate = False
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._notice.setText(f"Could not open {path}")
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError(str((payload or {}).get("error") or "invalid file response"))
            if payload.get("encoding") != "base64":
                raise ValueError("invalid preview encoding")
            data = base64.b64decode(str(payload.get("data_base64") or ""), validate=True)
            self._desktop.open_preview(
                path,
                data,
                animate=animate,
                modified_ns=int(payload.get("modified_ns") or 0),
            )
            self._request_check(path)
        except Exception as exc:
            self._notice.setText(f"Could not open {path}: {exc}")
        finally:
            reply.deleteLater()
            queued, self._queued_file_request = self._queued_file_request, None
            if queued is not None:
                queued_path, queued_animate = queued
                QTimer.singleShot(
                    0,
                    lambda next_path=queued_path, next_animate=queued_animate: self._request_file(
                        next_path,
                        next_animate,
                    ),
                )

    def _save_file(self, path: str, text: str, expected_modified_ns: int) -> None:
        """Save one user edit through the authenticated optimistic bridge."""
        if self._pending_save is not None:
            self._desktop.mark_user_save_failed("A save is already in progress")
            return
        request = self._request("/api/save")
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps({
            "path": path,
            "text": text,
            "expected_modified_ns": int(expected_modified_ns or 0),
        }).encode("utf-8"))
        reply = self._network.post(request, payload)
        self._pending_save = reply
        reply.finished.connect(lambda current=reply: self._save_finished(current))
        self._desktop.set_status("Saving your changes…")

    def _save_finished(self, reply: QNetworkReply) -> None:
        if reply is self._pending_save:
            self._pending_save = None
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if reply.error() != QNetworkReply.NetworkError.NoError or not isinstance(payload, dict):
                raise ValueError(str((payload or {}).get("error") or reply.errorString()))
            if payload.get("error"):
                raise ValueError(str(payload["error"]))
            self._desktop.mark_user_save_complete(int(payload.get("modified_ns") or 0))
            self._notice.setText("Your changes are saved and visible to Wisp")
            self.refresh()
        except Exception as exc:
            self._desktop.mark_user_save_failed(str(exc))
            self._notice.setText(str(exc)[:180])
            self._add_activity_event("conflict", f"Your save was not applied: {exc}")
        finally:
            reply.deleteLater()

    def _file_operation(self, action: str, path: str, name: str, kind: str) -> None:
        """Apply a user-requested Explorer operation through the safe bridge."""
        if self._pending_file_operation is not None:
            self._notice.setText("Another file operation is still finishing")
            return
        request = self._request("/api/files")
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps({
            "action": str(action or ""),
            "path": str(path or ""),
            "name": str(name or ""),
            "kind": str(kind or ""),
        }).encode("utf-8"))
        reply = self._network.post(request, payload)
        self._pending_file_operation = reply
        reply.finished.connect(lambda current=reply: self._file_operation_finished(current))
        self._desktop.set_status(f"{str(action or 'Updating').capitalize()}…")

    def _file_operation_finished(self, reply: QNetworkReply) -> None:
        if reply is self._pending_file_operation:
            self._pending_file_operation = None
        try:
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if reply.error() != QNetworkReply.NetworkError.NoError or not isinstance(payload, dict):
                raise ValueError(str((payload or {}).get("error") or reply.errorString()))
            if payload.get("error") or not payload.get("ok"):
                raise ValueError(str(payload.get("error") or "File operation failed"))
            action = str(payload.get("action") or "updated")
            path = str(payload.get("path") or "")
            previous = str(payload.get("previous_path") or "")
            if action == "rename" and previous == self._desktop._active_path:
                self._desktop._active_path = path
                self._desktop._editor_title.setText(path)
            elif action == "delete" and path == self._desktop._active_path:
                self._desktop._document.setReadOnly(True)
                self._desktop._save.setEnabled(False)
                self._desktop._editor_title.setText(f"{path} · moved to workspace trash")
            if action != "delete":
                self._select_after_refresh = path
            message = {
                "create": f"Created {path}",
                "rename": f"Renamed to {path}",
                "delete": f"Moved {path} to workspace trash",
            }.get(action, f"Updated {path}")
            self._desktop.set_status(message)
            self._notice.setText(message)
            self.refresh()
        except Exception as exc:
            self._desktop.set_status("File operation failed")
            self._notice.setText(str(exc)[:180])
        finally:
            reply.deleteLater()

    def _workspace_system_path(self, relative_path: str) -> Path | None:
        """Resolve a displayed path beneath the authenticated session root."""
        if not self._scope_folder:
            return None
        root = Path(self._scope_folder).resolve()
        value = str(relative_path or "").strip().replace("\\", "/")
        parts = tuple(part for part in value.split("/") if part)
        if any(part in {".", ".."} or ":" in part for part in parts):
            return None
        target = root.joinpath(*parts)
        try:
            target.resolve(strict=False).relative_to(root)
        except ValueError:
            return None
        return target

    def _reveal_in_system(self, relative_path: str) -> None:
        """Open Explorer only after an explicit user menu action."""
        target = self._workspace_system_path(relative_path)
        if target is None:
            self._notice.setText("The workspace folder is not ready yet")
            return
        if sys.platform == "win32":
            if target.is_file():
                QProcess.startDetached("explorer.exe", ["/select,", str(target)])
            else:
                QProcess.startDetached("explorer.exe", [str(target)])
            return
        folder = target if target.is_dir() else target.parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_in_default_app(self, relative_path: str) -> None:
        """Open a real app only when the user explicitly requests it."""
        target = self._workspace_system_path(relative_path)
        if target is None or not target.is_file():
            self._notice.setText("That file is no longer available")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self._notice.setText(f"Windows could not open {target.name}")

    def _request_check(self, path: str) -> None:
        """Automatically validate supported code/data without running it."""
        if not str(path).casefold().endswith((".py", ".pyi", ".js", ".cjs", ".mjs", ".json")):
            return
        if self._pending_check is not None:
            self._queued_check_path = path
            return
        request = self._request("/api/check")
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps({"path": path}).encode("utf-8"))
        reply = self._network.post(request, payload)
        self._pending_check = reply
        self._pending_check_path = path
        reply.finished.connect(lambda current=reply: self._check_finished(current))

    def _check_finished(self, reply: QNetworkReply) -> None:
        path = self._pending_check_path
        if reply is self._pending_check:
            self._pending_check = None
            self._pending_check_path = ""
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._add_activity_event("check", f"Could not check {path}: {reply.errorString()}")
                return
            payload = json.loads(bytes(reply.readAll()).decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError(str((payload or {}).get("error") or "invalid check response"))
            summary = str(payload.get("summary") or "Check finished")
            detail = str(payload.get("stderr") or payload.get("stdout") or "").strip()
            message = f"{path}: {summary}"
            if detail:
                message += f" — {detail[:400]}"
            self._desktop.set_status(summary)
            self._add_activity_event("check", message)
        except Exception as exc:
            self._add_activity_event("check", f"Could not check {path}: {exc}")
        finally:
            reply.deleteLater()
            queued, self._queued_check_path = self._queued_check_path, ""
            if queued:
                QTimer.singleShot(0, lambda next_path=queued: self._request_check(next_path))

    def _start_task(self) -> None:
        objective = self._task.toPlainText().strip()
        if not objective:
            self._notice.setText("Describe what Wisp should do first.")
            self._task.setFocus()
            return
        if len(objective) > _MAX_TASK_CHARS:
            self._notice.setText(f"Keep the task under {_MAX_TASK_CHARS:,} characters.")
            return
        scope = self._scope_folder
        if not scope or self._on_start_task is None:
            self._notice.setText("The task runner is not connected yet.")
            return
        if bool(self._last_state.get("paused")):
            self._send_control("resume")
        self._task_paused = False
        self._pause_requested = False
        self._task_stopping = False
        self._stop_requested = False
        self.set_task_running(True)
        self._task_started_monotonic = time.monotonic()
        self._last_agent_event_monotonic = self._task_started_monotonic
        self._agent_connected = False
        self._wait_notices.clear()
        self._send_control("task_started")
        self._desktop.set_status("Wisp is starting the task…")
        self._notice.setText("Task started — changes will appear above")
        self._add_activity_event("task", "Task submitted to the workspace agent")
        self._on_start_task(objective, scope)

    def set_task_running(self, running: bool) -> None:
        self._task_running = bool(running)
        self._sync_task_controls()

    def _sync_task_controls(self) -> None:
        idle = not self._task_running and not self._task_stopping
        workspace_paused = bool(self._last_state.get("paused"))
        self._start.setEnabled(bool(self._scope_folder) and idle and not workspace_paused)
        self._task.setEnabled(idle)
        show_run_controls = self._task_running and not self._task_stopping
        self._pause.setVisible(show_run_controls)
        self._pause.setEnabled(show_run_controls and not self._pause_requested)
        if self._task_paused:
            self._pause.setText("Resume")
        elif self._pause_requested:
            self._pause.setText("Pausing…")
        else:
            self._pause.setText("Pause")
        self._cancel.setVisible(show_run_controls)
        self._cancel.setEnabled(show_run_controls)

    def append_agent_event(self, params: dict[str, Any]) -> None:
        """Show factual agent progress on the desktop without exposing private reasoning."""
        line = str((params or {}).get("line") or (params or {}).get("message") or "").strip()
        if not line:
            return
        clean = re.sub(r"^\[\d{2}:\d{2}:\d{2}\]\s*", "", line)
        agent_match = re.search(r"\s+\[agent=([^\]]{1,48})\]\s*$", clean)
        agent_label = agent_match.group(1).strip() if agent_match else ""
        if agent_match:
            clean = clean[: agent_match.start()].rstrip()
        phase_agent = re.sub(r"[^a-z0-9_-]+", "-", agent_label.casefold()).strip("-") or "main"
        activity_prefix = f"{agent_label}: " if agent_label else ""
        if re.match(r"^[^:]{1,80}\s+thought:\s*", clean, flags=re.IGNORECASE):
            clean = "Planning the next workspace step"
        self._agent_connected = True
        self._last_agent_event_monotonic = time.monotonic()
        self._wait_notices.clear()
        lower = clean.casefold()
        if lower.startswith("privacy filter "):
            # The structured privacy event carries the safe category/field
            # breakdown; suppress the less useful duplicate log line.
            self._desktop.set_status(clean)
            self._notice.setText(clean[:150])
            return
        if lower.startswith("requesting llm tool response"):
            self._desktop.set_status("Contacting model")
            self._notice.setText("Contacting the model…")
            self._add_activity_item(
                self._task_phase_id(f"model-{phase_agent}"),
                f"{datetime.now().strftime('%H:%M:%S')}  {activity_prefix}Contacting model",
            )
            return
        if lower.startswith("model call still waiting after "):
            elapsed = clean.split(" after ", 1)[1].split(" via ", 1)[0]
            message = f"Waiting for first model response · {elapsed}"
            self._desktop.set_status(message)
            self._notice.setText(message)
            self._add_activity_item(
                self._task_phase_id(f"model-{phase_agent}"),
                f"{datetime.now().strftime('%H:%M:%S')}  {activity_prefix}{message}",
            )
            return
        if lower.startswith("model first token after "):
            elapsed = clean.split(" after ", 1)[1].split(" via ", 1)[0]
            message = f"Model responded · receiving result ({elapsed})"
            self._desktop.set_status(message)
            self._notice.setText(message)
            self._add_activity_item(
                self._task_phase_id(f"model-{phase_agent}"),
                f"{datetime.now().strftime('%H:%M:%S')}  {activity_prefix}{message}",
            )
            return
        if lower.startswith(("model streaming response:", "model response still streaming after ")):
            detail = clean.split("(", 1)[-1].rstrip(")") if "(" in clean else "Receiving response"
            message = f"Receiving model result · {detail}"
            self._desktop.set_status(message)
            self._notice.setText(message)
            self._add_activity_item(
                self._task_phase_id(f"model-{phase_agent}"),
                f"{datetime.now().strftime('%H:%M:%S')}  {activity_prefix}{message}",
            )
            return
        if self._pause_requested and clean.casefold().startswith("agent run paused after turn"):
            self._pause_requested = False
            self._task_paused = True
            self._send_control("pause")
            self._desktop.set_status("Paused — current step finished")
            self._notice.setText("Paused before the next step")
            self._add_activity_event("control", "Current step finished; task is now paused")
            self._sync_task_controls()
            return
        if self._task_stopping:
            self._add_activity_event("agent", clean)
            return
        if self._task_paused:
            self._desktop.set_status("Paused — current step finished")
            self._notice.setText("Paused before the next step")
            self._add_activity_event("agent", clean)
            return
        self._desktop.set_status(clean)
        self._notice.setText("Finishing the current step before pausing…" if self._pause_requested else clean[:150])
        self._add_activity_event("agent", clean)

    def append_agent_trace(self, params: dict[str, Any]) -> bool:
        """Render bounded structured Workspace progress without exposing generic traces."""
        entry = str((params or {}).get("entry") or "").strip()
        if not entry.startswith("{") or len(entry) > (_MAX_DRAFT_CHARS * 2) + 4_000:
            return False
        try:
            payload = json.loads(entry)
        except (TypeError, ValueError):
            return False
        progress = payload.get("workspace_progress") if isinstance(payload, dict) else None
        if not isinstance(progress, dict):
            return False
        if progress.get("kind") == "model_response":
            content = str(progress.get("content") or "")
            if len(content) > 200_000:
                return False
            agent = str(progress.get("agent") or "Wisp").strip()[:80] or "Wisp"
            response_id = re.sub(
                r"[^a-zA-Z0-9_-]+",
                "-",
                str(progress.get("response_id") or "response"),
            ).strip("-")[:120] or "response"
            complete = bool(progress.get("complete"))
            response_chars = max(len(content), int(progress.get("chars") or 0))
            summary_text = ""
            if complete and not progress.get("truncated"):
                try:
                    response_payload = json.loads(content)
                except (TypeError, ValueError):
                    response_payload = None
                if isinstance(response_payload, dict):
                    summary_text = str(
                        response_payload.get("final")
                        or response_payload.get("thought")
                        or response_payload.get("reason")
                        or ""
                    ).strip()
            if summary_text:
                summary = f"{agent} replied: {summary_text}"
            elif complete:
                summary = f"{agent} reply complete Â· {response_chars:,} characters"
            else:
                summary = f"{agent} reply streaming Â· {response_chars:,} characters"
            self._agent_connected = True
            self._last_agent_event_monotonic = time.monotonic()
            self._desktop.set_status(
                f"{agent} replied" if complete else f"Receiving {agent}'s reply Â· {response_chars:,} characters"
            )
            self._notice.setText(
                f"{agent}'s full reply is available in Activity"
                if complete
                else f"Receiving {agent}'s real replyâ€¦ {response_chars:,} characters"
            )
            self._add_activity_item(
                self._task_phase_id(f"response-{response_id}"),
                f"{datetime.now().strftime('%H:%M:%S')}  {summary}",
                detail=content or "(The model returned an empty response.)",
                kind="model reply",
                status="complete" if complete else "streaming",
            )
            return True
        if progress.get("kind") == "privacy_redaction":
            summary = progress.get("summary") if isinstance(progress.get("summary"), dict) else {}
            count = max(0, int(summary.get("count") or 0))
            agent = str(progress.get("agent") or "Wisp").strip()[:80] or "Wisp"
            headline = str(summary.get("summary") or f"Privacy filter hid {count} item(s)")[:240]
            details = [
                f"Agent: {agent}",
                f"Detector: {str(summary.get('detector') or 'built_in').replace('_', ' ')}",
                f"Private items hidden: {count}",
            ]
            for category in list(summary.get("categories") or [])[:30]:
                if not isinstance(category, dict):
                    continue
                details.append(
                    f"• {category.get('label') or 'Sensitive data'} × {int(category.get('count') or 0)}"
                )
                reason = str(category.get("reason") or "").strip()
                if reason:
                    details.append(f"  {reason}")
            fields = [
                f"{field.get('label')} × {int(field.get('count') or 0)}"
                for field in list(summary.get("fields") or [])[:30]
                if isinstance(field, dict) and field.get("label")
            ]
            if fields:
                details.append("Hidden from: " + ", ".join(fields))
            phase_agent = re.sub(r"[^a-z0-9_-]+", "-", agent.casefold()).strip("-") or "wisp"
            self._add_activity_item(
                self._task_phase_id(f"privacy-{phase_agent}"),
                f"{datetime.now().strftime('%H:%M:%S')}  {headline}",
                detail="\n".join(details),
                kind="privacy",
                status="redacted" if summary.get("redacted") else "detected",
            )
            return True
        if progress.get("kind") != "workspace_draft":
            return False
        path = str(progress.get("path") or "").strip()
        content = str(progress.get("content") or "")
        agent = str(progress.get("agent") or "Wisp").strip()[:80] or "Wisp"
        if not path or len(content) > _MAX_DRAFT_CHARS:
            return False
        self._agent_connected = True
        self._last_agent_event_monotonic = time.monotonic()
        shown = self._desktop.show_live_draft(agent, path, content)
        if shown:
            self._notice.setText(f"{agent} is drafting {path} · {len(content):,} characters received")
        phase_agent = re.sub(r"[^a-z0-9_-]+", "-", agent.casefold()).strip("-") or "wisp"
        self._add_activity_item(
            self._task_phase_id(f"draft-{phase_agent}"),
            f"{datetime.now().strftime('%H:%M:%S')}  {agent}: Drafting {path} · {len(content):,} characters",
        )
        return True

    def finish_agent_task(self, params: dict[str, Any] | None = None) -> None:
        stopped = self._stop_requested
        self._task_stopping = False
        self._task_paused = False
        self._pause_requested = False
        self._stop_requested = False
        self.set_task_running(False)
        self._send_control("task_finished")
        payload = params or {}
        error = str(payload.get("error") or "").strip()
        final = str(payload.get("final") or "").strip()
        file_tool_successes = payload.get("file_tool_successes")
        incomplete = bool(
            re.search(
                r"(?:^blocked\b|stopped after reaching|turn limit|could not (?:complete|be created)|"
                r"did not complete|file creation is disabled|no artifacts were written)",
                final,
                flags=re.IGNORECASE,
            )
        )
        no_file_output = file_tool_successes is not None and int(file_tool_successes or 0) == 0
        failure = error or (final if incomplete else "")
        if not failure and no_file_output:
            failure = "No workspace files were created or updated."
        message = "Task stopped" if stopped else ("Task failed" if failure else "Task complete")
        self._desktop.set_status(message)
        if stopped:
            self._notice.setText("Stopped. Ready for another task.")
        else:
            self._notice.setText(failure[:150] if failure else "Task complete")
        file_tool_failures = int(payload.get("file_tool_failures") or 0)
        run_dir = str(payload.get("run_dir") or "").strip()
        run_log_path = str(payload.get("run_log_path") or "").strip()
        if not run_log_path and run_dir:
            run_log_path = str(Path(run_dir) / "run.log")
        model_errors = [
            str(item).strip()
            for item in list(payload.get("model_errors") or [])[-5:]
            if str(item).strip()
        ]
        diagnostic_reason = model_errors[-1] if model_errors else failure
        if failure and model_errors and not stopped:
            self._notice.setText(diagnostic_reason[:150])
        result_lines = []
        for result in list(payload.get("file_tool_results") or [])[:100]:
            if not isinstance(result, dict):
                continue
            result_lines.append(
                f"{'✓' if result.get('ok') else '✕'} "
                f"{result.get('tool') or 'file'}: {result.get('message') or '(no detail)'}"
            )
        failure_detail = "\n".join(filter(None, [
            f"Reason: {diagnostic_reason}" if diagnostic_reason else "",
            f"Task result: {failure}" if failure and diagnostic_reason != failure else "",
            f"Successful file operations: {int(file_tool_successes or 0)}",
            f"Failed file operations: {file_tool_failures}",
            "\n".join(result_lines),
            f"Full run log: {run_log_path}" if run_log_path else "",
        ]))
        failure_summary = (
            "Task failed — model connection"
            if failure and model_errors and "connection" in diagnostic_reason.casefold()
            else "Task incomplete — turn limit reached"
            if failure and "turn limit" in failure.casefold()
            else ("Task failed" if failure else message)
        )
        self._add_activity_event(
            "error" if failure and not stopped else "task",
            failure_summary,
            detail=failure_detail or message,
            expanded=bool(failure and not stopped),
            status="failed" if failure and not stopped else "complete",
        )

    def _task_tick(self) -> None:
        if not self._task_running or self._task_paused or self._task_stopping:
            return
        now = time.monotonic()
        quiet = max(0, int(now - self._last_agent_event_monotonic))
        total = max(0, int(now - self._task_started_monotonic))
        if quiet < 2:
            return
        if self._agent_connected:
            self._desktop.show_waiting(quiet)
            if self._pause_requested:
                self._notice.setText(f"Finishing the current response before pausing… {quiet}s elapsed")
            else:
                self._notice.setText(f"Waiting for the model response… {quiet}s elapsed")
            wait_message = f"Model response still pending ({quiet}s; task elapsed {total}s)"
        else:
            self._desktop.set_status(f"Waiting for task runner · {total}s")
            self._desktop.pointer.hide()
            self._notice.setText(f"Waiting for the task runner to connect… {total}s elapsed")
            wait_message = f"Task runner has not connected yet ({total}s)"
        for threshold in (5, 15, 30, 60, 120, 300):
            if quiet >= threshold and threshold not in self._wait_notices:
                self._wait_notices.add(threshold)
                self._add_activity_event("wait", wait_message)

    def _add_activity_event(
        self,
        kind: str,
        message: str,
        *,
        detail: str = "",
        expanded: bool = False,
        status: str = "",
    ) -> None:
        event_id = f"ui-{time.time_ns()}"
        stamp = datetime.now().strftime("%H:%M:%S")
        self._add_activity_item(
            event_id,
            f"{stamp}  {message}",
            detail=detail or message,
            kind=kind,
            status=status,
            expanded=expanded,
        )
        request = self._request("/api/event")
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps({"id": event_id, "kind": kind, "message": message}).encode("utf-8"))
        reply = self._network.post(request, payload)
        reply.finished.connect(reply.deleteLater)

    def _task_phase_id(self, phase: str) -> str:
        task_id = int(self._task_started_monotonic * 1_000) if self._task_started_monotonic else 0
        return f"ui-task-{task_id}-{phase}"

    def _add_activity_item(
        self,
        event_id: str,
        text: str,
        *,
        detail: str = "",
        kind: str = "agent",
        status: str = "",
        expanded: bool | None = None,
    ) -> None:
        if not event_id:
            return
        match = re.match(r"^(\d{2}:\d{2}:\d{2}|--:--:--)\s{2}(.*)$", str(text or ""), flags=re.DOTALL)
        timestamp = match.group(1) if match else datetime.now().strftime("%H:%M:%S")
        summary = match.group(2).strip() if match else str(text or "Activity").strip()
        item = self._activity.upsert(
            event_id,
            timestamp=timestamp,
            kind=kind,
            status=status,
            summary=summary,
            detail=detail or summary,
            expanded=expanded,
        )
        self._activity_items[event_id] = item
        self._activity.ensureWidgetVisible(item)
        while self._activity.count > 500:
            oldest_id = self._activity.ids[0]
            self._activity.remove_activity(oldest_id)
            self._activity_items.pop(oldest_id, None)

    def request_agent_approval(self, params: dict[str, Any]) -> bool:
        """Ask for a scoped task approval directly over the virtual desktop."""
        description = str(params.get("description") or params.get("message") or "Allow this task step?")
        answer = QMessageBox.question(
            self,
            "Wisp task approval",
            description[:2_000],
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _control(self, action: str) -> None:
        if action == "pause" and self._task_paused:
            self._task_paused = False
            self._pause_requested = False
            self._send_control("resume")
            self._agent_control("resume")
            self._last_agent_event_monotonic = time.monotonic()
            self._desktop.set_status("Resuming task")
            self._notice.setText("Resuming…")
            self._add_activity_event("control", "Task resumed")
            self._sync_task_controls()
            return
        if action == "pause" and self._task_running and not self._pause_requested:
            self._pause_requested = True
            self._agent_control("pause")
            self._desktop.set_status("Pausing after the current step")
            self._notice.setText("The current step will finish; no new step will begin")
            self._add_activity_event("control", "Pause requested after the current step")
            self._sync_task_controls()

    def _stop_task(self) -> None:
        if not self._task_running or self._task_stopping:
            return
        self._stop_requested = True
        self._task_stopping = True
        self._task_paused = True
        self._pause_requested = False
        self._task_running = False
        self._send_control("pause")
        self._agent_control("cancel")
        self._desktop.pointer.hide()
        self._desktop.set_status("Task stopped")
        self._notice.setText("Stopped — Wisp cannot make further changes to this screen")
        self._add_activity_event("control", "Stop requested; workspace file actions locked")
        self._sync_task_controls()

    def _agent_control(self, action: str) -> None:
        if self._on_agent_control is not None:
            self._on_agent_control(action)

    def _send_control(self, action: str) -> None:
        request = self._request("/api/control")
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        payload = QByteArray(json.dumps({"action": action}).encode("utf-8"))
        reply = self._network.post(request, payload)
        reply.finished.connect(lambda current=reply: self._control_finished(current))

    def _control_finished(self, reply: QNetworkReply) -> None:
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._set_offline(reply.errorString())
        finally:
            reply.deleteLater()
            QTimer.singleShot(0, self.refresh)

    def _set_offline(self, detail: str) -> None:
        self._connection.setText("● Offline")
        self._notice.setText(f"Workspace connection unavailable: {detail}")
        self._desktop.pointer.hide()
        self._start.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._poll_timer.stop()
        self._task_timer.stop()
        for reply in (self._pending_state, self._pending_scope, self._pending_file, self._pending_check):
            if reply is not None:
                reply.abort()
        self._pending_state = None
        self._pending_scope = None
        self._pending_file = None
        self._pending_check = None
        super().closeEvent(event)
