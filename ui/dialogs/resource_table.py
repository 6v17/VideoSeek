import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.widgets.scaffold import VSCard

from .common import SortableTableWidgetItem

class ResourceTableDialog(QDialog):
    def __init__(
        self,
        parent=None,
        is_dark=True,
        language="zh",
        title="",
        subtitle="",
        headers=None,
        rows=None,
        export_default_name="details.json",
        stretch_column=-1,
        fixed_column_widths=None,
        confirm_mode=False,
        confirm_text="",
        issue_row_predicate=None,
        summary_text="",
        row_payloads=None,
        extra_actions=None,
        selection_mode=QAbstractItemView.SingleSelection,
        row_double_click_handler=None,
        allow_sorting=True,
        show_utility_actions=True,
    ):
        super().__init__(parent)
        self.texts = get_texts(language)
        self.rows = list(rows or [])
        self.headers = list(headers or [])
        self.export_default_name = export_default_name
        self.stretch_column = int(stretch_column)
        self.fixed_column_widths = dict(fixed_column_widths or {})
        self.confirm_mode = bool(confirm_mode)
        self.confirm_text = confirm_text or self.texts["confirm_action"]
        self.issue_row_predicate = issue_row_predicate
        self.summary_text = summary_text
        self.row_payloads = list(row_payloads or self.rows)
        self.extra_actions = list(extra_actions or [])
        self.selection_mode = selection_mode
        self.row_double_click_handler = row_double_click_handler
        self.allow_sorting = bool(allow_sorting)
        self.show_utility_actions = bool(show_utility_actions)
        self.filtered_rows = list(self.rows)
        self.filtered_payloads = list(self.row_payloads)

        self.setWindowTitle(title or self.texts["details_title_default"])
        self.setMinimumSize(860, 540)
        self.resize(1040, 640)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title_label = QLabel(title or self.texts["details_title_default"])
        title_label.setObjectName("DialogPageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Hint")
        subtitle_label.setWordWrap(True)
        self.subtitle_label = subtitle_label

        toolbar_card = VSCard(object_name="ToolbarCard", margins=(14, 12, 14, 12), spacing=10)
        toolbar_layout = toolbar_card.content_layout

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.input_filter = QLineEdit()
        self.input_filter.setPlaceholderText(self.texts["details_filter_placeholder"])
        self.toggle_issues = QCheckBox(self.texts["details_show_issues"])
        self.btn_reset_filter = QPushButton(self.texts["details_reset_filter"])
        self.btn_reset_filter.setObjectName("GhostButton")
        self.toggle_issues.setVisible(callable(self.issue_row_predicate))
        filter_row.addWidget(self.input_filter, 1)
        filter_row.addWidget(self.toggle_issues)
        filter_row.addWidget(self.btn_reset_filter)
        toolbar_layout.addLayout(filter_row)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        self.summary_total = self._build_summary_card(self.texts["details_total_label"], "0")
        self.summary_visible = self._build_summary_card(self.texts["details_visible_label"], "0")
        self.summary_issues = self._build_summary_card(self.texts["details_issues_label"], "0")
        summary_row.addWidget(self.summary_total, 1)
        summary_row.addWidget(self.summary_visible, 1)
        summary_row.addWidget(self.summary_issues, 1)
        toolbar_layout.addLayout(summary_row)

        self.summary_hint = QLabel(self.summary_text)
        self.summary_hint.setObjectName("Hint")
        self.summary_hint.setWordWrap(True)
        self.summary_hint.setVisible(bool(self.summary_text))
        toolbar_layout.addWidget(self.summary_hint)

        self.table = QTableWidget(0, len(self.headers))
        self.table.setObjectName("ResourceDialogTable")
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(self.selection_mode)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(self.allow_sorting)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(360)

        details_card = VSCard(object_name="DetailsCard", margins=(14, 12, 14, 12), spacing=6)
        details_layout = details_card.content_layout
        details_title = QLabel(self._inline_text("选中项详情", "Selected Details"))
        details_title.setObjectName("DialogInlineTitle")
        details_hint = QLabel(self._inline_text("只显示当前选中行的关键信息。", "Shows the key fields for the selected row."))
        details_hint.setObjectName("Hint")
        details_hint.setWordWrap(True)
        self.details_text = QPlainTextEdit()
        self.details_text.setObjectName("DialogPlainBody")
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(96)
        details_layout.addWidget(details_title)
        details_layout.addWidget(details_hint)
        details_layout.addWidget(self.details_text)
        self.details_card = details_card
        self.details_card.hide()

        status_card = QFrame()
        status_card.setObjectName("StatusCard")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        self.status_hint = QLabel("")
        self.status_hint.setObjectName("Hint")
        self.status_hint.setWordWrap(True)
        status_layout.addWidget(self.status_hint)

        button_row = QHBoxLayout()
        self.btn_copy = QPushButton(self.texts["details_copy_json"])
        self.btn_export = QPushButton(self.texts["details_export_json"])
        self.btn_copy_row = QPushButton(self._inline_text("复制选中行", "Copy Selected"))
        self.btn_cancel = QPushButton(self.texts["cancel"])
        self.btn_close = QPushButton(self.texts["close"])
        self.btn_close.setObjectName("PrimaryButton")
        if self.show_utility_actions:
            button_row.addWidget(self.btn_copy)
            button_row.addWidget(self.btn_export)
            button_row.addWidget(self.btn_copy_row)
        else:
            self.btn_copy.hide()
            self.btn_export.hide()
            self.btn_copy_row.hide()
        for action in self.extra_actions:
            button = QPushButton(action.get("label", "Action"))
            object_name = str(action.get("object_name", "") or "").strip()
            if object_name:
                button.setObjectName(object_name)
            button.clicked.connect(lambda _, handler=action.get("handler"): handler(self) if callable(handler) else None)
            button_row.addWidget(button)
        button_row.addStretch()
        if self.confirm_mode:
            self.btn_cancel.setObjectName("GhostButton")
            button_row.addWidget(self.btn_cancel)
            self.btn_close.setText(self.confirm_text)
        button_row.addWidget(self.btn_close)

        root.addWidget(title_label)
        root.addWidget(subtitle_label)
        root.addWidget(toolbar_card)
        root.addWidget(self.table, 1)
        root.addWidget(status_card)
        root.addLayout(button_row)

        self._refresh_rows()
        self._apply_column_layout()

        self.input_filter.textChanged.connect(self._refresh_rows)
        if self.toggle_issues.isVisible():
            self.toggle_issues.toggled.connect(self._refresh_rows)
        self.btn_reset_filter.clicked.connect(self.reset_filters)
        if callable(self.row_double_click_handler):
            self.table.itemDoubleClicked.connect(self._handle_item_double_click)
        self.btn_copy.clicked.connect(self._copy_json)
        self.btn_export.clicked.connect(self._export_json)
        self.btn_copy_row.clicked.connect(self._copy_selected_row)
        if self.confirm_mode:
            self.btn_cancel.clicked.connect(self.reject)
        self.btn_close.clicked.connect(self.accept)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

    def _inline_text(self, zh_text, en_text):
        return en_text if self.texts["close"].lower() == "close" else zh_text

    def set_rows(self, rows, row_payloads=None):
        self.rows = list(rows or [])
        self.row_payloads = list(row_payloads or self.rows)
        self._refresh_rows()
        self._apply_column_layout()

    def set_subtitle(self, text):
        self.subtitle_label.setText(str(text or ""))

    def set_summary_text(self, text):
        self.summary_text = str(text or "")
        self.summary_hint.setText(self.summary_text)
        self.summary_hint.setVisible(bool(self.summary_text))

    def _build_summary_card(self, label_text, value_text):
        card = VSCard(object_name="SummaryCard", margins=(12, 10, 12, 10), spacing=2)
        layout = card.content_layout
        value = QLabel(value_text)
        value.setObjectName("SummaryValue")
        label = QLabel(label_text)
        label.setObjectName("SummaryLabel")
        layout.addWidget(value)
        layout.addWidget(label)
        card.value_label = value
        return card

    def _is_issue_row(self, row_data):
        if not callable(self.issue_row_predicate):
            return False
        try:
            return bool(self.issue_row_predicate(row_data))
        except Exception:
            return False

    def _matches_filter(self, row_data):
        keyword = self.input_filter.text().strip().lower()
        if keyword and keyword not in " ".join(str(value).lower() for value in row_data):
            return False
        if self.toggle_issues.isVisible() and self.toggle_issues.isChecked() and not self._is_issue_row(row_data):
            return False
        return True

    def _refresh_rows(self):
        filtered_pairs = [(row, payload) for row, payload in zip(self.rows, self.row_payloads) if self._matches_filter(row)]
        self.filtered_rows = [row for row, _ in filtered_pairs]
        self.filtered_payloads = [payload for _, payload in filtered_pairs]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row_data in self.filtered_rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            for col_index, value in enumerate(row_data):
                item = SortableTableWidgetItem(value)
                if col_index == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                if self._is_issue_row(row_data):
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(row_index, col_index, item)
        self.table.setSortingEnabled(self.allow_sorting)

        total_rows = len(self.rows)
        visible_rows = len(self.filtered_rows)
        issue_rows = sum(1 for row in self.rows if self._is_issue_row(row))
        self.summary_total.value_label.setText(str(total_rows))
        self.summary_visible.value_label.setText(str(visible_rows))
        self.summary_issues.value_label.setText(str(issue_rows))
        self.status_hint.setText(
            self.texts["details_empty"] if not self.filtered_rows else self.texts["details_showing_count"].format(
                visible=visible_rows,
                total=total_rows,
            )
        )
    def _apply_column_layout(self):
        if not self.headers:
            return
        stretch_col = self.stretch_column
        if stretch_col < 0 or stretch_col >= len(self.headers):
            stretch_col = len(self.headers) - 1

        for col in range(len(self.headers)):
            self.table.resizeColumnToContents(col)
            width = self.table.columnWidth(col)
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, max(80, min(width, 620)))

        for col, width in self.fixed_column_widths.items():
            col_index = int(col)
            col_width = int(width)
            if 0 <= col_index < len(self.headers) and col_width > 0:
                self.table.horizontalHeader().setSectionResizeMode(col_index, QHeaderView.Fixed)
                self.table.setColumnWidth(col_index, col_width)

        if 0 <= stretch_col < len(self.headers) and stretch_col not in {int(k) for k in self.fixed_column_widths.keys()}:
            self.table.setColumnWidth(stretch_col, max(self.table.columnWidth(stretch_col), 360))

    def _update_details(self):
        return

    def _copy_json(self):
        QApplication.clipboard().setText(json.dumps({"headers": self.headers, "rows": self.filtered_rows}, ensure_ascii=False, indent=2))
        self.status_hint.setText(self.texts["details_copy_done"])

    def _copy_selected_row(self):
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            self.status_hint.setText(self.texts["details_nothing_selected"])
            return
        row_index = selected_indexes[0].row()
        if not (0 <= row_index < len(self.filtered_rows)):
            self.status_hint.setText(self.texts["details_nothing_selected"])
            return
        row_data = self.filtered_rows[row_index]
        QApplication.clipboard().setText("\n".join(f"{header}: {value}" for header, value in zip(self.headers, row_data)))
        self.status_hint.setText(self.texts["details_copy_done"])

    def _copy_selected_cell(self):
        item = self.table.currentItem()
        if item is None:
            self.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(item.text())
        self.status_hint.setText(self.texts["details_copy_done"])

    def _export_json(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts["details_export_title"],
            self.export_default_name,
            self.texts["details_export_filter"],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"headers": self.headers, "rows": self.filtered_rows}, handle, ensure_ascii=False, indent=2)
        except Exception:
            self.status_hint.setText(self.texts["details_export_failed"])
            return
        self.status_hint.setText(self.texts["details_export_done"].format(path=path))

    def reset_filters(self):
        self.input_filter.clear()
        if self.toggle_issues.isVisible():
            self.toggle_issues.setChecked(False)
        else:
            self._refresh_rows()

    def get_selected_payloads(self):
        selected_indexes = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        return [self.filtered_payloads[row] for row in selected_indexes if 0 <= row < len(self.filtered_payloads)]

    def remove_selected_payloads(self):
        selected = self.get_selected_payloads()
        if not selected:
            return 0
        remaining_pairs = [(row, payload) for row, payload in zip(self.rows, self.row_payloads) if payload not in selected]
        self.rows = [row for row, _ in remaining_pairs]
        self.row_payloads = [payload for _, payload in remaining_pairs]
        self._refresh_rows()
        return len(selected)

    def _show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if item is not None:
            self.table.selectRow(item.row())

        menu = QMenu(self)
        action_copy_cell = menu.addAction(self._inline_text("复制当前单元格", "Copy Cell"))
        action_copy_row = menu.addAction(self._inline_text("复制当前行", "Copy Row"))
        action_open = None
        if callable(self.row_double_click_handler):
            action_open = menu.addAction(self._inline_text("打开当前项", "Open Item"))

        extra_action_map = {}
        if self.get_selected_payloads():
            menu.addSeparator()
            for action in self.extra_actions:
                menu_action = menu.addAction(action.get("label", self._inline_text("操作", "Action")))
                extra_action_map[menu_action] = action

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == action_copy_cell:
            self._copy_selected_cell()
            return
        if chosen == action_copy_row:
            self._copy_selected_row()
            return
        if action_open is not None and chosen == action_open:
            selected = self.get_selected_payloads()
            if not selected:
                self.status_hint.setText(self.texts["details_nothing_selected"])
                return
            self.row_double_click_handler(self, selected[0], self.table.currentItem())
            return
        action = extra_action_map.get(chosen)
        if action and callable(action.get("handler")):
            action["handler"](self)

    def _handle_item_double_click(self, item):
        row_index = item.row()
        if callable(self.row_double_click_handler) and 0 <= row_index < len(self.filtered_payloads):
            self.row_double_click_handler(self, self.filtered_payloads[row_index], item)

