from PySide6.QtCore import QObject, Signal

from ui.threading_utils import bind_thread_release, release_finished_thread, shutdown_thread
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
        bind_thread_release(self, "version_worker", self.version_worker)
        self.version_worker.start()

    def refresh_notice(self, language):
        if self.notice_worker and self.notice_worker.isRunning():
            return
        self.notice_worker = NoticeFetchWorker(language)
        self.notice_worker.result_ready.connect(self.notice_ready.emit)
        bind_thread_release(self, "notice_worker", self.notice_worker)
        self.notice_worker.start()

    def refresh_about(self, language):
        if self.about_worker and self.about_worker.isRunning():
            return
        self.about_worker = AboutFetchWorker(language)
        self.about_worker.result_ready.connect(self.about_ready.emit)
        bind_thread_release(self, "about_worker", self.about_worker)
        self.about_worker.start()

    def shutdown(self):
        workers = (
            ("version_worker", self.version_worker),
            ("notice_worker", self.notice_worker),
            ("about_worker", self.about_worker),
        )
        for _name, worker in workers:
            shutdown_thread(worker)
        for name, worker in workers:
            release_finished_thread(self, name, worker)
