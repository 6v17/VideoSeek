"""Understanding evidence generation UI — dedicated sidebar page."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QApplication, QAbstractItemView, QFileDialog, QScrollArea

from src.app.config import load_config, save_config, DEFAULT_CONFIG
from src.app.indexing_progress import format_progress_text
from src.services.library_service import list_libraries
from src.services.understanding_resource_service import (
    REMOTE_VLM_MODE_CLOUD,
    REMOTE_VLM_MODE_LOCAL,
    REMOTE_VLM_PRESET_CUSTOM,
    get_remote_vlm_api_key_for_preset,
    get_remote_vlm_preset_defaults,
    get_understanding_resource_status,
    list_remote_vlm_preset_ids,
    normalize_remote_vlm_api_keys,
    normalize_remote_vlm_provider_mode,
    set_remote_vlm_api_key_for_preset,
)
from src.services.understanding_service import (
    clear_all_evidence,
    delete_evidence_for_videos,
    list_local_evidence_details,
    list_ready_video_entries,
    load_evidence_bundle,
    resolve_video_context,
)
from src.services.indexing_service import load_video_chunks_by_id
from src.utils import format_timecode_range, open_folder_in_explorer, open_in_explorer
from ui.dialogs import ResourceTableDialog
from ui.widgets.chunk_timeline import ChunkTimelineSegment
from ui.workers import RemoteVlmConnectionTestWorker


class _UnderstandingConfigHost:
    """VLM connection fields live on the services dialog; language/prompts stay on the page."""

    __slots__ = ("_window",)

    def __init__(self, window):
        self._window = window

    def __getattr__(self, name):
        window = self._window
        dialog = getattr(window, "understanding_services_dialog", None)
        form = getattr(dialog, "vlm_form", None) if dialog is not None else None
        page = getattr(window, "understanding_page", None)
        for owner in (form, dialog, page):
            if owner is not None and hasattr(owner, name):
                return getattr(owner, name)
        raise AttributeError(name)


class UnderstandingGuiMixin:
    """Sidebar page for manual understanding evidence generation."""

    def _understanding_config_widgets(self):
        if getattr(self, "understanding_page", None) is None:
            return None
        return _UnderstandingConfigHost(self)

    def load_understanding_settings(self, *, refresh_status: bool = True):
        page = self._understanding_config_widgets()
        if page is None:
            return
        try:
            config = load_config()
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_config_load_failed", "Failed to load settings."), exc)
            return
        from src.services.understanding_resource_service import get_remote_vlm_settings

        remote_vlm = dict(get_remote_vlm_settings(config))
        self._remote_vlm_api_keys = normalize_remote_vlm_api_keys(remote_vlm.get("api_keys"))
        self._populate_vlm_provider_mode_options(remote_vlm.get("provider_mode", REMOTE_VLM_MODE_LOCAL))
        self._populate_vlm_provider_preset_options(
            remote_vlm.get("provider_mode", REMOTE_VLM_MODE_LOCAL),
            remote_vlm.get("provider_preset", "lm_studio"),
        )
        page.input_remote_vlm_base_url.setText(str(remote_vlm.get("base_url", "") or ""))
        page.input_remote_vlm_api_key.setText(
            get_remote_vlm_api_key_for_preset(
                remote_vlm,
                remote_vlm.get("provider_preset", "lm_studio"),
                mode=remote_vlm.get("provider_mode", REMOTE_VLM_MODE_LOCAL),
            )
        )
        page.input_remote_vlm_model.setText(str(remote_vlm.get("model", "") or ""))
        self._sync_vlm_provider_ui()
        self._remember_vlm_ui_selection(page)
        self._populate_understanding_caption_language_options(remote_vlm.get("caption_language", "zh"))
        page.input_caption_concurrency.setValue(
            max(1, min(4, int(remote_vlm.get("concurrency", 2) or 2)))
        )
        self._load_vlm_prompt_editors(remote_vlm)
        self._sync_understanding_mode_ui()
        self._load_llm_settings(config)
        self._load_asr_settings(config)
        self._understanding_settings_applied = True
        if refresh_status:
            self._refresh_understanding_settings_status()

    def _current_understanding_mode(self) -> str:
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION

        return UNDERSTANDING_MODE_MOTION

    def _sync_understanding_mode_ui(self, *, reload_timeline: bool = False, reload_dialogue: bool = False):
        page = self._understanding_config_widgets()
        if page is None:
            return
        page.btn_generate_evidence.setText(
            self.texts.get("understanding_generate_motion_button", "Generate change notes")
        )
        page.btn_generate_batch.setText(
            self.texts.get("understanding_generate_batch_motion", "Batch change notes")
        )
        page.btn_generate_batch.setToolTip(
            self.texts.get(
                "understanding_generate_batch_tip",
                "Queue videos in the current scope that are still missing results for this mode. Processes one video at a time.",
            )
        )
        page.chunk_detail_title.setText(
            self.texts.get("understanding_chunk_detail_title_motion", "Segment change")
        )
        if hasattr(page, "order_workflow_cards"):
            # Layout order is fixed at page build; do not reshuffle on every label sync.
            page.order_workflow_cards(recap_first=True)
        if hasattr(page, "generate_title"):
            page.generate_title.setText(
                self.texts.get("understanding_step_generate_title_motion", "4. Optional full-video change notes")
            )
        if hasattr(page, "dialogue_title"):
            page.dialogue_title.setText(
                self.texts.get("understanding_step_dialogue_title_motion", "2. Extract speech")
            )
        if hasattr(page, "export_title"):
            page.export_title.setText(
                self.texts.get("understanding_step_export_title_motion", "3. Recap cuts")
            )
        if hasattr(page, "select_hint"):
            page.select_hint.setText(
                self.texts.get("understanding_step_select_hint_motion", page.select_hint.text())
            )
        if hasattr(page, "header"):
            page.header.subtitle.setText(
                self.texts.get("understanding_page_desc_motion", page.header.subtitle.text())
            )
        if page.btn_generate_evidence.objectName() != "GhostButton":
            page.btn_generate_evidence.setObjectName("GhostButton")
            style = page.btn_generate_evidence.style()
            style.unpolish(page.btn_generate_evidence)
            style.polish(page.btn_generate_evidence)
            page.btn_generate_evidence.update()
        page.btn_evidence_details.setText(
            self.texts.get(
                "library_evidence_detail_motion",
                self.texts.get("library_evidence_detail", "Change history"),
            )
        )
        if hasattr(page, "video_summary_card"):
            page.video_summary_card.hide()
        if hasattr(page, "video_summary_text"):
            self._set_understanding_readonly_text(page.video_summary_text, "")
        if hasattr(page, "video_summary_meta_label"):
            page.video_summary_meta_label.setText("")
        if hasattr(page, "export_card"):
            page.export_card.setVisible(True)
        if hasattr(page, "generate_hint"):
            page.generate_hint.setText(
                self.texts.get(
                    "understanding_step_generate_hint_motion",
                    "Optional: caption every segment now. Recap can fill beat windows later.",
                )
            )
        self._sync_vlm_prompt_tab_for_mode()
        page.btn_export_video_json.setEnabled(
            (not (getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()))
            and self._current_video_has_exportable_evidence()
        )
        recap_buttons = (
            "btn_export_recap",
            "btn_recap_step_plan",
            "btn_recap_step_match",
            "btn_recap_step_captions",
            "btn_edit_recap_beats",
            "btn_recap_jianying",
            "btn_recap_fcpxml",
        )
        for name in recap_buttons:
            button = getattr(page, name, None)
            if button is not None:
                button.setVisible(True)
        for bar_name in ("recap_step_bar", "recap_main_bar"):
            bar = getattr(page, bar_name, None)
            if bar is not None:
                bar.setVisible(True)
        if hasattr(page, "recap_start_hint"):
            page.recap_start_hint.setVisible(True)
        # Dialogue table is filled by timeline / ASR handlers — not on every label sync.
        self._sync_recap_export_button()
        if hasattr(page, "export_hint"):
            page.export_hint.setText(
                self.texts.get("understanding_step_export_hint_motion", "")
            )
        if reload_timeline:
            self._load_understanding_video_timeline()
        elif reload_dialogue:
            self._refresh_understanding_dialogue_step()
        if hasattr(page, "chunk_sample_frames"):
            page.chunk_sample_frames.setVisible(True)

    def _on_understanding_caption_language_changed(self, *_args):
        self._refresh_vlm_prompt_editors_for_language()
        self._persist_understanding_job_options()

    def _persist_understanding_job_options(self) -> None:
        """Write mode + caption language without requiring Save on the service form."""
        page = self._understanding_config_widgets()
        if page is None:
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        try:
            config = load_config()
            understanding = config.get("understanding")
            if not isinstance(understanding, dict):
                understanding = {}
                config["understanding"] = understanding
            remote_vlm = dict(
                understanding.get("remote_vlm") or DEFAULT_CONFIG["understanding"]["remote_vlm"]
            )
            from src.services.understanding_resource_service import (
                finalize_remote_vlm_settings,
                normalize_caption_language,
            )

            remote_vlm["caption_language"] = normalize_caption_language(
                page.input_caption_language.currentData()
            )
            remote_vlm["understanding_mode"] = self._current_understanding_mode()
            self._apply_vlm_prompts_from_page(remote_vlm)
            understanding["remote_vlm"] = finalize_remote_vlm_settings(remote_vlm)
            config["understanding"] = understanding
            save_config(config)
        except Exception as exc:
            from src.app.logging_utils import get_logger

            get_logger("understanding.ui").warning("Failed to persist understanding job options: %s", exc)

    def _populate_understanding_caption_language_options(self, active_language=None):
        page = self._understanding_config_widgets()
        if page is None:
            return
        combo = page.input_caption_language
        active = str(active_language or "zh").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.texts.get("understanding_caption_language_zh", "中文"), "zh")
        combo.addItem(self.texts.get("understanding_caption_language_en", "English"), "en")
        index = combo.findData(active if active in {"zh", "en"} else "zh")
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _vlm_provider_mode_label(self, mode: str) -> str:
        if mode == REMOTE_VLM_MODE_CLOUD:
            return self.texts.get("understanding_vlm_provider_mode_cloud", "Cloud API")
        return self.texts.get("understanding_vlm_provider_mode_local", "Local")

    def _vlm_provider_preset_label(self, preset_id: str) -> str:
        key = f"understanding_vlm_provider_preset_{preset_id}"
        defaults = {
            "lm_studio": "LM Studio",
            "ollama": "Ollama",
            "openai": "OpenAI",
            "dashscope": "DashScope (Qwen)",
            "siliconflow": "SiliconFlow",
            REMOTE_VLM_PRESET_CUSTOM: "Custom",
        }
        return self.texts.get(key, defaults.get(preset_id, preset_id))

    def _populate_vlm_provider_mode_options(self, active_mode=None):
        page = self._understanding_config_widgets()
        if page is None:
            return
        combo = page.input_vlm_provider_mode
        active = normalize_remote_vlm_provider_mode(active_mode)
        combo.blockSignals(True)
        combo.clear()
        for mode in (REMOTE_VLM_MODE_LOCAL, REMOTE_VLM_MODE_CLOUD):
            combo.addItem(self._vlm_provider_mode_label(mode), mode)
        index = combo.findData(active)
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _populate_vlm_provider_preset_options(self, mode, active_preset=None):
        page = self._understanding_config_widgets()
        if page is None:
            return
        combo = page.input_vlm_provider_preset
        normalized_mode = normalize_remote_vlm_provider_mode(mode)
        active = str(active_preset or "").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        preset_ids = list_remote_vlm_preset_ids(mode=normalized_mode)
        for preset_id in preset_ids:
            combo.addItem(self._vlm_provider_preset_label(preset_id), preset_id)
        index = combo.findData(active if active in preset_ids else preset_ids[0])
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _sync_vlm_provider_ui(self):
        page = self._understanding_config_widgets()
        if page is None:
            return
        mode = normalize_remote_vlm_provider_mode(page.input_vlm_provider_mode.currentData())
        preset_id = str(page.input_vlm_provider_preset.currentData() or REMOTE_VLM_PRESET_CUSTOM)
        is_cloud = mode == REMOTE_VLM_MODE_CLOUD
        is_custom = preset_id == REMOTE_VLM_PRESET_CUSTOM
        preset_defaults = get_remote_vlm_preset_defaults(preset_id) if not is_custom else {}

        page.label_remote_vlm_api_key.setVisible(is_cloud)
        page.input_remote_vlm_api_key.setVisible(is_cloud)
        page.label_remote_vlm_base_url.setVisible(is_custom)
        page.input_remote_vlm_base_url.setVisible(is_custom)
        page.label_remote_vlm_model.setVisible(True)
        page.input_remote_vlm_model.setVisible(True)

        if is_custom:
            page.hint_vlm_preset_summary.hide()
            return

        if preset_defaults.get("base_url"):
            page.input_remote_vlm_base_url.setText(str(preset_defaults.get("base_url") or ""))
        current = str(page.input_remote_vlm_model.text() or "").strip()
        model = current or str(preset_defaults.get("model", "") or "").strip()
        if model and not current:
            page.input_remote_vlm_model.setText(model)
        preset_label = self._vlm_provider_preset_label(preset_id)
        endpoint = str(preset_defaults.get("base_url", "") or page.input_remote_vlm_base_url.text() or "").strip()
        if model:
            if is_cloud:
                summary = self.texts.get(
                    "understanding_vlm_preset_model_summary_cloud",
                    "Preset {preset}: {model} via {base_url}. Enter an API Key; change the model id if your account list differs.",
                ).format(preset=preset_label, model=model, base_url=endpoint or "—")
            else:
                summary = self.texts.get(
                    "understanding_vlm_preset_model_summary_local",
                    "Preset {preset}: {model} via {base_url}. Load a compatible vision model in your local server.",
                ).format(preset=preset_label, model=model, base_url=endpoint or "—")
            page.hint_vlm_preset_summary.setText(summary)
            page.hint_vlm_preset_summary.show()
        else:
            page.hint_vlm_preset_summary.hide()

    def _remember_vlm_ui_selection(self, page):
        if page is None:
            return
        self._vlm_ui_mode = normalize_remote_vlm_provider_mode(page.input_vlm_provider_mode.currentData())
        self._vlm_ui_preset = str(page.input_vlm_provider_preset.currentData() or REMOTE_VLM_PRESET_CUSTOM)

    def _commit_vlm_api_key_draft(self, page):
        if page is None:
            return
        if not hasattr(self, "_remote_vlm_api_keys") or not isinstance(getattr(self, "_remote_vlm_api_keys", None), dict):
            self._remote_vlm_api_keys = {}
        preset_id = getattr(self, "_vlm_ui_preset", None)
        mode = getattr(self, "_vlm_ui_mode", None)
        if not preset_id or not mode:
            self._remember_vlm_ui_selection(page)
            preset_id = self._vlm_ui_preset
            mode = self._vlm_ui_mode
        self._remote_vlm_api_keys = set_remote_vlm_api_key_for_preset(
            self._remote_vlm_api_keys,
            preset_id,
            page.input_remote_vlm_api_key.text(),
            mode=mode,
        )

    def _stash_vlm_api_key_for_active_preset(self, page):
        self._commit_vlm_api_key_draft(page)

    def _load_vlm_api_key_for_preset(self, page, preset_id: str, mode: str):
        if page is None:
            return
        if not hasattr(self, "_remote_vlm_api_keys") or not isinstance(getattr(self, "_remote_vlm_api_keys", None), dict):
            self._remote_vlm_api_keys = {}
        draft = {
            "api_keys": self._remote_vlm_api_keys,
            "provider_preset": preset_id,
            "provider_mode": mode,
        }
        page.input_remote_vlm_api_key.setText(
            get_remote_vlm_api_key_for_preset(draft, preset_id, mode=mode)
        )

    def _resolve_vlm_fields_for_save(self, page):
        provider_mode = normalize_remote_vlm_provider_mode(page.input_vlm_provider_mode.currentData())
        provider_preset = str(page.input_vlm_provider_preset.currentData() or REMOTE_VLM_PRESET_CUSTOM)
        if provider_preset != REMOTE_VLM_PRESET_CUSTOM:
            defaults = get_remote_vlm_preset_defaults(provider_preset)
            base_url = str(defaults.get("base_url", "") or page.input_remote_vlm_base_url.text() or "").strip()
            model = page.input_remote_vlm_model.text().strip() or str(defaults.get("model", "") or "").strip()
        else:
            base_url = page.input_remote_vlm_base_url.text().strip()
            model = page.input_remote_vlm_model.text().strip()
        return provider_mode, provider_preset, base_url, model

    def _build_remote_vlm_draft_from_page(self, page):
        self._stash_vlm_api_key_for_active_preset(page)
        provider_mode, provider_preset, base_url, model = self._resolve_vlm_fields_for_save(page)
        return {
            "provider_mode": provider_mode,
            "provider_preset": provider_preset,
            "base_url": base_url,
            "model": model,
            "api_keys": dict(self._remote_vlm_api_keys),
        }

    def _format_vlm_probe_status(self, probe: dict) -> str:
        probe = dict(probe or {})
        model = str(probe.get("configured_model", "") or "").strip()
        base_url = str(probe.get("base_url", "") or "").strip()
        error_code = str(probe.get("error_code", "") or "").strip()
        if probe.get("reachable") and probe.get("model_available"):
            if base_url:
                return self.texts.get(
                    "understanding_test_connection_success_with_endpoint",
                    "Connected. Model {model} is available at {base_url}.",
                ).format(model=model or "?", base_url=base_url)
            return self.texts.get(
                "understanding_test_vlm_success",
                "Connection OK. Model {model} is available.",
            ).format(model=model or "?")
        if error_code == "cloud_api_key_required":
            return self.texts.get(
                "understanding_test_vlm_api_key_required",
                "Enter an API Key before testing a cloud provider.",
            )
        if error_code == "auth_failed":
            return self.texts.get(
                "understanding_test_vlm_auth_failed",
                "API Key invalid or unauthorized.",
            )
        if error_code == "model_not_found":
            available = [str(item) for item in (probe.get("available_models") or []) if str(item).strip()]
            sample = ", ".join(available[:8])
            if len(available) > 8:
                sample = f"{sample} (+{len(available) - 8})"
            return self.texts.get(
                "understanding_test_vlm_model_missing",
                "Connected, but model {model} is not in your account list. Available: {samples}",
            ).format(model=model or "?", samples=sample or self.texts.get("understanding_test_vlm_no_models", "none"))
        if error_code == "timeout":
            return self.texts.get(
                "understanding_test_vlm_timeout",
                "Connection timed out: {error}",
            ).format(error=str(probe.get("error", "") or "timeout"))
        return self.texts.get(
            "understanding_test_vlm_failed",
            "Connection failed: {error}",
        ).format(error=str(probe.get("error", "") or "unknown error"))

    def _probe_status_state(self, probe: dict) -> str:
        probe = dict(probe or {})
        if probe.get("reachable") and probe.get("model_available"):
            return "ok"
        error_code = str(probe.get("error_code", "") or "").strip()
        if error_code in {"cloud_api_key_required", "model_not_found"}:
            return "warn"
        return "error"

    def test_understanding_service_connection(self):
        dialog = getattr(self, "understanding_services_dialog", None)
        nav_id = ""
        if dialog is not None and getattr(dialog, "current_nav_id", None):
            nav_id = str(dialog.current_nav_id() or "")
        if nav_id == "llm":
            self.test_understanding_llm_connection()
            return
        if nav_id == "asr":
            self.test_understanding_asr_connection()
            return
        self.test_understanding_vlm_connection()

    def test_understanding_vlm_connection(self):
        dialog = getattr(self, "understanding_services_dialog", None)
        if dialog is not None and getattr(dialog, "current_nav_id", None) and dialog.current_nav_id() == "llm":
            self.test_understanding_llm_connection()
            return
        page = self._understanding_config_widgets()
        if page is None:
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        if getattr(self, "_vlm_connection_test_worker", None) is not None:
            return

        draft = self._build_remote_vlm_draft_from_page(page)
        hint = getattr(page, "hint_understanding_status", None)
        from ui.widgets.understanding_form_common import set_status_hint

        set_status_hint(
            hint,
            self.texts.get("understanding_test_vlm_testing", "Testing description service…"),
            state="neutral",
        )

        worker = RemoteVlmConnectionTestWorker(draft, timeout_sec=8.0, parent=self)
        self._vlm_connection_test_worker = worker
        page.btn_test_vlm_connection.setEnabled(False)

        def _finish(active_worker=worker):
            if getattr(self, "_vlm_connection_test_worker", None) is active_worker:
                self._vlm_connection_test_worker = None
            page.btn_test_vlm_connection.setEnabled(True)
            try:
                active_worker.deleteLater()
            except Exception:
                pass

        worker.result_ready.connect(
            lambda probe, active_page=page, active_hint=hint: self._finish_vlm_connection_test(probe, active_page, active_hint)
        )
        worker.error_signal.connect(
            lambda message, active_page=page, active_hint=hint: self._fail_vlm_connection_test(message, active_page, active_hint)
        )
        worker.finished.connect(_finish)
        worker.start()

    def _finish_vlm_connection_test(self, probe, page, hint):
        from ui.widgets.understanding_form_common import set_status_hint

        self._cached_vlm_connection_probe = dict(probe or {})
        message = self._format_vlm_probe_status(probe)
        set_status_hint(hint, message, state=self._probe_status_state(probe))
        live = str(dict(probe or {}).get("configured_model") or "").strip()
        if live and dict(probe or {}).get("reachable"):
            page.input_remote_vlm_model.setText(live)
            self._sync_vlm_provider_ui()
        self._refresh_understanding_settings_status()
        if dict(probe or {}).get("reachable") and dict(probe or {}).get("model_available"):
            self.show_info_dialog(
                self.texts.get("understanding_test_vlm_title", "Connection test"),
                message,
                kind="success",
            )
        elif dict(probe or {}).get("error_code") != "cloud_api_key_required":
            self.show_error_dialog(message)

    def _fail_vlm_connection_test(self, message, page, hint):
        from ui.widgets.understanding_form_common import set_status_hint

        text = self.texts.get(
            "understanding_test_vlm_failed",
            "Connection failed: {error}",
        ).format(error=str(message or "unknown error"))
        self._cached_vlm_connection_probe = {
            "reachable": False,
            "model_available": False,
            "error": str(message or "unknown error"),
        }
        set_status_hint(hint, text, state="error")
        self._refresh_understanding_settings_status()
        self.show_error_dialog(text)

    def _clear_cached_vlm_connection_probe(self):
        self._cached_vlm_connection_probe = None

    def _apply_vlm_provider_preset(self, preset_id: str):
        page = self._understanding_config_widgets()
        if page is None:
            return
        preset_id = str(preset_id or "").strip().lower()
        mode = normalize_remote_vlm_provider_mode(page.input_vlm_provider_mode.currentData())
        if preset_id == REMOTE_VLM_PRESET_CUSTOM:
            self._sync_vlm_provider_ui()
            self._load_vlm_api_key_for_preset(page, preset_id, mode)
            return
        defaults = get_remote_vlm_preset_defaults(preset_id)
        if not defaults:
            self._sync_vlm_provider_ui()
            self._load_vlm_api_key_for_preset(page, preset_id, mode)
            return
        page.input_remote_vlm_base_url.setText(defaults.get("base_url", ""))
        page.input_remote_vlm_model.setText(defaults.get("model", ""))
        self._sync_vlm_provider_ui()
        if mode == REMOTE_VLM_MODE_CLOUD:
            self._load_vlm_api_key_for_preset(page, preset_id, mode)
        else:
            page.input_remote_vlm_api_key.setText("")

    def _on_vlm_provider_mode_changed(self, _index=None):
        page = self._understanding_config_widgets()
        if page is None:
            return
        self._commit_vlm_api_key_draft(page)
        self._clear_cached_vlm_connection_probe()
        mode = normalize_remote_vlm_provider_mode(page.input_vlm_provider_mode.currentData())
        default_preset = "openai" if mode == REMOTE_VLM_MODE_CLOUD else "lm_studio"
        self._populate_vlm_provider_preset_options(mode, default_preset)
        self._apply_vlm_provider_preset(default_preset)
        self._remember_vlm_ui_selection(page)

    def _on_vlm_provider_preset_changed(self, _index=None):
        page = self._understanding_config_widgets()
        if page is None:
            return
        self._commit_vlm_api_key_draft(page)
        preset_id = str(page.input_vlm_provider_preset.currentData() or REMOTE_VLM_PRESET_CUSTOM)
        self._apply_vlm_provider_preset(preset_id)
        self._remember_vlm_ui_selection(page)

    def save_understanding_settings(self):
        if not self._ensure_startup_migration_idle("feature_understanding"):
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        page = self._understanding_config_widgets()
        if page is None:
            return
        try:
            config = load_config()
            understanding = config.get("understanding")
            if not isinstance(understanding, dict):
                understanding = {}
                config["understanding"] = understanding
            remote_vlm = dict(understanding.get("remote_vlm") or DEFAULT_CONFIG["understanding"]["remote_vlm"])
            self._stash_vlm_api_key_for_active_preset(page)
            provider_mode, provider_preset, base_url, model = self._resolve_vlm_fields_for_save(page)
            remote_vlm["provider_mode"] = provider_mode
            remote_vlm["provider_preset"] = provider_preset
            remote_vlm["base_url"] = base_url
            remote_vlm["model"] = model
            remote_vlm["api_keys"] = dict(self._remote_vlm_api_keys)
            from src.services.understanding_resource_service import (
                finalize_remote_vlm_settings,
                normalize_caption_language,
            )

            language = normalize_caption_language(page.input_caption_language.currentData())
            remote_vlm["caption_language"] = language
            remote_vlm["understanding_mode"] = self._current_understanding_mode()
            self._apply_vlm_prompts_from_page(remote_vlm)
            remote_vlm["concurrency"] = int(page.input_caption_concurrency.value())
            understanding["remote_vlm"] = finalize_remote_vlm_settings(remote_vlm)
            self._commit_llm_settings_to_understanding(understanding)
            self._commit_asr_settings_to_understanding(understanding)
            config["understanding"] = understanding
            save_config(config)
            self._clear_cached_vlm_connection_probe()
            self._invalidate_understanding_status_cache()
            self._refresh_understanding_page_fast(install_bootstrap=True)
            message = self.texts.get("understanding_config_saved", "Understanding settings saved.")
            page.lbl_status.setText(message)
            self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_config_save_failed", "Failed to save settings."), exc)

    def _set_understanding_config_enabled(self, enabled: bool):
        page = self._understanding_config_widgets()
        if page is None:
            return
        page.input_vlm_provider_mode.setEnabled(enabled)
        page.input_vlm_provider_preset.setEnabled(enabled)
        page.input_remote_vlm_base_url.setEnabled(enabled)
        page.input_remote_vlm_api_key.setEnabled(enabled)
        page.input_remote_vlm_model.setEnabled(enabled)
        page.input_caption_language.setEnabled(enabled)
        if hasattr(page, "input_understanding_mode"):
            page.input_understanding_mode.setEnabled(enabled)
        page.input_caption_concurrency.setEnabled(enabled)
        page.btn_test_vlm_connection.setEnabled(enabled)
        page.btn_save_config.setEnabled(enabled)
        understanding_page = getattr(self, "understanding_page", None)
        if understanding_page is not None:
            if hasattr(understanding_page, "vlm_prompt_tabs"):
                understanding_page.vlm_prompt_tabs.setEnabled(enabled)
            if hasattr(understanding_page, "btn_reset_custom_prompts"):
                understanding_page.btn_reset_custom_prompts.setEnabled(enabled)
            for name in (
                "input_custom_caption_prompt",
                "input_custom_description_prompt",
                "input_custom_motion_prompt",
                "input_custom_summary_prompt",
            ):
                editor = getattr(understanding_page, name, None)
                if editor is not None:
                    editor.setEnabled(enabled)
        form = self._llm_form() if hasattr(self, "_llm_form") else None
        if form is not None:
            form.input_llm_provider_mode.setEnabled(enabled)
            form.input_llm_provider_preset.setEnabled(enabled)
            form.input_remote_llm_base_url.setEnabled(enabled)
            form.input_remote_llm_api_key.setEnabled(enabled)
            form.input_remote_llm_model.setEnabled(enabled)
        asr_form = self._asr_form() if hasattr(self, "_asr_form") else None
        if asr_form is not None:
            asr_form.input_asr_provider_mode.setEnabled(enabled)
            asr_form.input_asr_provider_preset.setEnabled(enabled)
            asr_form.input_remote_asr_base_url.setEnabled(enabled)
            asr_form.input_remote_asr_api_key.setEnabled(enabled)
            asr_form.input_remote_asr_model.setEnabled(enabled)

    def _vlm_prompt_getter_pairs(self):
        from src.services.understanding_resource_service import (
            get_description_prompt_for_language,
            get_motion_prompt_for_language,
            get_tag_prompt_for_language,
            get_video_summary_prompt_for_language,
        )

        page = getattr(self, "understanding_page", None)
        if page is None:
            return ()
        return (
            (getattr(page, "input_custom_caption_prompt", None), get_tag_prompt_for_language),
            (getattr(page, "input_custom_description_prompt", None), get_description_prompt_for_language),
            (getattr(page, "input_custom_motion_prompt", None), get_motion_prompt_for_language),
            (getattr(page, "input_custom_summary_prompt", None), get_video_summary_prompt_for_language),
        )

    def _vlm_prompt_language(self) -> str:
        from src.services.understanding_resource_service import normalize_caption_language

        page = getattr(self, "understanding_page", None)
        if page is None:
            return "zh"
        return normalize_caption_language(page.input_caption_language.currentData())

    def _apply_vlm_prompts_from_page(self, remote_vlm: dict) -> None:
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "input_custom_caption_prompt"):
            return
        tag = str(page.input_custom_caption_prompt.toPlainText() or "").strip()
        description = str(page.input_custom_description_prompt.toPlainText() or "").strip()
        motion = str(page.input_custom_motion_prompt.toPlainText() or "").strip()
        summary = str(page.input_custom_summary_prompt.toPlainText() or "").strip()
        remote_vlm["use_custom_prompts"] = True
        remote_vlm["custom_tag_prompt"] = tag
        remote_vlm["custom_caption_prompt"] = tag
        remote_vlm["custom_description_prompt"] = description
        remote_vlm["custom_motion_prompt"] = motion
        remote_vlm["custom_summary_prompt"] = summary

    def _load_vlm_prompt_editors(self, remote_vlm: dict) -> None:
        language = self._vlm_prompt_language()
        use_custom = bool(remote_vlm.get("use_custom_prompts"))
        saved = (
            str(remote_vlm.get("custom_tag_prompt") or remote_vlm.get("custom_caption_prompt", "") or "").strip(),
            str(remote_vlm.get("custom_description_prompt", "") or "").strip(),
            str(remote_vlm.get("custom_motion_prompt", "") or "").strip(),
            str(remote_vlm.get("custom_summary_prompt", "") or "").strip(),
        )
        for (editor, getter), text in zip(self._vlm_prompt_getter_pairs(), saved):
            if editor is None:
                continue
            if use_custom and text:
                editor.setPlainText(text)
            else:
                editor.setPlainText(getter(language))

    def _refresh_vlm_prompt_editors_for_language(self) -> None:
        language = self._vlm_prompt_language()
        builtin_langs = ("zh", "en")
        for editor, getter in self._vlm_prompt_getter_pairs():
            if editor is None:
                continue
            current = str(editor.toPlainText() or "").strip()
            if not current or any(current == str(getter(item) or "").strip() for item in builtin_langs):
                editor.setPlainText(getter(language))

    def _sync_vlm_prompt_tab_for_mode(self) -> None:
        page = getattr(self, "understanding_page", None)
        tabs = getattr(page, "vlm_prompt_tabs", None) if page is not None else None
        if tabs is None:
            return
        for index in range(tabs.count()):
            tabs.setTabVisible(index, index == 2)
        tabs.setCurrentIndex(2)

    def _on_reset_custom_prompts_clicked(self):
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "vlm_prompt_tabs"):
            return
        index = int(page.vlm_prompt_tabs.currentIndex())
        pairs = self._vlm_prompt_getter_pairs()
        if index < 0 or index >= len(pairs):
            index = 0
        editor, getter = pairs[index]
        if editor is not None:
            editor.setPlainText(getter(self._vlm_prompt_language()))

    def _is_current_page(self, page_name: str) -> bool:
        return self.pages.currentIndex() == self._nav_page_index(page_name)

    def _refresh_understanding_scope_options(self):
        if not hasattr(self, "understanding_page"):
            return
        combo = self.understanding_page.scope_combo
        current = combo.currentData(Qt.ItemDataRole.UserRole)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.texts.get("understanding_scope_all", "All libraries"), "")
        for path in list_libraries().keys():
            path = str(path or "").strip()
            if not path:
                continue
            combo.addItem(path, path)
        restore_index = 0
        if current:
            for index in range(combo.count()):
                if combo.itemData(index, Qt.ItemDataRole.UserRole) == current:
                    restore_index = index
                    break
        combo.setCurrentIndex(restore_index)
        combo.blockSignals(False)
        self._understanding_page_warm = True
        self._refresh_understanding_video_options()

    def _refresh_understanding_video_options(self):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        combo = page.video_combo
        current = combo.currentData(Qt.ItemDataRole.UserRole)
        target_lib = self._selected_understanding_target_lib()
        empty_text = self.texts.get("understanding_video_none", "No indexed videos")
        filter_text = self.texts.get("understanding_video_filter", "Filter videos…")
        if hasattr(combo, "set_placeholders"):
            combo.set_placeholders(empty=empty_text, filter_text=filter_text)

        combo.blockSignals(True)
        try:
            entries = list_ready_video_entries(library_path=target_lib, config=load_config())
            items: list[tuple[str, str]] = []
            # When browsing all libraries, prefix with folder name to disambiguate.
            show_lib_prefix = not bool(target_lib)
            for entry in entries:
                video_id = str(entry.get("video_id", "") or "").strip()
                if not video_id:
                    continue
                rel_path = str(entry.get("video_rel_path", "") or video_id).strip()
                library_path = str(entry.get("library_path", "") or "").strip()
                if show_lib_prefix and library_path:
                    lib_name = os.path.basename(os.path.normpath(library_path)) or library_path
                    label = f"{lib_name} / {rel_path}"
                else:
                    label = rel_path
                items.append((label, video_id))
            if hasattr(combo, "set_items"):
                combo.set_items(items, current_data=current)
            else:
                combo.clear()
                for label, video_id in items:
                    combo.addItem(label, video_id)
                if combo.count() == 0:
                    combo.addItem(empty_text, "")
                restore_index = 0
                if current:
                    found = combo.findData(current, Qt.ItemDataRole.UserRole)
                    if found >= 0:
                        restore_index = found
                combo.setCurrentIndex(restore_index)
        finally:
            combo.blockSignals(False)
        self._load_understanding_video_timeline()

    def _selected_understanding_video_id(self):
        if not hasattr(self, "understanding_page"):
            return ""
        return str(self.understanding_page.video_combo.currentData(Qt.ItemDataRole.UserRole) or "").strip()

    def _on_understanding_scope_changed(self, *_args):
        self._refresh_understanding_video_options()

    def _on_understanding_video_changed(self, *_args):
        self._load_understanding_video_timeline()

    def _on_understanding_chunk_clicked(self, index: int):
        self._show_understanding_chunk_detail(int(index))

    def _understanding_chunk_playback_times(self, index: int) -> tuple[float, float, float] | None:
        index_chunks = getattr(self, "_understanding_index_chunks", []) or []
        chunk_index = int(index)
        if not (0 <= chunk_index < len(index_chunks)):
            return None
        chunk = index_chunks[chunk_index]
        start_sec = float(chunk.get("start", 0.0))
        end_sec = float(chunk.get("end", start_sec))
        if end_sec <= start_sec:
            end_sec = start_sec + 0.1

        payload = dict(getattr(self, "_understanding_chunk_payloads", {}).get(chunk_index) or {})
        sample = dict(payload.get("sample") or {})
        stamps = list(sample.get("timestamps_sec") or [])
        if stamps:
            suggested_sec = float(stamps[0])
        elif sample.get("timestamp_sec") is not None:
            suggested_sec = float(sample.get("timestamp_sec"))
        else:
            suggested_sec = (start_sec + end_sec) / 2.0
        return start_sec, end_sec, suggested_sec

    def _on_understanding_chunk_double_clicked(self, index: int):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        playback_times = self._understanding_chunk_playback_times(index)
        if playback_times is None:
            return
        start_sec, end_sec, suggested_sec = playback_times

        video_path = self._current_understanding_preview_path()
        if not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return

        self._show_understanding_chunk_detail(int(index))
        # Stay on Understanding — floating dialog instead of jumping to Search preview.
        opened = self.open_floating_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
            on_status=page.lbl_status.setText,
        )
        if opened:
            page.lbl_status.setText(
                self.texts.get(
                    "understanding_chunk_play_started",
                    "Playing segment {index}: {range}",
                ).format(
                    index=int(index) + 1,
                    range=format_timecode_range(start_sec, end_sec),
                )
            )

    def _set_understanding_readonly_text(self, widget, text: str):
        widget.setPlainText(str(text or ""))

    def _extract_video_summary_text(self, evidence: dict | None) -> str:
        if not isinstance(evidence, dict):
            return ""
        summary = dict(evidence.get("summary") or {})
        return str(summary.get("text", "") or "").strip()

    def _refresh_understanding_video_meta(self, evidence: dict | None = None):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        if evidence is None:
            video_id = self._selected_understanding_video_id()
            evidence = (
                load_evidence_bundle(
                    video_id,
                    config=load_config(),
                    mode=self._current_understanding_mode(),
                )
                if video_id
                else None
            )
        if not isinstance(evidence, dict):
            page.video_summary_meta_label.setText("")
            return
        chunks = list(evidence.get("chunks") or [])
        generated_at = str((evidence.get("provenance") or {}).get("generated_at") or "").strip()
        parts = []
        if chunks:
            parts.append(
                self.texts.get("understanding_video_meta_chunks", "{count} segments").format(count=len(chunks))
            )
        if generated_at:
            parts.append(
                self.texts.get("understanding_video_meta_generated_at", "Generated: {time}").format(time=generated_at)
            )
        page.video_summary_meta_label.setText(" · ".join(parts))

    def _refresh_understanding_video_summary(self, evidence: dict | None = None):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        if evidence is None:
            video_id = self._selected_understanding_video_id()
            evidence = (
                load_evidence_bundle(
                    video_id,
                    config=load_config(),
                    mode=self._current_understanding_mode(),
                )
                if video_id
                else None
            )
        summary_text = self._extract_video_summary_text(evidence)
        if summary_text:
            self._set_understanding_readonly_text(page.video_summary_text, summary_text)
            self._refresh_understanding_video_meta(evidence)
            return
        running = getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()
        mode = str(getattr(self.understanding_controller, "current_mode", "") or "") if running else ""
        if running and mode == "summary":
            self._set_understanding_readonly_text(
                page.video_summary_text,
                self.texts.get(
                    "understanding_video_summary_generating",
                    "Generating video summary…",
                ),
            )
            self._refresh_understanding_video_meta(evidence)
            return
        self._set_understanding_readonly_text(
            page.video_summary_text,
            self.texts.get(
                "understanding_video_summary_empty",
                "Click “Generate summary” after tags are ready.",
            ),
        )
        self._refresh_understanding_video_meta(evidence)

    def _chunk_payload_has_evidence(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        tags = [str(item).strip() for item in list(payload.get("tags") or []) if str(item or "").strip()]
        if tags:
            return True
        evidence = dict(payload.get("evidence") or {})
        vision = dict(evidence.get("vision") or {})
        caption = str(dict(vision.get("image_caption") or {}).get("text", "") or "").strip()
        return bool(caption)

    def _load_understanding_video_timeline(self):
        if not hasattr(self, "understanding_page"):
            return
        with self._freeze_understanding_page_scroll():
            self._load_understanding_video_timeline_impl()

    def _load_understanding_video_timeline_impl(self):
        page = self.understanding_page
        video_id = self._selected_understanding_video_id()
        self._understanding_chunk_payloads = {}
        if not video_id:
            page.chunk_timeline.set_segments([])
            page.chunk_time_label.setText("")
            self._set_understanding_readonly_text(
                page.chunk_caption_text,
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
            )
            self._understanding_video_context = {}
            self._refresh_understanding_video_summary(None)
            self._refresh_understanding_video_meta(None)
            self._refresh_understanding_dialogue_step()
            self._sync_recap_export_button()
            return

        config = load_config()
        try:
            self._understanding_video_context = resolve_video_context(
                video_id,
                config=config,
                probe_duration=False,
            )
        except Exception:
            self._understanding_video_context = {}
        index_chunks = load_video_chunks_by_id(video_id, config)
        self._understanding_index_chunks = list(index_chunks)
        evidence = load_evidence_bundle(
            video_id,
            config=config,
            mode=self._current_understanding_mode(),
        ) or {}
        evidence_chunks = {
            int(item.get("chunk_index", -1)): dict(item)
            for item in (evidence.get("chunks") or [])
            if isinstance(item, dict)
        }
        segments: list[ChunkTimelineSegment] = []
        for index, chunk in enumerate(index_chunks):
            payload = evidence_chunks.get(index)
            if payload is not None:
                self._understanding_chunk_payloads[index] = payload
            state = "ready" if payload is not None and self._chunk_payload_has_evidence(payload) else "pending"
            segments.append(
                ChunkTimelineSegment(
                    start_sec=float(chunk.get("start", 0.0)),
                    end_sec=float(chunk.get("end", chunk.get("start", 0.0))),
                    state=state,
                )
            )
        duration_sec = float(self._understanding_video_context.get("duration_sec") or 0.0)
        if duration_sec <= 0:
            duration_sec = max((float(segment.end_sec) for segment in segments), default=0.0)
        page.chunk_timeline.set_segments(segments, duration_sec=duration_sec)
        self._refresh_understanding_video_summary(evidence)
        if segments:
            page.chunk_timeline.set_selected_index(0)
            self._show_understanding_chunk_detail_impl(0)
        else:
            page.chunk_time_label.setText("")
            self._set_understanding_readonly_text(
                page.chunk_caption_text,
                self.texts.get("understanding_video_no_chunks", "No semantic chunks for this video."),
            )
            self._refresh_understanding_video_summary(evidence)

        self._refresh_understanding_dialogue_step()
        self._sync_recap_export_button()

    def _pixmap_from_bgr_frame(self, frame, *, height: int = 96):
        if frame is None or getattr(frame, "size", 0) == 0:
            return QPixmap()
        try:
            import cv2
            import numpy as np
        except Exception:
            return QPixmap()
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb = np.ascontiguousarray(rgb)
        h, w, channels = rgb.shape
        image = QImage(rgb.data, w, h, channels * w, QImage.Format.Format_RGB888).copy()
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull() or height <= 0:
            return pixmap
        return pixmap.scaledToHeight(int(height), Qt.TransformationMode.SmoothTransformation)

    def _clear_understanding_sample_frames(self):
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "chunk_frame_start"):
            return
        page.chunk_frame_start.clear()
        page.chunk_frame_end.clear()
        page.chunk_frame_start.setText("")
        page.chunk_frame_end.setText("")

    def _update_understanding_sample_frames(self, payload: dict | None):
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "chunk_sample_frames"):
            return
        page.chunk_sample_frames.setVisible(True)
        sample = dict((payload or {}).get("sample") or {})
        stamps = [float(item) for item in list(sample.get("timestamps_sec") or []) if item is not None]
        if not stamps and sample.get("timestamp_sec") is not None:
            stamps = [float(sample.get("timestamp_sec"))]
        context = dict(getattr(self, "_understanding_video_context", {}) or {})
        video_path = str(context.get("video_path", "") or "").strip()
        if not video_path or not stamps:
            self._clear_understanding_sample_frames()
            return
        from src.media.thumbnail import get_single_thumbnail

        start_pix = self._pixmap_from_bgr_frame(get_single_thumbnail(video_path, stamps[0]))
        end_stamp = stamps[1] if len(stamps) > 1 else stamps[0]
        end_pix = self._pixmap_from_bgr_frame(get_single_thumbnail(video_path, end_stamp))
        page.chunk_frame_start.setPixmap(start_pix)
        page.chunk_frame_end.setPixmap(end_pix)

    def _overlapping_dialogue_text(self, start_sec: float, end_sec: float) -> str:
        video_id = self._selected_understanding_video_id()
        if not video_id:
            return ""
        try:
            from src.storage.dialogue_transcript_store import iter_shared_transcript_segment_rows

            lines: list[str] = []
            for row in iter_shared_transcript_segment_rows(video_id=video_id):
                cue_start = float(row.get("start", 0.0) or 0.0)
                cue_end = float(row.get("end", cue_start) or cue_start)
                if cue_end < start_sec or cue_start > end_sec:
                    continue
                text = str(row.get("text") or "").strip()
                if not text:
                    continue
                speaker = str(row.get("speaker") or "").strip()
                lines.append(f"{speaker}：{text}" if speaker else text)
                if len(lines) >= 12:
                    break
            return "\n".join(lines)
        except Exception:
            return ""

    def _show_understanding_chunk_detail(self, index: int, payload=None):
        if not hasattr(self, "understanding_page"):
            return
        with self._freeze_understanding_page_scroll():
            self._show_understanding_chunk_detail_impl(index, payload)

    def _show_understanding_chunk_detail_impl(self, index: int, payload=None):
        page = self.understanding_page
        page.chunk_timeline.set_selected_index(int(index))
        if payload is None:
            payload = dict(self._understanding_chunk_payloads.get(int(index)) or {})
        if not payload and int(index) >= 0:
            index_chunks = getattr(self, "_understanding_index_chunks", []) or []
            if int(index) < len(index_chunks):
                chunk = index_chunks[int(index)]
                start_sec = float(chunk.get("start", 0.0))
                end_sec = float(chunk.get("end", 0.0))
                page.chunk_time_label.setText(
                    self.texts.get("understanding_chunk_time", "Segment {index}: {range}").format(
                        index=int(index) + 1,
                        range=format_timecode_range(start_sec, end_sec),
                    )
                )
                pending = self.texts.get("understanding_chunk_pending", "Not generated yet.")
                dialogue = self._overlapping_dialogue_text(start_sec, end_sec)
                if dialogue:
                    pending = (
                        pending
                        + "\n\n"
                        + self.texts.get("understanding_chunk_dialogue_heading", "Dialogue")
                        + "\n"
                        + dialogue
                    )
                self._set_understanding_readonly_text(page.chunk_caption_text, pending)
                self._clear_understanding_sample_frames()
                if hasattr(page, "chunk_sample_frames"):
                    page.chunk_sample_frames.setVisible(True)
                return
        if not payload:
            return
        start_sec = float(payload.get("start_sec", 0.0))
        end_sec = float(payload.get("end_sec", start_sec))
        page.chunk_time_label.setText(
            self.texts.get("understanding_chunk_time", "Segment {index}: {range}").format(
                index=int(payload.get("chunk_index", index)) + 1,
                range=format_timecode_range(start_sec, end_sec),
            )
        )
        vision = dict(dict(payload.get("evidence") or {}).get("vision") or {})
        caption = str(dict(vision.get("image_caption") or {}).get("text", "") or "").strip()
        tags = [str(item).strip() for item in list(payload.get("tags") or []) if str(item or "").strip()]
        if not tags:
            nested = dict(vision.get("image_caption") or {}).get("tags") or []
            tags = [str(item).strip() for item in list(nested) if str(item or "").strip()]
        display = caption
        if tags:
            from src.services.understanding_tags import format_tags_for_display

            display = (display + "\n\n" if display else "") + format_tags_for_display(tags)
        dialogue = self._overlapping_dialogue_text(start_sec, end_sec)
        if dialogue:
            display = (
                (display or self.texts.get("understanding_chunk_no_caption", "No caption."))
                + "\n\n"
                + self.texts.get("understanding_chunk_dialogue_heading", "Dialogue")
                + "\n"
                + dialogue
            )
        self._set_understanding_readonly_text(
            page.chunk_caption_text,
            display or self.texts.get("understanding_chunk_no_caption", "No caption."),
        )
        self._update_understanding_sample_frames(payload)

    def _handle_recap_motion_chunk(self, index, total, payload) -> None:
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "chunk_timeline"):
            return
        chunk_index = int(index)
        self._understanding_chunk_payloads[chunk_index] = dict(payload or {})
        page.chunk_timeline.set_segment_state(chunk_index, "ready")
        page.chunk_timeline.set_generating_index(-1)
        page.chunk_timeline.set_selected_index(chunk_index)
        self._show_understanding_chunk_detail(chunk_index, payload)
        if not getattr(self, "_recap_motion_timeline_shown", False):
            self._ensure_understanding_timeline_on_screen()
            self._recap_motion_timeline_shown = True
        _ = total

    def _handle_understanding_chunk_completed(self, index, total, payload):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        chunk_index = int(index)
        self._understanding_chunk_payloads[chunk_index] = dict(payload or {})
        page.chunk_timeline.set_segment_state(chunk_index, "ready")
        next_index = chunk_index + 1
        page.chunk_timeline.set_generating_index(next_index if next_index < int(total) else -1)
        self._show_understanding_chunk_detail(chunk_index, payload)

    def _prepare_understanding_timeline_for_generation(self):
        page = self.understanding_page
        self._load_understanding_video_timeline()
        total = page.chunk_timeline.segment_count()
        first_pending = None
        for index in range(total):
            payload = dict(self._understanding_chunk_payloads.get(index) or {})
            if self._chunk_payload_has_evidence(payload):
                page.chunk_timeline.set_segment_state(index, "ready")
            else:
                page.chunk_timeline.set_segment_state(index, "pending")
                if first_pending is None:
                    first_pending = index
        page.chunk_timeline.set_generating_index(
            first_pending if first_pending is not None else (0 if total else -1)
        )
        self._refresh_understanding_video_summary()

    def _selected_understanding_target_lib(self):
        if not hasattr(self, "understanding_page"):
            return None
        value = self.understanding_page.scope_combo.currentData(Qt.ItemDataRole.UserRole)
        path = str(value or "").strip()
        return path or None

    def _invalidate_understanding_status_cache(self) -> None:
        self._understanding_status_cache = None

    def _fetch_understanding_resource_status(
        self,
        *,
        probe_remote: bool = False,
        install_bootstrap: bool = False,
        use_cache: bool = True,
    ) -> dict:
        cache_key = (bool(probe_remote), bool(install_bootstrap))
        cache = getattr(self, "_understanding_status_cache", None)
        now = time.monotonic()
        if (
            use_cache
            and isinstance(cache, dict)
            and cache.get("key") == cache_key
            and now - float(cache.get("at", 0.0) or 0.0) < 3.0
        ):
            return dict(cache.get("status") or {})

        try:
            status = get_understanding_resource_status(
                config=load_config(),
                probe_remote=probe_remote,
                remote_probe_timeout_sec=2.0,
                install_bootstrap=install_bootstrap,
            )
        except Exception:
            status = {"understanding_ready": False, "missing_components": []}
        self._understanding_status_cache = {"key": cache_key, "at": now, "status": dict(status)}
        return status

    def _deferred_understanding_page_refresh(self) -> None:
        self._understanding_page_refresh_pending = False
        if not self._is_current_page("understanding"):
            return
        # Subsequent visits: keep last video list / timeline / dialogue as-is.
        # Library/indexing/ASR handlers invalidate via _refresh_understanding_scope_options
        # or explicit dialogue/timeline reloads.
        if getattr(self, "_understanding_page_warm", False):
            return
        page = getattr(self, "understanding_page", None)
        if page is not None and hasattr(page, "lbl_status"):
            page.lbl_status.setText(
                self.texts.get("understanding_loading_videos", "Loading indexed videos…")
            )
        if not getattr(self, "_understanding_settings_applied", False):
            if hasattr(self, "load_understanding_settings"):
                self.load_understanding_settings(refresh_status=False)
            self._understanding_settings_applied = True
        if hasattr(self, "_refresh_understanding_scope_options"):
            self._refresh_understanding_scope_options()
        else:
            self._understanding_page_warm = True
        self._refresh_understanding_page_fast(install_bootstrap=False)
        if page is not None and hasattr(page, "lbl_status"):
            current = str(page.lbl_status.text() or "")
            if current == self.texts.get("understanding_loading_videos", "Loading indexed videos…"):
                page.lbl_status.setText("")

    def _refresh_understanding_page_fast(self, *, install_bootstrap: bool = False):
        status = self._fetch_understanding_resource_status(
            probe_remote=False,
            install_bootstrap=install_bootstrap,
        )
        self._refresh_understanding_ui(status=status)
        self._refresh_understanding_settings_status(status=status)

    def _refresh_understanding_ui(self, status=None, *, probe_remote: bool = False):
        if not hasattr(self, "understanding_page"):
            return
        if status is None:
            status = self._fetch_understanding_resource_status(
                probe_remote=probe_remote,
                install_bootstrap=probe_remote,
                use_cache=not probe_remote,
            )

        ready = bool(status.get("understanding_ready"))
        missing = ", ".join(status.get("missing_components") or [])
        understanding_running = getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()
        indexing_running = self.indexing_controller.is_running()
        page = self.understanding_page

        show_notice = self._is_current_page("understanding") and not ready and not understanding_running
        # Keep the banner widget in the layout with a stable min height so
        # show/hide does not shove the timeline on first open.
        page.understanding_notice.setMinimumHeight(40 if show_notice else 0)
        page.understanding_notice.setMaximumHeight(16777215 if show_notice else 0)
        page.understanding_notice.setVisible(show_notice)
        if show_notice:
            page.understanding_notice_text.setText(
                self.texts.get(
                    "understanding_not_ready_banner",
                    "Understanding models are not ready: {missing}. Import components and choose a profile in Settings.",
                ).format(missing=missing or self.texts.get("understanding_not_ready", "Not ready"))
            )

        has_video = bool(self._selected_understanding_video_id())
        page.btn_generate_evidence.setEnabled(
            ready and not understanding_running and not indexing_running and has_video
        )
        page.btn_generate_batch.setEnabled(ready and not understanding_running and not indexing_running)
        if hasattr(page, "btn_generate_summary"):
            page.btn_generate_summary.setEnabled(False)
            page.btn_generate_summary.hide()
        page.btn_evidence_details.setEnabled(not understanding_running)
        page.btn_export_video_json.setEnabled(
            not understanding_running and self._current_video_has_exportable_evidence()
        )
        self._sync_recap_export_button(running=understanding_running)
        page.scope_combo.setEnabled(not understanding_running)
        page.video_combo.setEnabled(not understanding_running)
        self._set_understanding_config_enabled(not understanding_running)
        if ready:
            page.lbl_understanding_hint.setText(
                self.texts.get(
                    "understanding_library_ready_hint",
                    "Local models are ready. Configure the description service and use Test connection before generating.",
                )
            )
        else:
            page.lbl_understanding_hint.setText(
                self.texts.get(
                    "understanding_library_not_ready_hint",
                    "Configure the description service below, then use Test connection.",
                )
            )
        if not ready:
            tip = self.texts.get("understanding_not_ready", "Not ready")
            page.btn_generate_evidence.setToolTip(tip)
        else:
            page.btn_generate_evidence.setToolTip("")
        # Labels / workflow chrome are owned by load_understanding_settings /
        # language refresh — do not re-run _sync_understanding_mode_ui here.

    def open_understanding_settings(self):
        self.switch_page("understanding")
        dialog = getattr(self, "understanding_services_dialog", None)
        if dialog is None:
            return
        if dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog.exec()

    def _remote_vlm_status_line(self, status=None) -> str:
        cached_probe = getattr(self, "_cached_vlm_connection_probe", None)
        if isinstance(cached_probe, dict) and cached_probe:
            if cached_probe.get("reachable") and cached_probe.get("model_available"):
                return self.texts.get(
                    "understanding_settings_remote_vlm_ready",
                    "Description service connected: {model}",
                ).format(
                    model=str(
                        cached_probe.get("configured_model", "") or cached_probe.get("model", "") or ""
                    )
                )
            return self._format_vlm_probe_status(cached_probe)

        remote_vlm = dict((status or {}).get("remote_vlm") or {})
        if remote_vlm.get("skipped"):
            return self.texts.get(
                "understanding_settings_remote_vlm_test_hint",
                "Description service: click Test connection to verify.",
            )
        if remote_vlm.get("reachable") and remote_vlm.get("model_available"):
            return self.texts.get(
                "understanding_settings_remote_vlm_ready",
                "Description service connected: {model}",
            ).format(model=str(remote_vlm.get("configured_model", "") or remote_vlm.get("model", "") or ""))
        if remote_vlm.get("reachable") and str(remote_vlm.get("error_code", "") or "") == "model_not_found":
            return self._format_vlm_probe_status(remote_vlm)
        if remote_vlm and not remote_vlm.get("skipped"):
            return self.texts.get(
                "understanding_settings_remote_vlm_not_ready",
                "Description service not ready: {error}",
            ).format(error=str(remote_vlm.get("error", "") or "unreachable"))
        return ""

    def _refresh_understanding_settings_status(self, status=None, *, probe_remote: bool = False):
        page = self._understanding_config_widgets()
        if page is None:
            return
        hint = getattr(page, "hint_understanding_status", None)
        if hint is None:
            return
        if status is None:
            status = self._fetch_understanding_resource_status(
                probe_remote=probe_remote,
                install_bootstrap=probe_remote,
                use_cache=not probe_remote,
            )
        remote_line = self._remote_vlm_status_line(status)

        if status.get("understanding_ready"):
            ready = self.texts.get(
                "understanding_settings_ready",
                "Description service is ready.",
            )
            lines = [line for line in (ready, remote_line) if line]
            hint.setText("\n".join(lines))
            return
        missing = ", ".join(status.get("missing_components") or [])
        profile_error = str(status.get("profile_error", "") or "").strip()
        detail = profile_error or missing or self.texts.get("understanding_not_ready", "Not ready")
        base = self.texts.get("understanding_settings_not_ready", "Missing: {missing}").format(missing=detail)
        lines = [line for line in (base, remote_line) if line]
        hint.setText("\n".join(lines))

    def start_generate_understanding_evidence(self, target_lib=None, video_id=None):
        if not self._ensure_startup_migration_idle("feature_understanding"):
            return
        if self.indexing_controller.is_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        try:
            status = get_understanding_resource_status(config=load_config())
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_generation_failed", "Failed to generate evidence."), exc)
            return
        if not status.get("understanding_ready"):
            self._refresh_understanding_ui()
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_not_ready", "Understanding models are not ready."),
                kind="warning",
            )
            return

        video_id = str(video_id or self._selected_understanding_video_id() or "").strip()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        if self.understanding_page.chunk_timeline.segment_count() <= 0:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_no_chunks", "No semantic chunks for this video."),
                kind="warning",
            )
            return

        self._persist_understanding_job_options()
        page = self.understanding_page
        self.switch_page("understanding")
        page.btn_generate_evidence.setEnabled(False)
        if hasattr(page, "btn_generate_batch"):
            page.btn_generate_batch.setEnabled(False)
        if hasattr(page, "btn_generate_summary"):
            page.btn_generate_summary.setEnabled(False)
        page.btn_evidence_details.setEnabled(False)
        page.btn_export_video_json.setEnabled(False)
        self._sync_recap_export_button(running=True)
        if hasattr(page, "btn_extract_asr"):
            page.btn_extract_asr.setEnabled(False)
        if hasattr(page, "btn_cluster_speakers"):
            page.btn_cluster_speakers.setEnabled(False)
        if hasattr(page, "btn_rename_speakers"):
            page.btn_rename_speakers.setEnabled(False)
        if hasattr(page, "btn_export_dialogue_json"):
            page.btn_export_dialogue_json.setEnabled(False)
        page.scope_combo.setEnabled(False)
        page.video_combo.setEnabled(False)
        self._set_understanding_config_enabled(False)
        page.btn_stop.setEnabled(True)
        page.btn_stop.setVisible(True)
        page.progress_bar.setVisible(True)
        page.lbl_status.setText(self.texts.get("understanding_generation_started", "Generating…"))
        page.understanding_notice.hide()
        self._prepare_understanding_timeline_for_generation()
        resumed = sum(
            1
            for index in range(page.chunk_timeline.segment_count())
            if self._chunk_payload_has_evidence(self._understanding_chunk_payloads.get(index))
        )
        if resumed > 0:
            page.lbl_status.setText(
                self.texts.get(
                    "understanding_generation_resuming",
                    "Resuming: {saved} segments already saved.",
                ).format(saved=resumed)
            )

        if self.understanding_controller.start_video(video_id, mode=self._current_understanding_mode()):
            if hasattr(self, "_sync_tray_stop_action"):
                self._sync_tray_stop_action()

    def start_generate_understanding_batch(self):
        if not self._ensure_startup_migration_idle("feature_understanding"):
            return
        if self.indexing_controller.is_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        try:
            status = get_understanding_resource_status(config=load_config())
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_generation_failed", "Failed to generate evidence."), exc)
            return
        if not status.get("understanding_ready"):
            self._refresh_understanding_ui()
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_not_ready", "Understanding models are not ready."),
                kind="warning",
            )
            return

        mode = self._current_understanding_mode()
        target_lib = self._selected_understanding_target_lib() or None
        from src.services.understanding_service import evidence_exists_for_video, list_ready_video_entries

        entries = list_ready_video_entries(library_path=target_lib or "", config=load_config())
        pending = [
            entry
            for entry in entries
            if str(entry.get("video_id", "") or "").strip()
            and not evidence_exists_for_video(
                str(entry.get("video_id", "") or "").strip(),
                config=load_config(),
                mode=mode,
            )
        ]
        if not pending:
            self.show_info_dialog(
                self.texts.get("info_title", self.texts.get("success_title", "Info")),
                self.texts.get(
                    "understanding_batch_empty",
                    "No pending videos in this scope for the current mode.",
                ),
                kind="info",
            )
            return

        if not self.show_confirm_dialog(
            self.texts.get("confirm_title", "Confirm"),
            self.texts.get(
                "understanding_batch_confirm",
                "Queue {count} videos in the current scope for {mode}? Already finished ones are skipped. Processes one video at a time.",
            ).format(
                count=len(pending),
                mode=self.texts.get("understanding_mode_motion", mode),
            ),
            kind="question",
        ):
            return

        self._persist_understanding_job_options()
        page = self.understanding_page
        self.switch_page("understanding")
        page.btn_generate_evidence.setEnabled(False)
        page.btn_generate_batch.setEnabled(False)
        if hasattr(page, "btn_generate_summary"):
            page.btn_generate_summary.setEnabled(False)
        page.btn_evidence_details.setEnabled(False)
        page.btn_export_video_json.setEnabled(False)
        self._sync_recap_export_button(running=True)
        if hasattr(page, "btn_extract_asr"):
            page.btn_extract_asr.setEnabled(False)
        if hasattr(page, "btn_cluster_speakers"):
            page.btn_cluster_speakers.setEnabled(False)
        if hasattr(page, "btn_rename_speakers"):
            page.btn_rename_speakers.setEnabled(False)
        if hasattr(page, "btn_export_dialogue_json"):
            page.btn_export_dialogue_json.setEnabled(False)
        page.scope_combo.setEnabled(False)
        page.video_combo.setEnabled(False)
        self._set_understanding_config_enabled(False)
        page.btn_stop.setEnabled(True)
        page.btn_stop.setVisible(True)
        page.progress_bar.setVisible(True)
        page.progress_bar.setValue(0)
        page.lbl_status.setText(
            self.texts.get(
                "understanding_batch_started",
                "Batch queued: {count} videos…",
            ).format(count=len(pending))
        )
        page.understanding_notice.hide()

        if self.understanding_controller.start(target_lib=target_lib, mode=mode, skip_existing=True):
            if hasattr(self, "_sync_tray_stop_action"):
                self._sync_tray_stop_action()

    def _on_understanding_batch_video_started(self, video_id, current, total):
        video_id = str(video_id or "").strip()
        if not video_id or not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        combo = page.video_combo
        # SearchableIdCombo has findData/currentData, not QComboBox.itemData.
        index = combo.findData(video_id, Qt.ItemDataRole.UserRole) if hasattr(combo, "findData") else -1
        if index >= 0 and combo.currentIndex() != index:
            combo.blockSignals(True)
            try:
                combo.setCurrentIndex(index)
            finally:
                combo.blockSignals(False)
        # Always refresh pending/ready markers — first queue item may already be selected.
        self._prepare_understanding_timeline_for_generation()
        page.lbl_status.setText(
            self.texts.get(
                "understanding_batch_progress",
                "Queue {current}/{total}: {video_id}",
            ).format(current=int(current), total=int(total), video_id=video_id)
        )
        page.progress_bar.setVisible(True)
        if page.progress_bar.maximum() <= 0:
            page.progress_bar.setMaximum(100)


    def start_generate_understanding_summary(self, video_id=None):
        self.start_generate_understanding_evidence(video_id=video_id)

    def stop_understanding_generation(self):
        recap_worker = getattr(self, "_recap_worker", None)
        if recap_worker is not None:
            recap_worker.stop()
            page = self.understanding_page
            page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            page.btn_stop.setEnabled(False)
            if hasattr(page, "recap_progress_status"):
                page.recap_progress_status.set_status_text(
                    self.texts.get("understanding_stop_requested", "Stopping…")
                )
            return
        worker = getattr(self, "_asr_worker", None)
        if worker is not None:
            worker.stop()
            page = self.understanding_page
            page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            page.btn_stop.setEnabled(False)
            if hasattr(page, "btn_stop_asr"):
                page.btn_stop_asr.setEnabled(False)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        cluster_worker = getattr(self, "_speaker_cluster_worker", None)
        if cluster_worker is not None:
            cluster_worker.stop()
            page = self.understanding_page
            page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            page.btn_stop.setEnabled(False)
            if hasattr(page, "btn_stop_asr"):
                page.btn_stop_asr.setEnabled(False)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        if not getattr(self, "understanding_controller", None) or not self.understanding_controller.is_running():
            return
        if self.understanding_controller.request_stop():
            self.understanding_page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            self.understanding_page.btn_stop.setEnabled(False)

    def _update_understanding_progress(self, value, text):
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()
        page = self.understanding_page
        label = format_progress_text(text, self.texts)
        page.progress_bar.setVisible(True)
        page.progress_bar.setValue(value)
        page.lbl_status.setText(label)
        if getattr(self, "_asr_worker", None) is not None or getattr(
            self, "_speaker_cluster_worker", None
        ) is not None:
            if hasattr(page, "dialogue_progress_bar"):
                page.dialogue_progress_bar.setVisible(True)
                page.dialogue_progress_bar.setValue(value)
            if hasattr(page, "dialogue_progress_status"):
                page.dialogue_progress_status.set_status_text(label)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(label)

    def _finish_understanding_generation(self, success, target, stopped=False, result=None):
        result = dict(result or {})
        page = self.understanding_page
        page.btn_generate_evidence.setEnabled(True)
        if hasattr(page, "btn_generate_batch"):
            page.btn_generate_batch.setEnabled(True)
        if hasattr(page, "btn_generate_summary"):
            page.btn_generate_summary.setEnabled(False)
            page.btn_generate_summary.hide()
        page.btn_evidence_details.setEnabled(True)
        page.btn_export_video_json.setEnabled(self._current_video_has_exportable_evidence())
        self._refresh_understanding_dialogue_step()
        self._sync_recap_export_button(running=False)
        page.scope_combo.setEnabled(True)
        page.video_combo.setEnabled(True)
        self._set_understanding_config_enabled(True)
        page.btn_stop.setEnabled(False)
        page.btn_stop.setVisible(False)
        page.progress_bar.setVisible(False)
        page.chunk_timeline.set_generating_index(-1)

        mode = str(result.get("mode", "") or "")
        is_batch = bool(result.get("batch")) or (
            "generated_count" in result and "chunk_count" not in result and not result.get("video_id")
        )
        if is_batch:
            generated_count = int(result.get("generated_count", 0) or 0)
            error_count = int(result.get("error_count", len(result.get("errors") or [])) or 0)
            requested_count = int(result.get("requested_count", 0) or 0)
            if stopped:
                status_text = self.texts.get(
                    "understanding_batch_stopped",
                    "Batch stopped. Done {done}/{total}.",
                ).format(done=generated_count, total=requested_count)
            elif requested_count == 0:
                status_text = self.texts.get(
                    "understanding_batch_empty",
                    "No pending videos in this scope for the current mode.",
                )
            elif error_count:
                status_text = self.texts.get(
                    "understanding_batch_done_with_errors",
                    "Batch done: {done}/{total}, {errors} failed.",
                ).format(done=generated_count, total=requested_count, errors=error_count)
            else:
                status_text = self.texts.get(
                    "understanding_batch_done",
                    "Batch finished: {done}/{total}.",
                ).format(done=generated_count, total=requested_count)
            page.lbl_status.setText(status_text)
            self._load_understanding_video_timeline()
        elif result.get("video_id") and mode == "summary":
            if stopped:
                page.lbl_status.setText(self.texts.get("understanding_generation_stopped", "Stopped."))
            elif success:
                page.lbl_status.setText(
                    self.texts.get("understanding_summary_generation_done", "Video summary done.")
                )
            else:
                page.lbl_status.setText(self.texts.get("understanding_generation_failed", "Failed."))
            self._load_understanding_video_timeline()
        elif result.get("video_id"):
            chunk_count = int(result.get("chunk_count", 0) or 0)
            chunk_total = int(result.get("chunk_total", chunk_count) or chunk_count)
            if stopped:
                status_text = self.texts.get(
                    "understanding_generation_stopped_partial",
                    "Stopped. Saved {saved}/{total} segments.",
                ).format(saved=chunk_count, total=chunk_total)
            elif success:
                if mode == "summary":
                    status_text = self.texts.get(
                        "understanding_summary_generation_done",
                        "Video summary done.",
                    )
                else:
                    status_text = self.texts.get(
                        "understanding_video_generation_done",
                        "Finished: {count} segments.",
                    ).format(count=chunk_count)
            else:
                status_text = self.texts.get("understanding_generation_failed", "Failed.")
            page.lbl_status.setText(status_text)
            self._load_understanding_video_timeline()
        else:
            page.lbl_status.setText(self.texts.get("understanding_generation_failed", "Failed."))

        self._refresh_understanding_ui()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()
        if getattr(self, "_close_when_indexing_stops", False):
            self._close_when_indexing_stops = False
            self.close()

    def _handle_understanding_error(self, error_text):
        detail = str(error_text or "").strip()
        if not detail:
            return
        self.show_error_dialog(self.texts.get("understanding_generation_failed", "Failed."), detail)

    def _current_video_has_motion_evidence(self) -> bool:
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION

        video_id = self._selected_understanding_video_id()
        if not video_id:
            return False
        return (
            load_evidence_bundle(
                video_id,
                config=load_config(),
                mode=UNDERSTANDING_MODE_MOTION,
            )
            is not None
        )

    def _current_video_recap_dialogue_status(self) -> dict:
        from src.services.recap_service import recap_dialogue_status

        video_id = self._selected_understanding_video_id()
        if not video_id:
            return {"ready": False, "count": 0, "source": ""}
        return recap_dialogue_status(video_id, config=load_config())

    def _current_video_has_recap_dialogue(self) -> bool:
        page = getattr(self, "understanding_page", None)
        table = getattr(page, "dialogue_table", None) if page is not None else None
        if table is not None:
            return table.rowCount() > 0
        return bool(self._current_video_recap_dialogue_status().get("ready"))

    def _current_video_can_export_recap(self) -> bool:
        return self._current_video_has_recap_dialogue()

    def _current_video_has_recap_beats(self) -> bool:
        from src.services.recap_service import load_recap_beats

        video_id = self._selected_understanding_video_id()
        video_path = self._current_recap_video_path()
        if not video_id or not video_path:
            return False
        return load_recap_beats(video_path, video_id=video_id) is not None

    def _current_video_has_recap_cuts(self) -> bool:
        from src.services.recap_service import load_recap_cuts

        video_id = self._selected_understanding_video_id()
        video_path = self._current_recap_video_path()
        if not video_id or not video_path:
            return False
        return load_recap_cuts(video_path, video_id=video_id) is not None

    def _dialogue_source_label(self, source: str) -> str:
        text = str(source or "").strip().lower()
        if "ocr" in text or text in {"subtitle", "subtitles"}:
            return self.texts.get("understanding_dialogue_source_ocr", "Hard-sub OCR")
        return self.texts.get("understanding_dialogue_source_asr", "Speech ASR")

    def _refresh_understanding_dialogue_step(self) -> None:
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "dialogue_card"):
            return
        with self._freeze_understanding_page_scroll():
            page.dialogue_card.setVisible(True)
            video_id = self._selected_understanding_video_id()
            cues = []
            if video_id:
                from src.services.recap_service import list_speech_dialogue_cues

                cues = list_speech_dialogue_cues(video_id, config=load_config())
            self._populate_understanding_dialogue_table(cues)
            source = self._dialogue_source_label(str((cues[0] or {}).get("asr_source") or "") if cues else "")
            if cues:
                from src.services.recap_service import recap_speaker_stats

                unnamed = int(recap_speaker_stats(cues).get("unnamed") or 0)
                if unnamed > 0:
                    page.dialogue_status.setText(
                        self.texts.get(
                            "understanding_step_dialogue_unnamed",
                            "{count} cues ({source}); {unnamed} still unnamed.",
                        ).format(count=len(cues), source=source, unnamed=unnamed)
                    )
                else:
                    page.dialogue_status.setText(
                        self.texts.get(
                            "understanding_step_dialogue_ready",
                            "Showing {count} cues from this video ({source}). Double-click to play that speech span; Edit to rename.",
                        ).format(count=len(cues), source=source)
                    )
            else:
                page.dialogue_status.setText(
                    self.texts.get(
                        "understanding_step_dialogue_empty",
                        "No speech dialogue for this video yet. Extract speech here.",
                    )
                )
            self._sync_asr_extract_button()

    def _populate_understanding_dialogue_table(self, cues: list) -> None:
        from PySide6.QtWidgets import QHBoxLayout, QPushButton, QTableWidgetItem, QWidget

        page = getattr(self, "understanding_page", None)
        table = getattr(page, "dialogue_table", None) if page is not None else None
        if table is None:
            return
        rows = list(cues or [])
        table.blockSignals(True)
        table.setRowCount(0)
        table.setRowCount(len(rows))
        edit_label = self.texts.get("understanding_dialogue_edit", "Edit")
        for index, cue in enumerate(rows):
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") or start)
            try:
                seg_index = int(cue.get("seg_index", index))
            except (TypeError, ValueError):
                seg_index = index
            time_item = QTableWidgetItem(format_timecode_range(start, end))
            time_item.setData(Qt.ItemDataRole.UserRole, start)
            time_item.setData(Qt.ItemDataRole.UserRole + 1, seg_index)
            time_item.setData(Qt.ItemDataRole.UserRole + 2, end)
            time_item.setFlags(time_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            speaker_item = QTableWidgetItem(str(cue.get("speaker") or "").strip())
            speaker_item.setData(Qt.ItemDataRole.UserRole, seg_index)
            speaker_item.setFlags(speaker_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            text_item = QTableWidgetItem(str(cue.get("text") or "").strip())
            text_item.setFlags(text_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            text_item.setToolTip(text_item.text())
            table.setItem(index, 0, time_item)
            table.setItem(index, 1, speaker_item)
            table.setItem(index, 2, text_item)
            button = QPushButton(edit_label)
            button.setProperty("class", "TableBtn")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(28)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setAutoDefault(False)
            button.setDefault(False)
            button.clicked.connect(lambda _checked=False, r=index: self._edit_understanding_dialogue_cue(r))
            host = QWidget()
            row_layout = QHBoxLayout(host)
            row_layout.setContentsMargins(4, 0, 4, 0)
            row_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row_layout.addWidget(button)
            table.setCellWidget(index, 3, host)
        table.blockSignals(False)

    def _edit_understanding_dialogue_cue(self, row: int) -> None:
        from ui.dialogs.dialogue_cue import DialogueCueDialog

        page = getattr(self, "understanding_page", None)
        table = getattr(page, "dialogue_table", None) if page is not None else None
        video_id = self._selected_understanding_video_id()
        if table is None or not video_id:
            return
        item = table.item(int(row), 0)
        if item is None:
            return
        try:
            start = float(item.data(Qt.ItemDataRole.UserRole))
            seg_index = int(item.data(Qt.ItemDataRole.UserRole + 1))
        except (TypeError, ValueError):
            return
        try:
            end = float(item.data(Qt.ItemDataRole.UserRole + 2))
        except (TypeError, ValueError):
            end = start
        speaker_item = table.item(int(row), 1)
        text_item = table.item(int(row), 2)
        dialog = DialogueCueDialog(
            self,
            texts=self.texts,
            start=start,
            end=end,
            speaker=str(speaker_item.text() if speaker_item is not None else "").strip(),
            text=str(text_item.text() if text_item is not None else "").strip(),
        )
        if dialog.exec() != DialogueCueDialog.DialogCode.Accepted:
            return
        cue = dialog.result_cue() or {}
        from src.storage.dialogue_transcript_store import update_dialogue_segment

        if not update_dialogue_segment(
            video_id,
            seg_index,
            start=float(cue.get("start") or start),
            end=float(cue.get("end") or end),
            text=str(cue.get("text") or ""),
            speaker=str(cue.get("speaker") or ""),
            config=load_config(),
        ):
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_dialogue_edit_failed", "Could not save this line."),
                kind="warning",
            )
            return
        self._refresh_understanding_dialogue_step()
        table = getattr(page, "dialogue_table", None)
        if table is not None:
            for index in range(table.rowCount()):
                time_item = table.item(index, 0)
                if time_item is None:
                    continue
                try:
                    if int(time_item.data(Qt.ItemDataRole.UserRole + 1)) == seg_index:
                        table.selectRow(index)
                        break
                except (TypeError, ValueError):
                    continue
        if hasattr(self, "_sync_asr_extract_button"):
            self._sync_asr_extract_button()

    def _on_understanding_dialogue_speaker_changed(self, item) -> None:
        from PySide6.QtCore import Qt

        if item is None or int(item.column()) != 1:
            return
        video_id = self._selected_understanding_video_id()
        if not video_id:
            return
        try:
            seg_index = int(item.data(Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return
        from src.storage.dialogue_transcript_store import (
            normalize_dialogue_speaker,
            update_dialogue_segment_speaker,
        )

        speaker = normalize_dialogue_speaker(item.text())
        if speaker != str(item.text() or ""):
            table = item.tableWidget()
            if table is not None:
                table.blockSignals(True)
            item.setText(speaker)
            if table is not None:
                table.blockSignals(False)
        update_dialogue_segment_speaker(video_id, seg_index, speaker, config=load_config())
        if hasattr(self, "_sync_asr_extract_button"):
            self._sync_asr_extract_button()

    def _on_understanding_dialogue_cell_clicked(self, row: int, column: int) -> None:
        # Keep row selection only — do not jump to the VLM chunk timeline.
        _ = (row, column)

    def _on_understanding_dialogue_cell_double_clicked(self, row: int, column: int) -> None:
        """Play this ASR cue's video span (not the overlapping VLM chunk)."""
        if int(column) == 3:
            return
        page = getattr(self, "understanding_page", None)
        table = getattr(page, "dialogue_table", None) if page is not None else None
        if table is None:
            return
        item = table.item(int(row), 0)
        if item is None:
            return
        try:
            start = float(item.data(Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return
        try:
            end = float(item.data(Qt.ItemDataRole.UserRole + 2))
        except (TypeError, ValueError):
            end = start
        self._play_understanding_range(start, end)

    def _current_understanding_preview_path(self) -> str:
        context = dict(getattr(self, "_understanding_video_context", {}) or {})
        path = str(context.get("video_path") or "").strip()
        if path and os.path.isfile(path):
            return path
        video_id = self._selected_understanding_video_id()
        if not video_id:
            return ""
        try:
            from src.services.understanding_service import resolve_video_context

            context = resolve_video_context(video_id, config=load_config(), probe_duration=False)
            self._understanding_video_context = context
            path = str(context.get("video_path") or "").strip()
            if path and os.path.isfile(path):
                return path
        except Exception:
            pass
        return ""

    def _play_understanding_range(self, start_sec: float, end_sec: float) -> None:
        page = getattr(self, "understanding_page", None)
        video_path = self._current_understanding_preview_path()
        if not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return
        start_sec = float(start_sec)
        end_sec = float(end_sec)
        if end_sec <= start_sec:
            end_sec = start_sec + 0.1
        opened = self.open_floating_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=start_sec,
            on_status=None if page is None else page.lbl_status.setText,
        )
        if not opened or page is None:
            return
        message = self.texts.get(
            "understanding_dialogue_play_started",
            "Playing line {range}",
        ).format(range=format_timecode_range(start_sec, end_sec))
        page.lbl_status.setText(message)
        if hasattr(page, "dialogue_status"):
            page.dialogue_status.setText(message)

    def _understanding_outer_scroll(self) -> QScrollArea | None:
        page = getattr(self, "understanding_page", None)
        if page is None:
            return None
        viewport = page.parentWidget()
        if viewport is None:
            return None
        parent = viewport.parentWidget()
        return parent if isinstance(parent, QScrollArea) else None

    @contextmanager
    def _freeze_understanding_page_scroll(self):
        """Keep the page viewport still across layout/visibility churn."""
        scroll = self._understanding_outer_scroll()
        bar = scroll.verticalScrollBar() if scroll is not None else None
        pos = int(bar.value()) if bar is not None else 0
        try:
            yield
        finally:
            if bar is not None:
                bar.setValue(pos)

    def _select_understanding_chunk_at(self, timestamp_sec: float) -> None:
        chunks = list(getattr(self, "_understanding_index_chunks", []) or [])
        if not chunks:
            return
        target = float(timestamp_sec)
        match = 0
        for index, chunk in enumerate(chunks):
            start = float(chunk.get("start", 0.0) or 0.0)
            end = float(chunk.get("end", start) or start)
            if start <= target <= end or (index == 0 and target < start):
                match = index
                break
            if target >= start:
                match = index
        page = self.understanding_page
        page.chunk_timeline.set_selected_index(match)
        QTimer.singleShot(0, lambda idx=match: page.chunk_timeline.set_selected_index(idx))
        self._show_understanding_chunk_detail(match)

    def _ensure_understanding_timeline_on_screen(self) -> None:
        # Intentionally no-op for the page QScrollArea.
        # ensureWidgetVisible used to yank the whole understanding page to the
        # timeline whenever recap/selection updated — felt like every click jumped.
        # ChunkTimelineWidget already scrolls horizontally to the selected segment.
        return

    def _sync_recap_export_button(self, *, running: bool | None = None) -> None:
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "btn_export_recap"):
            return
        if running is None:
            running = bool(
                getattr(self, "understanding_controller", None)
                and self.understanding_controller.is_running()
            ) or getattr(self, "_recap_worker", None) is not None or getattr(
                self, "_asr_worker", None
            ) is not None or getattr(self, "_speaker_cluster_worker", None) is not None
        can = (not running) and self._current_video_can_export_recap()
        has_cuts = self._current_video_has_recap_cuts()
        has_beats = self._current_video_has_recap_beats()
        can_sidecar = (not running) and has_cuts
        dialogue_missing = self.texts.get(
            "understanding_export_recap_dialogue_missing",
            "Extract speech ASR here first. Recap does not use hard-sub OCR.",
        )
        page.btn_export_recap.setEnabled(can)
        if hasattr(page, "btn_recap_step_plan"):
            page.btn_recap_step_plan.setEnabled(can)
        if hasattr(page, "btn_recap_step_match"):
            page.btn_recap_step_match.setEnabled((not running) and has_beats)
        if hasattr(page, "btn_recap_step_captions"):
            page.btn_recap_step_captions.setEnabled((not running) and has_cuts)
        if hasattr(page, "btn_edit_recap_beats"):
            page.btn_edit_recap_beats.setEnabled((not running) and has_beats)
        if hasattr(page, "btn_recap_jianying"):
            page.btn_recap_jianying.setEnabled(can_sidecar)
        if hasattr(page, "btn_recap_fcpxml"):
            page.btn_recap_fcpxml.setEnabled(can_sidecar)
        if hasattr(page, "input_recap_prompt"):
            page.input_recap_prompt.setEnabled(not running)
        if hasattr(page, "input_recap_plan_prompt"):
            page.input_recap_plan_prompt.setEnabled(not running)
        if hasattr(page, "input_recap_caption_prompt"):
            page.input_recap_caption_prompt.setEnabled(not running)
        if hasattr(page, "btn_reset_recap_prompt"):
            page.btn_reset_recap_prompt.setEnabled(not running)
        if hasattr(page, "recap_prompt_tabs"):
            page.recap_prompt_tabs.setEnabled(not running)
        if can:
            page.btn_export_recap.setToolTip(self.texts.get("understanding_export_recap_tip", ""))
            if hasattr(page, "btn_recap_step_plan"):
                page.btn_recap_step_plan.setToolTip(
                    self.texts.get("understanding_recap_step_plan_tip", "")
                )
        elif not self._current_video_has_recap_dialogue():
            page.btn_export_recap.setToolTip(dialogue_missing)
            if hasattr(page, "btn_recap_step_plan"):
                page.btn_recap_step_plan.setToolTip(dialogue_missing)
        else:
            page.btn_export_recap.setToolTip("")
            if hasattr(page, "btn_recap_step_plan"):
                page.btn_recap_step_plan.setToolTip("")
        if hasattr(page, "btn_recap_step_match"):
            page.btn_recap_step_match.setToolTip(
                self.texts.get("understanding_recap_step_match_tip", "")
                if has_beats
                else self.texts.get(
                    "understanding_recap_beats_missing",
                    "No story plan yet. Plan the outline first.",
                )
            )
        if hasattr(page, "btn_recap_step_captions"):
            page.btn_recap_step_captions.setToolTip(
                self.texts.get("understanding_recap_step_captions_tip", "")
                if has_cuts
                else self.texts.get(
                    "understanding_recap_cuts_missing",
                    "No cut list yet. Match shots first.",
                )
            )
        missing_cuts = self.texts.get(
            "understanding_recap_export_missing",
            "Generate recap cuts first.",
        )
        if hasattr(page, "btn_recap_jianying"):
            page.btn_recap_jianying.setToolTip(
                self.texts.get("understanding_recap_jianying_tip", "") if has_cuts else missing_cuts
            )
        if hasattr(page, "btn_recap_fcpxml"):
            page.btn_recap_fcpxml.setToolTip(
                self.texts.get("understanding_recap_fcpxml_tip", "") if has_cuts else missing_cuts
            )
        if hasattr(page, "btn_edit_recap_beats"):
            page.btn_edit_recap_beats.setToolTip(
                self.texts.get("understanding_recap_edit_beats_tip", "")
                if has_beats
                else self.texts.get(
                    "understanding_recap_beats_missing",
                    "No story plan yet. Start from stage 1.",
                )
            )

    def open_subtitle_library_for_recap(self) -> None:
        self.switch_page("library")
        page = getattr(self, "library_page", None)
        if page is not None:
            page.set_library_mode(1)

    def _current_video_has_exportable_evidence(self) -> bool:
        video_id = self._selected_understanding_video_id()
        if not video_id:
            return False
        # Prefer in-memory timeline payloads when already loaded for this video.
        payloads = getattr(self, "_understanding_chunk_payloads", None) or {}
        context = getattr(self, "_understanding_video_context", None) or {}
        if payloads and str(context.get("video_id") or "").strip() == video_id:
            return any(
                isinstance(payload, dict) and self._chunk_payload_has_evidence(payload)
                for payload in payloads.values()
            )
        from src.services.understanding_service import evidence_exists_for_video

        return bool(
            evidence_exists_for_video(
                video_id,
                config=load_config(),
                mode=self._current_understanding_mode(),
            )
        )

    def _default_understanding_export_name(self, evidence: dict) -> str:
        video = dict(evidence.get("video") or {})
        rel_path = str(video.get("video_rel_path") or video.get("video_id") or "video").strip()
        stem = os.path.splitext(os.path.basename(rel_path))[0] or "video"
        return f"{stem}_motion.json"

    def export_current_video_understanding_json(self):
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        evidence = load_evidence_bundle(
            video_id,
            config=load_config(),
            mode=self._current_understanding_mode(),
        )
        if not evidence:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_export_video_empty", "No understanding evidence for this video yet."),
                kind="warning",
            )
            return
        default_name = self._default_understanding_export_name(evidence)
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("understanding_export_video_title", "Export Video Understanding JSON"),
            default_name,
            self.texts.get("details_export_filter", "JSON Files (*.json)"),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(evidence, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.show_error_dialog(self.texts.get("details_export_failed", "Export failed."), exc)
            return
        message = self.texts.get("details_export_done", "Exported: {path}").format(path=path)
        self.understanding_page.lbl_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def show_local_evidence_details(self):
        try:
            detail = list_local_evidence_details(mode=self._current_understanding_mode())
            dialog = self._create_evidence_detail_dialog(detail)
            dialog.exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_evidence_load_failed"], exc)

    def _create_evidence_detail_dialog(self, detail):
        yes_text = self.texts["details_yes"]
        no_text = self.texts["details_no"]
        rows, payloads = self._build_local_evidence_detail_rows(detail, yes_text=yes_text, no_text=no_text)
        title = self.texts.get("library_evidence_title_motion", self.texts["library_evidence_title"])
        subtitle = self.texts["library_evidence_subtitle"].format(
            total=detail["total_entries"],
            evidence_dir=detail["evidence_dir"],
        )
        invalid_state_text = self.texts.get("library_evidence_state_invalid", "Invalid")
        return ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=title,
            subtitle=subtitle,
            headers=self.texts["library_evidence_headers"],
            rows=rows,
            row_payloads=payloads,
            export_default_name="local_evidence_details.json",
            stretch_column=2,
            allow_sorting=False,
            selection_mode=QAbstractItemView.ExtendedSelection,
            fixed_column_widths={
                0: 52,
                1: 200,
                2: 200,
                3: 120,
                4: 96,
                5: 140,
                6: 120,
                7: 180,
                8: 86,
                9: 86,
                10: 72,
                11: 148,
                12: 120,
            },
            issue_row_predicate=lambda row, invalid_text=invalid_state_text: row[12] == invalid_text,
            extra_actions=[
                {
                    "label": self.texts["details_open_selected"],
                    "object_name": "GhostButton",
                    "handler": self._open_selected_evidence_detail_path,
                },
                {
                    "label": self.texts["details_copy_selected"],
                    "object_name": "GhostButton",
                    "handler": self._copy_selected_evidence_detail_path,
                },
                {
                    "label": self.texts.get("library_evidence_open_dir", "Open Evidence Folder"),
                    "object_name": "GhostButton",
                    "handler": self._open_evidence_detail_folder,
                },
                {
                    "label": self.texts.get("library_evidence_delete_selected", "Delete Selected"),
                    "object_name": "DangerGhostButton",
                    "handler": self._delete_selected_evidence_records,
                },
                {
                    "label": self.texts.get("library_evidence_clear_all", "Clear All Evidence"),
                    "object_name": "DangerGhostButton",
                    "handler": self._clear_all_evidence_records,
                },
            ],
            row_double_click_handler=self._open_evidence_detail_payload,
        )

    def _reload_evidence_detail_dialog(self, dialog):
        detail = list_local_evidence_details(mode=self._current_understanding_mode())
        yes_text = self.texts["details_yes"]
        no_text = self.texts["details_no"]
        rows, payloads = self._build_local_evidence_detail_rows(detail, yes_text=yes_text, no_text=no_text)
        dialog.set_rows(rows, payloads)
        return detail

    def _delete_selected_evidence_records(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        if not self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["library_evidence_delete_confirm"].format(count=len(selected)),
            kind="warning",
        ):
            return
        paths = []
        for item in selected:
            evidence_file = str(item.get("evidence_file", "") or "").strip()
            if evidence_file:
                paths.append(evidence_file)
                paths.append(f"{evidence_file}.tmp")
        from src.services.understanding_service import _remove_paths

        removed, errors = _remove_paths(paths)
        detail = self._reload_evidence_detail_dialog(dialog)
        deleted_count = len({os.path.splitext(os.path.basename(path))[0] for path in removed})
        error_count = len(errors or [])
        if error_count:
            dialog.status_hint.setText(
                self.texts["library_evidence_delete_done_with_errors"].format(
                    count=deleted_count,
                    errors=error_count,
                )
            )
        else:
            dialog.status_hint.setText(
                self.texts["library_evidence_delete_done"].format(
                    count=deleted_count,
                    total=detail["evidence_count"],
                )
            )
        self._load_understanding_video_timeline()

    def _clear_all_evidence_records(self, dialog):
        detail = list_local_evidence_details()
        if int(detail.get("total_entries", 0) or 0) <= 0:
            dialog.status_hint.setText(self.texts.get("library_evidence_clear_empty", "No evidence files to clear."))
            return
        if not self.show_confirm_dialog(
            self.texts.get("library_evidence_clear_confirm_title", self.texts["confirm_title"]),
            self.texts["library_evidence_clear_confirm"].format(count=detail["total_entries"]),
            kind="warning",
        ):
            return
        result = clear_all_evidence()
        detail = self._reload_evidence_detail_dialog(dialog)
        deleted_count = int(result.get("deleted_count", 0) or 0)
        error_count = len(result.get("errors") or [])
        if error_count:
            dialog.status_hint.setText(
                self.texts["library_evidence_clear_done_with_errors"].format(
                    count=deleted_count,
                    errors=error_count,
                )
            )
        else:
            dialog.status_hint.setText(
                self.texts["library_evidence_clear_done"].format(
                    count=deleted_count,
                    total=detail["evidence_count"],
                )
            )

    def _build_local_evidence_detail_rows(self, detail, *, yes_text, no_text):
        rows = []
        payloads = []
        for index, item in enumerate(detail.get("entries") or [], start=1):
            clip_label = str(item.get("clip_model", "") or "").strip()
            provider = str(item.get("search_provider", "") or "").strip()
            if clip_label and provider:
                clip_label = f"{provider}/{clip_label}"
            rows.append(
                [
                    index,
                    item.get("library_path", ""),
                    item.get("video_rel_path", ""),
                    clip_label,
                    item.get("caption_model", "") or "",
                    item.get("other_models", "") or "",
                    os.path.basename(item.get("evidence_file", "") or "") if item.get("evidence_file") else "",
                    yes_text if item.get("source_exists") else no_text,
                    yes_text,
                    int(item.get("chunk_count", 0) or 0),
                    item.get("generated_at", "") or "",
                    self._local_evidence_state_text(item.get("evidence_state", "")),
                ]
            )
            payloads.append(item)
        return rows, payloads

    def _local_evidence_state_text(self, evidence_state):
        state_key = str(evidence_state or "").strip().lower() or "missing"
        return self.texts.get(f"library_evidence_state_{state_key}", state_key)

    def _open_evidence_detail_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 7
        library_path = str(payload.get("library_path", "") or "").strip()
        video_rel_path = str(payload.get("video_rel_path", "") or "").strip()
        evidence_file = str(payload.get("evidence_file", "") or "").strip()

        if column == 1:
            if not library_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_folder_in_explorer(library_path)
            dialog.status_hint.setText(library_path)
            return

        if column == 2:
            if not library_path or not video_rel_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            video_path = os.path.normpath(os.path.join(library_path, video_rel_path))
            if os.path.exists(video_path):
                open_in_explorer(video_path)
            else:
                open_folder_in_explorer(library_path)
            dialog.status_hint.setText(video_path)
            return

        if column == 7:
            if not evidence_file:
                dialog.status_hint.setText(self.texts.get("library_evidence_missing_file", "No evidence file yet."))
                return
            if os.path.exists(evidence_file):
                open_in_explorer(evidence_file)
            else:
                parent_dir = os.path.dirname(evidence_file)
                if parent_dir:
                    open_folder_in_explorer(parent_dir)
            dialog.status_hint.setText(evidence_file)
            return

        if not evidence_file:
            dialog.status_hint.setText(self.texts.get("library_evidence_missing_file", "No evidence file yet."))
            return
        if os.path.exists(evidence_file):
            open_in_explorer(evidence_file)
        else:
            parent_dir = os.path.dirname(evidence_file)
            if parent_dir:
                open_folder_in_explorer(parent_dir)
        dialog.status_hint.setText(evidence_file)

    def _open_selected_evidence_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_evidence_detail_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_evidence_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = str(payload.get("evidence_file", "") or "").strip()
        if not target_path:
            dialog.status_hint.setText(self.texts.get("library_evidence_missing_file", "No evidence file yet."))
            return
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def _open_evidence_detail_folder(self, dialog):
        try:
            from src.services.understanding_paths import get_evidence_mode_dir, get_evidence_root

            mode = self._current_understanding_mode()
            evidence_dir = os.path.normpath(get_evidence_mode_dir(mode, config=load_config()))
            os.makedirs(evidence_dir, exist_ok=True)
            open_folder_in_explorer(evidence_dir)
            dialog.status_hint.setText(evidence_dir)
            return
        except Exception as exc:
            try:
                evidence_dir = os.path.normpath(get_evidence_root(config=load_config()))
                os.makedirs(evidence_dir, exist_ok=True)
                open_folder_in_explorer(evidence_dir)
                dialog.status_hint.setText(evidence_dir)
                return
            except Exception:
                dialog.status_hint.setText(str(exc))
                return
