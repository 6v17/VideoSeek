from PySide6.QtCore import QObject, Signal

from ui.threading_utils import shutdown_thread
from ui.workers import UnderstandingSummaryWorker, UnderstandingVideoWorker, UnderstandingWorker


class UnderstandingController(QObject):
    status_changed = Signal(int, str)
    chunk_completed = Signal(int, int, object)
    video_started = Signal(str, int, int)
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

    def start(self, target_lib=None, mode=None, skip_existing=True):
        if self.is_running():
            return False

        self.current_target = target_lib
        self.current_mode = str(mode or "tags").strip() or "tags"
        self.worker = UnderstandingWorker(
            target_lib=target_lib,
            mode=self.current_mode,
            skip_existing=skip_existing,
        )
        self.worker.progress_signal.connect(self.status_changed.emit)
        if hasattr(self.worker, "video_started"):
            self.worker.video_started.connect(self.video_started.emit)
        if hasattr(self.worker, "chunk_completed"):
            self.worker.chunk_completed.connect(self.chunk_completed.emit)
        self.worker.error_signal.connect(self.error_occurred.emit)
        self.worker.finished_signal.connect(self._finish)
        self.worker.start()
        return True

    def start_video(self, video_id, mode=None):
        video_id = str(video_id or "").strip()
        if not video_id or self.is_running():
            return False

        self.current_target = video_id
        self.current_mode = str(mode or "tags").strip() or "tags"
        self.worker = UnderstandingVideoWorker(video_id=video_id, mode=self.current_mode)
        self.worker.progress_signal.connect(self.status_changed.emit)
        self.worker.chunk_completed.connect(self.chunk_completed.emit)
        self.worker.error_signal.connect(self.error_occurred.emit)
        self.worker.finished_signal.connect(self._finish)
        self.worker.start()
        return True

    def start_video_summary(self, video_id):
        # Kept for compatibility; summary mode now runs via start_video(mode="summary").
        return self.start_video(video_id, mode="summary")

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
        payload = dict(result or {})
        payload["mode"] = mode
        self.finished.emit(success, target, stopped, payload)
