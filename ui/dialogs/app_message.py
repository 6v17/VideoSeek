from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width
from ui.widgets.scaffold import VSCard
from ui.widgets.styles import repolish_widget


class AppMessageDialog(QDialog):
    def __init__(
        self,
        title,
        text,
        kind="info",
        parent=None,
        is_dark=True,
        language="zh",
        confirm=False,
        cancel_text="",
        confirm_text="",
    ):
        super().__init__(parent)
        texts = get_texts(language)

        self._result = False
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(
            message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"],
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            )
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        card = VSCard(variant="dialog", margins=(18, 18, 18, 14), spacing=12)
        layout = card.content_layout

        top = QHBoxLayout()
        top.setSpacing(12)
        badge = QLabel()
        badge.setObjectName("MessageBadge")
        badge.setAlignment(Qt.AlignCenter)
        badge_map = {"info": "i", "success": "OK", "warning": "!", "error": "X"}
        badge.setText(badge_map.get(kind, badge_map["info"]))
        badge.setProperty("kind", kind)
        repolish_widget(badge)
        top_text = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("DialogHeroTitle")
        body_label = QLabel(text)
        body_label.setObjectName("DialogBodyLabel")
        body_label.setWordWrap(True)
        top_text.addWidget(title_label)
        top_text.addWidget(body_label)
        top.addWidget(badge, 0)
        top.addLayout(top_text, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        if confirm:
            cancel_label = str(cancel_text or "").strip() or texts["cancel"]
            confirm_label = str(confirm_text or "").strip() or texts["confirm_action"]
            cancel = QPushButton(cancel_label)
            cancel.setObjectName("GhostButton")
            cancel.clicked.connect(self.reject)
            ok = QPushButton(confirm_label)
            ok.setObjectName("PrimaryButton")
            ok.clicked.connect(self._accept_confirm)
            buttons.addWidget(cancel)
            buttons.addWidget(ok)
        else:
            ok = QPushButton(texts["close"])
            ok.setObjectName("PrimaryButton")
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
