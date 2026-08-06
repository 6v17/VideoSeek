"""Team mode path helpers: nginx bundle + LAN address."""

from __future__ import annotations

import os
import socket
from typing import Iterable, List, Optional, Set, Tuple

from src.infra.paths import get_resource_path


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


def _parse_ipv4(ip: str) -> Optional[Tuple[int, int, int, int]]:
    text = str(ip or "").strip()
    parts = text.split(".")
    if len(parts) != 4:
        return None
    try:
        nums = tuple(int(part) for part in parts)
    except ValueError:
        return None
    if any(part < 0 or part > 255 for part in nums):
        return None
    return nums  # type: ignore[return-value]


def is_unusable_lan_ip(ip: str) -> bool:
    """IPs that must not be advertised as the team server address."""
    parsed = _parse_ipv4(ip)
    if parsed is None:
        return True
    a, b, _c, _d = parsed
    if a == 127:
        return True
    if a == 0 or a >= 224:
        return True
    # Link-local / APIPA
    if a == 169 and b == 254:
        return True
    # RFC 2544 benchmark range — also used by Clash/Surge fake-ip / TUN (e.g. 198.18.0.1)
    if a == 198 and 18 <= b <= 19:
        return True
    return False


def lan_ip_preference_score(ip: str) -> int:
    """Lower score is preferred for LAN sharing."""
    if is_unusable_lan_ip(ip):
        return 10_000
    parsed = _parse_ipv4(ip)
    if parsed is None:
        return 10_000
    a, b, _c, _d = parsed
    if a == 192 and b == 168:
        return 0
    if a == 10:
        return 1
    if a == 172 and 16 <= b <= 31:
        return 2
    # CGNAT / some mesh VPN ranges — usable but not preferred for office LAN
    if a == 100 and 64 <= b <= 127:
        return 50
    return 100


def _collect_candidate_ips() -> List[str]:
    seen: set[str] = set()
    out: List[str] = []

    def _add(raw: str) -> None:
        ip = str(raw or "").strip()
        if not ip or ip in seen or is_unusable_lan_ip(ip):
            return
        seen.add(ip)
        out.append(ip)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            _add(str(sock.getsockname()[0] or ""))
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            _add(str(info[4][0] or ""))
    except OSError:
        pass

    # Enumerate host interfaces when available (helps when default route is VPN).
    try:
        for info in socket.getaddrinfo(None, 0, socket.AF_INET, socket.SOCK_DGRAM):
            _add(str(info[4][0] or ""))
    except OSError:
        pass

    return out


def pick_lan_ip(candidates: Iterable[str], *, fallback: str = "127.0.0.1") -> str:
    usable = [str(ip).strip() for ip in candidates if str(ip or "").strip() and not is_unusable_lan_ip(ip)]
    if not usable:
        return fallback
    return min(usable, key=lan_ip_preference_score)


def detect_lan_ip() -> str:
    """Best-effort primary LAN IPv4 (falls back to 127.0.0.1).

    Skips VPN fake-ip / TUN ranges such as 198.18.0.0/15 that otherwise produce
    unreachable team URLs and browser 502s.
    """
    return pick_lan_ip(_collect_candidate_ips(), fallback="127.0.0.1")


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


def tcp_port_is_available(port: int, *, host: str = "0.0.0.0") -> bool:
    """Return True when ``port`` can be bound on ``host`` right now."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        return False
    if port < 1 or port > 65535:
        return False
    bind_host = "0.0.0.0" if str(host or "").strip() in {"", "0.0.0.0", "::"} else str(host)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            # Do not enable SO_REUSEADDR: on Windows it can falsely report busy ports as free.
            sock.bind((bind_host, port))
        return True
    except OSError:
        return False


def find_available_tcp_port(
    preferred: int,
    *,
    host: str = "0.0.0.0",
    attempts: int = 40,
    skip: Optional[Set[int]] = None,
) -> int:
    """Pick ``preferred`` or the next free TCP port (up to ``attempts`` tries)."""
    preferred = int(preferred or 0)
    if preferred < 1:
        preferred = 8765
    blocked = {int(p) for p in (skip or set()) if p}
    for offset in range(max(1, int(attempts or 1))):
        port = preferred + offset
        if port > 65535:
            break
        if port in blocked:
            continue
        if tcp_port_is_available(port, host=host):
            return port
    raise RuntimeError(f"No free TCP port near {preferred} (tried {attempts} ports)")
