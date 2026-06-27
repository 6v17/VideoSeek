"""Dialog for reviewing and reordering the in-session shot list."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from src.services.shot_list_service import ShotListStore
from src.services.search_service import format_clip_score_percent
from ui.views.table_views import _format_time_range
from ui.widgets.scaffold import VSCard


class ShotListDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        store: ShotListStore,
        language: str = "zh",
        is_dark: bool = True,
        on_preview=None,
        on_locate=None,
        on_export_manifest=None,
        on_batch_export=None,
        ffmpeg_available: bool = True,
    ):
        super().__init__(parent)
        self.store = store
        self.texts = get_texts(language)
        self.on_preview = on_preview
        self.on_locate = on_locate
        self.on_export_manifest = on_export_manifest
        self.on_batch_export = on_batch_export
        self.ffmpeg_available = bool(ffmpeg_available)
        self._selected_item_id = ""

        self.setWindowTitle(self.texts.get("shot_list_title", "Shot list"))
        self.setMinimumSize(860, 520)
        self.resize(980, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(self.texts.get("shot_list_title", "Shot list"))
        title.setObjectName("DialogPageTitle")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("Hint")
        self.subtitle.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(self.subtitle)

        card = VSCard(margins=(14, 12, 14, 12), spacing=10)
        card_layout = card.content_layout

        self.table = QTableWidget(0, 5)
        self.table.setObjectName("ResultTable")
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._sync_selection)
        self.table.cellDoubleClicked.connect(self._handle_double_click)
        headers = self.texts.get(
            "shot_list_headers",
            ["#", "Video", "Range", "Score", "Source query"],
        )
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 46)
        self.table.setColumnWidth(2, 108)
        self.table.setColumnWidth(3, 74)
        card_layout.addWidget(self.table)
        root.addWidget(card, 1)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        self.btn_export_manifest = QPushButton(self.texts.get("shot_list_export_manifest", "Export manifest"))
        self.btn_batch_export = QPushButton(self.texts.get("shot_list_batch_export", "Batch export clips"))
        self.btn_export_manifest.setObjectName("GhostButton")
        self.btn_batch_export.setObjectName("GhostButton")
        self.btn_batch_export.setEnabled(self.ffmpeg_available)
        if not self.ffmpeg_available:
            self.btn_batch_export.setToolTip(
                self.texts.get("shot_list_batch_export_ffmpeg_required", "FFmpeg is required for clip export.")
            )
        export_row.addWidget(self.btn_export_manifest)
        export_row.addWidget(self.btn_batch_export)
        export_row.addStretch(1)
        root.addLayout(export_row)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.btn_move_up = QPushButton(self.texts.get("shot_list_move_up", "Move up"))
        self.btn_move_down = QPushButton(self.texts.get("shot_list_move_down", "Move down"))
        self.btn_remove = QPushButton(self.texts.get("shot_list_remove", "Remove"))
        self.btn_clear = QPushButton(self.texts.get("shot_list_clear", "Clear all"))
        self.btn_preview = QPushButton(self.texts.get("preview", "Preview"))
        self.btn_locate = QPushButton(self.texts.get("locate", "Locate"))
        for button in (
            self.btn_move_up,
            self.btn_move_down,
            self.btn_remove,
            self.btn_clear,
            self.btn_preview,
            self.btn_locate,
        ):
            button.setObjectName("GhostButton")
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.btn_close = QPushButton(self.texts.get("close", "Close"))
        self.btn_close.setObjectName("PrimaryButton")
        toolbar.addWidget(self.btn_close)
        root.addLayout(toolbar)

        self.btn_move_up.clicked.connect(self._move_up)
        self.btn_move_down.clicked.connect(self._move_down)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear_all)
        self.btn_preview.clicked.connect(self._preview_selected)
        self.btn_locate.clicked.connect(self._locate_selected)
        self.btn_export_manifest.clicked.connect(self._export_manifest)
        self.btn_batch_export.clicked.connect(self._batch_export)
        self.btn_close.clicked.connect(self.accept)

        self._reload_table()

    def _reload_table(self) -> None:
        items = self.store.list_items()
        self.subtitle.setText(
            self.texts.get("shot_list_subtitle", "{count} clips collected").format(count=len(items))
        )
        self.table.setRowCount(0)
        for row, item in enumerate(items):
            self.table.insertRow(row)
            order_item = QTableWidgetItem(str(row + 1))
            order_item.setTextAlignment(Qt.AlignCenter)
            order_item.setData(Qt.UserRole, item.id)
            self.table.setItem(row, 0, order_item)

            video_item = QTableWidgetItem(os.path.basename(item.video_path) or item.video_path)
            video_item.setToolTip(item.video_path)
            self.table.setItem(row, 1, video_item)

            range_item = QTableWidgetItem(
                _format_time_range(item.start_sec, item.end_sec, self.texts, match_kind=item.match_kind)
            )
            range_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, range_item)

            score_text = "—"
            if item.score is not None:
                score_text = format_clip_score_percent(float(item.score))
            score_item = QTableWidgetItem(score_text)
            score_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, score_item)

            query_item = QTableWidgetItem(item.source_query or "—")
            query_item.setToolTip(item.source_query or "")
            self.table.setItem(row, 4, query_item)

        if items:
            self.table.selectRow(0)
        self._sync_selection()

    def _sync_selection(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self._selected_item_id = ""
        else:
            item = self.table.item(row, 0)
            self._selected_item_id = str(item.data(Qt.UserRole) if item is not None else "")
        has_selection = bool(self._selected_item_id)
        for button in (
            self.btn_move_up,
            self.btn_move_down,
            self.btn_remove,
            self.btn_preview,
            self.btn_locate,
        ):
            button.setEnabled(has_selection)
        self.btn_clear.setEnabled(self.store.count() > 0)
        self.btn_export_manifest.setEnabled(self.store.count() > 0)
        self.btn_batch_export.setEnabled(self.store.count() > 0 and self.ffmpeg_available)

    def _export_manifest(self) -> None:
        if self.on_export_manifest is not None:
            self.on_export_manifest()

    def _batch_export(self) -> None:
        if self.on_batch_export is not None:
            self.on_batch_export()

    def _selected_item(self):
        if not self._selected_item_id:
            return None
        return self.store.get(self._selected_item_id)

    def _move_up(self) -> None:
        if not self._selected_item_id:
            return
        if self.store.move_up(self._selected_item_id):
            self._reload_table()
            self._select_item_id(self._selected_item_id)

    def _move_down(self) -> None:
        if not self._selected_item_id:
            return
        if self.store.move_down(self._selected_item_id):
            self._reload_table()
            self._select_item_id(self._selected_item_id)

    def _remove_selected(self) -> None:
        if not self._selected_item_id:
            return
        self.store.remove(self._selected_item_id)
        self._reload_table()

    def _clear_all(self) -> None:
        self.store.clear()
        self._reload_table()

    def _preview_selected(self) -> None:
        item = self._selected_item()
        if item is None or self.on_preview is None:
            return
        self.on_preview(item.video_path, item.start_sec, item.end_sec)
        self.accept()

    def _locate_selected(self) -> None:
        item = self._selected_item()
        if item is None or self.on_locate is None:
            return
        self.on_locate(item.video_path)

    def _handle_double_click(self, row: int, _column: int) -> None:
        if row < 0:
            return
        self.table.selectRow(row)
        self._preview_selected()

    def _select_item_id(self, item_id: str) -> None:
        target = str(item_id or "").strip()
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is not None and str(cell.data(Qt.UserRole)) == target:
                self.table.selectRow(row)
                return
