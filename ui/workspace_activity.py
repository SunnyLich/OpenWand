"""Compact, expandable activity entries for OpenWand's shared workspace."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.i18n import t
from ui.shared.theme import theme_colors

MAX_ACTIVITY_ID = 160
MAX_SUMMARY_CHARS = 2_000
MAX_DETAIL_CHARS = 200_000
MAX_META_CHARS = 80

_ACTIVITY_KIND_SOURCES = {
    "user_file": "user file",
}


def _bounded(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"


def _stable_id(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("activity_id must not be empty")
    if len(text) > MAX_ACTIVITY_ID:
        raise ValueError(f"activity_id must be at most {MAX_ACTIVITY_ID} characters")
    return text


class ActivityHeader(QFrame):
    """Keyboard-accessible two-line header that toggles an activity item."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceActivityHeader")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(2)

        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 0, 0, 0)
        meta_layout.setSpacing(7)
        self.arrow_label = QLabel("▸")
        self.arrow_label.setObjectName("workspaceActivityArrow")
        self.timestamp_label = QLabel()
        self.timestamp_label.setObjectName("workspaceActivityTimestamp")
        self.kind_label = QLabel()
        self.kind_label.setObjectName("workspaceActivityKind")
        self.status_label = QLabel()
        self.status_label.setObjectName("workspaceActivityStatus")
        for label in (self.arrow_label, self.timestamp_label, self.kind_label, self.status_label):
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            meta_layout.addWidget(label)
        meta_layout.addStretch()
        layout.addLayout(meta_layout)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("workspaceActivitySummary")
        self.summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self.summary_label.setWordWrap(False)
        self.summary_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.summary_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.summary_label)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class WorkspaceActivityItem(QFrame):
    """One activity event with a compact header and optional full detail."""

    expandedChanged = Signal(bool)

    def __init__(
        self,
        activity_id: str,
        *,
        summary: str,
        detail: str = "",
        timestamp: str = "",
        kind: str = "info",
        status: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        stable_id = _stable_id(activity_id)
        self._activity_id = stable_id
        self._expanded = False
        self.setObjectName("workspaceActivityItem")
        self.setProperty("activityExpanded", False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = ActivityHeader()
        self.header.clicked.connect(self.toggle_expanded)
        layout.addWidget(self.header)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("workspaceActivityDetail")
        self.detail_label.setTextFormat(Qt.TextFormat.PlainText)
        self.detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail_label.setWordWrap(True)
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail_label.setContentsMargins(28, 8, 12, 12)
        self.detail_label.hide()
        layout.addWidget(self.detail_label)

        self.update_activity(
            summary=summary,
            detail=detail,
            timestamp=timestamp,
            kind=kind,
            status=status,
        )

    @property
    def activity_id(self) -> str:
        return self._activity_id

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def summary(self) -> str:
        return self.header.summary_label.text()

    @property
    def detail(self) -> str:
        return self.detail_label.text()

    def update_activity(
        self,
        *,
        summary: str,
        detail: str = "",
        timestamp: str = "",
        kind: str = "info",
        status: str = "",
    ) -> None:
        """Replace display data without changing the stable id or open state."""
        summary_text = _bounded(summary, MAX_SUMMARY_CHARS) or t("Activity")
        detail_text = _bounded(detail, MAX_DETAIL_CHARS)
        timestamp_text = _bounded(timestamp, MAX_META_CHARS)
        raw_kind = _bounded(kind, MAX_META_CHARS) or "info"
        raw_status = _bounded(status, MAX_META_CHARS)
        kind_text = t(_ACTIVITY_KIND_SOURCES.get(raw_kind, raw_kind))
        status_text = t(raw_status)

        self.header.summary_label.setText(summary_text)
        self.header.timestamp_label.setText(timestamp_text)
        self.header.timestamp_label.setVisible(bool(timestamp_text))
        self.header.kind_label.setText(kind_text)
        self.header.status_label.setText(status_text)
        self.header.status_label.setVisible(bool(status_text))
        self.detail_label.setText(detail_text or summary_text)
        self.setProperty("activityKind", raw_kind.casefold())
        self.setProperty("activityStatus", raw_status.casefold())
        self.header.setAccessibleName(" ".join(filter(None, (timestamp_text, kind_text, status_text, summary_text))))
        self._refresh_style()

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        value = bool(expanded)
        if value == self._expanded:
            return
        self._expanded = value
        self.detail_label.setVisible(value)
        self.header.arrow_label.setText("▾" if value else "▸")
        self.setProperty("activityExpanded", value)
        self._refresh_style()
        self.expandedChanged.emit(value)

    def _refresh_style(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()


class WorkspaceActivityList(QScrollArea):
    """Scrollable activity feed supporting safe stable-id upserts."""

    itemAdded = Signal(str)
    itemUpdated = Signal(str)
    itemRemoved = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, newest_first: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceActivityList")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._newest_first = bool(newest_first)
        self._items: dict[str, WorkspaceActivityItem] = {}

        self._content = QWidget()
        self._content.setObjectName("workspaceActivityContent")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setWidget(self._content)

    @property
    def count(self) -> int:
        return len(self._items)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(self._items)

    def item(self, activity_id: str) -> WorkspaceActivityItem | None:
        return self._items.get(str(activity_id).strip())

    def upsert(
        self,
        activity_id: str,
        *,
        summary: str,
        detail: str = "",
        timestamp: str = "",
        kind: str = "info",
        status: str = "",
        expanded: bool | None = None,
    ) -> WorkspaceActivityItem:
        """Add or update an entry; existing entries retain order and open state."""
        stable_id = _stable_id(activity_id)
        current = self._items.get(stable_id)
        if current is None:
            current = WorkspaceActivityItem(
                stable_id,
                summary=summary,
                detail=detail,
                timestamp=timestamp,
                kind=kind,
                status=status,
            )
            self._items[stable_id] = current
            index = 0 if self._newest_first else max(0, self._layout.count() - 1)
            self._layout.insertWidget(index, current)
            if expanded is not None:
                current.set_expanded(expanded)
            self.itemAdded.emit(stable_id)
            return current
        current.update_activity(
            summary=summary,
            detail=detail,
            timestamp=timestamp,
            kind=kind,
            status=status,
        )
        if expanded is not None:
            current.set_expanded(expanded)
        self.itemUpdated.emit(stable_id)
        return current

    def remove_activity(self, activity_id: str) -> bool:
        stable_id = str(activity_id).strip()
        item = self._items.pop(stable_id, None)
        if item is None:
            return False
        self._layout.removeWidget(item)
        item.deleteLater()
        self.itemRemoved.emit(stable_id)
        return True

    def clear_activities(self) -> None:
        for activity_id in tuple(self._items):
            self.remove_activity(activity_id)

    def expand_only(self, activity_ids: Iterable[str]) -> None:
        """Open a selected set and collapse all others."""
        wanted = {str(value).strip() for value in activity_ids}
        for activity_id, item in self._items.items():
            item.set_expanded(activity_id in wanted)


def workspace_activity_style() -> str:
    """Return activity-list styling for the active light or dark palette."""
    c = theme_colors()
    return f"""
QScrollArea#workspaceActivityList, QWidget#workspaceActivityContent {{
    background: {c["bg"]};
}}
QFrame#workspaceActivityItem {{
    background: {c["surface"]};
    border: 1px solid {c["border"]};
    border-radius: 7px;
}}
QFrame#workspaceActivityHeader:hover {{
    background: {c["raised"]};
}}
QLabel#workspaceActivityArrow, QLabel#workspaceActivityKind {{
    color: {c["accent"]};
}}
QLabel#workspaceActivityTimestamp, QLabel#workspaceActivityStatus {{
    color: {c["text_dim"]};
    font-size: 11px;
}}
QLabel#workspaceActivitySummary, QLabel#workspaceActivityDetail {{
    color: {c["text"]};
}}
QLabel#workspaceActivityDetail {{
    border-top: 1px solid {c["border"]};
    font-family: "Cascadia Mono", Consolas, monospace;
}}
QFrame#workspaceActivityItem[activityStatus="failed"] QLabel#workspaceActivityStatus {{
    color: {c["over_budget"]};
}}
QFrame#workspaceActivityItem[activityStatus="complete"] QLabel#workspaceActivityStatus {{
    color: {"#76d6a1" if c["bg"] == "#16181b" else "#2f7d54"};
}}
"""


OPENWAND_ACTIVITY_STYLE = workspace_activity_style()


__all__ = [
    "ActivityHeader",
    "OPENWAND_ACTIVITY_STYLE",
    "workspace_activity_style",
    "WorkspaceActivityItem",
    "WorkspaceActivityList",
]
