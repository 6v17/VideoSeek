"""Runtime resources, GPU/engine diagnostics, and page banners — extracted from MainWindow."""

from __future__ import annotations

import json
import os
import webbrowser

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from src.app.app_meta import get_app_meta
from src.app.config import get_configured_data_root, load_config
from src.app.logging_utils import get_logger
from src.utils import get_configured_model_dir, get_ffmpeg_status_text, open_folder_in_explorer
from ui.dialogs import AppMessageDialog
from ui.widgets.styles import set_runtime_banner_warn

logger = get_logger("gui.runtime")


class RuntimeGuiMixin:
    """Inference hint, diagnostics clipboard/dialog, resource controller entry points, banners."""

    def _iter_runtime_banner_pages(self):
        """Pages whose ``PageHeader`` shows the shared runtime-resource banner.

        Includes plugin pages (clone, etc.) so optional nav surfaces get the same
        FFmpeg / model warning as search and library.
        """
        seen: set[int] = set()
        pages = [
            getattr(self, "search_page", None),
            getattr(self, "link_page", None),
            getattr(self, "library_page", None),
            getattr(self, "understanding_page", None),
            getattr(self, "settings_page", None),
        ]
        for page in getattr(self, "_plugin_page_widgets", {}).values():
            pages.append(page)
        for page in pages:
            if page is None:
                continue
            marker = id(page)
            if marker in seen:
                continue
            header = getattr(page, "header", None)
            if header is None:
                continue
            if getattr(header, "runtime_banner_action", None) is None:
                continue
            seen.add(marker)
            yield page

    def open_runtime_resource_folder(self):
        from src.services.runtime_resource_service import ensure_runtime_resource_dirs

        target_dirs = ensure_runtime_resource_dirs()
        for target_dir in target_dirs:
            open_folder_in_explorer(target_dir)

    def _is_gpu_backend_label(self, backend):
        text = str(backend or "").strip().upper()
        if not text or text == "CPU":
            return False
        return True

    def _update_inference_backend_hint(self, status=None):
        from src.core.clip_embedding import get_engine_runtime_status

        config = load_config()
        if status is None:
            status = get_engine_runtime_status()
        else:
            status = dict(status)
        backend_text = ""
        show_help_link = False

        if status["initialized"]:
            backend_text = status["backend"] or ""
            is_gpu = self._is_gpu_backend_label(backend_text)
            if status["warning"]:
                issue_text = self._build_runtime_issue_summary(status)
                if is_gpu:
                    backend_text = f"{backend_text} ({issue_text})".strip()
                else:
                    backend_text = self.texts["setting_inference_cpu_issue"].format(issue=issue_text)
                show_help_link = True
                self.settings_page.hint_inference_backend.setProperty("state", "warn")
            elif is_gpu:
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
        if hasattr(self, "_refresh_search_model_display"):
            self._refresh_search_model_display()

    def _resolve_runtime_issue_key(self, status):
        """Pick the issue code that should be shown to users.

        Healthy DirectML sessions may still carry diagnostics.issue=\"unknown\" from an
        earlier soft probe; that must not be reported as a current fault.
        """
        normalized = dict(status or {})
        issue = str(normalized.get("issue") or "").strip()
        warning = str(normalized.get("warning") or "").strip()
        diagnostics = dict(normalized.get("diagnostics") or {})
        diag_issue = str(diagnostics.get("issue") or "").strip()
        effective = issue or diag_issue
        if not effective:
            return ""
        if effective == "unknown" and self._is_gpu_backend_label(normalized.get("backend")) and not warning:
            return ""
        return effective

    def _build_runtime_issue_summary(self, status):
        diagnostics = dict(status.get("diagnostics") or {})
        issue = self._resolve_runtime_issue_key(status)
        issue_text = self._get_runtime_issue_text(issue)
        if not issue_text:
            return ""

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
        backend = str(status.get("backend") or "").strip() or self.texts.get(
            "setting_inference_uninitialized", "Not initialized"
        )
        lines.append(
            self.texts.get("setting_runtime_detail_backend", "Backend: {value}").format(value=backend)
        )
        initialized = bool(status.get("initialized"))
        lines.append(
            self.texts.get("setting_runtime_detail_initialized", "Engine: {value}").format(
                value=self.texts.get(
                    "setting_runtime_detail_initialized_yes" if initialized else "setting_runtime_detail_initialized_no",
                    "Ready" if initialized else "Not initialized",
                )
            )
        )
        prefer_gpu = bool(status.get("prefer_gpu"))
        lines.append(
            self.texts.get("setting_runtime_detail_prefer_gpu", "Preference: {value}").format(
                value=self.texts.get(
                    "setting_runtime_detail_prefer_gpu_yes" if prefer_gpu else "setting_runtime_detail_prefer_gpu_no",
                    "Prefer GPU" if prefer_gpu else "CPU only",
                )
            )
        )
        from src.core.extract_frames import get_frame_decode_status

        decode_status = get_frame_decode_status(load_config())
        lines.append(
            self.texts.get(
                "setting_runtime_detail_frame_decode",
                "Frame decode: hardware={available}, requested={requested}, last={last}",
            ).format(
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
            lines.append(
                self.texts.get("setting_runtime_detail_missing_dlls", "Missing system components: {items}").format(
                    items=", ".join(missing_dlls)
                )
            )

        missing_msvc_dlls = [str(item) for item in diagnostics.get("missing_msvc_dlls") or [] if str(item).strip()]
        if missing_msvc_dlls:
            lines.append(
                self.texts.get("setting_runtime_detail_missing_msvc_dlls", "Missing VC++ components: {items}").format(
                    items=", ".join(missing_msvc_dlls)
                )
            )

        available_providers = [str(item) for item in diagnostics.get("available_providers") or [] if str(item).strip()]
        if available_providers:
            lines.append(
                self.texts.get("setting_runtime_detail_available_providers", "Available accelerators: {items}").format(
                    items=", ".join(available_providers)
                )
            )

        windows_build = diagnostics.get("windows_build")
        if windows_build:
            lines.append(
                self.texts.get("setting_runtime_detail_windows_build", "Windows build: {value}").format(
                    value=windows_build
                )
            )

        probe_stage = str(diagnostics.get("probe_stage") or "").strip()
        if probe_stage:
            probe_stage_key = f"setting_runtime_probe_stage_{probe_stage}"
            probe_stage_text = self.texts.get(probe_stage_key, probe_stage)
            lines.append(
                self.texts.get("setting_runtime_detail_probe_stage", "Stuck at: {value}").format(
                    value=probe_stage_text
                )
            )

        probe_exception_type = str(diagnostics.get("probe_exception_type") or "").strip()
        probe_exception_message = str(diagnostics.get("probe_exception_message") or "").strip()
        probe_exception = ": ".join(part for part in [probe_exception_type, probe_exception_message] if part)
        if probe_exception:
            lines.append(
                self.texts.get("setting_runtime_detail_probe_exception", "Technical error: {value}").format(
                    value=probe_exception
                )
            )

        failure_kind = str(diagnostics.get("failure_kind") or "").strip()
        if failure_kind:
            lines.append(
                self.texts.get("setting_runtime_detail_failure_kind", "Failure type: {value}").format(
                    value=failure_kind
                )
            )

        active_providers = diagnostics.get("active_providers")
        if isinstance(active_providers, dict) and active_providers:
            lines.append(
                self.texts.get("setting_runtime_detail_active_providers", "Active: {value}").format(
                    value=json.dumps(active_providers, ensure_ascii=False)
                )
            )

        return "\n".join(line for line in lines if line)

    def _runtime_diagnostics_advice_key(self, issue: str) -> str:
        issue_key = str(issue or "").strip()
        known = {
            "directml",
            "directx",
            "windows",
            "windows_version",
            "msvc",
            "probe_timeout",
            "probe_launch_failed",
            "visual_provider_not_activated",
            "text_provider_not_activated",
            "visual_probe_failed",
            "text_probe_failed",
            "session_init_failed",
        }
        if issue_key in known:
            return f"setting_runtime_diag_advice_{issue_key}"
        return "setting_runtime_diag_advice_unknown"

    def _build_runtime_diagnostics_user_message(self, status):
        normalized = dict(status or {})
        prefer_gpu = bool(normalized.get("prefer_gpu"))
        initialized = bool(normalized.get("initialized"))
        backend = str(normalized.get("backend") or "").strip()
        is_gpu = self._is_gpu_backend_label(backend)
        warning = str(normalized.get("warning") or "").strip()
        issue = self._resolve_runtime_issue_key(normalized)

        if not initialized:
            status_key = "setting_runtime_diag_status_uninitialized"
            meaning_key = "setting_runtime_diag_meaning_uninitialized"
            advice_key = "setting_runtime_diag_advice_uninitialized"
        elif not prefer_gpu and not is_gpu:
            status_key = "setting_runtime_diag_status_cpu_only"
            meaning_key = "setting_runtime_diag_meaning_cpu_only"
            advice_key = "setting_runtime_diag_advice_cpu_only"
        elif is_gpu and warning:
            status_key = "setting_runtime_diag_status_gpu_soft"
            meaning_key = "setting_runtime_diag_meaning_gpu_soft"
            advice_key = self._runtime_diagnostics_advice_key(issue) if issue else "setting_runtime_diag_advice_ok"
        elif is_gpu:
            status_key = "setting_runtime_diag_status_gpu_ok"
            meaning_key = "setting_runtime_diag_meaning_gpu_ok"
            advice_key = "setting_runtime_diag_advice_ok"
        else:
            status_key = "setting_runtime_diag_status_cpu_fallback"
            meaning_key = "setting_runtime_diag_meaning_cpu_fallback"
            advice_key = self._runtime_diagnostics_advice_key(issue)

        sections = [
            self.texts.get("setting_runtime_diag_section_status", "Status"),
            self.texts.get(status_key, status_key),
            self.texts.get(meaning_key, meaning_key),
        ]

        reason = self._build_runtime_issue_summary(normalized)
        if reason and (warning or issue):
            sections.extend(
                [
                    "",
                    self.texts.get("setting_runtime_diag_section_reason", "Reason"),
                    reason,
                ]
            )

        sections.extend(
            [
                "",
                self.texts.get("setting_runtime_diag_section_advice", "What to do"),
                self.texts.get(advice_key, advice_key),
                "",
                self.texts.get("setting_runtime_diag_section_tech", "Details"),
                self._build_runtime_diagnostics_detail(normalized),
            ]
        )
        return "\n".join(sections).strip()

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
            "user_message": self._build_runtime_diagnostics_user_message(normalized_status),
            "diagnostics": dict(normalized_status.get("diagnostics") or {}),
        }

    def _get_runtime_issue_text(self, issue):
        issue_key = str(issue or "").strip()
        if not issue_key:
            return ""
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
        text_key = issue_key_map.get(issue_key, "setting_runtime_issue_unknown")
        return self.texts.get(text_key, self.texts.get("setting_runtime_issue_unknown", "DirectML runtime"))

    def copy_runtime_diagnostics(self, status=None):
        from src.core.clip_embedding import get_engine_runtime_status

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
        from src.core.clip_embedding import get_engine_runtime_status

        status = get_engine_runtime_status()
        text = self._build_runtime_diagnostics_user_message(status)
        if not text:
            text = json.dumps(self._build_runtime_diagnostics_payload(status), ensure_ascii=False, indent=2)
        dialog = AppMessageDialog(
            self.texts.get("setting_show_runtime_diagnostics_title", "GPU diagnostics"),
            text,
            kind="info",
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            confirm=True,
            cancel_text=self.texts["close"],
            confirm_text=self.texts.get("setting_copy_runtime_diagnostics", "Copy diagnostics"),
        )
        dialog.exec()
        if dialog.confirmed():
            self.copy_runtime_diagnostics(status)

    def refresh_search_telemetry_panel(self):
        from src.services.search_telemetry import (
            format_telemetry_panel,
            get_telemetry_file_path,
            get_telemetry_summary,
            is_telemetry_enabled,
            reload_telemetry_state,
        )

        texts = self.texts
        if is_telemetry_enabled():
            reload_telemetry_state()
            summary = get_telemetry_summary()
            crop_total = int((summary.get("crop_locate") or {}).get("total", 0) or 0)
            playback_samples = int((summary.get("playback_bias") or {}).get("samples", 0) or 0)
            confidence_total = sum(int(v or 0) for v in (summary.get("confidence_tiers") or {}).values())
            if crop_total <= 0 and playback_samples <= 0 and confidence_total <= 0:
                body = texts.get(
                    "search_telemetry_panel_empty",
                    "No screenshot search data yet.",
                )
            else:
                body = format_telemetry_panel(language=self.language, texts=texts)
            updated_at = str(summary.get("updated_at") or "")
        else:
            body = format_telemetry_panel(language=self.language, texts=texts)
            updated_at = ""

        file_label = texts.get("search_telemetry_panel_file", "Data file: {path}").format(
            path=get_telemetry_file_path()
        )
        self.settings_page.set_search_telemetry_panel(
            body,
            file_path=file_label,
            updated_at=updated_at,
        )

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
        """Deprecated path: warmup is lazy on first CLIP search/sync."""
        self.ensure_runtime_warmup(lambda: None)

    def ensure_runtime_warmup(self, on_ready) -> None:
        """Warm CLIP/ONNX once, show status on search+library bars, then run ``on_ready``."""
        if callable(on_ready) is False:
            on_ready = lambda: None
        if getattr(self, "_runtime_warmup_ready", False):
            on_ready()
            return
        callbacks = getattr(self, "_warmup_ready_callbacks", None)
        if callbacks is None:
            self._warmup_ready_callbacks = []
            callbacks = self._warmup_ready_callbacks
        callbacks.append(on_ready)
        if self.search_controller.is_warmup_running():
            self._apply_runtime_warmup_status()
            return
        self._apply_runtime_warmup_status()
        self.search_controller.start_warmup()

    def _apply_runtime_warmup_status(self) -> None:
        text = self.texts.get("runtime_warmup_status", "Warming up model…")
        search_lbl = getattr(self.search_page, "lbl_status", None)
        library_lbl = getattr(self.library_page, "lbl_status", None)
        if search_lbl is not None:
            search_lbl.setText(text)
        if library_lbl is not None:
            library_lbl.setText(text)
        btn_search = getattr(self.search_page, "btn_search", None)
        if btn_search is not None:
            btn_search.setEnabled(False)
        btn_sync = getattr(self.library_page, "btn_sync_db", None)
        if btn_sync is not None and self.ui_state.resources_ready:
            # Keep sync disabled while the engine is still loading.
            btn_sync.setEnabled(False)

    def _on_runtime_warmup_finished(self) -> None:
        self._runtime_warmup_ready = True
        self.push_inference_status()
        callbacks = list(getattr(self, "_warmup_ready_callbacks", []) or [])
        self._warmup_ready_callbacks = []
        btn_search = getattr(self.search_page, "btn_search", None)
        if btn_search is not None:
            btn_search.setEnabled(True)
        if self.ui_state.resources_ready:
            btn_sync = getattr(self.library_page, "btn_sync_db", None)
            if btn_sync is not None:
                btn_sync.setEnabled(True)
            btn_refresh = getattr(self.library_page, "btn_refresh_visual_library", None)
            if btn_refresh is not None:
                btn_refresh.setEnabled(True)
        ready_text = self.texts.get("ready", "")
        warmup_text = self.texts.get("runtime_warmup_status", "Warming up model…")
        for lbl in (
            getattr(self.search_page, "lbl_status", None),
            getattr(self.library_page, "lbl_status", None),
        ):
            if lbl is not None and lbl.text().strip() == warmup_text.strip():
                lbl.setText(ready_text)
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception("Runtime warmup ready callback failed")

    def check_runtime_resources(self, show_dialog=True):
        return self.runtime_resource_controller.check_resources(show_dialog=show_dialog)

    def refresh_runtime_resource_ui(self, *, sync_dialog=True):
        """Re-read disk/config status, refresh page banners, and optionally sync the import dialog."""
        from src.services.runtime_resource_service import (
            get_runtime_resource_location_text,
            get_runtime_resource_status,
        )

        def _apply():
            status = get_runtime_resource_status()
            self.push_resources_status(status)
            if not sync_dialog:
                return
            controller = getattr(self, "runtime_resource_controller", None)
            dialog = getattr(controller, "dialog", None) if controller is not None else None
            if dialog is None or not dialog.isVisible() or getattr(dialog, "_downloading", False):
                return
            if status.get("resources_ready"):
                dialog.set_manage_state()
                return
            dialog.set_missing_state(
                status["display_files"],
                get_runtime_resource_location_text(
                    status=status,
                    include_ffmpeg=not status["ffmpeg_ready"] or not status["model_ready"],
                ),
                download_enabled=status["download_enabled"],
            )

        _apply()
        QTimer.singleShot(0, _apply)

    def start_runtime_resource_download(self):
        self.runtime_resource_controller.start_download()

    def open_runtime_resource_dialog(self):
        self.runtime_resource_controller.show_manage_dialog()

    def _on_runtime_banner_action(self):
        if getattr(self, "_legacy_migration_tip_visible", False) and not self.is_startup_migration_busy():
            # Prefer opening Settings migrate when tip is showing and resources are OK.
            try:
                from src.services.runtime_resource_service import get_runtime_resource_status

                if get_runtime_resource_status().get("resources_ready"):
                    self._open_settings_for_legacy_migration()
                    return
            except Exception:
                self._open_settings_for_legacy_migration()
                return
        self.open_runtime_resource_dialog()

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

    def open_model_package_github_page(self):
        app_meta = get_app_meta()
        target_url = str(app_meta.get("model_github_url", "") or "").strip()
        if not target_url:
            self.show_info_dialog(
                self.texts["warning_title"],
                self.texts["download_models_unavailable"],
                kind="warning",
            )
            return
        webbrowser.open(target_url)

    def _finish_runtime_resource_download(self, result):
        self.settings_page.input_model_dir.setText(result.get("model_dir", get_configured_model_dir()))
        if result.get("ffmpeg_path"):
            self.settings_page.input_ffmpeg_path.setText(result["ffmpeg_path"])
        self.refresh_runtime_resource_ui(sync_dialog=True)
        self.push_inference_status()

    def _apply_runtime_resource_status(self, status):
        model_ready = bool(status.get("model_ready", self.ui_state.model_ready))
        resources_ready = bool(status.get("resources_ready", self.ui_state.resources_ready))
        # Keep Search enabled: subtitle keyword search does not need CLIP.
        # Visual tabs still gate inside start_search via check_runtime_resources.
        self.search_page.btn_search.setEnabled(True)
        self.library_page.btn_sync_db.setEnabled(resources_ready)
        self.library_page.btn_refresh_visual_library.setEnabled(resources_ready)
        # CLIP/ONNX warmup is deferred until first visual search or library sync.
        disabled_text = self.texts.get("model_features_disabled", "")
        if not resources_ready:
            status_text = disabled_text
            # Visual download / sync still need CLIP+ffmpeg; do not freeze the
            # search status bar (subtitle search remains usable).
            self.link_page.lbl_status.setText(status_text)
            self.library_page.lbl_status.setText(status_text)
        elif disabled_text:
            ready_text = self.texts.get("ready", "")
            for label in (
                getattr(self.search_page, "lbl_status", None),
                getattr(self.library_page, "lbl_status", None),
                getattr(self.link_page, "lbl_status", None),
            ):
                if label is not None and label.text().strip() == disabled_text.strip():
                    label.setText(ready_text)
        self._update_runtime_banner(status)

    def _update_runtime_banner(self, status):
        if self.is_startup_migration_busy():
            return
        if status.get("resources_ready") and getattr(self, "_legacy_migration_tip_visible", False):
            self._show_legacy_migration_tip_banner()
            return
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
        for page in self._iter_runtime_banner_pages():
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
