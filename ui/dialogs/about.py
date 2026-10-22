from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.app.config import get_app_version
from src.app.i18n import get_texts
from ui.dialogs.app_message import AppMessageDialog
from ui.dialogs.html_links import ExternalLinkTextBrowser
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard

# Version label multi-tap opens the developer thank-you note.
_VERSION_TAP_COUNT = 7
_VERSION_TAP_WINDOW_MS = 4000


class _ClickableVersionLabel(QLabel):
    def __init__(self, text: str, on_click, parent=None):
        super().__init__(text, parent)
        self._on_click = on_click
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.button() == Qt.MouseButton.LeftButton and callable(self._on_click):
            self._on_click()
        super().mousePressEvent(event)


class AboutDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", version_info=None, about=None):
        super().__init__(parent)
        texts = get_texts(language)
        version_info = version_info or {}
        about = about or {}
        self._texts = texts
        self._is_dark = bool(is_dark)
        self._language = language
        self._version_taps = 0
        self._version_tap_first_ms = 0

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
        version = _ClickableVersionLabel(
            texts["version_label"].format(
                version=str(version_info.get("current_version") or get_app_version())
            ),
            on_click=self._on_version_clicked,
        )
        version.setObjectName("DialogMetaLabel")
        version_status = QLabel(version_info.get("status_text", texts["version_check_unavailable"]))
        version_status.setObjectName("DialogMetaLabel")
        version_status.setWordWrap(True)
        self._version_status = version_status

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setObjectName("DialogDivider")

        body = ExternalLinkTextBrowser()
        body.setObjectName("DialogBodyBrowser")
        body.setReadOnly(True)
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

    def _on_version_clicked(self) -> None:
        from PySide6.QtCore import QDateTime

        now = int(QDateTime.currentMSecsSinceEpoch())
        if self._version_taps == 0 or (now - self._version_tap_first_ms) > _VERSION_TAP_WINDOW_MS:
            self._version_taps = 1
            self._version_tap_first_ms = now
        else:
            self._version_taps += 1
        if self._version_taps < _VERSION_TAP_COUNT:
            return
        self._version_taps = 0
        self._version_tap_first_ms = 0
        title = self._texts.get("about_thanks_note_title", "A note for you")
        body = self._texts.get(
            "about_thanks_note_body",
            "Thanks for finding this. VideoSeek was built with limited spare time, "
            "hoping to help people who dig through footage every day. It stays free forever.",
        )
        self._version_status.setText(self._texts.get("about_thanks_note_hint", ""))
        AppMessageDialog(
            title,
            body,
            kind="success",
            parent=self,
            is_dark=self._is_dark,
            language=self._language,
        ).exec()
