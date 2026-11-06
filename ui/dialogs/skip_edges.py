"""Dialog for optional skip windows. Clocks, not a text format."""

from PySide6.QtCore import QSize, QTime, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from src.app.i18n import get_texts
from src.services.search_skip_ranges import (
    format_search_skip_range_item,
    normalize_search_skip_ranges_text,
    try_parse_search_skip_ranges,
    validate_search_skip_ranges,
)
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size

from .app_message import AppMessageDialog
from .shell import VSDialogShell


class _NoWheelTimeEdit(QTimeEdit):
    def wheelEvent(self, event):
        event.ignore()


def _seconds_to_time(seconds) -> QTime:
    whole = max(0, int(round(float(seconds or 0))))
    whole = min(whole, 23 * 3600 + 59 * 60 + 59)
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return QTime(int(hours), int(minutes), int(secs))


def _time_to_seconds(value: QTime) -> int:
    return int(value.hour()) * 3600 + int(value.minute()) * 60 + int(value.second())


class _SkipRangeRow(QWidget):
    """One absolute window. The same clocks apply on every video."""

    def __init__(self, texts):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.prefix = QLabel(texts["skip_edges_from"])
        self.prefix.setObjectName("InlineFieldLabel")
        self.start_edit = self._make_time_edit()
        self.to_label = QLabel(texts["skip_edges_to"])
        self.to_label.setObjectName("InlineFieldLabel")
        self.end_edit = self._make_time_edit()

        self.btn_remove = QPushButton(texts["skip_edges_remove"])
        self.btn_remove.setObjectName("GhostButton")
        self.btn_remove.setMinimumHeight(32)

        row.addWidget(self.prefix, 0)
        row.addWidget(self.start_edit, 0)
        row.addWidget(self.to_label, 0)
        row.addWidget(self.end_edit, 0)
        row.addStretch(1)
        row.addWidget(self.btn_remove, 0)

    def _make_time_edit(self) -> QTimeEdit:
        edit = _NoWheelTimeEdit()
        edit.setDisplayFormat("HH:mm:ss")
        edit.setTimeRange(QTime(0, 0, 0), QTime(23, 59, 59))
        edit.setTime(QTime(0, 0, 0))
        edit.setFixedWidth(108)
        edit.setMinimumHeight(32)
        return edit

    def load_rule(self, rule: dict):
        if str(rule.get("kind") or "") == "from_end":
            return
        self.start_edit.setTime(_seconds_to_time(rule.get("start")))
        self.end_edit.setTime(_seconds_to_time(rule.get("end")))

    def range_text(self) -> str:
        start = _time_to_seconds(self.start_edit.time())
        end = _time_to_seconds(self.end_edit.time())
        if start == 0 and end == 0:
            return ""
        if end <= start:
            raise ValueError("end before start")
        return format_search_skip_range_item({"kind": "absolute", "start": start, "end": end})


class SkipEdgesDialog(VSDialogShell):
    def __init__(self, parent=None, is_dark=True, language="zh", ranges_text=""):
        self.language = language
        self.texts = get_texts(language)
        self._is_dark = bool(is_dark)
        self._ranges_text = normalize_search_skip_ranges_text(ranges_text)
        self._rows: list[_SkipRangeRow] = []

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
            QSize(640, 420),
            QSize(520, 340),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(8)
        self._rows_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self._rows_host)
        scroll.setMinimumHeight(168)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.content_layout.addWidget(scroll, 1)

        toolbar_host = QWidget()
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        toolbar.addStretch(1)
        self.btn_add = QPushButton(self.texts["skip_edges_add"])
        self.btn_add.setObjectName("GhostButton")
        toolbar.addWidget(self.btn_add)
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

        self.btn_add.clicked.connect(lambda: self._append_row(None))
        self._load_ranges(self._ranges_text)

    def ranges_text(self) -> str:
        return self._ranges_text

    def _append_row(self, rule):
        row = _SkipRangeRow(self.texts)
        row.btn_remove.clicked.connect(lambda _checked=False, widget=row: self._remove_row(widget))
        if rule is not None:
            row.load_rule(rule)
        insert_at = max(0, self._rows_layout.count() - 1)
        self._rows_layout.insertWidget(insert_at, row)
        self._rows.append(row)
        return row

    def _remove_row(self, row: _SkipRangeRow):
        if row not in self._rows:
            return
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        if not self._rows:
            self._append_row(None)

    def _load_ranges(self, ranges_text):
        normalized = normalize_search_skip_ranges_text(ranges_text)
        rules = try_parse_search_skip_ranges(normalized) if normalized else []
        if not rules:
            self._append_row(None)
            return
        for rule in rules:
            if str(rule.get("kind") or "") == "from_end":
                continue
            self._append_row(rule)
        if not self._rows:
            self._append_row(None)

    def _apply(self):
        parts = []
        for index, row in enumerate(self._rows):
            try:
                text = row.range_text()
            except ValueError:
                AppMessageDialog(
                    self.texts["skip_edges_title"],
                    self.texts["skip_edges_invalid_row"].format(row=index + 1),
                    kind="warning",
                    parent=self,
                    is_dark=self._is_dark,
                    language=self.language,
                ).exec()
                return
            if text:
                parts.append(text)
        normalized = normalize_search_skip_ranges_text("; ".join(parts))
        ok, _detail = validate_search_skip_ranges(normalized)
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
