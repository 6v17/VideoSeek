"""Result table host: populate helpers + async thumbnail cell updates."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QStackedWidget, QTableWidget, QVBoxLayout, QWidget

from ui.views.table_views import (
    populate_network_result_table,
    populate_result_table,
)
from ui.widgets.result_table import ResultTable
from ui.widgets.table_specs import LOCAL_SEARCH_TABLE_SPEC
from ui.widgets.thumb_cell import make_thumb_label

THUMB_COLUMN = int(LOCAL_SEARCH_TABLE_SPEC.thumb_column or 1)


class ResultView(QWidget):
    """Wraps a result QTableWidget; controllers call populate / set_thumbnail instead of setCellWidget."""

    def __init__(
        self,
        parent=None,
        *,
        table: QTableWidget | None = None,
        min_table_height: int | None = None,
    ):
        super().__init__(parent)
        self._busy = False
        self._empty_message = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        if min_table_height is not None:
            self.stack.setMinimumHeight(min_table_height)

        self.table = table if table is not None else ResultTable()
        if min_table_height is not None:
            self.table.setMinimumHeight(min_table_height)

        self.empty_panel = QWidget()
        empty_layout = QVBoxLayout(self.empty_panel)
        empty_layout.setContentsMargins(24, 32, 24, 32)
        self.empty_hint = QLabel()
        self.empty_hint.setObjectName("LibraryEmptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_hint)
        empty_layout.addStretch(1)

        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty_panel)
        layout.addWidget(self.stack)
        self._sync_empty_overlay()

    @property
    def result_table(self) -> QTableWidget:
        return self.table

    def set_empty_message(self, text: str) -> None:
        self._empty_message = str(text or "").strip()
        self.empty_hint.setText(self._empty_message)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_empty_overlay()

    def _sync_empty_overlay(self) -> None:
        if self._busy or self.table.rowCount() > 0:
            self.stack.setCurrentWidget(self.table)
        else:
            if self._empty_message:
                self.empty_hint.setText(self._empty_message)
            self.stack.setCurrentWidget(self.empty_panel)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self._sync_empty_overlay()

    def populate_local(
        self,
        results,
        on_preview,
        on_locate,
        on_export,
        texts,
        on_deep_locate=None,
        *,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
    ) -> None:
        populate_result_table(
            self.table,
            results,
            on_preview,
            on_locate,
            on_export,
            texts,
            on_deep_locate,
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_score,
        )
        self._sync_empty_overlay()

    def populate_network(self, results, texts) -> None:
        populate_network_result_table(self.table, results, texts)
        self._sync_empty_overlay()

    def set_thumbnail(self, row: int, pixmap, column: int | None = None) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        if column is None:
            spec = getattr(self.table, "spec", None)
            thumb = getattr(spec, "thumb_column", None) if spec is not None else None
            column = int(thumb if thumb is not None else THUMB_COLUMN)
        if pixmap is None or (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            self.table.setCellWidget(row, column, make_thumb_label(text="—"))
        else:
            self.table.setCellWidget(row, column, make_thumb_label(pixmap=pixmap))
