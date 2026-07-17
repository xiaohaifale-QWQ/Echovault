"""Interactive waveform timeline used by the audio editing workspace."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class AudioTimeline(QWidget):
    """Waveform editor surface with playhead, range selection, ruler and zoom."""

    seek_requested = pyqtSignal(float)
    selection_changed = pyqtSignal(float, float)
    view_changed = pyqtSignal(float, float)

    RULER_HEIGHT = 30

    def __init__(self, parent=None):
        super().__init__(parent)
        self.peaks: list[tuple[float, float]] = []
        self.duration_seconds = 0.0
        self.playhead_seconds = 0.0
        self.selection_start = 0.0
        self.selection_end = 0.0
        self.view_start = 0.0
        self.view_end = 1.0
        self._drag_anchor: float | None = None
        self._dragging = False
        self.interaction_enabled = True
        self.waveform_color = QColor("#4A90D9")
        self.waveform_edge_color = QColor("#236FB5")
        self.setMinimumHeight(280)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.IBeamCursor)

    def set_interaction_enabled(self, enabled: bool) -> None:
        self.interaction_enabled = bool(enabled)
        self.setCursor(
            Qt.CursorShape.IBeamCursor
            if self.interaction_enabled
            else Qt.CursorShape.ArrowCursor
        )

    def set_waveform_color(self, color: str) -> None:
        self.waveform_color = QColor(color)
        self.waveform_edge_color = self.waveform_color.darker(125)
        self.update()

    def set_audio(
        self,
        peaks: list[tuple[float, float]],
        duration_seconds: float,
    ) -> None:
        self.peaks = list(peaks)
        self.duration_seconds = max(0.0, float(duration_seconds))
        self.playhead_seconds = 0.0
        self.selection_start = 0.0
        self.selection_end = 0.0
        self.view_start = 0.0
        self.view_end = 1.0
        self.selection_changed.emit(0.0, 0.0)
        self.view_changed.emit(self.view_start, self.view_end)
        self.update()

    def set_loading(self) -> None:
        self.peaks = []
        self.update()

    def set_playhead_seconds(self, seconds: float) -> None:
        self.playhead_seconds = max(0.0, min(self.duration_seconds, float(seconds)))
        self.update()

    def set_selection_seconds(self, start: float, end: float, *, emit=True) -> None:
        start = max(0.0, min(self.duration_seconds, float(start)))
        end = max(0.0, min(self.duration_seconds, float(end)))
        self.selection_start, self.selection_end = sorted((start, end))
        if emit:
            self.selection_changed.emit(self.selection_start, self.selection_end)
        self.update()

    def clear_selection(self) -> None:
        self.set_selection_seconds(0.0, 0.0)

    def select_all(self) -> None:
        self.set_selection_seconds(0.0, self.duration_seconds)

    def has_selection(self) -> bool:
        return self.selection_end - self.selection_start > 0.001

    def set_view(self, start_ratio: float, end_ratio: float) -> None:
        start = max(0.0, min(1.0, float(start_ratio)))
        end = max(start + 0.01, min(1.0, float(end_ratio)))
        if end > 1.0:
            start = max(0.0, start - (end - 1.0))
            end = 1.0
        self.view_start, self.view_end = start, end
        self.view_changed.emit(start, end)
        self.update()

    def zoom(self, factor: float, center_seconds: float | None = None) -> None:
        if self.duration_seconds <= 0:
            return
        span = self.view_end - self.view_start
        new_span = max(0.02, min(1.0, span * float(factor)))
        center = (
            self.playhead_seconds / self.duration_seconds
            if center_seconds is None
            else float(center_seconds) / self.duration_seconds
        )
        center = max(self.view_start, min(self.view_end, center))
        relative = (center - self.view_start) / max(span, 0.001)
        start = center - relative * new_span
        start = max(0.0, min(1.0 - new_span, start))
        self.set_view(start, start + new_span)

    def zoom_to_selection(self) -> None:
        if not self.has_selection() or self.duration_seconds <= 0:
            return
        start = self.selection_start / self.duration_seconds
        end = self.selection_end / self.duration_seconds
        padding = max(0.005, (end - start) * 0.08)
        self.set_view(max(0.0, start - padding), min(1.0, end + padding))

    def show_all(self) -> None:
        self.set_view(0.0, 1.0)

    def _wave_rect(self) -> QRectF:
        return QRectF(0, self.RULER_HEIGHT, self.width(), self.height() - self.RULER_HEIGHT)

    def _seconds_at_x(self, x: float) -> float:
        ratio = max(0.0, min(1.0, x / max(self.width() - 1, 1)))
        absolute = self.view_start + ratio * (self.view_end - self.view_start)
        return absolute * self.duration_seconds

    def _x_at_seconds(self, seconds: float) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        ratio = seconds / self.duration_seconds
        visible = (ratio - self.view_start) / max(self.view_end - self.view_start, 0.001)
        return visible * self.width()

    def mousePressEvent(self, event) -> None:
        if (
            self.interaction_enabled
            and
            event.button() == Qt.MouseButton.LeftButton
            and event.position().y() >= self.RULER_HEIGHT
        ):
            self._drag_anchor = self._seconds_at_x(event.position().x())
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            self.interaction_enabled
            and self._drag_anchor is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            current = self._seconds_at_x(event.position().x())
            if abs(current - self._drag_anchor) > max(0.02, self.duration_seconds * 0.001):
                self._dragging = True
                self.set_selection_seconds(self._drag_anchor, current)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if (
            self.interaction_enabled
            and event.button() == Qt.MouseButton.LeftButton
            and self._drag_anchor is not None
        ):
            current = self._seconds_at_x(event.position().x())
            if self._dragging:
                self.set_selection_seconds(self._drag_anchor, current)
            else:
                self.set_playhead_seconds(current)
                self.seek_requested.emit(current)
            self._drag_anchor = None
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        if not self.interaction_enabled or self.duration_seconds <= 0:
            return super().wheelEvent(event)
        center = self._seconds_at_x(event.position().x())
        self.zoom(0.8 if event.angleDelta().y() > 0 else 1.25, center)
        event.accept()

    @staticmethod
    def _tick_step(visible_seconds: float) -> float:
        target = max(0.01, visible_seconds / 8.0)
        magnitude = 10 ** math.floor(math.log10(target))
        for multiplier in (1, 2, 5, 10):
            step = magnitude * multiplier
            if step >= target:
                return step
        return magnitude * 10

    @staticmethod
    def _time_text(seconds: float) -> str:
        milliseconds = int(round(max(0.0, seconds) * 1000))
        minutes, remainder = divmod(milliseconds, 60_000)
        secs, millis = divmod(remainder, 1000)
        return f"{minutes}:{secs:02d}.{millis:03d}" if millis else f"{minutes}:{secs:02d}"

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        wave_rect = self._wave_rect()
        painter.fillRect(wave_rect, QColor("#F5F8FC"))

        visible_start = self.view_start * self.duration_seconds
        visible_end = self.view_end * self.duration_seconds
        visible_seconds = max(0.001, visible_end - visible_start)
        step = self._tick_step(visible_seconds)
        tick = math.floor(visible_start / step) * step
        metrics = QFontMetrics(painter.font())
        while tick <= visible_end + step:
            x = self._x_at_seconds(tick)
            painter.setPen(QPen(QColor("#DCE4EF"), 1))
            painter.drawLine(int(x), self.RULER_HEIGHT, int(x), self.height())
            painter.setPen(QColor("#64748B"))
            label = self._time_text(tick)
            painter.drawText(int(x + 4), 19, label)
            tick += step
        painter.setPen(QPen(QColor("#CBD5E1"), 1))
        painter.drawLine(0, self.RULER_HEIGHT - 1, self.width(), self.RULER_HEIGHT - 1)

        if self.has_selection():
            left = self._x_at_seconds(self.selection_start)
            right = self._x_at_seconds(self.selection_end)
            selection = QRectF(left, wave_rect.top(), right - left, wave_rect.height())
            painter.fillRect(selection, QColor(47, 125, 209, 42))
            painter.setPen(QPen(QColor("#2F7DD1"), 1))
            painter.drawLine(int(left), int(wave_rect.top()), int(left), self.height())
            painter.drawLine(int(right), int(wave_rect.top()), int(right), self.height())

        center = wave_rect.center().y()
        painter.setPen(QPen(QColor("#C7D2E0"), 1))
        painter.drawLine(0, int(center), self.width(), int(center))
        if self.peaks:
            start_index = int(self.view_start * len(self.peaks))
            end_index = max(start_index + 1, int(math.ceil(self.view_end * len(self.peaks))))
            visible = self.peaks[start_index:end_index]
            top_path = QPainterPath()
            bottom_path = QPainterPath()
            amplitude_height = max(1.0, wave_rect.height() / 2 - 14)
            for index, (low, high) in enumerate(visible):
                x = index * self.width() / max(len(visible) - 1, 1)
                top = center - max(0.0, high) * amplitude_height
                bottom = center - min(0.0, low) * amplitude_height
                if index == 0:
                    top_path.moveTo(QPointF(x, top))
                    bottom_path.moveTo(QPointF(x, bottom))
                else:
                    top_path.lineTo(QPointF(x, top))
                    bottom_path.lineTo(QPointF(x, bottom))
            fill = QPainterPath(top_path)
            for index in range(len(visible) - 1, -1, -1):
                x = index * self.width() / max(len(visible) - 1, 1)
                low = visible[index][0]
                fill.lineTo(QPointF(x, center - min(0.0, low) * amplitude_height))
            fill.closeSubpath()
            painter.fillPath(fill, self.waveform_color)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(QPen(self.waveform_edge_color, 1))
            painter.drawPath(top_path)
            painter.drawPath(bottom_path)
        else:
            painter.setPen(QColor("#7B8796"))
            message = "正在生成波形…" if self.duration_seconds else "请选择音频或视频素材"
            width = metrics.horizontalAdvance(message)
            painter.drawText(int((self.width() - width) / 2), int(center), message)

        playhead_x = self._x_at_seconds(self.playhead_seconds)
        painter.setPen(QPen(QColor("#D64545"), 2))
        painter.drawLine(
            int(playhead_x), self.RULER_HEIGHT, int(playhead_x), self.height()
        )
