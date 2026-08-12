from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from ui import virtual_workspace_window as workspace_window_mod
from ui import workspace_activity as activity_mod
from ui.workspace_activity import (
    OPENWAND_ACTIVITY_STYLE,
    WorkspaceActivityItem,
    WorkspaceActivityList,
)


def test_activity_is_compact_and_detail_is_hidden_initially(qapp) -> None:
    item = WorkspaceActivityItem(
        "step-1",
        timestamp="12:04:02",
        kind="file",
        status="running",
        summary="Writing report.md",
        detail="Full internal detail\nwith another line",
    )
    item.show()
    qapp.processEvents()
    assert not item.expanded
    assert item.detail_label.isHidden()
    assert item.header.layout().count() == 2
    assert item.header.summary_label.text() == "Writing report.md"
    item.deleteLater()


def test_click_toggles_full_detail(qapp) -> None:
    item = WorkspaceActivityItem("step-1", summary="Summary", detail="Long detail")
    item.resize(420, item.sizeHint().height())
    item.show()
    qapp.processEvents()
    QTest.mouseClick(item.header, Qt.MouseButton.LeftButton)
    assert item.expanded
    assert not item.detail_label.isHidden()
    assert item.detail_label.text() == "Long detail"
    QTest.mouseClick(item.header, Qt.MouseButton.LeftButton)
    assert not item.expanded
    item.deleteLater()


def test_keyboard_toggles_full_detail(qapp) -> None:
    item = WorkspaceActivityItem("step-1", summary="Summary", detail="Detail")
    item.show()
    item.header.setFocus()
    QTest.keyClick(item.header, Qt.Key.Key_Space)
    assert item.expanded
    item.deleteLater()


def test_upsert_updates_same_item_and_preserves_expansion(qapp) -> None:
    feed = WorkspaceActivityList()
    original = feed.upsert("call-7", summary="Calling tool", detail="request", status="running")
    original.set_expanded(True)
    updated = feed.upsert("call-7", summary="Tool finished", detail="response", status="complete")
    assert updated is original
    assert feed.count == 1
    assert updated.expanded
    assert updated.summary == "Tool finished"
    assert updated.detail == "response"
    assert updated.property("activityStatus") == "complete"
    feed.deleteLater()


def test_activity_translates_metadata_but_preserves_style_properties(qapp, monkeypatch) -> None:
    translations = {"model reply": "réponse du modèle", "complete": "terminé"}
    monkeypatch.setattr(activity_mod, "t", lambda text: translations.get(text, text))
    item = WorkspaceActivityItem(
        "translated",
        summary="Runtime summary",
        kind="model reply",
        status="complete",
    )
    assert item.header.kind_label.text() == "réponse du modèle"
    assert item.header.status_label.text() == "terminé"
    assert item.property("activityKind") == "model reply"
    assert item.property("activityStatus") == "complete"
    item.deleteLater()


def test_workspace_journal_messages_translate_known_templates(monkeypatch) -> None:
    translations = {
        "You renamed {old} to {new}": "RENAMED {old} TO {new}",
        "Workspace started": "STARTED",
    }
    monkeypatch.setattr(
        workspace_window_mod,
        "t",
        lambda text: translations.get(text, text),
    )
    assert workspace_window_mod._translate_operation_message("Workspace started") == "STARTED"
    assert (
        workspace_window_mod._translate_operation_message("You renamed old.txt to new.txt")
        == "RENAMED old.txt TO new.txt"
    )
    assert workspace_window_mod._translate_operation_message("Custom runtime detail") == "Custom runtime detail"


def test_newest_entries_are_visually_first(qapp) -> None:
    feed = WorkspaceActivityList(newest_first=True)
    first = feed.upsert("one", summary="First")
    second = feed.upsert("two", summary="Second")
    assert feed.ids == ("one", "two")
    assert feed._layout.itemAt(0).widget() is second
    assert feed._layout.itemAt(1).widget() is first
    feed.deleteLater()


def test_remove_clear_and_expand_only(qapp) -> None:
    feed = WorkspaceActivityList()
    first = feed.upsert("one", summary="First")
    second = feed.upsert("two", summary="Second")
    feed.expand_only(["one"])
    assert first.expanded
    assert not second.expanded
    assert feed.remove_activity("missing") is False
    assert feed.remove_activity("one") is True
    assert feed.item("one") is None
    feed.clear_activities()
    assert feed.count == 0
    feed.deleteLater()


def test_plain_text_and_dark_style_hooks(qapp) -> None:
    item = WorkspaceActivityItem(
        "safe",
        summary="<b>not markup</b>",
        detail="<script>not executable</script>",
        kind="Tool",
        status="Failed",
    )
    assert item.summary == "<b>not markup</b>"
    assert item.detail == "<script>not executable</script>"
    assert item.property("activityKind") == "tool"
    assert item.property("activityStatus") == "failed"
    assert "workspaceActivityItem" in OPENWAND_ACTIVITY_STYLE
    assert 'activityStatus="failed"' in OPENWAND_ACTIVITY_STYLE
    item.deleteLater()


def test_empty_stable_id_is_rejected(qapp) -> None:
    feed = WorkspaceActivityList()
    with pytest.raises(ValueError):
        feed.upsert("  ", summary="No id")
    with pytest.raises(ValueError):
        feed.upsert("x" * 161, summary="Too long")
    feed.deleteLater()
