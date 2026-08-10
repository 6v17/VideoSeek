from src.app.i18n import get_texts
from ui.dialogs.shell import VSDialogShell
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width


class AppMessageDialog(VSDialogShell):
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
        texts = get_texts(language)
        super().__init__(
            parent,
            title=str(title or ""),
            body=str(text or ""),
            kind=str(kind or "info"),
            minimum_width=message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"],
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            ),
        )
        self._result = False
        # Message dialogs are header-only; keep content host empty/collapsed.
        self.set_content_visible(False)

        if confirm:
            cancel_label = str(cancel_text or "").strip() or texts["cancel"]
            confirm_label = str(confirm_text or "").strip() or texts["confirm_action"]
            self.add_footer_button(cancel_label, object_name="GhostButton", on_click=self.reject)
            self.add_footer_button(
                confirm_label,
                object_name="PrimaryButton",
                on_click=self._accept_confirm,
                default=True,
            )
        else:
            self.add_footer_button(
                texts["close"],
                object_name="PrimaryButton",
                on_click=self.accept,
                default=True,
            )

    def _accept_confirm(self):
        self._result = True
        self.accept()

    def confirmed(self):
        return self._result
