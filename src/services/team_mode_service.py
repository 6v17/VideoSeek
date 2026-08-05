"""Team mode orchestration (server: API + nginx; client: connection state)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.team_media_map import mounts_public_payload
from src.services.team_nginx_service import is_nginx_running, start_nginx, stop_nginx
from src.services.team_paths import detect_lan_ip, normalize_http_base, normalize_team_mode, nginx_bundle_ready

logger = get_logger("team_mode")

# In-process server mounts (used when enriching Agent search hits)
_active_mounts: List[Dict[str, str]] = []
_active_media_base: str = ""


def get_team_mode(config=None) -> str:
    cfg = config if config is not None else load_config()
    return normalize_team_mode(cfg.get("team_mode", "off"))


def is_team_client_mode(config=None) -> bool:
    return get_team_mode(config) == "client"


def is_team_server_mode(config=None) -> bool:
    return get_team_mode(config) == "server"


def get_active_media_mounts() -> List[Dict[str, str]]:
    return list(_active_mounts)


def get_active_media_base_url() -> str:
    return str(_active_media_base or "")


def list_local_library_paths(config=None) -> List[str]:
    from src.services.library_service import list_libraries

    _ = config  # libraries come from active model meta
    try:
        libraries = list_libraries(maintain=False)
    except Exception:
        logger.exception("list_libraries failed")
        return []
    if isinstance(libraries, dict):
        return [str(path) for path in libraries.keys() if str(path or "").strip()]
    return []


def build_team_server_status(config=None) -> Dict[str, Any]:
    cfg = config if config is not None else load_config()
    mode = get_team_mode(cfg)
    lan_ip = detect_lan_ip()
    api_port = int(cfg.get("team_api_port", 8765) or 8765)
    nginx_port = int(cfg.get("team_nginx_port", 18080) or 18080)
    return {
        "mode": mode,
        "lan_ip": lan_ip,
        "api_port": api_port,
        "nginx_port": nginx_port,
        "api_base_url": f"http://{lan_ip}:{api_port}",
        "media_base_url": f"http://{lan_ip}:{nginx_port}",
        "nginx_ready": nginx_bundle_ready(),
        "nginx_running": is_nginx_running(),
        "mounts": mounts_public_payload(_active_mounts),
        "server_url": normalize_http_base(str(cfg.get("team_server_url") or ""), default_port=api_port),
    }


def start_team_server_media(config=None) -> Dict[str, Any]:
    """Write nginx conf for current libraries and start/reload nginx."""
    global _active_mounts, _active_media_base
    cfg = config if config is not None else load_config()
    nginx_port = int(cfg.get("team_nginx_port", 18080) or 18080)
    libraries = list_local_library_paths(cfg)
    mounts = start_nginx(library_paths=libraries, listen_port=nginx_port)
    lan_ip = detect_lan_ip()
    _active_mounts = mounts
    _active_media_base = f"http://{lan_ip}:{nginx_port}"
    status = build_team_server_status(cfg)
    status["mounts"] = mounts_public_payload(mounts)
    status["nginx_running"] = True
    return status


def stop_team_server_media() -> None:
    global _active_mounts, _active_media_base
    try:
        stop_nginx()
    finally:
        _active_mounts = []
        _active_media_base = ""


def refresh_team_server_media(config=None) -> Dict[str, Any]:
    """Re-read libraries and reload nginx (server mode)."""
    return start_team_server_media(config=config)
