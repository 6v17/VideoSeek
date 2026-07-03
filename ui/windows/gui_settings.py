"""Settings page wiring — extracted from MainWindow to shrink gui.py."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QFileDialog

from src.app.config import (
    DEFAULT_CONFIG,
    get_configured_data_root,
    load_config,
    save_config,
)
from src.core.chunk_policy import (
    CHUNK_POLICY_CUSTOM,
    detect_chunk_policy,
    resolve_chunk_policy_values,
)
from src.core.clip_embedding import reset_engine
from src.services.storage_service import (
    cleanup_old_data_root as cleanup_old_data_root_service,
    cleanup_old_model_dir as cleanup_old_model_dir_service,
    migrate_app_data_root,
    migrate_model_root,
)
from src.storage.config_store import get_effective_model_dir, resolve_provider_dir
from src.utils import (
    ensure_sampling_fps_rules_open_tail,
    normalize_sampling_fps_mode,
    normalize_sampling_fps_rules_text,
    resolve_sampling_fps,
    sync_ffmpeg_path_to_config,
    sync_model_dir_to_config,
    validate_sampling_fps_rules_full_coverage,
)
from ui.dialogs import SamplingRulesDialog


class SettingsGuiMixin:
    """Load/save settings, data root, model dir, sampling UI; mixed into `MainWindow`."""

    def load_settings_values(self):
        self._settings_loading = True
        try:
            config = load_config()
        except Exception as exc:
            self._settings_loading = False
            self.show_error_dialog(self.texts["settings_load_failed"], exc)
            return
        self._populate_model_profile_options(config)
        sampling_fps_mode = normalize_sampling_fps_mode(
            config.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
        )
        self.settings_page.set_sampling_fps_mode(sampling_fps_mode)
        self.settings_page.input_fps.setValue(config.get("fps", DEFAULT_CONFIG["fps"]))
        sampling_rules = normalize_sampling_fps_rules_text(
            config.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
        )
        if sampling_fps_mode == "dynamic" and not sampling_rules:
            sampling_rules = DEFAULT_CONFIG["sampling_fps_rules"]
        self.settings_page.set_sampling_fps_rules_text(sampling_rules)
        self.settings_page.input_top_k.setValue(config.get("search_top_k", DEFAULT_CONFIG["search_top_k"]))
        frame_neighbor_rerank_enabled = bool(
            config.get(
                "frame_neighbor_rerank_enabled",
                DEFAULT_CONFIG["frame_neighbor_rerank_enabled"],
            )
        )
        self.settings_page.input_frame_neighbor_rerank_enabled.setCurrentIndex(1 if frame_neighbor_rerank_enabled else 0)
        self.settings_page.input_frame_neighbor_rerank_top_n.setValue(
            int(
                config.get(
                    "frame_neighbor_rerank_top_n",
                    DEFAULT_CONFIG["frame_neighbor_rerank_top_n"],
                )
            )
        )
        self.settings_page.input_frame_neighbor_rerank_window.setValue(
            int(
                config.get(
                    "frame_neighbor_rerank_window",
                    DEFAULT_CONFIG["frame_neighbor_rerank_window"],
                )
            )
        )
        self.settings_page.input_image_pixel_rerank_top_n.setValue(
            int(
                config.get(
                    "image_pixel_rerank_top_n",
                    DEFAULT_CONFIG["image_pixel_rerank_top_n"],
                )
            )
        )
        probe_mode = str(
            config.get(
                "image_pixel_rerank_probe_mode",
                DEFAULT_CONFIG["image_pixel_rerank_probe_mode"],
            )
        ).strip().lower()
        probe_mode_index = self.settings_page.input_image_pixel_rerank_probe_mode.findData(probe_mode)
        self.settings_page.input_image_pixel_rerank_probe_mode.setCurrentIndex(
            0 if probe_mode_index < 0 else probe_mode_index
        )
        self.settings_page.input_image_pixel_rerank_time_window_sec.setValue(
            float(
                config.get(
                    "image_pixel_rerank_time_window_sec",
                    DEFAULT_CONFIG["image_pixel_rerank_time_window_sec"],
                )
            )
        )
        self.settings_page.input_image_pixel_rerank_probe_step_sec.setValue(
            float(
                config.get(
                    "image_pixel_rerank_probe_step_sec",
                    DEFAULT_CONFIG["image_pixel_rerank_probe_step_sec"],
                )
            )
        )
        self.settings_page.input_image_search_fetch_multiplier.setValue(
            int(
                config.get(
                    "image_search_fetch_multiplier",
                    DEFAULT_CONFIG["image_search_fetch_multiplier"],
                )
            )
        )
        self.settings_page.input_preview_seconds.setValue(
            config.get("preview_seconds", DEFAULT_CONFIG["preview_seconds"])
        )
        self.settings_page.input_thumb_width.setValue(
            config.get("thumb_width", DEFAULT_CONFIG["thumb_width"])
        )
        self.settings_page.input_thumb_height.setValue(
            config.get("thumb_height", DEFAULT_CONFIG["thumb_height"])
        )
        export_video_silent = bool(config.get("export_video_silent", DEFAULT_CONFIG["export_video_silent"]))
        self.settings_page.input_export_video_silent.setCurrentIndex(1 if export_video_silent else 0)
        self.settings_page.input_remote_max_frames.setValue(
            int(config.get("remote_max_frames", DEFAULT_CONFIG["remote_max_frames"]))
        )
        self.settings_page.input_embedding_batch_size.setValue(
            int(config.get("embedding_batch_size", DEFAULT_CONFIG["embedding_batch_size"]))
        )
        search_mode = config.get("search_mode", DEFAULT_CONFIG["search_mode"])
        self.search_page.search_mode.setCurrentIndex(0 if search_mode == "frame" else 1)
        video_discovery_enabled = bool(
            config.get(
                "search_video_discovery_enabled",
                DEFAULT_CONFIG["search_video_discovery_enabled"],
            )
        )
        toggle = self.search_page.search_video_discovery_toggle
        toggle.blockSignals(True)
        toggle.setChecked(video_discovery_enabled)
        toggle.blockSignals(False)
        self.settings_page.input_similarity_threshold.setValue(
            config.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"])
        )
        self.settings_page.input_min_chunk_size.setValue(
            config.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"])
        )
        self.settings_page.input_min_chunk_duration.setValue(
            config.get("min_chunk_duration", DEFAULT_CONFIG["min_chunk_duration"])
        )
        chunk_policy_id = detect_chunk_policy(config)
        stored_policy = str(config.get("chunk_policy", "") or "").strip().lower()
        if stored_policy and stored_policy != CHUNK_POLICY_CUSTOM and stored_policy == chunk_policy_id:
            self.settings_page.set_chunk_policy_id(stored_policy)
        else:
            self.settings_page.set_chunk_policy_id(chunk_policy_id)
        self.settings_page.sync_chunk_advanced_visibility()
        prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
        self.settings_page.input_prefer_gpu.setCurrentIndex(0 if prefer_gpu else 1)
        experimental_hw_decode = bool(
            config.get("experimental_hw_decode", DEFAULT_CONFIG["experimental_hw_decode"])
        )
        self.settings_page.input_experimental_hw_decode.setCurrentIndex(1 if experimental_hw_decode else 0)
        gpu_probe_unknown_keep_gpu = bool(
            config.get("gpu_probe_unknown_keep_gpu", DEFAULT_CONFIG["gpu_probe_unknown_keep_gpu"])
        )
        self.settings_page.input_gpu_probe_unknown_keep_gpu.setCurrentIndex(1 if gpu_probe_unknown_keep_gpu else 0)
        auto_cleanup_missing_files = bool(
            config.get("auto_cleanup_missing_files", DEFAULT_CONFIG["auto_cleanup_missing_files"])
        )
        self.settings_page.input_auto_cleanup_missing_files.setCurrentIndex(1 if auto_cleanup_missing_files else 0)
        close_window_action = str(config.get("close_window_action", DEFAULT_CONFIG["close_window_action"]))
        tray_index = self.settings_page.input_close_window_action.findData("tray")
        self.settings_page.input_close_window_action.setCurrentIndex(
            tray_index if close_window_action == "tray" and tray_index >= 0 else 0
        )
        agent_api_enabled = bool(config.get("agent_api_enabled", DEFAULT_CONFIG["agent_api_enabled"]))
        self.settings_page.input_agent_api_enabled.setCurrentIndex(1 if agent_api_enabled else 0)
        self.settings_page.input_data_root.setText(get_configured_data_root(config))
        self.settings_page.input_ffmpeg_path.setText(config.get("ffmpeg_path", DEFAULT_CONFIG["ffmpeg_path"]))
        self.settings_page.input_model_dir.setText(config.get("model_dir", DEFAULT_CONFIG["model_dir"]))
        self.push_inference_status()
        self._update_sampling_rules_feedback()
        self._update_sampling_preview()
        self._refresh_pending_cleanup_actions(config)
        self._settings_loading = False
        self._set_settings_dirty(False)
        self._refresh_agent_api_status()
        if hasattr(self, "_refresh_search_precision_controls"):
            self._refresh_search_precision_controls()
        if hasattr(self, "load_understanding_settings"):
            self.load_understanding_settings()

    def _bind_settings_dirty_tracking(self):
        if self._settings_dirty_tracking_bound:
            return
        self._settings_dirty_tracking_bound = True
        editors = [
            self.settings_page.input_fps,
            self.settings_page.input_top_k,
            self.settings_page.input_frame_neighbor_rerank_enabled,
            self.settings_page.input_frame_neighbor_rerank_top_n,
            self.settings_page.input_frame_neighbor_rerank_window,
            self.settings_page.input_image_pixel_rerank_top_n,
            self.settings_page.input_image_pixel_rerank_probe_mode,
            self.settings_page.input_image_pixel_rerank_time_window_sec,
            self.settings_page.input_image_pixel_rerank_probe_step_sec,
            self.settings_page.input_image_search_fetch_multiplier,
            self.settings_page.input_preview_seconds,
            self.settings_page.input_thumb_width,
            self.settings_page.input_thumb_height,
            self.settings_page.input_export_video_silent,
            self.settings_page.input_remote_max_frames,
            self.settings_page.input_embedding_batch_size,
            self.settings_page.input_chunk_policy,
            self.settings_page.input_similarity_threshold,
            self.settings_page.input_min_chunk_size,
            self.settings_page.input_min_chunk_duration,
            self.settings_page.input_prefer_gpu,
            self.settings_page.input_experimental_hw_decode,
            self.settings_page.input_gpu_probe_unknown_keep_gpu,
            self.settings_page.input_auto_cleanup_missing_files,
            self.settings_page.input_close_window_action,
            self.settings_page.input_agent_api_enabled,
            self.settings_page.input_active_model_profile,
            self.settings_page.input_data_root,
            self.settings_page.input_ffmpeg_path,
            self.settings_page.input_model_dir,
            self.settings_page.input_sampling_fps_mode,
            self.settings_page.input_sampling_fps_rules,
        ]
        for widget in editors:
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._mark_settings_dirty)
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._mark_settings_dirty)
            elif hasattr(widget, "textChanged"):
                widget.textChanged.connect(self._mark_settings_dirty)
        self._bind_chunk_policy_handlers()

    def _bind_chunk_policy_handlers(self):
        if getattr(self, "_chunk_policy_handlers_bound", False):
            return
        self._chunk_policy_handlers_bound = True
        self.settings_page.input_chunk_policy.currentIndexChanged.connect(self._on_chunk_policy_changed)
        chunk_editors = [
            self.settings_page.input_similarity_threshold,
            self.settings_page.input_min_chunk_size,
            self.settings_page.input_min_chunk_duration,
        ]
        for widget in chunk_editors:
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._on_chunk_policy_field_changed)
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._on_chunk_policy_field_changed)

    def _on_chunk_policy_changed(self, *_args):
        if self._settings_loading or self.settings_page.is_chunk_policy_syncing():
            return
        policy_id = self.settings_page.get_chunk_policy_id()
        preset_values = resolve_chunk_policy_values(policy_id)
        if preset_values:
            self.settings_page.apply_chunk_policy_values(preset_values)
        if policy_id == CHUNK_POLICY_CUSTOM:
            self.settings_page.set_chunk_advanced_expanded(True)
        else:
            self.settings_page.set_chunk_advanced_expanded(False)
        self._mark_settings_dirty()

    def _on_chunk_policy_field_changed(self, *_args):
        if self._settings_loading or self.settings_page.is_chunk_policy_syncing():
            return
        self.settings_page.set_chunk_policy_id(CHUNK_POLICY_CUSTOM)
        self.settings_page.set_chunk_advanced_expanded(True)
        self._mark_settings_dirty()

    def _mark_settings_dirty(self, *_args):
        if self._settings_loading:
            return
        self._set_settings_dirty(True)

    def _set_settings_dirty(self, dirty):
        dirty = bool(dirty)
        self._settings_dirty = dirty
        btn = self.settings_page.btn_save
        btn.setEnabled(dirty)
        target_object = "PrimaryButton" if dirty else "GhostButton"
        if btn.objectName() != target_object:
            btn.setObjectName(target_object)
            style = btn.style()
            style.unpolish(btn)
            style.polish(btn)
            btn.update()

    def _populate_model_profile_options(self, config):
        models = dict(config.get("models") or {})
        profiles = [item for item in models.get("profiles", []) if isinstance(item, dict)]
        active_profile_id = str(models.get("active_profile", "") or "").strip()
        combo = self.settings_page.input_active_model_profile
        combo.blockSignals(True)
        combo.clear()
        for profile in profiles:
            profile_id = str(profile.get("id", "") or "").strip()
            if not profile_id:
                continue
            runtime = dict(profile.get("runtime") or {})
            provider = str(profile.get("provider", "") or "").strip()
            provider_dir = resolve_provider_dir(provider)
            model_variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
            if not model_variant:
                model_variant = "vit-base-patch32"
            display_name = f"{provider_dir} / {model_variant}"
            combo.addItem(display_name, profile_id)
        if combo.count() == 0:
            combo.addItem(
                self.texts.get("model_profile_none", "No model imported"),
                "",
            )
            active_profile_id = ""
        index = combo.findData(active_profile_id)
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def _on_active_model_profile_changed(self, _index):
        config = load_config()
        selected_profile_id = str(self.settings_page.input_active_model_profile.currentData() or "").strip()
        models = dict(config.get("models") or {})
        profiles = [item for item in models.get("profiles", []) if isinstance(item, dict)]
        for profile in profiles:
            if str(profile.get("id", "") or "").strip() != selected_profile_id:
                continue
            runtime = dict(profile.get("runtime") or {})
            prefer_gpu = bool(runtime.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"]))
            model_dir = str(runtime.get("model_dir", "") or "").strip() or config.get("model_dir", DEFAULT_CONFIG["model_dir"])
            self.settings_page.input_prefer_gpu.setCurrentIndex(0 if prefer_gpu else 1)
            self.settings_page.input_model_dir.setText(model_dir)
            break

    def save_settings(self):
        if not self._ensure_startup_migration_idle("feature_settings"):
            return
        try:
            config = load_config()
            current_data_root = get_configured_data_root(config)
            previous_fps = config.get("fps", DEFAULT_CONFIG["fps"] )
            previous_sampling_fps_mode = normalize_sampling_fps_mode(
                config.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
            )
            previous_sampling_fps_rules = normalize_sampling_fps_rules_text(
                config.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
            )
            previous_similarity_threshold = float(
                config.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"])
            )
            previous_embedding_batch_size = int(
                config.get("embedding_batch_size", DEFAULT_CONFIG["embedding_batch_size"])
            )
            previous_min_chunk_size = int(config.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"]))
            previous_min_chunk_duration = float(
                config.get("min_chunk_duration", DEFAULT_CONFIG["min_chunk_duration"])
            )
            previous_chunk_policy = str(config.get("chunk_policy", DEFAULT_CONFIG.get("chunk_policy", "balanced")))
            previous_prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
            previous_gpu_probe_unknown_keep_gpu = bool(
                config.get("gpu_probe_unknown_keep_gpu", DEFAULT_CONFIG["gpu_probe_unknown_keep_gpu"])
            )
            previous_models = dict(config.get("models") or {})
            previous_active_profile_id = str(previous_models.get("active_profile", "") or "").strip()
            try:
                previous_effective_model_dir = str(get_effective_model_dir(config=config) or "").strip()
            except Exception:
                previous_effective_model_dir = ""
            new_fps = self.settings_page.input_fps.value()
            new_sampling_fps_mode = normalize_sampling_fps_mode(
                self.settings_page.get_sampling_fps_mode()
            )
            user_sampling_fps_rules = normalize_sampling_fps_rules_text(
                self.settings_page.get_sampling_fps_rules_text()
            )
            new_sampling_fps_rules = user_sampling_fps_rules
            if new_sampling_fps_mode == "dynamic":
                new_sampling_fps_rules = ensure_sampling_fps_rules_open_tail(new_sampling_fps_rules, default_tail_fps=1)
            auto_tail_rule = ""
            if (
                new_sampling_fps_mode == "dynamic"
                and user_sampling_fps_rules
                and new_sampling_fps_rules != user_sampling_fps_rules
            ):
                auto_tail_rule = new_sampling_fps_rules[len(user_sampling_fps_rules):].lstrip(" ;")
            rules_valid, _ = validate_sampling_fps_rules_full_coverage(new_sampling_fps_rules)
            if new_sampling_fps_mode == "dynamic" and new_sampling_fps_rules and not rules_valid:
                self.settings_page.lbl_status.setText(self.texts["setting_sampling_fps_rules_invalid"] )
                self.show_info_dialog(
                    self.texts["error_title"],
                    self.texts["setting_sampling_fps_rules_invalid"],
                    kind="warning",
                )
                return
            new_similarity_threshold = float(self.settings_page.input_similarity_threshold.value())
            new_embedding_batch_size = int(self.settings_page.input_embedding_batch_size.value())
            new_min_chunk_size = int(self.settings_page.input_min_chunk_size.value())
            new_min_chunk_duration = float(self.settings_page.input_min_chunk_duration.value())
            new_chunk_policy = str(self.settings_page.get_chunk_policy_id())
            config["fps"] = new_fps
            config["sampling_fps_mode"] = new_sampling_fps_mode
            # Preserve the user's rule set even while fixed mode is active so
            # switching back to dynamic mode does not silently drop it.
            config["sampling_fps_rules"] = new_sampling_fps_rules
            config["search_top_k"] = self.settings_page.input_top_k.value()
            config["frame_neighbor_rerank_enabled"] = bool(
                self.settings_page.input_frame_neighbor_rerank_enabled.currentData()
            )
            config["frame_neighbor_rerank_top_n"] = int(
                self.settings_page.input_frame_neighbor_rerank_top_n.value()
            )
            config["frame_neighbor_rerank_window"] = int(
                self.settings_page.input_frame_neighbor_rerank_window.value()
            )
            config["image_pixel_rerank_top_n"] = int(
                self.settings_page.input_image_pixel_rerank_top_n.value()
            )
            config["image_pixel_rerank_probe_mode"] = str(
                self.settings_page.input_image_pixel_rerank_probe_mode.currentData() or "index"
            )
            config["image_pixel_rerank_time_window_sec"] = float(
                self.settings_page.input_image_pixel_rerank_time_window_sec.value()
            )
            config["image_pixel_rerank_probe_step_sec"] = float(
                self.settings_page.input_image_pixel_rerank_probe_step_sec.value()
            )
            config["image_search_fetch_multiplier"] = int(
                self.settings_page.input_image_search_fetch_multiplier.value()
            )
            config["preview_seconds"] = self.settings_page.input_preview_seconds.value()
            config["thumb_width"] = self.settings_page.input_thumb_width.value()
            config["thumb_height"] = self.settings_page.input_thumb_height.value()
            config["export_video_silent"] = bool(self.settings_page.input_export_video_silent.currentData())
            config["remote_max_frames"] = int(self.settings_page.input_remote_max_frames.value())
            config["embedding_batch_size"] = new_embedding_batch_size
            config["similarity_threshold"] = new_similarity_threshold
            config["min_chunk_size"] = new_min_chunk_size
            config["min_chunk_duration"] = new_min_chunk_duration
            config["chunk_policy"] = new_chunk_policy
            config["prefer_gpu"] = bool(self.settings_page.input_prefer_gpu.currentData())
            config["experimental_hw_decode"] = bool(
                self.settings_page.input_experimental_hw_decode.currentData()
            )
            config["gpu_probe_unknown_keep_gpu"] = bool(
                self.settings_page.input_gpu_probe_unknown_keep_gpu.currentData()
            )
            config["auto_cleanup_missing_files"] = bool(
                self.settings_page.input_auto_cleanup_missing_files.currentData()
            )
            config["close_window_action"] = str(
                self.settings_page.input_close_window_action.currentData() or "exit"
            )
            config["agent_api_enabled"] = bool(self.settings_page.input_agent_api_enabled.currentData())
            selected_profile_id = str(self.settings_page.input_active_model_profile.currentData() or "").strip()
            models = config.get("models")
            if not isinstance(models, dict):
                models = {}
                config["models"] = models
            profiles = models.get("profiles")
            if not isinstance(profiles, list):
                profiles = []
                models["profiles"] = profiles
            if selected_profile_id:
                models["active_profile"] = selected_profile_id
            requested_data_root = self._normalize_requested_data_root(self.settings_page.input_data_root.text())
            config["ffmpeg_path"] = self.settings_page.input_ffmpeg_path.text().strip()
            config["model_dir"] = self.settings_page.input_model_dir.text().strip() or DEFAULT_CONFIG["model_dir"]
            if selected_profile_id:
                for idx, item in enumerate(profiles):
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("id", "") or "").strip() != selected_profile_id:
                        continue
                    updated_item = dict(item)
                    runtime = dict(updated_item.get("runtime") or {})
                    runtime["prefer_gpu"] = config["prefer_gpu"]
                    runtime["model_dir"] = config["model_dir"]
                    updated_item["runtime"] = runtime
                    profiles[idx] = updated_item
                    break
            try:
                new_effective_model_dir = str(get_effective_model_dir(config=config) or "").strip()
            except Exception:
                new_effective_model_dir = ""
            profile_switched = bool(selected_profile_id) and selected_profile_id != previous_active_profile_id
            effective_model_dir_changed = (
                os.path.normcase(os.path.normpath(previous_effective_model_dir or ""))
                != os.path.normcase(os.path.normpath(new_effective_model_dir or ""))
            )
            migration_result = self._migrate_data_root_if_needed(current_data_root, requested_data_root)
            if migration_result is False:
                return
            config["data_root"] = requested_data_root
            if isinstance(migration_result, dict) and migration_result.get("migrated"):
                config["pending_cleanup_data_root"] = migration_result.get("old_data_root", "")
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            self.settings_page.input_data_root.setText(get_configured_data_root(config))
            effective_rules = new_sampling_fps_rules if new_sampling_fps_mode == "dynamic" else ""
            fps_changed = (
                previous_fps != new_fps
                or previous_sampling_fps_mode != new_sampling_fps_mode
                or previous_sampling_fps_rules != effective_rules
            )
            chunk_changed = (
                previous_similarity_threshold != new_similarity_threshold
                or previous_min_chunk_size != new_min_chunk_size
                or previous_min_chunk_duration != new_min_chunk_duration
                or previous_chunk_policy != new_chunk_policy
            )
            if (
                previous_prefer_gpu != config["prefer_gpu"]
                or previous_gpu_probe_unknown_keep_gpu != config["gpu_probe_unknown_keep_gpu"]
                or previous_embedding_batch_size != config["embedding_batch_size"]
                or profile_switched
                or effective_model_dir_changed
            ):
                reset_engine()
            if not config["model_dir"]:
                synced_model_dir = sync_model_dir_to_config()
                if synced_model_dir:
                    self.settings_page.input_model_dir.setText(synced_model_dir)
            if not config["ffmpeg_path"]:
                synced_path = sync_ffmpeg_path_to_config()
                if synced_path:
                    self.settings_page.input_ffmpeg_path.setText(synced_path)
            self.check_runtime_resources(show_dialog=False)
            self.push_inference_status()
            if hasattr(self, "_refresh_understanding_ui"):
                self._refresh_understanding_ui()
            self._update_sampling_preview()
            if profile_switched:
                self.refresh_library_table()
            if profile_switched and hasattr(self, "refresh_search_presets_ui"):
                self.refresh_search_presets_ui()
            save_message = self._build_settings_save_message(fps_changed, chunk_changed)
            if auto_tail_rule:
                save_message = f"{save_message}\n\n{self.texts['sampling_rules_auto_tail_added'].format(rule=auto_tail_rule)}"
            if profile_switched:
                save_message = f"{save_message}\n\n{self.texts['model_profile_switched_rebuild_hint']}"
            if isinstance(migration_result, dict) and migration_result.get("migrated"):
                save_message = f"{save_message}\n\n{self._build_data_root_migration_message(migration_result, requested_data_root)}"
            self.settings_page.lbl_status.setText(save_message)
            self.show_info_dialog(self.texts["success_title"], save_message, kind="success")
            self._set_settings_dirty(False)
            self._apply_agent_api_settings()
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _apply_agent_api_settings(self):
        if not hasattr(self, "agent_api_controller"):
            return
        from src.web.agent_api import is_agent_api_enabled

        if is_agent_api_enabled():
            url = self.agent_api_controller.start()
            if not url:
                self.show_info_dialog(
                    self.texts["error_title"],
                    self.texts.get("setting_agent_api_start_failed", "Failed to start local API."),
                    kind="warning",
                )
        else:
            self.agent_api_controller.stop()
        self._refresh_agent_api_status()

    def _refresh_agent_api_status(self):
        if not hasattr(self, "settings_page"):
            return
        running = hasattr(self, "agent_api_controller") and self.agent_api_controller.is_running()
        if running:
            url = self.agent_api_controller.get_base_url()
            text = self.texts.get("setting_agent_api_status_running", "Running: {url}").format(url=url)
            self.settings_page.btn_copy_agent_api_url.setEnabled(True)
            self.settings_page.btn_copy_agent_starter.setEnabled(True)
        else:
            text = self.texts.get("setting_agent_api_status_stopped", "Stopped")
            self.settings_page.btn_copy_agent_api_url.setEnabled(False)
            self.settings_page.btn_copy_agent_starter.setEnabled(False)
        self.settings_page.lbl_agent_api_status.setText(text)

    def _build_agent_starter_text(self) -> str:
        if not hasattr(self, "agent_api_controller") or not self.agent_api_controller.is_running():
            return ""
        from src.services.agent_starter_service import build_agent_starter_text
        from src.web.agent_api import build_health_payload

        base_url = self.agent_api_controller.get_base_url()
        health = build_health_payload()
        locale = getattr(self, "language", "zh") or "zh"
        return build_agent_starter_text(base_url, health, locale=locale)

    def copy_agent_api_url(self):
        if not hasattr(self, "agent_api_controller") or not self.agent_api_controller.is_running():
            return
        QApplication.clipboard().setText(self.agent_api_controller.get_base_url())
        self.settings_page.lbl_status.setText(
            self.texts.get("setting_agent_api_copy_url_done", "Interface URL copied.")
        )

    def copy_agent_starter(self):
        starter = self._build_agent_starter_text()
        if not starter:
            self.settings_page.lbl_status.setText(
                self.texts.get(
                    "setting_agent_api_starter_unavailable",
                    "API is not running; cannot build setup notes.",
                )
            )
            return
        QApplication.clipboard().setText(starter)
        self.settings_page.lbl_status.setText(
            self.texts.get(
                "setting_agent_api_copy_starter_done",
                "Setup notes copied.",
            )
        )

    def reset_settings(self):
        try:
            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts.get("reset_settings_confirm", "Restore parameter defaults now?"),
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return
            config = load_config()
            current_data_root = get_configured_data_root(config)
            previous_prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
            preserved_values = {
                "theme": config.get("theme"),
                "language": config.get("language"),
                "data_root": config.get("data_root"),
                "model_dir": config.get("model_dir"),
                "ffmpeg_path": config.get("ffmpeg_path"),
                "models": config.get("models"),
                "pending_cleanup_data_root": config.get("pending_cleanup_data_root"),
                "pending_cleanup_model_dir": config.get("pending_cleanup_model_dir"),
            }
            for key, value in DEFAULT_CONFIG.items():
                if key in {
                    "theme",
                    "language",
                    "data_root",
                    "model_dir",
                    "ffmpeg_path",
                    "models",
                    "pending_cleanup_data_root",
                    "pending_cleanup_model_dir",
                }:
                    continue
                config[key] = value
            config.update({k: v for k, v in preserved_values.items() if v is not None})
            requested_data_root = self._normalize_requested_data_root(str(config.get("data_root", current_data_root) or current_data_root))
            migration_result = None
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            if previous_prefer_gpu != config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"]):
                reset_engine()
            synced_model_dir = sync_model_dir_to_config()
            synced_path = sync_ffmpeg_path_to_config()
            self.load_settings_values()
            if hasattr(self, "load_understanding_settings"):
                self.load_understanding_settings()
            if synced_model_dir:
                self.settings_page.input_model_dir.setText(synced_model_dir)
            if synced_path:
                self.settings_page.input_ffmpeg_path.setText(synced_path)
            self.check_runtime_resources(show_dialog=False)
            self.push_inference_status()
            self._update_sampling_preview()
            reset_message = self.texts["reset_settings_done"]
            if isinstance(migration_result, dict) and migration_result.get("migrated"):
                reset_message = f"{reset_message}\n\n{self._build_data_root_migration_message(migration_result, requested_data_root)}"
            self.settings_page.lbl_status.setText(reset_message)
            self.show_info_dialog(self.texts["success_title"], reset_message, kind="success")
            self._apply_agent_api_settings()
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _normalize_requested_data_root(self, raw_value):
        value = str(raw_value or "").strip()
        if not value:
            value = DEFAULT_CONFIG["data_root"]
        return os.path.normpath(os.path.abspath(os.path.expanduser(value)))

    def _migrate_data_root_if_needed(self, current_data_root, requested_data_root):
        if os.path.normcase(requested_data_root) == os.path.normcase(current_data_root):
            return None
        confirmed = self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["data_root_move_confirm"].format(path=requested_data_root),
        )
        if not confirmed:
            self.settings_page.lbl_status.setText(self.texts["settings_hint"])
            return False
        return migrate_app_data_root(requested_data_root)

    def _build_data_root_migration_message(self, migration_result, fallback_new_path):
        result = dict(migration_result or {})
        old_path = str(result.get("old_data_root", "") or "").strip()
        new_path = str(result.get("new_data_root", "") or "").strip() or str(fallback_new_path or "").strip()
        if old_path and new_path:
            template = self.texts.get("data_root_move_success_detail", "")
            if template:
                return template.format(old_path=old_path, new_path=new_path)
        return self.texts["data_root_move_success"].format(path=new_path or fallback_new_path)

    def _browse_data_root(self):
        current_path = self._normalize_requested_data_root(self.settings_page.input_data_root.text())
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.texts["browse_folder"],
            current_path,
        )
        if not selected_path:
            return
        self.settings_page.input_data_root.setText(os.path.normpath(selected_path))

    def _get_pending_cleanup_data_root(self, config=None):
        current_config = dict(config or load_config())
        pending_root = str(current_config.get("pending_cleanup_data_root", "") or "").strip()
        if not pending_root:
            return ""
        pending_root = self._normalize_requested_data_root(pending_root)
        active_root = get_configured_data_root(current_config)
        if os.path.normcase(pending_root) == os.path.normcase(active_root):
            return ""
        return pending_root

    def _refresh_pending_cleanup_action(self, config=None):
        pending_root = self._get_pending_cleanup_data_root(config)
        self.settings_page.btn_cleanup_old_data_root.setVisible(bool(pending_root))
        if pending_root:
            self.settings_page.btn_cleanup_old_data_root.setToolTip(
                self.texts["cleanup_old_data_root_pending"].format(path=pending_root)
            )
        else:
            self.settings_page.btn_cleanup_old_data_root.setToolTip("")
        return pending_root

    def _get_pending_cleanup_model_dir(self, config=None):
        current_config = dict(config or load_config())
        pending = str(current_config.get("pending_cleanup_model_dir", "") or "").strip()
        if not pending:
            return ""
        pending = os.path.normpath(os.path.abspath(os.path.expanduser(pending)))
        try:
            active = get_effective_model_dir(config=current_config)
        except Exception:
            return pending
        active_norm = os.path.normpath(os.path.abspath(os.path.expanduser(str(active or "").strip())))
        if pending and active_norm and os.path.normcase(pending) == os.path.normcase(active_norm):
            return ""
        return pending

    def _refresh_pending_cleanup_model_action(self, config=None):
        pending_path = self._get_pending_cleanup_model_dir(config)
        self.settings_page.btn_cleanup_old_model_dir.setVisible(bool(pending_path))
        if pending_path:
            self.settings_page.btn_cleanup_old_model_dir.setToolTip(
                self.texts["cleanup_old_model_dir_pending"].format(path=pending_path)
            )
        else:
            self.settings_page.btn_cleanup_old_model_dir.setToolTip("")
        return pending_path

    def _refresh_pending_cleanup_actions(self, config=None):
        self._refresh_pending_cleanup_action(config)
        self._refresh_pending_cleanup_model_action(config)

    def cleanup_old_data_root(self):
        config = load_config()
        current_data_root = get_configured_data_root(config)
        target_root = self._get_pending_cleanup_data_root(config)
        try:
            if not target_root:
                message = self.texts["cleanup_old_data_root_unavailable"]
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                self._refresh_pending_cleanup_actions(config)
                return

            if os.path.normcase(target_root) == os.path.normcase(current_data_root):
                message = self.texts["cleanup_old_data_root_active_error"].format(path=target_root)
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_data_root_confirm"].format(path=target_root),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_data_root_confirm_again"].format(
                    path=target_root,
                    active_path=current_data_root,
                ),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            result = cleanup_old_data_root_service(target_root, active_data_root=current_data_root)
            config.pop("pending_cleanup_data_root", None)
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            if result.get("cleaned"):
                message = self.texts["cleanup_old_data_root_done"].format(path=result.get("old_data_dir", target_root))
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["success_title"], message, kind="success")
                return

            message = self.texts["cleanup_old_data_root_missing"].format(path=result.get("old_data_dir", target_root))
            self.settings_page.lbl_status.setText(message)
            self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
        except Exception as exc:
            self.show_error_dialog(self.texts["cleanup_old_data_root_failed"], exc)

    def cleanup_old_model_dir(self):
        config = load_config()
        target_dir = self._get_pending_cleanup_model_dir(config)
        try:
            active_dir = get_effective_model_dir(config=config)
        except Exception as exc:
            self.show_error_dialog(self.texts["cleanup_old_model_dir_failed"], exc)
            return
        try:
            if not target_dir:
                message = self.texts["cleanup_old_model_dir_unavailable"]
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                self._refresh_pending_cleanup_actions(config)
                return

            if os.path.normcase(target_dir) == os.path.normcase(os.path.normpath(active_dir)):
                message = self.texts["cleanup_old_model_dir_active_error"].format(path=target_dir)
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_model_dir_confirm"].format(path=target_dir),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            if not self.show_confirm_dialog(
                self.texts["confirm_title"],
                self.texts["cleanup_old_model_dir_confirm_again"].format(
                    path=target_dir,
                    active_path=active_dir,
                ),
                kind="warning",
            ):
                self.settings_page.lbl_status.setText(self.texts["settings_hint"])
                return

            result = cleanup_old_model_dir_service(target_dir, active_model_dir=active_dir)
            config.pop("pending_cleanup_model_dir", None)
            save_config(config)
            self._refresh_pending_cleanup_actions(config)
            if result.get("cleaned"):
                message = self.texts["cleanup_old_model_dir_done"].format(
                    path=result.get("old_model_dir", target_dir)
                )
                self.settings_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["success_title"], message, kind="success")
                return

            message = self.texts["cleanup_old_model_dir_missing"].format(
                path=result.get("old_model_dir", target_dir)
            )
            self.settings_page.lbl_status.setText(message)
            self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
        except Exception as exc:
            self.show_error_dialog(self.texts["cleanup_old_model_dir_failed"], exc)

    def _browse_ffmpeg_path(self):
        current_path = self.settings_page.input_ffmpeg_path.text().strip()
        initial_dir = os.path.dirname(current_path) if current_path else ""
        selected_path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["browse_file"],
            initial_dir,
            "Executable Files (*.exe);;All Files (*.*)",
        )
        if not selected_path:
            return
        self.settings_page.input_ffmpeg_path.setText(os.path.normpath(selected_path))

    def _browse_model_dir(self):
        current_path = self.settings_page.input_model_dir.text().strip()
        initial_dir = current_path if current_path and os.path.isdir(current_path) else ""
        selected_path = QFileDialog.getExistingDirectory(
            self,
            self.texts["browse_folder"],
            initial_dir,
        )
        if not selected_path:
            return
        self.settings_page.input_model_dir.setText(os.path.normpath(selected_path))

    def _migrate_model_root(self):
        t = self.texts
        try:
            config = load_config()
            source = get_effective_model_dir(config=config)
        except Exception as exc:
            self.show_error_dialog(t["model_root_move_failed"], exc)
            return
        if not source or not os.path.isdir(source):
            self.show_info_dialog(t["warning_title"], t["model_root_move_source_missing"], kind="warning")
            return
        initial = source
        dest = QFileDialog.getExistingDirectory(self, t["model_root_move_pick_target"], initial)
        if not dest:
            return
        dest = os.path.normpath(os.path.abspath(os.path.expanduser(dest)))
        if os.path.normcase(dest) == os.path.normcase(source):
            self.show_info_dialog(t["warning_title"], t["model_root_move_same_path"], kind="warning")
            return
        if not self.show_confirm_dialog(t["confirm_title"], t["model_root_move_confirm"].format(source=source, dest=dest)):
            self.settings_page.lbl_status.setText(t["settings_hint"])
            return
        try:
            result = migrate_model_root(dest)
        except Exception as exc:
            self.show_error_dialog(t["model_root_move_failed"], exc)
            return
        if not result.get("migrated") and result.get("reason") == "same_path":
            return
        self.load_settings_values()
        synced = sync_model_dir_to_config()
        if synced:
            self.settings_page.input_model_dir.setText(synced)
        self.check_runtime_resources(show_dialog=False)
        self.push_inference_status()
        old_path = str(result.get("old_model_dir", "") or "")
        new_path = str(result.get("new_model_dir", "") or "")
        detail = str(t.get("model_root_move_success_detail") or "").strip()
        if detail and old_path and new_path:
            msg = detail.format(old_path=old_path, new_path=new_path)
        else:
            msg = t["model_root_move_success"].format(path=new_path or dest)
        self.settings_page.lbl_status.setText(msg)
        self.show_info_dialog(t["success_title"], msg, kind="success")

    def _bind_sampling_preview_signals(self):
        if getattr(self, "_sampling_preview_bound", False):
            return
        self._sampling_preview_bound = True
        self.settings_page.input_fps.valueChanged.connect(self._update_sampling_preview)
        self.settings_page.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_preview_changed)
        self.settings_page.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_feedback_changed)
        self.settings_page.input_sampling_fps_rules.textChanged.connect(self._update_sampling_preview)
        self.settings_page.input_sampling_fps_rules.textChanged.connect(self._update_sampling_rules_feedback)

    def _handle_sampling_mode_preview_changed(self, *_args):
        self._ensure_dynamic_sampling_defaults()
        self._update_sampling_preview()

    def _handle_sampling_mode_feedback_changed(self, *_args):
        self._ensure_dynamic_sampling_defaults()
        self._update_sampling_rules_feedback()

    def _open_sampling_rules_dialog(self):
        dialog = SamplingRulesDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            rules_text=self.settings_page.get_sampling_fps_rules_text() or DEFAULT_CONFIG["sampling_fps_rules"],
        )
        if dialog.exec():
            self.settings_page.set_sampling_fps_rules_text(dialog.rules_text())
            self._update_sampling_rules_feedback()
            self._update_sampling_preview()

    def _ensure_dynamic_sampling_defaults(self):
        if normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode()) != "dynamic":
            return
        current_rules_text = normalize_sampling_fps_rules_text(self.settings_page.get_sampling_fps_rules_text())
        if current_rules_text:
            return
        self.settings_page.set_sampling_fps_rules_text(DEFAULT_CONFIG["sampling_fps_rules"])

    def _update_sampling_rules_feedback(self):
        current_rules_text = self.settings_page.get_sampling_fps_rules_text()
        rules_text = normalize_sampling_fps_rules_text(current_rules_text)
        sampling_fps_mode = normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode())
        if sampling_fps_mode == "dynamic":
            rules_text = ensure_sampling_fps_rules_open_tail(rules_text, default_tail_fps=1)
        if current_rules_text != rules_text:
            self.settings_page.set_sampling_fps_rules_text(rules_text)
            return
        if sampling_fps_mode != "dynamic":
            self.settings_page.set_sampling_rules_error_state(False)
            return

        is_valid, _ = validate_sampling_fps_rules_full_coverage(rules_text)
        if rules_text and not is_valid:
            self.settings_page.set_sampling_rules_error_state(True)
            return

        self.settings_page.set_sampling_rules_error_state(False)

    def _update_sampling_preview(self):
        base_fps = float(self.settings_page.input_fps.value())
        sampling_fps_mode = normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode())
        rules_text = normalize_sampling_fps_rules_text(self.settings_page.get_sampling_fps_rules_text())
        if sampling_fps_mode == "dynamic":
            rules_text = ensure_sampling_fps_rules_open_tail(rules_text, default_tail_fps=1)
        rules_valid, _ = validate_sampling_fps_rules_full_coverage(rules_text)
        if sampling_fps_mode == "dynamic" and rules_text and not rules_valid:
            return
        samples = [
            ("2m", 120.0),
            ("10m", 600.0),
            ("30m", 1800.0),
            ("2h", 7200.0),
        ]
        preview_parts = []
        for label, duration_sec in samples:
            fps_value = resolve_sampling_fps(
                duration_sec=duration_sec,
                config={
                    "fps": base_fps,
                    "sampling_fps_mode": sampling_fps_mode,
                    "sampling_fps_rules": rules_text,
                },
            )
            frame_count = max(1, int(round(duration_sec * fps_value)))
            if self.language == "zh":
                preview_parts.append(f"{label} -> {fps_value:.2f} FPS / ~{frame_count}\u5e27")
            else:
                preview_parts.append(f"{label} -> {fps_value:.2f} FPS / ~{frame_count} frames")

        if self.language != "zh":
            prefix = "Fixed sampling" if sampling_fps_mode == "fixed" else "Duration-range sampling"
        else:
            prefix = "\u56fa\u5b9a\u91c7\u6837" if sampling_fps_mode == "fixed" else "\u603b\u957f\u5ea6\u533a\u95f4\u91c7\u6837"
        self.settings_page.hint_sampling_fps_preview.setText(f"{prefix}: " + " | ".join(preview_parts))

    def _build_settings_save_message(self, fps_changed, chunk_changed):
        if fps_changed and chunk_changed:
            return self.texts["settings_saved_mixed_rebuild"]
        if fps_changed:
            return self.texts["settings_saved_full_rebuild"]
        if chunk_changed:
            return self.texts["settings_saved_chunk_rebuild"]
        return self.texts["settings_saved_no_rebuild"]
