"""Hand-edit one recap VO line from the review table."""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtWidgets import QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from ui.dialogs.shell import VSDialogShell


class RecapVoDialog(VSDialogShell):
    def __init__(
        self,
        parent=None,
        *,
        texts: Mapping[str, Any],
        vo: str = "",
        event: str = "",
        clip_label: str = "",
    ):
        self.texts = dict(texts or {})
        hint = str(
            self.texts.get(
                "understanding_recap_review_edit_hint",
                "Edit narration for this shot only. Empty clears the line. Cuts and SRT are updated; this is not timeline trimming.",
            )
        )
        if str(event or "").strip():
            hint = f"{hint}\n{self.texts.get('understanding_recap_review_edit_event', 'Beat event')}: {event}"
        super().__init__(
            parent,
            title=str(self.texts.get("understanding_recap_review_edit_title", "Edit VO")),
            body=hint,
            minimum_width=480,
        )
        self._result: str | None = None

        self.vo_edit = QPlainTextEdit(str(vo or "").strip())
        self.vo_edit.setObjectName("UnderstandingOutput")
        self.vo_edit.setMinimumHeight(120)
        label = QLabel(
            str(clip_label or self.texts.get("understanding_recap_review_edit_vo", "Narration"))
        )
        label.setObjectName("InlineFieldLabel")
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(label)
        layout.addWidget(self.vo_edit)
        self.content_layout.addWidget(wrap)

        self.add_footer_button(
            str(self.texts.get("cancel", "Cancel")),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(self.texts.get("understanding_recap_review_edit_save", "Save")),
            object_name="PrimaryButton",
            on_click=self._accept,
            default=True,
        )

    def result_vo(self) -> str | None:
        return self._result

    def _accept(self) -> None:
        self._result = str(self.vo_edit.toPlainText() or "").strip()
        self.accept()
