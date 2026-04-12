from PySide6.QtCore import QObject, Signal

from ui.threading_utils import shutdown_thread
from ui.workers import AboutFetchWorker, NoticeFetchWorker, VersionCheckWorker


class AppMetaController(QObject):
    version_ready = Signal(dict)
    notice_ready = Signal(dict)
    about_ready = Signal(dict)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.version_worker = None
        self.notice_worker = None
        self.about_worker = None

    def refresh(self, language):
        self.refresh_version(language)
        self.refresh_notice(language)
        self.refresh_about(language)

    def refresh_version(self, language):
        if self.version_worker and self.version_worker.isRunning():
            return
        self.version_worker = VersionCheckWorker(language)
        self.version_worker.result_ready.connect(self.version_ready.emit)
        self.version_worker.start()

    def refresh_notice(self, language):
        if self.notice_worker and self.notice_worker.isRunning():
            return
        self.notice_worker = NoticeFetchWorker(language)
        self.notice_worker.result_ready.connect(self.notice_ready.emit)
        self.notice_worker.start()

    def refresh_about(self, language):
        if self.about_worker and self.about_worker.isRunning():
            return
        self.about_worker = AboutFetchWorker(language)
        self.about_worker.result_ready.connect(self.about_ready.emit)
        self.about_worker.start()

    def shutdown(self):
        for worker in (self.version_worker, self.notice_worker, self.about_worker):
            shutdown_thread(worker)
