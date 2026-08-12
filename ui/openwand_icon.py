"""Animated OpenWand logo used by the floating overlay."""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QRectF, QTimer
from PySide6.QtGui import QImageReader, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGraphicsObject, QLabel, QWidget


class SpeakingRippleGraphicsItem(QGraphicsObject):
    """Play the speaking ripple behind a graphics-scene item."""

    def __init__(self, size: float = 250.0, parent=None) -> None:
        super().__init__(parent)
        self._size = float(size)
        self._frames: tuple[QPixmap, ...] = ()
        self._frame = 0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._advance)

    @property
    def uses_vfx_assets(self) -> bool:
        return bool(self._frames)

    @property
    def animation_state(self) -> str:
        return "speaking" if self._timer.isActive() else "idle"

    def set_vfx_sources(self, directory: str) -> bool:
        self._frames = OpenWandIconLabel._load_animation(
            Path(directory) / "speaking-ripple.webp"
        )
        self._frame = 0
        self.update()
        return self.uses_vfx_assets

    def start(self) -> None:
        if self._frames:
            self._timer.start()
            self.update()

    def stop(self) -> None:
        self._timer.stop()
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API override
        return QRectF(0.0, 0.0, self._size, self._size)

    def paint(self, painter: QPainter, _option, _widget=None) -> None:
        if not self._frames:
            return
        frame = self._frames[self._frame % len(self._frames)]
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(0.32)
        painter.drawPixmap(self.boundingRect(), frame, QRectF(frame.rect()))
        painter.restore()

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % max(1, len(self._frames))
        self.update()


class OpenWandIconLabel(QLabel):
    """Paint the OpenWand mark and its restrained state feedback.

    The logo stays vector. A finished third-party animation supplies the
    center-out speaking ripple; runtime code only plays and places its frames.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source_pixmap = QPixmap()
        self._svg_renderer: QSvgRenderer | None = None
        self._ripple_frames: tuple[QPixmap, ...] = ()
        self._asset_frame = 0
        self._state = "idle"
        self._phase = 0.0
        self._amplitude = 0.0
        self._target_amplitude = 0.0
        self._last_audio_amplitude = 0.0
        self._animation_timer = QTimer(self)
        self._animation_timer.setInterval(40)  # 25 fps is ample for a 60 px overlay.
        self._animation_timer.timeout.connect(self._advance_animation)

    @property
    def animation_state(self) -> str:
        """Expose the current visual state for diagnostics and tests."""
        return self._state

    @property
    def audio_amplitude(self) -> float:
        """Return the most recent normalized audio input."""
        return self._last_audio_amplitude

    @property
    def uses_vector_source(self) -> bool:
        """Return whether the logo is currently rendered from a valid SVG."""
        return self._svg_renderer is not None and self._svg_renderer.isValid()

    @property
    def uses_vfx_assets(self) -> bool:
        """Return whether the licensed speaking ripple loaded successfully."""
        return bool(self._ripple_frames)

    def set_vector_source(self, path: str) -> bool:
        """Load the primary SVG artwork, retaining the pixmap as a fallback."""
        renderer = QSvgRenderer(path, self)
        if not renderer.isValid():
            renderer.deleteLater()
            self._svg_renderer = None
            self.update()
            return False
        old_renderer = self._svg_renderer
        self._svg_renderer = renderer
        if old_renderer is not None:
            old_renderer.deleteLater()
        self.update()
        return True

    def set_vfx_sources(self, directory: str) -> bool:
        """Load the finished center-out ripple animation from a folder."""
        root = Path(directory)
        self._ripple_frames = self._load_animation(root / "speaking-ripple.webp")
        self._asset_frame = 0
        self.update()
        return self.uses_vfx_assets

    @staticmethod
    def _load_animation(path: Path) -> tuple[QPixmap, ...]:
        reader = QImageReader(str(path))
        frames: list[QPixmap] = []
        while reader.canRead():
            image = reader.read()
            if image.isNull():
                break
            frames.append(QPixmap.fromImage(image))
        return tuple(frames)

    def setPixmap(self, pixmap: QPixmap) -> None:  # noqa: N802 - Qt API override
        """Keep the original artwork; scaling happens in ``paintEvent``."""
        self._source_pixmap = QPixmap(pixmap)
        self.update()

    def pixmap(self, *args, **kwargs) -> QPixmap:  # noqa: N802 - Qt API override
        """Match QLabel's public surface for callers that inspect the asset."""
        return QPixmap(self._source_pixmap)

    def set_animation_state(self, state: str) -> None:
        state = state if state in {"idle", "listening", "thinking", "speaking"} else "idle"
        if state == self._state:
            return
        self._state = state
        self._asset_frame = 0
        if state in {"thinking", "speaking"}:
            self._animation_timer.start()
        else:
            self._animation_timer.stop()
            self._amplitude = 0.0
            self._target_amplitude = 0.0
            self._last_audio_amplitude = 0.0
        self.update()

    def set_audio_amplitude(self, amplitude: float) -> None:
        """Accept a normalized PCM level; invalid input safely becomes silence."""
        try:
            value = float(amplitude)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        self._last_audio_amplitude = max(0.0, min(1.0, value))
        self._target_amplitude = self._last_audio_amplitude
        if self._state == "speaking" and not self._animation_timer.isActive():
            self._animation_timer.start()

    def _advance_animation(self) -> None:
        self._phase = (self._phase + 0.105) % (math.tau * 8)
        self._asset_frame += 1
        # Quick attack, gentle release. Audio events arrive once per PCM chunk,
        # so decay the target between chunks instead of holding a rigid meter.
        blend = 0.46 if self._target_amplitude > self._amplitude else 0.20
        self._amplitude += (self._target_amplitude - self._amplitude) * blend
        self._target_amplitude *= 0.88
        if self._amplitude < 0.002:
            self._amplitude = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API override
        if not self.uses_vector_source and self._source_pixmap.isNull():
            return super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        side = float(min(self.width(), self.height()))
        # Leave a narrow perimeter so the speaking ripple can emerge from
        # behind the opaque logo instead of being painted across its face.
        icon_rect = QRectF(side * 0.07, side * 0.07, side * 0.86, side * 0.86)

        if self._state == "speaking":
            self._paint_ripple(painter)

        self._paint_source(painter, icon_rect)

        # Keep the logo glow secondary to the white speaking ripple.
        if self._state in {"thinking", "speaking"}:
            pulse = (math.sin(self._phase) + 1.0) * 0.5
            boost = (
                0.08 + pulse * 0.07
                if self._state == "thinking"
                else 0.01 + self._amplitude * 0.035
            )
            painter.save()
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
            painter.setOpacity(boost)
            self._paint_source(painter, icon_rect)
            painter.restore()

    def _paint_source(self, painter: QPainter, target: QRectF) -> None:
        if self.uses_vector_source:
            self._svg_renderer.render(painter, target)
        else:
            painter.drawPixmap(target, self._source_pixmap, QRectF(self._source_pixmap.rect()))

    def _paint_ripple(self, painter: QPainter) -> None:
        if not self._ripple_frames:
            return
        frame = self._ripple_frames[self._asset_frame % len(self._ripple_frames)]
        painter.save()
        painter.setOpacity(0.26 + self._amplitude * 0.48)
        # The source ring occupies about 94% of its frame at maximum expansion.
        # A 146% centered canvas keeps the circle close to the widget corners
        # without letting the effect feel larger than the logo needs.
        side = float(min(self.width(), self.height()))
        ripple_side = side * 1.46
        target = QRectF(
            (self.width() - ripple_side) * 0.5,
            (self.height() - ripple_side) * 0.5,
            ripple_side,
            ripple_side,
        )
        painter.drawPixmap(target, frame, QRectF(frame.rect()))
        painter.restore()
