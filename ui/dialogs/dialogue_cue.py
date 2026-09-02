"""Edit one speech-dialogue cue on the understanding page."""

from __future__ import annotations

from typing import Any, Mapping

from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from src.services.recap_service import format_recap_clock, parse_recap_clock
from ui.dialogs.shell import VSDialogShell


class DialogueCueDialog(VSDialogShell):
    def __init__(
        self,
        parent=None,
        *,
        texts: Mapping[str, Any],
        start: float = 0.0,
        end: float = 0.0,
        speaker: str = "",
        text: str = "",
    ):
        self.texts = dict(texts or {})
        super().__init__(
            parent,
            title=str(self.texts.get("understanding_dialogue_edit_title", "Edit line")),
            body=str(
                self.texts.get(
                    "understanding_dialogue_edit_hint",
                    "Change the time, speaker, or line. Saved for this video only.",
                )
            ),
            minimum_width=480,
        )
        self._result: dict[str, Any] | None = None

        self.start_edit = QLineEdit(format_recap_clock(start))
        self.start_edit.setObjectName("SearchInput")
        self.end_edit = QLineEdit(format_recap_clock(end))
        self.end_edit.setObjectName("SearchInput")
        self.speaker_edit = QLineEdit(str(speaker or "").strip())
        self.speaker_edit.setObjectName("SearchInput")
        self.text_edit = QPlainTextEdit(str(text or "").strip())
        self.text_edit.setObjectName("UnderstandingOutput")
        self.text_edit.setMinimumHeight(96)

        self.content_layout.addWidget(
            self._labeled(self.texts.get("understanding_dialogue_edit_start", "Start"), self.start_edit)
        )
        self.content_layout.addWidget(
            self._labeled(self.texts.get("understanding_dialogue_edit_end", "End"), self.end_edit)
        )
        self.content_layout.addWidget(
            self._labeled(self.texts.get("understanding_dialogue_edit_speaker", "Speaker"), self.speaker_edit)
        )
        self.content_layout.addWidget(
            self._labeled(self.texts.get("understanding_dialogue_edit_text", "Line"), self.text_edit)
        )

        self.error_label = QLabel()
        self.error_label.setObjectName("StatusHint")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.content_layout.addWidget(self.error_label)

        self.add_footer_button(
            str(self.texts.get("cancel", "Cancel")),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(self.texts.get("understanding_dialogue_edit_save", "Save")),
            object_name="PrimaryButton",
            on_click=self._accept,
            default=True,
        )

    @staticmethod
    def _labeled(title: str, field: QWidget) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QLabel(str(title or ""))
        label.setObjectName("InlineFieldLabel")
        layout.addWidget(label)
        layout.addWidget(field)
        return wrap

    def result_cue(self) -> dict[str, Any] | None:
        return self._result

    def _accept(self) -> None:
        line = str(self.text_edit.toPlainText() or "").strip()
        if not line:
            self.error_label.setText(
                str(self.texts.get("understanding_dialogue_edit_empty", "Line text cannot be empty."))
            )
            self.error_label.show()
            return
        try:
            start = parse_recap_clock(self.start_edit.text())
            end = parse_recap_clock(self.end_edit.text())
        except (TypeError, ValueError):
            self.error_label.setText(
                str(
                    self.texts.get(
                        "understanding_dialogue_edit_time_invalid",
                        "Enter start/end as mm:ss or seconds.",
                    )
                )
            )
            self.error_label.show()
            return
        if end <= start:
            end = start + 0.2
        self._result = {
            "start": round(float(start), 2),
            "end": round(float(end), 2),
            "speaker": str(self.speaker_edit.text() or "").strip(),
            "text": line,
        }
        self.accept()
