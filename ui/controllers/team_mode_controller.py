"""Team mode UI controller: start/stop server media + API host binding."""

from __future__ import annotations

import os
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

from src.app.config import load_config, save_config
from src.app.logging_utils import get_logger
from src.services.team_mode_service import (
    build_team_server_status,
    get_preferred_team_ports,
    get_team_mode,
    set_active_team_ports,
    start_team_server_media,
    stop_team_server_media,
)
from src.services.team_paths import detect_lan_ip, find_available_tcp_port

logger = get_logger("team_mode_controller")

ProgressCallback = Optional[Callable[[str], None]]


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

    def apply_from_config(self, progress_callback: ProgressCallback = None) -> dict:
        """Start/stop team server pieces according to session team_mode."""
        mode = get_team_mode()
        if mode == "server":
            return self.start_server(progress_callback=progress_callback)
        self.stop_server(progress_callback=progress_callback)
        return self.refresh_status()

    def _emit_progress(self, progress_callback: ProgressCallback, phase: str) -> None:
        if callable(progress_callback):
            try:
                progress_callback(str(phase or ""))
            except Exception:
                logger.exception("team progress callback failed for %s", phase)

    def _heal_preferred_ports_in_config(self, cfg: dict) -> dict:
        """Undo older builds that persisted busy-port remaps into config.json."""
        preferred_api, preferred_media = get_preferred_team_ports()
        dirty = False
        try:
            saved_api = int(cfg.get("team_api_port", preferred_api) or preferred_api)
        except (TypeError, ValueError):
            saved_api = preferred_api
        try:
            saved_media = int(cfg.get("team_nginx_port", preferred_media) or preferred_media)
        except (TypeError, ValueError):
            saved_media = preferred_media
        if saved_api != preferred_api:
            cfg["team_api_port"] = preferred_api
            dirty = True
        if saved_media != preferred_media:
            cfg["team_nginx_port"] = preferred_media
            dirty = True
        if dirty:
            save_config(cfg)
            logger.info(
                "Reset persisted team ports to defaults api=%s media=%s",
                preferred_api,
                preferred_media,
            )
        return cfg

    def start_server(self, progress_callback: ProgressCallback = None) -> dict:
        cfg = self._heal_preferred_ports_in_config(load_config())
        preferred_api, preferred_media = get_preferred_team_ports()
        host = os.environ.get("VIDEOSEEK_AGENT_API_HOST", "0.0.0.0")
        port_notes: list[str] = []

        self._emit_progress(progress_callback, "allocating_ports")
        try:
            api_port = find_available_tcp_port(preferred_api, host=host)
            media_port = find_available_tcp_port(preferred_media, host=host, skip={api_port})
        except Exception as exc:
            logger.exception("Failed to allocate team ports")
            status = build_team_server_status(cfg)
            status["error"] = str(exc)
            status["api_running"] = False
            self.status_changed.emit(status)
            return status

        # Remaps are session-only — never write team_*_port back to config.
        if api_port != preferred_api:
            port_notes.append(
                f"API 端口 {preferred_api} 被占用，本次改用 {api_port}（下次仍优先 {preferred_api}）"
            )
        if media_port != preferred_media:
            port_notes.append(
                f"视频端口 {preferred_media} 被占用，本次改用 {media_port}（下次仍优先 {preferred_media}）"
            )
        if port_notes:
            logger.warning("Team ports remapped for this session: %s", "；".join(port_notes))

        # Stop previous LAN API / loopback agent before binding.
        self._emit_progress(progress_callback, "stopping_old")
        if self._api_service is not None:
            try:
                self._api_service.stop()
            except Exception:
                logger.exception("Failed to stop previous team API")
            self._api_service = None
        agent = getattr(self.parent_window, "agent_api_controller", None)
        if agent is not None and agent.is_running():
            try:
                agent.stop()
            except Exception:
                logger.exception("Failed to stop loopback agent before team server start")

        media_error = ""
        try:
            from src.web.agent_api import configure_search_concurrency

            self._emit_progress(progress_callback, "starting_media")
            configure_search_concurrency(cfg)
            media_status = start_team_server_media(cfg, listen_port=media_port)
        except Exception as exc:
            # Media proxy is optional for connect/search; keep going so API still binds.
            logger.exception("Failed to start team nginx")
            media_status = build_team_server_status(cfg)
            media_error = str(exc)
            media_status["error"] = media_error

        self._emit_progress(progress_callback, "starting_api")
        try:
            from src.web.agent_api import AgentApiService

            self._api_service = AgentApiService(host=host, port=api_port)
            self._api_service.start()
        except Exception as exc:
            logger.exception("Failed to start team API on port %s", api_port)
            # One more remapped attempt if bind raced after the free-port probe.
            try:
                fallback = find_available_tcp_port(api_port + 1, host=host, skip={media_port})
                logger.warning("Retrying team API on port %s after failure on %s", fallback, api_port)
                self._emit_progress(progress_callback, "starting_api_retry")
                from src.web.agent_api import AgentApiService

                self._api_service = AgentApiService(host=host, port=fallback)
                self._api_service.start()
                api_port = fallback
                port_notes.append(
                    f"API 启动失败后本次改用端口 {api_port}（下次仍优先 {preferred_api}）"
                )
            except Exception as retry_exc:
                logger.exception("Failed to start team API after retry")
                stop_team_server_media()
                detail = str(retry_exc) if not media_error else f"{media_error}\n{retry_exc}"
                if not detail:
                    detail = str(exc)
                media_status["error"] = detail
                media_status["api_running"] = False
                if port_notes:
                    media_status["port_note"] = "；".join(port_notes)
                self.status_changed.emit(media_status)
                return media_status

        set_active_team_ports(api_port=api_port, nginx_port=media_port)
        self._emit_progress(progress_callback, "ready")
        lan_ip = detect_lan_ip()
        media_status["api_running"] = True
        media_status["api_port"] = api_port
        media_status["nginx_port"] = media_port
        media_status["api_base_url"] = f"http://{lan_ip}:{api_port}"
        media_status["media_base_url"] = f"http://{lan_ip}:{media_port}"
        if port_notes:
            media_status["port_note"] = "；".join(port_notes)
            # Keep any media warning, but surface remaps clearly.
            if media_error:
                media_status["error"] = f"{media_error}\n" + media_status["port_note"]
            else:
                media_status.pop("error", None)
        self.status_changed.emit(media_status)
        return media_status

    def stop_server(self, progress_callback: ProgressCallback = None) -> None:
        self._emit_progress(progress_callback, "stopping_api")
        if self._api_service is not None:
            try:
                self._api_service.stop()
            except Exception:
                logger.exception("Failed to stop team API")
            self._api_service = None
        self._emit_progress(progress_callback, "stopping_media")
        stop_team_server_media()
        # Restore normal agent API if enabled
        self._emit_progress(progress_callback, "restoring_agent")
        agent = getattr(self.parent_window, "agent_api_controller", None)
        if agent is not None:
            from src.web.agent_api import is_agent_api_enabled

            if is_agent_api_enabled():
                # Only if not team server — caller should have set mode off/client
                if get_team_mode() != "server":
                    try:
                        agent.start()
                    except Exception:
                        logger.exception("Failed to restore loopback agent API")
        self._emit_progress(progress_callback, "ready")
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
