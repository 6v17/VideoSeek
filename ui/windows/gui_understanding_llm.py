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
            "siliconflow": "SiliconFlow",
            "moonshot": "Moonshot (Kimi)",
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
                    "Preset {preset}: {model} via {base_url}. Change the id if your account list differs (text model, not vision).",
                ).format(
                    preset=self._llm_provider_preset_label(preset_id),
                    model=model,
                    base_url=str(preset_defaults.get("base_url", "") or form.input_remote_llm_base_url.text() or "—"),
                )
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
        from ui.widgets.understanding_form_common import set_status_hint

        set_status_hint(
            form.hint_llm_status,
            self.texts.get("understanding_test_llm_testing", "Testing language model…"),
            state="neutral",
        )
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
        from ui.widgets.understanding_form_common import set_status_hint

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
                set_status_hint(form.hint_llm_status, message, state="warn")
                self.show_info_dialog(
                    self.texts.get("understanding_test_vlm_title", "Connection test"),
                    message,
                    kind="warning",
                )
                return
        message = self._format_vlm_probe_status(probe)
        set_status_hint(form.hint_llm_status, message, state=self._probe_status_state(probe))
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
        from ui.widgets.understanding_form_common import set_status_hint

        text = self.texts.get("understanding_test_vlm_failed", "Connection failed: {error}").format(
            error=str(message or "unknown error")
        )
        set_status_hint(form.hint_llm_status, text, state="error")
        self.show_error_dialog(text)

    def export_current_video_recap(self, start_from: str = "plan"):
        if getattr(self, "_recap_worker", None) is not None:
            return
        if not isinstance(start_from, str):
            start_from = "plan"
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
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
        video_path = self._current_recap_video_path()
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
        if start_from in {"plan", "plan_only"}:
            from src.services.recap_service import list_speech_dialogue_cues, recap_speaker_stats

            speaker_stats = recap_speaker_stats(
                list_speech_dialogue_cues(video_id, config=load_config())
            )
            unnamed = int(speaker_stats.get("unnamed") or 0)
            if unnamed > 0 and not self.show_confirm_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_speakers_unnamed_confirm",
                    "{count} dialogue lines are still unnamed. Continue anyway?",
                ).format(count=unnamed),
                confirm_text=self.texts.get("understanding_recap_speakers_continue", "Continue"),
            ):
                return
        if start_from in {"match", "match_only"} and not self._current_video_has_recap_beats():
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
            "match_only": "understanding_export_recap_matching",
            "captions": "understanding_export_recap_captions",
        }.get(start_from, "understanding_export_recap_planning")
        page.lbl_status.setText(self.texts.get(start_status, "Generating recap…"))
        self._sync_recap_export_button(running=True)
        if hasattr(self, "_sync_asr_extract_button"):
            self._sync_asr_extract_button()
        from contextlib import nullcontext

        freeze_cm = (
            self._freeze_understanding_page_scroll()
            if hasattr(self, "_freeze_understanding_page_scroll")
            else nullcontext()
        )
        with freeze_cm:
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
        polish_prompt = ""
        if hasattr(page, "input_recap_prompt"):
            system_prompt = str(page.input_recap_prompt.toPlainText() or "")
        if hasattr(page, "input_recap_plan_prompt"):
            plan_prompt = str(page.input_recap_plan_prompt.toPlainText() or "")
        if hasattr(page, "input_recap_caption_prompt"):
            caption_prompt = str(page.input_recap_caption_prompt.toPlainText() or "")
        if hasattr(page, "input_recap_polish_prompt"):
            polish_prompt = str(page.input_recap_polish_prompt.toPlainText() or "")
        self._recap_motion_timeline_shown = False
        if hasattr(self, "_prepare_understanding_timeline_for_generation"):
            self._prepare_understanding_timeline_for_generation()
            page.chunk_timeline.set_generating_index(-1)
        worker = RecapTimelineWorker(
            video_id,
            dest,
            system_prompt=system_prompt,
            plan_prompt=plan_prompt,
            caption_prompt=caption_prompt,
            polish_prompt=polish_prompt,
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
            if hasattr(active_page, "input_recap_polish_prompt"):
                active_page.input_recap_polish_prompt.setEnabled(True)
            if hasattr(active_page, "btn_reset_recap_prompt"):
                active_page.btn_reset_recap_prompt.setEnabled(True)
            if hasattr(active_page, "chunk_timeline"):
                active_page.chunk_timeline.set_generating_index(-1)
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

        def _on_motion_chunk(index, total, payload):
            self._handle_recap_motion_chunk(index, total, payload)

        worker.progress_signal.connect(_on_progress)
        worker.chunk_completed.connect(_on_motion_chunk)
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
        stage = str(result.get("stage") or "")
        if stage == "plan" and not result.get("cuts_path"):
            message = self.texts.get(
                "understanding_export_recap_plan_done",
                "Saved plan with {count} beats / target {duration:.0f}s\n{path}",
            ).format(
                count=int(result.get("beat_count") or result.get("clip_count") or 0)
                or self._count_saved_recap_beats(),
                duration=float(result.get("duration_sec") or 0.0),
                path=str(result.get("beats_path") or ""),
            )
        elif stage == "match":
            message = self.texts.get(
                "understanding_export_recap_match_done",
                "Matched {count} shots / {duration:.0f}s\n{path}\nThen pack captions, or export a Jianying draft / FCPXML.",
            ).format(
                count=int(result.get("clip_count") or 0),
                duration=float(result.get("duration_sec") or 0.0),
                path=str(result.get("cuts_path") or ""),
            )
        else:
            message = self.texts.get(
                "understanding_export_recap_done",
                "Generated {count} shots / {duration:.0f}s\n{path}\nThen export a Jianying draft or FCPXML.",
            ).format(
                count=int(result.get("clip_count") or 0),
                duration=float(result.get("duration_sec") or 0.0),
                path=str(result.get("cuts_path") or result.get("srt_path") or ""),
            )
        warn_lines = []
        needed = int(result.get("motion_needed") or 0)
        filled = int(result.get("motion_filled") or 0)
        if result.get("motion_checked"):
            if needed > 0:
                warn_lines.append(
                    self.texts.get(
                        "understanding_export_recap_motion_filled",
                        "Filled change notes on {filled}/{needed} beat-window segments before matching.",
                    ).format(filled=filled, needed=needed)
                )
            else:
                warn_lines.append(
                    self.texts.get(
                        "understanding_export_recap_motion_none",
                        "No beat-window change notes were needed before matching.",
                    )
                )
        for key in result.get("warnings") or []:
            line = str(self.texts.get(str(key), "") or "").strip() or str(key).strip()
            if line:
                warn_lines.append(line)
        if warn_lines:
            message = message + "\n" + "\n".join(warn_lines)
        self.understanding_page.lbl_status.setText(
            (message.split("\n", 1)[0] + (" · " + warn_lines[0] if warn_lines else ""))
        )
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")
        self._sync_recap_export_button()
        if stage == "plan" and not result.get("cuts_path"):
            self.edit_current_recap_beats()
        else:
            self._refresh_recap_review_panel()

    def _count_saved_recap_beats(self) -> int:
        from src.services.recap_service import load_recap_beats

        video_path = self._current_recap_video_path()
        if not video_path:
            return 0
        saved = load_recap_beats(video_path, video_id=self._selected_understanding_video_id()) or {}
        return len(list(saved.get("beats") or []))

    def edit_current_recap_beats(self):
        from src.services.recap_service import load_recap_beats, recap_target_sec, save_recap_plan_edits
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION
        from src.services.understanding_service import load_evidence_bundle
        from ui.dialogs.recap_beats import RecapBeatsDialog

        video_id = self._selected_understanding_video_id()
        video_path = self._current_recap_video_path()
        if not video_id or not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        saved = load_recap_beats(video_path, video_id=video_id)
        if not saved:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_beats_missing",
                    "No story plan yet. Start from stage 1.",
                ),
                kind="warning",
            )
            return
        evidence = load_evidence_bundle(video_id, config=load_config(), mode=UNDERSTANDING_MODE_MOTION) or {}
        duration = float(((evidence.get("video") or {}).get("duration_sec") or saved.get("duration_sec") or 0.0))
        target = float(saved.get("target_sec") or recap_target_sec(duration))
        dialog = RecapBeatsDialog(
            self,
            texts=self.texts,
            title=str(saved.get("title") or ""),
            beats=list(saved.get("beats") or []),
            people=list(saved.get("people") or []),
            target_sec=target,
        )
        if dialog.exec() != RecapBeatsDialog.DialogCode.Accepted:
            return
        payload = dialog.result_payload() or {}
        try:
            written = save_recap_plan_edits(
                video_path,
                video_id=video_id,
                title=str(payload.get("title") or saved.get("title") or ""),
                beats=list(payload.get("beats") or []),
                people=list(payload.get("people") or []),
                duration_sec=duration,
                target_sec=target,
            )
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("understanding_export_recap_failed", "Recap export failed"),
                exc,
            )
            return
        count = len(list(payload.get("beats") or []))
        message = self.texts.get(
            "understanding_recap_edit_saved",
            "Saved {count} beats.",
        ).format(count=count)
        self.understanding_page.lbl_status.setText(f"{message} {written.name}")
        self._sync_recap_export_button()

    def _current_recap_video_path(self) -> str:
        from src.services.understanding_resource_service import UNDERSTANDING_MODE_MOTION
        from src.services.understanding_service import load_evidence_bundle, resolve_current_media_path

        video_id = self._selected_understanding_video_id()
        if not video_id:
            return ""
        evidence = load_evidence_bundle(video_id, config=load_config(), mode=UNDERSTANDING_MODE_MOTION) or {}
        stored = str(((evidence or {}).get("video") or {}).get("video_path") or "")
        return resolve_current_media_path(video_id, stored=stored, config=load_config())

    def _load_current_recap_cuts(self):
        from src.services.recap_service import load_recap_cuts

        video_path = self._current_recap_video_path()
        if not video_path:
            return None
        return load_recap_cuts(video_path, video_id=self._selected_understanding_video_id())

    def _recap_review_scroll_bars(self):
        tree = self._recap_review_tree()
        if tree is None:
            return None, None
        return tree.verticalScrollBar(), tree.horizontalScrollBar()

    def _capture_recap_review_scroll(self) -> tuple[int, int]:
        vbar, hbar = self._recap_review_scroll_bars()
        return (
            int(vbar.value()) if vbar is not None else 0,
            int(hbar.value()) if hbar is not None else 0,
        )

    def _restore_recap_review_scroll(self, vertical: int, horizontal: int) -> None:
        vbar, hbar = self._recap_review_scroll_bars()
        if vbar is not None:
            vbar.setValue(int(vertical))
        if hbar is not None:
            hbar.setValue(int(horizontal))

    def _stable_recap_review_mutation(self, mutate) -> None:
        """Run refresh/select without yanking the page or the review tree."""
        from contextlib import nullcontext

        from PySide6.QtCore import QTimer

        freeze = getattr(self, "_freeze_understanding_page_scroll", None)
        page_cm = freeze() if callable(freeze) else nullcontext()
        vpos, hpos = self._capture_recap_review_scroll()
        with page_cm:
            mutate()
            self._restore_recap_review_scroll(vpos, hpos)
            QTimer.singleShot(0, lambda: self._restore_recap_review_scroll(vpos, hpos))

    def _refresh_recap_review_panel(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QTreeWidgetItem

        from src.services.recap_service import (
            format_recap_clock_range,
            group_recap_vo_units,
            load_recap_beats,
        )

        page = getattr(self, "understanding_page", None)
        tree = getattr(page, "recap_review_tree", None) if page is not None else None
        if tree is None and page is not None:
            tree = getattr(page, "recap_review_table", None)
        if page is None or tree is None:
            return
        vpos, hpos = self._capture_recap_review_scroll()
        panel = getattr(page, "recap_review_panel", None)
        payload = self._load_current_recap_cuts()
        clips = list((payload or {}).get("clips") or [])
        show = bool(clips)
        if panel is not None:
            panel.setVisible(show)
        else:
            for name in (
                "recap_review_title",
                "recap_review_hint",
                "recap_review_status",
                "recap_review_detail",
                "recap_review_action_bar",
            ):
                widget = getattr(page, name, None)
                if widget is not None:
                    widget.setVisible(show)
            tree.setVisible(show)
        if not show:
            tree.clear()
            if hasattr(page, "recap_review_detail"):
                page.recap_review_detail.setText("")
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(
                    self.texts.get(
                        "understanding_recap_review_empty",
                        "No shot list yet. Run Match shots or one-click recap first.",
                    )
                )
            self._sync_recap_review_rewrite_button()
            return

        video_path = self._current_recap_video_path()
        beats_payload = (
            load_recap_beats(video_path, video_id=self._selected_understanding_video_id()) or {}
        )
        beats = list(beats_payload.get("beats") or [])
        units = group_recap_vo_units(clips, beats=beats)
        empty_label = self.texts.get("understanding_recap_review_flag_empty_vo", "no VO")
        short_label = self.texts.get("understanding_recap_review_flag_underfill", "short VO")
        tree.blockSignals(True)
        tree.setUpdatesEnabled(False)
        try:
            tree.clear()
            for unit in units:
                unit_index = int(unit.get("unit_index") or 0)
                vo = str(unit.get("vo") or "").strip()
                beat_id = unit.get("beat_id")
                picture = float(unit.get("picture_sec") or 0.0)
                speak = float(unit.get("speak_sec") or 0.0)
                shortfall = float(unit.get("shortfall_sec") or 0.0)
                status_parts: list[str] = []
                if not vo:
                    status_parts.append(empty_label)
                elif shortfall > 0.35:
                    status_parts.append(short_label)
                label = self.texts.get(
                    "understanding_recap_review_unit_label",
                    "Unit {n} · VO {sec:.1f}s",
                ).format(n=unit_index + 1, sec=speak)
                if beat_id:
                    label = f"{label} · #{beat_id}"
                parent = QTreeWidgetItem(
                    [
                        label,
                        format_recap_clock_range(
                            float(unit.get("tl_in") or 0.0),
                            float(unit.get("tl_out") or 0.0),
                        ),
                        format_recap_clock_range(
                            float(unit.get("src_in") or 0.0),
                            float(unit.get("src_out") or 0.0),
                        ),
                        vo or "—",
                    ]
                )
                unit_payload = {
                    "kind": "unit",
                    "unit_index": unit_index,
                    "clip_indices": list(unit.get("clip_indices") or []),
                    "beat_id": beat_id,
                    "event": str(unit.get("event") or "").strip(),
                    "vo": vo,
                    "src_in": float(unit.get("src_in") or 0.0),
                    "src_out": float(unit.get("src_out") or 0.0),
                    "tl_in": float(unit.get("tl_in") or 0.0),
                    "tl_out": float(unit.get("tl_out") or 0.0),
                    "picture_sec": picture,
                    "speak_sec": speak,
                    "shortfall_sec": shortfall,
                    "shot_count": len(list(unit.get("shots") or [])),
                    "status": " · ".join(status_parts) if status_parts else "OK",
                }
                parent.setData(0, Qt.ItemDataRole.UserRole, unit_payload)
                parent.setToolTip(3, vo)
                for shot in list(unit.get("shots") or []):
                    role = str(shot.get("role") or "").strip()
                    shot_sec = float(shot.get("picture_sec") or 0.0)
                    child = QTreeWidgetItem(
                        [
                            self.texts.get(
                                "understanding_recap_review_shot_label",
                                "Shot {n} · {sec:.1f}s",
                            ).format(n=int(shot.get("clip_index") or 0) + 1, sec=shot_sec),
                            format_recap_clock_range(
                                float(shot.get("tl_in") or 0.0),
                                float(shot.get("tl_out") or 0.0),
                            ),
                            format_recap_clock_range(
                                float(shot.get("src_in") or 0.0),
                                float(shot.get("src_out") or 0.0),
                            ),
                            role or "—",
                        ]
                    )
                    child.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {
                            "kind": "shot",
                            "unit_index": unit_index,
                            "clip_indices": list(unit.get("clip_indices") or []),
                            "offset": int(shot.get("offset") or 0),
                            "clip_index": int(shot.get("clip_index") or 0),
                            "beat_id": beat_id,
                            "event": str(unit.get("event") or "").strip(),
                            "vo": vo,
                            "role": role,
                            "src_in": float(shot.get("src_in") or 0.0),
                            "src_out": float(shot.get("src_out") or 0.0),
                            "tl_in": float(shot.get("tl_in") or 0.0),
                            "tl_out": float(shot.get("tl_out") or 0.0),
                            "picture_sec": float(shot.get("picture_sec") or 0.0),
                        },
                    )
                    parent.addChild(child)
                tree.addTopLevelItem(parent)
                parent.setExpanded(True)
        finally:
            tree.setUpdatesEnabled(True)
            tree.blockSignals(False)
            self._restore_recap_review_scroll(vpos, hpos)
        page.recap_review_status.setText(
            self.texts.get(
                "understanding_recap_review_ready",
                "{units} units · {shots} shots · short cover {short}. Double-click to preview.",
            ).format(
                units=len(units),
                shots=len(clips),
                count=len(clips),
                weak=0,
                empty=sum(1 for unit in units if not str(unit.get("vo") or "").strip()),
                short=sum(1 for unit in units if float(unit.get("shortfall_sec") or 0.0) > 0.35),
            )
        )
        page.recap_review_detail.setText(
            self.texts.get(
                "understanding_recap_review_detail_empty",
                "Select a narration unit or child shot.",
            )
        )
        self._sync_recap_review_rewrite_button()
        # Second restore after status/detail text can change outer page layout.
        self._restore_recap_review_scroll(vpos, hpos)

    def _recap_review_busy(self) -> bool:
        return (
            getattr(self, "_recap_worker", None) is not None
            or getattr(self, "_recap_clip_caption_worker", None) is not None
            or getattr(self, "_recap_rematch_beat_worker", None) is not None
            or getattr(self, "_recap_rematch_weak_worker", None) is not None
        )

    def _recap_review_tree(self):
        page = getattr(self, "understanding_page", None)
        if page is None:
            return None
        return getattr(page, "recap_review_tree", None) or getattr(page, "recap_review_table", None)

    def _selected_recap_review_payload(self) -> dict | None:
        from PySide6.QtCore import Qt

        tree = self._recap_review_tree()
        if tree is None:
            return None
        item = tree.currentItem()
        if item is None:
            return None
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        return dict(payload) if isinstance(payload, dict) else None

    def _selected_recap_unit_indices(self) -> list[int] | None:
        payload = self._selected_recap_review_payload()
        if not payload:
            return None
        indices = [int(i) for i in list(payload.get("clip_indices") or [])]
        return indices or None

    def _selected_recap_review_clip_index(self) -> int | None:
        payload = self._selected_recap_review_payload()
        if not payload:
            return None
        if payload.get("kind") == "shot":
            try:
                return int(payload.get("clip_index"))
            except (TypeError, ValueError):
                return None
        indices = list(payload.get("clip_indices") or [])
        if not indices:
            return None
        try:
            return int(indices[0])
        except (TypeError, ValueError):
            return None

    def _selected_recap_review_beat_id(self) -> int | None:
        payload = self._selected_recap_review_payload()
        if not payload:
            return None
        try:
            beat_id = int(payload.get("beat_id") or 0)
        except (TypeError, ValueError):
            return None
        return beat_id if beat_id > 0 else None

    def _sync_recap_review_rewrite_button(self) -> None:
        page = getattr(self, "understanding_page", None)
        if page is None:
            return
        busy = self._recap_review_busy()
        has_cuts = self._current_video_has_recap_cuts()
        payload = self._selected_recap_review_payload()
        unit_ok = bool(payload) and has_cuts and (not busy)
        edit = getattr(page, "btn_edit_recap_unit_vo", None)
        if edit is not None:
            edit.setEnabled(unit_ok)
        add_btn = getattr(page, "btn_add_recap_shot", None)
        if add_btn is not None:
            add_btn.setEnabled(unit_ok)
        shot = payload if payload and payload.get("kind") == "shot" else None
        offsets = list((payload or {}).get("clip_indices") or []) if payload else []
        offset = int((shot or {}).get("offset") or 0) if shot else -1
        up = getattr(page, "btn_recap_shot_up", None)
        if up is not None:
            up.setEnabled(bool(shot) and offset > 0 and has_cuts and (not busy))
        down = getattr(page, "btn_recap_shot_down", None)
        if down is not None:
            down.setEnabled(
                bool(shot) and 0 <= offset < len(offsets) - 1 and has_cuts and (not busy)
            )
        delete_btn = getattr(page, "btn_delete_recap", None)
        if delete_btn is not None:
            delete_btn.setEnabled(unit_ok)
            if payload and payload.get("kind") == "shot":
                delete_btn.setToolTip(
                    self.texts.get(
                        "understanding_recap_review_delete_shot_tip",
                        "Delete this child shot. If it is the last shot, the narration unit remains.",
                    )
                )
            else:
                delete_btn.setToolTip(
                    self.texts.get(
                        "understanding_recap_review_delete_unit_tip",
                        "Delete this narration unit (VO and all child shots).",
                    )
                )
        # Legacy LLM buttons stay hidden/disabled.
        for name in ("btn_rewrite_recap_vo", "btn_rematch_recap_beat", "btn_rematch_weak_beats"):
            button = getattr(page, name, None)
            if button is not None:
                button.setEnabled(False)
                button.setVisible(False)

    def _current_weak_match_beat_count(self) -> int:
        from src.services.recap_service import list_weak_match_beat_ids

        payload = self._load_current_recap_cuts() or {}
        return len(list_weak_match_beat_ids(list(payload.get("clips") or [])))

    def _select_recap_review_unit(self, unit_index: int, *, offset: int | None = None) -> None:
        from PySide6.QtCore import Qt

        tree = self._recap_review_tree()
        if tree is None:
            return
        vpos, hpos = self._capture_recap_review_scroll()
        for top in range(tree.topLevelItemCount()):
            parent = tree.topLevelItem(top)
            if parent is None:
                continue
            payload = parent.data(0, Qt.ItemDataRole.UserRole)
            if not isinstance(payload, dict):
                continue
            if int(payload.get("unit_index") or -1) != int(unit_index):
                continue
            target = parent
            if offset is not None and 0 <= int(offset) < parent.childCount():
                child = parent.child(int(offset))
                if child is not None:
                    target = child
            tree.setCurrentItem(target)
            # setCurrentItem may scroll-to-item; keep the viewport where the user left it.
            self._restore_recap_review_scroll(vpos, hpos)
            self._on_recap_review_item_clicked(target, 0)
            self._restore_recap_review_scroll(vpos, hpos)
            return

    def edit_selected_recap_unit_vo(self) -> None:
        from PySide6.QtWidgets import QDialog

        from src.services.recap_service import save_recap_vo_unit
        from ui.dialogs.recap_vo import RecapVoDialog

        if self._recap_review_busy():
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_edit_busy",
                    "A recap job is running. Try editing VO again in a moment.",
                ),
                kind="warning",
            )
            return
        payload = self._selected_recap_review_payload()
        indices = self._selected_recap_unit_indices()
        if not payload or not indices:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_edit_need_unit",
                    "Select a narration unit first.",
                ),
                kind="warning",
            )
            return
        unit_index = int(payload.get("unit_index") or 0)
        # Prefer parent unit VO when a child shot is selected.
        if payload.get("kind") == "shot":
            tree = self._recap_review_tree()
            item = tree.currentItem() if tree is not None else None
            parent = item.parent() if item is not None else None
            if parent is not None:
                from PySide6.QtCore import Qt

                parent_payload = parent.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(parent_payload, dict):
                    payload = parent_payload
        dialog = RecapVoDialog(
            self,
            texts=self.texts,
            vo=str(payload.get("vo") or ""),
            event=str(payload.get("event") or ""),
            clip_label=self.texts.get("understanding_recap_review_edit_vo", "Narration"),
        )
        if int(dialog.exec()) != int(QDialog.DialogCode.Accepted):
            return
        video_path = self._current_recap_video_path()
        if not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return
        try:
            result = save_recap_vo_unit(
                video_path,
                indices,
                str(dialog.result_vo() or ""),
                video_id=self._selected_understanding_video_id(),
            )
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("understanding_recap_review_edit_failed", "Could not save VO"),
                exc,
            )
            return
        self._stable_recap_review_mutation(
            lambda: (
                self._refresh_recap_review_panel(),
                self._select_recap_review_unit(unit_index),
            )
        )
        speak = float(result.get("speak_sec") or 0.0)
        message = self.texts.get(
            "understanding_recap_review_edit_saved",
            "Saved unit {index} VO (~{sec:.1f}s cover).",
        ).format(index=unit_index + 1, sec=speak)
        page = getattr(self, "understanding_page", None)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(message)
        self._sync_recap_review_rewrite_button()

    def move_selected_recap_shot(self, delta: int) -> None:
        from src.services.recap_service import reorder_recap_unit_shot

        if self._recap_review_busy():
            return
        payload = self._selected_recap_review_payload()
        if not payload or payload.get("kind") != "shot":
            return
        indices = [int(i) for i in list(payload.get("clip_indices") or [])]
        from_offset = int(payload.get("offset") or 0)
        to_offset = from_offset + int(delta)
        if to_offset < 0 or to_offset >= len(indices):
            return
        video_path = self._current_recap_video_path()
        if not video_path:
            return
        unit_index = int(payload.get("unit_index") or 0)
        try:
            reorder_recap_unit_shot(
                video_path,
                indices,
                from_offset,
                to_offset,
                video_id=self._selected_understanding_video_id(),
            )
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get(
                    "understanding_recap_review_reorder_failed",
                    "Could not reorder shots",
                ),
                exc,
            )
            return
        self._stable_recap_review_mutation(
            lambda: (
                self._refresh_recap_review_panel(),
                self._select_recap_review_unit(unit_index, offset=to_offset),
            )
        )

    def delete_selected_recap_review(self) -> None:
        from src.services.recap_service import delete_recap_unit_shot, delete_recap_vo_unit

        if self._recap_review_busy():
            return
        payload = self._selected_recap_review_payload()
        if not payload:
            return
        video_path = self._current_recap_video_path()
        if not video_path:
            return
        indices = [int(i) for i in list(payload.get("clip_indices") or [])]
        if not indices:
            return
        unit_index = int(payload.get("unit_index") or 0)
        kind = str(payload.get("kind") or "unit")
        if kind == "shot":
            offset = int(payload.get("offset") or 0)
            confirm = self.texts.get(
                "understanding_recap_review_delete_shot_confirm",
                "Delete this child shot?\n• Narration text is kept on the unit\n• If this is the last shot, the unit stays as VO-only",
            )
            if not self.show_confirm_dialog(
                self.texts.get("understanding_recap_review_delete_title", "Delete"),
                confirm,
                kind="warning",
                confirm_text=self.texts.get("understanding_recap_review_delete_action", "Delete"),
            ):
                return
            try:
                delete_recap_unit_shot(
                    video_path,
                    indices,
                    offset,
                    video_id=self._selected_understanding_video_id(),
                )
            except Exception as exc:
                self.show_error_dialog(
                    self.texts.get(
                        "understanding_recap_review_delete_failed",
                        "Could not delete",
                    ),
                    exc,
                )
                return
            self._stable_recap_review_mutation(
                lambda: (
                    self._refresh_recap_review_panel(),
                    self._select_recap_review_unit(unit_index),
                )
            )
            message = self.texts.get(
                "understanding_recap_review_delete_shot_saved",
                "Deleted a child shot from unit {index}.",
            ).format(index=unit_index + 1)
        else:
            vo = str(payload.get("vo") or "").strip()
            shots = int(payload.get("shot_count") or len(indices) or 0)
            confirm = self.texts.get(
                "understanding_recap_review_delete_unit_confirm",
                "Delete narration unit {index}?\n• Removes VO and {shots} shot(s)\n• This cannot be undone from here",
            ).format(index=unit_index + 1, shots=shots, vo=(vo[:40] + ("…" if len(vo) > 40 else "")))
            if not self.show_confirm_dialog(
                self.texts.get("understanding_recap_review_delete_title", "Delete"),
                confirm,
                kind="warning",
                confirm_text=self.texts.get("understanding_recap_review_delete_action", "Delete"),
            ):
                return
            try:
                delete_recap_vo_unit(
                    video_path,
                    indices,
                    video_id=self._selected_understanding_video_id(),
                )
            except Exception as exc:
                self.show_error_dialog(
                    self.texts.get(
                        "understanding_recap_review_delete_failed",
                        "Could not delete",
                    ),
                    exc,
                )
                return
            self._stable_recap_review_mutation(lambda: self._refresh_recap_review_panel())
            message = self.texts.get(
                "understanding_recap_review_delete_unit_saved",
                "Deleted narration unit {index}.",
            ).format(index=unit_index + 1)
        page = getattr(self, "understanding_page", None)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(message)
        self._sync_recap_review_rewrite_button()

    def add_shot_to_selected_recap_unit(self) -> None:
        from PySide6.QtWidgets import QDialog

        from ui.dialogs.recap_chunk_pick import RecapChunkPickDialog
        from src.services.recap_service import classify_chunk_usage_for_clips

        if self._recap_review_busy():
            return
        payload = self._selected_recap_review_payload()
        indices = self._selected_recap_unit_indices()
        if not payload or not indices:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_edit_need_unit",
                    "Select a narration unit first.",
                ),
                kind="warning",
            )
            return

        chunks = list(getattr(self, "_understanding_index_chunks", []) or [])
        if not chunks:
            try:
                from src.app.config import load_config
                from src.services.indexing_service import load_video_chunks_by_id

                video_id = self._selected_understanding_video_id()
                if video_id:
                    chunks = list(load_video_chunks_by_id(video_id, load_config()) or [])
                    self._understanding_index_chunks = list(chunks)
            except Exception:
                chunks = []
        if not chunks:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_chunk_pick_no_chunks",
                    "No semantic chunks for this video yet.",
                ),
                kind="warning",
            )
            return

        cuts = self._load_current_recap_cuts() or {}
        all_clips = list(cuts.get("clips") or [])
        unit_clips = [all_clips[i] for i in indices if 0 <= int(i) < len(all_clips)]
        usage = classify_chunk_usage_for_clips(
            chunks,
            unit_clips=unit_clips,
            all_clips=all_clips,
        )
        # Anchor the axis on this unit's first shot, not the currently selected row's out-point.
        first_clip = unit_clips[0] if unit_clips else {}
        focus = float(
            first_clip.get("src_in")
            or first_clip.get("src_out")
            or payload.get("src_in")
            or 0.0
        )
        duration = float(
            (getattr(self, "_understanding_video_context", {}) or {}).get("duration_sec") or 0.0
        )

        # Single modal only — never nest floating preview inside this picker.
        dialog = RecapChunkPickDialog(
            self,
            texts=self.texts,
            chunks=chunks,
            usage_by_index=usage,
            duration_sec=duration,
            focus_sec=focus,
        )
        if int(dialog.exec()) != int(QDialog.DialogCode.Accepted):
            return
        if dialog.chose_custom():
            self._insert_recap_unit_shot_custom_dialog()
            return
        shot = dialog.result_shot() or {}
        self._insert_recap_unit_shot(
            src_in=float(shot.get("src_in") or 0.0),
            src_out=float(shot.get("src_out") or 0.0),
            chunk_index=shot.get("chunk_index"),
        )


    def _recap_add_shot_anchor(self) -> tuple[dict, list[int], int, float, float] | None:
        payload = self._selected_recap_review_payload()
        indices = self._selected_recap_unit_indices()
        if not payload or not indices:
            return None
        if payload.get("kind") == "shot":
            after_offset = int(payload.get("offset") or 0)
            src_in = float(payload.get("src_in") or 0.0)
            src_out = max(src_in + 0.5, float(payload.get("src_out") or src_in + 0.5))
        else:
            after_offset = max(0, len(indices) - 1)
            # Prefer last child shot clocks when parent unit is selected.
            tree = self._recap_review_tree()
            item = tree.currentItem() if tree is not None else None
            child = item.child(item.childCount() - 1) if item is not None and item.childCount() else None
            if child is not None:
                from PySide6.QtCore import Qt

                child_payload = child.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(child_payload, dict):
                    src_in = float(child_payload.get("src_in") or 0.0)
                    src_out = max(src_in + 0.5, float(child_payload.get("src_out") or src_in + 0.5))
                else:
                    src_in = float(payload.get("src_in") or 0.0)
                    src_out = max(src_in + 0.5, float(payload.get("src_out") or src_in + 0.5))
            else:
                src_in = float(payload.get("src_in") or 0.0)
                src_out = max(src_in + 0.5, float(payload.get("src_out") or src_in + 0.5))
        return payload, indices, after_offset, src_in, src_out

    def _insert_recap_unit_shot(
        self,
        *,
        duration_sec: float | None = 2.0,
        src_in: float | None = None,
        src_out: float | None = None,
        chunk_index: int | None = None,
    ) -> None:
        from src.services.recap_service import add_recap_unit_shot

        anchor = self._recap_add_shot_anchor()
        if anchor is None:
            return
        payload, indices, after_offset, anchor_in, anchor_out = anchor
        if src_in is None or src_out is None:
            span = max(0.5, float(anchor_out) - float(anchor_in))
            if duration_sec is None:
                duration_sec = span
            start = float(anchor_out)
            end = start + max(0.5, float(duration_sec))
        else:
            start = float(src_in)
            end = float(src_out)
        video_path = self._current_recap_video_path()
        if not video_path:
            return
        unit_index = int(payload.get("unit_index") or 0)
        kwargs: dict = {
            "src_in": start,
            "src_out": end,
            "after_offset": after_offset,
            "video_id": self._selected_understanding_video_id(),
        }
        if chunk_index is not None:
            kwargs["chunk_index"] = int(chunk_index)
        try:
            add_recap_unit_shot(video_path, indices, **kwargs)
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get(
                    "understanding_recap_review_add_shot_failed",
                    "Could not add shot",
                ),
                exc,
            )
            return
        self._stable_recap_review_mutation(
            lambda: (
                self._refresh_recap_review_panel(),
                self._select_recap_review_unit(unit_index, offset=(after_offset or 0) + 1),
            )
        )
        page = getattr(self, "understanding_page", None)
        message = self.texts.get(
            "understanding_recap_review_add_shot_saved",
            "Added a child shot to unit {index}.",
        ).format(index=unit_index + 1)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(message)

    def _insert_recap_unit_shot_custom_dialog(self) -> None:
        from PySide6.QtWidgets import QDialog

        from ui.dialogs.recap_vo import RecapAddShotDialog

        anchor = self._recap_add_shot_anchor()
        if anchor is None:
            return
        _payload, _indices, _after, src_in, src_out = anchor
        # Seed custom dialog at the insert point (after current out).
        dialog = RecapAddShotDialog(
            self,
            texts=self.texts,
            src_in=float(src_out),
            src_out=float(src_out) + max(1.0, float(src_out) - float(src_in)),
        )
        if int(dialog.exec()) != int(QDialog.DialogCode.Accepted):
            return
        rang = dialog.result_range() or {}
        self._insert_recap_unit_shot(
            src_in=float(rang.get("src_in") or 0.0),
            src_out=float(rang.get("src_out") or 0.0),
        )

    def rewrite_selected_recap_vo(self) -> None:
        from ui.workers import RecapClipCaptionWorker

        if self._recap_review_busy():
            return
        page = getattr(self, "understanding_page", None)
        clip_index = self._selected_recap_review_clip_index()
        if clip_index is None:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_rewrite_need_row",
                    "Select a shot in the table first.",
                ),
                kind="warning",
            )
            return
        video_path = self._current_recap_video_path()
        if not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return
        caption_prompt = ""
        if page is not None and hasattr(page, "input_recap_caption_prompt"):
            caption_prompt = str(page.input_recap_caption_prompt.toPlainText() or "")
        running_text = self.texts.get(
            "understanding_recap_review_rewrite_running",
            "Rewriting narration for this shot…",
        )
        if page is not None:
            page.lbl_status.setText(running_text)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(running_text)
            if hasattr(page, "recap_progress_bar"):
                page.recap_progress_bar.setVisible(True)
                page.recap_progress_bar.setValue(20)
            if hasattr(page, "recap_progress_status"):
                page.recap_progress_status.set_status_text(running_text)
            page.btn_stop.setVisible(True)
            page.btn_stop.setEnabled(True)
        self._sync_recap_export_button(running=True)
        self._sync_recap_review_rewrite_button()
        worker = RecapClipCaptionWorker(
            video_path,
            clip_index,
            video_id=self._selected_understanding_video_id(),
            system_prompt=caption_prompt,
            parent=self,
        )
        self._recap_clip_caption_worker = worker

        def _finish(active_worker=worker):
            if getattr(self, "_recap_clip_caption_worker", None) is active_worker:
                self._recap_clip_caption_worker = None
            if page is not None:
                if hasattr(page, "recap_progress_bar") and getattr(self, "_recap_worker", None) is None:
                    page.recap_progress_bar.setVisible(False)
                if getattr(self, "_recap_worker", None) is None and not (
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                ):
                    page.btn_stop.setEnabled(False)
                    page.btn_stop.setVisible(False)
            self._sync_recap_export_button(running=False)
            self._sync_recap_review_rewrite_button()
            try:
                active_worker.deleteLater()
            except Exception:
                pass

        def _on_progress(pct: int, label: str, active_page=page):
            if active_page is None:
                return
            if hasattr(active_page, "recap_progress_bar"):
                active_page.recap_progress_bar.setVisible(True)
                active_page.recap_progress_bar.setValue(max(0, min(100, int(pct))))
            if hasattr(active_page, "recap_progress_status"):
                active_page.recap_progress_status.set_status_text(label)
            active_page.lbl_status.setText(label)

        worker.progress_signal.connect(_on_progress)
        worker.finished_signal.connect(self._finish_recap_clip_caption_rewrite)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get(
                    "understanding_recap_review_rewrite_failed",
                    "Could not rewrite this VO",
                ),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()

    def _finish_recap_clip_caption_rewrite(self, ok: bool, stopped: bool, payload: object) -> None:
        page = getattr(self, "understanding_page", None)
        if stopped or not ok:
            if page is not None and stopped:
                page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        result = dict(payload or {})
        clip_index = int(result.get("clip_index") or 0)
        self._refresh_recap_review_panel()
        message = self.texts.get(
            "understanding_recap_review_rewrite_done",
            "Rewrote VO on shot {index}.",
        ).format(index=clip_index + 1)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def rematch_selected_recap_beat(self) -> None:
        from ui.workers import RecapRematchBeatWorker

        if self._recap_review_busy():
            return
        page = getattr(self, "understanding_page", None)
        beat_id = self._selected_recap_review_beat_id()
        if beat_id is None:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_rematch_need_beat",
                    "Select a shot that has a beat id first.",
                ),
                kind="warning",
            )
            return
        if not self.show_confirm_dialog(
            self.texts.get("understanding_recap_review_rematch", "Rematch this beat"),
            self.texts.get(
                "understanding_recap_review_rematch_confirm",
                "Rematch beat #{beat}? Its current shots are replaced; other beats are kept.",
            ).format(beat=beat_id),
        ):
            return
        video_id = self._selected_understanding_video_id()
        video_path = self._current_recap_video_path()
        if not video_id or not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return
        match_prompt = ""
        caption_prompt = ""
        if page is not None:
            if hasattr(page, "input_recap_prompt"):
                match_prompt = str(page.input_recap_prompt.toPlainText() or "")
            if hasattr(page, "input_recap_caption_prompt"):
                caption_prompt = str(page.input_recap_caption_prompt.toPlainText() or "")
        running_text = self.texts.get(
            "understanding_recap_review_rematch_running",
            "Rematching this beat…",
        )
        if page is not None:
            page.lbl_status.setText(running_text)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(running_text)
            if hasattr(page, "recap_progress_bar"):
                page.recap_progress_bar.setVisible(True)
                page.recap_progress_bar.setValue(8)
            if hasattr(page, "recap_progress_status"):
                page.recap_progress_status.set_status_text(running_text)
            page.btn_stop.setVisible(True)
            page.btn_stop.setEnabled(True)
        self._sync_recap_export_button(running=True)
        self._sync_recap_review_rewrite_button()
        worker = RecapRematchBeatWorker(
            video_id,
            beat_id,
            video_path=video_path,
            system_prompt=match_prompt,
            caption_prompt=caption_prompt,
            parent=self,
        )
        self._recap_rematch_beat_worker = worker

        def _finish(active_worker=worker):
            if getattr(self, "_recap_rematch_beat_worker", None) is active_worker:
                self._recap_rematch_beat_worker = None
            if page is not None:
                if hasattr(page, "recap_progress_bar") and getattr(self, "_recap_worker", None) is None:
                    page.recap_progress_bar.setVisible(False)
                if getattr(self, "_recap_worker", None) is None and not (
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                ):
                    page.btn_stop.setEnabled(False)
                    page.btn_stop.setVisible(False)
            self._sync_recap_export_button(running=False)
            self._sync_recap_review_rewrite_button()
            try:
                active_worker.deleteLater()
            except Exception:
                pass

        def _on_progress(pct: int, label: str, active_page=page):
            if active_page is None:
                return
            if hasattr(active_page, "recap_progress_bar"):
                active_page.recap_progress_bar.setVisible(True)
                active_page.recap_progress_bar.setValue(max(0, min(100, int(pct))))
            if hasattr(active_page, "recap_progress_status"):
                active_page.recap_progress_status.set_status_text(label)
            active_page.lbl_status.setText(label)

        worker.progress_signal.connect(_on_progress)
        worker.finished_signal.connect(self._finish_recap_rematch_beat)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get(
                    "understanding_recap_review_rematch_failed",
                    "Could not rematch this beat",
                ),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()

    def _finish_recap_rematch_beat(self, ok: bool, stopped: bool, payload: object) -> None:
        page = getattr(self, "understanding_page", None)
        if stopped or not ok:
            if page is not None and stopped:
                page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        result = dict(payload or {})
        beat_id = int(result.get("beat_id") or 0)
        count = int(result.get("beat_clip_count") or result.get("clip_count") or 0)
        self._refresh_recap_review_panel()
        message = self.texts.get(
            "understanding_recap_review_rematch_done",
            "Rematched beat #{beat} ({count} shots).",
        ).format(beat=beat_id, count=count)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def rematch_weak_recap_beats(self) -> None:
        from src.services.recap_service import MAX_WEAK_REMATCH_BEATS, list_weak_match_beat_ids
        from ui.workers import RecapRematchWeakBeatsWorker

        if self._recap_review_busy():
            return
        page = getattr(self, "understanding_page", None)
        payload = self._load_current_recap_cuts() or {}
        weak_ids = list_weak_match_beat_ids(list(payload.get("clips") or []))
        if not weak_ids:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get(
                    "understanding_recap_review_rematch_weak_none",
                    "No weak-match beats right now.",
                ),
                kind="warning",
            )
            return
        limit = int(MAX_WEAK_REMATCH_BEATS)
        if not self.show_confirm_dialog(
            self.texts.get("understanding_recap_review_rematch_weak", "Rematch all weak beats"),
            self.texts.get(
                "understanding_recap_review_rematch_weak_confirm",
                "Rematch {count} weak-evidence beats?\nAt most {limit} beats per run.",
            ).format(count=len(weak_ids), limit=limit),
        ):
            return
        video_id = self._selected_understanding_video_id()
        video_path = self._current_recap_video_path()
        if not video_id or not video_path:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return
        match_prompt = ""
        caption_prompt = ""
        if page is not None:
            if hasattr(page, "input_recap_prompt"):
                match_prompt = str(page.input_recap_prompt.toPlainText() or "")
            if hasattr(page, "input_recap_caption_prompt"):
                caption_prompt = str(page.input_recap_caption_prompt.toPlainText() or "")
        running_text = self.texts.get(
            "understanding_recap_review_rematch_weak_running",
            "Batch-rematching weak beats…",
        )
        if page is not None:
            page.lbl_status.setText(running_text)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(running_text)
            if hasattr(page, "recap_progress_bar"):
                page.recap_progress_bar.setVisible(True)
                page.recap_progress_bar.setValue(8)
            if hasattr(page, "recap_progress_status"):
                page.recap_progress_status.set_status_text(running_text)
            page.btn_stop.setVisible(True)
            page.btn_stop.setEnabled(True)
        self._sync_recap_export_button(running=True)
        self._sync_recap_review_rewrite_button()
        worker = RecapRematchWeakBeatsWorker(
            video_id,
            video_path=video_path,
            system_prompt=match_prompt,
            caption_prompt=caption_prompt,
            max_beats=limit,
            parent=self,
        )
        self._recap_rematch_weak_worker = worker

        def _finish(active_worker=worker):
            if getattr(self, "_recap_rematch_weak_worker", None) is active_worker:
                self._recap_rematch_weak_worker = None
            if page is not None:
                if hasattr(page, "recap_progress_bar") and getattr(self, "_recap_worker", None) is None:
                    page.recap_progress_bar.setVisible(False)
                if getattr(self, "_recap_worker", None) is None and not (
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                ):
                    page.btn_stop.setEnabled(False)
                    page.btn_stop.setVisible(False)
            self._sync_recap_export_button(running=False)
            self._sync_recap_review_rewrite_button()
            try:
                active_worker.deleteLater()
            except Exception:
                pass

        def _on_progress(pct: int, label: str, active_page=page):
            if active_page is None:
                return
            if hasattr(active_page, "recap_progress_bar"):
                active_page.recap_progress_bar.setVisible(True)
                active_page.recap_progress_bar.setValue(max(0, min(100, int(pct))))
            if hasattr(active_page, "recap_progress_status"):
                active_page.recap_progress_status.set_status_text(label)
            active_page.lbl_status.setText(label)

        worker.progress_signal.connect(_on_progress)
        worker.finished_signal.connect(self._finish_recap_rematch_weak)
        worker.error_signal.connect(
            lambda message: self.show_error_dialog(
                self.texts.get(
                    "understanding_recap_review_rematch_weak_failed",
                    "Could not batch-rematch weak beats",
                ),
                Exception(message),
            )
        )
        worker.finished.connect(_finish)
        worker.start()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()

    def _finish_recap_rematch_weak(self, ok: bool, stopped: bool, payload: object) -> None:
        page = getattr(self, "understanding_page", None)
        if stopped or not ok:
            if page is not None and stopped:
                page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            return
        result = dict(payload or {})
        done = len(list(result.get("beat_ids") or []))
        remain = len(list(result.get("remaining_weak") or []))
        failed = len(list(result.get("failed") or []))
        self._refresh_recap_review_panel()
        message = self.texts.get(
            "understanding_recap_review_rematch_weak_done",
            "Rematched {done} weak beats; still weak {remain}; failed {failed}.",
        ).format(done=done, remain=remain, failed=failed)
        if page is not None:
            page.lbl_status.setText(message)
            if hasattr(page, "recap_review_status"):
                page.recap_review_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def _on_recap_review_item_clicked(self, item, column: int) -> None:
        _ = column
        from PySide6.QtCore import Qt

        page = getattr(self, "understanding_page", None)
        if page is None or item is None:
            return
        freeze = getattr(self, "_freeze_understanding_page_scroll", None)
        if freeze is not None:
            with freeze():
                self._update_recap_review_detail_from_item(item)
                self._sync_recap_review_rewrite_button()
            return
        self._update_recap_review_detail_from_item(item)
        self._sync_recap_review_rewrite_button()

    def _update_recap_review_detail_from_item(self, item) -> None:
        import html

        from PySide6.QtCore import Qt

        page = getattr(self, "understanding_page", None)
        if page is None or item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        from src.services.recap_service import format_recap_clock_range

        beat = payload.get("beat_id") or "—"
        event = str(payload.get("event") or "").strip() or "—"
        vo = str(payload.get("vo") or "").strip()
        kind = str(payload.get("kind") or "unit")

        def _chip(text: str, *, fg: str, bg: str) -> str:
            return (
                f'<span style="color:{fg};background:{bg};font-weight:700;'
                f'padding:1px 7px;border-radius:4px;">{html.escape(text)}</span>'
            )

        def _timing_colors():
            try:
                from ui.widgets.styles import theme_color_map

                colors = theme_color_map(bool(getattr(self, "is_dark_mode", True)))
            except Exception:
                colors = {}
            return colors

        colors = _timing_colors()
        if kind == "shot":
            picture = float(payload.get("picture_sec") or 0.0)
            timing_plain = self.texts.get(
                "understanding_recap_review_detail_shot_timing",
                "Picture {picture:.1f}s",
            ).format(picture=picture)
            timing = _chip(
                timing_plain,
                fg=str(colors.get("SUCCESS") or "#0f7b3a"),
                bg=str(colors.get("SUCCESS_SOFT") or "#e6f5ec"),
            )
            detail = self.texts.get(
                "understanding_recap_review_detail_shot",
                "Shot {n} · role {role}\nRecap {tl} · source {src}\n{timing}\nUnit VO: {vo}",
            ).format(
                n=int(payload.get("clip_index") or 0) + 1,
                role=html.escape(str(payload.get("role") or "—") or "—"),
                tl=format_recap_clock_range(
                    float(payload.get("tl_in") or 0.0),
                    float(payload.get("tl_out") or 0.0),
                ),
                src=format_recap_clock_range(
                    float(payload.get("src_in") or 0.0),
                    float(payload.get("src_out") or 0.0),
                ),
                timing=timing,
                vo=html.escape(vo or "—"),
            )
        else:
            speak = float(payload.get("speak_sec") or 0.0)
            picture = float(payload.get("picture_sec") or 0.0)
            shortfall = float(payload.get("shortfall_sec") or max(0.0, speak - picture))
            speak_fg = str(colors.get("WARN") or "#9a6700")
            speak_bg = str(colors.get("WARN_SOFT") or "#fff4ce")
            if shortfall > 0.35:
                speak_fg = str(colors.get("DANGER") or "#c42b1c")
                speak_bg = str(colors.get("DANGER_SOFT") or "#fde7e9")
            speak_label = self.texts.get(
                "understanding_recap_review_detail_timing_speak",
                "Speak ~{speak:.1f}s",
            ).format(speak=speak)
            picture_label = self.texts.get(
                "understanding_recap_review_detail_timing_picture",
                "picture {picture:.1f}s",
            ).format(picture=picture)
            timing = (
                f"{_chip(speak_label, fg=speak_fg, bg=speak_bg)}"
                f' <span style="color:{html.escape(str(colors.get("MUTED") or "#6b6b6b"))};">/</span> '
                f'{_chip(picture_label, fg=str(colors.get("SUCCESS") or "#0f7b3a"), bg=str(colors.get("SUCCESS_SOFT") or "#e6f5ec"))}'
            )
            detail = self.texts.get(
                "understanding_recap_review_detail",
                "Unit {unit} · beat #{beat} · {shots} shots\nRecap {tl} · source {src}\n{timing}\nEvent: {event}\nVO: {vo}",
            ).format(
                unit=int(payload.get("unit_index") or 0) + 1,
                beat=html.escape(str(beat)),
                shots=int(payload.get("shot_count") or len(list(payload.get("clip_indices") or []))),
                tl=format_recap_clock_range(
                    float(payload.get("tl_in") or 0.0),
                    float(payload.get("tl_out") or 0.0),
                ),
                src=format_recap_clock_range(
                    float(payload.get("src_in") or 0.0),
                    float(payload.get("src_out") or 0.0),
                ),
                timing=timing,
                event=html.escape(event),
                vo=html.escape(vo or "—"),
            )
        # Keep detail height stable so page scroll does not jump.
        page.recap_review_detail.setTextFormat(Qt.TextFormat.RichText)
        page.recap_review_detail.setText(detail.replace("\n", "<br/>"))

    def _on_recap_review_item_double_clicked(self, item, column: int) -> None:
        _ = column
        from PySide6.QtCore import Qt

        page = getattr(self, "understanding_page", None)
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(payload, dict):
            return
        try:
            start = float(payload.get("src_in") or 0.0)
            end = float(payload.get("src_out") or start)
        except (TypeError, ValueError):
            return
        vo = str(payload.get("vo") or "").strip()
        self._play_understanding_range(start, end, caption_text=vo or None)
        if page is not None:
            from src.utils import format_timecode_range

            page.lbl_status.setText(
                self.texts.get(
                    "understanding_recap_review_play",
                    "Previewing source {range}",
                ).format(range=format_timecode_range(start, end))
            )

    def _on_recap_review_cell_clicked(self, row: int, column: int) -> None:
        # Back-compat for older callers; tree selection uses item handlers.
        _ = row, column
        tree = self._recap_review_tree()
        if tree is None:
            return
        self._on_recap_review_item_clicked(tree.currentItem(), 0)

    def _on_recap_review_cell_double_clicked(self, row: int, column: int) -> None:
        _ = row, column
        tree = self._recap_review_tree()
        if tree is None:
            return
        self._on_recap_review_item_double_clicked(tree.currentItem(), 0)

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
        from src.services.recap_service import (
            default_recap_caption_prompt,
            default_recap_match_prompt,
            default_recap_plan_prompt,
            default_recap_polish_prompt,
        )

        page = getattr(self, "understanding_page", None)
        if page is None or not hasattr(page, "input_recap_prompt"):
            return
        language = self._vlm_prompt_language() if hasattr(self, "_vlm_prompt_language") else "zh"
        index = 1
        if hasattr(page, "recap_prompt_tabs"):
            index = int(page.recap_prompt_tabs.currentIndex())
        editors = (
            (getattr(page, "input_recap_plan_prompt", None), default_recap_plan_prompt(language)),
            (page.input_recap_prompt, default_recap_match_prompt(language)),
            (getattr(page, "input_recap_caption_prompt", None), default_recap_caption_prompt(language)),
            (getattr(page, "input_recap_polish_prompt", None), default_recap_polish_prompt(language)),
        )
        if index < 0 or index >= len(editors):
            index = 1
        editor, default = editors[index]
        if editor is not None:
            editor.setPlainText(default)

    def _recap_prompt_getter_pairs(self):
        from src.services.recap_service import (
            default_recap_caption_prompt,
            default_recap_match_prompt,
            default_recap_plan_prompt,
            default_recap_polish_prompt,
        )

        page = getattr(self, "understanding_page", None)
        if page is None:
            return ()
        return (
            (getattr(page, "input_recap_plan_prompt", None), default_recap_plan_prompt),
            (getattr(page, "input_recap_prompt", None), default_recap_match_prompt),
            (getattr(page, "input_recap_caption_prompt", None), default_recap_caption_prompt),
            (getattr(page, "input_recap_polish_prompt", None), default_recap_polish_prompt),
        )

    def _refresh_recap_prompt_editors_for_language(self) -> None:
        language = self._vlm_prompt_language() if hasattr(self, "_vlm_prompt_language") else "zh"
        builtin_langs = ("zh", "en")
        for editor, getter in self._recap_prompt_getter_pairs():
            if editor is None:
                continue
            current = str(editor.toPlainText() or "").strip()
            if not current or any(current == str(getter(item) or "").strip() for item in builtin_langs):
                editor.setPlainText(getter(language))

    def _ensure_recap_prompt_default(self):
        from src.services.recap_service import (
            RECAP_GAP_SYSTEM,
            RECAP_GAP_SYSTEM_EN,
        )

        page = getattr(self, "understanding_page", None)
        if page is None:
            return
        language = self._vlm_prompt_language() if hasattr(self, "_vlm_prompt_language") else "zh"
        caption_editor = getattr(page, "input_recap_caption_prompt", None)
        match_editor = getattr(page, "input_recap_prompt", None)
        for editor, getter in self._recap_prompt_getter_pairs():
            if editor is None:
                continue
            body = str(editor.toPlainText() or "").strip()
            stale_caption = editor is caption_editor and (
                body in {str(RECAP_GAP_SYSTEM).strip(), str(RECAP_GAP_SYSTEM_EN).strip()}
                or "按 reason、beat 和 people 写旁白" in body
                or "连续空镜特写可以并进前一句" in body
            )
            stale_match = editor is match_editor and (
                "不要写 vo" in body
                and "换场能并进" in body
                and '"role":"insert"' not in body.replace(" ", "")
            )
            if not body or stale_caption or stale_match:
                editor.setPlainText(getter(language))
            elif any(
                body == str(getter(item) or "").strip() for item in ("zh", "en")
            ) and body != str(getter(language) or "").strip():
                editor.setPlainText(getter(language))
