"""Wrapping layout so a row of buttons can break instead of widening the page."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, *, spacing: int = 8):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = max(0, int(spacing))
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            if self._is_hidden(item):
                continue
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    @staticmethod
    def _is_hidden(item: QLayoutItem) -> bool:
        widget = item.widget()
        return widget is not None and widget.isHidden()

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        left = rect.x() + margins.left()
        top = rect.y() + margins.top()
        space_x = self._spacing
        space_y = self._spacing
        x = left
        y = top
        line_height = 0
        available_right = rect.x() + rect.width() - margins.right()
        for item in self._items:
            if self._is_hidden(item):
                continue
            hint = item.sizeHint().expandedTo(item.minimumSize())
            if x > left and x + hint.width() > available_right:
                x = left
                y = y + line_height + space_y
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = x + hint.width() + space_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
