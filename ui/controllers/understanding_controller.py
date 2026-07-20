from PySide6.QtCore import QObject, Signal

from ui.threading_utils import shutdown_thread
from ui.workers import UnderstandingVideoWorker, UnderstandingWorker


class UnderstandingController(QObject):
    status_changed = Signal(int, str)
    chunk_completed = Signal(int, int, object)
    finished = Signal(bool, object, bool, object)
    error_occurred = Signal(str)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.current_target = None
        self.current_mode = ""

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def start(self, target_lib=None):
        if self.is_running():
            return False

        self.current_target = target_lib
        self.current_mode = "batch"
        self.worker = UnderstandingWorker(target_lib=target_lib)
        self.worker.progress_signal.connect(self.status_changed.emit)
        self.worker.error_signal.connect(self.error_occurred.emit)
        self.worker.finished_signal.connect(self._finish)
        self.worker.start()
        return True

    def start_video(self, video_id):
        video_id = str(video_id or "").strip()
        if not video_id or self.is_running():
            return False

        self.current_target = video_id
        self.current_mode = "video"
        self.worker = UnderstandingVideoWorker(video_id=video_id)
        self.worker.progress_signal.connect(self.status_changed.emit)
        self.worker.chunk_completed.connect(self.chunk_completed.emit)
        self.worker.error_signal.connect(self.error_occurred.emit)
        self.worker.finished_signal.connect(self._finish)
        self.worker.start()
        return True

    def shutdown(self):
        shutdown_thread(self.worker, stop_first=True, allow_terminate=True, wait_ms=3000)

    def request_stop(self):
        if self.is_running() and hasattr(self.worker, "stop"):
            self.worker.stop()
            return True
        return False

    def _finish(self, success, stopped, result):
        target = self.current_target
        mode = self.current_mode
        self.current_target = None
        self.current_mode = ""
        self.finished.emit(success, target, stopped, result)
