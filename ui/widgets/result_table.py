"""Virtualized local-search results: QTableView + SearchResultTableModel + delegates.

Off-screen rows do not host action QPushButtons; editors open only for the
viewport (±1 row). Thumbnails are painted by SearchResultThumbDelegate.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
)

from ui.views.table_views import _build_result_actions

from ui.widgets.button_roles import name_table_corner_button
from ui.widgets.search_result_delegates import (
    SearchResultActionsDelegate,
    SearchResultPlainDelegate,
    SearchResultThumbDelegate,
    SearchResultVideoDelegate,
    group_badge_chip_rect,
)
from ui.widgets.search_result_table_model import (
    GroupMetaRole,
    HitPayloadRole,
    SearchResultTableModel,
    ThumbRole,
)
from ui.widgets.table_scroll import table_wheel_pixel_delta
from ui.widgets.table_specs import LOCAL_SEARCH_TABLE_SPEC, LocalSearchCol


class ResultTable(QTableView):
    """Local vector search results (7 columns, preview column) — virtualized."""

    group_toggle_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spec = LOCAL_SEARCH_TABLE_SPEC
        self._display_row_height = int(self.spec.row_height)
        self._open_action_rows: set[int] = set()
        self._sync_actions_scheduled = False
        self._pending_restore: tuple[int, int | None] | None = None

        self.result_model = SearchResultTableModel(self)
        self.setModel(self.result_model)

        self._thumb_delegate = SearchResultThumbDelegate(self)
        self._video_delegate = SearchResultVideoDelegate(self)
        self._actions_delegate = SearchResultActionsDelegate(self)
        self.setItemDelegateForColumn(int(LocalSearchCol.PREVIEW), self._thumb_delegate)
        self.setItemDelegateForColumn(int(LocalSearchCol.VIDEO), self._video_delegate)
        self.setItemDelegateForColumn(int(LocalSearchCol.ACTIONS), self._actions_delegate)
        self._video_delegate.group_toggle_requested.connect(self.group_toggle_requested)
        self._plain_delegate = SearchResultPlainDelegate(self)
        self.setItemDelegate(self._plain_delegate)
        self.viewport().setMouseTracking(True)

        self._apply_spec()
        self.verticalScrollBar().valueChanged.connect(self._schedule_sync_action_editors)
        # Geometry changes (resize / scale) also change which rows are visible.
        self.verticalHeader().sectionResized.connect(lambda *_: self._schedule_sync_action_editors())

    def _apply_spec(self) -> None:
        spec = self.spec
        self.setObjectName(spec.object_name)
        name_table_corner_button(self)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(spec.row_height)
        self.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setShowGrid(False)
        self.setMinimumWidth(0)
        if spec.scroll_per_pixel:
            self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
            self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        step = max(12, int(spec.row_height or 24))
        self.verticalScrollBar().setSingleStep(step)
        self.horizontalHeader().setStretchLastSection(False)

        header = self.horizontalHeader()
        for index, column in enumerate(spec.columns):
            if column.resize == "stretch":
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
                if column.width is not None:
                    self.setColumnWidth(index, column.width)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def apply_header_labels(self, texts: dict) -> None:
        key = self.spec.texts_header_key
        if not key:
            return
        labels = texts.get(key)
        if labels:
            self.result_model.set_headers(list(labels))

    # --- QTableWidget-compatible helpers used by SearchController / ResultView ---

    def rowCount(self) -> int:  # noqa: N802
        return int(self.result_model.rowCount())

    def setRowCount(self, rows: int) -> None:  # noqa: N802
        if int(rows) <= 0:
            self.clear_results()

    def clear_results(self) -> None:
        self._close_all_action_editors()
        self.result_model.clear_rows()

    def set_thumbnail(self, row: int, pixmap) -> None:
        self.result_model.set_thumbnail(int(row), pixmap)

    def hit_payload(self, row: int) -> dict | None:
        """Hit dict for one row. Replaces the old ``QTableWidgetItem`` UserRole payload."""
        index = self.result_model.index(int(row), int(LocalSearchCol.ORDER))
        if not index.isValid():
            return None
        payload = self.result_model.data(index, HitPayloadRole)
        return dict(payload) if isinstance(payload, dict) else None

    def thumbnail_pixmap(self, row: int) -> QPixmap | None:
        index = self.result_model.index(int(row), int(LocalSearchCol.PREVIEW))
        if not index.isValid():
            return None
        thumb = self.result_model.data(index, ThumbRole)
        if isinstance(thumb, QPixmap) and not thumb.isNull():
            return thumb
        return None

    def scroll_to_row(self, row: int) -> None:
        index = self.result_model.index(int(row), int(LocalSearchCol.ORDER))
        if index.isValid():
            self.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)

    def populate_results(
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
        self._close_all_action_editors()
        display_texts = texts
        if clip_score_mode:
            display_texts = dict(texts)
            headers = list(texts.get("result_headers") or [])
            if len(headers) > int(LocalSearchCol.SCORE):
                headers[int(LocalSearchCol.SCORE)] = texts.get(
                    "result_header_clip_score", headers[int(LocalSearchCol.SCORE)]
                )
                display_texts["result_headers"] = headers
        self.apply_header_labels(display_texts)
        self.result_model.set_action_handlers(
            on_preview=on_preview,
            on_locate=on_locate,
            on_export=on_export,
            on_deep_locate=on_deep_locate,
            on_add_to_shot_list=on_add_to_shot_list,
        )
        self._pending_restore = None
        self.result_model.set_hits(
            results,
            texts=texts,
            rank_offset=rank_offset,
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_score,
            highlight_query=highlight_query,
            dialogue_match_mode=dialogue_match_mode,
        )
        self._schedule_sync_action_editors()
        QTimer.singleShot(0, self._consume_pending_restore)

    def _consume_pending_restore(self) -> None:
        pending = self._pending_restore
        self._pending_restore = None
        if not pending:
            return
        scroll, index = pending
        QTimer.singleShot(0, lambda s=int(scroll), i=index: self.restore_viewport(s, i))

    def restore_viewport(self, scroll_value: int, selected_index: int | None = None) -> None:
        """Put the list back where it was, and mark the row the user opened."""
        bar = self.verticalScrollBar()
        bar.setValue(max(0, int(scroll_value)))
        if selected_index is None:
            return
        row = int(selected_index)
        if row < 0 or row >= self.result_model.rowCount():
            return
        self.selectRow(row)
        index = self.result_model.index(row, int(LocalSearchCol.VIDEO))
        self.scrollTo(index, QAbstractItemView.ScrollHint.EnsureVisible)

    def append_results(
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
        self.result_model.set_action_handlers(
            on_preview=on_preview,
            on_locate=on_locate,
            on_export=on_export,
            on_deep_locate=on_deep_locate,
            on_add_to_shot_list=on_add_to_shot_list,
        )
        self.result_model.append_hits(
            results,
            texts=texts,
            rank_offset=rank_offset,
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_score,
            highlight_query=highlight_query,
            dialogue_match_mode=dialogue_match_mode,
        )
        self._schedule_sync_action_editors()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        super().mouseMoveEvent(event)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        hand = False
        if index.isValid() and index.column() == int(LocalSearchCol.VIDEO):
            meta = index.data(GroupMetaRole) or {}
            if isinstance(meta, dict) and meta.get("show_badge") and meta.get("badge"):
                chip = group_badge_chip_rect(self.visualRect(index), str(meta.get("badge") or ""), self.fontMetrics())
                hand = chip.contains(pos)
        if hand:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        bar = self.verticalScrollBar()
        if bar is None or bar.maximum() <= 0:
            super().wheelEvent(event)
            return
        row_height = int(getattr(self, "_display_row_height", None) or self.spec.row_height or 24)
        delta = table_wheel_pixel_delta(
            int(event.pixelDelta().y()),
            int(event.angleDelta().y()),
            row_height=row_height,
        )
        if delta == 0:
            super().wheelEvent(event)
            return
        if self.verticalScrollMode() != QAbstractItemView.ScrollMode.ScrollPerPixel:
            row = max(12, row_height)
            steps = int(round(delta / row)) or (1 if delta > 0 else -1)
            delta = steps
        old = int(bar.value())
        bar.setValue(old - delta)
        if int(bar.value()) == old:
            event.ignore()
            return
        event.accept()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_sync_action_editors()

    # --- visible action editors ----------------------------------------

    def _schedule_sync_action_editors(self, *_args) -> None:
        if self._sync_actions_scheduled:
            return
        self._sync_actions_scheduled = True
        QTimer.singleShot(0, self._sync_action_editors)

    def _visible_row_span(self) -> tuple[int, int]:
        count = self.result_model.rowCount()
        if count <= 0:
            return 0, -1
        top = self.rowAt(0)
        bottom = self.rowAt(max(0, self.viewport().height() - 1))
        if top < 0:
            top = 0
        if bottom < 0:
            bottom = min(count - 1, top + 8)
        first = max(0, top - 1)
        last = min(count - 1, bottom + 1)
        return first, last

    def _make_action_widget(self, row: int):
        ent = self.result_model.row_dict(row) or {}
        handlers = self.result_model.action_handlers()
        texts = dict(self.result_model.texts or {})
        on_preview = handlers.get("on_preview") or (lambda *_a, **_k: None)
        on_locate = handlers.get("on_locate") or (lambda *_a, **_k: None)
        on_export = handlers.get("on_export") or (lambda *_a, **_k: None)
        return _build_result_actions(
            ent.get("video_path") or "",
            float(ent.get("start_sec") or 0.0),
            float(ent.get("end_sec") or 0.0),
            on_preview,
            on_locate,
            on_export,
            texts,
            match_kind=str(ent.get("match_kind") or "frame"),
            on_deep_locate=handlers.get("on_deep_locate"),
            on_add_to_shot_list=handlers.get("on_add_to_shot_list"),
            anchor_score=float(ent.get("score") or 0.0),
            preview_sec=ent.get("preview_sec"),
        )

    def _sync_action_editors(self) -> None:
        """Attach real action buttons only for viewport rows (setIndexWidget)."""
        self._sync_actions_scheduled = False
        count = self.result_model.rowCount()
        if count <= 0:
            self._close_all_action_editors()
            return
        first, last = self._visible_row_span()
        if last < first:
            self._close_all_action_editors()
            return
        wanted = set(range(first, last + 1))
        for row in list(self._open_action_rows):
            if row not in wanted or row >= count:
                index = self.result_model.index(row, int(LocalSearchCol.ACTIONS))
                if index.isValid():
                    self.setIndexWidget(index, None)
                self._open_action_rows.discard(row)
        for row in sorted(wanted):
            if row in self._open_action_rows:
                continue
            index = self.result_model.index(row, int(LocalSearchCol.ACTIONS))
            if not index.isValid():
                continue
            self.setIndexWidget(index, self._make_action_widget(row))
            self._open_action_rows.add(row)

    def _close_all_action_editors(self) -> None:
        for row in list(self._open_action_rows):
            index = self.result_model.index(row, int(LocalSearchCol.ACTIONS))
            if index.isValid():
                self.setIndexWidget(index, None)
        self._open_action_rows.clear()
