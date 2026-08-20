import os

from PySide6.QtCore import QObject

from src.app.logging_utils import get_logger

logger = get_logger("agent_api_controller")

# Keep literals here so importing this controller does not execute agent_api.__init__
# (which eagerly pulls FastAPI / search / ONNX).
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765


class AgentApiController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._service = None

    def start(self):
        from src.web.agent_api import AgentApiService, DEFAULT_HOST, DEFAULT_PORT, is_agent_api_enabled

        if not is_agent_api_enabled():
            return None
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
        if self._service is None:
            return
        self._service.stop()

    def shutdown(self):
        self.stop()

    def is_running(self):
        return self._service is not None and self._service.is_running()

    def get_base_url(self):
        return self._service.get_base_url() if self._service is not None else ""
