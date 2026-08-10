from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from ui.dialogs.shell import VSDialogShell
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width


class IndexingCloseChoiceDialog(VSDialogShell):
    """Ask how to handle window close while library indexing is running."""

    def __init__(self, texts, parent=None, is_dark=True, language="zh"):
        super().__init__(
            parent,
            title=texts.get("indexing_close_dialog_title", "Indexing in progress"),
            body=texts.get("indexing_close_dialog_body", ""),
            kind="warning",
            minimum_width=message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"] + 80,
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            ),
            outer_margins=(18, 18, 18, 18),
            card_margins=(22, 22, 22, 18),
            card_spacing=14,
        )
        self._texts = texts
        self._choice = "cancel"
        self.content_layout.setSpacing(8)

        self.content_layout.addWidget(
            self._make_choice_button(
                texts.get("indexing_close_choice_background", "Continue in background"),
                "PrimaryButton",
                "background",
            )
        )
        self.content_layout.addWidget(
            self._make_choice_button(
                texts.get("indexing_close_choice_stop_exit", "Stop indexing and quit"),
                "GhostButton",
                "stop_exit",
            )
        )
        self.add_footer_button(
            texts.get("cancel", "Cancel"),
            object_name="GhostButton",
            on_click=self.reject,
        )

    def _make_choice_button(self, text: str, object_name: str, choice: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._choose(choice))
        return button

    def _choose(self, choice):
        self._choice = choice
        self.accept()

    def choice(self):
        return self._choice
