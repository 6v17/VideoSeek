"""Batch-rename a speaker label on one video's dialogue cues."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QWidget

from src.storage.dialogue_transcript_store import (
    is_auto_speaker_label,
    normalize_dialogue_speaker,
)
from ui.dialogs.shell import VSDialogShell
from ui.widgets.components import NoWheelComboBox


def prompt_rename_speakers(
    parent,
    texts: dict,
    *,
    labels: list[tuple[str, int]],
    current: str = "",
) -> tuple[str, str] | None:
    """Pick an existing speaker and a new name. Returns ``(old, new)`` or None."""
    if not labels:
        return None
    dialog = VSDialogShell(
        parent,
        title=str(texts.get("understanding_speaker_rename_title", "Rename speakers")),
        body=str(
            texts.get(
                "understanding_speaker_rename_hint",
                "Every line with this speaker on the current video is renamed.",
            )
        ),
        minimum_width=420,
    )

    form_host = QWidget()
    form = QFormLayout(form_host)
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(10)
    form.setHorizontalSpacing(12)

    from_label = QLabel(str(texts.get("understanding_speaker_rename_from", "Current")))
    from_label.setObjectName("InlineFieldLabel")
    combo = NoWheelComboBox()
    combo.setObjectName("SearchModeSelect")
    combo.setMinimumWidth(240)
    current_norm = normalize_dialogue_speaker(current)
    select_index = 0
    for index, (label, count) in enumerate(labels):
        combo.addItem(
            str(
                texts.get(
                    "understanding_speaker_rename_item",
                    "{name} ({count})",
                )
            ).format(name=label, count=int(count)),
            label,
        )
        if label == current_norm:
            select_index = index
    combo.setCurrentIndex(select_index)

    to_label = QLabel(str(texts.get("understanding_speaker_rename_to", "Rename to")))
    to_label.setObjectName("InlineFieldLabel")
    edit = QLineEdit()
    edit.setObjectName("SearchInput")
    edit.setPlaceholderText(
        str(texts.get("understanding_speaker_rename_placeholder", "e.g. shopkeeper"))
    )
    prefill = current_norm if current_norm and not is_auto_speaker_label(current_norm) else ""
    if prefill:
        edit.setText(prefill)
    form.addRow(from_label, combo)
    form.addRow(to_label, edit)
    dialog.content_layout.addWidget(form_host)

    result: dict[str, str] = {}

    def _sync_target(_index: int = -1) -> None:
        source = normalize_dialogue_speaker(combo.currentData())
        typed = normalize_dialogue_speaker(edit.text())
        if is_auto_speaker_label(source):
            if not typed or is_auto_speaker_label(typed):
                edit.clear()
            return
        if source:
            edit.setText(source)

    def _accept() -> None:
        source = normalize_dialogue_speaker(combo.currentData())
        target = normalize_dialogue_speaker(edit.text())
        if not source or not target or source == target:
            return
        result["old"] = source
        result["new"] = target
        dialog.accept()

    combo.currentIndexChanged.connect(_sync_target)
    dialog.add_footer_button(
        str(texts.get("cancel", "Cancel")),
        object_name="GhostButton",
        on_click=dialog.reject,
    )
    dialog.add_footer_button(
        str(texts.get("confirm_action", "OK")),
        object_name="PrimaryButton",
        on_click=_accept,
        default=True,
    )
    edit.returnPressed.connect(_accept)
    edit.setFocus(Qt.FocusReason.OtherFocusReason)

    if dialog.exec() != VSDialogShell.DialogCode.Accepted:
        return None
    old = str(result.get("old") or "")
    new = str(result.get("new") or "")
    if not old or not new:
        return None
    return old, new
