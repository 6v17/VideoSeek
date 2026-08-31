"""LLM settings + recap export for the understanding page."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog

from src.app.config import load_config, save_config
from src.services.llm_settings import (
    REMOTE_LLM_MODE_CLOUD,
    REMOTE_LLM_MODE_LOCAL,
    REMOTE_LLM_PRESET_CUSTOM,
    finalize_remote_llm_settings,
    get_remote_llm_api_key_for_preset,
    get_remote_llm_preset_defaults,
    get_remote_llm_settings,
    list_remote_llm_preset_ids,
    normalize_remote_llm_api_keys,
    normalize_remote_llm_provider_mode,
    set_remote_llm_api_key_for_preset,
)
from ui.workers import RecapTimelineWorker, RemoteLlmConnectionTestWorker


class UnderstandingLlmGuiMixin:
    def _llm_form(self):
        dialog = getattr(self, "understanding_services_dialog", None)
        return getattr(dialog, "llm_form", None) if dialog is not None else None

    def _load_llm_settings(self, config=None):
        form = self._llm_form()
        if form is None:
            return
        cfg = config if config is not None else load_config()
        remote_llm = dict(get_remote_llm_settings(cfg))
        self._remote_llm_api_keys = normalize_remote_llm_api_keys(remote_llm.get("api_keys"))
        mode = remote_llm.get("provider_mode", REMOTE_LLM_MODE_CLOUD)
        self._populate_llm_provider_mode_options(mode)
        self._populate_llm_provider_preset_options(mode, remote_llm.get("provider_preset", "deepseek"))
        form.input_remote_llm_base_url.setText(str(remote_llm.get("base_url", "") or ""))
        form.input_remote_llm_model.setText(str(remote_llm.get("model", "") or ""))
        form.input_remote_llm_api_key.setText(
            get_remote_llm_api_key_for_preset(
                remote_llm,
                remote_llm.get("provider_preset", "deepseek"),
                mode=mode,
            )
        )
        self._sync_llm_provider_ui()
        self._remember_llm_ui_selection(form)

    def _llm_provider_mode_label(self, mode: str) -> str:
        if mode == REMOTE_LLM_MODE_CLOUD:
            return self.texts.get("understanding_vlm_provider_mode_cloud", "Cloud API")
        return self.texts.get("understanding_vlm_provider_mode_local", "Local")

    def _llm_provider_preset_label(self, preset_id: str) -> str:
        key = f"understanding_llm_provider_preset_{preset_id}"
        defaults = {
            "deepseek": "DeepSeek",
            "openai": "OpenAI",
            "dashscope": "DashScope (Qwen)",
            "lm_studio": "LM Studio",
            "ollama": "Ollama",
            REMOTE_LLM_PRESET_CUSTOM: "Custom",
        }
        return self.texts.get(key, defaults.get(preset_id, preset_id))

    def _populate_llm_provider_mode_options(self, active_mode=None):
        form = self._llm_form()
        if form is None:
            return
        combo = form.input_llm_provider_mode
        active = normalize_remote_llm_provider_mode(active_mode)
        combo.blockSignals(True)
        combo.clear()
        for mode in (REMOTE_LLM_MODE_LOCAL, REMOTE_LLM_MODE_CLOUD):
            combo.addItem(self._llm_provider_mode_label(mode), mode)
        index = combo.findData(active)
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _populate_llm_provider_preset_options(self, mode, active_preset=None):
        form = self._llm_form()
        if form is None:
            return
        combo = form.input_llm_provider_preset
        normalized_mode = normalize_remote_llm_provider_mode(mode)
        active = str(active_preset or "").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        preset_ids = list_remote_llm_preset_ids(mode=normalized_mode)
        for preset_id in preset_ids:
            combo.addItem(self._llm_provider_preset_label(preset_id), preset_id)
        index = combo.findData(active if active in preset_ids else preset_ids[0])
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _sync_llm_provider_ui(self):
        form = self._llm_form()
        if form is None:
            return
        mode = normalize_remote_llm_provider_mode(form.input_llm_provider_mode.currentData())
        preset_id = str(form.input_llm_provider_preset.currentData() or REMOTE_LLM_PRESET_CUSTOM)
        is_cloud = mode == REMOTE_LLM_MODE_CLOUD
        is_custom = preset_id == REMOTE_LLM_PRESET_CUSTOM
        preset_defaults = get_remote_llm_preset_defaults(preset_id) if not is_custom else {}
        form.label_remote_llm_api_key.setVisible(is_cloud)
        form.input_remote_llm_api_key.setVisible(is_cloud)
        form.label_remote_llm_base_url.setVisible(is_custom)
        form.input_remote_llm_base_url.setVisible(is_custom)
        form.label_remote_llm_model.setVisible(True)
        form.input_remote_llm_model.setVisible(True)
        if is_custom:
            form.hint_llm_preset_summary.hide()
            return
        if preset_defaults.get("base_url"):
            form.input_remote_llm_base_url.setText(str(preset_defaults.get("base_url") or ""))
        current = str(form.input_remote_llm_model.text() or "").strip()
        model = current or str(preset_defaults.get("model", "") or "").strip()
        if model and not current:
            form.input_remote_llm_model.setText(model)
        if model:
            form.hint_llm_preset_summary.setText(
                self.texts.get(
                    "understanding_llm_preset_model_hint",
                    "Preset {preset} uses {model}. Change the id if your account list differs (use a text model, not vision).",
                ).format(preset=self._llm_provider_preset_label(preset_id), model=model)
            )
            form.hint_llm_preset_summary.show()
        else:
            form.hint_llm_preset_summary.hide()

    def _remember_llm_ui_selection(self, form):
        if form is None:
            return
        self._llm_ui_mode = normalize_remote_llm_provider_mode(form.input_llm_provider_mode.currentData())
        self._llm_ui_preset = str(form.input_llm_provider_preset.currentData() or REMOTE_LLM_PRESET_CUSTOM)

    def _commit_llm_api_key_draft(self, form):
        if form is None:
            return
        if not hasattr(self, "_remote_llm_api_keys") or not isinstance(self._remote_llm_api_keys, dict):
            self._remote_llm_api_keys = {}
        mode = normalize_remote_llm_provider_mode(
            getattr(self, "_llm_ui_mode", None) or form.input_llm_provider_mode.currentData()
        )
        preset_id = str(getattr(self, "_llm_ui_preset", "") or form.input_llm_provider_preset.currentData() or "")
        self._remote_llm_api_keys = set_remote_llm_api_key_for_preset(
            self._remote_llm_api_keys,
            preset_id,
            form.input_remote_llm_api_key.text(),
            mode=mode,
        )

    def _load_llm_api_key_for_preset(self, form, preset_id: str, mode: str):
        if form is None:
            return
        if not hasattr(self, "_remote_llm_api_keys") or not isinstance(self._remote_llm_api_keys, dict):
            self._remote_llm_api_keys = {}
        draft = {"api_keys": self._remote_llm_api_keys, "provider_preset": preset_id, "provider_mode": mode}
        form.input_remote_llm_api_key.setText(get_remote_llm_api_key_for_preset(draft, preset_id, mode=mode))

    def _resolve_llm_fields_for_save(self, form):
        provider_mode = normalize_remote_llm_provider_mode(form.input_llm_provider_mode.currentData())
        provider_preset = str(form.input_llm_provider_preset.currentData() or REMOTE_LLM_PRESET_CUSTOM)
        if provider_preset != REMOTE_LLM_PRESET_CUSTOM:
            defaults = get_remote_llm_preset_defaults(provider_preset)
            base_url = str(defaults.get("base_url", "") or form.input_remote_llm_base_url.text() or "").strip()
            model = form.input_remote_llm_model.text().strip() or str(defaults.get("model", "") or "").strip()
        else:
            base_url = form.input_remote_llm_base_url.text().strip()
            model = form.input_remote_llm_model.text().strip()
        return provider_mode, provider_preset, base_url, model

    def _commit_llm_settings_to_understanding(self, understanding: dict) -> None:
        form = self._llm_form()
        if form is None:
            return
        self._commit_llm_api_key_draft(form)
        provider_mode, provider_preset, base_url, model = self._resolve_llm_fields_for_save(form)
        remote_llm = dict(understanding.get("remote_llm") or {})
        remote_llm["provider_mode"] = provider_mode
        remote_llm["provider_preset"] = provider_preset
        remote_llm["base_url"] = base_url
        remote_llm["model"] = model
        remote_llm["api_keys"] = dict(getattr(self, "_remote_llm_api_keys", {}) or {})
        understanding["remote_llm"] = finalize_remote_llm_settings(remote_llm)

    def _apply_llm_provider_preset(self, preset_id: str):
        form = self._llm_form()
        if form is None:
            return
        preset_id = str(preset_id or "").strip().lower()
        mode = normalize_remote_llm_provider_mode(form.input_llm_provider_mode.currentData())
        defaults = get_remote_llm_preset_defaults(preset_id)
        if preset_id != REMOTE_LLM_PRESET_CUSTOM and defaults:
            form.input_remote_llm_base_url.setText(defaults.get("base_url", ""))
            form.input_remote_llm_model.setText(defaults.get("model", ""))
        self._sync_llm_provider_ui()
        if mode == REMOTE_LLM_MODE_CLOUD:
            self._load_llm_api_key_for_preset(form, preset_id, mode)
        else:
            form.input_remote_llm_api_key.setText("")

    def _on_llm_provider_mode_changed(self, _index=None):
        form = self._llm_form()
        if form is None:
            return
        self._commit_llm_api_key_draft(form)
        mode = normalize_remote_llm_provider_mode(form.input_llm_provider_mode.currentData())
        default_preset = "deepseek" if mode == REMOTE_LLM_MODE_CLOUD else "lm_studio"
        self._populate_llm_provider_preset_options(mode, default_preset)
        self._apply_llm_provider_preset(default_preset)
        self._remember_llm_ui_selection(form)

    def _on_llm_provider_preset_changed(self, _index=None):
        form = self._llm_form()
        if form is None:
            return
        self._commit_llm_api_key_draft(form)
        preset_id = str(form.input_llm_provider_preset.currentData() or REMOTE_LLM_PRESET_CUSTOM)
        self._apply_llm_provider_preset(preset_id)
        self._remember_llm_ui_selection(form)

    def test_understanding_llm_connection(self):
        form = self._llm_form()
        page = self._understanding_config_widgets()
        if form is None or page is None:
            return
        if getattr(self, "_llm_connection_test_worker", None) is not None:
            return
        self._commit_llm_api_key_draft(form)
        provider_mode, provider_preset, base_url, model = self._resolve_llm_fields_for_save(form)
        draft = {
            "provider_mode": provider_mode,
            "provider_preset": provider_preset,
            "base_url": base_url,
            "model": model,
            "api_keys": dict(getattr(self, "_remote_llm_api_keys", {}) or {}),
        }
        form.hint_llm_status.setText(self.texts.get("understanding_test_vlm_testing", "Testing…"))
        worker = RemoteLlmConnectionTestWorker(draft, timeout_sec=8.0, parent=self)
        self._llm_connection_test_worker = worker
        page.btn_test_vlm_connection.setEnabled(False)

        def _finish(active_worker=worker):
            if getattr(self, "_llm_connection_test_worker", None) is active_worker:
                self._llm_connection_test_worker = None
            page.btn_test_vlm_connection.setEnabled(True)
            try:
                active_worker.deleteLater()
            except Exception:
                pass

        worker.result_ready.connect(lambda probe: self._finish_llm_connection_test(probe, form))
        worker.error_signal.connect(lambda message: self._fail_llm_connection_test(message, form))
        worker.finished.connect(_finish)
        worker.start()

    def _finish_llm_connection_test(self, probe, form):
        from src.services.llm_settings import pick_available_text_llm_model

        probe = dict(probe or {})
        configured = str(probe.get("configured_model", "") or "").strip()
        if probe.get("reachable") and not probe.get("model_available"):
            suggested = pick_available_text_llm_model(configured, probe.get("available_models") or [])
            if suggested and suggested != configured:
                form.input_remote_llm_model.setText(suggested)
                self._sync_llm_provider_ui()
                message = self.texts.get(
                    "understanding_test_llm_model_switched",
                    "Connected. {old} is not on this account; filled in {model}. Save, then test again.",
                ).format(old=configured or "?", model=suggested)
                form.hint_llm_status.setText(message)
                self.show_info_dialog(
                    self.texts.get("understanding_test_vlm_title", "Connection test"),
                    message,
                    kind="warning",
                )
                return
        message = self._format_vlm_probe_status(probe)
        form.hint_llm_status.setText(message)
        if probe.get("reachable") and probe.get("model_available"):
            live = str(probe.get("configured_model") or "").strip()
            if live:
                form.input_remote_llm_model.setText(live)
                self._sync_llm_provider_ui()
            self.show_info_dialog(
                self.texts.get("understanding_test_vlm_title", "Connection test"),
                message,
                kind="success",
            )
        elif probe.get("error_code") != "cloud_api_key_required":
            self.show_error_dialog(message)

    def _fail_llm_connection_test(self, message, form):
        text = self.texts.get("understanding_test_vlm_failed", "Connection failed: {error}").format(
            error=str(message or "unknown error")
        )
        form.hint_llm_status.setText(text)
        self.show_error_dialog(text)

    def export_current_video_recap(self):
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION
        from src.services.understanding_service import load_evidence_bundle, resolve_current_media_path

        if getattr(self, "_recap_worker", None) is not None:
            return
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        evidence = load_evidence_bundle(video_id, config=load_config(), mode=UNDERSTANDING_MODE_MOTION)
        if not evidence:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_export_recap_empty", "Generate motion notes first."),
                kind="warning",
            )
            return
        llm = get_remote_llm_settings(load_config())
        if not str(llm.get("model") or "").strip():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_export_recap_llm_missing", "Configure LLM first."),
                kind="warning",
            )
            return
        if not self._current_video_has_recap_dialogue():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_export_recap_dialogue_missing",
                    "Extract speech ASR here first. Recap does not use hard-sub OCR.",
                ),
                kind="warning",
            )
            return
        stored = str((evidence.get("video") or {}).get("video_path") or "")
        video_path = resolve_current_media_path(video_id, stored=stored, config=load_config())
        dest = os.path.dirname(video_path) or ""
        if not dest:
            dest = QFileDialog.getExistingDirectory(
                self,
                self.texts.get("understanding_export_recap_title", "Save recap cuts"),
                "",
            )
        if not dest:
            return
        page = self.understanding_page
        start_from = "plan"
        if hasattr(page, "input_recap_start"):
            start_from = str(page.input_recap_start.currentData() or "plan")
        if start_from == "match" and not self._current_video_has_recap_beats():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_beats_missing",
                    "No story plan yet. Start from stage 1.",
                ),
                kind="warning",
            )
            return
        if start_from == "captions" and not self._current_video_has_recap_cuts():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_cuts_missing",
                    "No cut list yet. Start from stage 1 or 2.",
                ),
                kind="warning",
            )
            return
        start_status = {
            "match": "understanding_export_recap_matching",
            "captions": "understanding_export_recap_captions",
        }.get(start_from, "understanding_export_recap_planning")
        page.lbl_status.setText(self.texts.get(start_status, "Generating recap…"))
        self._sync_recap_export_button(running=True)
        if hasattr(self, "_sync_asr_extract_button"):
            self._sync_asr_extract_button()
        page.btn_stop.setVisible(True)
        page.btn_stop.setEnabled(True)
        page.progress_bar.setVisible(True)
        page.progress_bar.setValue(8)
        if hasattr(page, "recap_progress_bar"):
            page.recap_progress_bar.setVisible(True)
            page.recap_progress_bar.setValue(8)
        if hasattr(page, "recap_progress_status"):
            page.recap_progress_status.set_status_text(
                self.texts.get(start_status, "Generating recap…")
            )
        system_prompt = ""
        plan_prompt = ""
        caption_prompt = ""
        if hasattr(page, "input_recap_prompt"):
            system_prompt = str(page.input_recap_prompt.toPlainText() or "")
        if hasattr(page, "input_recap_plan_prompt"):
            plan_prompt = str(page.input_recap_plan_prompt.toPlainText() or "")
        if hasattr(page, "input_recap_caption_prompt"):
            caption_prompt = str(page.input_recap_caption_prompt.toPlainText() or "")
        worker = RecapTimelineWorker(
            video_id,
            dest,
            system_prompt=system_prompt,
            plan_prompt=plan_prompt,
            caption_prompt=caption_prompt,
            start_from=start_from,
            parent=self,
        )
        self._recap_worker = worker

        def _on_progress(pct, text, active_page=page):
            label = str(text or "")
            active_page.lbl_status.setText(label)
            active_page.progress_bar.setVisible(True)
            active_page.progress_bar.setValue(max(0, min(100, int(pct))))
            if hasattr(active_page, "recap_progress_bar"):
                active_page.recap_progress_bar.setVisible(True)
                active_page.recap_progress_bar.setValue(max(0, min(100, int(pct))))
            if hasattr(active_page, "recap_progress_status"):
                active_page.recap_progress_status.set_status_text(label)

        def _finish(active_worker=worker, active_page=page):
            if getattr(self, "_recap_worker", None) is active_worker:
                self._recap_worker = None
            if hasattr(active_page, "input_recap_prompt"):
                active_page.input_recap_prompt.setEnabled(True)
            if hasattr(active_page, "input_recap_plan_prompt"):
                active_page.input_recap_plan_prompt.setEnabled(True)
            if hasattr(active_page, "input_recap_caption_prompt"):
                active_page.input_recap_caption_prompt.setEnabled(True)
            if hasattr(active_page, "btn_reset_recap_prompt"):
                active_page.btn_reset_recap_prompt.setEnabled(True)
            if hasattr(active_page, "input_recap_start"):
                active_page.input_recap_start.setEnabled(True)
            if hasattr(active_page, "recap_prompt_tabs"):
                active_page.recap_prompt_tabs.setEnabled(True)
            active_page.progress_bar.setVisible(False)
            if hasattr(active_page, "recap_progress_bar"):
                active_page.recap_progress_bar.setVisible(False)
            if not (
                getattr(self, "understanding_controller", None)
                and self.understanding_controller.is_running()
            ) and getattr(self, "_asr_worker", None) is None and getattr(
                self, "_speaker_cluster_worker", None
            ) is None:
                active_page.btn_stop.setEnabled(False)
                active_page.btn_stop.setVisible(False)
            self._sync_recap_export_button(running=False)
            if hasattr(self, "_sync_asr_extract_button"):
                self._sync_asr_extract_button()
            if hasattr(self, "_sync_tray_stop_action"):
                self._sync_tray_stop_action()
            try:
                active_worker.deleteLater()
            except Exception:
                pass

        worker.progress_signal.connect(_on_progress)
        worker.finished_signal.connect(self._finish_recap_export)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get("understanding_export_recap_failed", "Recap export failed"),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()

    def _finish_recap_export(self, ok: bool, stopped: bool, payload: object):
        if stopped or not ok:
            return
        result = dict(payload or {})
        message = self.texts.get(
            "understanding_export_recap_done",
            "Generated {count} shots / {duration:.0f}s\n{path}\nThen export a Jianying draft or FCPXML.",
        ).format(
            count=int(result.get("clip_count") or 0),
            duration=float(result.get("duration_sec") or 0.0),
            path=str(result.get("cuts_path") or result.get("srt_path") or ""),
        )
        self.understanding_page.lbl_status.setText(message.split("\n", 1)[0])
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")
        self._sync_recap_export_button()

    def _current_recap_video_path(self) -> str:
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION
        from src.services.understanding_service import load_evidence_bundle, resolve_current_media_path

        video_id = self._selected_understanding_video_id()
        if not video_id:
            return ""
        evidence = load_evidence_bundle(video_id, config=load_config(), mode=UNDERSTANDING_MODE_MOTION)
        stored = str(((evidence or {}).get("video") or {}).get("video_path") or "")
        return resolve_current_media_path(video_id, stored=stored, config=load_config())

    def _load_current_recap_cuts(self):
        from src.services.recap_service import load_recap_cuts

        video_path = self._current_recap_video_path()
        if not video_path:
            return None
        return load_recap_cuts(video_path, video_id=self._selected_understanding_video_id())

    def export_current_recap_jianying(self):
        from src.services.jianying_draft_service import (
            JianyingDraftError,
            export_recap_to_jianying_draft,
            is_jianying_draft_support_available,
            resolve_jianying_drafts_dir,
        )
        from src.utils import open_folder_in_explorer

        title = self.texts.get("understanding_recap_jianying", "Generate Jianying draft")
        if not is_jianying_draft_support_available():
            self.show_error_dialog(
                title,
                self.texts.get(
                    "shot_list_export_jianying_missing",
                    "pyJianYingDraft is not installed.",
                ),
            )
            return
        payload = self._load_current_recap_cuts()
        if not payload:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_recap_export_missing", "Generate recap cuts first."),
                kind="warning",
            )
            return
        video_path = str(payload.get("video") or self._current_recap_video_path() or "")
        from src.services.understanding_service import resolve_current_media_path

        video_path = resolve_current_media_path(
            self._selected_understanding_video_id(),
            stored=video_path,
            config=load_config(),
        )
        if not video_path or not os.path.isfile(video_path):
            self.show_error_dialog(title, f"找不到原片：{video_path or '(空路径)'}")
            return
        drafts_dir = resolve_jianying_drafts_dir()
        if not drafts_dir or not os.path.isdir(drafts_dir):
            drafts_dir = QFileDialog.getExistingDirectory(
                self,
                self.texts.get("shot_list_export_jianying_pick_dir", "Select Jianying drafts folder"),
            )
        if not drafts_dir:
            return
        try:
            result = export_recap_to_jianying_draft(
                list(payload.get("clips") or []),
                video_path=video_path,
                drafts_dir=drafts_dir,
                title=str(payload.get("title") or ""),
                fps=float(payload.get("fps") or 30),
            )
        except JianyingDraftError as exc:
            self.show_error_dialog(title, exc.detail or exc.summary)
            return
        except Exception as exc:
            self.show_error_dialog(title, str(exc))
            return
        message = self.texts.get(
            "understanding_recap_jianying_done",
            "Jianying draft “{name}”\n{path}\nClose Jianying first, then open this draft.",
        ).format(name=result.get("draft_name") or "", path=result.get("draft_path") or "")
        self.understanding_page.lbl_status.setText(message.split("\n", 1)[0])
        self.show_info_dialog(title, message, kind="success")
        draft_path = str(result.get("draft_path") or "")
        if draft_path and os.path.isdir(draft_path):
            open_folder_in_explorer(draft_path)

    def export_current_recap_fcpxml(self):
        from src.services.recap_service import export_saved_recap_fcpxml

        payload = self._load_current_recap_cuts()
        if not payload:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_recap_export_missing", "Generate recap cuts first."),
                kind="warning",
            )
            return
        video_path = str(payload.get("video") or self._current_recap_video_path() or "")
        from src.services.understanding_service import resolve_current_media_path

        video_path = resolve_current_media_path(
            self._selected_understanding_video_id(),
            stored=video_path,
            config=load_config(),
        )
        stem = os.path.splitext(os.path.basename(video_path or "recap"))[0] or "recap"
        dest, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("understanding_recap_fcpxml", "Export FCPXML"),
            f"{stem}_recap.fcpxml",
            self.texts.get("understanding_recap_fcpxml_filter", "FCPXML (*.fcpxml)"),
        )
        if not dest:
            return
        try:
            written = export_saved_recap_fcpxml(payload, dest, video_path=video_path)
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("understanding_recap_fcpxml", "Export FCPXML"),
                str(exc),
            )
            return
        message = self.texts.get(
            "understanding_recap_fcpxml_done",
            "FCPXML exported:\n{path}",
        ).format(path=str(written))
        self.understanding_page.lbl_status.setText(message.split("\n", 1)[0])
        self.show_info_dialog(
            self.texts.get("understanding_recap_fcpxml", "Export FCPXML"),
            message,
            kind="success",
        )

    def reset_recap_prompt(self):
        from src.services.recap_service import RECAP_CAPTION_SYSTEM, RECAP_PLAN_SYSTEM, RECAP_SYSTEM

        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "input_recap_prompt"):
            return
        index = 1
        if hasattr(page, "recap_prompt_tabs"):
            index = int(page.recap_prompt_tabs.currentIndex())
        editors = (
            (getattr(page, "input_recap_plan_prompt", None), RECAP_PLAN_SYSTEM),
            (page.input_recap_prompt, RECAP_SYSTEM),
            (getattr(page, "input_recap_caption_prompt", None), RECAP_CAPTION_SYSTEM),
        )
        if index < 0 or index >= len(editors):
            index = 1
        editor, default = editors[index]
        if editor is not None:
            editor.setPlainText(default)

    def _ensure_recap_prompt_default(self):
        from src.services.recap_service import RECAP_CAPTION_SYSTEM, RECAP_GAP_SYSTEM, RECAP_PLAN_SYSTEM, RECAP_SYSTEM

        page = getattr(self, "understanding_page", None)
        if page is None:
            return
        caption_editor = getattr(page, "input_recap_caption_prompt", None)
        pairs = (
            (getattr(page, "input_recap_plan_prompt", None), RECAP_PLAN_SYSTEM),
            (getattr(page, "input_recap_prompt", None), RECAP_SYSTEM),
            (caption_editor, RECAP_CAPTION_SYSTEM),
        )
        for editor, default in pairs:
            if editor is None:
                continue
            body = str(editor.toPlainText() or "").strip()
            if not body or (
                editor is caption_editor and body == str(RECAP_GAP_SYSTEM).strip()
            ):
                editor.setPlainText(default)

    def _populate_recap_start_options(self, active=None):
        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "input_recap_start"):
            return
        combo = page.input_recap_start
        current = str(active or combo.currentData() or "plan")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.texts.get("understanding_recap_start_plan", "Stage 1"), "plan")
        combo.addItem(self.texts.get("understanding_recap_start_match", "Stage 2"), "match")
        combo.addItem(self.texts.get("understanding_recap_start_captions", "Stage 3"), "captions")
        index = combo.findData(current)
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)
