"""Chunk timeline bar for per-segment understanding evidence."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal, QSize, QEvent
from PySide6.QtGui import QColor, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QWidget


@dataclass(frozen=True)
class ChunkTimelineSegment:
    start_sec: float
    end_sec: float
    state: str = "pending"  # pending | ready | generating


def effective_timeline_duration(
    segments: list[ChunkTimelineSegment],
    duration_sec: float = 0.0,
) -> float:
    if not segments:
        return 0.0
    spans = [
        max(float(segment.end_sec) - float(segment.start_sec), 0.001)
        for segment in segments
    ]
    chunk_end = max(float(segment.end_sec) for segment in segments)
    passed = float(duration_sec or 0.0)
    timeline_duration = chunk_end if passed <= 0 or passed > chunk_end * 1.01 else passed
    return max(timeline_duration, chunk_end, sum(spans))


def layout_segments_sequential(
    segments: list[ChunkTimelineSegment],
    *,
    duration_sec: float = 0.0,
    min_segment_width: int = 14,
    segment_gap: int = 2,
    pixels_per_second: float = 6.0,
    target_inner_width: int | None = None,
) -> tuple[list[tuple[int, int]], int]:
    """Pack segments left-to-right with uniform gaps; width follows duration.

    When ``target_inner_width`` is set (typically the visible track width), segments
    expand proportionally to fill that space instead of leaving empty track.
    """
    count = len(segments)
    if count <= 0:
        return [], 0

    duration = max(float(duration_sec or 0.0), effective_timeline_duration(segments, duration_sec))
    if duration <= 0:
        return [], 0

    min_each = max(int(min_segment_width), 1)
    gap = max(int(segment_gap), 0)
    proportional = int(round(duration * float(pixels_per_second)))
    gap_total = gap * max(count - 1, 0)
    min_total = count * min_each + gap_total
    content_width = max(proportional, min_total, 1)
    inner_width = max(content_width, int(target_inner_width or 0))

    widths = distribute_segment_widths(
        segments,
        inner_width - gap_total,
        duration_sec=duration,
        min_segment_width=min_each,
    )

    order = sorted(
        range(count),
        key=lambda index: (
            float(segments[index].start_sec),
            float(segments[index].end_sec),
        ),
    )
    placements: list[tuple[int, int] | None] = [None] * count
    cursor = 0
    for rank, index in enumerate(order):
        width = widths[index]
        if rank > 0:
            cursor += gap
        placements[index] = (cursor, width)
        cursor += width

    total_width = max(cursor, inner_width)
    resolved: list[tuple[int, int]] = []
    for item in placements:
        left, width = item or (0, min_each)
        resolved.append((left, width))
    return resolved, total_width


def distribute_segment_widths(
    segments: list[ChunkTimelineSegment],
    usable_width: int,
    *,
    duration_sec: float = 0.0,
    min_segment_width: int = 12,
) -> list[int]:
    count = len(segments)
    if count <= 0:
        return []

    spans = [
        max(float(segment.end_sec) - float(segment.start_sec), 0.001)
        for segment in segments
    ]
    duration = max(effective_timeline_duration(segments, duration_sec), sum(spans))
    min_each = max(int(min_segment_width), 1)
    min_total = count * min_each
    usable_width = max(int(usable_width), min_total)

    remaining = usable_width - min_total
    if remaining <= 0:
        base, extra = divmod(usable_width, count)
        return [base + (1 if index < extra else 0) for index in range(count)]

    raw_fractions = [remaining * (span / duration) for span in spans]
    extras = [int(value) for value in raw_fractions]
    leftover = remaining - sum(extras)
    if leftover > 0:
        ranked = sorted(
            ((raw_fractions[index] - extras[index], index) for index in range(count)),
            reverse=True,
        )
        for offset in range(leftover):
            extras[ranked[offset % count][1]] += 1
    return [min_each + extras[index] for index in range(count)]


def horizontal_scroll_to_rect(
    x: int,
    width: int,
    viewport_w: int,
    *,
    current: int = 0,
    maximum: int = 0,
    margin: int = 16,
) -> int:
    """Scrollbar value that brings ``[x, x+width]`` into a horizontal viewport."""
    viewport_w = max(1, int(viewport_w))
    x = int(x)
    width = max(1, int(width))
    margin = max(0, int(margin))
    left = x - margin
    right = x + width + margin
    visible_left = int(current)
    visible_right = visible_left + viewport_w
    if left >= visible_left and right <= visible_right:
        return int(current)
    if width + margin * 2 >= viewport_w:
        target = left
    elif left < visible_left:
        target = left
    else:
        target = right - viewport_w
    return max(0, min(int(maximum), target))


class ChunkTimelineWidget(QWidget):
    chunk_clicked = Signal(int)
    chunk_double_clicked = Signal(int)

    _SEGMENT_GAP = 2
    _OUTER_RADIUS = 8
    _INNER_RADIUS = 4
    _MIN_SEGMENT_WIDTH = 14
    _PIXELS_PER_SECOND = 6.0
    _VIEWPORT_MIN_WIDTH = 320
    _TRACK_VERTICAL_INSET = 2
    _TRACK_INNER_PADDING = 2
    _TRACK_END_PADDING = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(32)
        self.setMinimumWidth(self._VIEWPORT_MIN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self._segments: list[ChunkTimelineSegment] = []
        self._segment_rects: list[tuple[int, int, int, int]] = []
        self._selected_index = -1
        self._generating_index = -1
        self._duration_sec = 0.0

    def _theme_colors(self) -> dict[str, str]:
        try:
            from PySide6.QtWidgets import QApplication

            from ui.widgets.styles import theme_color_map

            app = QApplication.instance()
            is_dark = True
            if app is not None:
                prop = app.property("videoseek_is_dark")
                if prop is None:
                    is_dark = app.palette().color(app.palette().ColorRole.Window).lightness() < 128
                else:
                    is_dark = bool(prop)
            return theme_color_map(is_dark)
        except Exception:
            return {
                "WARN": "#C9A227",
                "SUCCESS": "#3DAA6D",
                "LINE_STRONG": "#4A4A4A",
                "TRACK": "#1E1E1E",
                "LINE": "#3A3A3A",
                "HEADLINE": "#FFFFFF",
                "MUTED": "#777777",
                "ACCENT": "#60a5fa",
            }

    def _qcolor(self, key: str, fallback: str) -> QColor:
        colors = self._theme_colors()
        return QColor(str(colors.get(key) or fallback))

    def set_segments(self, segments: list[ChunkTimelineSegment], *, duration_sec: float = 0.0):
        self._segments = list(segments or [])
        if self._segments:
            chunk_end = max(float(item.end_sec) for item in self._segments)
            passed = float(duration_sec or 0.0)
            self._duration_sec = chunk_end if passed <= 0 or passed > chunk_end * 1.01 else passed
        else:
            self._duration_sec = 0.0
        if self._selected_index >= len(self._segments):
            self._selected_index = len(self._segments) - 1
        self._segment_rects = []
        self._sync_layout_width()
        self.update()

    def set_selected_index(self, index: int):
        index = int(index)
        changed = index != self._selected_index
        self._selected_index = index
        if changed:
            self.update()
        self._scroll_index_into_view_if_needed(index)

    def selected_index(self) -> int:
        return self._selected_index

    def set_generating_index(self, index: int):
        self._generating_index = int(index)
        self.update()
        self._scroll_index_into_view_if_needed(self._generating_index)

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

    def sizeHint(self) -> QSize:
        return QSize(self._layout_width(), self.minimumHeight())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def showEvent(self, event):
        super().showEvent(event)
        viewport = self.parentWidget()
        if viewport is not None and not getattr(self, "_viewport_filter_installed", False):
            viewport.installEventFilter(self)
            self._viewport_filter_installed = True
        self._sync_layout_width()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._sync_layout_width()
        return super().eventFilter(watched, event)

    def wheelEvent(self, event: QWheelEvent):
        scroll_area = self._scroll_area()
        if scroll_area is not None:
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                bar = scroll_area.horizontalScrollBar()
                if bar is not None and bar.maximum() > 0:
                    bar.setValue(bar.value() - delta)
                    event.accept()
                    return
        super().wheelEvent(event)

    def _scroll_area(self) -> QScrollArea | None:
        viewport = self.parentWidget()
        if viewport is None:
            return None
        parent = viewport.parentWidget()
        return parent if isinstance(parent, QScrollArea) else None

    def _viewport_width(self) -> int:
        scroll_area = self._scroll_area()
        if scroll_area is not None:
            return max(int(scroll_area.viewport().width()), 0)
        return max(int(self.width()), self._VIEWPORT_MIN_WIDTH)

    def _effective_duration(self) -> float:
        return effective_timeline_duration(self._segments, self._duration_sec)

    def _compute_content_width(self) -> int:
        count = len(self._segments)
        horizontal_pad = self._TRACK_INNER_PADDING * 2 + 2
        if count <= 0 or self._effective_duration() <= 0:
            return self._VIEWPORT_MIN_WIDTH

        _placements, inner_width = layout_segments_sequential(
            self._segments,
            duration_sec=self._duration_sec,
            min_segment_width=self._MIN_SEGMENT_WIDTH,
            segment_gap=self._SEGMENT_GAP,
            pixels_per_second=self._PIXELS_PER_SECOND,
        )
        return inner_width + horizontal_pad + self._TRACK_END_PADDING

    def _distribute_segment_widths(self, usable_width: int) -> list[int]:
        return distribute_segment_widths(
            self._segments,
            usable_width,
            duration_sec=self._duration_sec,
            min_segment_width=self._MIN_SEGMENT_WIDTH,
        )

    def _layout_width(self) -> int:
        content = self._compute_content_width()
        viewport = self._viewport_width()
        if viewport > 0:
            return max(content, viewport)
        return max(content, self._VIEWPORT_MIN_WIDTH)

    def _sync_layout_width(self):
        viewport = self._viewport_width()
        content = self._compute_content_width()
        # Avoid a temporary 320px width on first show when the viewport is still 0 —
        # that causes a visible jump once the real viewport arrives.
        if viewport <= 0:
            if self.width() >= max(content, self._VIEWPORT_MIN_WIDTH):
                return
            target = max(content, self._VIEWPORT_MIN_WIDTH)
        else:
            target = max(content, viewport)
        if self.width() == target:
            return
        self.setFixedWidth(target)
        self._segment_rects = []
        self.updateGeometry()

    def _track_rect(self):
        inset = self._TRACK_VERTICAL_INSET
        return self.rect().adjusted(0, inset, 0, -inset)

    def _compute_segment_rects(self, track_rect):
        count = len(self._segments)
        if count <= 0 or self._effective_duration() <= 0:
            return []

        pad = self._TRACK_INNER_PADDING
        inner = track_rect.adjusted(pad, pad, -pad, -pad)
        placements, _total_width = layout_segments_sequential(
            self._segments,
            duration_sec=self._duration_sec,
            min_segment_width=self._MIN_SEGMENT_WIDTH,
            segment_gap=self._SEGMENT_GAP,
            pixels_per_second=self._PIXELS_PER_SECOND,
            target_inner_width=max(int(inner.width()), 1),
        )

        rects: list[tuple[int, int, int, int]] = []
        height = inner.height()
        top = inner.top()
        for left, width in placements:
            rects.append((inner.left() + left, top, width, height))
        return rects

    def _is_index_visible(self, index: int, margin: int = 8) -> bool:
        if index < 0:
            return True
        scroll_area = self._scroll_area()
        if scroll_area is None:
            return True
        if not self._segment_rects:
            self._segment_rects = self._compute_segment_rects(self._track_rect())
        if index >= len(self._segment_rects):
            return False
        x, _y, width, _height = self._segment_rects[index]
        bar = scroll_area.horizontalScrollBar()
        if bar is None:
            return True
        visible_left = int(bar.value()) + margin
        visible_right = visible_left + scroll_area.viewport().width() - margin * 2
        return x >= visible_left and (x + width) <= visible_right

    def _scroll_index_into_view_if_needed(self, index: int):
        if index < 0 or self._is_index_visible(index):
            return
        self._ensure_index_visible(index)

    def _ensure_index_visible(self, index: int):
        if index < 0:
            return
        scroll_area = self._scroll_area()
        if scroll_area is None:
            return
        if not self._segment_rects:
            self._segment_rects = self._compute_segment_rects(self._track_rect())
        if index >= len(self._segment_rects):
            return
        x, _y, width, _height = self._segment_rects[index]
        bar = scroll_area.horizontalScrollBar()
        if bar is None:
            return
        bar.setValue(
            horizontal_scroll_to_rect(
                x,
                width,
                scroll_area.viewport().width(),
                current=int(bar.value()),
                maximum=int(bar.maximum()),
            )
        )

    def _segment_color(self, segment: ChunkTimelineSegment, index: int) -> QColor:
        if segment.state == "ready":
            return self._qcolor("SUCCESS", "#3DAA6D")
        if segment.state == "pending" or segment.state == "generating":
            return self._qcolor("WARN", "#C9A227")
        return self._qcolor("LINE_STRONG", "#4A4A4A")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track_rect = self._track_rect()

        painter.setPen(QPen(self._qcolor("LINE", "#3A3A3A"), 1))
        painter.setBrush(self._qcolor("TRACK", "#1E1E1E"))
        painter.drawRoundedRect(track_rect, self._OUTER_RADIUS, self._OUTER_RADIUS)

        if not self._segments or self._effective_duration() <= 0:
            painter.setPen(QPen(self._qcolor("MUTED", "#777777")))
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

            if index == self._generating_index and segment.state != "ready":
                painter.setPen(QPen(self._qcolor("WARN", "#FFE08A"), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(segment_rect.adjusted(1, 1, -1, -1), self._INNER_RADIUS, self._INNER_RADIUS)
            elif index == self._selected_index:
                painter.setPen(QPen(self._qcolor("ACCENT", "#FFFFFF"), 2))
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
        if selected != self._selected_index:
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
        if selected != self._selected_index:
            self._selected_index = selected
            self.update()
        self.chunk_clicked.emit(selected)
        self.chunk_double_clicked.emit(selected)
        event.accept()
