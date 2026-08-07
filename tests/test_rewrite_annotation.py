from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QSignalSpy, QTest

from ui.rewrite_annotation import RewriteAnnotationPopup, inline_diff_html


def test_inline_diff_marks_deletions_and_additions() -> None:
    rendered = inline_diff_html("This sentence are long.", "This sentence is short.")

    assert "#ff6b6b" in rendered
    assert "text-decoration:line-through" in rendered
    assert "#51cf66" in rendered
    assert "are" in rendered
    assert "is" in rendered


def test_enter_submits_then_collapses_to_balloon(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a1", selected_text="old words")
    submitted = QSignalSpy(popup.submitted)
    popup.show_composer()
    popup._comment.setPlainText("Make this clearer")

    QTest.keyClick(popup._comment, Qt.Key.Key_Return)

    assert submitted.count() == 1
    assert list(submitted.at(0)) == ["a1", "Make this clearer", False]
    assert popup.state == "processing"
    assert popup._stack.currentWidget() is popup._balloon
    assert popup._balloon_button.text() == "1"
    popup.remove()


def test_ctrl_enter_forces_document_context(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a2", selected_text="old words")
    submitted = QSignalSpy(popup.submitted)
    popup.show_composer()
    popup._comment.setPlainText("Match the rest of the document")

    QTest.keyClick(
        popup._comment,
        Qt.Key.Key_Return,
        Qt.KeyboardModifier.ControlModifier,
    )

    assert submitted.count() == 1
    assert list(submitted.at(0)) == ["a2", "Match the rest of the document", True]
    popup.remove()


def test_processing_balloon_shows_its_comment_number(qapp) -> None:
    popup = RewriteAnnotationPopup(
        annotation_id="numbered",
        display_number=3,
        selected_text="old words",
    )

    popup.show_processing()

    assert popup._balloon_button.text() == "3"
    popup.remove()


def test_hold_stashes_without_submitting_and_sits_above_send(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="held-1", selected_text="old words")
    held = QSignalSpy(popup.held)
    submitted = QSignalSpy(popup.submitted)
    popup.show_composer()
    popup._comment.setPlainText("Make this clearer later")
    qapp.processEvents()

    assert popup._hold.y() < popup._send.y()
    popup._hold.click()

    assert held.count() == 1
    assert list(held.at(0)) == ["held-1", "Make this clearer later", False]
    assert submitted.count() == 0
    assert popup.state == "held"
    assert not popup.isVisible()
    popup.remove()


def test_close_cancels_only_after_processing_popup_is_reopened(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a3", selected_text="old words")
    declined = QSignalSpy(popup.declined)
    cancelled = QSignalSpy(popup.cancel_requested)

    popup.show_composer()
    popup._close.click()
    assert declined.count() == 1
    assert cancelled.count() == 0

    popup.show_processing()
    assert popup._stack.currentWidget() is popup._balloon
    popup._balloon_button.click()
    popup._close.click()
    assert cancelled.count() == 1
    popup.remove()


def test_proposal_expands_with_accept_decline_and_revision(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a4", selected_text="This are wrong.")
    accepted = QSignalSpy(popup.accept_requested)
    revisions = QSignalSpy(popup.revision_requested)

    popup.show_processing()
    popup.show_proposal("This is correct.")

    assert popup.state == "proposal"
    assert popup._stack.currentWidget() is popup._panel
    assert "#ff6b6b" in popup._diff.text()
    assert "#51cf66" in popup._diff.text()
    popup._accept.click()
    assert list(accepted.at(0)) == ["a4", "This is correct."]
    assert not popup.isVisible()

    # An application failure explicitly restores the same proposal so the user
    # can retry or copy it instead of leaving a dead hidden annotation.
    popup.show_proposal("This is correct.")
    popup._revision.setPlainText("Make it friendlier")
    QTest.keyClick(popup._revision, Qt.Key.Key_Return)
    assert list(revisions.at(0)) == ["a4", "Make it friendlier"]
    assert popup.state == "processing"
    popup.remove()


def test_copy_only_proposal_relabels_accept(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a5", selected_text="old")
    popup.show_proposal("new", copy_only=True)

    assert popup._accept.text() == "Copy"
    popup.remove()


def test_comment_editor_and_popup_expand_with_content(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a6", selected_text="old")
    popup.show_composer()
    qapp.processEvents()
    initial_editor_height = popup._comment.height()
    initial_popup_height = popup.height()

    popup._comment.setPlainText("\n".join(f"Detailed instruction {index}" for index in range(10)))
    qapp.processEvents()

    assert popup._comment.height() > initial_editor_height
    assert popup.height() > initial_popup_height
    assert popup._comment.height() <= 220
    assert "Enter: Send" in popup._hint.text()
    assert "Ctrl+Enter: Include document" in popup._hint.text()
    assert "Shift+Enter: New line" in popup._hint.text()
    popup.remove()


def test_composer_controls_are_inside_the_native_popup_window(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="contained", selected_text="old")
    popup.show_composer()
    qapp.processEvents()

    for widget in (popup._close, popup._comment, popup._hint, popup._hold, popup._send):
        top_left = widget.mapTo(popup, QPoint(0, 0))
        assert top_left.x() >= 0
        assert top_left.y() >= 0
        assert top_left.x() + widget.width() <= popup.width()
        assert top_left.y() + widget.height() <= popup.height()
    popup.remove()


def test_proposal_restores_popup_height_after_balloon(qapp) -> None:
    popup = RewriteAnnotationPopup(annotation_id="a7", selected_text="old words")
    popup.show_processing()
    assert popup.height() == 44

    popup.show_proposal("new words")
    qapp.processEvents()

    assert popup.height() > 44
    assert popup.width() == 390
    popup.remove()


def test_popup_anchors_beside_captured_selection(qapp) -> None:
    popup = RewriteAnnotationPopup(
        annotation_id="a8",
        selected_text="selected words",
        selection_rect={"left": 100, "top": 120, "width": 80, "height": 20},
    )

    popup.show_composer()
    qapp.processEvents()

    assert popup.x() == 190
    assert popup.y() == 108
    popup.remove()


def test_processing_balloon_keeps_the_composer_anchor_side(qapp) -> None:
    available = qapp.primaryScreen().availableGeometry()
    selection = QRect(available.right() - 90, available.top() + 160, 70, 20)
    popup = RewriteAnnotationPopup(
        annotation_id="edge-anchor",
        selected_text="selected words",
        selection_rect={
            "left": selection.left(),
            "top": selection.top(),
            "width": selection.width(),
            "height": selection.height(),
        },
    )

    popup.show_composer()
    qapp.processEvents()
    assert popup.geometry().right() < selection.left()

    popup.show_processing()
    qapp.processEvents()
    assert popup.geometry().right() < selection.left()
    assert popup.geometry().right() == selection.left() - 11
    popup.remove()


def test_accept_and_decline_hide_proposals_immediately(qapp) -> None:
    accepted_popup = RewriteAnnotationPopup(annotation_id="accept-now", selected_text="old")
    accepted = QSignalSpy(accepted_popup.accept_requested)
    accepted_popup.show_proposal("two words")
    qapp.processEvents()
    accepted_popup._accept.click()

    assert accepted.count() == 1
    assert not accepted_popup.isVisible()

    declined_popup = RewriteAnnotationPopup(annotation_id="decline-now", selected_text="old")
    declined = QSignalSpy(declined_popup.declined)
    declined_popup.show_proposal("two words")
    qapp.processEvents()
    declined_popup._decline.click()

    assert declined.count() == 1
    assert not declined_popup.isVisible()
    accepted_popup.remove()
    declined_popup.remove()


def test_selection_anchor_follows_source_window_movement(qapp) -> None:
    popup = RewriteAnnotationPopup(
        annotation_id="a9",
        selected_text="selected words",
        selection_rect={"left": 100, "top": 120, "width": 80, "height": 20},
    )

    first = popup._selection_anchor_for_source(QRect(20, 30, 800, 600))
    moved = popup._selection_anchor_for_source(QRect(70, 75, 800, 600))

    assert first == QRect(100, 120, 80, 20)
    assert moved == QRect(150, 165, 80, 20)
    popup.remove()


def test_selection_anchor_follows_scroll_and_hides_when_offscreen(qapp) -> None:
    popup = RewriteAnnotationPopup(
        annotation_id="scroll-anchor",
        selected_text="selected words",
        selection_rect={"left": 100, "top": 120, "width": 80, "height": 20},
    )
    popup.show_composer()
    qapp.processEvents()
    first = popup.pos()

    popup.update_selection_anchor(
        {"left": 100, "top": 200, "width": 80, "height": 20},
        visible=True,
    )
    qapp.processEvents()
    assert popup.y() == first.y() + 80

    popup.update_selection_anchor(None, visible=False)
    qapp.processEvents()
    assert not popup.isVisible()

    popup.update_selection_anchor(
        {"left": 100, "top": 140, "width": 80, "height": 20},
        visible=True,
    )
    qapp.processEvents()
    assert popup.isVisible()
    assert popup.y() == 128
    popup.remove()


def test_processing_balloon_follows_scroll_hides_and_reappears(qapp) -> None:
    popup = RewriteAnnotationPopup(
        annotation_id="scroll-balloon",
        display_number=4,
        selected_text="selected words",
        selection_rect={"left": 180, "top": 260, "width": 90, "height": 20},
    )
    popup.show_composer()
    popup.show_processing()
    qapp.processEvents()
    first = popup.pos()

    popup.update_selection_anchor(
        {"left": 180, "top": 180, "width": 90, "height": 20},
        visible=True,
    )
    qapp.processEvents()
    assert popup.state == "processing"
    assert popup._stack.currentWidget() is popup._balloon
    assert popup._balloon_button.text() == "4"
    assert popup.y() == first.y() - 80

    popup.update_selection_anchor(None, visible=False)
    qapp.processEvents()
    assert not popup.isVisible()

    popup.update_selection_anchor(
        {"left": 180, "top": 220, "width": 90, "height": 20},
        visible=True,
    )
    qapp.processEvents()
    assert popup.isVisible()
    assert popup.state == "processing"
    assert popup._stack.currentWidget() is popup._balloon
    assert popup.y() == first.y() - 40
    popup.remove()
