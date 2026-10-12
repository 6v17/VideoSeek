"""ASR settings + speech extract for the understanding page."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog

from src.app.config import load_config
from src.services.asr_settings import (
    REMOTE_ASR_MODE_CLOUD,
    REMOTE_ASR_MODE_LOCAL,
    REMOTE_ASR_PRESET_CUSTOM,
    finalize_remote_asr_settings,
    get_remote_asr_api_key_for_preset,
    get_remote_asr_preset_defaults,
    get_remote_asr_settings,
    list_remote_asr_preset_ids,
    normalize_remote_asr_api_keys,
    normalize_remote_asr_provider_mode,
    set_remote_asr_api_key_for_preset,
)
from ui.workers import AsrTranscriptWorker, RemoteAsrConnectionTestWorker, SpeakerClusterWorker


class UnderstandingAsrGuiMixin:
    def _asr_form(self):
        dialog = getattr(self, "understanding_services_dialog", None)
        return getattr(dialog, "asr_form", None) if dialog is not None else None

    def _load_asr_settings(self, config=None):
        form = self._asr_form()
        if form is None:
            return
        cfg = config if config is not None else load_config()
        remote_asr = dict(get_remote_asr_settings(cfg))
        self._remote_asr_api_keys = normalize_remote_asr_api_keys(remote_asr.get("api_keys"))
        mode = remote_asr.get("provider_mode", REMOTE_ASR_MODE_CLOUD)
        self._populate_asr_provider_mode_options(mode)
        self._populate_asr_provider_preset_options(mode, remote_asr.get("provider_preset", "openai"))
        form.input_remote_asr_base_url.setText(str(remote_asr.get("base_url", "") or ""))
        form.input_remote_asr_model.setText(str(remote_asr.get("model", "") or ""))
        form.input_remote_asr_api_key.setText(
            get_remote_asr_api_key_for_preset(
                remote_asr,
                remote_asr.get("provider_preset", "openai"),
                mode=mode,
            )
        )
        self._sync_asr_provider_ui()
        self._remember_asr_ui_selection(form)

    def _asr_provider_mode_label(self, mode: str) -> str:
        if mode == REMOTE_ASR_MODE_CLOUD:
            return self.texts.get("understanding_vlm_provider_mode_cloud", "Cloud API")
        return self.texts.get("understanding_vlm_provider_mode_local", "Local")

    def _asr_provider_preset_label(self, preset_id: str) -> str:
        key = f"understanding_asr_provider_preset_{preset_id}"
        defaults = {
            "openai": "OpenAI Whisper",
            "groq": "Groq",
            "dashscope": "DashScope (Qwen-ASR)",
            "siliconflow": "SiliconFlow",
            REMOTE_ASR_PRESET_CUSTOM: "Custom",
        }
        return self.texts.get(key, defaults.get(preset_id, preset_id))

    def _populate_asr_provider_mode_options(self, active_mode=None):
        form = self._asr_form()
        if form is None:
            return
        combo = form.input_asr_provider_mode
        active = normalize_remote_asr_provider_mode(active_mode)
        combo.blockSignals(True)
        combo.clear()
        for mode in (REMOTE_ASR_MODE_LOCAL, REMOTE_ASR_MODE_CLOUD):
            combo.addItem(self._asr_provider_mode_label(mode), mode)
        index = combo.findData(active)
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _populate_asr_provider_preset_options(self, mode, active_preset=None):
        form = self._asr_form()
        if form is None:
            return
        combo = form.input_asr_provider_preset
        normalized_mode = normalize_remote_asr_provider_mode(mode)
        active = str(active_preset or "").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        preset_ids = list_remote_asr_preset_ids(mode=normalized_mode)
        for preset_id in preset_ids:
            combo.addItem(self._asr_provider_preset_label(preset_id), preset_id)
        index = combo.findData(active if active in preset_ids else preset_ids[0])
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _sync_asr_provider_ui(self):
        form = self._asr_form()
        if form is None:
            return
        mode = normalize_remote_asr_provider_mode(form.input_asr_provider_mode.currentData())
        preset_id = str(form.input_asr_provider_preset.currentData() or REMOTE_ASR_PRESET_CUSTOM)
        is_cloud = mode == REMOTE_ASR_MODE_CLOUD
        is_custom = preset_id == REMOTE_ASR_PRESET_CUSTOM
        preset_defaults = get_remote_asr_preset_defaults(preset_id) if not is_custom else {}
        form.label_remote_asr_api_key.setVisible(is_cloud)
        form.input_remote_asr_api_key.setVisible(is_cloud)
        form.label_remote_asr_base_url.setVisible(is_custom)
        form.input_remote_asr_base_url.setVisible(is_custom)
        form.label_remote_asr_model.setVisible(True)
        form.input_remote_asr_model.setVisible(True)
        if is_custom:
            form.hint_asr_preset_summary.hide()
            return
        if preset_defaults.get("base_url"):
            form.input_remote_asr_base_url.setText(str(preset_defaults.get("base_url") or ""))
        current = str(form.input_remote_asr_model.text() or "").strip()
        model = current or str(preset_defaults.get("model", "") or "").strip()
        if model and not current:
            form.input_remote_asr_model.setText(model)
        if model:
            form.hint_asr_preset_summary.setText(
                self.texts.get(
                    "understanding_asr_preset_model_hint",
                    "Preset {preset}: {model} via {base_url}. Change the id if your account list differs.",
                ).format(
                    preset=self._asr_provider_preset_label(preset_id),
                    model=model,
                    base_url=str(preset_defaults.get("base_url", "") or form.input_remote_asr_base_url.text() or "—"),
                )
            )
            form.hint_asr_preset_summary.show()
        else:
            form.hint_asr_preset_summary.hide()

    def _remember_asr_ui_selection(self, form):
        if form is None:
            return
        self._asr_ui_mode = normalize_remote_asr_provider_mode(form.input_asr_provider_mode.currentData())
        self._asr_ui_preset = str(form.input_asr_provider_preset.currentData() or REMOTE_ASR_PRESET_CUSTOM)

    def _commit_asr_api_key_draft(self, form):
        if form is None:
            return
        if not hasattr(self, "_remote_asr_api_keys") or not isinstance(self._remote_asr_api_keys, dict):
            self._remote_asr_api_keys = {}
        mode = normalize_remote_asr_provider_mode(
            getattr(self, "_asr_ui_mode", None) or form.input_asr_provider_mode.currentData()
        )
        preset_id = str(getattr(self, "_asr_ui_preset", "") or form.input_asr_provider_preset.currentData() or "")
        self._remote_asr_api_keys = set_remote_asr_api_key_for_preset(
            self._remote_asr_api_keys,
            preset_id,
            form.input_remote_asr_api_key.text(),
            mode=mode,
        )

    def _load_asr_api_key_for_preset(self, form, preset_id: str, mode: str):
        if form is None:
            return
        if not hasattr(self, "_remote_asr_api_keys") or not isinstance(self._remote_asr_api_keys, dict):
            self._remote_asr_api_keys = {}
        draft = {"api_keys": self._remote_asr_api_keys, "provider_preset": preset_id, "provider_mode": mode}
        form.input_remote_asr_api_key.setText(get_remote_asr_api_key_for_preset(draft, preset_id, mode=mode))

    def _resolve_asr_fields_for_save(self, form):
        provider_mode = normalize_remote_asr_provider_mode(form.input_asr_provider_mode.currentData())
        provider_preset = str(form.input_asr_provider_preset.currentData() or REMOTE_ASR_PRESET_CUSTOM)
        if provider_preset != REMOTE_ASR_PRESET_CUSTOM:
            defaults = get_remote_asr_preset_defaults(provider_preset)
            base_url = str(defaults.get("base_url", "") or form.input_remote_asr_base_url.text() or "").strip()
            model = form.input_remote_asr_model.text().strip() or str(defaults.get("model", "") or "").strip()
        else:
            base_url = form.input_remote_asr_base_url.text().strip()
            model = form.input_remote_asr_model.text().strip()
        return provider_mode, provider_preset, base_url, model

    def _commit_asr_settings_to_understanding(self, understanding: dict) -> None:
        form = self._asr_form()
        if form is None:
            return
        self._commit_asr_api_key_draft(form)
        provider_mode, provider_preset, base_url, model = self._resolve_asr_fields_for_save(form)
        remote_asr = dict(understanding.get("remote_asr") or {})
        remote_asr["provider_mode"] = provider_mode
        remote_asr["provider_preset"] = provider_preset
        remote_asr["base_url"] = base_url
        remote_asr["model"] = model
        remote_asr["api_keys"] = dict(getattr(self, "_remote_asr_api_keys", {}) or {})
        understanding["remote_asr"] = finalize_remote_asr_settings(remote_asr)

    def _apply_asr_provider_preset(self, preset_id: str):
        form = self._asr_form()
        if form is None:
            return
        preset_id = str(preset_id or "").strip().lower()
        mode = normalize_remote_asr_provider_mode(form.input_asr_provider_mode.currentData())
        defaults = get_remote_asr_preset_defaults(preset_id)
        if preset_id != REMOTE_ASR_PRESET_CUSTOM and defaults:
            form.input_remote_asr_base_url.setText(defaults.get("base_url", ""))
            form.input_remote_asr_model.setText(defaults.get("model", ""))
        self._sync_asr_provider_ui()
        if mode == REMOTE_ASR_MODE_CLOUD:
            self._load_asr_api_key_for_preset(form, preset_id, mode)
        else:
            form.input_remote_asr_api_key.setText("")

    def _on_asr_provider_mode_changed(self, _index=None):
        form = self._asr_form()
        if form is None:
            return
        self._commit_asr_api_key_draft(form)
        mode = normalize_remote_asr_provider_mode(form.input_asr_provider_mode.currentData())
        default_preset = "openai" if mode == REMOTE_ASR_MODE_CLOUD else REMOTE_ASR_PRESET_CUSTOM
        self._populate_asr_provider_preset_options(mode, default_preset)
        self._apply_asr_provider_preset(default_preset)
        self._remember_asr_ui_selection(form)

    def _on_asr_provider_preset_changed(self, _index=None):
        form = self._asr_form()
        if form is None:
            return
        self._commit_asr_api_key_draft(form)
        preset_id = str(form.input_asr_provider_preset.currentData() or REMOTE_ASR_PRESET_CUSTOM)
        self._apply_asr_provider_preset(preset_id)
        self._remember_asr_ui_selection(form)

    def test_understanding_asr_connection(self):
        form = self._asr_form()
        page = self._understanding_config_widgets()
        if form is None or page is None:
            return
        if getattr(self, "_asr_connection_test_worker", None) is not None:
            return
        self._commit_asr_api_key_draft(form)
        provider_mode, provider_preset, base_url, model = self._resolve_asr_fields_for_save(form)
        draft = {
            "provider_mode": provider_mode,
            "provider_preset": provider_preset,
            "base_url": base_url,
            "model": model,
            "api_keys": dict(getattr(self, "_remote_asr_api_keys", {}) or {}),
        }
        from ui.widgets.understanding_form_common import set_status_hint

        set_status_hint(
            form.hint_asr_status,
            self.texts.get("understanding_test_asr_testing", "Testing speech model…"),
            state="neutral",
        )
        worker = RemoteAsrConnectionTestWorker(draft, timeout_sec=8.0, parent=self)
        self._asr_connection_test_worker = worker
        page.btn_test_vlm_connection.setEnabled(False)

        def _finish(active_worker=worker):
            if getattr(self, "_asr_connection_test_worker", None) is active_worker:
                self._asr_connection_test_worker = None
            page.btn_test_vlm_connection.setEnabled(True)
            try:
                active_worker.deleteLater()
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:263")
                pass

        from ui.threading_utils import connect_on_receiver

        connect_on_receiver(
            worker,
            "result_ready(QVariantMap)",
            self,
            lambda probe: self._finish_asr_connection_test(probe, form),
        )
        connect_on_receiver(
            worker,
            "error_signal(QString)",
            self,
            lambda message: self._fail_asr_connection_test(message, form),
        )
        connect_on_receiver(worker, "finished()", self, _finish)
        worker.start()

    def _finish_asr_connection_test(self, probe, form):
        from src.services.asr_settings import pick_available_asr_model
        from ui.widgets.understanding_form_common import set_status_hint

        probe = dict(probe or {})
        configured = str(probe.get("configured_model", "") or "").strip()
        if probe.get("reachable") and not probe.get("model_available"):
            suggested = pick_available_asr_model(configured, probe.get("available_models") or [])
            if suggested and suggested != configured:
                form.input_remote_asr_model.setText(suggested)
                self._sync_asr_provider_ui()
                message = self.texts.get(
                    "understanding_test_asr_model_switched",
                    "Connected. {old} is not on this account; filled in {model}. Save, then test again.",
                ).format(old=configured or "?", model=suggested)
                set_status_hint(form.hint_asr_status, message, state="warn")
                self.show_info_dialog(
                    self.texts.get("understanding_test_vlm_title", "Connection test"),
                    message,
                    kind="warning",
                )
                return
        message = self._format_vlm_probe_status(probe)
        set_status_hint(form.hint_asr_status, message, state=self._probe_status_state(probe))
        if probe.get("reachable") and probe.get("model_available"):
            live = str(probe.get("configured_model") or "").strip()
            if live:
                form.input_remote_asr_model.setText(live)
                self._sync_asr_provider_ui()
            self.show_info_dialog(
                self.texts.get("understanding_test_vlm_title", "Connection test"),
                message,
                kind="success",
            )
        elif probe.get("error_code") != "cloud_api_key_required":
            self.show_error_dialog(message)

    def _fail_asr_connection_test(self, message, form):
        from ui.widgets.understanding_form_common import set_status_hint

        text = self.texts.get("understanding_test_vlm_failed", "Connection failed: {error}").format(
            error=str(message or "unknown error")
        )
        set_status_hint(form.hint_asr_status, text, state="error")
        self.show_error_dialog(text)

    def _asr_job_running(self) -> bool:
        return (
            getattr(self, "_asr_worker", None) is not None
            or getattr(self, "_speaker_cluster_worker", None) is not None
        )

    def _dialogue_extract_uses_ocr(self) -> bool:
        page = getattr(self, "understanding_page", None)
        button = getattr(page, "btn_dialogue_mode_ocr", None)
        return bool(button is not None and button.isChecked())

    def _sync_dialogue_extract_label(self, *_args) -> None:
        page = getattr(self, "understanding_page", None)
        button = getattr(page, "btn_extract_asr", None)
        if button is None:
            return
        texts = getattr(self, "texts", None) or {}
        if self._dialogue_extract_uses_ocr():
            button.setText(texts.get("understanding_step_dialogue_open", "Extract subtitles"))
        else:
            button.setText(texts.get("understanding_step_dialogue_extract_asr", "Extract speech"))

    def _set_dialogue_mode_enabled(self, enabled: bool) -> None:
        page = getattr(self, "understanding_page", None)
        for name in ("btn_dialogue_mode_ocr", "btn_dialogue_mode_asr"):
            button = getattr(page, name, None)
            if button is not None:
                button.setEnabled(bool(enabled))

    def _confirm_replace_local_dialogue(self) -> bool:
        from src.services.understanding_dialogue import load_working_copy

        video_id = self._selected_understanding_video_id()
        payload = load_working_copy(video_id, config=load_config()) if video_id else None
        if not list((payload or {}).get("cues") or []):
            return True
        return self.show_confirm_dialog(
            self.texts.get("confirm_title", "Confirm"),
            self.texts.get(
                "understanding_dialogue_replace_local_confirm",
                "This replaces the dialogue on this page. The subtitle library stays unchanged. Continue?",
            ),
        )

    def _extract_current_video_ocr(self):
        from src.services.subtitle_index_service import ensure_subtitle_ocr_ready
        from src.utils import has_ffmpeg
        from ui.workers import DialogueIndexWorker

        page = getattr(self, "understanding_page", None)
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        if not has_ffmpeg():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_asr_missing_ffmpeg",
                    "FFmpeg is required for speech extraction. Configure it in Settings.",
                ),
                kind="warning",
            )
            return
        ready, error = ensure_subtitle_ocr_ready(config=load_config(), import_engine=False)
        if not ready:
            detail = self.texts.get(
                "understanding_ocr_missing",
                "Import RapidOCR first.",
            )
            if error:
                detail = f"{detail}\n\n{error}"
            self.show_info_dialog(self.texts.get("warning_title", "Warning"), detail, kind="warning")
            return
        if not self._confirm_replace_local_dialogue():
            return
        context = getattr(self, "_understanding_video_context", None) or {}
        if str(context.get("video_id") or "") != video_id:
            from src.services.understanding_service import resolve_video_context

            try:
                context = resolve_video_context(video_id, config=load_config(), probe_duration=False)
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:ocr_context")
                context = {}
        running_text = self.texts.get("understanding_ocr_extract_running", "Reading burned-in subtitles…")
        if page is not None:
            page.lbl_status.setText(running_text)
            page.progress_bar.setVisible(True)
            page.progress_bar.setValue(5)
            page.btn_stop.setVisible(True)
            page.btn_stop.setEnabled(True)
            if hasattr(page, "btn_stop_asr"):
                page.btn_stop_asr.setVisible(True)
                page.btn_stop_asr.setEnabled(True)
            if hasattr(page, "dialogue_progress_bar"):
                page.dialogue_progress_bar.setVisible(True)
                page.dialogue_progress_bar.setValue(5)
            if hasattr(page, "dialogue_progress_status"):
                page.dialogue_progress_status.set_status_text(running_text)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(running_text)
            page.btn_generate_evidence.setEnabled(False)
            if hasattr(page, "btn_generate_batch"):
                page.btn_generate_batch.setEnabled(False)
            page.scope_combo.setEnabled(False)
            page.video_combo.setEnabled(False)
        if hasattr(page, "btn_extract_asr"):
            page.btn_extract_asr.setEnabled(False)
        self._set_dialogue_mode_enabled(False)
        if hasattr(page, "btn_cluster_speakers"):
            page.btn_cluster_speakers.setEnabled(False)
        if hasattr(page, "btn_rename_speakers"):
            page.btn_rename_speakers.setEnabled(False)
        if hasattr(page, "btn_reset_speakers"):
            page.btn_reset_speakers.setEnabled(False)
        if hasattr(page, "btn_export_dialogue_json"):
            page.btn_export_dialogue_json.setEnabled(False)
        self._sync_recap_export_button(running=True)
        worker = DialogueIndexWorker(
            [
                {
                    "video_id": video_id,
                    "video_path": str(context.get("video_path") or ""),
                    "library_path": str(context.get("library_path") or ""),
                }
            ],
            mode="ocr",
            persist=False,
            force_overwrite=True,  # user confirmed via _confirm_replace_local_dialogue
        )
        worker.setParent(self)
        self._asr_worker = worker

        def _finish(active_worker=worker):
            if getattr(self, "_asr_worker", None) is active_worker:
                self._asr_worker = None
            if page is not None:
                page.progress_bar.setVisible(False)
                if hasattr(page, "dialogue_progress_bar"):
                    page.dialogue_progress_bar.setVisible(False)
                generating = bool(
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                )
                if not generating:
                    page.btn_stop.setEnabled(False)
                    page.btn_stop.setVisible(False)
                    if hasattr(page, "btn_stop_asr"):
                        page.btn_stop_asr.setEnabled(False)
                        page.btn_stop_asr.setVisible(False)
                    page.btn_generate_evidence.setEnabled(True)
                    if hasattr(page, "btn_generate_batch"):
                        page.btn_generate_batch.setEnabled(True)
                    page.scope_combo.setEnabled(True)
                    page.video_combo.setEnabled(True)
            self._sync_asr_extract_button()
            self._sync_recap_export_button(running=False)
            try:
                active_worker.deleteLater()
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:ocr_finish")
            if hasattr(self, "_maybe_close_when_busy_work_stops"):
                self._maybe_close_when_busy_work_stops()

        worker.progress_signal.connect(self._on_understanding_ocr_progress)
        worker.finished_signal.connect(self._finish_ocr_extract)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get("understanding_ocr_extract_failed", "Hard-sub OCR failed"),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()

    def _on_understanding_ocr_progress(self, value, text) -> None:
        self._update_understanding_progress(value, self._format_understanding_ocr_progress(text))

    def _format_understanding_ocr_progress(self, text: str) -> str:
        """Turn ``dialogue_index|1|1|subtitle_ocr|12|400`` into a readable stage line."""
        raw = str(text or "").strip()
        fallback = self.texts.get("understanding_ocr_extract_running", "Reading burned-in subtitles…")
        if not raw.startswith("dialogue_index|"):
            return raw or fallback
        parts = raw.split("|")
        if len(parts) < 3:
            return raw or fallback
        stage_token = "|".join(parts[3:]) if len(parts) > 3 else ""
        stage = ""
        if stage_token and hasattr(self, "_format_dialogue_stage"):
            formatted = str(self._format_dialogue_stage(stage_token) or "")
            if formatted and formatted != stage_token:
                stage = formatted
        current, total = parts[1], parts[2]
        if not stage:
            stage = fallback
        if current == total == "1":
            return stage
        return self.texts.get(
            "build_dialogue_index_progress",
            "Subtitles {current}/{total}: {stage}",
        ).format(current=current, total=total, stage=stage)

    def _finish_ocr_extract(self, ok: bool, stopped: bool, payload: object):
        page = getattr(self, "understanding_page", None)
        self._refresh_understanding_dialogue_step()
        summary = dict(payload or {})
        if stopped or not ok or int(summary.get("failed") or 0) > 0:
            if page is not None and stopped:
                page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
                if hasattr(page, "dialogue_status"):
                    page.dialogue_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            elif int(summary.get("failed") or 0) > 0:
                detail = "; ".join(str(item) for item in list(summary.get("errors") or []) if str(item).strip())
                self.show_error_dialog(
                    self.texts.get("understanding_ocr_extract_failed", "Hard-sub OCR failed"),
                    Exception(detail or "OCR failed"),
                )
            return
        count = int(summary.get("segment_rows") or 0)
        if count <= 0:
            message = self.texts.get(
                "understanding_ocr_extract_empty",
                "No burned-in subtitles found.",
            )
            if page is not None:
                page.lbl_status.setText(message)
                if hasattr(page, "dialogue_status"):
                    page.dialogue_status.setText(message)
            self.show_info_dialog(self.texts.get("warning_title", "Warning"), message, kind="warning")
            return
        message = self.texts.get(
            "understanding_ocr_extract_done",
            "Saved {count} hard-sub cues.",
        ).format(count=count)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def extract_current_video_asr(self):
        from src.services.asr_settings import get_remote_asr_settings
        from src.utils import has_ffmpeg

        if self._asr_job_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        if self._dialogue_extract_uses_ocr():
            self._extract_current_video_ocr()
            return
        page = getattr(self, "understanding_page", None)
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        if not has_ffmpeg():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_asr_missing_ffmpeg",
                    "FFmpeg is required for speech extraction. Configure it in Settings.",
                ),
                kind="warning",
            )
            return
        asr = get_remote_asr_settings(load_config())
        if not str(asr.get("model") or "").strip():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_asr_not_configured", "Configure speech ASR in Model services first."),
                kind="warning",
            )
            return
        if not self._confirm_replace_local_dialogue():
            return
        context = getattr(self, "_understanding_video_context", None) or {}
        if str(context.get("video_id") or "") != video_id:
            from src.services.understanding_service import resolve_video_context

            try:
                context = resolve_video_context(video_id, config=load_config(), probe_duration=False)
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:387")
                context = {}
        language = ""
        if page is not None:
            language = str(page.input_caption_language.currentData() or "").strip().lower()
        if page is not None:
            page.lbl_status.setText(self.texts.get("understanding_asr_extract_running", "Extracting speech…"))
            page.progress_bar.setVisible(True)
            page.progress_bar.setValue(5)
            page.btn_stop.setVisible(True)
            page.btn_stop.setEnabled(True)
            if hasattr(page, "btn_stop_asr"):
                page.btn_stop_asr.setVisible(True)
                page.btn_stop_asr.setEnabled(True)
            if hasattr(page, "dialogue_progress_bar"):
                page.dialogue_progress_bar.setVisible(True)
                page.dialogue_progress_bar.setValue(5)
            if hasattr(page, "dialogue_progress_status"):
                page.dialogue_progress_status.set_status_text(
                    self.texts.get("understanding_asr_extract_running", "Extracting speech…")
                )
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(
                    self.texts.get("understanding_asr_extract_running", "Extracting speech…")
                )
            page.btn_generate_evidence.setEnabled(False)
            if hasattr(page, "btn_generate_batch"):
                page.btn_generate_batch.setEnabled(False)
            page.scope_combo.setEnabled(False)
            page.video_combo.setEnabled(False)
        if hasattr(page, "btn_extract_asr"):
            page.btn_extract_asr.setEnabled(False)
        self._set_dialogue_mode_enabled(False)
        if hasattr(page, "btn_cluster_speakers"):
            page.btn_cluster_speakers.setEnabled(False)
        if hasattr(page, "btn_rename_speakers"):
            page.btn_rename_speakers.setEnabled(False)
        if hasattr(page, "btn_reset_speakers"):
            page.btn_reset_speakers.setEnabled(False)
        if hasattr(page, "btn_export_dialogue_json"):
            page.btn_export_dialogue_json.setEnabled(False)
        self._sync_recap_export_button(running=True)
        worker = AsrTranscriptWorker(
            video_id,
            video_path=str(context.get("video_path") or ""),
            library_path=str(context.get("library_path") or ""),
            force=True,
            language=language,
            persist=False,
            force_overwrite=True,  # user confirmed via _confirm_replace_local_dialogue
            parent=self,
        )
        self._asr_worker = worker

        def _finish(active_worker=worker):
            if getattr(self, "_asr_worker", None) is active_worker:
                self._asr_worker = None
            if page is not None:
                page.progress_bar.setVisible(False)
                if hasattr(page, "dialogue_progress_bar"):
                    page.dialogue_progress_bar.setVisible(False)
                generating = bool(
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                )
                if not generating:
                    page.btn_stop.setEnabled(False)
                    page.btn_stop.setVisible(False)
                    if hasattr(page, "btn_stop_asr"):
                        page.btn_stop_asr.setEnabled(False)
                        page.btn_stop_asr.setVisible(False)
                    page.btn_generate_evidence.setEnabled(True)
                    if hasattr(page, "btn_generate_batch"):
                        page.btn_generate_batch.setEnabled(True)
                    page.scope_combo.setEnabled(True)
                    page.video_combo.setEnabled(True)
            self._sync_asr_extract_button()
            self._sync_recap_export_button(running=False)
            try:
                active_worker.deleteLater()
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:464")
                pass
            if hasattr(self, "_maybe_close_when_busy_work_stops"):
                self._maybe_close_when_busy_work_stops()

        worker.progress_signal.connect(self._update_understanding_progress)
        worker.finished_signal.connect(self._finish_asr_extract)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get("understanding_asr_extract_failed", "Speech extraction failed"),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()

    def _finish_asr_extract(self, ok: bool, stopped: bool, payload: object):
        page = getattr(self, "understanding_page", None)
        self._refresh_understanding_dialogue_step()
        if stopped or not ok:
            if page is not None and stopped:
                page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
                if hasattr(page, "dialogue_status"):
                    page.dialogue_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        result = dict(payload or {})
        count = int(result.get("segment_count") or 0)
        if count <= 0:
            message = self.texts.get(
                "understanding_asr_extract_empty",
                "Speech ASR finished, but no dialogue was recognized.",
            )
            if page is not None:
                page.lbl_status.setText(message)
                if hasattr(page, "dialogue_status"):
                    page.dialogue_status.setText(message)
            self.show_info_dialog(self.texts.get("warning_title", "Warning"), message, kind="warning")
            return
        message = self.texts.get(
            "understanding_asr_extract_done",
            "Speech ASR saved {count} cues.",
        ).format(count=count)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def _sync_asr_extract_button(self) -> None:
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "btn_extract_asr"):
            return
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION

        running = bool(
            getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()
        ) or self._asr_job_running() or getattr(self, "_recap_worker", None) is not None
        can = (
            (not running)
            and self._current_understanding_mode() == UNDERSTANDING_MODE_MOTION
            and bool(self._selected_understanding_video_id())
        )
        page.btn_extract_asr.setEnabled(can)
        self._set_dialogue_mode_enabled(not running)
        if hasattr(page, "btn_cluster_speakers"):
            page.btn_cluster_speakers.setEnabled(can and self._current_video_has_recap_dialogue())
        if hasattr(page, "btn_rename_speakers"):
            page.btn_rename_speakers.setEnabled(
                (not running) and bool(self._current_video_speaker_labels())
            )
        if hasattr(page, "btn_reset_speakers"):
            page.btn_reset_speakers.setEnabled(
                (not running) and bool(self._current_video_speaker_labels())
            )
        if hasattr(page, "btn_export_dialogue_json"):
            page.btn_export_dialogue_json.setEnabled((not running) and self._current_video_has_recap_dialogue())

    def cluster_current_video_speakers(self):
        from src.core.asr.campplus_onnx import resolve_campplus_model_path
        from src.utils import has_ffmpeg

        if self._asr_job_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        page = getattr(self, "understanding_page", None)
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        if not self._current_video_has_recap_dialogue():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_speaker_cluster_empty",
                    "No speech dialogue to cluster. Extract speech first.",
                ),
                kind="warning",
            )
            return
        if not has_ffmpeg():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_asr_missing_ffmpeg",
                    "FFmpeg is required for speech extraction. Configure it in Settings.",
                ),
                kind="warning",
            )
            return
        if not resolve_campplus_model_path():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_speaker_cluster_missing_model",
                    "CAM++ model not found. Put campplus.onnx and campplus.onnx.data in resources/asr.",
                ),
                kind="warning",
            )
            return
        context = getattr(self, "_understanding_video_context", None) or {}
        if str(context.get("video_id") or "") != video_id:
            from src.services.understanding_service import resolve_video_context

            try:
                context = resolve_video_context(video_id, config=load_config(), probe_duration=False)
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:593")
                context = {}
        running_text = self.texts.get("understanding_speaker_cluster_running", "Clustering speakers…")
        if page is not None:
            page.lbl_status.setText(running_text)
            page.progress_bar.setVisible(True)
            page.progress_bar.setValue(5)
            page.btn_stop.setVisible(True)
            page.btn_stop.setEnabled(True)
            if hasattr(page, "btn_stop_asr"):
                page.btn_stop_asr.setVisible(True)
                page.btn_stop_asr.setEnabled(True)
            if hasattr(page, "dialogue_progress_bar"):
                page.dialogue_progress_bar.setVisible(True)
                page.dialogue_progress_bar.setValue(5)
            if hasattr(page, "dialogue_progress_status"):
                page.dialogue_progress_status.set_status_text(running_text)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(running_text)
            page.btn_generate_evidence.setEnabled(False)
            if hasattr(page, "btn_generate_batch"):
                page.btn_generate_batch.setEnabled(False)
            page.scope_combo.setEnabled(False)
            page.video_combo.setEnabled(False)
        if hasattr(page, "btn_extract_asr"):
            page.btn_extract_asr.setEnabled(False)
        self._set_dialogue_mode_enabled(False)
        if hasattr(page, "btn_cluster_speakers"):
            page.btn_cluster_speakers.setEnabled(False)
        if hasattr(page, "btn_rename_speakers"):
            page.btn_rename_speakers.setEnabled(False)
        if hasattr(page, "btn_reset_speakers"):
            page.btn_reset_speakers.setEnabled(False)
        if hasattr(page, "btn_export_dialogue_json"):
            page.btn_export_dialogue_json.setEnabled(False)
        self._sync_recap_export_button(running=True)
        worker = SpeakerClusterWorker(
            video_id,
            video_path=str(context.get("video_path") or ""),
            parent=self,
        )
        self._speaker_cluster_worker = worker

        def _finish(active_worker=worker):
            if getattr(self, "_speaker_cluster_worker", None) is active_worker:
                self._speaker_cluster_worker = None
            if page is not None:
                page.progress_bar.setVisible(False)
                if hasattr(page, "dialogue_progress_bar"):
                    page.dialogue_progress_bar.setVisible(False)
                generating = bool(
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                )
                if not generating:
                    page.btn_stop.setEnabled(False)
                    page.btn_stop.setVisible(False)
                    if hasattr(page, "btn_stop_asr"):
                        page.btn_stop_asr.setEnabled(False)
                        page.btn_stop_asr.setVisible(False)
                    page.btn_generate_evidence.setEnabled(True)
                    if hasattr(page, "btn_generate_batch"):
                        page.btn_generate_batch.setEnabled(True)
                    page.scope_combo.setEnabled(True)
                    page.video_combo.setEnabled(True)
            self._sync_asr_extract_button()
            self._sync_recap_export_button(running=False)
            try:
                active_worker.deleteLater()
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/windows/gui_understanding_asr.py:661")
                pass
            if hasattr(self, "_maybe_close_when_busy_work_stops"):
                self._maybe_close_when_busy_work_stops()

        worker.progress_signal.connect(self._update_understanding_progress)
        worker.finished_signal.connect(self._finish_speaker_cluster)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get("understanding_speaker_cluster_failed", "Speaker clustering failed"),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()

    def _finish_speaker_cluster(self, ok: bool, stopped: bool, payload: object):
        page = getattr(self, "understanding_page", None)
        self._refresh_understanding_dialogue_step()
        if stopped or not ok:
            if page is not None and stopped:
                page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
                if hasattr(page, "dialogue_status"):
                    page.dialogue_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        result = dict(payload or {})
        labeled = int(result.get("labeled") or 0)
        speakers = int(result.get("speakers") or 0)
        skipped = int(result.get("skipped") or 0)
        if labeled <= 0:
            reason = str(result.get("reason") or "")
            if reason == "short":
                message = self.texts.get(
                    "understanding_speaker_cluster_short",
                    "These lines are shorter than about 0.4 seconds, so there is not enough audio to cluster.",
                )
            elif reason == "quiet":
                message = self.texts.get(
                    "understanding_speaker_cluster_quiet",
                    "Those time ranges have almost no speech, so the voices could not be separated.",
                )
            else:
                message = self.texts.get(
                    "understanding_speaker_cluster_none",
                    "No dialogue lines to cluster.",
                )
            if page is not None:
                page.lbl_status.setText(message)
                if hasattr(page, "dialogue_status"):
                    page.dialogue_status.setText(message)
            self.show_info_dialog(self.texts.get("warning_title", "Warning"), message, kind="warning")
            return
        message = self.texts.get(
            "understanding_speaker_cluster_done",
            "Labeled {labeled} cues ({speakers} voices). Left {skipped} manual names unchanged.",
        ).format(labeled=labeled, speakers=speakers, skipped=skipped)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def _current_video_speaker_labels(self) -> list[tuple[str, int]]:
        from src.storage.dialogue_transcript_store import normalize_dialogue_speaker

        page = getattr(self, "understanding_page", None)
        table = getattr(page, "dialogue_table", None) if page is not None else None
        counts: dict[str, int] = {}
        if table is None:
            return []
        for row in range(table.rowCount()):
            item = table.item(row, 1)
            name = normalize_dialogue_speaker(item.text() if item is not None else "")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    def _selected_dialogue_speaker(self) -> str:
        from src.storage.dialogue_transcript_store import normalize_dialogue_speaker

        page = getattr(self, "understanding_page", None)
        table = getattr(page, "dialogue_table", None) if page is not None else None
        if table is None:
            return ""
        row = table.currentRow()
        if row < 0:
            return ""
        item = table.item(row, 1)
        return normalize_dialogue_speaker(item.text() if item is not None else "")

    def rename_current_video_speakers(self):
        from src.services.understanding_dialogue import rename_working_speakers
        from ui.dialogs.rename_speakers import prompt_rename_speakers

        if self._asr_job_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        labels = self._current_video_speaker_labels()
        if not labels:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_speaker_rename_empty",
                    "No named speakers yet. Cluster voices first, or double-click Speaker to name one.",
                ),
                kind="warning",
            )
            return
        picked = prompt_rename_speakers(
            self,
            self.texts,
            labels=labels,
            current=self._selected_dialogue_speaker(),
        )
        if not picked:
            return
        old_speaker, new_speaker = picked
        try:
            updated = rename_working_speakers(
                video_id,
                old_speaker,
                new_speaker,
                config=load_config(),
            )
        except Exception as exc:
            from src.app.logging_utils import note_swallowed
            note_swallowed(exc, 'ui/windows/gui_understanding_asr.py:771')
            self.show_error_dialog(
                self.texts.get("understanding_speaker_rename_failed", "Could not rename speakers"),
                exc,
            )
            return
        self._refresh_understanding_dialogue_step()
        if updated <= 0:
            message = self.texts.get(
                "understanding_speaker_rename_none",
                "No dialogue lines needed renaming.",
            )
            self.show_info_dialog(self.texts.get("warning_title", "Warning"), message, kind="warning")
            return
        message = self.texts.get(
            "understanding_speaker_rename_done",
            'Renamed "{old}" to "{new}" ({count} lines).',
        ).format(old=old_speaker, new=new_speaker, count=updated)
        page = getattr(self, "understanding_page", None)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def reset_current_video_speakers(self):
        from src.services.understanding_dialogue import clear_working_speakers

        if self._asr_job_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        if not self._current_video_speaker_labels():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_speaker_reset_none",
                    "No speaker labels to clear.",
                ),
                kind="warning",
            )
            return
        if not self.show_confirm_dialog(
            self.texts.get("understanding_speaker_reset_title", "Reset speakers"),
            self.texts.get(
                "understanding_speaker_reset_confirm",
                "Clear every speaker label on this video (including manual character names)? You can cluster again afterwards.",
            ),
        ):
            return
        try:
            updated = clear_working_speakers(video_id, config=load_config())
        except Exception as exc:
            from src.app.logging_utils import note_swallowed
            note_swallowed(exc, 'ui/windows/gui_understanding_asr.py:831')
            self.show_error_dialog(
                self.texts.get("understanding_speaker_reset_failed", "Could not reset speakers"),
                exc,
            )
            return
        self._refresh_understanding_dialogue_step()
        if updated <= 0:
            message = self.texts.get(
                "understanding_speaker_reset_none",
                "No speaker labels to clear.",
            )
            self.show_info_dialog(self.texts.get("warning_title", "Warning"), message, kind="warning")
            return
        message = self.texts.get(
            "understanding_speaker_reset_done",
            "Cleared {count} speaker labels.",
        ).format(count=updated)
        page = getattr(self, "understanding_page", None)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def _dialogue_export_video_path(self, record: dict) -> str:
        from src.app.config import load_config
        from src.services.understanding_service import resolve_current_media_path

        stored = str((record or {}).get("video_path") or "")
        context = getattr(self, "_understanding_video_context", None) or {}
        if not stored:
            stored = str(context.get("video_path") or "")
        video_id = str((record or {}).get("video_id") or self._selected_understanding_video_id() or "")
        if hasattr(self, "_current_recap_video_path"):
            current = str(self._current_recap_video_path() or "")
            if current:
                stored = current
        return resolve_current_media_path(video_id, stored=stored, config=load_config())

    def export_current_video_dialogue_json(self):
        from src.app.config import load_config
        from src.services.dialogue_export_service import render_dialogue_srt
        from src.services.subtitle_srt_import import srt_filename_for_video, srt_save_path_for_video
        from src.services.understanding_dialogue import load_working_copy

        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        record = load_working_copy(video_id, config=load_config()) or {}
        cues = list(record.get("cues") or [])
        if not cues:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_export_dialogue_json_empty",
                    "No dialogue on this page yet. Copy it from the subtitle library, or extract subtitles or speech here.",
                ),
                kind="warning",
            )
            return
        video_path = self._dialogue_export_video_path(record)
        filename = srt_filename_for_video(video_path)
        if not filename:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_export_dialogue_srt_unnamed",
                    "This video has no file name, so the SRT cannot match a subtitle-library import.",
                ),
                kind="warning",
            )
            return
        start_dir = os.path.dirname(video_path) if video_path else ""
        suggested = os.path.join(start_dir, filename) if start_dir else filename
        chosen, _selected = QFileDialog.getSaveFileName(
            self,
            self.texts.get("understanding_export_dialogue_json_title", "Export SRT"),
            suggested,
            self.texts.get("import_subtitle_srt_filter", "SRT subtitles (*.srt)"),
        )
        if not chosen:
            return
        path = srt_save_path_for_video(video_path, chosen)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(render_dialogue_srt(cues))
        except Exception as exc:
            from src.app.logging_utils import note_swallowed
            note_swallowed(exc, "ui/windows/gui_understanding_asr.py:export_srt")
            self.show_error_dialog(self.texts.get("details_export_failed", "Export failed."), exc)
            return
        message = self.texts.get("details_export_done", "Exported: {path}").format(path=path)
        page = getattr(self, "understanding_page", None)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "dialogue_status"):
                page.dialogue_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")