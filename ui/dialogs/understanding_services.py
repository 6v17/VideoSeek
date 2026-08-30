"""Fluent settings dialog for understanding model services (VLM + LLM + ASR)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QWidget,
)

from src.app.i18n import get_texts
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.understanding_asr_form import UnderstandingAsrForm
from ui.widgets.understanding_llm_form import UnderstandingLlmForm
from ui.widgets.understanding_service_form import UnderstandingServiceForm

from .shell import VSDialogShell

_NAV_VLM = "vlm"
_NAV_LLM = "llm"
_NAV_ASR = "asr"


class UnderstandingServicesDialog(VSDialogShell):
    def __init__(self, parent=None, *, is_dark=True, language="zh"):
        self.language = language
        self.texts = get_texts(language)
        self._is_dark = bool(is_dark)

        super().__init__(
            parent,
            title=self.texts.get("understanding_services_dialog_title", "Model services"),
            body=self.texts.get(
                "understanding_services_dialog_body",
                "Vision captions use VLM. Recap scripts use LLM. Speech uses ASR.",
            ),
            card_margins=(16, 16, 16, 14),
            card_spacing=12,
            outer_margins=(12, 12, 12, 12),
        )
        apply_dialog_size(
            self,
            WINDOW_SIZES["understanding_services_dialog"]["preferred"],
            WINDOW_SIZES["understanding_services_dialog"]["minimum"],
            WINDOW_SIZES["understanding_services_dialog"]["screen_margin"],
        )

        split = QWidget()
        split_layout = QHBoxLayout(split)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(14)

        self.nav = QListWidget()
        self.nav.setObjectName("UnderstandingServiceNav")
        self.nav.setFixedWidth(188)
        self.nav.setSpacing(2)
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        self.pages = QStackedWidget()
        self.vlm_form = UnderstandingServiceForm()
        self.llm_form = UnderstandingLlmForm()
        self.asr_form = UnderstandingAsrForm()
        self.pages.addWidget(self.vlm_form)
        self.pages.addWidget(self.llm_form)
        self.pages.addWidget(self.asr_form)

        split_layout.addWidget(self.nav, 0)
        split_layout.addWidget(self.pages, 1)
        self.content_layout.addWidget(split, 1)

        self.btn_close = self.add_footer_button(
            self.texts.get("close", "Close"),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.btn_test_vlm_connection = self.add_footer_button(
            self.texts.get("understanding_test_vlm_connection", "Test connection"),
            object_name="GhostButton",
        )
        self.btn_save_config = self.add_footer_button(
            self.texts.get("understanding_save_config", "Save"),
            object_name="PrimaryButton",
            default=True,
        )

        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self._rebuild_nav()
        self.nav.setCurrentRow(0)
        self._on_nav_changed(0)

    def current_nav_id(self) -> str:
        item = self.nav.currentItem()
        if item is None:
            return _NAV_VLM
        return str(item.data(Qt.ItemDataRole.UserRole) or _NAV_VLM)

    def _rebuild_nav(self) -> None:
        t = self.texts
        current = self.nav.currentItem()
        current_id = current.data(Qt.ItemDataRole.UserRole) if current is not None else _NAV_VLM
        self.nav.blockSignals(True)
        self.nav.clear()
        specs = (
            (_NAV_VLM, t.get("understanding_services_nav_vlm", "Vision (VLM)")),
            (_NAV_LLM, t.get("understanding_services_nav_llm", "Language (LLM)")),
            (_NAV_ASR, t.get("understanding_services_nav_asr", "Speech (ASR)")),
        )
        restore = 0
        for index, (nav_id, label) in enumerate(specs):
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, nav_id)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.nav.addItem(item)
            if nav_id == current_id:
                restore = index
        self.nav.setCurrentRow(restore)
        self.nav.blockSignals(False)

    def _on_nav_changed(self, row: int) -> None:
        item = self.nav.item(max(0, row))
        nav_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else _NAV_VLM
        if nav_id == _NAV_VLM:
            self.pages.setCurrentIndex(0)
            self.btn_test_vlm_connection.setVisible(True)
            self.btn_save_config.setVisible(True)
        elif nav_id == _NAV_LLM:
            self.pages.setCurrentIndex(1)
            self.btn_test_vlm_connection.setVisible(True)
            self.btn_save_config.setVisible(True)
        else:
            self.pages.setCurrentIndex(2)
            self.btn_test_vlm_connection.setVisible(True)
            self.btn_save_config.setVisible(True)

    def apply_texts(self, texts: dict) -> None:
        self.texts = texts
        self.set_title(texts.get("understanding_services_dialog_title", "Model services"))
        self.set_body(
            texts.get(
                "understanding_services_dialog_body",
                "Vision captions use VLM. Recap scripts use LLM. Speech uses ASR.",
            )
        )
        self.btn_close.setText(texts.get("close", "Close"))
        self.btn_test_vlm_connection.setText(
            texts.get("understanding_test_vlm_connection", "Test connection")
        )
        self.btn_test_vlm_connection.setToolTip(
            texts.get("understanding_test_vlm_connection_hint", "")
        )
        self.btn_save_config.setText(texts.get("understanding_save_config", "Save"))
        form = self.llm_form
        form.hint_llm_body.setText(
            texts.get(
                "understanding_llm_form_body",
                "Text model for recap scripts. Keep this separate from the vision model.",
            )
        )
        form.label_llm_provider_mode.setText(texts.get("understanding_llm_provider_mode", "Provider"))
        form.label_llm_provider_preset.setText(texts.get("understanding_llm_provider_preset", "Preset"))
        form.label_remote_llm_api_key.setText(texts.get("setting_remote_vlm_api_key", "API Key"))
        form.input_remote_llm_api_key.setToolTip(texts.get("setting_remote_vlm_api_key_hint", ""))
        form.label_remote_llm_base_url.setText(texts.get("setting_remote_vlm_base_url", "Service URL"))
        form.input_remote_llm_base_url.setToolTip(
            texts.get("understanding_llm_base_url_hint", texts.get("setting_remote_vlm_base_url_hint", ""))
        )
        form.label_remote_llm_model.setText(texts.get("setting_remote_vlm_model", "Model id"))
        form.input_remote_llm_model.setToolTip(
            texts.get("understanding_llm_model_hint", "Text model id from GET /v1/models.")
        )
        asr = self.asr_form
        asr.hint_asr_body.setText(
            texts.get(
                "understanding_asr_form_body",
                "Speech model for videos without burned-in subtitles. OpenAI-compatible /v1/audio/transcriptions.",
            )
        )
        asr.label_asr_provider_mode.setText(texts.get("understanding_asr_provider_mode", "Provider"))
        asr.label_asr_provider_preset.setText(texts.get("understanding_asr_provider_preset", "Preset"))
        asr.label_remote_asr_api_key.setText(texts.get("setting_remote_vlm_api_key", "API Key"))
        asr.input_remote_asr_api_key.setToolTip(texts.get("setting_remote_vlm_api_key_hint", ""))
        asr.label_remote_asr_base_url.setText(texts.get("setting_remote_vlm_base_url", "Service URL"))
        asr.input_remote_asr_base_url.setToolTip(
            texts.get("understanding_asr_base_url_hint", texts.get("setting_remote_vlm_base_url_hint", ""))
        )
        asr.label_remote_asr_model.setText(texts.get("setting_remote_vlm_model", "Model id"))
        asr.input_remote_asr_model.setToolTip(
            texts.get("understanding_asr_model_hint", "Whisper / ASR model id from GET /v1/models.")
        )
        self._rebuild_nav()
        self._on_nav_changed(self.nav.currentRow())
