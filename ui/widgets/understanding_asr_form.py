"""Speech (ASR) service fields used inside the understanding services dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.components import NoWheelComboBox
from ui.widgets.layout import COMPONENT_SIZES


def _field_label(text=""):
    label = QLabel(text)
    label.setObjectName("CardHint")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setFixedWidth(COMPONENT_SIZES.get("understanding_form_label_width", 96))
    return label


def _configure_line(field: QLineEdit, *, width: int):
    field.setMinimumWidth(width)
    field.setMaximumWidth(width)
    field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class UnderstandingAsrForm(QWidget):
    """Remote speech ASR connection for dialogue without burned-in subtitles."""

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

        self.hint_asr_body = QLabel()
        self.hint_asr_body.setObjectName("CardHint")
        self.hint_asr_body.setWordWrap(True)
        inner_layout.addWidget(self.hint_asr_body)

        form_host = QWidget()
        config_form = QFormLayout(form_host)
        config_form.setContentsMargins(0, 0, 0, 0)
        config_form.setHorizontalSpacing(12)
        config_form.setVerticalSpacing(10)
        config_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        config_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        config_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        config_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.label_asr_provider_mode = _field_label()
        self.input_asr_provider_mode = NoWheelComboBox()
        self.input_asr_provider_mode.setObjectName("SearchModeSelect")
        self.input_asr_provider_mode.setMinimumWidth(180)
        self.input_asr_provider_mode.setMaximumWidth(260)
        config_form.addRow(self.label_asr_provider_mode, self.input_asr_provider_mode)

        self.label_asr_provider_preset = _field_label()
        self.input_asr_provider_preset = NoWheelComboBox()
        self.input_asr_provider_preset.setObjectName("SearchModeSelect")
        self.input_asr_provider_preset.setMinimumWidth(180)
        self.input_asr_provider_preset.setMaximumWidth(260)
        config_form.addRow(self.label_asr_provider_preset, self.input_asr_provider_preset)

        self.label_remote_asr_api_key = _field_label()
        self.input_remote_asr_api_key = QLineEdit()
        self.input_remote_asr_api_key.setObjectName("SearchInput")
        self.input_remote_asr_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        _configure_line(self.input_remote_asr_api_key, width=260)
        config_form.addRow(self.label_remote_asr_api_key, self.input_remote_asr_api_key)

        self.label_remote_asr_base_url = _field_label()
        self.input_remote_asr_base_url = QLineEdit()
        self.input_remote_asr_base_url.setObjectName("SearchInput")
        _configure_line(self.input_remote_asr_base_url, width=260)
        config_form.addRow(self.label_remote_asr_base_url, self.input_remote_asr_base_url)

        self.label_remote_asr_model = _field_label()
        self.input_remote_asr_model = QLineEdit()
        self.input_remote_asr_model.setObjectName("SearchInput")
        _configure_line(self.input_remote_asr_model, width=260)
        config_form.addRow(self.label_remote_asr_model, self.input_remote_asr_model)

        inner_layout.addWidget(form_host)
        self.hint_asr_preset_summary = QLabel()
        self.hint_asr_preset_summary.setObjectName("CardHint")
        self.hint_asr_preset_summary.setWordWrap(True)
        self.hint_asr_preset_summary.hide()
        inner_layout.addWidget(self.hint_asr_preset_summary)

        self.hint_asr_status = QLabel()
        self.hint_asr_status.setObjectName("StatusHint")
        self.hint_asr_status.setWordWrap(True)
        inner_layout.addWidget(self.hint_asr_status)
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
