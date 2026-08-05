"""Team mode path helpers: nginx bundle + LAN address."""

from __future__ import annotations

import os
import socket
from typing import Optional

from src.infra.paths import get_app_install_dir, get_resource_path


def get_nginx_root() -> str:
    """Resolved ``server/nginx`` directory (dev install or packaged)."""
    return get_resource_path(os.path.join("server", "nginx"))


def get_nginx_exe() -> str:
    return os.path.join(get_nginx_root(), "nginx.exe")


def get_nginx_conf_dir() -> str:
    return os.path.join(get_nginx_root(), "conf")


def get_nginx_conf_d_dir() -> str:
    return os.path.join(get_nginx_conf_dir(), "conf.d")


def get_nginx_videos_conf_path() -> str:
    return os.path.join(get_nginx_conf_d_dir(), "videos.conf")


def nginx_bundle_ready() -> bool:
    exe = get_nginx_exe()
    conf = os.path.join(get_nginx_conf_dir(), "nginx.conf")
    return os.path.isfile(exe) and os.path.isfile(conf)


def detect_lan_ip() -> str:
    """Best-effort primary LAN IPv4 (falls back to 127.0.0.1)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = str(sock.getsockname()[0] or "").strip()
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = str(info[4][0] or "").strip()
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return "127.0.0.1"


def normalize_team_mode(raw) -> str:
    mode = str(raw or "off").strip().lower()
    if mode in {"server", "host", "share"}:
        return "server"
    if mode in {"client", "join", "employee"}:
        return "client"
    return "off"


def normalize_http_base(url: str, *, default_port: Optional[int] = None) -> str:
    text = str(url or "").strip().rstrip("/")
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    if default_port is not None and text.count(":") == 1 and text.startswith("http"):
        # host only → append port
        scheme, rest = text.split("://", 1)
        if "/" not in rest and rest.count(":") == 0:
            text = f"{scheme}://{rest}:{int(default_port)}"
    return text.rstrip("/")
