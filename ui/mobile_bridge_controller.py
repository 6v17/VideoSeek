from PySide6.QtCore import QObject, Signal

from src.web.mobile_bridge import MobileBridgeService


class MobileBridgeController(QObject):
    upload_received = Signal(str, str)
    status_changed = Signal(str)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._service = None

    def start(self):
        if self._service is None:
            self._service = MobileBridgeService(on_image_received=self._handle_upload_received)
        if self.is_running():
            return self.get_access_url()
        self._service.start()
        self.status_changed.emit("running")
        return self.get_access_url()

    def stop(self):
        if not self.is_running():
            self.status_changed.emit("stopped")
            return
        self._service.stop()
        self.status_changed.emit("stopped")

    def toggle(self):
        if self.is_running():
            self.stop()
            return None
        return self.start()

    def shutdown(self):
        self.stop()

    def is_running(self):
        return self._service is not None and self._service.is_running()

    def get_access_url(self):
        return self._service.get_access_url() if self._service is not None else ""

    def _handle_upload_received(self, path, source):
        self.upload_received.emit(str(path), str(source or ""))
