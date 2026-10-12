import os
import threading

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, QTimer, Signal, Slot


def _test_mode() -> bool:
    return str(os.environ.get("VIDEOSEEK_TEST_MODE", "") or "").strip() in {
        "1",
        "true",
        "True",
        "yes",
    }


class MobileBridgeController(QObject):
    search_requested = Signal(dict)
    status_changed = Signal(str)
    # Worker-thread emit → UI-thread slot (blocking) so the phone learns if search started.
    _accept_on_ui = Signal(dict, object)

    def __init__(self, parent_window=None):
        # Only adopt a real QObject parent (MainWindow). Tests may pass a
        # SimpleNamespace — parenting that would crash / corrupt on Windows CI.
        qt_parent = parent_window if isinstance(parent_window, QObject) else None
        super().__init__(qt_parent)
        self.parent_window = parent_window
        self._service = None
        self._accept_on_ui.connect(self._run_accept_on_ui, Qt.ConnectionType.BlockingQueuedConnection)

    def start(self):
        if self._service is None:
            from src.web.mobile_bridge import MobileBridgeService

            self._service = MobileBridgeService(on_search_requested=self._handle_search_requested)
        if self.is_running():
            return self.get_access_url()
        # Pytest/Windows: nested QEventLoop + MagicMock parents has crashed runners
        # (0xc0000374). Keep production async; tests call start() synchronously.
        if _test_mode():
            self._service.start()
            if not self.is_running():
                raise RuntimeError("Mobile bridge server failed to start.")
            self.status_changed.emit("running")
            return self.get_access_url()
        # Run the blocking bind/wait off the UI thread; pump Qt events meanwhile.
        box: dict = {"error": None}
        loop = QEventLoop(self)

        def _work():
            try:
                self._service.start()
            except Exception as exc:
                box["error"] = exc
            finally:
                loop.quit()

        worker = threading.Thread(target=_work, name="MobileBridgeStart", daemon=True)
        worker.start()
        QTimer.singleShot(8000, loop.quit)
        loop.exec()
        worker.join(timeout=0.2)
        if box.get("error") is not None:
            raise box["error"]
        if not self.is_running():
            raise RuntimeError("Mobile bridge server failed to start.")
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

    @Slot(dict, object)
    def _run_accept_on_ui(self, payload, box):
        accept = getattr(self.parent_window, "accept_mobile_search_request", None)
        if callable(accept):
            box["value"] = accept(dict(payload or {}))
        else:
            self.search_requested.emit(dict(payload or {}))
            box["value"] = {"ok": True}

    def _handle_search_requested(self, payload):
        """Called from the uvicorn thread; must return whether the UI started the search."""
        box: dict = {}
        data = dict(payload or {})
        if QThread.currentThread() is self.thread():
            self._run_accept_on_ui(data, box)
        else:
            self._accept_on_ui.emit(data, box)
        result = dict(box.get("value") or {})
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "search_not_started"))
        return result
