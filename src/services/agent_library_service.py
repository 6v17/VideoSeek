"""Read-only library discovery for the Agent API."""

from __future__ import annotations

import os
from typing import Any, Dict, Iterator, List, Optional

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


def _derive_subtitle_library_index_state(
    stored: str,
    *,
    video_count_total: int,
    video_count_subtitle_ready: int,
) -> tuple[str, bool]:
    """Align index_state with whether dialogue search can return hits for this library."""
    ready = max(0, int(video_count_subtitle_ready or 0))
    total = max(0, int(video_count_total or 0))
    searchable = ready > 0
    if ready <= 0:
        state = str(stored or "").strip().lower() or "pending"
        if state not in {"pending", "indexing", "error", "unknown", "missing"}:
            state = "pending"
        return state, False
    if total > 0 and ready >= total:
        return "ready", True
    return "partial", True


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


def _iter_library_video_rows(
    library_path: str,
    library_data: dict,
    *,
    ready_only: bool,
    probe_source_exists: bool = False,
) -> Iterator[Dict[str, Any]]:
    """Yield video rows for one library.

    By default trusts meta ``asset_state`` for readiness (no per-file ``isfile``).
    Set ``probe_source_exists=True`` only for rows that will be returned to clients.
    """
    files = library_data.get("files", {}) if isinstance(library_data, dict) else {}
    if not isinstance(files, dict):
        files = {}

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
        if ready_only and asset_state != "ready":
            continue
        # Cheap existence: trust meta unless caller asks to probe the page rows.
        source_exists = asset_state != "missing_source"
        if probe_source_exists:
            source_exists = os.path.isfile(abs_path)
            if ready_only and not source_exists:
                continue
        yield {
            "video_path": abs_path,
            "video_rel_path": rel_text.replace("\\", "/"),
            "video_id": video_id,
            "library_path": library_path,
            "library_display_name": _library_display_name(library_path),
            "asset_state": asset_state,
            "source_exists": source_exists,
        }


def _collect_library_video_rows(
    library_path: str,
    library_data: dict,
    *,
    ready_only: bool,
) -> List[Dict[str, Any]]:
    """Compatibility helper — materializes one library (tests / small scopes)."""
    return list(
        _iter_library_video_rows(
            library_path,
            library_data,
            ready_only=ready_only,
            probe_source_exists=True,
        )
    )


def list_agent_videos(
    library_path: Optional[str] = None,
    *,
    video_id: Optional[str] = None,
    q: Optional[str] = None,
    ready_only: bool = True,
    limit: int = _DEFAULT_VIDEO_PAGE_LIMIT,
    offset: int = 0,
    config=None,
) -> Dict[str, Any]:
    from src.services.library_service import list_libraries

    libraries = list_libraries()
    video_id_text = str(video_id or "").strip()
    safe_limit = max(1, min(int(limit or _DEFAULT_VIDEO_PAGE_LIMIT), _MAX_VIDEO_PAGE_LIMIT))
    safe_offset = max(0, int(offset or 0))

    if library_path:
        resolved_key = _resolve_library_key(library_path, libraries)
        if resolved_key is None:
            raise KeyError(f"Library not found: {library_path}")
        library_keys = [resolved_key]
        libraries_scanned = 1
        scoped_library_path = resolved_key
    else:
        library_keys = sorted(libraries.keys(), key=lambda p: normalize_scope_path(p))
        libraries_scanned = len(library_keys)
        scoped_library_path = None

    # Stream-filter: count all matches from meta; probe isfile only for the page.
    total_listed = 0
    total_ready = 0
    page: List[Dict[str, Any]] = []
    matched_any_for_video_id = False

    for resolved_key in library_keys:
        for row in _iter_library_video_rows(
            resolved_key,
            libraries.get(resolved_key, {}),
            ready_only=ready_only,
            probe_source_exists=False,
        ):
            if video_id_text and str(row.get("video_id") or "").strip() != video_id_text:
                continue
            if video_id_text:
                matched_any_for_video_id = True
            if q and not _video_matches_query(row, q):
                continue

            probed = dict(row)
            exists = os.path.isfile(str(probed.get("video_path") or ""))
            probed["source_exists"] = exists
            if ready_only and not exists:
                continue

            index = total_listed
            total_listed += 1
            if str(probed.get("asset_state") or "") == "ready" and exists:
                total_ready += 1

            if index < safe_offset or len(page) >= safe_limit:
                continue
            page.append(probed)

    if video_id_text and not matched_any_for_video_id:
        raise KeyError(f"Video not found: {video_id_text}")

    payload: Dict[str, Any] = {
        "api_version": API_VERSION,
        "ok": True,
        "videos": page,
        "meta": {
            "returned": len(page),
            "total_listed": total_listed,
            "total_ready": total_ready,
            "offset": safe_offset,
            "limit": safe_limit,
            "ready_only": bool(ready_only),
            "libraries_scanned": libraries_scanned,
            "filters": {
                "video_id": video_id_text or None,
                "q": str(q or "").strip() or None,
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
    ready_only: bool = True,
    limit: int = _DEFAULT_VIDEO_PAGE_LIMIT,
    offset: int = 0,
    config=None,
) -> Dict[str, Any]:
    return list_agent_videos(
        library_path,
        video_id=video_id,
        q=q,
        ready_only=ready_only,
        limit=limit,
        offset=offset,
        config=config,
    )


def list_agent_subtitle_libraries(config=None) -> Dict[str, Any]:
    """Probe global subtitle libraries (independent of CLIP visual libraries)."""
    from src.services.subtitle_library_service import (
        list_subtitle_libraries,
        list_subtitle_search_scope_entries,
    )
    from src.storage.config_store import get_dialogue_search_scope_mode
    from src.storage.lance_dialogue_search import get_dialogue_index_stats

    cfg = config or load_config()
    libraries = list_subtitle_libraries(config=cfg, seed=True)
    by_lib: Dict[str, Dict[str, int]] = {}
    for item in list_subtitle_search_scope_entries(config=cfg):
        lib = normalize_scope_path(str(item.get("library_path") or ""))
        if not lib:
            continue
        bucket = by_lib.setdefault(
            lib,
            {
                "video_count_total": 0,
                "video_count_subtitle_ready": 0,
                "video_count_missing_source": 0,
            },
        )
        bucket["video_count_total"] += 1
        if bool(item.get("has_transcript")) and bool(item.get("source_exists", True)):
            bucket["video_count_subtitle_ready"] += 1
        if not bool(item.get("source_exists", True)):
            bucket["video_count_missing_source"] += 1

    items: List[Dict[str, Any]] = []
    for library_path in sorted(libraries.keys(), key=lambda p: normalize_scope_path(p)):
        key = normalize_scope_path(library_path)
        library_data = libraries.get(library_path, {})
        counts = by_lib.get(
            key,
            {
                "video_count_total": 0,
                "video_count_subtitle_ready": 0,
                "video_count_missing_source": 0,
            },
        )
        # Prefer live entry counts; fall back to meta file count when scan empty.
        if counts["video_count_total"] <= 0 and isinstance(library_data, dict):
            files = library_data.get("files") or {}
            if isinstance(files, dict):
                counts = {
                    "video_count_total": len(files),
                    "video_count_subtitle_ready": 0,
                    "video_count_missing_source": 0,
                }
        stored_state = str((library_data or {}).get("index_state", "") or "").strip().lower()
        index_state, searchable = _derive_subtitle_library_index_state(
            stored_state,
            video_count_total=int(counts["video_count_total"]),
            video_count_subtitle_ready=int(counts["video_count_subtitle_ready"]),
        )
        items.append(
            {
                "library_path": library_path,
                "display_name": _library_display_name(library_path),
                "index_state": index_state,
                "searchable": searchable,
                **counts,
                "offline": not os.path.exists(library_path),
            }
        )

    dialogue_stats = get_dialogue_index_stats(config=cfg)
    return {
        "api_version": API_VERSION,
        "ok": True,
        "libraries": items,
        "meta": {
            "count": len(items),
            "kind": "subtitle",
            "saved_dialogue_search_scope_mode": get_dialogue_search_scope_mode(cfg),
            "dialogue_index_ready": bool(dialogue_stats.get("dialogue_index_ready")),
            "dialogue_indexed_videos": int(dialogue_stats.get("dialogue_indexed_videos") or 0),
            "dialogue_rows": int(dialogue_stats.get("dialogue_rows") or 0),
        },
    }


def list_agent_subtitle_videos(
    library_path: Optional[str] = None,
    *,
    video_id: Optional[str] = None,
    q: Optional[str] = None,
    ready_only: bool = True,
    limit: int = _DEFAULT_VIDEO_PAGE_LIMIT,
    offset: int = 0,
    config=None,
) -> Dict[str, Any]:
    """List videos in global subtitle libraries; ``ready_only`` = has OCR transcript."""
    from src.services.subtitle_library_service import (
        list_subtitle_libraries,
        list_subtitle_search_scope_entries,
    )

    cfg = config or load_config()
    libraries = list_subtitle_libraries(config=cfg, seed=True)
    video_id_text = str(video_id or "").strip()
    safe_limit = max(1, min(int(limit or _DEFAULT_VIDEO_PAGE_LIMIT), _MAX_VIDEO_PAGE_LIMIT))
    safe_offset = max(0, int(offset or 0))

    scoped_library_path = None
    if library_path:
        resolved_key = _resolve_library_key(library_path, libraries)
        if resolved_key is None:
            raise KeyError(f"Subtitle library not found: {library_path}")
        scoped_library_path = resolved_key
        target_key = normalize_scope_path(resolved_key)
        libraries_scanned = 1
    else:
        target_key = ""
        libraries_scanned = len(libraries)

    total_listed = 0
    total_ready = 0
    page: List[Dict[str, Any]] = []
    matched_any_for_video_id = False

    for item in list_subtitle_search_scope_entries(config=cfg):
        row_lib = str(item.get("library_path") or "")
        if target_key and normalize_scope_path(row_lib) != target_key:
            continue
        row = {
            "video_path": item.get("video_path") or "",
            "video_rel_path": item.get("video_rel_path") or "",
            "video_id": item.get("video_id") or "",
            "library_path": row_lib,
            "library_display_name": _library_display_name(row_lib),
            "source_exists": bool(item.get("source_exists", True)),
            "has_transcript": bool(item.get("has_transcript")),
            "asset_state": str(item.get("asset_state") or ""),
        }
        if video_id_text and str(row.get("video_id") or "").strip() != video_id_text:
            continue
        if video_id_text:
            matched_any_for_video_id = True
        if q and not _video_matches_query(row, q):
            continue
        if ready_only and str(row.get("asset_state") or "").strip().lower() != "ready":
            continue

        index = total_listed
        total_listed += 1
        if str(row.get("asset_state") or "").strip().lower() == "ready":
            total_ready += 1
        if index < safe_offset or len(page) >= safe_limit:
            continue
        page.append(row)

    if video_id_text and not matched_any_for_video_id:
        raise KeyError(f"Video not found: {video_id_text}")

    payload: Dict[str, Any] = {
        "api_version": API_VERSION,
        "ok": True,
        "videos": page,
        "meta": {
            "returned": len(page),
            "total_listed": total_listed,
            "total_ready": total_ready,
            "offset": safe_offset,
            "limit": safe_limit,
            "ready_only": bool(ready_only),
            "libraries_scanned": libraries_scanned,
            "kind": "subtitle",
            "filters": {
                "video_id": video_id_text or None,
                "q": str(q or "").strip() or None,
            },
        },
    }
    if scoped_library_path:
        payload["library_path"] = scoped_library_path
        payload["library_display_name"] = _library_display_name(scoped_library_path)
    return payload
