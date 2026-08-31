"""QTableWidget configured from TableSpec."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget

from ui.widgets.table_scroll import table_wheel_pixel_delta
from ui.widgets.table_specs import TableSpec


class DataTable(QTableWidget):
    def __init__(self, parent=None, *, spec: TableSpec):
        super().__init__(0, spec.column_count, parent)
        self.spec = spec
        self._apply_spec()

    def _apply_spec(self) -> None:
        spec = self.spec
        self.setObjectName(spec.object_name)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(spec.row_height)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        if spec.scroll_per_pixel:
            self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        step = max(12, int(spec.row_height or 24))
        self.verticalScrollBar().setSingleStep(step)
        self.horizontalHeader().setStretchLastSection(False)

        header = self.horizontalHeader()
        for index, column in enumerate(spec.columns):
            if column.resize == "stretch":
                header.setSectionResizeMode(index, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.Fixed)
                if column.width is not None:
                    self.setColumnWidth(index, column.width)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        bar = self.verticalScrollBar()
        if bar is None or bar.maximum() <= 0:
            super().wheelEvent(event)
            return
        delta = table_wheel_pixel_delta(
            int(event.pixelDelta().y()),
            int(event.angleDelta().y()),
            row_height=int(self.spec.row_height or 24),
        )
        if delta == 0:
            super().wheelEvent(event)
            return
        if self.verticalScrollMode() != QAbstractItemView.ScrollMode.ScrollPerPixel:
            row = max(12, int(self.spec.row_height or 24))
            steps = int(round(delta / row)) or (1 if delta > 0 else -1)
            delta = steps
        old = int(bar.value())
        bar.setValue(old - delta)
        if int(bar.value()) == old:
            event.ignore()
            return
        event.accept()

    def apply_header_labels(self, texts: dict) -> None:
        key = self.spec.texts_header_key
        if not key:
            return
        labels = texts.get(key)
        if labels:
            self.setHorizontalHeaderLabels(labels)
