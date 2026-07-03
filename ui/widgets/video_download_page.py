"""Video download page — replaces legacy LinkSearchPage."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
)

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import PageScaffold, VSCard

COL_INDEX = 0
COL_TITLE = 1
COL_QUALITY = 2
COL_STATUS = 3
COL_PROGRESS = 4
COL_PATH = 5
COL_ACTION = 6

_ROW_WIDGET_HEIGHT = 28
_ROW_SECTION_HEIGHT = 50


def _elide_middle(text: str, *, limit: int = 88) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    keep = max(16, (limit - 1) // 2)
    return f"{value[:keep]}…{value[-keep:]}"


def _toolbar_divider() -> QFrame:
    divider = QFrame()
    divider.setFrameShape(QFrame.Shape.VLine)
    divider.setFrameShadow(QFrame.Shadow.Plain)
    divider.setObjectName("ToolbarDivider")
    return divider


def _wrap_table_cell(widget: QWidget, *, center: bool = False) -> QWidget:
    host = QWidget()
    host.setObjectName("DownloadCellHost")
    layout = QHBoxLayout(host)
    layout.setContentsMargins(8, 0, 8, 0)
    layout.setSpacing(0)
    widget.setFixedHeight(_ROW_WIDGET_HEIGHT)
    if center:
        layout.addStretch(1)
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)
    else:
        layout.addWidget(widget, 1, Qt.AlignmentFlag.AlignVCenter)
    return host


def _make_quality_combo(texts: dict, heights: list[int]) -> QComboBox:
    combo = QComboBox()
    combo.setObjectName("DownloadRowCombo")
    combo.setFixedHeight(_ROW_WIDGET_HEIGHT)
    combo.addItem(texts.get("download_quality_best", "best"), "best")
    for height in sorted({int(item) for item in heights if int(item) > 0}, reverse=True):
        combo.addItem(f"{height}p", str(height))
    combo.setCurrentIndex(0)
    return combo


def _make_row_action_button(text: str, *, tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    btn.setObjectName("DownloadRowButton")
    btn.setFixedSize(56, _ROW_WIDGET_HEIGHT)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        btn.setToolTip(tooltip)
    return btn


def _make_row_progress_bar() -> QProgressBar:
    bar = QProgressBar()
    bar.setObjectName("DownloadRowProgress")
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setTextVisible(True)
    bar.setFixedHeight(22)
    bar.setFormat("—")
    return bar


def _set_table_item(
    table: QTableWidget,
    row: int,
    column: int,
    text: str,
    *,
    tooltip: str = "",
    align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
) -> None:
    item = QTableWidgetItem(str(text or ""))
    item.setTextAlignment(align)
    if tooltip:
        item.setToolTip(tooltip)
    table.setItem(row, column, item)


class VideoDownloadPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        field_gap = int(COMPONENT_SIZES.get("search_field_gap", 4))
        card_margin = int(COMPONENT_SIZES.get("search_panel_card_margin", 12))
        self._texts: dict = {}

        self.links_card = VSCard(margins=(card_margin,) * 4, spacing=0)
        self.links_input = QTextEdit()
        self.links_input.setObjectName("SearchInput")
        self.links_input.setMinimumHeight(128)
        self.links_input.setAcceptRichText(False)
        self.links_card.content_layout.addWidget(self.links_input)
        page_body.addWidget(self.links_card)

        self.options_card = VSCard(variant="sub", margins=(16, 12, 16, 12), spacing=10)
        options_layout = QVBoxLayout()
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(10)

        cookie_row = QHBoxLayout()
        cookie_row.setContentsMargins(0, 0, 0, 0)
        cookie_row.setSpacing(field_gap)
        self.lbl_cookie = QLabel()
        self.lbl_cookie.setObjectName("InlineFieldLabel")
        self.lbl_cookie.setMinimumWidth(76)
        self.input_cookie_file = QLineEdit()
        self.input_cookie_file.setObjectName("SearchInput")
        self.input_cookie_file.setReadOnly(True)
        self.input_cookie_file.setMinimumHeight(34)
        self.btn_browse_cookie = QPushButton()
        self.btn_browse_cookie.setObjectName("GhostButton")
        self.btn_browse_cookie.setMinimumHeight(34)
        self.btn_clear_cookie = QPushButton()
        self.btn_clear_cookie.setObjectName("GhostButton")
        self.btn_clear_cookie.setMinimumHeight(34)
        self.btn_cookie_help = QPushButton()
        self.btn_cookie_help.setObjectName("GhostButton")
        self.btn_cookie_help.setMinimumHeight(34)
        cookie_row.addWidget(self.lbl_cookie)
        cookie_row.addWidget(self.input_cookie_file, 1)
        cookie_row.addWidget(self.btn_browse_cookie)
        cookie_row.addWidget(self.btn_clear_cookie)
        cookie_row.addWidget(self.btn_cookie_help)

        self.lbl_cookie_hint = QLabel()
        self.lbl_cookie_hint.setObjectName("StatusHint")
        self.lbl_cookie_hint.setWordWrap(True)

        self.lbl_cookie_admin_hint = QLabel()
        self.lbl_cookie_admin_hint.setObjectName("StatusHint")
        self.lbl_cookie_admin_hint.setWordWrap(True)
        self.lbl_cookie_admin_hint.hide()

        dir_row = QHBoxLayout()
        dir_row.setContentsMargins(0, 0, 0, 0)
        dir_row.setSpacing(field_gap)
        self.lbl_dir = QLabel()
        self.lbl_dir.setObjectName("InlineFieldLabel")
        self.lbl_dir.setMinimumWidth(76)
        self.input_default_dir = QLineEdit()
        self.input_default_dir.setObjectName("SearchInput")
        self.input_default_dir.setReadOnly(True)
        self.input_default_dir.setMinimumHeight(34)
        self.btn_change_dir = QPushButton()
        self.btn_change_dir.setObjectName("GhostButton")
        self.btn_change_dir.setMinimumHeight(34)
        dir_row.addWidget(self.lbl_dir)
        dir_row.addWidget(self.input_default_dir, 1)
        dir_row.addWidget(self.btn_change_dir)

        options_layout.addLayout(cookie_row)
        options_layout.addWidget(self.lbl_cookie_hint)
        options_layout.addWidget(self.lbl_cookie_admin_hint)
        options_layout.addLayout(dir_row)
        self.options_card.content_layout.addLayout(options_layout)
        page_body.addWidget(self.options_card)

        self._cookie_full_path = ""
        self._default_dir_path = ""

        self.target_title = QLabel()
        self.target_title.hide()
        self.lbl_default_dir = self.input_default_dir

        self.toolbar_card = VSCard(margins=(18, 14, 18, 14), spacing=0)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_probe = QPushButton()
        self.btn_probe.setObjectName("GhostButton")
        self.btn_probe.setMinimumHeight(38)
        self.btn_download = QPushButton()
        self.btn_download.setObjectName("PrimaryButton")
        self.btn_download.setMinimumHeight(38)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        self.btn_clear.setMinimumHeight(38)
        self.btn_open_dir = QPushButton()
        self.btn_open_dir.setObjectName("NeutralToolButton")
        self.btn_open_dir.setMinimumHeight(38)
        self.btn_clear_legacy = QPushButton()
        self.btn_clear_legacy.setObjectName("GhostButton")
        self.btn_clear_legacy.setMinimumHeight(38)
        action_row.addWidget(self.btn_probe)
        action_row.addWidget(self.btn_download, 1)
        action_row.addWidget(self.btn_clear)
        action_row.addSpacing(4)
        action_row.addWidget(_toolbar_divider())
        action_row.addSpacing(4)
        action_row.addWidget(self.btn_open_dir)
        action_row.addWidget(self.btn_clear_legacy)
        self.toolbar_card.content_layout.addLayout(action_row)
        page_body.addWidget(self.toolbar_card)

        self.list_card = VSCard(spacing=8)
        list_layout = self.list_card.content_layout
        self.list_title = QLabel()
        self.list_title.setObjectName("CardTitle")
        self.download_table = QTableWidget(0, 7)
        self.download_table.setObjectName("DownloadListTable")
        self.download_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.download_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.download_table.setShowGrid(False)
        self.download_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.download_table.setAlternatingRowColors(False)
        self.download_table.verticalHeader().setVisible(False)
        self.download_table.verticalHeader().setDefaultSectionSize(_ROW_SECTION_HEIGHT)
        self.download_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        list_layout.addWidget(self.list_title)
        list_layout.addWidget(self.download_table, 1)
        page_body.addWidget(self.list_card, 1)

        self.lbl_status = QLabel()
        self.lbl_status.hide()
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()

        self.notice_body = QLabel()
        self.notice_body.hide()
        self.section_title = QLabel()
        self.section_title.hide()
        self.section_hint = QLabel()
        self.section_hint.hide()

        self.btn_download.setEnabled(False)

    def set_download_texts(self, texts: dict) -> None:
        self._texts = dict(texts)
        self.lbl_cookie.setText(texts.get("download_cookie_label", ""))
        self.lbl_dir.setText(texts.get("download_dir_label", ""))
        self.lbl_cookie_hint.setText(texts.get("download_cookie_hint", ""))
        self.lbl_cookie_admin_hint.setText(texts.get("download_cookie_admin_hint", ""))
        self.btn_browse_cookie.setText(texts.get("download_cookie_browse", ""))
        self.btn_clear_cookie.setText(texts.get("download_cookie_clear", ""))
        self.btn_cookie_help.setText(texts.get("download_cookie_help_btn", ""))
        self.btn_cookie_help.setToolTip(texts.get("download_cookie_help_body", ""))
        self.input_cookie_file.setPlaceholderText(texts.get("download_cookie_placeholder", ""))
        self.input_default_dir.setPlaceholderText(texts.get("download_dir_placeholder", ""))
        for row in range(self.download_table.rowCount()):
            btn = self.row_action_button(row)
            if btn is not None:
                btn.setText(texts.get("download_row_download", ""))
                btn.setToolTip(texts.get("download_row_download_tip", ""))

    def clear_cookie_file(self) -> None:
        self.set_cookie_file_path("")

    def set_cookie_file_path(self, path: str) -> None:
        full_path = str(path or "").strip()
        self._cookie_full_path = full_path
        display = os.path.basename(full_path) if full_path else ""
        self.input_cookie_file.setText(display)
        self.input_cookie_file.setToolTip(full_path)

    def cookie_file_path(self) -> str:
        return str(self._cookie_full_path or "").strip()

    def set_cookie_admin_hint_visible(self, visible: bool) -> None:
        label = self.lbl_cookie_admin_hint
        label.setProperty("state", "warn" if visible else "neutral")
        style = label.style()
        style.unpolish(label)
        style.polish(label)
        if visible:
            label.show()
        else:
            label.hide()

    def set_default_dir_label(self, path: str) -> None:
        full_path = str(path or "").strip()
        self._default_dir_path = full_path
        self.input_default_dir.setText(full_path)
        self.input_default_dir.setToolTip(full_path)

    def set_list_headers(self, headers: list[str]) -> None:
        self.download_table.setColumnCount(len(headers))
        self.download_table.setHorizontalHeaderLabels(headers)
        header = self.download_table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(COL_INDEX, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_TITLE, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(COL_QUALITY, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(COL_PATH, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_ACTION, QHeaderView.ResizeMode.Fixed)
        self.download_table.setColumnWidth(COL_INDEX, 40)
        self.download_table.setColumnWidth(COL_TITLE, 220)
        self.download_table.setColumnWidth(COL_QUALITY, 112)
        self.download_table.setColumnWidth(COL_PROGRESS, 72)
        self.download_table.setColumnWidth(COL_ACTION, 72)
        header.setMinimumSectionSize(36)

    def default_dir_path(self) -> str:
        return str(self._default_dir_path or "").strip()

    def clear_download_list(self) -> None:
        self.download_table.setRowCount(0)

    def reset_links_input(self) -> None:
        self.links_input.document().clear()
        self.links_input.setAcceptRichText(False)
        self.links_input.setPlaceholderText(self._texts.get("download_links_placeholder", ""))

    def reset_action_state(self) -> None:
        self.btn_probe.setEnabled(True)
        self.btn_download.setEnabled(False)

    def prepare_probe_rows(self, links: list[str]) -> None:
        texts = self._texts
        self.clear_download_list()
        for index, url in enumerate(links, start=1):
            row = self.download_table.rowCount()
            self.download_table.insertRow(row)
            index_item = QTableWidgetItem(str(index))
            index_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            index_item.setData(Qt.ItemDataRole.UserRole, url)
            self.download_table.setItem(row, COL_INDEX, index_item)
            display_url = _elide_middle(url, limit=72)
            title_item = QTableWidgetItem(display_url)
            title_item.setToolTip(url)
            title_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self.download_table.setItem(row, COL_TITLE, title_item)
            _set_table_item(
                self.download_table,
                row,
                COL_STATUS,
                texts.get("download_row_probing", ""),
                align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            )
            self.download_table.setCellWidget(row, COL_PROGRESS, _wrap_table_cell(_make_row_progress_bar(), center=True))
            _set_table_item(self.download_table, row, COL_PATH, "")
            placeholder = QComboBox()
            placeholder.setObjectName("DownloadRowCombo")
            placeholder.setFixedHeight(_ROW_WIDGET_HEIGHT)
            placeholder.setEnabled(False)
            self.download_table.setCellWidget(row, COL_QUALITY, _wrap_table_cell(placeholder))
            btn = _make_row_action_button(
                texts.get("download_row_download", ""),
                tooltip=texts.get("download_row_download_tip", ""),
            )
            btn.setEnabled(False)
            self.download_table.setCellWidget(row, COL_ACTION, _wrap_table_cell(btn, center=True))

    def row_url(self, row: int) -> str:
        item = self.download_table.item(int(row), COL_INDEX)
        if item is None:
            return ""
        return str(item.data(Qt.ItemDataRole.UserRole) or "")

    def row_quality(self, row: int) -> str:
        widget = self._cell_inner_widget(int(row), COL_QUALITY)
        if isinstance(widget, QComboBox) and widget.isEnabled():
            return str(widget.currentData() or "best")
        return "best"

    def row_action_button(self, row: int) -> QPushButton | None:
        widget = self._cell_inner_widget(int(row), COL_ACTION)
        return widget if isinstance(widget, QPushButton) else None

    def row_progress_bar(self, row: int) -> QProgressBar | None:
        widget = self._cell_inner_widget(int(row), COL_PROGRESS)
        return widget if isinstance(widget, QProgressBar) else None

    def _cell_inner_widget(self, row: int, column: int) -> QWidget | None:
        host = self.download_table.cellWidget(int(row), int(column))
        if host is None:
            return None
        layout = host.layout()
        if layout is None:
            return host
        for index in range(layout.count()):
            item = layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                return widget
        return host

    def set_row_probe_result(self, row: int, *, title: str, ok: bool, status: str, heights: list[int]) -> None:
        display_title = _elide_middle(title, limit=64)
        title_item = self.download_table.item(int(row), COL_TITLE)
        if title_item is not None:
            title_item.setText(display_title)
            title_item.setToolTip(title)
        _set_table_item(
            self.download_table,
            int(row),
            COL_STATUS,
            status,
            align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        )
        combo = _make_quality_combo(self._texts, heights if ok else [])
        combo.setEnabled(bool(ok))
        self.download_table.setCellWidget(int(row), COL_QUALITY, _wrap_table_cell(combo))
        btn = self.row_action_button(row)
        if btn is not None:
            btn.setEnabled(bool(ok))

    def row_can_download(self, row: int) -> bool:
        btn = self.row_action_button(row)
        return bool(btn and btn.isEnabled())

    def downloadable_rows(self) -> list[int]:
        return [row for row in range(self.download_table.rowCount()) if self.row_can_download(row)]

    def set_row_downloading(self, row: int) -> None:
        texts = self._texts
        _set_table_item(
            self.download_table,
            int(row),
            COL_STATUS,
            texts.get("download_task_running", ""),
            align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        )
        progress = self.row_progress_bar(row)
        if progress is not None:
            progress.setValue(0)
            progress.setFormat("%p%")
        btn = self.row_action_button(row)
        if btn is not None:
            btn.setEnabled(False)
        combo = self._cell_inner_widget(int(row), COL_QUALITY)
        if isinstance(combo, QComboBox):
            combo.setEnabled(False)

    def update_row_progress(self, row: int, percent: int) -> None:
        progress = self.row_progress_bar(row)
        if progress is None:
            return
        value = max(0, min(100, int(percent)))
        progress.setValue(value)
        progress.setFormat("%p%")

    def set_row_download_result(self, row: int, *, ok: bool, status: str, path: str) -> None:
        _set_table_item(
            self.download_table,
            int(row),
            COL_STATUS,
            status,
            align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
        )
        progress = self.row_progress_bar(row)
        if progress is not None:
            progress.setValue(100 if ok else 0)
            progress.setFormat("100%" if ok else "—")
        display_path = _elide_middle(path, limit=80)
        _set_table_item(self.download_table, int(row), COL_PATH, display_path, tooltip=path)
        btn = self.row_action_button(row)
        if btn is not None:
            btn.setEnabled(True)
        combo = self._cell_inner_widget(int(row), COL_QUALITY)
        if isinstance(combo, QComboBox):
            combo.setEnabled(True)

    # Legacy aliases used elsewhere
    probe_table = property(lambda self: self.download_table)
    tasks_table = property(lambda self: self.download_table)
    probe_title = property(lambda self: self.list_title)
    tasks_title = property(lambda self: self.list_title)

    def clear_probe_rows(self) -> None:
        self.clear_download_list()

    def clear_task_rows(self) -> None:
        pass

    def show_probe_card(self, visible: bool) -> None:
        del visible

    def set_probe_headers(self, headers: list[str]) -> None:
        self.set_list_headers(headers)

    def set_task_headers(self, headers: list[str]) -> None:
        self.set_list_headers(headers)
