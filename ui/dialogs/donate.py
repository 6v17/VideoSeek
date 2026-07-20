from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from src.app.logging_utils import get_logger
from src.services.remote_html_assets import download_url_to_temp_file
from ui.dialogs.html_links import open_html_link
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard

logger = get_logger("donate_dialog")
_DONATE_IMAGE_MAX_EDGE = 380


class DonateDialog(QDialog):
    def __init__(self, parent=None, *, is_dark=True, language="zh", donate=None):
        super().__init__(parent)
        texts = get_texts(language)
        donate = dict(donate or {})
        self._image_url = str(donate.get("image_url", "") or "").strip()
        self._github_url = str(donate.get("github_url", "") or "").strip()

        self.setWindowTitle(texts["donate_title"])
        apply_dialog_size(
            self,
            WINDOW_SIZES["donate_dialog"]["preferred"],
            WINDOW_SIZES["donate_dialog"]["minimum"],
            WINDOW_SIZES["donate_dialog"]["screen_margin"],
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        shell = VSCard(spacing=12)
        inner = shell.content_layout

        title = QLabel(texts["donate_title"])
        title.setObjectName("DialogHeroTitle")
        body = QLabel(texts["donate_body"])
        body.setObjectName("Hint")
        body.setWordWrap(True)

        image_label = QLabel()
        image_label.setObjectName("DonateImageLabel")
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_label.setWordWrap(True)
        if self._image_url:
            image_label.setText(texts["donate_loading"])
            self._load_image(image_label, texts)
        else:
            image_label.setText(texts["donate_unavailable"])

        hint = QLabel(texts["donate_image_hint"])
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        close_button = QPushButton(texts["close"])
        close_button.setObjectName("PrimaryButton")
        close_button.setFixedHeight(40)
        close_button.clicked.connect(self.accept)

        inner.addWidget(title)
        inner.addWidget(body)
        inner.addWidget(image_label)
        inner.addWidget(hint)
        button_row = QHBoxLayout()
        button_row.addStretch()
        if self._github_url:
            github_button = QPushButton(texts.get("donate_github", "GitHub"))
            github_button.setObjectName("GhostButton")
            github_button.setFixedHeight(40)
            github_button.clicked.connect(lambda: open_html_link(self._github_url))
            button_row.addWidget(github_button)
        button_row.addWidget(close_button)
        inner.addLayout(button_row)
        layout.addWidget(shell)

    def _load_image(self, image_label: QLabel, texts: dict) -> None:
        try:
            temp_path = download_url_to_temp_file(self._image_url)
            pixmap = QPixmap(temp_path)
            if pixmap.isNull():
                raise ValueError("invalid image payload")
            scaled = pixmap.scaled(
                _DONATE_IMAGE_MAX_EDGE,
                _DONATE_IMAGE_MAX_EDGE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            image_label.setText("")
            image_label.setPixmap(scaled)
            image_label.setMinimumSize(scaled.size())
        except Exception as exc:
            logger.warning("Donate image load failed: %s", exc)
            image_label.setText(texts["donate_unavailable"])
