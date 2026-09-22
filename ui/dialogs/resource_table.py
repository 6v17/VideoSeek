import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from src.app.i18n import get_texts
from ui.widgets.styles import theme_color_map

from .common import SortableTableWidgetItem
from .shell import VSDialogShell


class ResourceTableDialog(VSDialogShell):
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
        resolved_title = title or get_texts(language).get("details_title_default", "Details")
        super().__init__(
            parent,
            title=resolved_title,
            body=str(subtitle or ""),
            minimum_width=900,
            outer_margins=(14, 14, 14, 14),
            card_margins=(20, 18, 20, 14),
            card_spacing=14,
        )
        self.is_dark = bool(is_dark)
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
        self.subtitle_label = self.body_label
        self._issue_brush = QBrush(QColor(theme_color_map(self.is_dark).get("WARN", "#c98700")))

        self.setMinimumSize(920, 560)
        self.resize(1100, 660)

        # Flat filter + counts — no nested KPI cards.
        toolbar = QWidget()
        toolbar.setObjectName("DialogToolbar")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.input_filter = QLineEdit()
        self.input_filter.setObjectName("SearchInput")
        self.input_filter.setPlaceholderText(self.texts["details_filter_placeholder"])
        self.input_filter.setClearButtonEnabled(True)
        self.toggle_issues = QCheckBox(self.texts["details_show_issues"])
        self.btn_reset_filter = QPushButton(self.texts["details_reset_filter"])
        self.btn_reset_filter.setObjectName("GhostButton")
        self.btn_reset_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_issues.setVisible(callable(self.issue_row_predicate))
        filter_row.addWidget(self.input_filter, 1)
        filter_row.addWidget(self.toggle_issues, 0, Qt.AlignmentFlag.AlignVCenter)
        filter_row.addWidget(self.btn_reset_filter, 0)
        toolbar_layout.addLayout(filter_row)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("DialogMetaLine")
        self.meta_label.setWordWrap(True)
        # Back-compat aliases used by older callers / tests that poke summary_* cards.
        self.summary_total = self.meta_label
        self.summary_visible = self.meta_label
        self.summary_issues = self.meta_label
        toolbar_layout.addWidget(self.meta_label)

        self.summary_hint = QLabel(self.summary_text)
        self.summary_hint.setObjectName("Hint")
        self.summary_hint.setWordWrap(True)
        self.summary_hint.setVisible(bool(self.summary_text))
        toolbar_layout.addWidget(self.summary_hint)
        self.content_layout.addWidget(toolbar)

        table_host = QFrame()
        table_host.setObjectName("DialogTableHost")
        table_host_layout = QVBoxLayout(table_host)
        table_host_layout.setContentsMargins(0, 0, 0, 0)
        table_host_layout.setSpacing(0)

        self.table = QTableWidget(0, len(self.headers))
        self.table.setObjectName("ResourceDialogTable")
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(self.selection_mode)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(False)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(self.allow_sorting)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.setMinimumHeight(340)
        table_host_layout.addWidget(self.table)
        self.content_layout.addWidget(table_host, 1)

        self.status_hint = QLabel("")
        self.status_hint.setObjectName("DialogStatusHint")
        self.status_hint.setWordWrap(True)
        self.content_layout.addWidget(self.status_hint)

        self.clear_footer(keep_stretch=False)
        self._utility_menu = None
        self.btn_copy = QPushButton(self.texts["details_copy_json"])
        self.btn_export = QPushButton(self.texts["details_export_json"])
        self.btn_copy_row = QPushButton(self._inline_text("复制选中行", "Copy Selected"))
        self.btn_copy.hide()
        self.btn_export.hide()
        self.btn_copy_row.hide()
        if self.show_utility_actions:
            self.btn_utility = self.add_footer_button(
                self.texts.get("details_export_menu", self._inline_text("导出", "Export")),
                object_name="GhostButton",
            )
            self.btn_utility.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.btn_utility.setAutoDefault(False)
            self.btn_utility.setDefault(False)
            self._utility_menu = QMenu(self.btn_utility)
            self._utility_menu.addAction(self.texts["details_copy_json"], self._copy_json)
            self._utility_menu.addAction(self.texts["details_export_json"], self._export_json)
            self.btn_utility.setMenu(self._utility_menu)
        else:
            self.btn_utility = QPushButton(self.texts.get("details_export_menu", "Export"))
            self.btn_utility.hide()

        self._footer_extra_buttons = []
        for action in self.extra_actions:
            if action.get("footer", True) is False:
                continue
            object_name = str(action.get("object_name", "") or "").strip() or "GhostButton"
            if object_name == "Ghost":
                object_name = "GhostButton"
            button = self.add_footer_button(
                action.get("label", "Action"),
                object_name=object_name,
                on_click=lambda _checked=False, handler=action.get("handler"): (
                    handler(self) if callable(handler) else None
                ),
            )
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoDefault(False)
            button.setDefault(False)
            self._footer_extra_buttons.append(button)
        self.add_footer_stretch()
        if self.confirm_mode:
            self.btn_cancel = self.add_footer_button(
                self.texts["cancel"],
                object_name="GhostButton",
                on_click=self.reject,
            )
            self.btn_close = self.add_footer_button(
                self.confirm_text,
                object_name="PrimaryButton",
                on_click=self.accept,
                default=True,
            )
        else:
            self.btn_cancel = QPushButton(self.texts["cancel"])
            self.btn_cancel.hide()
            self.btn_close = self.add_footer_button(
                self.texts["close"],
                object_name="PrimaryButton",
                on_click=self.accept,
                default=True,
            )

        self._refresh_rows()
        self._apply_column_layout()

        self.input_filter.textChanged.connect(self._refresh_rows)
        if self.toggle_issues.isVisible():
            self.toggle_issues.toggled.connect(self._refresh_rows)
        self.btn_reset_filter.clicked.connect(self.reset_filters)
        if callable(self.row_double_click_handler):
            self.table.itemDoubleClicked.connect(self._handle_item_double_click)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        copy_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        copy_shortcut.activated.connect(self._copy_selected_cell)

    def _inline_text(self, zh_text, en_text):
        return en_text if self.texts["close"].lower() == "close" else zh_text

    def set_rows(self, rows, row_payloads=None):
        self.rows = list(rows or [])
        self.row_payloads = list(row_payloads or self.rows)
        self._refresh_rows()
        self._apply_column_layout()

    def set_subtitle(self, text):
        self.set_body(str(text or ""))

    def set_summary_text(self, text):
        self.summary_text = str(text or "")
        self.summary_hint.setText(self.summary_text)
        self.summary_hint.setVisible(bool(self.summary_text))

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
        filtered_pairs = [
            (row, payload)
            for row, payload in zip(self.rows, self.row_payloads)
            if self._matches_filter(row)
        ]
        self.filtered_rows = [row for row, _ in filtered_pairs]
        self.filtered_payloads = [payload for _, payload in filtered_pairs]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for row_data in self.filtered_rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            is_issue = self._is_issue_row(row_data)
            for col_index, value in enumerate(row_data):
                item = SortableTableWidgetItem(value)
                if col_index == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                if is_issue:
                    item.setForeground(self._issue_brush)
                self.table.setItem(row_index, col_index, item)
        self.table.setSortingEnabled(self.allow_sorting)

        total_rows = len(self.rows)
        visible_rows = len(self.filtered_rows)
        issue_rows = sum(1 for row in self.rows if self._is_issue_row(row))
        self.meta_label.setText(
            self.texts.get(
                "details_meta_line",
                "{total} total · {visible} shown · {issues} issues",
            ).format(total=total_rows, visible=visible_rows, issues=issue_rows)
        )
        self.meta_label.setVisible(True)
        if not self.filtered_rows:
            self.status_hint.setText(self.texts["details_empty"])
        else:
            self.status_hint.setText(
                self.texts["details_showing_count"].format(
                    visible=visible_rows,
                    total=total_rows,
                )
            )

    def _apply_column_layout(self):
        if not self.headers:
            return
        header = self.table.horizontalHeader()
        stretch_col = self.stretch_column
        if stretch_col < 0 or stretch_col >= len(self.headers):
            stretch_col = len(self.headers) - 1

        fixed_keys = {int(k) for k in self.fixed_column_widths.keys()}
        fixed_total = 0
        for col in range(len(self.headers)):
            if col in fixed_keys:
                continue
            self.table.resizeColumnToContents(col)
            width = self.table.columnWidth(col)
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.table.setColumnWidth(col, max(80, min(width, 620)))

        for col, width in self.fixed_column_widths.items():
            col_index = int(col)
            col_width = int(width)
            if 0 <= col_index < len(self.headers) and col_width > 0:
                header.setSectionResizeMode(col_index, QHeaderView.Fixed)
                self.table.setColumnWidth(col_index, col_width)
                fixed_total += col_width

        if 0 <= stretch_col < len(self.headers) and stretch_col not in fixed_keys:
            viewport_w = max(0, int(self.table.viewport().width()) or int(self.table.width()) or 0)
            if viewport_w > 0 and fixed_total + 120 < viewport_w:
                header.setSectionResizeMode(stretch_col, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(stretch_col, QHeaderView.Interactive)
                self.table.setColumnWidth(
                    stretch_col, max(self.table.columnWidth(stretch_col), 360)
                )

        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _copy_json(self):
        QApplication.clipboard().setText(
            json.dumps(
                {"headers": self.headers, "rows": self.filtered_rows},
                ensure_ascii=False,
                indent=2,
            )
        )
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
        QApplication.clipboard().setText(
            "\n".join(f"{header}: {value}" for header, value in zip(self.headers, row_data))
        )
        self.status_hint.setText(self.texts["details_copy_done"])

    def _copy_selected_cell(self):
        item = self.table.currentItem()
        if item is not None and str(item.text() or "").strip():
            QApplication.clipboard().setText(item.text())
            self.status_hint.setText(self.texts["details_copy_done"])
            return
        selected_indexes = self.table.selectionModel().selectedRows()
        if not selected_indexes:
            self.status_hint.setText(self.texts["details_nothing_selected"])
            return
        row_index = selected_indexes[0].row()
        if not (0 <= row_index < len(self.filtered_rows)):
            self.status_hint.setText(self.texts["details_nothing_selected"])
            return
        row_data = self.filtered_rows[row_index]
        QApplication.clipboard().setText("\t".join(str(value) for value in row_data))
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
                json.dump(
                    {"headers": self.headers, "rows": self.filtered_rows},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
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
        return [
            self.filtered_payloads[row]
            for row in selected_indexes
            if 0 <= row < len(self.filtered_payloads)
        ]

    def remove_selected_payloads(self):
        selected = self.get_selected_payloads()
        if not selected:
            return 0
        remaining_pairs = [
            (row, payload)
            for row, payload in zip(self.rows, self.row_payloads)
            if payload not in selected
        ]
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
        context_actions = [
            action for action in self.extra_actions if action.get("context", True) is not False
        ]
        if self.get_selected_payloads() and context_actions:
            menu.addSeparator()
            for action in context_actions:
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
