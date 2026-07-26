"""Real-entry acceptance for the floating icon and tray shell."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.workflow


def _close_overlay(overlay, qapp) -> None:
    overlay._bubble.clear()
    overlay._context_panel.close()
    overlay._provider_badge.close()
    overlay._icon_label.close()
    overlay.close()
    qapp.processEvents()


def test_icon_states_drag_autohide_and_real_tray_visibility_toggle(qapp, monkeypatch) -> None:
    """Drive the production icon signal, mouse, timer, and tray QAction paths."""
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt

    import config
    import ui.overlay as overlay_module
    from ui.overlay import IconOverlay, OverlaySignals

    class MouseEvent:
        def __init__(self, event_type, point, *, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.NoButton):
            self._event_type = event_type
            self._point = QPointF(point)
            self._button = button
            self._buttons = buttons

        def type(self):
            return self._event_type

        def globalPosition(self):
            return self._point

        def position(self):
            return self._point

        def button(self):
            return self._button

        def buttons(self):
            return self._buttons

    monkeypatch.setattr(IconOverlay, "_pin_overlay_windows", lambda _self: None)
    monkeypatch.setattr(overlay_module, "is_wayland", lambda: False)
    monkeypatch.setattr(overlay_module, "start_wayland_system_move", lambda _widget: False)
    monkeypatch.setattr(config, "ICON_AUTO_HIDE", False)
    signals = OverlaySignals()
    overlay = IconOverlay(signals)
    try:
        for auto_hide in (False, True):
            monkeypatch.setattr(config, "ICON_AUTO_HIDE", auto_hide)
            for state in ("idle", "listening", "thinking", "speaking"):
                overlay._icon_label.hide() if auto_hide else overlay._icon_label.show()
                signals.set_state.emit(state)
                qapp.processEvents()
                assert overlay._current_state == state
                assert state in overlay._state_icons
                assert overlay._icon_label.pixmap() is not None
                assert overlay._icon_label.isVisible() is (not auto_hide or state != "idle")

        monkeypatch.setattr(config, "ICON_AUTO_HIDE", False)

        original = overlay._icon_label.pos()
        provider_original = overlay._provider_badge.pos()
        panel_original = overlay._context_panel.pos()
        press_global = original + QPoint(12, 12)
        destination = press_global + QPoint(90, -45)
        assert overlay.eventFilter(
            overlay._icon_label,
            MouseEvent(QEvent.Type.MouseButtonPress, press_global, button=Qt.MouseButton.LeftButton),
        )
        assert overlay.eventFilter(
            overlay._icon_label,
            MouseEvent(QEvent.Type.MouseMove, destination, buttons=Qt.MouseButton.LeftButton),
        )
        assert overlay.eventFilter(
            overlay._icon_label,
            MouseEvent(QEvent.Type.MouseButtonRelease, destination, button=Qt.MouseButton.LeftButton),
        )
        assert overlay._icon_label.pos() == original + QPoint(90, -45)
        assert overlay._provider_badge.pos() != provider_original
        assert overlay._context_panel.pos() != panel_original

        toggle = overlay._icon_toggle_action
        assert overlay._icon_label.isVisible()
        toggle.trigger()
        qapp.processEvents()
        assert not overlay._icon_label.isVisible()
        overlay._sync_icon_toggle_text()
        assert toggle.text() == "Show icon"
        toggle.trigger()
        qapp.processEvents()
        assert overlay._icon_label.isVisible()

        monkeypatch.setattr(config, "ICON_AUTO_HIDE", True)
        signals.set_state.emit("listening")
        qapp.processEvents()
        assert overlay._icon_label.isVisible()
        signals.hide_icon.emit()
        assert overlay._icon_hide_timer.isActive()
        overlay._on_icon_hide_timeout()
        assert not overlay._icon_label.isVisible()
    finally:
        _close_overlay(overlay, qapp)


def test_real_icon_drop_event_adds_text_and_image_context(qapp, tmp_path, monkeypatch) -> None:
    """A real Qt drag/drop gesture must reach the production context signal."""

    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
    from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage
    from PySide6.QtWidgets import QApplication

    import ui.drop_zone as drop_zone
    from ui.overlay import IconOverlay, OverlaySignals

    text_path = tmp_path / "notes.txt"
    text_path.write_text("dropped notes", encoding="utf-8")
    image_path = tmp_path / "pixel.png"
    image = QImage(2, 2, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(image_path), "PNG")

    monkeypatch.setattr(IconOverlay, "_pin_overlay_windows", lambda _self: None)
    # The particle/toast cosmetics are not part of context extraction/routing
    # and would otherwise leave animation windows alive past this assertion.
    monkeypatch.setattr(drop_zone, "VanishEffect", lambda _point: None)
    monkeypatch.setattr(drop_zone, "AddedContextToast", lambda _point, _size: None)
    signals = OverlaySignals()
    dropped: list[list[tuple[str, str, str]]] = []
    signals.context_items_dropped.connect(dropped.append)
    overlay = IconOverlay(signals)
    try:
        overlay.show()
        overlay._icon_label.show()
        qapp.processEvents()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(text_path)), QUrl.fromLocalFile(str(image_path))])
        drag = QDragEnterEvent(
            QPoint(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        drop = QDropEvent(
            QPointF(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        QApplication.sendEvent(overlay._icon_label, drag)
        QApplication.sendEvent(overlay._icon_label, drop)
        qapp.processEvents()

        assert drag.isAccepted() and drop.isAccepted()
        assert len(dropped) == 1
        by_name = {name: (content, item_type) for name, content, item_type in dropped[0]}
        assert by_name["notes.txt"] == ("dropped notes", "text")
        assert by_name["pixel.png"][1] == "image"
        assert by_name["pixel.png"][0]
        assert len(overlay._context_panel._badges) == 2
    finally:
        _close_overlay(overlay, qapp)
