"""Result table host: populate helpers + async thumbnail cell updates."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QStackedWidget, QTableWidget, QVBoxLayout, QWidget

from ui.views.table_views import populate_result_table
from ui.widgets.result_grid import ResultGrid
from ui.widgets.result_table import ResultTable
from ui.widgets.table_specs import LOCAL_SEARCH_TABLE_SPEC
from ui.widgets.thumb_cell import make_thumb_label

THUMB_COLUMN = int(LOCAL_SEARCH_TABLE_SPEC.thumb_column or 1)

VIEW_TABLE = "table"
VIEW_GRID = "grid"


class ResultView(QWidget):
    """Wraps result table/grid; controllers call populate / set_thumbnail instead of setCellWidget."""

    view_mode_changed = Signal(str)

    def __init__(
        self,
        parent=None,
        *,
        table: QTableWidget | None = None,
        min_table_height: int | None = None,
        view_mode: str = VIEW_TABLE,
    ):
        super().__init__(parent)
        self._busy = False
        self._empty_message = ""
        self._mode = VIEW_GRID if str(view_mode or "").strip().lower() == VIEW_GRID else VIEW_TABLE

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        if min_table_height is not None:
            self.stack.setMinimumHeight(min_table_height)

        self.content_stack = QStackedWidget()
        self.table = table if table is not None else ResultTable()
        if min_table_height is not None:
            self.table.setMinimumHeight(min_table_height)
        self.grid = ResultGrid(min_height=min_table_height)
        self.content_stack.addWidget(self.table)
        self.content_stack.addWidget(self.grid)

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

        self.stack.addWidget(self.content_stack)
        self.stack.addWidget(self.empty_panel)
        layout.addWidget(self.stack)
        self._apply_mode_widget()
        self._sync_empty_overlay()

    @property
    def result_table(self) -> QTableWidget:
        return self.table

    @property
    def view_mode(self) -> str:
        return self._mode

    def set_view_mode(self, mode: str, *, emit: bool = True) -> None:
        next_mode = VIEW_GRID if str(mode or "").strip().lower() == VIEW_GRID else VIEW_TABLE
        if next_mode == self._mode:
            self._apply_mode_widget()
            return
        self._mode = next_mode
        self._apply_mode_widget()
        self._sync_empty_overlay()
        if emit:
            self.view_mode_changed.emit(self._mode)

    def _apply_mode_widget(self) -> None:
        self.content_stack.setCurrentWidget(self.grid if self._mode == VIEW_GRID else self.table)

    def set_empty_message(self, text: str) -> None:
        self._empty_message = str(text or "").strip()
        self.empty_hint.setText(self._empty_message)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._sync_empty_overlay()

    def _has_results(self) -> bool:
        if self._mode == VIEW_GRID:
            return self.grid.count() > 0
        return self.table.rowCount() > 0

    def _sync_empty_overlay(self) -> None:
        if self._busy or self._has_results():
            self.stack.setCurrentWidget(self.content_stack)
            self._apply_mode_widget()
        else:
            if self._empty_message:
                self.empty_hint.setText(self._empty_message)
            self.stack.setCurrentWidget(self.empty_panel)

    def clear(self) -> None:
        self.table.setRowCount(0)
        self.grid.clear()
        self._sync_empty_overlay()

    def populate_local(
        self,
        results,
        on_preview,
        on_locate,
        on_export,
        texts,
        on_deep_locate=None,
        on_add_to_shot_list=None,
        *,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
        rank_offset: int = 0,
        highlight_query: str = "",
        dialogue_match_mode: str = "",
    ) -> None:
        kwargs = dict(
            results=results,
            on_preview=on_preview,
            on_locate=on_locate,
            on_export=on_export,
            texts=texts,
            on_deep_locate=on_deep_locate,
            on_add_to_shot_list=on_add_to_shot_list,
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_score,
            rank_offset=rank_offset,
            highlight_query=highlight_query,
            dialogue_match_mode=dialogue_match_mode,
        )
        if self._mode == VIEW_GRID:
            self.table.setRowCount(0)
            self.grid.populate(**kwargs)
        else:
            self.grid.clear()
            populate_result_table(self.table, **kwargs)
        self._sync_empty_overlay()

    def set_thumbnail(self, row: int, pixmap, column: int | None = None) -> None:
        if self._mode == VIEW_GRID:
            self.grid.set_thumbnail(row, pixmap)
            return
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
