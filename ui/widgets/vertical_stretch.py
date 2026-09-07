"""Drag handle under a widget so the user can grow/shrink list height."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QSizePolicy, QVBoxLayout, QWidget


class VerticalStretchHandle(QFrame):
    """Thin bar; drag vertically to change ``target`` height."""

    height_changed = Signal(int)

    def __init__(
        self,
        target: QWidget,
        *,
        min_height: int = 120,
        max_height: int = 1600,
        parent=None,
    ):
        super().__init__(parent)
        self._target = target
        self._min_height = max(48, int(min_height))
        self._max_height = max(self._min_height, int(max_height))
        self._drag_origin_y = 0
        self._drag_origin_h = 0
        self._dragging = False
        self.setObjectName("VerticalStretchHandle")
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Drag to resize")

    def set_tooltip_text(self, text: str) -> None:
        self.setToolTip(str(text or "Drag to resize"))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._target is None:
            super().mousePressEvent(event)
            return
        self._dragging = True
        self._drag_origin_y = int(event.globalPosition().y())
        self._drag_origin_h = max(self._min_height, int(self._target.height()))
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self._dragging or self._target is None:
            super().mouseMoveEvent(event)
            return
        delta = int(event.globalPosition().y()) - self._drag_origin_y
        height = max(self._min_height, min(self._max_height, self._drag_origin_h + delta))
        self._apply_height(height)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mid_y = self.height() // 2
        left = max(8, (self.width() - 28) // 2)
        right = left + 28
        # Subtle grip dashes so users notice the handle.
        pen = QPen(QColor(120, 120, 120, 140), 1.5)
        painter.setPen(pen)
        painter.drawLine(left, mid_y - 1, right, mid_y - 1)
        painter.drawLine(left, mid_y + 2, right, mid_y + 2)
        painter.end()

    def _apply_height(self, height: int) -> None:
        height = max(self._min_height, min(self._max_height, int(height)))
        self._target.setMinimumHeight(height)
        self._target.setMaximumHeight(height)
        self._target.setFixedHeight(height)
        self.height_changed.emit(height)


def add_vertically_stretchable(
    layout: QVBoxLayout,
    widget: QWidget,
    *,
    default_height: int,
    min_height: int = 120,
    max_height: int = 1600,
    stretch: int = 0,
) -> VerticalStretchHandle:
    """Add ``widget`` + drag handle; height starts at ``default_height``."""
    default_height = max(int(min_height), int(default_height))
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    widget.setMinimumHeight(default_height)
    widget.setMaximumHeight(default_height)
    widget.setFixedHeight(default_height)
    layout.addWidget(widget, stretch)
    handle = VerticalStretchHandle(widget, min_height=min_height, max_height=max_height)
    layout.addWidget(handle, 0)
    return handle
