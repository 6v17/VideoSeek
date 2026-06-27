import webbrowser

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard


class NoticeDialog(QDialog):
    def __init__(self, parent=None, is_dark=True, language="zh", notice=None, version_info=None):
        super().__init__(parent)
        texts = get_texts(language)
        notice = notice or {}
        version_info = version_info or {}
        has_update = bool(version_info.get("has_update"))
        download_url = str(version_info.get("download_url") or "").strip()

        self._update_button = None
        self._update_breath_effect = None
        self._update_breath_animation = None

        self.setWindowTitle(texts["notice_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["notice_dialog"]["preferred"],
            WINDOW_SIZES["notice_dialog"]["minimum"],
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        shell = VSCard(spacing=12)
        form = shell.content_layout

        title = QLabel(notice.get("title", texts["notice_heading"]))
        title.setObjectName("DialogHeroTitle")
        subtitle = QLabel(notice.get("subtitle", texts["notice_subtitle"]))
        subtitle.setObjectName("Hint")
        subtitle.setWordWrap(True)

        content = QTextBrowser()
        content.setObjectName("DialogBodyBrowser")
        content.setReadOnly(True)
        content.setOpenExternalLinks(True)
        if notice.get("format") == "html":
            content.setHtml(notice.get("body", texts["notice_body"]))
        else:
            content.setPlainText(notice.get("body", texts["notice_body"]))

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        if has_update:
            status_text = str(version_info.get("status_text") or "").strip()
            if not status_text:
                status_text = texts["version_update_available"].format(
                    version=version_info.get("latest_version", "")
                )
            status = QLabel(status_text)
            status.setObjectName("NoticeUpdateHint")
            button_row.addWidget(status, 0)

        button_row.addStretch(1)

        if has_update and download_url:
            download_button = QPushButton(texts["download_latest"])
            download_button.setObjectName("UpdateButton")
            download_button.setFixedHeight(36)
            download_button.setCursor(Qt.CursorShape.PointingHandCursor)
            download_button.clicked.connect(lambda: webbrowser.open(download_url))
            button_row.addWidget(download_button, 0)
            self._update_button = download_button

        close_button = QPushButton(texts["close"])
        close_button.setObjectName("PrimaryButton")
        close_button.setFixedHeight(36)
        close_button.setFixedWidth(96)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button, 0)

        form.addWidget(title)
        form.addWidget(subtitle)
        form.addWidget(content)
        form.addLayout(button_row)
        layout.addWidget(shell)

    def showEvent(self, event):
        super().showEvent(event)
        self._start_update_breath_animation()

    def closeEvent(self, event):
        self._stop_update_breath_animation()
        super().closeEvent(event)

    def _start_update_breath_animation(self):
        button = self._update_button
        if button is None:
            return
        if self._update_breath_effect is None:
            effect = QGraphicsOpacityEffect(button)
            effect.setOpacity(1.0)
            button.setGraphicsEffect(effect)
            self._update_breath_effect = effect
        if self._update_breath_animation is None:
            animation = QPropertyAnimation(self._update_breath_effect, b"opacity", self)
            animation.setStartValue(1.0)
            animation.setEndValue(0.58)
            animation.setDuration(900)
            animation.setEasingCurve(QEasingCurve.Type.InOutSine)
            animation.setLoopCount(-1)
            self._update_breath_animation = animation
        if self._update_breath_animation.state() != QPropertyAnimation.State.Running:
            self._update_breath_animation.start()

    def _stop_update_breath_animation(self):
        animation = self._update_breath_animation
        if animation is not None and animation.state() == QPropertyAnimation.State.Running:
            animation.stop()
        if self._update_breath_effect is not None:
            self._update_breath_effect.setOpacity(1.0)
