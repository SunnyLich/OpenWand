"""Focused tests for the reusable workspace folder tree."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWidgets import QApplication

from ui.workspace_file_tree import (
    AGENT_CREATED_COLOR,
    AGENT_DELETED_COLOR,
    AGENT_EDITED_COLOR,
    CHANGE_ROLE,
    KIND_ROLE,
    PATH_ROLE,
    WorkspaceFileTree,
)


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_builds_nested_tree_from_flat_entries_and_activates_files(app: QApplication) -> None:
    tree = WorkspaceFileTree()
    activated: list[str] = []
    tree.file_activated.connect(activated.append)
    tree.set_entries(
        [
            {"path": "docs/guide/start.md", "kind": "file"},
            {"path": "README.md", "kind": "file"},
        ]
    )

    docs = tree.item_for_path("docs")
    guide = tree.item_for_path("docs/guide")
    start = tree.item_for_path("docs/guide/start.md")
    root = tree.topLevelItem(0)
    assert root.text(0) == "Workspace"
    assert root.isExpanded()
    assert not root.icon(0).isNull()
    assert docs is not None and docs.data(0, KIND_ROLE) == "folder"
    assert docs.parent() is root
    assert not docs.icon(0).isNull()
    assert guide is not None and guide.parent() is docs
    assert start is not None and start.parent() is guide
    assert not start.icon(0).isNull()
    assert start.data(0, PATH_ROLE) == "docs/guide/start.md"
    assert tree.activate_path("docs/guide/start.md") is True
    assert activated == ["docs/guide/start.md"]
    assert tree.activate_path("docs") is False


def test_refresh_preserves_selection_and_each_existing_folder_state(app: QApplication) -> None:
    tree = WorkspaceFileTree()
    tree.set_entries(
        [
            {"path": "open/one.txt", "kind": "file"},
            {"path": "closed/two.txt", "kind": "file"},
        ]
    )
    assert tree.item_for_path("open") is not None
    assert tree.item_for_path("closed") is not None
    tree.item_for_path("open").setExpanded(True)  # type: ignore[union-attr]
    tree.item_for_path("closed").setExpanded(False)  # type: ignore[union-attr]
    tree.setCurrentItem(tree.item_for_path("closed/two.txt"))

    tree.set_entries(
        [
            {"path": "open/one.txt", "kind": "file", "change": "edited"},
            {"path": "closed/two.txt", "kind": "file"},
            {"path": "new/three.txt", "kind": "file"},
        ]
    )

    assert tree.current_path() == "closed/two.txt"
    assert tree.item_for_path("open").isExpanded() is True  # type: ignore[union-attr]
    assert tree.item_for_path("closed").isExpanded() is False  # type: ignore[union-attr]
    assert tree.item_for_path("new").isExpanded() is True  # type: ignore[union-attr]


def test_colors_agent_changes_and_keeps_deleted_tombstones(app: QApplication) -> None:
    tree = WorkspaceFileTree()
    tree.set_entries(
        [
            {"path": "created.png", "kind": "file", "change": "agent-created"},
            {"path": "edited.pdf", "kind": "file", "status": "updated"},
            {
                "path": "gone.txt",
                "kind": "deleted",
                "original_kind": "file",
                "tombstone": True,
            },
        ]
    )

    created = tree.item_for_path("created.png")
    edited = tree.item_for_path("edited.pdf")
    deleted = tree.item_for_path("gone.txt")
    assert QColor(created.foreground(0).color()) == AGENT_CREATED_COLOR  # type: ignore[union-attr]
    assert QColor(edited.foreground(0).color()) == AGENT_EDITED_COLOR  # type: ignore[union-attr]
    assert QColor(deleted.foreground(0).color()) == AGENT_DELETED_COLOR  # type: ignore[union-attr]
    assert deleted.data(0, CHANGE_ROLE) == "deleted"  # type: ignore[union-attr]
    assert deleted.font(0).strikeOut() is True  # type: ignore[union-attr]
    assert tree.activate_path("gone.txt") is False
    assert tree.current_file_path() == ""


def test_ignores_paths_that_are_not_inside_the_workspace(app: QApplication) -> None:
    tree = WorkspaceFileTree()
    tree.set_entries(
        [
            {"path": "../escape.txt", "kind": "file"},
            {"path": "/absolute.txt", "kind": "file"},
            {"path": "C:/host.txt", "kind": "file"},
            {"path": "safe/file.txt", "kind": "file"},
        ]
    )

    assert tree.item_for_path("../escape.txt") is None
    assert tree.item_for_path("/absolute.txt") is None
    assert tree.item_for_path("C:/host.txt") is None
    assert tree.item_for_path("safe/file.txt") is not None


def test_sorts_folders_before_files_and_supports_explorer_refresh_key(app: QApplication) -> None:
    tree = WorkspaceFileTree()
    refreshed: list[bool] = []
    tree.refresh_requested.connect(lambda: refreshed.append(True))
    tree.set_entries(
        [
            {"path": "alpha.txt", "kind": "file"},
            {"path": "z-folder/item.txt", "kind": "file"},
        ]
    )

    root = tree.topLevelItem(0)
    assert [root.child(index).text(0) for index in range(root.childCount())] == [
        "z-folder",
        "alpha.txt",
    ]
    event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F5, Qt.KeyboardModifier.NoModifier)
    tree.keyPressEvent(event)

    assert refreshed == [True]
    assert event.isAccepted()
