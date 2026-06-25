"""Chunk timeline bar for per-segment understanding evidence."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


@dataclass(frozen=True)
class ChunkTimelineSegment:
    start_sec: float
    end_sec: float
    state: str = "pending"  # pending | ready | generating


class ChunkTimelineWidget(QWidget):
    chunk_clicked = Signal(int)
    chunk_double_clicked = Signal(int)

    _COLOR_PENDING = QColor("#C9A227")
    _COLOR_READY = QColor("#3DAA6D")
    _COLOR_EMPTY = QColor("#4A4A4A")
    _COLOR_TRACK = QColor("#1E1E1E")
    _COLOR_TRACK_BORDER = QColor("#3A3A3A")
    _COLOR_SEPARATOR = QColor("#0F0F0F")
    _COLOR_SELECTED = QColor("#FFFFFF")
    _COLOR_ACTIVE = QColor("#FFE08A")

    _SEGMENT_GAP = 3
    _OUTER_RADIUS = 6
    _INNER_RADIUS = 3
    _MIN_SEGMENT_WIDTH = 4
    _TRACK_VERTICAL_INSET = 2
    _TRACK_INNER_PADDING = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(32)
        self.setMinimumWidth(480)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._segments: list[ChunkTimelineSegment] = []
        self._segment_rects: list[tuple[int, int, int, int]] = []
        self._selected_index = -1
        self._generating_index = -1
        self._duration_sec = 0.0

    def set_segments(self, segments: list[ChunkTimelineSegment], *, duration_sec: float = 0.0):
        self._segments = list(segments or [])
        if duration_sec > 0:
            self._duration_sec = float(duration_sec)
        elif self._segments:
            self._duration_sec = max(float(item.end_sec) for item in self._segments)
        else:
            self._duration_sec = 0.0
        if self._selected_index >= len(self._segments):
            self._selected_index = len(self._segments) - 1
        self._segment_rects = []
        self.update()

    def set_selected_index(self, index: int):
        self._selected_index = int(index)
        self.update()

    def selected_index(self) -> int:
        return self._selected_index

    def set_generating_index(self, index: int):
        self._generating_index = int(index)
        self.update()

    def set_segment_state(self, index: int, state: str):
        if index < 0 or index >= len(self._segments):
            return
        current = self._segments[index]
        self._segments[index] = ChunkTimelineSegment(
            start_sec=current.start_sec,
            end_sec=current.end_sec,
            state=str(state or "pending"),
        )
        self.update()

    def segment_count(self) -> int:
        return len(self._segments)

    def _track_rect(self):
        inset = self._TRACK_VERTICAL_INSET
        return self.rect().adjusted(0, inset, 0, -inset)

    def _compute_segment_rects(self, track_rect):
        count = len(self._segments)
        if count <= 0 or self._duration_sec <= 0:
            return []

        pad = self._TRACK_INNER_PADDING
        inner = track_rect.adjusted(pad, pad, -pad, -pad)
        total_width = max(inner.width(), 1)
        gap_total = self._SEGMENT_GAP * max(count - 1, 0)
        usable_width = max(total_width - gap_total, count * self._MIN_SEGMENT_WIDTH)

        spans = [
            max(float(segment.end_sec) - float(segment.start_sec), 0.001)
            for segment in self._segments
        ]
        duration = max(self._duration_sec, sum(spans))

        raw_widths = [usable_width * (span / duration) for span in spans]
        widths = [max(self._MIN_SEGMENT_WIDTH, int(round(width))) for width in raw_widths]
        width_delta = usable_width - sum(widths)
        if widths:
            widths[-1] = max(self._MIN_SEGMENT_WIDTH, widths[-1] + width_delta)

        rects: list[tuple[int, int, int, int]] = []
        x = inner.left()
        height = inner.height()
        top = inner.top()
        for index, width in enumerate(widths):
            rects.append((x, top, width, height))
            x += width
            if index < count - 1:
                x += self._SEGMENT_GAP
        return rects

    def _segment_color(self, segment: ChunkTimelineSegment, index: int) -> QColor:
        if segment.state == "ready":
            return self._COLOR_READY
        if segment.state == "pending" or segment.state == "generating":
            return self._COLOR_PENDING
        return self._COLOR_EMPTY

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track_rect = self._track_rect()

        painter.setPen(QPen(self._COLOR_TRACK_BORDER, 1))
        painter.setBrush(self._COLOR_TRACK)
        painter.drawRoundedRect(track_rect, self._OUTER_RADIUS, self._OUTER_RADIUS)

        if not self._segments or self._duration_sec <= 0:
            painter.setPen(QPen(QColor("#777777")))
            painter.drawText(track_rect, Qt.AlignmentFlag.AlignCenter, "—")
            painter.end()
            return

        self._segment_rects = self._compute_segment_rects(track_rect)
        for index, segment in enumerate(self._segments):
            if index >= len(self._segment_rects):
                break
            x, y, width, height = self._segment_rects[index]
            segment_rect = track_rect.__class__(x, y, width, height)
            color = self._segment_color(segment, index)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(segment_rect, self._INNER_RADIUS, self._INNER_RADIUS)

            if index < len(self._segments) - 1:
                separator_x = x + width
                painter.fillRect(
                    separator_x,
                    y + 1,
                    self._SEGMENT_GAP,
                    max(height - 2, 1),
                    self._COLOR_SEPARATOR,
                )

            if index == self._generating_index and segment.state != "ready":
                painter.setPen(QPen(self._COLOR_ACTIVE, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(segment_rect.adjusted(1, 1, -1, -1), self._INNER_RADIUS, self._INNER_RADIUS)
            elif index == self._selected_index:
                painter.setPen(QPen(self._COLOR_SELECTED, 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(segment_rect.adjusted(1, 1, -1, -1), self._INNER_RADIUS, self._INNER_RADIUS)

        painter.end()

    def _index_at_position(self, point) -> int:
        if not self._segment_rects:
            self._segment_rects = self._compute_segment_rects(self._track_rect())
        for index, (x, y, width, height) in enumerate(self._segment_rects):
            rect = self._track_rect().__class__(x, y, width, height)
            if rect.contains(point):
                return index
        return -1

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self._segments:
            super().mousePressEvent(event)
            return
        selected = self._index_at_position(event.position().toPoint())
        if selected < 0:
            super().mousePressEvent(event)
            return
        self._selected_index = selected
        self.update()
        self.chunk_clicked.emit(selected)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self._segments:
            super().mouseDoubleClickEvent(event)
            return
        selected = self._index_at_position(event.position().toPoint())
        if selected < 0:
            super().mouseDoubleClickEvent(event)
            return
        self._selected_index = selected
        self.update()
        self.chunk_clicked.emit(selected)
        self.chunk_double_clicked.emit(selected)
        event.accept()
