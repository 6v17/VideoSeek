"""Shared Fluent-style dialog chrome (QSS tokens, no QFluentWidgets)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.scaffold import VSCard
from ui.widgets.styles import repolish_widget


class VSDialogShell(QDialog):
    """QDialog + dialog card with title/body header, content host, and footer actions."""

    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        body: str = "",
        kind: str | None = None,
        minimum_width: int | None = None,
        outer_margins: tuple[int, int, int, int] = (14, 14, 14, 14),
        card_margins: tuple[int, int, int, int] = (18, 18, 18, 14),
        card_spacing: int = 12,
    ):
        super().__init__(parent)
        self.setModal(True)
        self.setObjectName("VSDialogShell")
        if minimum_width is not None:
            self.setMinimumWidth(int(minimum_width))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(*outer_margins)
        outer.setSpacing(0)

        self._card = VSCard(
            variant="dialog",
            margins=card_margins,
            spacing=card_spacing,
            object_name="DialogCard",
        )
        card_layout = self._card.content_layout

        self._header = QWidget()
        self._header.setObjectName("DialogHeader")
        header_row = QHBoxLayout(self._header)
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(12)

        self._badge = QLabel()
        self._badge.setObjectName("MessageBadge")
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.hide()

        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(6)
        self._title_label = QLabel()
        self._title_label.setObjectName("DialogHeroTitle")
        self._title_label.setWordWrap(True)
        self._body_label = QLabel()
        self._body_label.setObjectName("DialogBodyLabel")
        self._body_label.setWordWrap(True)
        self._body_label.hide()
        header_text.addWidget(self._title_label)
        header_text.addWidget(self._body_label)

        header_row.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignTop)
        header_row.addLayout(header_text, 1)
        card_layout.addWidget(self._header)

        self._content_host = QWidget()
        self._content_host.setObjectName("DialogContent")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(10)
        card_layout.addWidget(self._content_host, 1)

        self._footer = QFrame()
        self._footer.setObjectName("DialogFooter")
        self._footer_layout = QHBoxLayout(self._footer)
        self._footer_layout.setContentsMargins(0, 12, 0, 0)
        self._footer_layout.setSpacing(8)
        self._footer_layout.addStretch(1)
        card_layout.addWidget(self._footer)

        outer.addWidget(self._card, 1)

        self.set_title(title)
        self.set_body(body)
        if kind:
            self.set_kind(kind)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._content_layout

    @property
    def footer_layout(self) -> QHBoxLayout:
        return self._footer_layout

    @property
    def title_label(self) -> QLabel:
        return self._title_label

    @property
    def body_label(self) -> QLabel:
        return self._body_label

    def set_title(self, text: str) -> None:
        label = str(text or "").strip()
        self._title_label.setText(label)
        if label:
            self.setWindowTitle(label)

    def set_body(self, text: str) -> None:
        label = str(text or "").strip()
        self._body_label.setText(label)
        self._body_label.setVisible(bool(label))

    def set_kind(self, kind: str | None) -> None:
        token = str(kind or "").strip().lower()
        if not token:
            self._badge.hide()
            return
        badge_map = {"info": "i", "success": "OK", "warning": "!", "error": "X"}
        self._badge.setText(badge_map.get(token, badge_map["info"]))
        self._badge.setProperty("kind", token if token in badge_map else "info")
        self._badge.show()
        repolish_widget(self._badge)

    def clear_footer(self, *, keep_stretch: bool = True) -> None:
        while self._footer_layout.count():
            item = self._footer_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if keep_stretch:
            self._footer_layout.addStretch(1)

    def add_footer_button(
        self,
        text: str,
        *,
        object_name: str = "GhostButton",
        on_click=None,
        default: bool = False,
    ) -> QPushButton:
        button = QPushButton(str(text or ""))
        button.setObjectName(str(object_name or "GhostButton"))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if callable(on_click):
            button.clicked.connect(on_click)
        if default:
            button.setDefault(True)
            button.setAutoDefault(True)
        self._footer_layout.addWidget(button, 0)
        return button

    def add_footer_stretch(self) -> None:
        self._footer_layout.addStretch(1)

    def set_content_visible(self, visible: bool) -> None:
        self._content_host.setVisible(bool(visible))
