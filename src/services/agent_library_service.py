"""Read-only library discovery for the Agent API."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from src.app.config import load_config
from src.services.search_index_schema import (
    get_search_index_schema_version,
    library_index_is_ready,
    list_library_search_index_summaries,
)
from src.services.search_scope import normalize_scope_path

API_VERSION = "1"
_DEFAULT_VIDEO_PAGE_LIMIT = 500
_MAX_VIDEO_PAGE_LIMIT = 2000


def _library_display_name(library_path: str) -> str:
    base = os.path.basename(os.path.normpath(library_path))
    return base or library_path


def _resolve_library_key(library_path: str, libraries: dict) -> Optional[str]:
    target = normalize_scope_path(library_path)
    for key in libraries.keys():
        if normalize_scope_path(key) == target:
            return key
    return None


def _count_library_videos(library_data: dict) -> Dict[str, int]:
    total = 0
    ready = 0
    missing_source = 0
    files = library_data.get("files", {}) if isinstance(library_data, dict) else {}
    if not isinstance(files, dict):
        return {"video_count_total": 0, "video_count_indexed_ready": 0, "video_count_missing_source": 0}
    for rel_path, info in files.items():
        if not isinstance(info, dict):
            continue
        if not str(rel_path or "").strip():
            continue
        total += 1
        if not str(info.get("vid", "") or "").strip():
            continue
        asset_state = str(info.get("asset_state", "") or "").strip().lower()
        if asset_state == "ready":
            ready += 1
        if asset_state == "missing_source":
            missing_source += 1
    return {
        "video_count_total": total,
        "video_count_indexed_ready": ready,
        "video_count_missing_source": missing_source,
    }


def list_agent_libraries(config=None) -> Dict[str, Any]:
    from src.services.library_service import list_libraries
    from src.storage.asset_store import load_model_metadata
    from src.storage.config_store import get_search_scope_mode

    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    libraries = list_libraries()
    summaries = {
        normalize_scope_path(str(item.get("library_path", "") or "")): item
        for item in list_library_search_index_summaries(meta, config=cfg)
    }
    items: List[Dict[str, Any]] = []
    for library_path in sorted(libraries.keys(), key=lambda p: normalize_scope_path(p)):
        library_data = libraries.get(library_path, {})
        counts = _count_library_videos(library_data)
        summary = summaries.get(normalize_scope_path(library_path), {})
        per_library_ready = bool(
            library_index_is_ready(library_path, config=cfg)
            or summary.get("frame_index_ready")
            or summary.get("chunk_index_ready")
        )
        items.append(
            {
                "library_path": library_path,
                "display_name": _library_display_name(library_path),
                "index_state": str(library_data.get("index_state", "") or "").strip().lower() or "unknown",
                **counts,
                "per_library_index_ready": per_library_ready,
                "offline": not os.path.exists(library_path),
            }
        )
    return {
        "api_version": API_VERSION,
        "ok": True,
        "libraries": items,
        "meta": {
            "count": len(items),
            "search_index_schema_version": get_search_index_schema_version(meta),
            "saved_search_scope_mode": get_search_scope_mode(cfg),
        },
    }


def list_agent_library_videos(
    library_path: str,
    *,
    ready_only: bool = True,
    limit: int = _DEFAULT_VIDEO_PAGE_LIMIT,
    offset: int = 0,
    config=None,
) -> Dict[str, Any]:
    from src.services.library_service import list_libraries

    cfg = config or load_config()
    libraries = list_libraries()
    resolved_key = _resolve_library_key(library_path, libraries)
    if resolved_key is None:
        raise KeyError(f"Library not found: {library_path}")

    library_data = libraries.get(resolved_key, {})
    files = library_data.get("files", {}) if isinstance(library_data, dict) else {}
    if not isinstance(files, dict):
        files = {}

    rows: List[Dict[str, Any]] = []
    for rel_path in sorted(files.keys(), key=lambda p: str(p).lower()):
        info = files.get(rel_path, {})
        if not isinstance(info, dict):
            continue
        rel_text = str(rel_path or "").strip()
        video_id = str(info.get("vid", "") or "").strip()
        if not rel_text or not video_id:
            continue
        abs_path = os.path.normpath(os.path.join(resolved_key, rel_text))
        asset_state = str(info.get("asset_state", "") or "").strip().lower() or "unknown"
        source_exists = os.path.isfile(abs_path)
        if ready_only:
            if asset_state != "ready" or not source_exists:
                continue
        rows.append(
            {
                "video_path": abs_path,
                "video_rel_path": rel_text.replace("\\", "/"),
                "video_id": video_id,
                "asset_state": asset_state,
                "source_exists": source_exists,
            }
        )

    total_ready = sum(1 for row in rows if row["asset_state"] == "ready" and row["source_exists"])
    safe_limit = max(1, min(int(limit or _DEFAULT_VIDEO_PAGE_LIMIT), _MAX_VIDEO_PAGE_LIMIT))
    safe_offset = max(0, int(offset or 0))
    page = rows[safe_offset : safe_offset + safe_limit]

    return {
        "api_version": API_VERSION,
        "ok": True,
        "library_path": resolved_key,
        "videos": page,
        "meta": {
            "returned": len(page),
            "total_listed": len(rows),
            "total_ready": total_ready,
            "offset": safe_offset,
            "limit": safe_limit,
            "ready_only": bool(ready_only),
        },
    }
