import os
import threading

from PySide6.QtCore import QObject, Qt, Signal

from src.app.logging_utils import get_logger

logger = get_logger("agent_api_controller")

# Keep literals here so importing this controller does not execute agent_api.__init__
# (which eagerly pulls FastAPI / search / ONNX).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765


class _IndexSyncInvoker(QObject):
    requested = Signal(object)


class AgentApiController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._service = None
        self._sync_invoker = _IndexSyncInvoker(self)
        self._sync_invoker.requested.connect(self._run_index_sync, Qt.ConnectionType.QueuedConnection)
        self._sync_bound = False

    def start(self):
        from src.web.agent_api import AgentApiService, DEFAULT_HOST, DEFAULT_PORT, is_agent_api_enabled

        if not is_agent_api_enabled():
            return None
        self._bind_index_sync()
        if self._service is None:
            host = os.environ.get("VIDEOSEEK_AGENT_API_HOST", DEFAULT_HOST or _DEFAULT_HOST)
            port = int(os.environ.get("VIDEOSEEK_AGENT_API_PORT", DEFAULT_PORT or _DEFAULT_PORT))
            self._service = AgentApiService(host=host, port=port)
        if self.is_running():
            return self.get_base_url()
        try:
            self._service.start()
        except Exception:
            logger.exception("Failed to start Agent API.")
            return None
        return self.get_base_url()

    def stop(self):
        self._unbind_index_sync()
        if self._service is None:
            return
        self._service.stop()

    def _bind_index_sync(self):
        if self._sync_bound:
            return
        from src.services.agent_index_sync import (
            register_agent_add_library_handler,
            register_agent_include_handler,
            register_agent_index_sync_handler,
            register_agent_library_refresh_handler,
        )

        register_agent_index_sync_handler(self._request_index_sync)
        register_agent_add_library_handler(self._request_add_library)
        register_agent_library_refresh_handler(self._request_library_refresh)
        register_agent_include_handler(self._request_include)
        self._sync_bound = True

    def _unbind_index_sync(self):
        if not self._sync_bound:
            return
        from src.services.agent_index_sync import (
            unregister_agent_add_library_handler,
            unregister_agent_include_handler,
            unregister_agent_index_sync_handler,
            unregister_agent_library_refresh_handler,
        )

        unregister_agent_index_sync_handler(self._request_index_sync)
        unregister_agent_add_library_handler(self._request_add_library)
        unregister_agent_library_refresh_handler(self._request_library_refresh)
        unregister_agent_include_handler(self._request_include)
        self._sync_bound = False

    def _request_index_sync(self, library_paths, video_ids=None):
        return self._invoke_desktop(
            "sync",
            {"library_paths": list(library_paths or []), "video_ids": video_ids},
        )

    def _request_add_library(self, library_path):
        return self._invoke_desktop("add", library_path)

    def _request_library_refresh(self, library_paths):
        return self._invoke_desktop("refresh", list(library_paths or []))

    def _request_include(self, plan):
        return self._invoke_desktop("include", dict(plan or {}))

    def _invoke_desktop(self, action, value):
        box = {}
        event = threading.Event()

        def finish(result):
            box["result"] = result
            event.set()

        self._sync_invoker.requested.emit((action, value, finish))
        if not event.wait(8.0):
            return {"accepted": False, "reason": "desktop_timeout"}
        return box.get("result") or {"accepted": False, "reason": "failed"}

    def _run_index_sync(self, payload):
        action, value, finish = payload
        try:
            if action == "add":
                result = self.parent_window.start_agent_add_library(value)
            elif action == "refresh":
                result = self.parent_window.start_agent_library_refresh(value)
            elif action == "include":
                result = self.parent_window.start_agent_include_videos(value)
            else:
                body = value if isinstance(value, dict) else {"library_paths": value}
                result = self.parent_window.start_agent_library_sync(
                    body.get("library_paths"),
                    video_ids=body.get("video_ids"),
                )
        except Exception as exc:
            logger.exception("Agent library request failed to start.")
            result = {"accepted": False, "reason": "failed", "message": str(exc)}
        finish(result)

    def shutdown(self):
        self.stop()

    def is_running(self):
        return self._service is not None and self._service.is_running()

    def get_base_url(self):
        return self._service.get_base_url() if self._service is not None else ""
