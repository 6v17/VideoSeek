from PySide6.QtCore import QObject, Signal

from ui.threading_utils import shutdown_thread
from ui.workers import IndexUpdateWorker


class IndexingController(QObject):
    status_changed = Signal(int, str)
    finished = Signal(bool, object, bool, bool, object, bool)
    runtime_status_changed = Signal(dict)
    error_occurred = Signal(str)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.current_target = None
        self.current_rebuild_global_assets = True

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def start(
        self,
        target_lib=None,
        force_cleanup_missing_files=False,
        cleanup_missing_entries=None,
        rebuild_global_assets=True,
        debug_failure="",
    ):
        if self.is_running():
            return False

        self.current_target = target_lib
        self.current_rebuild_global_assets = bool(rebuild_global_assets)
        worker_kwargs = {
            "target_lib": target_lib,
            "force_cleanup_missing_files": force_cleanup_missing_files,
            "cleanup_missing_entries": cleanup_missing_entries,
            "rebuild_global_assets": rebuild_global_assets,
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

    def shutdown(self):
        shutdown_thread(self.worker, stop_first=True, allow_terminate=False)

    def request_stop(self):
        if self.is_running() and hasattr(self.worker, "stop"):
            self.worker.stop()
            return True
        return False

    def _finish(self, success, stopped, has_search_assets, issues):
        target = self.current_target
        rebuild_global_assets = self.current_rebuild_global_assets
        self.current_target = None
        self.current_rebuild_global_assets = True
        self.finished.emit(success, target, stopped, has_search_assets, issues, rebuild_global_assets)
