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
from src.utils import (
    ensure_sampling_fps_rules_open_tail,
    normalize_sampling_fps_rules_text,
    validate_sampling_fps_rules,
    validate_sampling_fps_rules_full_coverage,
)
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size

from .app_message import AppMessageDialog
from .shell import VSDialogShell


class SamplingRulesDialog(VSDialogShell):
    def __init__(self, parent=None, is_dark=True, language="zh", rules_text=""):
        self.language = language
        self.texts = get_texts(language)
        self._is_dark = bool(is_dark)
        self._rules_text = normalize_sampling_fps_rules_text(rules_text)

        super().__init__(
            parent,
            title=self.texts["sampling_rules_title"],
            body=self.texts["sampling_rules_hint"],
            card_margins=(16, 16, 16, 16),
            card_spacing=10,
            outer_margins=(12, 12, 12, 12),
        )
        apply_dialog_size(
            self,
            QSize(760, 460),
            QSize(620, 380),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("DialogRulesTable")
        self.table.setHorizontalHeaderLabels(
            [
                self.texts["sampling_rules_col_start"],
                self.texts["sampling_rules_col_end"],
                self.texts["sampling_rules_col_fps"],
            ]
        )
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.content_layout.addWidget(self.table, 1)

        toolbar_host = QWidget()
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.empty_hint = QLabel(self.texts["sampling_rules_empty"])
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        toolbar.addWidget(self.empty_hint, 1)
        self.btn_add = QPushButton(self.texts["sampling_rules_add"])
        self.btn_add.setObjectName("GhostButton")
        self.btn_remove = QPushButton(self.texts["sampling_rules_remove"])
        self.btn_remove.setObjectName("GhostButton")
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_remove)
        self.content_layout.addWidget(toolbar_host)

        self.btn_cancel = self.add_footer_button(
            self.texts["cancel"],
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.btn_apply = self.add_footer_button(
            self.texts["sampling_rules_apply"],
            object_name="PrimaryButton",
            on_click=self._apply_rules,
            default=True,
        )

        self.btn_add.clicked.connect(lambda: self._append_row("", "", ""))
        self.btn_remove.clicked.connect(self._remove_selected_row)

        self._load_rules(self._rules_text)

    def _append_row(self, start_text, end_text, fps_text):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(start_text))
        self.table.setItem(row, 1, QTableWidgetItem(end_text))
        self.table.setItem(row, 2, QTableWidgetItem(fps_text))

    def _load_rules(self, rules_text):
        normalized = normalize_sampling_fps_rules_text(rules_text)
        if not normalized:
            self._append_row("", "", "")
            return
        for chunk in normalized.split(";"):
            item = chunk.strip()
            if not item or "=" not in item or "-" not in item:
                continue
            range_part, fps_part = item.split("=", 1)
            start_text, end_text = range_part.split("-", 1)
            self._append_row(start_text.strip(), end_text.strip(), fps_part.strip())
        if self.table.rowCount() == 0:
            self._append_row("", "", "")

    def _remove_selected_row(self):
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)
        if self.table.rowCount() == 0:
            self._append_row("", "", "")

    def _apply_rules(self):
        parts = []
        for row in range(self.table.rowCount()):
            start_item = self.table.item(row, 0)
            end_item = self.table.item(row, 1)
            fps_item = self.table.item(row, 2)
            start_text = (start_item.text() if start_item else "").strip()
            end_text = (end_item.text() if end_item else "").strip()
            fps_text = (fps_item.text() if fps_item else "").strip()
            if not start_text and not end_text and not fps_text:
                continue
            rule_text = f"{start_text}-{end_text}={fps_text}"
            is_valid, _ = validate_sampling_fps_rules(rule_text)
            if not is_valid:
                AppMessageDialog(
                    self.texts["sampling_rules_title"],
                    self.texts["sampling_rules_invalid_row"].format(row=row + 1),
                    kind="warning",
                    parent=self,
                    is_dark=self._is_dark,
                    language=self.language,
                ).exec()
                return
            parts.append(rule_text)

        normalized_rules = normalize_sampling_fps_rules_text("; ".join(parts))
        normalized_rules = ensure_sampling_fps_rules_open_tail(normalized_rules, default_tail_fps=1)
        all_valid, invalid_ref = validate_sampling_fps_rules_full_coverage(normalized_rules)
        if not all_valid:
            invalid_row = None
            token = str(invalid_ref or "").strip()
            if token.lower().startswith("rule "):
                raw_num = token[5:].strip()
                if raw_num.isdigit():
                    invalid_row = int(raw_num)
            message = (
                self.texts["sampling_rules_invalid_row"].format(row=invalid_row)
                if invalid_row
                else self.texts["setting_sampling_fps_rules_invalid"]
            )
            AppMessageDialog(
                self.texts["sampling_rules_title"],
                message,
                kind="warning",
                parent=self,
                is_dark=self._is_dark,
                language=self.language,
            ).exec()
            return

        self._rules_text = normalized_rules
        self.accept()

    def rules_text(self):
        return self._rules_text
