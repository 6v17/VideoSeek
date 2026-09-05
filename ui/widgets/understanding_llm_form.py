"""Language (LLM) service fields used inside the understanding services dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.components import NoWheelComboBox
from ui.widgets.understanding_form_common import configure_expanding_line, field_label


class UnderstandingLlmForm(QWidget):
    """Text LLM connection for recap / script jobs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setObjectName("DialogScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 4, 0)
        inner_layout.setSpacing(10)

        self.hint_llm_body = QLabel()
        self.hint_llm_body.setObjectName("CardHint")
        self.hint_llm_body.setWordWrap(True)
        inner_layout.addWidget(self.hint_llm_body)

        form_host = QWidget()
        config_form = QFormLayout(form_host)
        config_form.setContentsMargins(0, 0, 0, 0)
        config_form.setHorizontalSpacing(12)
        config_form.setVerticalSpacing(10)
        config_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        config_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        config_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        config_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.label_llm_provider_mode = field_label()
        self.input_llm_provider_mode = NoWheelComboBox()
        self.input_llm_provider_mode.setObjectName("SearchModeSelect")
        self.input_llm_provider_mode.setMinimumWidth(180)
        self.input_llm_provider_mode.setMaximumWidth(320)
        config_form.addRow(self.label_llm_provider_mode, self.input_llm_provider_mode)

        self.label_llm_provider_preset = field_label()
        self.input_llm_provider_preset = NoWheelComboBox()
        self.input_llm_provider_preset.setObjectName("SearchModeSelect")
        self.input_llm_provider_preset.setMinimumWidth(180)
        self.input_llm_provider_preset.setMaximumWidth(360)
        config_form.addRow(self.label_llm_provider_preset, self.input_llm_provider_preset)

        self.label_remote_llm_api_key = field_label()
        self.input_remote_llm_api_key = QLineEdit()
        self.input_remote_llm_api_key.setObjectName("SearchInput")
        self.input_remote_llm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_remote_llm_api_key.setPlaceholderText("sk-…")
        configure_expanding_line(self.input_remote_llm_api_key)
        config_form.addRow(self.label_remote_llm_api_key, self.input_remote_llm_api_key)

        self.label_remote_llm_base_url = field_label()
        self.input_remote_llm_base_url = QLineEdit()
        self.input_remote_llm_base_url.setObjectName("SearchInput")
        self.input_remote_llm_base_url.setPlaceholderText("https://…/v1")
        configure_expanding_line(self.input_remote_llm_base_url)
        config_form.addRow(self.label_remote_llm_base_url, self.input_remote_llm_base_url)

        self.label_remote_llm_model = field_label()
        self.input_remote_llm_model = QLineEdit()
        self.input_remote_llm_model.setObjectName("SearchInput")
        self.input_remote_llm_model.setPlaceholderText("text-model-id")
        configure_expanding_line(self.input_remote_llm_model, min_width=220)
        config_form.addRow(self.label_remote_llm_model, self.input_remote_llm_model)

        inner_layout.addWidget(form_host)
        self.hint_llm_preset_summary = QLabel()
        self.hint_llm_preset_summary.setObjectName("CardHint")
        self.hint_llm_preset_summary.setWordWrap(True)
        self.hint_llm_preset_summary.hide()
        inner_layout.addWidget(self.hint_llm_preset_summary)

        self.hint_llm_status = QLabel()
        self.hint_llm_status.setObjectName("StatusHint")
        self.hint_llm_status.setWordWrap(True)
        self.hint_llm_status.setProperty("state", "neutral")
        inner_layout.addWidget(self.hint_llm_status)
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
