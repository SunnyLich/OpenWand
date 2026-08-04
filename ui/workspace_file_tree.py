"""Reusable nested file tree for Wisp-owned workspaces."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QInputDialog,
    QMenu,
    QMessageBox,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
)

PATH_ROLE = int(Qt.ItemDataRole.UserRole)
KIND_ROLE = PATH_ROLE + 1
CHANGE_ROLE = PATH_ROLE + 2

AGENT_CREATED_COLOR = QColor("#4da3ff")
AGENT_EDITED_COLOR = QColor("#f59e0b")
AGENT_DELETED_COLOR = QColor("#ef4444")

_CREATED = {"created", "new", "agent-created", "agent_created"}
_EDITED = {"edited", "updated", "modified", "agent-edited", "agent_edited"}
_DELETED = {"deleted", "removed", "tombstone", "agent-deleted", "agent_deleted"}


class WorkspaceFileTree(QTreeWidget):
    """Render flat workspace entries as a stable, activatable folder tree.

    ``set_entries`` accepts mappings with at least ``path`` and optionally
    ``kind`` (``file``/``folder``), ``change`` and ``tombstone``. Intermediate
    folders are generated automatically. Invalid or non-relative paths are
    ignored rather than displayed as workspace files.
    """

    file_activated = Signal(str)
    file_operation_requested = Signal(str, str, str, str)
    refresh_requested = Signal()
    reveal_requested = Signal(str)
    open_external_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformRowHeights(False)
        self.setAnimated(True)
        self.setRootIsDecorated(True)
        self.setItemsExpandable(True)
        self.setExpandsOnDoubleClick(False)
        self.setIndentation(17)
        self.setIconSize(QSize(18, 18))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet(
            "QTreeWidget { background: #11151f; border: 0; color: #e6e9f2; "
            "padding: 6px 5px; outline: 0; }"
            "QTreeWidget::item { min-height: 28px; border-radius: 4px; padding: 1px 4px; }"
            "QTreeWidget::item:hover { background: #202532; }"
            "QTreeWidget::item:selected { background: #3b3560; color: #ffffff; }"
            "QTreeWidget::branch { background: transparent; }"
        )
        self._items_by_path: dict[str, QTreeWidgetItem] = {}
        self._entries: dict[str, dict[str, Any]] = {}
        self._root_item: QTreeWidgetItem | None = None
        self._workspace_root = ""
        self._initialized = False
        self.itemActivated.connect(self._on_item_activated)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def set_workspace_root(self, root: str) -> None:
        """Attach the real session folder used by user-invoked system actions."""
        self._workspace_root = str(root or "")
        if self._root_item is not None:
            self._root_item.setToolTip(0, self._workspace_root or "Wisp Shared Workspace")

    def set_entries(self, entries: Iterable[Mapping[str, Any]]) -> None:
        """Replace the flat snapshot while preserving user navigation state."""
        selected_path = self.current_path()
        old_folder_paths = {
            path
            for path, item in self._items_by_path.items()
            if item.data(0, KIND_ROLE) == "folder"
        }
        expanded_paths = {
            path
            for path in old_folder_paths
            if self._items_by_path[path].isExpanded()
        }
        normalized = self._normalize_entries(entries)
        self._entries = normalized

        self.setUpdatesEnabled(False)
        try:
            self.clear()
            self._items_by_path = {}
            style = QApplication.style()
            root_item = QTreeWidgetItem(["Workspace"])
            root_item.setData(0, PATH_ROLE, "")
            root_item.setData(0, KIND_ROLE, "folder")
            root_item.setIcon(0, style.standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            root_font = root_item.font(0)
            root_font.setBold(True)
            root_item.setFont(0, root_font)
            root_item.setSizeHint(0, QSize(0, 30))
            root_item.setExpanded(True)
            root_item.setToolTip(0, self._workspace_root or "Wisp Shared Workspace")
            self.addTopLevelItem(root_item)
            self._root_item = root_item
            for path in sorted(
                normalized,
                key=lambda value: (
                    len(PurePosixPath(value).parts),
                    PurePosixPath(value).parent.as_posix().casefold(),
                    0 if normalized[value]["kind"] == "folder" else 1,
                    PurePosixPath(value).name.casefold(),
                ),
            ):
                metadata = normalized[path]
                item = QTreeWidgetItem([PurePosixPath(path).name])
                kind = str(metadata["kind"])
                change = str(metadata.get("change") or "")
                item.setData(0, PATH_ROLE, path)
                item.setData(0, KIND_ROLE, kind)
                item.setData(0, CHANGE_ROLE, change)
                item.setIcon(
                    0,
                    style.standardIcon(
                        QStyle.StandardPixmap.SP_DirIcon
                        if kind == "folder"
                        else QStyle.StandardPixmap.SP_FileIcon
                    ),
                )
                item.setSizeHint(0, QSize(0, 28))
                self._apply_change_style(item, change)
                parent_path = PurePosixPath(path).parent.as_posix()
                parent = root_item if parent_path == "." else self._items_by_path.get(parent_path)
                (parent or root_item).addChild(item)
                if kind == "folder":
                    item.setExpanded(
                        path in expanded_paths
                        if path in old_folder_paths
                        else True
                    )
                self._items_by_path[path] = item

            root_item.setExpanded(True)

            if selected_path in self._items_by_path:
                self.setCurrentItem(self._items_by_path[selected_path])
            elif not self._initialized:
                first_file = next(
                    (
                        item
                        for item in self._items_by_path.values()
                        if item.data(0, KIND_ROLE) == "file"
                        and item.data(0, CHANGE_ROLE) != "deleted"
                    ),
                    None,
                )
                if first_file is not None:
                    self.setCurrentItem(first_file)
            self._initialized = True
        finally:
            self.setUpdatesEnabled(True)
        self.viewport().update()

    def current_path(self) -> str:
        """Return the selected relative path, or an empty string."""
        item = self.currentItem()
        return str(item.data(0, PATH_ROLE) or "") if item is not None else ""

    def current_file_path(self) -> str:
        """Return the selected live file path, excluding folders/tombstones."""
        item = self.currentItem()
        if (
            item is None
            or item.data(0, KIND_ROLE) != "file"
            or item.data(0, CHANGE_ROLE) == "deleted"
        ):
            return ""
        return str(item.data(0, PATH_ROLE) or "")

    def item_for_path(self, path: str) -> QTreeWidgetItem | None:
        """Offer model lookup for integrations and tests."""
        normalized = _safe_path(path)
        return self._items_by_path.get(normalized or "")

    def activate_path(self, path: str) -> bool:
        """Select and emit one live file, returning whether it was activatable."""
        item = self.item_for_path(path)
        if item is None:
            return False
        self.setCurrentItem(item)
        return self._activate_item(item)

    def select_path(self, path: str) -> bool:
        """Select and reveal an entry without opening it."""
        item = self.item_for_path(path)
        if item is None:
            return False
        self.setCurrentItem(item)
        self.scrollToItem(item)
        return True

    def _on_item_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, KIND_ROLE) == "folder":
            item.setExpanded(not item.isExpanded())
            return
        self._activate_item(item)

    def _activate_item(self, item: QTreeWidgetItem) -> bool:
        if (
            item.data(0, KIND_ROLE) != "file"
            or item.data(0, CHANGE_ROLE) == "deleted"
        ):
            return False
        path = str(item.data(0, PATH_ROLE) or "")
        if not path:
            return False
        self.file_activated.emit(path)
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Provide familiar Explorer keyboard operations."""
        if event.key() == Qt.Key.Key_F2:
            self._request_rename()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Delete:
            self._request_delete()
            event.accept()
            return
        if event.key() == Qt.Key.Key_F5:
            self.refresh_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _show_context_menu(self, position: Any) -> None:
        item = self.itemAt(position)
        if item is not None:
            self.setCurrentItem(item)
        else:
            item = self._root_item
            if item is not None:
                self.setCurrentItem(item)
        if item is None:
            return
        path = str(item.data(0, PATH_ROLE) or "")
        kind = str(item.data(0, KIND_ROLE) or "")
        deleted = str(item.data(0, CHANGE_ROLE) or "") == "deleted"
        menu = QMenu(self)

        if kind == "file" and not deleted:
            open_action = QAction("Open", menu)
            open_action.triggered.connect(lambda: self._activate_item(item))
            menu.addAction(open_action)
            external_action = QAction("Open in default app", menu)
            external_action.triggered.connect(lambda: self.open_external_requested.emit(path))
            menu.addAction(external_action)
        elif kind == "folder":
            expand_action = QAction("Collapse" if item.isExpanded() else "Expand", menu)
            expand_action.triggered.connect(lambda: item.setExpanded(not item.isExpanded()))
            menu.addAction(expand_action)

        if not deleted:
            menu.addSeparator()
            new_folder = QAction("New folder", menu)
            new_folder.triggered.connect(lambda: self._request_create("folder"))
            menu.addAction(new_folder)
            new_file = QAction("New text document", menu)
            new_file.triggered.connect(lambda: self._request_create("file"))
            menu.addAction(new_file)

        if path and not deleted:
            menu.addSeparator()
            rename_action = QAction("Rename", menu)
            rename_action.setShortcut("F2")
            rename_action.triggered.connect(self._request_rename)
            menu.addAction(rename_action)
            delete_action = QAction("Delete", menu)
            delete_action.setShortcut("Del")
            delete_action.triggered.connect(self._request_delete)
            menu.addAction(delete_action)

        menu.addSeparator()
        reveal_action = QAction("Show in File Explorer", menu)
        reveal_action.triggered.connect(lambda: self.reveal_requested.emit(path))
        menu.addAction(reveal_action)
        copy_action = QAction("Copy path", menu)
        copy_action.triggered.connect(lambda: self._copy_path(path))
        menu.addAction(copy_action)
        refresh_action = QAction("Refresh", menu)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self.refresh_requested.emit)
        menu.addAction(refresh_action)
        menu.exec(self.viewport().mapToGlobal(position))

    def _operation_parent_path(self) -> str:
        item = self.currentItem() or self._root_item
        if item is None:
            return ""
        path = str(item.data(0, PATH_ROLE) or "")
        if item.data(0, KIND_ROLE) == "folder":
            return path
        parent = PurePosixPath(path).parent.as_posix()
        return "" if parent == "." else parent

    def _request_create(self, kind: str) -> None:
        parent = self._operation_parent_path()
        default = "New folder" if kind == "folder" else "New Text Document.txt"
        title = "Create folder" if kind == "folder" else "Create text document"
        name, accepted = QInputDialog.getText(self, title, "Name:", text=default)
        if accepted and str(name).strip():
            self.file_operation_requested.emit("create", parent, str(name).strip(), kind)

    def _request_rename(self) -> None:
        item = self.currentItem()
        if item is None:
            return
        path = str(item.data(0, PATH_ROLE) or "")
        if not path or item.data(0, CHANGE_ROLE) == "deleted":
            return
        old_name = PurePosixPath(path).name
        name, accepted = QInputDialog.getText(self, "Rename", "New name:", text=old_name)
        clean_name = str(name).strip()
        if accepted and clean_name and clean_name != old_name:
            self.file_operation_requested.emit("rename", path, clean_name, "")

    def _request_delete(self) -> None:
        item = self.currentItem()
        if item is None:
            return
        path = str(item.data(0, PATH_ROLE) or "")
        if not path or item.data(0, CHANGE_ROLE) == "deleted":
            return
        answer = QMessageBox.question(
            self,
            "Move to workspace trash?",
            f"Move {PurePosixPath(path).name} to the workspace trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.file_operation_requested.emit("delete", path, "", "")

    def _copy_path(self, path: str) -> None:
        value = path
        if self._workspace_root:
            value = (
                str(Path(self._workspace_root, *PurePosixPath(path).parts))
                if path
                else self._workspace_root
            )
        QApplication.clipboard().setText(value)

    @classmethod
    def _normalize_entries(
        cls,
        entries: Iterable[Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        explicit: dict[str, dict[str, Any]] = {}
        for raw in entries:
            if not isinstance(raw, Mapping):
                continue
            path = _safe_path(str(raw.get("path") or ""))
            if path is None:
                continue
            raw_kind = str(raw.get("kind") or "file").strip().lower()
            tombstone = bool(raw.get("tombstone")) or raw_kind in _DELETED
            kind = str(raw.get("original_kind") or raw_kind).strip().lower()
            kind = "folder" if kind == "folder" else "file"
            change = _normalize_change(raw.get("change") or raw.get("status"))
            if tombstone:
                change = "deleted"
            explicit[path] = {**dict(raw), "path": path, "kind": kind, "change": change}

        normalized: dict[str, dict[str, Any]] = {}
        for path in explicit:
            parent = PurePosixPath(path).parent
            while parent.as_posix() != ".":
                parent_path = parent.as_posix()
                normalized.setdefault(
                    parent_path,
                    {"path": parent_path, "kind": "folder", "change": ""},
                )
                parent = parent.parent
        normalized.update(explicit)
        return normalized

    @staticmethod
    def _apply_change_style(item: QTreeWidgetItem, change: str) -> None:
        color = {
            "created": AGENT_CREATED_COLOR,
            "edited": AGENT_EDITED_COLOR,
            "deleted": AGENT_DELETED_COLOR,
        }.get(change)
        if color is not None:
            item.setForeground(0, color)
        tooltip = {
            "created": "Created by Wisp",
            "edited": "Edited by Wisp",
            "deleted": "Deleted by Wisp",
        }.get(change)
        if tooltip:
            item.setToolTip(0, tooltip)
        if change == "deleted":
            font = item.font(0)
            font.setStrikeOut(True)
            item.setFont(0, font)
            item.setToolTip(0, "Deleted by Wisp · no longer in the workspace")


def _normalize_change(value: Any) -> str:
    change = str(value or "").strip().lower()
    if change in _CREATED:
        return "created"
    if change in _EDITED:
        return "edited"
    if change in _DELETED:
        return "deleted"
    return ""


def _safe_path(value: str) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text or len(text) > 240 or "\x00" in text or ":" in text:
        return None
    path = PurePosixPath(text)
    if path.is_absolute() or len(path.parts) > 12:
        return None
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    return path.as_posix()


__all__ = [
    "AGENT_CREATED_COLOR",
    "AGENT_DELETED_COLOR",
    "AGENT_EDITED_COLOR",
    "CHANGE_ROLE",
    "KIND_ROLE",
    "PATH_ROLE",
    "WorkspaceFileTree",
]
