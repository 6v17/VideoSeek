"""Runtime resources, GPU/engine diagnostics, and page banners — extracted from MainWindow."""

from __future__ import annotations

import json
import os
import webbrowser

from PySide6.QtWidgets import QApplication

from src.app.app_meta import get_app_meta
from src.app.config import get_configured_data_root, load_config
from src.core.clip_embedding import get_engine_runtime_status
from src.core.extract_frames import get_frame_decode_status
from src.utils import get_configured_model_dir, get_ffmpeg_status_text, open_folder_in_explorer
from ui.dialogs import AppMessageDialog
from ui.widgets.styles import set_runtime_banner_warn


class RuntimeGuiMixin:
    """Inference hint, diagnostics clipboard/dialog, resource controller entry points, banners."""

    def open_runtime_resource_folder(self):
        from src.services.runtime_resource_service import ensure_runtime_resource_dirs

        target_dirs = ensure_runtime_resource_dirs()
        for target_dir in target_dirs:
            open_folder_in_explorer(target_dir)

    def _update_inference_backend_hint(self, status=None):
        config = load_config()
        if status is None:
            status = get_engine_runtime_status()
        else:
            status = dict(status)
        backend_text = ""
        show_help_link = False

        if status["initialized"]:
            backend_text = status["backend"] or ""
            if status["warning"]:
                issue_text = self._build_runtime_issue_summary(status)
                if str(status.get("backend") or "").upper() == "GPU":
                    backend_text = f"{backend_text} ({issue_text})".strip()
                else:
                    backend_text = self.texts["setting_inference_cpu_issue"].format(issue=issue_text)
                show_help_link = True
                self.settings_page.hint_inference_backend.setProperty("state", "warn")
            elif str(status["backend"]).upper() == "GPU":
                self.settings_page.hint_inference_backend.setProperty("state", "ok")
            else:
                self.settings_page.hint_inference_backend.setProperty("state", "neutral")
        else:
            self.settings_page.hint_inference_backend.setProperty("state", "neutral")

        backend_label = (
            self.texts["setting_inference_backend"].format(backend=backend_text)
            if backend_text else self.texts["setting_inference_backend"].format(
                backend=self.texts["setting_inference_uninitialized"]
            )
        )
        if show_help_link:
            backend_label = f"{backend_label} | {self.texts['setting_gpu_runtime_link_only']}"
        ffmpeg_label = self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        data_label = self._build_data_storage_status_text(config)
        self.settings_page.set_runtime_status_texts(backend_label, ffmpeg_label, data_label)

    def _build_runtime_issue_summary(self, status):
        issue = str(status.get("issue") or "").strip()
        diagnostics = dict(status.get("diagnostics") or {})
        issue_text = self._get_runtime_issue_text(issue or diagnostics.get("issue"))

        missing_dlls = [str(item) for item in diagnostics.get("missing_dlls") or [] if str(item).strip()]
        if missing_dlls:
            return f"{issue_text}: {', '.join(missing_dlls)}"

        missing_msvc_dlls = [str(item) for item in diagnostics.get("missing_msvc_dlls") or [] if str(item).strip()]
        if missing_msvc_dlls:
            return f"{issue_text}: {', '.join(missing_msvc_dlls)}"

        available_providers = [str(item) for item in diagnostics.get("available_providers") or [] if str(item).strip()]
        if issue == "directml" and available_providers:
            return f"{issue_text}: {', '.join(available_providers)}"

        return issue_text

    def _build_runtime_diagnostics_detail(self, status):
        diagnostics = dict(status.get("diagnostics") or {})
        lines = []
        backend = str(status.get("backend") or "").strip() or self.texts.get("setting_inference_uninitialized", "Not initialized")
        lines.append(f"Backend: {backend}")
        lines.append(f"Initialized: {bool(status.get('initialized'))}")
        lines.append(f"Prefer GPU: {bool(status.get('prefer_gpu'))}")
        decode_status = get_frame_decode_status(load_config())
        lines.append(
            self.texts.get("setting_runtime_detail_frame_decode", "Frame decode: requested={requested}, d3d11va available={available}, last={last}").format(
                requested=bool(decode_status.get("requested")),
                available=bool(decode_status.get("d3d11va_available")),
                last=str(decode_status.get("last_backend") or "cpu"),
            )
        )
        issue_text = self._build_runtime_issue_summary(status)
        if issue_text:
            lines.append(issue_text)

        missing_dlls = [str(item) for item in diagnostics.get("missing_dlls") or [] if str(item).strip()]
        if missing_dlls:
            lines.append(self.texts.get("setting_runtime_detail_missing_dlls", "Missing DLLs: {items}").format(items=", ".join(missing_dlls)))

        missing_msvc_dlls = [str(item) for item in diagnostics.get("missing_msvc_dlls") or [] if str(item).strip()]
        if missing_msvc_dlls:
            lines.append(self.texts.get("setting_runtime_detail_missing_msvc_dlls", "Missing VC++ DLLs: {items}").format(items=", ".join(missing_msvc_dlls)))

        available_providers = [str(item) for item in diagnostics.get("available_providers") or [] if str(item).strip()]
        if available_providers:
            lines.append(self.texts.get("setting_runtime_detail_available_providers", "Available providers: {items}").format(items=", ".join(available_providers)))

        windows_build = diagnostics.get("windows_build")
        if windows_build:
            lines.append(self.texts.get("setting_runtime_detail_windows_build", "Windows build: {value}").format(value=windows_build))

        probe_stage = str(diagnostics.get("probe_stage") or "").strip()
        if probe_stage:
            probe_stage_key = f"setting_runtime_probe_stage_{probe_stage}"
            probe_stage_text = self.texts.get(probe_stage_key, probe_stage)
            lines.append(self.texts.get("setting_runtime_detail_probe_stage", "Failure stage: {value}").format(value=probe_stage_text))

        probe_exception_type = str(diagnostics.get("probe_exception_type") or "").strip()
        probe_exception_message = str(diagnostics.get("probe_exception_message") or "").strip()
        probe_exception = ": ".join(part for part in [probe_exception_type, probe_exception_message] if part)
        if probe_exception:
            lines.append(self.texts.get("setting_runtime_detail_probe_exception", "Exception: {value}").format(value=probe_exception))

        failure_kind = str(diagnostics.get("failure_kind") or "").strip()
        if failure_kind:
            lines.append(f"Failure kind: {failure_kind}")

        active_providers = diagnostics.get("active_providers")
        if isinstance(active_providers, dict) and active_providers:
            lines.append(f"Active providers: {json.dumps(active_providers, ensure_ascii=False)}")

        return "\n".join(line for line in lines if line)

    def _build_runtime_diagnostics_payload(self, status):
        normalized_status = dict(status or {})
        return {
            "backend": normalized_status.get("backend", ""),
            "initialized": bool(normalized_status.get("initialized")),
            "prefer_gpu": normalized_status.get("prefer_gpu"),
            "issue": normalized_status.get("issue", ""),
            "warning": normalized_status.get("warning", ""),
            "summary": self._build_runtime_issue_summary(normalized_status),
            "detail": self._build_runtime_diagnostics_detail(normalized_status),
            "diagnostics": dict(normalized_status.get("diagnostics") or {}),
        }

    def _get_runtime_issue_text(self, issue):
        issue_key_map = {
            "directml": "setting_runtime_issue_directml",
            "directx": "setting_runtime_issue_directx",
            "windows": "setting_runtime_issue_windows",
            "windows_version": "setting_runtime_issue_windows_version",
            "msvc": "setting_runtime_issue_msvc",
            "probe_timeout": "setting_runtime_issue_probe_timeout",
            "probe_launch_failed": "setting_runtime_issue_probe_launch_failed",
            "visual_provider_not_activated": "setting_runtime_issue_visual_provider_not_activated",
            "text_provider_not_activated": "setting_runtime_issue_text_provider_not_activated",
            "visual_probe_failed": "setting_runtime_issue_visual_probe_failed",
            "text_probe_failed": "setting_runtime_issue_text_probe_failed",
            "session_init_failed": "setting_runtime_issue_session_init_failed",
        }
        text_key = issue_key_map.get(str(issue or "").strip(), "setting_runtime_issue_unknown")
        return self.texts.get(text_key, self.texts.get("setting_runtime_issue_unknown", "DirectML runtime"))

    def copy_runtime_diagnostics(self, status=None):
        if status is None:
            status = get_engine_runtime_status()
        payload = self._build_runtime_diagnostics_payload(status)
        QApplication.clipboard().setText(json.dumps(payload, ensure_ascii=False, indent=2))
        self.settings_page.lbl_status.setText(
            self.texts.get(
                "setting_copy_runtime_diagnostics_done",
                self.texts.get("details_copy_done", "Copied to clipboard."),
            )
        )

    def show_runtime_diagnostics(self):
        status = get_engine_runtime_status()
        payload = self._build_runtime_diagnostics_payload(status)
        lines = []
        if payload["summary"]:
            lines.append(payload["summary"])
        if payload["detail"] and payload["detail"] != payload["summary"]:
            lines.append(payload["detail"])
        if payload["warning"]:
            lines.append(payload["warning"])
        text = "\n\n".join(line for line in lines if line).strip()
        if not text:
            text = json.dumps(payload, ensure_ascii=False, indent=2)
        dialog = AppMessageDialog(
            self.texts.get("setting_show_runtime_diagnostics_title", "GPU diagnostics"),
            text,
            kind="info",
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            confirm=True,
            cancel_text=self.texts["close"],
            confirm_text=self.texts.get("setting_copy_runtime_diagnostics", "Copy GPU diagnostics"),
        )
        dialog.exec()
        if dialog.confirmed():
            self.copy_runtime_diagnostics(status)

    def _build_data_storage_status_text(self, config):
        normalized_config = dict(config or {})
        data_root = str(normalized_config.get("data_root", "") or "").strip()
        if data_root:
            data_root = os.path.normpath(data_root)
        else:
            data_root = get_configured_data_root(normalized_config)
        return self.texts["setting_data_active"].format(data_root=data_root)

    def _handle_runtime_resource_exit(self):
        self.startup_cancelled = True
        self.close()

    def _start_runtime_warmup(self):
        self.search_controller.start_warmup()
        self.preview_controller.start_warmup()

    def check_runtime_resources(self, show_dialog=True):
        return self.runtime_resource_controller.check_resources(show_dialog=show_dialog)

    def start_runtime_resource_download(self):
        self.runtime_resource_controller.start_download()

    def open_runtime_resource_dialog(self):
        self.runtime_resource_controller.show_manage_dialog()

    def open_model_package_download_page(self):
        app_meta = get_app_meta()
        target_url = str(app_meta.get("model_manifest_url", "") or "").strip()
        if not target_url:
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts["download_models_unavailable"],
                kind="warning",
            )
            return
        webbrowser.open(target_url)

    def _finish_runtime_resource_download(self, result):
        self.check_runtime_resources(show_dialog=False)
        self.settings_page.input_model_dir.setText(result.get("model_dir", get_configured_model_dir()))
        if result.get("ffmpeg_path"):
            self.settings_page.input_ffmpeg_path.setText(result["ffmpeg_path"])
        self.push_inference_status()

    def _apply_runtime_resource_status(self, status):
        model_ready = bool(status.get("model_ready", self.ui_state.model_ready))
        resources_ready = bool(status.get("resources_ready", self.ui_state.resources_ready))
        self.search_page.btn_search.setEnabled(model_ready)
        self.network_search_controller.refresh_status()
        self.library_page.btn_sync_db.setEnabled(resources_ready)
        if resources_ready:
            if getattr(self, "_startup_complete", False):
                self._start_runtime_warmup()
            else:
                self._defer_runtime_warmup = True
        if not resources_ready:
            status_text = self.texts["model_features_disabled"]
            self.search_page.lbl_status.setText(status_text)
            self.link_page.lbl_build_status.setText(status_text)
            self.link_page.lbl_search_status.setText(status_text)
            self.library_page.lbl_status.setText(status_text)
        self._update_runtime_banner(status)

    def _update_runtime_banner(self, status):
        model_ready = bool(status.get("model_ready"))
        ffmpeg_ready = bool(status.get("ffmpeg_ready"))
        if (not model_ready) and (not ffmpeg_ready):
            missing_text = self.texts.get("models_missing_generic_both", "Model and FFmpeg are not ready.")
        elif not model_ready:
            missing_text = self.texts.get("models_missing_generic_model", "Model resources are missing.")
        elif not ffmpeg_ready:
            missing_text = self.texts.get("models_missing_generic_ffmpeg", "FFmpeg is missing.")
        else:
            missing_text = self.texts.get("models_missing_generic_unknown", "Runtime resources are incomplete.")
        banner_text = self.texts.get("runtime_banner_missing", "Runtime resources are not ready: {missing}").format(missing=missing_text)
        action_text = self.texts.get("runtime_banner_open_import", "Go Import")
        for page in (self.search_page, self.link_page, self.library_page, self.settings_page):
            banner = page.header.runtime_banner
            banner_label = page.header.runtime_banner_text
            banner_btn = page.header.runtime_banner_action
            banner_btn.setText(action_text)
            if status.get("resources_ready"):
                set_runtime_banner_warn(banner, False)
                banner.hide()
            else:
                banner_label.setText(banner_text)
                set_runtime_banner_warn(banner, True)
                banner_btn.show()
                banner.show()
