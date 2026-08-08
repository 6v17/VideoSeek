"""Team mode orchestration (server: API + nginx; client: connection state).

Team role (off / server / client) is session-only: never restored from disk on
startup. Users must explicitly Apply each run. team_server_url may still be
remembered for convenience.
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.app.config import DEFAULT_CONFIG, load_config
from src.app.logging_utils import get_logger
from src.services.team_media_map import mounts_public_payload
from src.services.team_nginx_service import is_nginx_running, start_nginx, stop_nginx
from src.services.team_paths import detect_lan_ip, normalize_http_base, normalize_team_mode, nginx_bundle_ready

logger = get_logger("team_mode")

# In-process server mounts (used when enriching Agent search hits)
_active_mounts: List[Dict[str, str]] = []
_active_media_base: str = ""
# Session bind ports (may differ from defaults when preferred ports are busy).
_active_api_port: int = 0
_active_nginx_port: int = 0
# Session role — not persisted. Always starts as off.
_session_team_mode: str = "off"


def get_preferred_team_ports() -> tuple[int, int]:
    """Canonical preferred ports. Remaps are session-only and must not stick in config."""
    api = int(DEFAULT_CONFIG.get("team_api_port", 8765) or 8765)
    media = int(DEFAULT_CONFIG.get("team_nginx_port", 18080) or 18080)
    return api, media


def set_active_team_ports(*, api_port: int = 0, nginx_port: int = 0) -> None:
    global _active_api_port, _active_nginx_port
    _active_api_port = int(api_port or 0)
    _active_nginx_port = int(nginx_port or 0)


def clear_active_team_ports() -> None:
    set_active_team_ports(api_port=0, nginx_port=0)


def get_team_mode(config=None) -> str:
    """Active team role for this process (session-only; ignores config)."""
    _ = config
    return normalize_team_mode(_session_team_mode)


def set_session_team_mode(mode) -> str:
    """Set in-memory team role for this run. Does not write config."""
    global _session_team_mode
    _session_team_mode = normalize_team_mode(mode)
    return _session_team_mode


def clear_session_team_mode() -> None:
    set_session_team_mode("off")


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
    paths: List[str] = []
    seen: set[str] = set()
    try:
        libraries = list_libraries(maintain=False)
    except Exception:
        logger.exception("list_libraries failed")
        libraries = {}
    if isinstance(libraries, dict):
        for path in libraries.keys():
            text = str(path or "").strip()
            if not text:
                continue
            key = text.replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            paths.append(text)
    # Subtitle libraries may differ from CLIP visual roots; mount both for team play URLs.
    try:
        from src.services.subtitle_library_service import list_subtitle_libraries

        for path in list_subtitle_libraries(config=config, seed=True).keys():
            text = str(path or "").strip()
            if not text:
                continue
            key = text.replace("\\", "/").lower()
            if key in seen:
                continue
            seen.add(key)
            paths.append(text)
    except Exception:
        logger.exception("list_subtitle_libraries failed while building team mounts")
    return paths


def build_team_server_status(config=None) -> Dict[str, Any]:
    cfg = config if config is not None else load_config()
    mode = get_team_mode(cfg)
    lan_ip = detect_lan_ip()
    preferred_api, preferred_media = get_preferred_team_ports()
    # Prefer live session binds so UI/share URLs match the actual listener.
    api_port = int(_active_api_port or preferred_api)
    nginx_port = int(_active_nginx_port or preferred_media)
    media_base = str(_active_media_base or "").strip() or f"http://{lan_ip}:{nginx_port}"
    return {
        "mode": mode,
        "lan_ip": lan_ip,
        "api_port": api_port,
        "nginx_port": nginx_port,
        "api_base_url": f"http://{lan_ip}:{api_port}",
        "media_base_url": media_base,
        "nginx_ready": nginx_bundle_ready(),
        "nginx_running": is_nginx_running(),
        "mounts": mounts_public_payload(_active_mounts),
        "server_url": normalize_http_base(str(cfg.get("team_server_url") or ""), default_port=preferred_api),
    }


def start_team_server_media(config=None, *, listen_port: int | None = None) -> Dict[str, Any]:
    """Write nginx conf for current libraries and start/reload nginx."""
    global _active_mounts, _active_media_base, _active_nginx_port
    cfg = config if config is not None else load_config()
    _preferred_api, preferred_media = get_preferred_team_ports()
    nginx_port = int(listen_port if listen_port is not None else preferred_media)
    libraries = list_local_library_paths(cfg)
    mounts = start_nginx(library_paths=libraries, listen_port=nginx_port)
    lan_ip = detect_lan_ip()
    _active_mounts = mounts
    _active_nginx_port = nginx_port
    _active_media_base = f"http://{lan_ip}:{nginx_port}"
    status = build_team_server_status(cfg)
    status["nginx_port"] = nginx_port
    status["media_base_url"] = _active_media_base
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
        clear_active_team_ports()


def refresh_team_server_media(config=None) -> Dict[str, Any]:
    """Re-read libraries and reload nginx (server mode)."""
    return start_team_server_media(config=config)
