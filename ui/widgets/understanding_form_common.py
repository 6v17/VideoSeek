"""Shared helpers for understanding VLM / LLM / ASR service forms."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QLineEdit, QSizePolicy

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.styles import repolish_widget


def field_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("CardHint")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setFixedWidth(COMPONENT_SIZES.get("understanding_form_label_width", 96))
    return label


def configure_expanding_line(field: QLineEdit, *, min_width: int = 280) -> None:
    """Let URL / key / model fields grow with the dialog instead of a fixed narrow box."""
    field.setMinimumWidth(int(min_width))
    field.setMaximumWidth(16777215)
    field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def set_status_hint(label: QLabel | None, text: str, *, state: str = "neutral") -> None:
    if label is None:
        return
    label.setText(str(text or ""))
    label.setProperty("state", str(state or "neutral"))
    repolish_widget(label)
