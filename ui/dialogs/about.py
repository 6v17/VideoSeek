from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.app.config import get_app_version
from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard


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

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        shell = VSCard(spacing=12)
        inner = shell.content_layout

        title_text = about.get("title", texts["app_name"])
        subtitle_text = about.get("badge", texts["about_badge"])
        title = QLabel(title_text)
        title.setObjectName("DialogHeroTitle")
        subtitle = QLabel(subtitle_text)
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)
        version = QLabel(texts["version_label"].format(version=get_app_version()))
        version.setObjectName("DialogMetaLabel")
        version_status = QLabel(version_info.get("status_text", texts["version_check_unavailable"]))
        version_status.setObjectName("DialogMetaLabel")
        version_status.setWordWrap(True)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("DialogDivider")

        body = QTextBrowser()
        body.setObjectName("DialogBodyBrowser")
        body.setReadOnly(True)
        body.setOpenExternalLinks(True)
        if about.get("format") == "html":
            body.setHtml(about.get("body", texts["about_body"]))
        else:
            body.setPlainText(about.get("body", texts["about_body"]))

        close_button = QPushButton(texts["close"])
        close_button.setObjectName("PrimaryButton")
        close_button.setFixedHeight(40)
        close_button.clicked.connect(self.accept)

        inner.addWidget(title)
        inner.addWidget(subtitle)
        inner.addWidget(version)
        inner.addWidget(version_status)
        inner.addWidget(divider)
        inner.addWidget(body)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(close_button)

        inner.addLayout(button_row)
        layout.addWidget(shell)
