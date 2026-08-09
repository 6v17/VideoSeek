"""Model package import, FFmpeg side-import, and profile removal — extracted from MainWindow."""

from __future__ import annotations

import os
import shutil

from PySide6.QtWidgets import QFileDialog

from src.app.config import load_config, save_config
from src.core.clip_embedding import reset_engine
from src.services.model_package_service import (
    rediscover_model_profiles as run_rediscover_model_profiles,
    remove_model_profile,
)
from src.storage.config_store import get_active_model_profile, get_effective_model_dir, resolve_provider_dir
from src.utils import get_configured_ffmpeg_target_path
from ui.workers import ModelPackageImportWorker


class ModelPackagesGuiMixin:
    """ZIP/manifest import via worker, ffmpeg.exe drop-in, and active profile removal."""

    def rediscover_model_profiles(self):
        """Scan model_dir for complete packs and repair the profile switcher."""
        try:
            result = run_rediscover_model_profiles()
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("model_rediscover_failed", "重新探测模型失败"),
                exc,
            )
            return
        try:
            reset_engine()
        except Exception:
            pass
        config = load_config()
        if hasattr(self, "_populate_model_profile_options"):
            self._populate_model_profile_options(config)
        if hasattr(self, "refresh_runtime_resource_ui"):
            self.refresh_runtime_resource_ui(sync_dialog=True)
        if hasattr(self, "push_inference_status"):
            self.push_inference_status()

        imported = int(result.get("imported", 0) or 0)
        updated = int(result.get("updated", 0) or 0)
        removed = list(result.get("removed") or [])
        errors = list(result.get("errors") or [])
        active = str(result.get("active_profile", "") or "").strip()
        if imported or updated or removed:
            message = self.texts.get(
                "model_rediscover_done",
                "已重新探测模型：新增 {imported}，更新 {updated}，移除不完整配置 {removed}。当前：{active}",
            ).format(
                imported=imported,
                updated=updated,
                removed=len(removed),
                active=active or "-",
            )
            if errors:
                message = f"{message}\n\n" + "\n".join(str(item) for item in errors[:6])
            self.show_info_dialog(self.texts["success_title"], message, kind="success")
            return
        if errors:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("model_rediscover_none", "模型目录下没有发现完整可用的模型包。")
                + "\n\n"
                + "\n".join(str(item) for item in errors[:8]),
                kind="warning",
            )
            return
        self.show_info_dialog(
            self.texts.get("warning_title", "Warning"),
            self.texts.get("model_rediscover_none", "模型目录下没有发现完整可用的模型包。"),
            kind="warning",
        )

    def parse_model_packages(self, selected_files=None, scan_only=False):
        config = load_config()
        try:
            model_root = self._resolve_model_package_root(config)
            if not model_root:
                raise ValueError("Active profile model_dir is empty.")

            if selected_files is not None:
                selected_files = [str(path or "").strip() for path in (selected_files or []) if str(path or "").strip()]
            elif not scan_only:
                selected_files, _ = QFileDialog.getOpenFileNames(
                    self,
                    self.texts.get("model_upload_package", "Upload Model Package"),
                    "",
                    "Runtime Package (*.zip *.sha256 *.exe);;All Files (*.*)",
                )
                selected_files = [str(path or "").strip() for path in (selected_files or []) if str(path or "").strip()]
            else:
                selected_files = []
        except Exception as exc:
            self.show_error_dialog(self.texts.get("parse_model_package_failed", "Failed to parse model package."), exc)
            return
        ffmpeg_files = [
            path for path in selected_files
            if path.lower().endswith(".exe") and os.path.basename(path).strip().lower() == "ffmpeg.exe"
        ]
        model_files = [path for path in selected_files if not path.lower().endswith(".exe")]
        ffmpeg_updated = False
        ffmpeg_error = ""
        if ffmpeg_files:
            try:
                self._import_ffmpeg_executable(ffmpeg_files[0], config)
                ffmpeg_updated = True
            except Exception as exc:
                ffmpeg_error = str(exc)
        if ffmpeg_error:
            self.show_error_dialog(
                self.texts.get("parse_model_package_failed", "Failed to parse model package."),
                ffmpeg_error,
            )
            return
        self._ffmpeg_imported_with_package = bool(ffmpeg_updated)
        if not model_files and not scan_only:
            self.refresh_runtime_resource_ui(sync_dialog=True)
            self.push_inference_status()
            if ffmpeg_updated:
                self.show_info_dialog(
                    self.texts["success_title"],
                    self.texts.get("ffmpeg_import_done", "FFmpeg imported successfully."),
                    kind="success",
                )
            return
        self._start_model_package_import(model_root, model_files, scan_only)

    def _import_ffmpeg_executable(self, ffmpeg_file, config):
        source_path = os.path.normpath(os.path.abspath(os.fspath(ffmpeg_file)))
        if os.path.basename(source_path).strip().lower() != "ffmpeg.exe":
            raise RuntimeError("Selected executable is not ffmpeg.exe")
        if not os.path.exists(source_path):
            raise RuntimeError(f"FFmpeg file not found: {source_path}")
        target_path = os.path.normpath(get_configured_ffmpeg_target_path(config=config))
        target_dir = os.path.dirname(target_path)
        if target_dir:
            os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(source_path, target_path)
        config["ffmpeg_path"] = target_path
        save_config(config)

    def _resolve_model_package_root(self, config):
        config_root = str(config.get("model_dir", "") or "").strip()
        active_root = str(get_effective_model_dir(config=config) or "").strip()
        model_root = config_root or active_root
        if not model_root:
            return ""
        model_root = os.path.normpath(os.path.abspath(os.fspath(model_root)))
        # Compatibility: if runtime.model_dir was accidentally saved as provider/variant leaf, step back to root.
        try:
            profile = get_active_model_profile(config=config)
            provider = str(profile.get("provider", "") or "").strip()
            runtime = dict(profile.get("runtime") or {})
            variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip()
            if provider and variant:
                provider_dir = resolve_provider_dir(provider)
                expected_tail = os.path.normcase(os.path.normpath(os.path.join(provider_dir, variant)))
                if os.path.normcase(model_root).endswith(expected_tail):
                    parent = os.path.dirname(os.path.dirname(model_root))
                    if parent:
                        model_root = parent
        except Exception:
            pass
        return model_root

    def _start_model_package_import(self, model_root, selected_files, scan_only):
        if self._model_package_import_worker and self._model_package_import_worker.isRunning():
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts.get("model_import_in_progress", "Model package import is already running."),
                kind="warning",
            )
            return
        worker = ModelPackageImportWorker(model_root, selected_files=selected_files, scan_only=scan_only)
        self._model_package_import_worker = worker
        worker.progress_signal.connect(self._on_model_package_import_progress)
        worker.finished_signal.connect(self._on_model_package_import_finished)
        worker.error_signal.connect(self._on_model_package_import_error)
        worker.finished.connect(lambda active_worker=worker: self._cleanup_model_package_import_worker(active_worker))
        self._on_model_package_import_progress(0, self.texts.get("model_download_starting", "Starting..."))
        worker.start()

    def _active_model_import_dialog(self):
        dialog = getattr(self.runtime_resource_controller, "dialog", None)
        if dialog is None or not dialog.isVisible():
            return None
        return dialog

    def _on_model_package_import_progress(self, value, text):
        dialog = self._active_model_import_dialog()
        if dialog is not None:
            dialog.set_import_progress_state(max(0, min(100, int(value))), str(text or ""))
        else:
            self.settings_page.lbl_status.setText(str(text or ""))

    def _on_model_package_import_finished(self, result):
        imported = int(result.get("imported", 0))
        updated = int(result.get("updated", 0))
        errors = [str(item) for item in result.get("errors", []) if str(item).strip()]
        checksum_verified_count = int(result.get("checksum_verified_count", 0))
        dialog = self._active_model_import_dialog()
        if imported or updated:
            reset_engine()
            self.load_settings_values()
            self.refresh_runtime_resource_ui(sync_dialog=True)
            self.push_inference_status()
            if hasattr(self, "load_understanding_settings"):
                if hasattr(self, "_invalidate_understanding_status_cache"):
                    self._invalidate_understanding_status_cache()
                self.load_understanding_settings()
            elif hasattr(self, "_refresh_understanding_ui"):
                if hasattr(self, "_invalidate_understanding_status_cache"):
                    self._invalidate_understanding_status_cache()
                self._refresh_understanding_ui()
            message = self.texts.get("parse_model_package_done", "Model packages parsed: +{imported}, updated {updated}.").format(
                imported=imported,
                updated=updated,
            )
            if checksum_verified_count > 0:
                message = f"{message}\n\nChecksums verified: {checksum_verified_count}"
            if self._ffmpeg_imported_with_package:
                message = f"{message}\n\n{self.texts.get('ffmpeg_import_done', 'FFmpeg imported successfully.')}"
            if dialog is not None and not self.ui_state.resources_ready:
                dialog.set_import_success_state(
                    self.texts.get("parse_model_package_done", "Model packages parsed: +{imported}, updated {updated}.").format(
                        imported=imported,
                        updated=updated,
                    )
                )
            if errors:
                skipped_note = self.texts.get(
                    "parse_model_package_skipped",
                    "Some other model packages were skipped:",
                )
                message = f"{message}\n\n{skipped_note}\n" + "\n".join(errors[:3])
            self.show_info_dialog(self.texts["success_title"], message, kind="success")
            self._ffmpeg_imported_with_package = False
            return
        if errors:
            if dialog is not None:
                status = self.runtime_resource_controller.get_status_snapshot()
                dialog.set_error_state(
                    "\n".join(errors[:3]),
                    status["display_files"],
                    "",
                    download_enabled=status["download_enabled"],
                )
            self.show_info_dialog(self.texts["warning_title"], "\n".join(errors[:3]), kind="warning")
            self._ffmpeg_imported_with_package = False
            return
        if dialog is not None:
            dialog.set_manage_state()
        self.show_info_dialog(
            self.texts["warning_title"],
            self.texts.get("parse_model_package_none", "No model_manifest.json found."),
            kind="warning",
        )
        self._ffmpeg_imported_with_package = False

    def _on_model_package_import_error(self, error_text):
        dialog = self._active_model_import_dialog()
        if dialog is not None:
            status = self.runtime_resource_controller.get_status_snapshot()
            dialog.set_error_state(
                str(error_text or ""),
                status["display_files"],
                "",
                download_enabled=status["download_enabled"],
            )
        self.show_error_dialog(
            self.texts.get("parse_model_package_failed", "Failed to parse model package."),
            error_text,
        )
        self._ffmpeg_imported_with_package = False

    def _cleanup_model_package_import_worker(self, worker):
        if self._model_package_import_worker is worker:
            self._model_package_import_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    def remove_current_model_profile(self):
        selected_profile_id = str(self.settings_page.input_active_model_profile.currentData() or "").strip()
        if not selected_profile_id:
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts.get("remove_model_profile_none", "No model profile is selected."),
                kind="warning",
            )
            return
        config = load_config()
        models = dict(config.get("models") or {})
        profiles = [item for item in models.get("profiles", []) if isinstance(item, dict)]
        remaining_after_remove = max(0, len(profiles) - 1)
        confirm_text = self.texts.get(
            "remove_model_profile_confirm",
            "Remove the current model profile and delete its model resources and model-scoped data?",
        )
        if remaining_after_remove == 0:
            confirm_text = (
                f"{confirm_text}\n\n"
                + self.texts.get(
                    "remove_model_profile_last_warning",
                    "This is the last available model profile. After removal, no model will be available until you import one.",
                )
            )
        if not self.show_confirm_dialog(self.texts["confirm_title"], confirm_text):
            return
        try:
            # Release ONNX handles before directory deletion (service also resets).
            reset_engine()
            result = remove_model_profile(selected_profile_id)
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("remove_model_profile_failed", "Failed to remove model profile."),
                exc,
            )
            return

        refresh_error = ""
        try:
            reset_engine()
            self.load_settings_values()
            self.refresh_runtime_resource_ui(sync_dialog=False)
            self.push_inference_status()
            self.refresh_library_table()
        except Exception as exc:
            refresh_error = str(exc)
            try:
                self.load_settings_values()
            except Exception:
                pass

        active_profile = str(result.get("active_profile", "") or "").strip()
        removed_resource_dir = str(result.get("removed_resource_dir", "") or "").strip()
        removed_asset_dir = str(result.get("removed_asset_dir", "") or "").strip()
        summary = self.texts.get(
            "remove_model_profile_done",
            "Model removed. Active profile: {active}.",
        ).format(active=active_profile or "none")
        details = []
        if removed_resource_dir:
            details.append(f"Resource dir: {removed_resource_dir}")
        if removed_asset_dir:
            details.append(f"Data dir: {removed_asset_dir}")
        for warning in list(result.get("delete_warnings") or []):
            text = str(warning or "").strip()
            if text:
                details.append(text)
        if refresh_error:
            details.append(refresh_error)
        message = summary if not details else f"{summary}\n\n" + "\n".join(details)
        kind = "warning" if (refresh_error or result.get("delete_warnings")) else "success"
        self.show_info_dialog(self.texts["success_title"], message, kind=kind)
