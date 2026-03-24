import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QTextEdit, QVBoxLayout

from src.app.config import get_app_version, load_config
from src.app.i18n import get_texts


def dialog_palette(is_dark):
    return {
        "bg": "#161c28" if is_dark else "#f7f3e8",
        "card": "#1d2635" if is_dark else "#fffdfa",
        "text": "#f3f5f8" if is_dark else "#1d2430",
        "muted": "#9aa6b7" if is_dark else "#617086",
        "accent": "#4a86ff" if is_dark else "#3b6fd8",
        "border": "#2d3950" if is_dark else "#d7deea",
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
        self.setMinimumWidth(440)
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
    def __init__(self, parent=None, is_dark=True, language="zh", version_info=None):
        super().__init__(parent)
        texts = get_texts(language)
        config = load_config()
        version_info = version_info or {}

        self.setWindowTitle(texts["about_title"])
        self.setFixedSize(420, 520)

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
            #Card {{ background: {card}; border: 1px solid {border}; border-radius: 20px; }}
            #Title {{ font-size: 24px; font-weight: 800; }}
            #Muted {{ color: {muted}; font-size: 12px; }}
            #Body {{ color: {muted}; font-size: 13px; line-height: 1.45; }}
            QPushButton {{
                background: {accent};
                color: white;
                border: none;
                border-radius: 12px;
                padding: 10px 18px;
                font-weight: 700;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)

        card_frame = QFrame()
        card_frame.setObjectName("Card")
        layout = QVBoxLayout(card_frame)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)

        badge = QLabel(texts["about_badge"])
        badge.setStyleSheet(f"color: {accent}; font-size: 11px; font-weight: 800;")
        title = QLabel(texts["app_name"])
        title.setObjectName("Title")
        version = QLabel(texts["version_label"].format(version=get_app_version()))
        version.setObjectName("Muted")
        version_status = QLabel(version_info.get("status_text", texts["version_check_unavailable"]))
        version_status.setObjectName("Body")
        version_status.setWordWrap(True)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet(f"background: {border}; max-height: 1px; margin: 8px 0;")

        body = QLabel(texts["about_body"])
        body.setObjectName("Body")
        body.setWordWrap(True)

        download_button = QPushButton(texts["download_latest"])
        download_button.setFixedHeight(40)
        download_button.setVisible(bool(version_info.get("download_url")) and version_info.get("has_update"))
        download_button.clicked.connect(lambda: webbrowser.open(version_info["download_url"]))

        close_button = QPushButton(texts["close"])
        close_button.setFixedHeight(40)
        close_button.clicked.connect(self.accept)

        layout.addWidget(badge)
        layout.addWidget(title)
        layout.addWidget(version)
        layout.addWidget(version_status)
        layout.addWidget(divider)
        layout.addWidget(body)
        layout.addStretch()
        layout.addWidget(download_button)
        layout.addWidget(close_button)
        outer.addWidget(card_frame)


class NoticeDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", notice=None):
        super().__init__(parent)
        texts = get_texts(language)
        notice = notice or {}

        self.setWindowTitle(texts["notice_title"])
        self.setFixedSize(450, 340)

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
