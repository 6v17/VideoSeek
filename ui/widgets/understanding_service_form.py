"""Vision (VLM) service fields used inside the understanding services dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
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


class UnderstandingServiceForm(QWidget):
    """Caption / VLM connection + custom prompts for the current generation mode."""

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

        form_host = QWidget()
        config_form = QFormLayout(form_host)
        config_form.setContentsMargins(0, 0, 0, 0)
        config_form.setHorizontalSpacing(12)
        config_form.setVerticalSpacing(10)
        config_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        config_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        config_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        config_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.label_vlm_section = QLabel()
        self.label_vlm_section.setObjectName("CardHint")
        self.label_vlm_section.hide()

        self.label_vlm_provider_mode = _field_label()
        self.input_vlm_provider_mode = NoWheelComboBox()
        self.input_vlm_provider_mode.setObjectName("SearchModeSelect")
        self.input_vlm_provider_mode.setMinimumWidth(180)
        self.input_vlm_provider_mode.setMaximumWidth(260)
        config_form.addRow(self.label_vlm_provider_mode, self.input_vlm_provider_mode)

        self.label_vlm_provider_preset = _field_label()
        self.input_vlm_provider_preset = NoWheelComboBox()
        self.input_vlm_provider_preset.setObjectName("SearchModeSelect")
        self.input_vlm_provider_preset.setMinimumWidth(220)
        self.input_vlm_provider_preset.setMaximumWidth(320)
        config_form.addRow(self.label_vlm_provider_preset, self.input_vlm_provider_preset)

        self.hint_vlm_preset_summary = QLabel()
        self.hint_vlm_preset_summary.setObjectName("CardHint")
        self.hint_vlm_preset_summary.setWordWrap(True)
        self.hint_vlm_preset_summary.hide()
        config_form.addRow(self.hint_vlm_preset_summary)

        self.label_remote_vlm_api_key = _field_label()
        self.input_remote_vlm_api_key = QLineEdit()
        self.input_remote_vlm_api_key.setObjectName("SearchInput")
        self.input_remote_vlm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        _configure_line(
            self.input_remote_vlm_api_key,
            width=COMPONENT_SIZES.get("settings_path_input_width", 520),
        )
        self.hint_remote_vlm_api_key = QLabel()
        self.hint_remote_vlm_api_key.setObjectName("CardHint")
        self.hint_remote_vlm_api_key.hide()
        config_form.addRow(self.label_remote_vlm_api_key, self.input_remote_vlm_api_key)

        self.label_remote_vlm_base_url = _field_label()
        self.input_remote_vlm_base_url = QLineEdit()
        self.input_remote_vlm_base_url.setObjectName("SearchInput")
        _configure_line(
            self.input_remote_vlm_base_url,
            width=COMPONENT_SIZES.get("settings_path_input_width", 520),
        )
        self.hint_remote_vlm_base_url = QLabel()
        self.hint_remote_vlm_base_url.setObjectName("CardHint")
        self.hint_remote_vlm_base_url.hide()
        config_form.addRow(self.label_remote_vlm_base_url, self.input_remote_vlm_base_url)

        self.label_remote_vlm_model = _field_label()
        self.input_remote_vlm_model = QLineEdit()
        self.input_remote_vlm_model.setObjectName("SearchInput")
        _configure_line(
            self.input_remote_vlm_model,
            width=COMPONENT_SIZES.get("settings_input_width", 116) + 180,
        )
        self.hint_remote_vlm_model = QLabel()
        self.hint_remote_vlm_model.setObjectName("CardHint")
        self.hint_remote_vlm_model.hide()
        config_form.addRow(self.label_remote_vlm_model, self.input_remote_vlm_model)

        self.label_caption_concurrency = _field_label()
        self.input_caption_concurrency = QSpinBox()
        self.input_caption_concurrency.setObjectName("SearchModeSelect")
        self.input_caption_concurrency.setMinimum(1)
        self.input_caption_concurrency.setMaximum(4)
        self.input_caption_concurrency.setMinimumWidth(80)
        self.input_caption_concurrency.setMaximumWidth(120)
        config_form.addRow(self.label_caption_concurrency, self.input_caption_concurrency)

        inner_layout.addWidget(form_host)

        self.prompt_advanced = QFrame()
        self.prompt_advanced.setObjectName("UnderstandingPromptAdvanced")
        prompt_adv_layout = QVBoxLayout(self.prompt_advanced)
        prompt_adv_layout.setContentsMargins(0, 4, 0, 0)
        prompt_adv_layout.setSpacing(8)

        self.chk_use_custom_prompts = QCheckBox()
        prompt_adv_layout.addWidget(self.chk_use_custom_prompts, 0)

        self.custom_prompt_fields = QWidget()
        custom_fields_layout = QVBoxLayout(self.custom_prompt_fields)
        custom_fields_layout.setContentsMargins(0, 0, 0, 0)
        custom_fields_layout.setSpacing(8)

        self.hint_custom_prompts = QLabel()
        self.hint_custom_prompts.setObjectName("CardHint")
        self.hint_custom_prompts.setWordWrap(True)
        custom_fields_layout.addWidget(self.hint_custom_prompts)

        self.label_custom_caption_prompt = _field_label()
        self.label_custom_caption_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_caption_prompt)
        self.input_custom_caption_prompt = QPlainTextEdit()
        self.input_custom_caption_prompt.setObjectName("SearchInput")
        self.input_custom_caption_prompt.setFixedHeight(72)
        self.input_custom_caption_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_caption_prompt)

        self.label_custom_description_prompt = _field_label()
        self.label_custom_description_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_description_prompt)
        self.input_custom_description_prompt = QPlainTextEdit()
        self.input_custom_description_prompt.setObjectName("SearchInput")
        self.input_custom_description_prompt.setFixedHeight(72)
        self.input_custom_description_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_description_prompt)

        self.label_custom_motion_prompt = _field_label()
        self.label_custom_motion_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_motion_prompt)
        self.input_custom_motion_prompt = QPlainTextEdit()
        self.input_custom_motion_prompt.setObjectName("SearchInput")
        self.input_custom_motion_prompt.setFixedHeight(72)
        self.input_custom_motion_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_motion_prompt)

        self.label_custom_summary_prompt = _field_label()
        self.label_custom_summary_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_summary_prompt)
        self.input_custom_summary_prompt = QPlainTextEdit()
        self.input_custom_summary_prompt.setObjectName("SearchInput")
        self.input_custom_summary_prompt.setFixedHeight(72)
        self.input_custom_summary_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_summary_prompt)

        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.setSpacing(8)
        self.btn_reset_custom_prompts = QPushButton()
        self.btn_reset_custom_prompts.setObjectName("GhostButton")
        self.btn_reset_custom_prompts.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_custom_prompts.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        reset_row.addWidget(self.btn_reset_custom_prompts, 0)
        reset_row.addStretch(1)
        custom_fields_layout.addLayout(reset_row)

        self.custom_prompt_fields.hide()
        prompt_adv_layout.addWidget(self.custom_prompt_fields)
        inner_layout.addWidget(self.prompt_advanced)

        self.hint_understanding_status = QLabel()
        self.hint_understanding_status.setObjectName("StatusHint")
        self.hint_understanding_status.setWordWrap(True)
        inner_layout.addWidget(self.hint_understanding_status)
        inner_layout.addStretch(1)

        scroll.setWidget(inner)
        root.addWidget(scroll, 1)
