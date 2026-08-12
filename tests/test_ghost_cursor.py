"""Tests for passive mouse-action and collaborative-caret overlays."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor

from core.actions.interaction import Bounds
from ui.ghost_cursor import GhostCursorOverlay


def test_agent_mouse_pointer_is_compact_click_through_and_never_moves_os_cursor(qapp) -> None:
    screen = qapp.primaryScreen()
    geometry = screen.geometry()
    target = Bounds(geometry.center().x(), geometry.center().y(), 40, 30)
    cursor_before = QCursor.pos()
    overlay = GhostCursorOverlay()

    overlay.show_mouse(target, "OpenWand", pulse=True)
    qapp.processEvents()

    assert overlay.isVisible()
    assert overlay.target == target
    assert overlay.mode == "mouse"
    assert overlay.width() <= 130
    assert overlay.height() <= 52
    assert not overlay._blink_timer.isActive()
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert QCursor.pos() == cursor_before

    overlay.clear()
    qapp.processEvents()
    assert not overlay.isVisible()
    assert overlay.target is None
    assert QCursor.pos() == cursor_before
    overlay.close()


def test_agent_text_focus_uses_blinking_caret_with_openwand_agent_label(qapp) -> None:
    screen = qapp.primaryScreen()
    geometry = screen.geometry()
    target = Bounds(geometry.center().x(), geometry.center().y(), 240, 34)
    cursor_before = QCursor.pos()
    overlay = GhostCursorOverlay()

    overlay.show_text_caret(target)
    qapp.processEvents()

    assert overlay.isVisible()
    assert overlay.mode == "text"
    assert overlay.target == target
    assert overlay._label == "OpenWand agent"
    assert overlay._blink_timer.isActive()
    assert QCursor.pos() == cursor_before

    overlay.clear()
    assert not overlay._blink_timer.isActive()
    assert overlay.mode == ""
    assert QCursor.pos() == cursor_before
    overlay.close()


def test_ghost_cursor_hides_for_invalid_or_offscreen_targets(qapp) -> None:
    overlay = GhostCursorOverlay()

    overlay.show_mouse(Bounds(0, 0, 0, 0), "Invalid")
    assert not overlay.isVisible()

    overlay.show_text_caret(Bounds(10_000_000, 10_000_000, 20, 20))
    qapp.processEvents()
    assert not overlay.isVisible()
    assert overlay.target is None
    overlay.close()
