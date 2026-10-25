"""Result table/grid host: populate helpers + async thumbnail cell updates."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from ui.widgets.result_grid import RESULT_SCALE_DEFAULT, ResultGrid, clamp_result_scale_percent
from ui.widgets.result_table import ResultTable
from ui.widgets.table_specs import LOCAL_SEARCH_TABLE_SPEC

THUMB_COLUMN = int(LOCAL_SEARCH_TABLE_SPEC.thumb_column or 1)

VIEW_TABLE = "table"
VIEW_GRID = "grid"


def table_display_metrics(scale_percent: int = RESULT_SCALE_DEFAULT) -> tuple[int, int]:
    """Row height and preview-column width for the list view at this size."""
    factor = clamp_result_scale_percent(scale_percent) / 100.0
    preview = next((col for col in LOCAL_SEARCH_TABLE_SPEC.columns if col.key == "preview"), None)
    row_h = max(72, int(round(int(LOCAL_SEARCH_TABLE_SPEC.row_height) * factor)))
    preview_w = max(140, int(round(int(getattr(preview, "width", None) or 220) * factor)))
    return row_h, preview_w


class ResultView(QWidget):
    """Wraps result table/grid; controllers call populate / set_thumbnail instead of setCellWidget."""

    view_mode_changed = Signal(str)

    def __init__(
        self,
        parent=None,
        *,
        table: ResultTable | None = None,
        min_table_height: int | None = None,
        view_mode: str = VIEW_TABLE,
    ):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._busy = False
        self._empty_message = ""
        self._mode = VIEW_GRID if str(view_mode or "").strip().lower() == VIEW_GRID else VIEW_TABLE
        self._scale_percent = RESULT_SCALE_DEFAULT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
    def result_table(self) -> ResultTable:
        return self.table

    @property
    def view_mode(self) -> str:
        return self._mode

    @property
    def display_scale_percent(self) -> int:
        return int(self._scale_percent)

    def set_display_scale(self, scale_percent: int) -> None:
        """Resize grid cards and table rows. Cached frames are drawn again at the new size."""
        self._scale_percent = clamp_result_scale_percent(scale_percent)
        self.grid.set_display_scale(self._scale_percent)
        self._apply_table_scale()
        # Thumb delegate paints from source pixmaps; force a redraw at the new cell size.
        self.table.viewport().update()

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

    def set_viewport_min_height(self, height: int) -> None:
        """One floor for the stack. Child table/grid mins must not stack on top of it."""
        height = max(120, int(height))
        self.stack.setMinimumHeight(height)
        self.table.setMinimumHeight(0)
        self.grid.setMinimumHeight(0)

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
        self.table.clear_results()
        self.grid.clear()
        self._sync_empty_overlay()

    def _apply_table_scale(self) -> None:
        row_h, preview_w = table_display_metrics(self._scale_percent)
        header = self.table.verticalHeader()
        header.setDefaultSectionSize(row_h)
        self.table._display_row_height = row_h
        bar = self.table.verticalScrollBar()
        if bar is not None:
            bar.setSingleStep(row_h)
        column = int(
            LOCAL_SEARCH_TABLE_SPEC.thumb_column
            if LOCAL_SEARCH_TABLE_SPEC.thumb_column is not None
            else THUMB_COLUMN
        )
        self.table.setColumnWidth(column, preview_w)
        # Default section size covers new rows; touch existing ones for immediate feedback.
        for row in range(self.table.rowCount()):
            self.table.setRowHeight(row, row_h)
        sync = getattr(self.table, "_schedule_sync_action_editors", None)
        if callable(sync):
            sync()

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
            self.table.clear_results()
            self.grid.populate(**kwargs)
        else:
            self.grid.clear()
            self.table.populate_results(**kwargs)
            self._apply_table_scale()
        self._sync_empty_overlay()

    def append_local(
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
            self.grid.append(**kwargs)
        else:
            self.table.append_results(**kwargs)
            self._apply_table_scale()
        self._sync_empty_overlay()

    def set_thumbnail(self, row: int, pixmap, column: int | None = None) -> None:
        del column
        if self._mode == VIEW_GRID:
            self.grid.set_thumbnail(row, pixmap)
            return
        if pixmap is None or (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            self.table.set_thumbnail(int(row), None)
        else:
            self.table.set_thumbnail(int(row), pixmap)
