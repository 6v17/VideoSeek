import webbrowser
import json

from PySide6.QtCore import Qt, Signal, QSize
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QTextBrowser,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from src.app.config import get_app_version, load_config
from src.app.i18n import get_texts
from src.utils import normalize_sampling_fps_rules_text, validate_sampling_fps_rules
from ui.layout import WINDOW_SIZES, apply_dialog_size, message_dialog_min_width


def dialog_palette(is_dark):
    return {
        "bg": "#161c28" if is_dark else "#f3f6fb",
        "card": "#1d2635" if is_dark else "#ffffff",
        "text": "#f3f5f8" if is_dark else "#1d2430",
        "muted": "#9aa6b7" if is_dark else "#617086",
        "accent": "#4a86ff" if is_dark else "#3b6fd8",
        "border": "#2d3950" if is_dark else "#d5ddea",
    }


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, value):
        super().__init__("" if value is None else str(value))
        self._sort_key = self._build_sort_key(value)

    @staticmethod
    def _build_sort_key(value):
        if value is None:
            return (2, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))

        text = str(value).strip()
        if not text:
            return (2, "")

        try:
            return (0, int(text))
        except ValueError:
            pass

        try:
            return (0, float(text))
        except ValueError:
            pass

        return (1, text.lower())

    def __lt__(self, other):
        if isinstance(other, SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)


class AppMessageDialog(QDialog):
    def __init__(self, title, text, kind="info", parent=None, is_dark=True, language="zh", confirm=False):
        super().__init__(parent)
        texts = get_texts(language)
        palette = dialog_palette(is_dark)

        kind_map = {
            "info": ("i", palette["accent"]),
            "success": ("OK", "#2ec27e" if is_dark else "#198754"),
            "warning": ("!", "#e0a100" if is_dark else "#b78103"),
            "error": ("X", "#e55353" if is_dark else "#c0392b"),
        }
        badge_text, badge_color = kind_map.get(kind, kind_map["info"])

        self._result = False
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(
            message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"],
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            )
        )
        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Card {{ background: {palette['card']}; border: 1px solid {palette['border']}; border-radius: 20px; }}
            #Title {{ font-size: 22px; font-weight: 800; }}
            #Body {{ color: {palette['muted']}; font-size: 13px; }}
            #Badge {{
                min-width: 34px; max-width: 34px; min-height: 34px; max-height: 34px;
                border-radius: 17px; background: {badge_color}; color: white; font-weight: 800;
            }}
            QPushButton {{
                border: none; border-radius: 12px; padding: 10px 18px; font-weight: 700;
            }}
            #Primary {{ background: {palette['accent']}; color: white; }}
            #Ghost {{ background: transparent; color: {palette['muted']}; border: 1px solid {palette['border']}; }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel(badge_text)
        badge.setObjectName("Badge")
        badge.setAlignment(Qt.AlignCenter)
        top_text = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("Title")
        body_label = QLabel(text)
        body_label.setObjectName("Body")
        body_label.setWordWrap(True)
        top_text.addWidget(title_label)
        top_text.addWidget(body_label)
        top.addWidget(badge, 0)
        top.addLayout(top_text, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if confirm:
            cancel = QPushButton(texts["cancel"])
            cancel.setObjectName("Ghost")
            cancel.clicked.connect(self.reject)
            ok = QPushButton(texts["confirm_action"])
            ok.setObjectName("Primary")
            ok.clicked.connect(self._accept_confirm)
            buttons.addWidget(cancel)
            buttons.addWidget(ok)
        else:
            ok = QPushButton(texts["close"])
            ok.setObjectName("Primary")
            ok.clicked.connect(self.accept)
            buttons.addWidget(ok)

        layout.addLayout(top)
        layout.addLayout(buttons)
        outer.addWidget(card)

    def _accept_confirm(self):
        self._result = True
        self.accept()

    def confirmed(self):
        return self._result


class AboutDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", version_info=None, about=None):
        super().__init__(parent)
        texts = get_texts(language)
        version_info = version_info or {}
        about = about or {}

        self.setWindowTitle(texts["about_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["about_dialog"]["preferred"],
            WINDOW_SIZES["about_dialog"]["minimum"],
            WINDOW_SIZES["about_dialog"]["screen_margin"],
        )

        palette = dialog_palette(is_dark)
        bg = palette["bg"]
        card = palette["card"]
        text = palette["text"]
        muted = palette["muted"]
        accent = palette["accent"]
        border = palette["border"]

        self.setStyleSheet(f"""
            QDialog {{ background: {bg}; }}
            QLabel {{ color: {text}; background: transparent; }}
            QTextEdit, QTextBrowser {{
                background: {card};
                color: {muted};
                border: 1px solid {border};
                border-radius: 16px;
                padding: 12px;
                font-size: 13px;
            }}
            QPushButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 18px;
                font-weight: 700;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_text = about.get("title", texts["app_name"])
        subtitle_text = about.get("badge", texts["about_badge"])
        title = QLabel(title_text)
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        subtitle = QLabel(subtitle_text)
        subtitle.setStyleSheet(f"color: {muted}; font-size: 12px;")
        subtitle.setWordWrap(True)
        version = QLabel(texts["version_label"].format(version=get_app_version()))
        version.setStyleSheet(f"color: {muted}; font-size: 12px;")
        version_status = QLabel(version_info.get("status_text", texts["version_check_unavailable"]))
        version_status.setStyleSheet(f"color: {muted}; font-size: 13px;")
        version_status.setWordWrap(True)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"background: {border}; max-height: 1px; margin: 8px 0;")

        body = QTextBrowser()
        body.setReadOnly(True)
        body.setOpenExternalLinks(True)
        if about.get("format") == "html":
            body.setHtml(about.get("body", texts["about_body"]))
        else:
            body.setPlainText(about.get("body", texts["about_body"]))

        download_button = QPushButton(texts["download_latest"])
        download_button.setFixedHeight(40)
        download_button.setVisible(bool(version_info.get("download_url")) and version_info.get("has_update"))
        download_button.clicked.connect(lambda: webbrowser.open(version_info["download_url"]))

        close_button = QPushButton(texts["close"])
        close_button.setFixedHeight(40)
        close_button.clicked.connect(self.accept)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(version)
        layout.addWidget(version_status)
        layout.addWidget(divider)
        layout.addWidget(body)
        button_row = QHBoxLayout()
        button_row.addStretch()
        if download_button.isVisible():
            button_row.addWidget(download_button)
        button_row.addWidget(close_button)

        layout.addLayout(button_row)


class NoticeDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", notice=None):
        super().__init__(parent)
        texts = get_texts(language)
        notice = notice or {}

        self.setWindowTitle(texts["notice_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["notice_dialog"]["preferred"],
            WINDOW_SIZES["notice_dialog"]["minimum"],
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        palette = dialog_palette(is_dark)
        bg = palette["bg"]
        card = palette["card"]
        text = palette["text"]
        muted = palette["muted"]
        accent = palette["accent"]
        border = palette["border"]

        self.setStyleSheet(f"""
            QDialog {{ background: {bg}; }}
            QLabel {{ color: {text}; background: transparent; }}
            QTextEdit, QTextBrowser {{
                background: {card};
                color: {muted};
                border: 1px solid {border};
                border-radius: 16px;
                padding: 12px;
                font-size: 13px;
            }}
            QPushButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 18px;
                font-weight: 700;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel(notice.get("title", texts["notice_heading"]))
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        subtitle = QLabel(notice.get("subtitle", texts["notice_subtitle"]))
        subtitle.setStyleSheet(f"color: {muted}; font-size: 12px;")
        subtitle.setWordWrap(True)

        content = QTextBrowser()
        content.setReadOnly(True)
        content.setOpenExternalLinks(True)
        if notice.get("format") == "html":
            content.setHtml(notice.get("body", texts["notice_body"]))
        else:
            content.setPlainText(notice.get("body", texts["notice_body"]))

        button_row = QHBoxLayout()
        button_row.addStretch()
        close_button = QPushButton(texts["close"])
        close_button.setFixedWidth(110)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(content)
        layout.addLayout(button_row)


class LinkEditorDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", initial_links=None):
        super().__init__(parent)
        self.texts = get_texts(language)
        palette = dialog_palette(is_dark)
        self._links = list(initial_links or [])

        self.setWindowTitle(self.texts["network_link_editor_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["notice_dialog"]["preferred"],
            WINDOW_SIZES["notice_dialog"]["minimum"],
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Hint {{ color: {palette['muted']}; font-size: 12px; }}
            QPlainTextEdit {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                padding: 10px;
                font-family: Consolas, 'Microsoft YaHei UI';
                font-size: 12px;
            }}
            QPushButton {{
                border-radius: 10px;
                border: 1px solid {palette['border']};
                padding: 8px 12px;
                color: {palette['text']};
                background: {palette['card']};
            }}
            #Primary {{ background: {palette['accent']}; color: white; border-color: {palette['accent']}; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(self.texts["network_link_editor_title"])
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        hint = QLabel(self.texts["network_link_editor_hint"])
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(self.texts["network_link_editor_placeholder"])
        self.editor.setPlainText("\n".join(self._links))

        toolbar = QHBoxLayout()
        self.btn_import = QPushButton(self.texts["network_link_editor_import"])
        self.btn_clear = QPushButton(self.texts["network_link_editor_clear"])
        toolbar.addWidget(self.btn_import)
        toolbar.addWidget(self.btn_clear)
        toolbar.addStretch()

        actions = QHBoxLayout()
        actions.addStretch()
        self.btn_cancel = QPushButton(self.texts["cancel"])
        self.btn_ok = QPushButton(self.texts["confirm_action"])
        self.btn_ok.setObjectName("Primary")
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_ok)

        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(self.editor, 1)
        root.addLayout(toolbar)
        root.addLayout(actions)

        self.btn_import.clicked.connect(self._import_file)
        self.btn_clear.clicked.connect(self.editor.clear)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_ok.clicked.connect(self.accept)

    def get_links(self):
        lines = [line.strip() for line in self.editor.toPlainText().splitlines()]
        deduped = []
        seen = set()
        for line in lines:
            if not line or line.startswith("#"):
                continue
            if line in seen:
                continue
            seen.add(line)
            deduped.append(line)
        return deduped

    def _import_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["network_links_file_title"],
            "",
            self.texts["network_links_file_filter"],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                imported = [line.rstrip("\n") for line in handle]
        except Exception:
            return
        existing = self.editor.toPlainText().splitlines()
        merged = [line for line in existing if line.strip()]
        merged.extend(imported)
        self.editor.setPlainText("\n".join(merged))


class SamplingRulesDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", rules_text=""):
        super().__init__(parent)
        self.language = language
        self.texts = get_texts(language)
        palette = dialog_palette(is_dark)
        self._rules_text = normalize_sampling_fps_rules_text(rules_text)

        self.setWindowTitle(self.texts["sampling_rules_title"])
        apply_dialog_size(
            self,
            QSize(760, 460),
            QSize(620, 380),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )
        self.setModal(True)
        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Hint {{ color: {palette['muted']}; font-size: 12px; }}
            QTableWidget {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                gridline-color: {palette['border']};
                alternate-background-color: {"#202a3b" if is_dark else "#f7f9fd"};
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            QTableWidget::item:hover {{
                background: {"#2a3a57" if is_dark else "#eef4ff"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected {{
                background: {"#35507c" if is_dark else "#dce8ff"};
                color: {palette['text']};
            }}
            QHeaderView::section {{
                color: {palette['muted']};
                background: {palette['card']};
                border: none;
                border-bottom: 1px solid {palette['border']};
                padding: 10px 8px;
            }}
            QPushButton {{
                border-radius: 10px;
                border: 1px solid {palette['border']};
                padding: 8px 12px;
                color: {palette['text']};
                background: {palette['card']};
            }}
            #Primary {{ background: {palette['accent']}; color: white; border-color: {palette['accent']}; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel(self.texts["sampling_rules_title"])
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        hint = QLabel(self.texts["sampling_rules_hint"])
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [
                self.texts["sampling_rules_col_start"],
                self.texts["sampling_rules_col_end"],
                self.texts["sampling_rules_col_fps"],
            ]
        )
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)

        toolbar = QHBoxLayout()
        self.empty_hint = QLabel(self.texts["sampling_rules_empty"])
        self.empty_hint.setObjectName("Hint")
        self.empty_hint.setWordWrap(True)
        toolbar.addWidget(self.empty_hint, 1)
        self.btn_add = QPushButton(self.texts["sampling_rules_add"])
        self.btn_remove = QPushButton(self.texts["sampling_rules_remove"])
        toolbar.addWidget(self.btn_add)
        toolbar.addWidget(self.btn_remove)

        actions = QHBoxLayout()
        actions.addStretch()
        self.btn_cancel = QPushButton(self.texts["cancel"])
        self.btn_apply = QPushButton(self.texts["sampling_rules_apply"])
        self.btn_apply.setObjectName("Primary")
        actions.addWidget(self.btn_cancel)
        actions.addWidget(self.btn_apply)

        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(self.table, 1)
        root.addLayout(toolbar)
        root.addLayout(actions)

        self.btn_add.clicked.connect(lambda: self._append_row("", "", ""))
        self.btn_remove.clicked.connect(self._remove_selected_row)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._apply_rules)

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
                    is_dark="#161c28" in self.styleSheet(),
                    language=self.language,
                ).exec()
                return
            parts.append(rule_text)

        self._rules_text = normalize_sampling_fps_rules_text("; ".join(parts))
        self.accept()

    def rules_text(self):
        return self._rules_text


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
        self.filtered_rows = list(self.rows)
        self.filtered_payloads = list(self.row_payloads)

        palette = dialog_palette(is_dark)
        self.setWindowTitle(title or self.texts["details_title_default"])
        self.setMinimumSize(820, 520)
        self.resize(980, 620)
        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Hint {{ color: {palette['muted']}; font-size: 12px; }}
            #Title {{ color: {palette['text']}; font-size: 21px; font-weight: 800; }}
            #ToolbarCard, #PreviewCard, #StatusCard {{
                background: {palette['card']};
                border: 1px solid {palette['border']};
                border-radius: 14px;
            }}
            #SummaryCard {{
                background: {palette['card']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                padding: 10px 12px;
            }}
            #SummaryValue {{ color: {palette['text']}; font-size: 18px; font-weight: 800; }}
            #SummaryLabel {{ color: {palette['muted']}; font-size: 11px; }}
            QTableWidget {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                gridline-color: {palette['border']};
                alternate-background-color: {"#202a3b" if is_dark else "#f7f9fd"};
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            QTableWidget::item:hover {{
                background: {"#253247" if is_dark else "#edf3fb"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected {{
                background: {"#314664" if is_dark else "#dfeaf8"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected:active {{
                background: {"#395274" if is_dark else "#d3e3f7"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected:!active {{
                background: {"#2b3d57" if is_dark else "#e6eef9"};
                color: {palette['text']};
            }}
            QHeaderView::section {{
                color: {palette['muted']};
                background: {palette['card']};
                border: none;
                border-bottom: 1px solid {palette['border']};
                padding: 10px 8px;
                font-weight: 700;
            }}
            QLineEdit {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 10px;
                padding: 8px 10px;
            }}
            QLineEdit:focus {{ border-color: {palette['accent']}; }}
            QCheckBox {{ color: {palette['muted']}; spacing: 6px; }}
            QPlainTextEdit {{
                background: {palette['bg']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 10px;
                padding: 10px;
                font-family: Consolas, 'Microsoft YaHei UI';
                font-size: 12px;
            }}
            QPushButton {{
                border-radius: 10px;
                border: 1px solid {palette['border']};
                padding: 8px 12px;
                color: {palette['text']};
                background: {palette['card']};
            }}
            #Primary {{ background: {palette['accent']}; color: white; border-color: {palette['accent']}; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title_label = QLabel(title or self.texts["details_title_default"])
        title_label.setObjectName("Title")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Hint")
        subtitle_label.setWordWrap(True)

        toolbar_card = QFrame()
        toolbar_card.setObjectName("ToolbarCard")
        toolbar_layout = QVBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(14, 12, 14, 12)
        toolbar_layout.setSpacing(10)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.input_filter = QLineEdit()
        self.input_filter.setPlaceholderText(self.texts["details_filter_placeholder"])
        self.toggle_issues = QCheckBox(self.texts["details_show_issues"])
        self.btn_reset_filter = QPushButton(self.texts["details_reset_filter"])
        self.btn_reset_filter.setObjectName("Ghost")
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
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(self.selection_mode)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)

        preview_card = QFrame()
        preview_card.setObjectName("PreviewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        preview_layout.setSpacing(8)
        preview_title = QLabel(self._preview_title_text())
        preview_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        preview_hint = QLabel(self._preview_hint_text())
        preview_hint.setObjectName("Hint")
        preview_hint.setWordWrap(True)
        self.preview_text = QPlainTextEdit()
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(preview_hint)
        preview_layout.addWidget(self.preview_text, 1)

        content_splitter = QSplitter(Qt.Vertical)
        content_splitter.addWidget(self.table)
        content_splitter.addWidget(preview_card)
        content_splitter.setChildrenCollapsible(False)
        content_splitter.setStretchFactor(0, 4)
        content_splitter.setStretchFactor(1, 2)

        button_row = QHBoxLayout()
        self.btn_copy = QPushButton(self.texts["details_copy_json"])
        self.btn_export = QPushButton(self.texts["details_export_json"])
        self.btn_copy_row = QPushButton("Copy Selected" if self.texts["close"].lower() == "close" else "复制选中行")
        self.btn_cancel = QPushButton(self.texts["cancel"])
        self.btn_close = QPushButton(self.texts["close"])
        self.btn_close.setObjectName("Primary")
        button_row.addWidget(self.btn_copy)
        button_row.addWidget(self.btn_export)
        button_row.addWidget(self.btn_copy_row)
        self.extra_action_buttons = []
        for action in self.extra_actions:
            button = QPushButton(action.get("label", "Action"))
            button.setObjectName(action.get("object_name", "Ghost"))
            button.clicked.connect(lambda _, handler=action.get("handler"): handler(self) if callable(handler) else None)
            self.extra_action_buttons.append(button)
            button_row.addWidget(button)
        button_row.addStretch()
        if self.confirm_mode:
            self.btn_cancel.setObjectName("Ghost")
            self.btn_close.setText(self.confirm_text)
            button_row.addWidget(self.btn_cancel)
        button_row.addWidget(self.btn_close)

        status_card = QFrame()
        status_card.setObjectName("StatusCard")
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(12, 10, 12, 10)
        status_layout.setSpacing(8)
        self.status_hint = QLabel("")
        self.status_hint.setObjectName("Hint")
        self.status_hint.setWordWrap(True)
        status_layout.addWidget(self.status_hint)

        root.addWidget(title_label)
        root.addWidget(subtitle_label)
        root.addWidget(toolbar_card)
        root.addWidget(content_splitter, 1)
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
        self.table.itemSelectionChanged.connect(self._update_preview)
        if self.confirm_mode:
            self.btn_cancel.clicked.connect(self.reject)
        self.btn_close.clicked.connect(self.accept)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

    def _preview_title_text(self):
        return "Preview" if self.texts["close"].lower() == "close" else "详情预览"

    def _preview_hint_text(self):
        if self.texts["close"].lower() == "close":
            return "Selected row details and payload JSON."
        return "展示当前选中行的完整信息与负载 JSON。"

    def _inline_text(self, zh_text, en_text):
        return en_text if self.texts["close"].lower() == "close" else zh_text

    def _build_summary_card(self, label_text, value_text):
        card = QFrame()
        card.setObjectName("SummaryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
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
        filtered_pairs = [
            (row, payload)
            for row, payload in zip(self.rows, self.row_payloads)
            if self._matches_filter(row)
        ]
        self.filtered_rows = [row for row, _ in filtered_pairs]
        self.filtered_payloads = [payload for _, payload in filtered_pairs]
        self.table.setRowCount(0)
        for row_data in self.filtered_rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            for col_index, value in enumerate(row_data):
                item = QTableWidgetItem(str(value))
                if col_index == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                if self._is_issue_row(row_data):
                    item.setForeground(Qt.GlobalColor.red)
                self.table.setItem(row_index, col_index, item)
        total_rows = len(self.rows)
        visible_rows = len(self.filtered_rows)
        issue_rows = sum(1 for row in self.rows if self._is_issue_row(row))
        self.summary_total.value_label.setText(str(total_rows))
        self.summary_visible.value_label.setText(str(visible_rows))
        self.summary_issues.value_label.setText(str(issue_rows))
        if not self.filtered_rows:
            self.status_hint.setText(self.texts["details_empty"])
        else:
            self.status_hint.setText(
                self.texts["details_showing_count"].format(visible=visible_rows, total=total_rows)
            )
        self._update_preview()

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

    def _update_preview(self):
        selected = self.get_selected_payloads()
        if selected:
            payload = selected[0]
            selected_indexes = self.table.selectionModel().selectedRows()
            row_index = selected_indexes[0].row() if selected_indexes else 0
        elif self.filtered_payloads:
            payload = self.filtered_payloads[0]
            row_index = 0
        else:
            self.preview_text.clear()
            return

        row_data = self.filtered_rows[row_index] if 0 <= row_index < len(self.filtered_rows) else []
        lines = [f"{header}: {value}" for header, value in zip(self.headers, row_data)]
        lines.append("")
        lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
        self.preview_text.setPlainText("\n".join(lines))

    def _copy_json(self):
        payload = {
            "headers": self.headers,
            "rows": self.filtered_rows,
        }
        QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False, indent=2))
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
        text = "\n".join(f"{header}: {value}" for header, value in zip(self.headers, row_data))
        QApplication.clipboard().setText(text)
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
        payload = {
            "headers": self.headers,
            "rows": self.filtered_rows,
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
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

    def _handle_item_double_click(self, item):
        if not callable(self.row_double_click_handler):
            return
        row_index = item.row()
        if not (0 <= row_index < len(self.filtered_payloads)):
            return
        self.row_double_click_handler(self, self.filtered_payloads[row_index])

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
            for index, action in enumerate(self.extra_actions):
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
            self.row_double_click_handler(self, selected[0])
            return
        action = extra_action_map.get(chosen)
        if action and callable(action.get("handler")):
            action["handler"](self)

    def _handle_item_double_click(self, item):
        row_index = item.row()
        if 0 <= row_index < len(self.filtered_payloads):
            self.row_double_click_handler(self, self.filtered_payloads[row_index])


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
        self.filtered_rows = list(self.rows)
        self.filtered_payloads = list(self.row_payloads)

        palette = dialog_palette(is_dark)
        self.setWindowTitle(title or self.texts["details_title_default"])
        self.setMinimumSize(860, 540)
        self.resize(1040, 640)
        self.setStyleSheet(
            f"""
            QDialog {{ background: {palette['bg']}; }}
            QLabel {{ color: {palette['text']}; background: transparent; }}
            #Hint {{ color: {palette['muted']}; font-size: 12px; }}
            #Title {{ color: {palette['text']}; font-size: 20px; font-weight: 800; }}
            #ToolbarCard, #DetailsCard, #StatusCard {{
                background: {palette['card']};
                border: 1px solid {palette['border']};
                border-radius: 14px;
            }}
            #SummaryCard {{
                background: {palette['card']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                padding: 8px 10px;
            }}
            #SummaryValue {{ color: {palette['text']}; font-size: 16px; font-weight: 800; }}
            #SummaryLabel {{ color: {palette['muted']}; font-size: 11px; }}
            QLineEdit {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 10px;
                padding: 8px 10px;
            }}
            QLineEdit:focus {{ border-color: {palette['accent']}; }}
            QCheckBox {{ color: {palette['muted']}; spacing: 6px; }}
            QTableWidget {{
                background: {palette['card']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 12px;
                alternate-background-color: {"#202a3b" if is_dark else "#f7f9fd"};
                selection-background-color: {"#314664" if is_dark else "#dfeaf8"};
                selection-color: {palette['text']};
                outline: none;
            }}
            QTableWidget::item {{ padding: 6px 8px; }}
            QTableWidget::item:hover {{
                background: transparent;
                color: {palette['text']};
            }}
            QTableWidget::item:selected {{
                background: {"#314664" if is_dark else "#dfeaf8"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected:active {{
                background: {"#395274" if is_dark else "#d3e3f7"};
                color: {palette['text']};
            }}
            QTableWidget::item:selected:!active {{
                background: {"#2b3d57" if is_dark else "#e6eef9"};
                color: {palette['text']};
            }}
            QHeaderView::section {{
                color: {palette['muted']};
                background: {palette['card']};
                border: none;
                border-bottom: 1px solid {palette['border']};
                padding: 10px 8px;
                font-weight: 700;
            }}
            QPlainTextEdit {{
                background: {palette['bg']};
                color: {palette['text']};
                border: 1px solid {palette['border']};
                border-radius: 10px;
                padding: 10px;
                font-family: Consolas, 'Microsoft YaHei UI';
                font-size: 12px;
            }}
            QPushButton {{
                border-radius: 10px;
                border: 1px solid {palette['border']};
                padding: 8px 12px;
                color: {palette['text']};
                background: {palette['card']};
            }}
            #Primary {{ background: {palette['accent']}; color: white; border-color: {palette['accent']}; }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title_label = QLabel(title or self.texts["details_title_default"])
        title_label.setObjectName("Title")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Hint")
        subtitle_label.setWordWrap(True)

        toolbar_card = QFrame()
        toolbar_card.setObjectName("ToolbarCard")
        toolbar_layout = QVBoxLayout(toolbar_card)
        toolbar_layout.setContentsMargins(14, 12, 14, 12)
        toolbar_layout.setSpacing(10)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.input_filter = QLineEdit()
        self.input_filter.setPlaceholderText(self.texts["details_filter_placeholder"])
        self.toggle_issues = QCheckBox(self.texts["details_show_issues"])
        self.btn_reset_filter = QPushButton(self.texts["details_reset_filter"])
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
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(self.selection_mode)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(360)

        details_card = QFrame()
        details_card.setObjectName("DetailsCard")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(14, 12, 14, 12)
        details_layout.setSpacing(6)
        details_title = QLabel(self._inline_text("选中项详情", "Selected Details"))
        details_title.setStyleSheet("font-size: 14px; font-weight: 700;")
        details_hint = QLabel(self._inline_text("只显示当前选中行的关键信息。", "Shows the key fields for the selected row."))
        details_hint.setObjectName("Hint")
        details_hint.setWordWrap(True)
        self.details_text = QPlainTextEdit()
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
        self.btn_close.setObjectName("Primary")
        button_row.addWidget(self.btn_copy)
        button_row.addWidget(self.btn_export)
        button_row.addWidget(self.btn_copy_row)
        for action in self.extra_actions:
            button = QPushButton(action.get("label", "Action"))
            button.clicked.connect(lambda _, handler=action.get("handler"): handler(self) if callable(handler) else None)
            button_row.addWidget(button)
        button_row.addStretch()
        if self.confirm_mode:
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

    def _build_summary_card(self, label_text, value_text):
        card = QFrame()
        card.setObjectName("SummaryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
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
        self.table.setSortingEnabled(True)

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


class ModelDownloadDialog(QDialog):
    download_requested = Signal()
    open_folder_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None, is_dark=True, language="zh"):
        super().__init__(parent)
        self.texts = get_texts(language)
        self.palette = dialog_palette(is_dark)
        self._downloading = False

        self.setWindowTitle(self.texts["models_missing_title"])
        self.setModal(True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        apply_dialog_size(
            self,
            WINDOW_SIZES["notice_dialog"]["preferred"],
            WINDOW_SIZES["notice_dialog"]["minimum"],
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        self.setStyleSheet(
            f"""
            QDialog {{ background: {self.palette['bg']}; }}
            QLabel {{ color: {self.palette['text']}; background: transparent; }}
            #Card {{ background: {self.palette['card']}; border: 1px solid {self.palette['border']}; border-radius: 20px; }}
            #Title {{ font-size: 24px; font-weight: 800; }}
            #Body {{ color: {self.palette['muted']}; font-size: 13px; line-height: 1.45; }}
            #Hint {{ color: {self.palette['muted']}; font-size: 12px; }}
            #PathCard {{
                background: {self.palette['bg']};
                border: 1px solid {self.palette['border']};
                border-radius: 14px;
                padding: 12px;
            }}
            QPushButton {{
                border: none; border-radius: 12px; padding: 10px 18px; font-weight: 700;
            }}
            #Primary {{ background: {self.palette['accent']}; color: white; }}
            #Ghost {{ background: transparent; color: {self.palette['muted']}; border: 1px solid {self.palette['border']}; }}
            #Danger {{ background: #c0392b; color: white; }}
            QProgressBar {{
                background: {self.palette['bg']};
                border: 1px solid {self.palette['border']};
                border-radius: 10px;
                text-align: center;
                min-height: 18px;
            }}
            QProgressBar::chunk {{
                background: {self.palette['accent']};
                border-radius: 9px;
            }}
            """
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(14)

        self.title_label = QLabel(self.texts["models_missing_title"])
        self.title_label.setObjectName("Title")
        self.body_label = QLabel()
        self.body_label.setObjectName("Body")
        self.body_label.setWordWrap(True)

        self.path_title = QLabel(self.texts["model_target_folder"])
        self.path_title.setObjectName("Hint")
        self.path_card = QLabel()
        self.path_card.setObjectName("PathCard")
        self.path_card.setWordWrap(True)

        self.progress_title = QLabel(self.texts["model_download_waiting"])
        self.progress_title.setObjectName("Hint")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("Body")
        self.progress_label.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.exit_button = QPushButton(self.texts["exit_app"])
        self.exit_button.setObjectName("Danger")
        self.open_button = QPushButton(self.texts["open_model_dir"])
        self.open_button.setObjectName("Ghost")
        self.download_button = QPushButton(self.texts["download_models"])
        self.download_button.setObjectName("Primary")
        self.done_button = QPushButton(self.texts["model_ready_action"])
        self.done_button.setObjectName("Primary")
        self.done_button.hide()
        button_row.addWidget(self.exit_button)
        button_row.addStretch()
        button_row.addWidget(self.open_button)
        button_row.addWidget(self.download_button)
        button_row.addWidget(self.done_button)

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        layout.addWidget(self.path_title)
        layout.addWidget(self.path_card)
        layout.addWidget(self.progress_title)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addLayout(button_row)
        outer.addWidget(card)

        self.download_button.clicked.connect(self.download_requested.emit)
        self.open_button.clicked.connect(self.open_folder_requested.emit)
        self.exit_button.clicked.connect(self._handle_exit)
        self.done_button.clicked.connect(self.accept)

    def reject(self):
        if self._downloading:
            return
        super().reject()

    def closeEvent(self, event):
        if self._downloading:
            event.ignore()
            return
        super().closeEvent(event)

    def _handle_exit(self):
        self.exit_requested.emit()
        self.reject()

    def set_missing_state(self, missing_files, folder, download_enabled=True):
        self._downloading = False
        self.title_label.setText(self.texts["models_missing_title"])
        self.body_label.setText(
            self.texts["models_missing_body"].format(files=", ".join(missing_files), folder=folder)
        )
        self.path_card.setText(folder)
        self.body_label.show()
        self.path_title.show()
        self.path_card.show()
        self.progress_title.hide()
        self.progress_bar.hide()
        self.progress_label.hide()
        self.download_button.setVisible(download_enabled)
        self.download_button.setEnabled(download_enabled)
        self.open_button.show()
        self.exit_button.show()
        self.open_button.setEnabled(True)
        self.exit_button.setEnabled(True)
        self.done_button.hide()

    def set_progress_state(self, value, text):
        self._downloading = True
        self.title_label.setText(self.texts["download_models"])
        self.body_label.hide()
        self.path_title.hide()
        self.path_card.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["model_download_in_progress"])
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)
        self.download_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.exit_button.setEnabled(False)
        self.done_button.hide()

    def set_error_state(self, error_text, missing_files, folder, download_enabled=True):
        self._downloading = False
        self.title_label.setText(self.texts["model_download_failed"])
        self.body_label.setText(
            self.texts["models_missing_body"].format(files=", ".join(missing_files), folder=folder)
        )
        self.path_card.setText(folder)
        self.body_label.show()
        self.path_title.show()
        self.path_card.show()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["warning_title"])
        self.progress_bar.setValue(0)
        self.progress_label.setText(error_text)
        self.download_button.setVisible(download_enabled)
        self.download_button.setEnabled(download_enabled)
        self.open_button.show()
        self.exit_button.show()
        self.open_button.setEnabled(True)
        self.exit_button.setEnabled(True)
        self.done_button.hide()

    def set_success_state(self, folder):
        self._downloading = False
        self.title_label.setText(self.texts["success_title"])
        self.body_label.setText(self.texts["model_download_done"])
        self.body_label.show()
        self.path_title.hide()
        self.path_card.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["model_download_in_progress"])
        self.progress_bar.setValue(100)
        self.progress_label.setText(self.texts["model_ready_hint"])
        self.download_button.hide()
        self.open_button.hide()
        self.exit_button.hide()
        self.done_button.show()
