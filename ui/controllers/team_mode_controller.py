"""Team mode UI controller: start/stop server media + API host binding."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.team_mode_service import (
    build_team_server_status,
    get_team_mode,
    start_team_server_media,
    stop_team_server_media,
)
from src.services.team_paths import detect_lan_ip
from src.web.agent_api import DEFAULT_PORT, AgentApiService, is_agent_api_enabled

logger = get_logger("team_mode_controller")


class TeamModeController(QObject):
    status_changed = Signal(dict)

    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._api_service = None

    def refresh_status(self) -> dict:
        status = build_team_server_status()
        status["api_running"] = bool(self._api_service and self._api_service.is_running())
        self.status_changed.emit(status)
        return status

    def apply_from_config(self) -> dict:
        """Start/stop team server pieces according to session team_mode."""
        mode = get_team_mode()
        if mode == "server":
            return self.start_server()
        self.stop_server()
        return self.refresh_status()

    def start_server(self) -> dict:
        cfg = load_config()
        api_port = int(cfg.get("team_api_port", DEFAULT_PORT) or DEFAULT_PORT)
        media_error = ""
        try:
            from src.web.agent_api import configure_search_concurrency

            configure_search_concurrency(cfg)
            media_status = start_team_server_media(cfg)
        except Exception as exc:
            # Media proxy is optional for connect/search; keep going so API still binds.
            logger.exception("Failed to start team nginx")
            media_status = build_team_server_status(cfg)
            media_error = str(exc)
            media_status["error"] = media_error

        # Bind LAN API (reuse Agent API surface)
        host = os.environ.get("VIDEOSEEK_AGENT_API_HOST", "0.0.0.0")
        if self._api_service is not None:
            self._api_service.stop()
            self._api_service = None
        # Also stop the loopback-only agent controller if running
        agent = getattr(self.parent_window, "agent_api_controller", None)
        if agent is not None and agent.is_running():
            agent.stop()

        try:
            self._api_service = AgentApiService(host=host, port=api_port)
            self._api_service.start()
        except Exception as exc:
            logger.exception("Failed to start team API")
            stop_team_server_media()
            media_status["error"] = str(exc) if not media_error else f"{media_error}\n{exc}"
            media_status["api_running"] = False
            self.status_changed.emit(media_status)
            return media_status

        media_status["api_running"] = True
        media_status["api_base_url"] = f"http://{detect_lan_ip()}:{api_port}"
        self.status_changed.emit(media_status)
        return media_status

    def stop_server(self) -> None:
        if self._api_service is not None:
            try:
                self._api_service.stop()
            except Exception:
                logger.exception("Failed to stop team API")
            self._api_service = None
        stop_team_server_media()
        # Restore normal agent API if enabled
        agent = getattr(self.parent_window, "agent_api_controller", None)
        if agent is not None and is_agent_api_enabled():
            # Only if not team server — caller should have set mode off/client
            if get_team_mode() != "server":
                agent.start()
        self.refresh_status()

    def shutdown(self) -> None:
        from src.services.team_mode_service import clear_session_team_mode

        if get_team_mode() == "server":
            self.stop_server()
        elif self._api_service is not None:
            self._api_service.stop()
            self._api_service = None
        clear_session_team_mode()
        self.refresh_status()
