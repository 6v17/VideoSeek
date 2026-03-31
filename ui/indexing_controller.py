from PySide6.QtCore import QObject, Signal

from ui.workers import IndexUpdateWorker


class IndexingController(QObject):
    status_changed = Signal(int, str)
    finished = Signal(bool, object)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.current_target = None

    def is_running(self):
        return self.worker is not None and self.worker.isRunning()

    def start(self, target_lib=None):
        if self.is_running():
            return False

        self.current_target = target_lib
        self.worker = IndexUpdateWorker(target_lib=target_lib)
        self.worker.progress_signal.connect(self.status_changed.emit)
        self.worker.finished_signal.connect(self._finish)
        self.worker.start()
        return True

    def shutdown(self):
        if not self.worker or not self.worker.isRunning():
            return
        self.worker.quit()
        if self.worker.wait(1500):
            return
        self.worker.requestInterruption()
        if self.worker.wait(1500):
            return
        self.worker.terminate()
        self.worker.wait(1000)

    def _finish(self, success):
        target = self.current_target
        self.current_target = None
        self.finished.emit(success, target)
