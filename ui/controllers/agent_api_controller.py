import os

from PySide6.QtCore import QObject

from src.app.logging_utils import get_logger
from src.web.agent_api import DEFAULT_HOST, DEFAULT_PORT, AgentApiService, is_agent_api_enabled

logger = get_logger("agent_api_controller")


class AgentApiController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._service = None

    def start(self):
        if not is_agent_api_enabled():
            return None
        if self._service is None:
            host = os.environ.get("VIDEOSEEK_AGENT_API_HOST", DEFAULT_HOST)
            port = int(os.environ.get("VIDEOSEEK_AGENT_API_PORT", DEFAULT_PORT))
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
