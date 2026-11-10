"""Pid lock so the MCP shim can see a running VideoSeek without scanning processes."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

_LOCK_NAME = "agent_api.lock"
_DEV_LOCK_NAME = "agent_api.dev.lock"


def instance_lock_path() -> str:
    from src.infra.paths import get_app_data_dir, is_standalone_app

    name = _LOCK_NAME if is_standalone_app() else _DEV_LOCK_NAME
    folder = get_app_data_dir()
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name)


def api_bind() -> tuple[str, int]:
    host = str(os.environ.get("VIDEOSEEK_AGENT_API_HOST", "127.0.0.1") or "127.0.0.1").strip()
    try:
        port = int(os.environ.get("VIDEOSEEK_AGENT_API_PORT", "8765") or 8765)
    except (TypeError, ValueError):
        port = 8765
    return host, port


def configured_api_enabled() -> bool:
    forced = str(os.environ.get("VIDEOSEEK_AGENT_API", "") or "").strip().lower()
    if forced in {"0", "false", "no", "off"}:
        return False
    if forced in {"1", "true", "yes", "on"}:
        return True
    try:
        from src.app.config import load_config

        return bool(load_config().get("agent_api_enabled", False))
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/app/instance_lock.py:configured_api_enabled")
        return False


def write_instance_lock(*, api_enabled: bool) -> None:
    host, port = api_bind()
    payload = {"pid": os.getpid(), "host": host, "port": port, "api_enabled": bool(api_enabled)}
    path = instance_lock_path()
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(temporary, path)


def update_instance_lock(*, api_enabled: bool) -> None:
    """Refresh the flag for this process. Ignore a lock owned by someone else."""
    current = read_instance_lock()
    if current is not None and int(current.get("pid") or 0) not in {0, os.getpid()}:
        return
    try:
        write_instance_lock(api_enabled=api_enabled)
    except OSError:
        return


def read_instance_lock() -> dict[str, Any] | None:
    try:
        with open(instance_lock_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if not pid_alive(pid):
        return None
    try:
        port = int(payload.get("port") or 8765)
    except (TypeError, ValueError):
        port = 8765
    return {
        "pid": pid,
        "host": str(payload.get("host") or "127.0.0.1"),
        "port": port,
        "api_enabled": bool(payload.get("api_enabled")),
    }


def remove_instance_lock() -> None:
    path = instance_lock_path()
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if int(payload.get("pid") or 0) != os.getpid():
            return
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return
    try:
        os.remove(path)
    except OSError:
        return


def pid_alive(pid: int) -> bool:
    pid = int(pid)
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes

        access = 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
        handle = ctypes.windll.kernel32.OpenProcess(access, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        # Access denied still means a process exists.
        if int(ctypes.windll.kernel32.GetLastError() or 0) == 5:
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
