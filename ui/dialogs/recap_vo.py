"""Hand-edit one recap VO unit or add a child shot from the review tree."""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from src.services.recap_service import format_recap_clock, parse_recap_clock
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
                "Edit narration for this unit. Cover time is inferred from length. Empty clears the line.",
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


class RecapAddShotDialog(VSDialogShell):
    def __init__(
        self,
        parent=None,
        *,
        texts: Mapping[str, Any],
        src_in: float = 0.0,
        src_out: float = 0.0,
    ):
        self.texts = dict(texts or {})
        super().__init__(
            parent,
            title=str(self.texts.get("understanding_recap_review_add_shot_title", "Add shot")),
            body=str(
                self.texts.get(
                    "understanding_recap_review_add_shot_hint",
                    "Insert a child shot into this narration unit. Use source clocks (mm:ss).",
                )
            ),
            minimum_width=420,
        )
        self._result: dict[str, float] | None = None
        self.start_edit = QLineEdit(format_recap_clock(src_in))
        self.start_edit.setObjectName("SearchInput")
        self.end_edit = QLineEdit(format_recap_clock(src_out))
        self.end_edit.setObjectName("SearchInput")
        for label, widget in (
            (self.texts.get("understanding_recap_review_add_shot_in", "Source in"), self.start_edit),
            (self.texts.get("understanding_recap_review_add_shot_out", "Source out"), self.end_edit),
        ):
            row = QWidget()
            layout = QVBoxLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            caption = QLabel(str(label))
            caption.setObjectName("InlineFieldLabel")
            layout.addWidget(caption)
            layout.addWidget(widget)
            self.content_layout.addWidget(row)
        self.add_footer_button(
            str(self.texts.get("cancel", "Cancel")),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(self.texts.get("understanding_recap_review_add_shot_save", "Add")),
            object_name="PrimaryButton",
            on_click=self._accept,
            default=True,
        )

    def result_range(self) -> dict[str, float] | None:
        return self._result

    def _accept(self) -> None:
        try:
            start = parse_recap_clock(self.start_edit.text())
            end = parse_recap_clock(self.end_edit.text())
        except Exception:
            return
        if end <= start + 0.04:
            return
        self._result = {"src_in": float(start), "src_out": float(end)}
        self.accept()
