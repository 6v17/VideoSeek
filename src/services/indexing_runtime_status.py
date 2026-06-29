"""In-process video library sync status for Agent API / health."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

_lock = threading.Lock()
_index_sync_in_progress = False
_index_sync_target_library_path: Optional[str] = None


def set_index_sync_running(target_library_path: Optional[str] = None) -> None:
    with _lock:
        global _index_sync_in_progress, _index_sync_target_library_path
        _index_sync_in_progress = True
        target = str(target_library_path or "").strip()
        _index_sync_target_library_path = target or None


def clear_index_sync_running() -> None:
    with _lock:
        global _index_sync_in_progress, _index_sync_target_library_path
        _index_sync_in_progress = False
        _index_sync_target_library_path = None


def get_index_sync_status() -> Dict[str, Any]:
    with _lock:
        return {
            "index_sync_in_progress": bool(_index_sync_in_progress),
            "index_sync_target_library_path": _index_sync_target_library_path,
        }


def library_sync_in_progress(library_path: str, *, sync_status: Optional[Dict[str, Any]] = None) -> bool:
    status = sync_status if sync_status is not None else get_index_sync_status()
    if not status.get("index_sync_in_progress"):
        return False
    target = str(status.get("index_sync_target_library_path") or "").strip()
    if not target:
        return True
    from src.services.search_scope import normalize_scope_path

    return normalize_scope_path(library_path) == normalize_scope_path(target)
