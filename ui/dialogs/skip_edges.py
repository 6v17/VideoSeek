"""Dialog for optional multi-range skip windows. Empty means no filtering."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from src.app.i18n import get_texts
from src.services.search_skip_ranges import (
    format_search_skip_range_item,
    normalize_search_skip_ranges_text,
    parse_search_skip_range_item,
    parse_search_skip_ranges,
    validate_search_skip_ranges,
    format_duration_token as _format_duration_token,
)
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size

from .app_message import AppMessageDialog
from .shell import VSDialogShell


class SkipEdgesDialog(VSDialogShell):
    def __init__(self, parent=None, is_dark=True, language="zh", ranges_text=""):
        self.language = language
        self.texts = get_texts(language)
        self._is_dark = bool(is_dark)
        self._ranges_text = normalize_search_skip_ranges_text(ranges_text)

        super().__init__(
            parent,
            title=self.texts["skip_edges_title"],
            body=self.texts["skip_edges_hint"],
            card_margins=(16, 16, 16, 16),
            card_spacing=10,
            outer_margins=(12, 12, 12, 12),
        )
        apply_dialog_size(
            self,
            QSize(560, 380),
            QSize(480, 320),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("DialogRulesTable")
        self.table.setHorizontalHeaderLabels(
            [
                self.texts["skip_edges_col_start"],
                self.texts["skip_edges_col_end"],
            ]
        )
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.content_layout.addWidget(self.table, 1)

        toolbar_host = QWidget()
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.empty_hint = QLabel(self.texts["skip_edges_empty"])
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        toolbar.addWidget(self.empty_hint, 1)
        self.btn_add = QPushButton(self.texts["skip_edges_add"])
        self.btn_add.setObjectName("GhostButton")
        self.btn_remove = QPushButton(self.texts["skip_edges_remove"])
        self.btn_remove.setObjectName("GhostButton")
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_remove)
        self.content_layout.addWidget(toolbar_host)

        self.add_footer_button(
            self.texts["cancel"],
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            self.texts["skip_edges_apply"],
            object_name="PrimaryButton",
            on_click=self._apply,
            default=True,
        )

        self.btn_add.clicked.connect(lambda: self._append_row("", ""))
        self.btn_remove.clicked.connect(self._remove_selected_row)
        self._load_ranges(self._ranges_text)

    def ranges_text(self) -> str:
        return self._ranges_text

    def _append_row(self, start_text, end_text):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(start_text))
        self.table.setItem(row, 1, QTableWidgetItem(end_text))

    def _load_ranges(self, ranges_text):
        normalized = normalize_search_skip_ranges_text(ranges_text)
        if not normalized:
            self._append_row("", "")
            return
        for rule in parse_search_skip_ranges(normalized):
            if rule.get("kind") == "from_end":
                self._append_row("end", _format_duration_token(rule.get("amount")))
            else:
                self._append_row(
                    _format_duration_token(rule.get("start")),
                    _format_duration_token(rule.get("end")),
                )
        if self.table.rowCount() == 0:
            self._append_row("", "")

    def _remove_selected_row(self):
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
        if self.table.rowCount() == 0:
            self._append_row("", "")

    def _apply(self):
        parts = []
        for row in range(self.table.rowCount()):
            start_item = self.table.item(row, 0)
            end_item = self.table.item(row, 1)
            start_text = (start_item.text() if start_item else "").strip()
            end_text = (end_item.text() if end_item else "").strip()
            if not start_text and not end_text:
                continue
            if start_text.lower() == "end":
                rule_text = f"end-{end_text}"
            else:
                rule_text = f"{start_text}-{end_text}"
            try:
                parse_search_skip_range_item(rule_text, row)
            except (TypeError, ValueError):
                AppMessageDialog(
                    self.texts["skip_edges_title"],
                    self.texts["skip_edges_invalid_row"].format(row=row + 1),
                    kind="warning",
                    parent=self,
                    is_dark=self._is_dark,
                    language=self.language,
                ).exec()
                return
            parts.append(format_search_skip_range_item(parse_search_skip_range_item(rule_text, row)))

        normalized = normalize_search_skip_ranges_text("; ".join(parts))
        ok, _ = validate_search_skip_ranges(normalized)
        if not ok:
            AppMessageDialog(
                self.texts["skip_edges_title"],
                self.texts["skip_edges_invalid"],
                kind="warning",
                parent=self,
                is_dark=self._is_dark,
                language=self.language,
            ).exec()
            return
        self._ranges_text = normalized
        self.accept()
