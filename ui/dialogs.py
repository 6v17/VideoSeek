import webbrowser
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QTextBrowser,
    QProgressBar,
    QVBoxLayout,
)

from src.app.config import get_app_version, load_config
from src.app.i18n import get_texts
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
    ):
        super().__init__(parent)
        self.texts = get_texts(language)
        self.rows = list(rows or [])
        self.headers = list(headers or [])
        self.export_default_name = export_default_name
        self.stretch_column = int(stretch_column)
        self.fixed_column_widths = dict(fixed_column_widths or {})

        palette = dialog_palette(is_dark)
        self.setWindowTitle(title or self.texts["details_title_default"])
        self.setMinimumSize(820, 520)
        self.resize(980, 620)
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
            }}
            QHeaderView::section {{
                color: {palette['muted']};
                background: transparent;
                border: none;
                padding: 8px;
                font-weight: 700;
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
        title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("Hint")
        subtitle_label.setWordWrap(True)

        self.table = QTableWidget(0, len(self.headers))
        self.table.setHorizontalHeaderLabels(self.headers)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        button_row = QHBoxLayout()
        self.btn_copy = QPushButton(self.texts["details_copy_json"])
        self.btn_export = QPushButton(self.texts["details_export_json"])
        self.btn_close = QPushButton(self.texts["close"])
        self.btn_close.setObjectName("Primary")
        button_row.addWidget(self.btn_copy)
        button_row.addWidget(self.btn_export)
        button_row.addStretch()
        button_row.addWidget(self.btn_close)

        self.status_hint = QLabel("")
        self.status_hint.setObjectName("Hint")

        root.addWidget(title_label)
        root.addWidget(subtitle_label)
        root.addWidget(self.table, 1)
        root.addWidget(self.status_hint)
        root.addLayout(button_row)

        self._populate_rows()
        self._apply_column_layout()

        self.btn_copy.clicked.connect(self._copy_json)
        self.btn_export.clicked.connect(self._export_json)
        self.btn_close.clicked.connect(self.accept)

    def _populate_rows(self):
        self.table.setRowCount(0)
        for row_data in self.rows:
            row_index = self.table.rowCount()
            self.table.insertRow(row_index)
            for col_index, value in enumerate(row_data):
                item = QTableWidgetItem(str(value))
                if col_index == 0:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_index, col_index, item)
        if not self.rows:
            self.status_hint.setText(self.texts["details_empty"])

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

    def _copy_json(self):
        payload = {
            "headers": self.headers,
            "rows": self.rows,
        }
        QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False, indent=2))
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
            "rows": self.rows,
        }
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except Exception:
            self.status_hint.setText(self.texts["details_export_failed"])
            return
        self.status_hint.setText(self.texts["details_export_done"].format(path=path))


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
