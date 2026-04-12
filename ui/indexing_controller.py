from PySide6.QtCore import QObject, Signal

from ui.threading_utils import shutdown_thread
from ui.workers import IndexUpdateWorker


class IndexingController(QObject):
    status_changed = Signal(int, str)
    finished = Signal(bool, object, bool)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.current_target = None

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def start(self, target_lib=None, force_cleanup_missing_files=False):
        if self.is_running():
            return False

        self.current_target = target_lib
        self.worker = IndexUpdateWorker(
            target_lib=target_lib,
            force_cleanup_missing_files=force_cleanup_missing_files,
        )
        self.worker.progress_signal.connect(self.status_changed.emit)
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

    def _finish(self, success, stopped):
        target = self.current_target
        self.current_target = None
        self.finished.emit(success, target, stopped)
