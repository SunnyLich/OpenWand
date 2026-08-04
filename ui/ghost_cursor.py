"""Small, passive agent pointer and collaborative text-caret indicators."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

from core.actions.interaction.contracts import Bounds

_OVERLAY_WIDTH = 126
_OVERLAY_HEIGHT = 50
_MOUSE_ANCHOR_X = 4
_MOUSE_ANCHOR_Y = 4
_CARET_ANCHOR_X = 5
_CARET_ANCHOR_Y = 25


class GhostCursorOverlay(QWidget):
    """Click-through mouse-action pointer or Google Docs-style agent caret."""

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(_OVERLAY_WIDTH, _OVERLAY_HEIGHT)
        self._label = ""
        self._target: Bounds | None = None
        self._mode = ""
        self._caret_visible = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(520)
        self._blink_timer.timeout.connect(self._toggle_caret)

    @property
    def target(self) -> Bounds | None:
        return self._target

    @property
    def mode(self) -> str:
        """Return ``mouse``, ``text``, or an empty string while hidden."""
        return self._mode

    def show_mouse(self, bounds: Bounds, label: str = "Wisp", *, pulse: bool = False) -> None:
        """Show a compact ordinary pointer only for an actual agent mouse action."""
        del pulse  # Kept for callers; the calmer pointer intentionally never pulses.
        point = self._target_point(bounds, text=False)
        if point is None:
            self.clear()
            return
        self._target = bounds
        self._mode = "mouse"
        self._label = " ".join(str(label or "Wisp").split())[:18]
        self._blink_timer.stop()
        self._caret_visible = True
        self.move(point[0] - _MOUSE_ANCHOR_X, point[1] - _MOUSE_ANCHOR_Y)
        self._show_passively()

    def show_text_caret(self, bounds: Bounds, label: str = "Wisp agent") -> None:
        """Show a blinking collaborative caret for agent text/keyboard focus."""
        point = self._target_point(bounds, text=True)
        if point is None:
            self.clear()
            return
        self._target = bounds
        self._mode = "text"
        self._label = " ".join(str(label or "Wisp agent").split())[:20]
        self._caret_visible = True
        self.move(point[0] - _CARET_ANCHOR_X, point[1] - _CARET_ANCHOR_Y)
        self._blink_timer.start()
        self._show_passively()

    def show_target(self, bounds: Bounds, label: str = "Wisp", *, pulse: bool = False) -> None:
        """Compatibility alias for callers explicitly representing mouse targeting."""
        self.show_mouse(bounds, label, pulse=pulse)

    def clear(self) -> None:
        """Hide immediately on pause, failure, cancellation, staleness, or completion."""
        self._blink_timer.stop()
        self._caret_visible = True
        self._target = None
        self._mode = ""
        self._label = ""
        self.hide()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.clear()
        super().closeEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._mode == "mouse":
            self._paint_mouse(painter)
        elif self._mode == "text":
            self._paint_text_caret(painter)
        painter.end()

    def _paint_mouse(self, painter: QPainter) -> None:
        # Familiar OS-style arrow: restrained, high contrast, and no glow.
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
        if self._label:
            width = min(88, max(42, painter.fontMetrics().horizontalAdvance(self._label) + 14))
            label_rect = QRect(24, 5, width, 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(46, 48, 55, 238))
            painter.drawRoundedRect(label_rect, 5, 5)
            painter.setPen(QColor("#f5f5f6"))
            painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Medium))
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self._label)

    def _paint_text_caret(self, painter: QPainter) -> None:
        accent = QColor("#7651c9")
        label_width = min(110, max(72, painter.fontMetrics().horizontalAdvance(self._label) + 18))
        label_rect = QRect(0, 0, label_width, 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(label_rect, 4, 4)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        painter.drawText(label_rect.adjusted(8, 0, -7, 0), Qt.AlignmentFlag.AlignVCenter, self._label)
        if self._caret_visible:
            painter.setPen(QPen(accent, 2.2))
            painter.drawLine(_CARET_ANCHOR_X, 23, _CARET_ANCHOR_X, 48)

    def _show_passively(self) -> None:
        self._apply_native_input_transparency()
        self.show()
        self.raise_()
        self.update()

    def _toggle_caret(self) -> None:
        if self._mode != "text":
            self._blink_timer.stop()
            return
        self._caret_visible = not self._caret_visible
        self.update()

    @staticmethod
    def _target_point(bounds: Bounds, *, text: bool) -> tuple[int, int] | None:
        if bounds.width <= 0 or bounds.height <= 0:
            return None
        if text:
            x = bounds.x + min(12, max(2, bounds.width // 10))
            y = bounds.y + max(13, min(bounds.height - 2, bounds.height // 2 + 9))
        else:
            x = bounds.x + bounds.width // 2
            y = bounds.y + bounds.height // 2
        if QApplication.screenAt(GhostCursorOverlay._qt_point(x, y)) is None:
            return None
        return x, y

    @staticmethod
    def _qt_point(x: int, y: int):
        from PySide6.QtCore import QPoint

        return QPoint(x, y)

    def _apply_native_input_transparency(self) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            get_window_long = user32.GetWindowLongPtrW
            set_window_long = user32.SetWindowLongPtrW
            exstyle = int(get_window_long(hwnd, -20))
            # WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_LAYERED
            set_window_long(hwnd, -20, exstyle | 0x20 | 0x80 | 0x08000000 | 0x00080000)
        except Exception:
            return


__all__ = ["GhostCursorOverlay"]
