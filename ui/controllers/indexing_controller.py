from PySide6.QtCore import QObject, Signal

from ui.threading_utils import shutdown_thread
from ui.workers import IndexUpdateWorker, LibraryRegisterWorker


class IndexingController(QObject):
    status_changed = Signal(int, str)
    finished = Signal(bool, object, bool, bool, object, bool)
    runtime_status_changed = Signal(dict)
    error_occurred = Signal(str)

    register_progress = Signal(int, str)
    register_finished = Signal(bool, object)
    register_error = Signal(str)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.register_worker = None
        self.current_target = None
        self.current_rebuild_global_assets = True
        self.current_index_from_vectors_only = False
        self._register_then_index = False
        self._pending_index_kwargs = None
        self._register_context = {}

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def is_registering(self):
        return self.register_worker is not None and self.register_worker.isRunning()

    def is_busy(self):
        return self.is_running() or self.is_registering()

    def start(
        self,
        target_lib=None,
        force_cleanup_missing_files=False,
        cleanup_missing_entries=None,
        rebuild_global_assets=True,
        debug_failure="",
        index_from_vectors_only=False,
        video_ids=None,
    ):
        if self.is_busy():
            return False

        self.current_target = target_lib
        self.current_rebuild_global_assets = bool(rebuild_global_assets)
        self.current_index_from_vectors_only = bool(index_from_vectors_only)
        worker_kwargs = {
            "target_lib": target_lib,
            "force_cleanup_missing_files": force_cleanup_missing_files,
            "cleanup_missing_entries": cleanup_missing_entries,
            "rebuild_global_assets": rebuild_global_assets,
            "index_from_vectors_only": index_from_vectors_only,
            "video_ids": video_ids,
        }
        if debug_failure:
            worker_kwargs["debug_failure"] = debug_failure
        self.worker = IndexUpdateWorker(**worker_kwargs)
        self.worker.progress_signal.connect(self.status_changed.emit)
        self.worker.runtime_status_signal.connect(self.runtime_status_changed.emit)
        self.worker.error_signal.connect(self.error_occurred.emit)
        self.worker.finished_signal.connect(self._finish)
        self.worker.start()
        return True

    def start_register(
        self,
        library_paths,
        *,
        then_index=False,
        index_kwargs=None,
        mode: str = "visual",
        context=None,
    ):
        """Register videos under ``library_paths`` on a background thread."""
        if self.is_busy():
            return False
        if isinstance(library_paths, (list, tuple, set)):
            paths = [str(p or "").strip() for p in library_paths if str(p or "").strip()]
        else:
            text = str(library_paths or "").strip()
            paths = [text] if text else []
        if not paths:
            return False

        self._register_then_index = bool(then_index)
        self._pending_index_kwargs = dict(index_kwargs or {}) if then_index else None
        self._register_context = dict(context or {})
        self.register_worker = LibraryRegisterWorker(paths, mode=mode)
        self.register_worker.progress_signal.connect(self.register_progress.emit)
        self.register_worker.error_signal.connect(self.register_error.emit)
        self.register_worker.finished_signal.connect(self._finish_register)
        self.register_worker.start()
        return True

    def shutdown(self):
        shutdown_thread(self.register_worker, stop_first=True, allow_terminate=True, wait_ms=3000)
        shutdown_thread(self.worker, stop_first=True, allow_terminate=True, wait_ms=3000)

    def request_stop(self):
        if self.is_registering() and hasattr(self.register_worker, "stop"):
            self.register_worker.stop()
            return True
        if self.is_running() and hasattr(self.worker, "stop"):
            self.worker.stop()
            return True
        return False

    def _finish_register(self, success, payload):
        result = dict(payload or {})
        result["then_index"] = bool(self._register_then_index)
        if self._pending_index_kwargs is not None:
            result["index_kwargs"] = dict(self._pending_index_kwargs)
        if self._register_context:
            result.update(self._register_context)
        self._register_then_index = False
        self._pending_index_kwargs = None
        self._register_context = {}
        worker = self.register_worker
        self.register_worker = None
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception:
                pass
        self.register_finished.emit(bool(success), result)

    def _finish(self, success, stopped, has_search_assets, issues):
        from src.services.indexing_runtime_status import clear_index_sync_running

        # Safety net if the worker/flow exited without releasing the claim.
        clear_index_sync_running()
        target = self.current_target
        rebuild_global_assets = self.current_rebuild_global_assets
        self.current_target = None
        self.current_rebuild_global_assets = True
        self.finished.emit(success, target, stopped, has_search_assets, issues, rebuild_global_assets)
