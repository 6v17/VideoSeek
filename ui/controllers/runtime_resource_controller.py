from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from src.app.i18n import get_texts
from src.services.runtime_resource_service import (
    ensure_runtime_resource_dirs,
    get_runtime_resource_location_text,
    get_runtime_resource_status,
)
from ui.dialogs import ModelDownloadDialog
from ui.threading_utils import bind_thread_release, release_finished_thread, shutdown_thread
from ui.workers import ResourceDownloadWorker


class RuntimeResourceController(QObject):
    startup_cancelled = Signal()
    resources_ready = Signal(dict)
    status_changed = Signal(dict)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.dialog = None
        self.worker = None
        self._dialog_theme = None
        self._dialog_language = None
        self._bundled_bootstrap_started = False

    def _exec_runtime_resource_dialog(self, dialog):
        # Flush pending resize/move on the main window so the first modal placement matches later opens.
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        dialog.exec()

    def check_resources(self, show_dialog=True):
        status = get_runtime_resource_status()
        # Config can lose profiles while ONNX packs remain on disk — rescan once.
        if not status.get("model_ready"):
            try:
                from src.services.model_package_service import rediscover_model_profiles

                rediscover = rediscover_model_profiles()
                if int(rediscover.get("imported", 0) or 0) or int(rediscover.get("updated", 0) or 0) or rediscover.get(
                    "removed"
                ):
                    status = get_runtime_resource_status()
                    parent = self.parent_window
                    if hasattr(parent, "_populate_model_profile_options"):
                        from src.app.config import load_config

                        parent._populate_model_profile_options(load_config())
                    if hasattr(parent, "refresh_runtime_resource_ui"):
                        parent.refresh_runtime_resource_ui(sync_dialog=False)
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/controllers/runtime_resource_controller.py:rediscover_model_profiles")
        else:
            # Already-imported packs may still carry stale Large=512 metadata.
            try:
                from src.services.model_package_service import heal_stale_model_embedding_dimensions

                heal = heal_stale_model_embedding_dimensions()
                if heal.get("changed"):
                    parent = self.parent_window
                    if hasattr(parent, "_populate_model_profile_options"):
                        from src.app.config import load_config

                        parent._populate_model_profile_options(load_config())
                    if hasattr(parent, "_refresh_search_model_display"):
                        parent._refresh_search_model_display()
                    if hasattr(parent, "refresh_runtime_resource_ui"):
                        parent.refresh_runtime_resource_ui(sync_dialog=False)
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/controllers/runtime_resource_controller.py:heal_stale_model_embedding_dimensions")
        self.status_changed.emit(status)
        if status["resources_ready"]:
            return True
        if show_dialog:
            self.show_missing_dialog(status)
        return False

    def start_bundled_bootstrap_if_needed(self) -> bool:
        """Import Full-edition ``runtime\\`` seed in the background (does not block the main window)."""
        if self._bundled_bootstrap_started:
            return bool(self.worker and self.worker.isRunning())
        from src.services.bundled_runtime_service import has_pending_bundled_import

        if not has_pending_bundled_import():
            return False
        if self.worker and self.worker.isRunning():
            return True

        from ui.workers import BundledRuntimeBootstrapWorker

        texts = get_texts(self.parent_window.language)
        self._bundled_bootstrap_started = True
        worker = BundledRuntimeBootstrapWorker()
        self.worker = worker

        def _localize_bundled_progress(text: str) -> str:
            raw = str(text or "").strip()
            if not raw:
                return ""
            exact = {
                "Importing bundled runtime resources": "runtime_bundled_bootstrap_progress",
                "Copying ffmpeg.exe…": "runtime_bundled_progress_ffmpeg",
                "Runtime import finished": "runtime_bundled_bootstrap_done",
                "Bundled runtime import finished": "runtime_bundled_bootstrap_done",
            }
            for en, key in exact.items():
                if raw == en:
                    return texts.get(key, raw)
            if raw.startswith("Importing ") and raw.endswith(".zip"):
                name = raw[len("Importing ") : -len(".zip")]
                return texts.get("runtime_bundled_progress_zip", "Importing {name}…").format(name=name)
            return raw

        def _emit_import_status(*, progress: int, text: str) -> None:
            snapshot = dict(get_runtime_resource_status())
            snapshot["bundled_import_in_progress"] = True
            snapshot["bundled_import_failed"] = False
            progress_value = max(0, min(100, int(progress)))
            snapshot["bundled_import_progress"] = progress_value
            detail = _localize_bundled_progress(text)
            if progress_value > 0:
                detail = texts.get(
                    "runtime_bundled_bootstrap_progress_with_pct",
                    "{detail} ({progress}%)",
                ).format(detail=detail or texts.get("runtime_bundled_bootstrap_progress", ""), progress=progress_value)
            snapshot["bundled_import_text"] = detail or texts.get(
                "runtime_bundled_bootstrap_progress",
                "Importing bundled resources…",
            )
            self.status_changed.emit(snapshot)

        def _finish(result=None):
            from ui.threading_utils import release_finished_thread

            payload = dict(result or {})
            release_finished_thread(self, "worker", worker)
            self._refresh_after_runtime_import()
            final = dict(get_runtime_resource_status())
            final["bundled_import_in_progress"] = False
            final["bundled_import_failed"] = False
            if payload.get("supplemental") and payload.get("ok"):
                final["bundled_import_toast"] = texts.get(
                    "runtime_bundled_supplemental_ok",
                    "Missing bundled resources were added. Your active search model was not changed.",
                )
            self.status_changed.emit(final)
            if final.get("resources_ready") or payload.get("ok"):
                self.resources_ready.emit(payload)
            toast = str(final.get("bundled_import_toast") or "").strip()
            if toast and hasattr(self.parent_window, "show_info_dialog"):
                self.parent_window.show_info_dialog(
                    texts.get("runtime_bundled_supplemental_title", texts.get("success_title", "Done")),
                    toast,
                    kind="success",
                )

        def _fail(message: str) -> None:
            from ui.threading_utils import release_finished_thread
            from src.services.bundled_runtime_errors import format_bundled_import_error

            release_finished_thread(self, "worker", worker)
            texts_local = get_texts(self.parent_window.language)
            formatted = format_bundled_import_error(str(message or ""), texts_local)
            snapshot = dict(get_runtime_resource_status())
            snapshot["bundled_import_in_progress"] = False
            snapshot["bundled_import_failed"] = True
            snapshot["bundled_import_error"] = formatted
            self.status_changed.emit(snapshot)
            if hasattr(self.parent_window, "show_error_dialog"):
                self.parent_window.show_error_dialog(formatted)

        _emit_import_status(
            progress=0,
            text=texts.get("runtime_bundled_bootstrap_starting", "Importing bundled resources…"),
        )
        worker.progress_signal.connect(lambda value, text: _emit_import_status(progress=int(value), text=str(text)))
        worker.finished_signal.connect(_finish)
        worker.error_signal.connect(_fail)
        from ui.threading_utils import bind_thread_release

        bind_thread_release(self, "worker", worker)
        worker.start()
        return True

    def _refresh_after_runtime_import(self):
        parent = self.parent_window
        if hasattr(parent, "_populate_model_profile_options"):
            from src.app.config import load_config

            parent._populate_model_profile_options(load_config())
        if hasattr(parent, "_refresh_search_model_display"):
            parent._refresh_search_model_display()
        if hasattr(parent, "refresh_runtime_resource_ui"):
            parent.refresh_runtime_resource_ui(sync_dialog=False)

    def get_status_snapshot(self):
        return get_runtime_resource_status()

    def show_missing_dialog(self, status=None):
        status = status or get_runtime_resource_status()
        ensure_runtime_resource_dirs(status)
        dialog = self._ensure_dialog()
        dialog.set_missing_state(
            status["display_files"],
            get_runtime_resource_location_text(
                status=status,
                include_ffmpeg=not status["ffmpeg_ready"] or not status["model_ready"],
            ),
            download_enabled=status["download_enabled"],
        )
        self._exec_runtime_resource_dialog(dialog)

    def show_manage_dialog(self):
        status = get_runtime_resource_status()
        ensure_runtime_resource_dirs(status)
        dialog = self._ensure_dialog()
        if status.get("resources_ready"):
            dialog.set_manage_state()
        else:
            dialog.set_missing_state(
                status["display_files"],
                get_runtime_resource_location_text(
                    status=status,
                    include_ffmpeg=not status["ffmpeg_ready"] or not status["model_ready"],
                ),
                download_enabled=status["download_enabled"],
            )
        self._exec_runtime_resource_dialog(dialog)

    def start_download(self):
        if self.worker and self.worker.isRunning():
            return

        status = get_runtime_resource_status()
        if not status["download_enabled"]:
            texts = get_texts(self.parent_window.language)
            self.parent_window.show_info_dialog(
                texts["warning_title"],
                texts["download_models_unavailable"],
                kind="warning",
            )
            return

        dialog = self._ensure_dialog()
        dialog.set_progress_state(0, get_texts(self.parent_window.language)["model_download_starting"])

        self.worker = ResourceDownloadWorker(
            need_models=bool(status["missing_model_files"]),
            need_ffmpeg=not status["ffmpeg_ready"],
        )
        self.worker.progress_signal.connect(self._update_progress)
        self.worker.finished_signal.connect(self._finish_download)
        self.worker.error_signal.connect(self._fail_download)
        bind_thread_release(self, "worker", self.worker)
        self.worker.start()

    def shutdown(self):
        worker = self.worker
        shutdown_thread(worker)
        release_finished_thread(self, "worker", worker)

    def _ensure_dialog(self):
        current_theme = bool(self.parent_window.is_dark_mode)
        current_language = str(self.parent_window.language)
        if (
            self.dialog is not None
            and (self._dialog_theme != current_theme or self._dialog_language != current_language)
        ):
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None
        if self.dialog is None:
            self.dialog = ModelDownloadDialog(
                self.parent_window,
                current_theme,
                current_language,
            )
            self.dialog.import_requested.connect(self.parent_window.parse_model_packages)
            self.dialog.go_download_requested.connect(self.parent_window.open_model_package_download_page)
            self.dialog.go_github_download_requested.connect(
                self.parent_window.open_model_package_github_page
            )
            self._dialog_theme = current_theme
            self._dialog_language = current_language
        return self.dialog

    def _update_progress(self, value, text):
        if self.dialog:
            self.dialog.set_progress_state(value, text)

    def _finish_download(self, result):
        status = get_runtime_resource_status()
        self.status_changed.emit(status)
        if self.dialog:
            self.dialog.set_success_state(
                get_runtime_resource_location_text(status=status, include_ffmpeg=True)
            )
        self.resources_ready.emit(result)

    def _fail_download(self, error_text):
        status = get_runtime_resource_status()
        self.status_changed.emit(status)
        if self.dialog:
            self.dialog.set_error_state(
                error_text,
                status["display_files"],
                get_runtime_resource_location_text(
                    status=status,
                    include_ffmpeg=not status["ffmpeg_ready"],
                ),
                download_enabled=status["download_enabled"],
            )
