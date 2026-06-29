"""Read-only library discovery for the Agent API."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from src.app.config import load_config
from src.services.indexing_runtime_status import get_index_sync_status, library_sync_in_progress
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


def _indexed_evidence_video_ids(*, config=None) -> Set[str]:
    from src.services.understanding_paths import get_evidence_videos_dir

    cfg = config or load_config()
    evidence_dir = os.path.normpath(get_evidence_videos_dir(config=cfg))
    video_ids: Set[str] = set()
    if not os.path.isdir(evidence_dir):
        return video_ids
    for name in os.listdir(evidence_dir):
        if not str(name).lower().endswith(".json"):
            continue
        path = os.path.join(evidence_dir, name)
        if os.path.isfile(path):
            video_ids.add(os.path.splitext(name)[0])
    return video_ids


def _video_matches_query(row: Dict[str, Any], query: str) -> bool:
    needle = str(query or "").strip().lower()
    if not needle:
        return True
    haystacks = (
        row.get("video_rel_path", ""),
        os.path.basename(str(row.get("video_path", "") or "")),
        row.get("video_id", ""),
        row.get("library_display_name", ""),
    )
    return any(needle in str(item).lower() for item in haystacks if str(item).strip())


def _apply_video_list_filters(
    rows: List[Dict[str, Any]],
    *,
    video_id: Optional[str] = None,
    q: Optional[str] = None,
    has_evidence: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    filtered = rows
    video_id_text = str(video_id or "").strip()
    if video_id_text:
        filtered = [row for row in filtered if str(row.get("video_id", "") or "").strip() == video_id_text]
    if q:
        filtered = [row for row in filtered if _video_matches_query(row, q)]
    if has_evidence is not None:
        want_evidence = bool(has_evidence)
        filtered = [row for row in filtered if bool(row.get("has_evidence")) == want_evidence]
    return filtered


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
    sync_status = get_index_sync_status()
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
                "sync_in_progress": library_sync_in_progress(library_path, sync_status=sync_status),
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
            **sync_status,
        },
    }


def _collect_library_video_rows(
    library_path: str,
    library_data: dict,
    *,
    ready_only: bool,
    evidence_video_ids: Set[str],
) -> List[Dict[str, Any]]:
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
        abs_path = os.path.normpath(os.path.join(library_path, rel_text))
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
                "library_path": library_path,
                "library_display_name": _library_display_name(library_path),
                "asset_state": asset_state,
                "source_exists": source_exists,
                "has_evidence": video_id in evidence_video_ids,
            }
        )
    return rows


def list_agent_videos(
    library_path: Optional[str] = None,
    *,
    video_id: Optional[str] = None,
    q: Optional[str] = None,
    has_evidence: Optional[bool] = None,
    ready_only: bool = True,
    limit: int = _DEFAULT_VIDEO_PAGE_LIMIT,
    offset: int = 0,
    config=None,
) -> Dict[str, Any]:
    from src.services.library_service import list_libraries

    cfg = config or load_config()
    libraries = list_libraries()
    evidence_video_ids = _indexed_evidence_video_ids(config=cfg)
    rows: List[Dict[str, Any]] = []

    if library_path:
        resolved_key = _resolve_library_key(library_path, libraries)
        if resolved_key is None:
            raise KeyError(f"Library not found: {library_path}")
        rows = _collect_library_video_rows(
            resolved_key,
            libraries.get(resolved_key, {}),
            ready_only=ready_only,
            evidence_video_ids=evidence_video_ids,
        )
        libraries_scanned = 1
        scoped_library_path = resolved_key
    else:
        for resolved_key in sorted(libraries.keys(), key=lambda p: normalize_scope_path(p)):
            rows.extend(
                _collect_library_video_rows(
                    resolved_key,
                    libraries.get(resolved_key, {}),
                    ready_only=ready_only,
                    evidence_video_ids=evidence_video_ids,
                )
            )
        libraries_scanned = len(libraries)
        scoped_library_path = None

    filtered_rows = _apply_video_list_filters(
        rows,
        video_id=video_id,
        q=q,
        has_evidence=has_evidence,
    )
    video_id_text = str(video_id or "").strip()
    if video_id_text and not filtered_rows:
        raise KeyError(f"Video not found: {video_id_text}")

    total_ready = sum(1 for row in filtered_rows if row["asset_state"] == "ready" and row["source_exists"])
    safe_limit = max(1, min(int(limit or _DEFAULT_VIDEO_PAGE_LIMIT), _MAX_VIDEO_PAGE_LIMIT))
    safe_offset = max(0, int(offset or 0))
    page = filtered_rows[safe_offset : safe_offset + safe_limit]

    payload: Dict[str, Any] = {
        "api_version": API_VERSION,
        "ok": True,
        "videos": page,
        "meta": {
            "returned": len(page),
            "total_listed": len(filtered_rows),
            "total_ready": total_ready,
            "offset": safe_offset,
            "limit": safe_limit,
            "ready_only": bool(ready_only),
            "libraries_scanned": libraries_scanned,
            "filters": {
                "video_id": video_id_text or None,
                "q": str(q or "").strip() or None,
                "has_evidence": has_evidence,
            },
        },
    }
    if scoped_library_path:
        payload["library_path"] = scoped_library_path
        payload["library_display_name"] = _library_display_name(scoped_library_path)
    return payload


def list_agent_library_videos(
    library_path: str,
    *,
    video_id: Optional[str] = None,
    q: Optional[str] = None,
    has_evidence: Optional[bool] = None,
    ready_only: bool = True,
    limit: int = _DEFAULT_VIDEO_PAGE_LIMIT,
    offset: int = 0,
    config=None,
) -> Dict[str, Any]:
    return list_agent_videos(
        library_path,
        video_id=video_id,
        q=q,
        has_evidence=has_evidence,
        ready_only=ready_only,
        limit=limit,
        offset=offset,
        config=config,
    )
