"""Localhost Agent API (v1): health + visual search only."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as exc:
    FastAPI = None
    HTTPException = None
    JSONResponse = None
    BaseModel = object
    Field = lambda *args, **kwargs: None
    uvicorn = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from src.app.config import DEFAULT_CONFIG, load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.search_index_schema import (
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    get_search_index_schema_version,
    library_index_is_ready,
    list_library_search_index_summaries,
    needs_search_index_upgrade,
)
from src.services.search_service import load_chunk_search_assets, load_search_assets, run_chunk_search, run_search
from src.services.search_scope import (
    is_search_scoped,
    normalize_scope_path,
    resolve_active_search_library_scope,
    resolve_active_search_video_scope,
    resolve_fetch_top_k,
)
from src.storage.config_store import (
    get_active_embedding_spec,
    get_search_mode,
    get_search_scope_library_paths,
    get_search_scope_mode,
    get_search_top_k,
)

logger = get_logger("agent_api")

API_VERSION = "1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Fallbacks when config keys are missing (see agent_api_* in config.json).
_SEARCH_TIMEOUT_FAST_FALLBACK_SEC = 90.0
_SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC = 180.0
_BATCH_TIMEOUT_FALLBACK_SEC = 1200.0
_BATCH_TIMEOUT_MAX_SEC = 7200.0
MAX_CONCURRENT_SEARCHES = 2
MAX_BATCH_QUERIES = 64
_BATCH_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

DEFAULT_FRAME_PAD_BEFORE_SEC = 3.0
DEFAULT_FRAME_PAD_AFTER_SEC = 3.0

_search_semaphore = threading.Semaphore(MAX_CONCURRENT_SEARCHES)
_duration_cache: Dict[str, Optional[float]] = {}
_duration_cache_lock = threading.Lock()


class AgentSearchScope(BaseModel):
    video_paths: Optional[List[str]] = None
    library_paths: Optional[List[str]] = None
    use_saved_scope: bool = False


class AgentSearchRequest(BaseModel):
    query: Optional[str] = None
    preset_id: Optional[str] = None
    query_type: str = "text"
    top_k: Optional[int] = None
    mode: Optional[str] = None
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
    client_request_id: Optional[str] = None
    scope: Optional[AgentSearchScope] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC


class AgentBatchSearchRequest(BaseModel):
    """Batch search: explicit queries and/or all images under image_folder."""

    queries: List[AgentSearchRequest] = Field(default_factory=list)
    image_folder: Optional[str] = None
    top_k: Optional[int] = None
    mode: Optional[str] = None
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
    continue_on_error: bool = True
    scope: Optional[AgentSearchScope] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC


class AgentManifestItem(BaseModel):
    id: Optional[str] = None
    query: Optional[str] = None
    client_request_id: Optional[str] = None
    video_path: str
    start_sec: float
    end_sec: float
    score: Optional[float] = None
    rank: Optional[int] = None
    notes: Optional[str] = None


class AgentManifestRequest(BaseModel):
    project: str = "rough-cut"
    items: Optional[List[AgentManifestItem]] = None
    sources: Optional[List[Dict[str, Any]]] = None
    keep_per_source: int = Field(default=2, ge=1, le=50)
    dedupe: bool = True
    write_path: Optional[str] = None
    expand_frame_hits: bool = True
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC
    mode: Optional[str] = None


def _normalize_mode(mode: Optional[str]) -> str:
    config = load_config()
    normalized = str(mode or get_search_mode(config)).strip().lower()
    if normalized not in {"frame", "chunk"}:
        normalized = get_search_mode(config)
    return normalized


def _clamp_top_k(top_k: Optional[int]) -> int:
    config = load_config()
    default_k = get_search_top_k(config)
    if top_k is None:
        return default_k
    try:
        value = int(top_k)
    except (TypeError, ValueError):
        return default_k
    return max(1, min(200, value))


def _count_library_videos() -> int:
    from src.services.library_service import list_libraries

    total = 0
    for library in list_libraries().values():
        files = library.get("files", {}) if isinstance(library, dict) else {}
        if isinstance(files, dict):
            total += len(files)
    return total


def _index_vector_count(search_index) -> int:
    return int(getattr(search_index, "ntotal", 0) or 0) if search_index is not None else 0


def _library_index_snapshot(config=None) -> Dict[str, Any]:
    from src.storage.asset_store import load_model_metadata

    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    schema_version = get_search_index_schema_version(meta)
    summaries = (
        list_library_search_index_summaries(meta, config=cfg)
        if schema_version >= TARGET_SEARCH_INDEX_SCHEMA_VERSION
        else []
    )
    ready_count = sum(1 for item in summaries if str(item.get("status", "")).strip().lower() == "ready")
    stale_count = sum(1 for item in summaries if str(item.get("status", "")).strip().lower() == "stale")
    return {
        "search_index_schema_version": schema_version,
        "library_indexes_upgrade_needed": needs_search_index_upgrade(meta, config=cfg),
        "library_index_count": len(summaries),
        "library_indexes_ready": ready_count,
        "library_indexes_stale": stale_count,
    }


def _index_snapshot(mode: str, config=None) -> Dict[str, Any]:
    cfg = config or load_config()
    frame_index, _frame_ts, frame_paths = load_search_assets(cfg)
    chunk_index, _chunk_ranges, chunk_paths = load_chunk_search_assets(cfg)

    if mode == "chunk":
        search_index = chunk_index
        video_paths = chunk_paths
    else:
        search_index = frame_index
        video_paths = frame_paths

    vector_count = _index_vector_count(search_index)
    unique_paths = set()
    if video_paths:
        unique_paths = {str(path) for path in video_paths if path}
    index_ready = search_index is not None and vector_count > 0
    from src.services.library_service import get_global_index_state

    global_state = str(get_global_index_state() or "").strip().lower()
    frame_vector_count = _index_vector_count(frame_index)
    chunk_vector_count = _index_vector_count(chunk_index)
    library_snapshot = _library_index_snapshot(cfg)
    return {
        "index_ready": index_ready,
        "vector_count": vector_count,
        "indexed_video_paths": len(unique_paths),
        "global_index_state": global_state or "fresh",
        "index_stale": global_state == "stale",
        "frame_index_ready": frame_index is not None and frame_vector_count > 0,
        "chunk_index_ready": chunk_index is not None and chunk_vector_count > 0,
        "frame_vector_count": frame_vector_count,
        "chunk_vector_count": chunk_vector_count,
        **library_snapshot,
    }


def _build_index_id(spec: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    model_id = str(spec.get("model_id") or spec.get("provider") or "unknown").strip()
    dimension = int(spec.get("dimension") or 0)
    metric = str(spec.get("metric") or "ip").strip().lower() or "ip"
    embedding_space = str(spec.get("embedding_space") or model_id).strip()
    state = str(snapshot.get("global_index_state") or "fresh").strip().lower()
    return f"{embedding_space}_{dimension}_{metric}_{state}"


def _build_capabilities(snapshot: Dict[str, Any]) -> Dict[str, bool]:
    ffmpeg_info = _build_ffmpeg_info()
    return {
        "text_search": True,
        "image_search": True,
        "frame_search": bool(snapshot.get("frame_index_ready")),
        "chunk_search": bool(snapshot.get("chunk_index_ready")),
        "export_manifest": True,
        "export_clip": False,
        "local_ffmpeg_clip": bool(ffmpeg_info.get("ffmpeg_available")),
        "batch_search": True,
        "search_presets": True,
        "search_precision": True,
    }


def _build_ffmpeg_info() -> Dict[str, Any]:
    from src.utils import has_ffmpeg, resolve_ffmpeg_path_info

    resolved_path, source = resolve_ffmpeg_path_info()
    available = bool(has_ffmpeg())
    path = str(resolved_path or "").strip()
    return {
        "ffmpeg_available": available,
        "ffmpeg_path": path,
        "ffmpeg_source": str(source or "missing"),
    }


def api_error_payload(code: str, message: str) -> Dict[str, Any]:
    return {
        "api_version": API_VERSION,
        "ok": False,
        "error": {"code": str(code), "message": str(message)},
    }


def raise_api_error(status_code: int, code: str, message: str) -> None:
    if HTTPException is None:
        raise RuntimeError(f"{code}: {message}")
    raise HTTPException(status_code=status_code, detail=api_error_payload(code, message))


def build_health_payload(mode: Optional[str] = None) -> Dict[str, Any]:
    config = load_config()
    mode = _normalize_mode(mode)
    spec = get_active_embedding_spec(config=config)
    snapshot = _index_snapshot(mode)
    timeouts = _agent_timeout_settings(config)
    return {
        "api_version": API_VERSION,
        "ok": True,
        "service": "videoseek-agent-api",
        "index_ready": bool(snapshot["index_ready"]),
        "index_stale": bool(snapshot["index_stale"]),
        "global_index_state": snapshot["global_index_state"],
        "index_id": _build_index_id(spec, snapshot),
        "search_mode_default": get_search_mode(config),
        "search_mode_checked": mode,
        "model": spec.get("model_id") or spec.get("provider"),
        "provider": spec.get("provider"),
        "embedding_space": spec.get("embedding_space"),
        "dimension": int(spec.get("dimension") or 0),
        "metric": spec.get("metric"),
        "capabilities": _build_capabilities(snapshot),
        "ffmpeg": _build_ffmpeg_info(),
        "video_count": _count_library_videos(),
        "vector_count": snapshot["vector_count"],
        "indexed_video_paths": snapshot["indexed_video_paths"],
        "frame_vector_count": snapshot["frame_vector_count"],
        "chunk_vector_count": snapshot["chunk_vector_count"],
        "search_index_schema_version": snapshot["search_index_schema_version"],
        "library_indexes_upgrade_needed": bool(snapshot["library_indexes_upgrade_needed"]),
        "library_index_count": snapshot["library_index_count"],
        "library_indexes_ready": snapshot["library_indexes_ready"],
        "library_indexes_stale": snapshot["library_indexes_stale"],
        "saved_search_scope_mode": get_search_scope_mode(config),
        "max_concurrent_searches": MAX_CONCURRENT_SEARCHES,
        "search_timeout_sec": timeouts["search_timeout_fast_sec"],
        "search_timeout_precise_sec": timeouts["search_timeout_precise_sec"],
        "agent_api_default_image_precision": _default_image_precision_mode(config),
        "max_batch_queries": MAX_BATCH_QUERIES,
        "batch_timeout_sec": timeouts["batch_timeout_sec"],
    }


def _normalize_agent_path(path: str) -> str:
    return normalize_scope_path(path)


def _scope_video_path_set(scope: Optional[AgentSearchScope]) -> Optional[set[str]]:
    if scope is None or not scope.video_paths:
        return None
    normalized = {_normalize_agent_path(item) for item in scope.video_paths if str(item or "").strip()}
    return normalized or None


def _scope_library_path_set(scope: Optional[AgentSearchScope]) -> Optional[set[str]]:
    library_paths = _resolve_scope_library_paths(scope)
    if not library_paths:
        return None
    normalized = {_normalize_agent_path(item) for item in library_paths}
    return normalized or None


def _resolve_scope_video_paths(scope: Optional[AgentSearchScope], config=None) -> Optional[List[str]]:
    if scope is not None and scope.video_paths:
        paths = [str(item).strip() for item in scope.video_paths if str(item or "").strip()]
        if paths:
            return paths
    if scope is None or not bool(getattr(scope, "use_saved_scope", False)):
        return None
    cfg = config or load_config()
    if get_search_scope_mode(cfg) != "selected":
        return None
    from src.storage.config_store import get_search_scope_video_paths

    saved = [str(item).strip() for item in get_search_scope_video_paths(cfg) if str(item or "").strip()]
    return saved or None


def _resolve_scope_library_paths(scope: Optional[AgentSearchScope], config=None) -> Optional[List[str]]:
    if scope is None:
        return None
    explicit = [str(item).strip() for item in (scope.library_paths or []) if str(item or "").strip()]
    if explicit:
        return explicit
    if not bool(getattr(scope, "use_saved_scope", False)):
        return None
    cfg = config or load_config()
    if get_search_scope_mode(cfg) != "selected":
        return None
    from src.storage.config_store import get_search_scope_video_paths

    if get_search_scope_video_paths(cfg):
        return None
    saved = [str(item).strip() for item in get_search_scope_library_paths(cfg) if str(item or "").strip()]
    return saved or None


def _per_library_indexes_ready(library_paths: Optional[List[str]], config=None) -> bool:
    if not library_paths:
        return False
    from src.storage.asset_store import load_model_metadata

    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    if get_search_index_schema_version(meta) < TARGET_SEARCH_INDEX_SCHEMA_VERSION:
        return False
    return all(library_index_is_ready(path, config=cfg) for path in library_paths)


def _search_index_ready_for_request(mode: str, scope: Optional[AgentSearchScope], config=None) -> bool:
    cfg = config or load_config()
    snapshot = _index_snapshot(mode, config=cfg)
    scope_library_paths = _resolve_scope_library_paths(scope, config=cfg)
    scope_video_paths = _resolve_scope_video_paths(scope, config=cfg)
    if scope_video_paths:
        return True
    if scope_library_paths and not scope_video_paths and _per_library_indexes_ready(scope_library_paths, config=cfg):
        return True
    return bool(snapshot["index_ready"])


def _resolve_fetch_top_k(top_k: int, scope: Optional[AgentSearchScope], config=None) -> int:
    cfg = config or load_config()
    scope_library_paths = _resolve_scope_library_paths(scope, config=cfg)
    scope_video_paths = _resolve_scope_video_paths(scope)
    return _resolve_fetch_top_k_for_paths(
        top_k,
        scope_video_paths,
        scope_library_paths,
        config=cfg,
    )


def _resolve_fetch_top_k_for_paths(
    top_k: int,
    scope_video_paths: Optional[List[str]],
    scope_library_paths: Optional[List[str]],
    config=None,
) -> int:
    cfg = config or load_config()
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    if scoped and scope_library_paths and not scope_video_paths and _per_library_indexes_ready(scope_library_paths, config=cfg):
        return top_k
    return resolve_fetch_top_k(top_k, scoped)


def _scope_request_is_explicit(scope: Optional[AgentSearchScope]) -> bool:
    if scope is None:
        return False
    if scope.video_paths or scope.library_paths:
        return True
    return bool(scope.use_saved_scope)


def _resolve_default_active_scope(config=None) -> tuple[Optional[List[str]], Optional[List[str]]]:
    cfg = config or load_config()
    scope_video_paths = resolve_active_search_video_scope(config=cfg)
    scope_library_paths = None if scope_video_paths else resolve_active_search_library_scope(config=cfg)
    return scope_video_paths, scope_library_paths


def _scope_from_resolved_paths(
    scope_video_paths: Optional[List[str]],
    scope_library_paths: Optional[List[str]],
) -> Optional[AgentSearchScope]:
    if scope_video_paths:
        return AgentSearchScope(video_paths=list(scope_video_paths))
    if scope_library_paths:
        return AgentSearchScope(library_paths=list(scope_library_paths))
    return None


def _resolve_agent_search_scope(
    body: AgentSearchRequest,
    *,
    preset_scope_video_paths: Optional[List[str]] = None,
    config=None,
) -> tuple[Optional[List[str]], Optional[List[str]]]:
    """Mirror desktop search scope: explicit request scope, else active saved scope."""
    cfg = config or load_config()
    if _scope_request_is_explicit(body.scope):
        scope_library_paths = _resolve_scope_library_paths(body.scope, config=cfg)
        scope_video_paths = _resolve_scope_video_paths(body.scope, config=cfg)
        return scope_video_paths, scope_library_paths

    scope_video_paths = list(preset_scope_video_paths) if preset_scope_video_paths else None
    if scope_video_paths:
        return scope_video_paths, None

    return _resolve_default_active_scope(config=cfg)


def _agent_timeout_settings(config=None) -> Dict[str, float]:
    cfg = config or load_config()
    try:
        fast = float(cfg.get("agent_api_search_timeout_fast_sec", DEFAULT_CONFIG["agent_api_search_timeout_fast_sec"]))
    except (TypeError, ValueError):
        fast = _SEARCH_TIMEOUT_FAST_FALLBACK_SEC
    try:
        precise = float(cfg.get("agent_api_search_timeout_precise_sec", DEFAULT_CONFIG["agent_api_search_timeout_precise_sec"]))
    except (TypeError, ValueError):
        precise = _SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC
    try:
        batch = float(cfg.get("agent_api_batch_timeout_sec", DEFAULT_CONFIG["agent_api_batch_timeout_sec"]))
    except (TypeError, ValueError):
        batch = _BATCH_TIMEOUT_FALLBACK_SEC
    return {
        "search_timeout_fast_sec": max(30.0, fast),
        "search_timeout_precise_sec": max(30.0, precise),
        "batch_timeout_sec": max(60.0, batch),
    }


def _default_image_precision_mode(config=None) -> str:
    cfg = config or load_config()
    value = str(cfg.get("agent_api_default_image_precision", DEFAULT_CONFIG["agent_api_default_image_precision"])).strip().lower()
    return value if value in {"fast", "precise"} else "fast"


def _resolve_search_timeout_sec(body: AgentSearchRequest, config=None) -> float:
    cfg = config or load_config()
    timeouts = _agent_timeout_settings(cfg)
    try:
        resolved = _resolve_agent_search_inputs(body, config=cfg)
        if resolved["search_precision_mode"] == "precise":
            return timeouts["search_timeout_precise_sec"]
    except Exception:
        if str(body.search_precision_mode or "").strip().lower() == "precise":
            return timeouts["search_timeout_precise_sec"]
    return timeouts["search_timeout_fast_sec"]


def _batch_requests_precise_mode(body: AgentBatchSearchRequest, config=None) -> bool:
    cfg = config or load_config()
    try:
        queries = _resolve_batch_queries(body)
    except ValueError:
        return False
    for item in queries:
        try:
            resolved = _resolve_agent_search_inputs(item, config=cfg)
        except ValueError:
            continue
        if resolved["search_precision_mode"] == "precise":
            return True
    return False


def _resolve_batch_timeout_sec(body: AgentBatchSearchRequest, config=None) -> float:
    cfg = config or load_config()
    timeouts = _agent_timeout_settings(cfg)
    per_item = (
        timeouts["search_timeout_precise_sec"]
        if _batch_requests_precise_mode(body, config=cfg)
        else timeouts["search_timeout_fast_sec"]
    )
    try:
        query_count = len(_resolve_batch_queries(body))
    except ValueError:
        query_count = len(body.queries or [])
    estimated = max(1, query_count) * per_item
    return min(_BATCH_TIMEOUT_MAX_SEC, max(timeouts["batch_timeout_sec"], estimated * 1.1))


def _normalize_search_precision_mode(
    mode: Optional[str],
    *,
    is_text: bool,
    has_image: bool,
    config=None,
) -> str:
    if is_text and not has_image:
        return "fast"
    if mode is None and has_image:
        mode = _default_image_precision_mode(config)
    normalized = str(mode or "fast").strip().lower()
    if normalized not in {"fast", "precise"}:
        normalized = "fast"
    return normalized


def _build_scope_meta(scope: Optional[AgentSearchScope], config=None) -> Dict[str, Any]:
    cfg = config or load_config()
    scope_library_paths = _resolve_scope_library_paths(scope, config=cfg)
    scope_video_paths = _resolve_scope_video_paths(scope)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    uses_per_library = bool(
        scope_library_paths
        and not scope_video_paths
        and _per_library_indexes_ready(scope_library_paths, config=cfg)
    )
    return {
        "scope_applied": scoped,
        "scope_video_paths": scope_video_paths or [],
        "scope_library_paths": scope_library_paths or [],
        "scope_uses_per_library_indexes": uses_per_library,
        "scope_use_saved_scope": bool(scope and getattr(scope, "use_saved_scope", False)),
        "saved_search_scope_mode": get_search_scope_mode(cfg),
    }


def _get_video_duration_cached(video_path: str) -> Optional[float]:
    key = _normalize_agent_path(video_path)
    with _duration_cache_lock:
        if key in _duration_cache:
            return _duration_cache[key]
    duration = None
    try:
        from src.utils import get_video_duration_seconds

        raw = get_video_duration_seconds(video_path)
        if raw is not None:
            duration = float(raw)
            if duration <= 0:
                duration = None
    except Exception:
        duration = None
    with _duration_cache_lock:
        _duration_cache[key] = duration
    return duration


def _format_timecode(seconds: float) -> str:
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _is_frame_point_hit(start_sec: float, end_sec: float) -> bool:
    return abs(float(end_sec) - float(start_sec)) < 0.01


def _expand_clip_window(
    start_sec: float,
    end_sec: float,
    *,
    mode: str,
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
    video_path: str,
) -> Dict[str, Any]:
    raw_start = float(start_sec)
    raw_end = float(end_sec)
    clip_start = raw_start
    clip_end = raw_end
    padding_applied = False

    if expand_frame_hits and mode == "frame" and _is_frame_point_hit(raw_start, raw_end):
        clip_start = max(0.0, raw_start - float(pad_before_sec))
        clip_end = raw_end + float(pad_after_sec)
        padding_applied = True

    duration = _get_video_duration_cached(video_path)
    if duration is not None:
        clip_start = max(0.0, min(clip_start, duration))
        clip_end = max(clip_start, min(clip_end, duration))

    return {
        "start_sec": clip_start,
        "end_sec": clip_end,
        "raw_start_sec": raw_start,
        "raw_end_sec": raw_end,
        "padding_applied": padding_applied,
    }


def _enrich_hit_payload(
    hit: SearchHit,
    *,
    rank: int,
    mode: str,
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
) -> Dict[str, Any]:
    window = _expand_clip_window(
        hit.start_sec,
        hit.end_sec,
        mode=mode,
        expand_frame_hits=expand_frame_hits,
        pad_before_sec=pad_before_sec,
        pad_after_sec=pad_after_sec,
        video_path=str(hit.video_path),
    )
    start_sec = float(window["start_sec"])
    end_sec = float(window["end_sec"])
    duration = _get_video_duration_cached(str(hit.video_path))
    payload = {
        "rank": rank,
        "video_path": str(hit.video_path),
        "start_sec": start_sec,
        "end_sec": end_sec,
        "score": float(hit.score),
        "duration_sec": max(0.0, end_sec - start_sec),
        "start_timecode": _format_timecode(start_sec),
        "end_timecode": _format_timecode(end_sec),
        "clip_window": {
            "start_sec": start_sec,
            "end_sec": end_sec,
            "padding_applied": bool(window["padding_applied"]),
            "raw_start_sec": float(window["raw_start_sec"]),
            "raw_end_sec": float(window["raw_end_sec"]),
        },
    }
    if duration is not None:
        payload["video_duration_sec"] = duration
    return payload


def _hits_to_payload(
    hits: List[SearchHit],
    *,
    mode: str,
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
) -> List[Dict[str, Any]]:
    return [
        _enrich_hit_payload(
            hit,
            rank=rank,
            mode=mode,
            expand_frame_hits=expand_frame_hits,
            pad_before_sec=pad_before_sec,
            pad_after_sec=pad_after_sec,
        )
        for rank, hit in enumerate(hits, start=1)
    ]


def _interval_overlap_ratio(start_a, end_a, start_b, end_b) -> float:
    left = max(float(start_a), float(start_b))
    right = min(float(end_a), float(end_b))
    overlap = max(0.0, right - left)
    shorter = max(1e-6, min(float(end_a) - float(start_a), float(end_b) - float(start_b)))
    return overlap / shorter


def _should_deduplicate(item_a: Dict[str, Any], item_b: Dict[str, Any], *, mode: str) -> bool:
    if _normalize_agent_path(item_a.get("video_path", "")) != _normalize_agent_path(item_b.get("video_path", "")):
        return False
    if _interval_overlap_ratio(item_a["start_sec"], item_a["end_sec"], item_b["start_sec"], item_b["end_sec"]) > 0.5:
        return True
    if mode == "frame" and abs(float(item_a["start_sec"]) - float(item_b["start_sec"])) <= 2.0:
        return True
    return False


def _manifest_item_rank(item: Dict[str, Any]) -> int:
    try:
        return int(item.get("rank") or 9999)
    except (TypeError, ValueError):
        return 9999


def dedupe_manifest_items(items: List[Dict[str, Any]], *, mode: str) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=_manifest_item_rank)
    kept: List[Dict[str, Any]] = []
    for candidate in ordered:
        if any(_should_deduplicate(candidate, existing, mode=mode) for existing in kept):
            continue
        kept.append(candidate)
    return kept


def _manifest_items_from_sources(
    sources: List[Dict[str, Any]],
    *,
    keep_per_source: int,
    mode: Optional[str],
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for block in sources:
        if not block.get("ok", True) and block.get("error"):
            continue
        block_mode = str(block.get("mode") or mode or "chunk")
        query = str(block.get("query") or "")
        client_request_id = block.get("client_request_id")
        hits = sorted(block.get("hits") or [], key=lambda row: row.get("rank", 999))
        for hit in hits[:keep_per_source]:
            stem = str(client_request_id or query or "item")
            item_id = f"{stem}-rank-{hit.get('rank', 1)}"
            items.append(
                {
                    "id": item_id,
                    "query": query,
                    "client_request_id": client_request_id,
                    "video_path": hit["video_path"],
                    "start_sec": float(hit["start_sec"]),
                    "end_sec": float(hit["end_sec"]),
                    "score": hit.get("score"),
                    "rank": hit.get("rank"),
                    "duration_sec": hit.get("duration_sec", max(0.0, float(hit["end_sec"]) - float(hit["start_sec"]))),
                    "start_timecode": hit.get("start_timecode") or _format_timecode(hit["start_sec"]),
                    "end_timecode": hit.get("end_timecode") or _format_timecode(hit["end_sec"]),
                    "clip_window": hit.get("clip_window"),
                    "video_duration_sec": hit.get("video_duration_sec"),
                    "notes": f"source_query={query}" if query else "",
                }
            )
    return items


def execute_export_manifest(body: AgentManifestRequest) -> Dict[str, Any]:
    mode = _normalize_mode(body.mode) if body.mode else "chunk"
    if body.items:
        raw_items = [item.model_dump() for item in body.items]
    elif body.sources:
        raw_items = _manifest_items_from_sources(
            body.sources,
            keep_per_source=body.keep_per_source,
            mode=body.mode,
            expand_frame_hits=body.expand_frame_hits,
            pad_before_sec=body.pad_before_sec,
            pad_after_sec=body.pad_after_sec,
        )
    else:
        raise ValueError("Provide items or sources.")

    if not raw_items:
        raise ValueError("Manifest has no clip items.")

    deduped = dedupe_manifest_items(raw_items, mode=mode) if body.dedupe else list(raw_items)
    manifest = {"version": 1, "project": body.project, "items": deduped}
    written_path = None
    if body.write_path:
        target = os.path.normpath(os.path.abspath(os.path.expanduser(str(body.write_path).strip())))
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
        written_path = target

    return {
        "api_version": API_VERSION,
        "ok": True,
        "manifest": manifest,
        "meta": {
            "item_count": len(deduped),
            "dedupe": bool(body.dedupe),
            "write_path": written_path,
        },
    }


def _filter_hits(hits: List[SearchHit], min_score: Optional[float]) -> List[SearchHit]:
    if min_score is None:
        return hits
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        return hits
    return [hit for hit in hits if float(hit.score) >= threshold]


def _preset_to_agent_payload(preset: dict, config=None) -> Dict[str, Any]:
    from src.services.search_preset_service import describe_preset_content, resolve_preset_ref_paths

    preset = dict(preset or {})
    ref_count = len(resolve_preset_ref_paths(preset, config=config))
    query = str(preset.get("query", "") or "").strip()
    payload = {
        "id": str(preset.get("id", "") or "").strip(),
        "name": str(preset.get("name", "") or "").strip(),
        "query": query,
        "reference_image_count": ref_count,
        "summary": describe_preset_content(preset, config=config),
    }
    fusion = preset.get("fusion")
    if isinstance(fusion, dict):
        payload["fusion"] = fusion
    if preset.get("top_k") is not None:
        payload["top_k"] = preset.get("top_k")
    if preset.get("min_score") is not None:
        payload["min_score"] = preset.get("min_score")
    return payload


def list_agent_search_presets(config=None) -> Dict[str, Any]:
    from src.services.search_preset_service import list_presets

    cfg = config or load_config()
    presets = [_preset_to_agent_payload(item, config=cfg) for item in list_presets(config=cfg)]
    return {
        "api_version": API_VERSION,
        "ok": True,
        "presets": presets,
        "meta": {"count": len(presets)},
    }


def get_agent_search_preset(preset_id: str, config=None) -> Dict[str, Any]:
    from src.services.search_preset_service import get_preset

    preset_id = str(preset_id or "").strip()
    if not preset_id:
        raise ValueError("preset_id is required")
    cfg = config or load_config()
    preset = get_preset(preset_id, config=cfg)
    if preset is None:
        raise KeyError(f"Preset not found: {preset_id}")
    return {
        "api_version": API_VERSION,
        "ok": True,
        "preset": _preset_to_agent_payload(preset, config=cfg),
    }


def _resolve_agent_search_inputs(body: AgentSearchRequest, config=None) -> Dict[str, Any]:
    cfg = config or load_config()
    preset_id = str(body.preset_id or "").strip()
    query = str(body.query or "").strip()
    if preset_id and query:
        raise ValueError("Provide either preset_id or query, not both.")
    if not preset_id and not query:
        raise ValueError("Provide preset_id or query.")

    preset = None
    query_vector = None
    default_top_k = None
    default_min_score = None
    preset_scope_video_paths = None
    pixel_query_data = None
    has_image = False

    if preset_id:
        from src.services.search_preset_service import build_preset_search_plan

        try:
            plan = build_preset_search_plan(preset_id, config=cfg)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        preset = dict(plan.get("preset") or {})
        query_vector = plan.get("query_vector")
        query_data = plan.get("query_data")
        is_text = bool(plan.get("is_text"))
        has_image = bool(plan.get("has_image"))
        query_label = str(preset.get("name") or preset_id)
        default_top_k = plan.get("top_k")
        default_min_score = plan.get("min_score")
        preset_scope_video_paths = plan.get("scope_video_paths")
        pixel_query_data = plan.get("pixel_query_data")
        query_type = "text" if is_text else "image_path"
    else:
        query_type = str(body.query_type or "text").strip().lower()
        if query_type not in {"text", "image_path"}:
            raise ValueError("query_type must be 'text' or 'image_path'")
        is_text = query_type == "text"
        has_image = not is_text
        if not is_text and not os.path.isfile(query):
            raise ValueError(f"image_path does not exist: {query}")
        query_data = query
        query_label = query
        query_type = query_type

    mode = _normalize_mode(body.mode)
    top_k = _clamp_top_k(body.top_k if body.top_k is not None else default_top_k)
    min_score = body.min_score if body.min_score is not None else default_min_score
    search_precision_mode = _normalize_search_precision_mode(
        body.search_precision_mode,
        is_text=is_text,
        has_image=has_image,
        config=cfg,
    )
    scope_video_paths, scope_library_paths = _resolve_agent_search_scope(
        body,
        preset_scope_video_paths=preset_scope_video_paths,
        config=cfg,
    )

    return {
        "preset": preset,
        "preset_id": preset_id or None,
        "query_label": query_label,
        "query_data": query_data,
        "query_type": query_type,
        "is_text": is_text,
        "has_image": has_image,
        "query_vector": query_vector,
        "pixel_query_data": pixel_query_data,
        "mode": mode,
        "top_k": top_k,
        "min_score": min_score,
        "search_precision_mode": search_precision_mode,
        "scope_library_paths": scope_library_paths,
        "scope_video_paths": scope_video_paths,
    }


def _scope_for_request_meta(body: AgentSearchRequest, resolved: Dict[str, Any]) -> Optional[AgentSearchScope]:
    if body.scope is not None:
        return body.scope
    return _scope_from_resolved_paths(
        resolved.get("scope_video_paths"),
        resolved.get("scope_library_paths"),
    )


def execute_agent_search(body: AgentSearchRequest) -> Dict[str, Any]:
    config = load_config()
    resolved = _resolve_agent_search_inputs(body, config=config)
    mode = resolved["mode"]
    top_k = resolved["top_k"]
    scope_video_paths = resolved["scope_video_paths"]
    scope_library_paths = resolved["scope_library_paths"]
    fetch_k = _resolve_fetch_top_k_for_paths(
        top_k,
        scope_video_paths,
        scope_library_paths,
        config=config,
    )
    snapshot = _index_snapshot(mode, config=config)
    if not _search_index_ready_for_request(mode, _scope_for_request_meta(body, resolved), config=config):
        if scope_library_paths and snapshot.get("library_indexes_upgrade_needed"):
            raise IndexNotReadyError(
                "Per-library search indexes are not ready. Restart VideoSeek and wait for startup data migration to finish."
            )
        raise IndexNotReadyError("Search index is not ready. Sync the library in VideoSeek first.")

    with _search_semaphore:
        search_kwargs = {
            "top_k": top_k,
            "scope_video_paths": scope_video_paths,
            "scope_library_paths": scope_library_paths,
            "query_vector": resolved["query_vector"],
            "search_precision_mode": resolved["search_precision_mode"],
            "pixel_query_data": resolved["pixel_query_data"],
        }
        if mode == "chunk":
            hits = run_chunk_search(
                resolved["query_data"],
                is_text=bool(resolved["is_text"]),
                **search_kwargs,
            )
        else:
            hits = run_search(
                resolved["query_data"],
                is_text=bool(resolved["is_text"]),
                search_mode="frame",
                **search_kwargs,
            )

    hits = _filter_hits(hits, resolved["min_score"])
    scope_meta = _build_scope_meta(_scope_for_request_meta(body, resolved), config=config)
    response = {
        "api_version": API_VERSION,
        "ok": True,
        "query": resolved["query_label"],
        "query_type": resolved["query_type"],
        "mode": mode,
        "client_request_id": body.client_request_id,
        "hits": _hits_to_payload(
            hits,
            mode=mode,
            expand_frame_hits=bool(body.expand_frame_hits),
            pad_before_sec=float(body.pad_before_sec),
            pad_after_sec=float(body.pad_after_sec),
        ),
        "meta": {
            "returned": len(hits),
            "top_k": top_k,
            "fetch_top_k": fetch_k,
            "search_precision_mode": resolved["search_precision_mode"],
            "index_ready": True,
            "global_index_state": snapshot["global_index_state"],
            "search_index_schema_version": snapshot.get("search_index_schema_version"),
            **scope_meta,
        },
    }
    if resolved["preset_id"]:
        response["preset_id"] = resolved["preset_id"]
        preset = resolved.get("preset") or {}
        if preset.get("name"):
            response["preset_name"] = str(preset.get("name"))
    return response


def _merge_search_request(item: AgentSearchRequest, batch: AgentBatchSearchRequest) -> AgentSearchRequest:
    return AgentSearchRequest(
        query=item.query,
        preset_id=item.preset_id,
        query_type=item.query_type,
        top_k=item.top_k if item.top_k is not None else batch.top_k,
        mode=item.mode if item.mode is not None else batch.mode,
        min_score=item.min_score if item.min_score is not None else batch.min_score,
        search_precision_mode=(
            item.search_precision_mode
            if item.search_precision_mode is not None
            else batch.search_precision_mode
        ),
        client_request_id=item.client_request_id,
        scope=item.scope if item.scope is not None else batch.scope,
        expand_frame_hits=batch.expand_frame_hits,
        pad_before_sec=batch.pad_before_sec,
        pad_after_sec=batch.pad_after_sec,
    )


def _expand_image_folder(folder: str) -> List[AgentSearchRequest]:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(folder).strip())))
    if not os.path.isdir(normalized):
        raise ValueError(f"image_folder is not a directory: {folder}")

    items = []
    for name in sorted(os.listdir(normalized)):
        path = os.path.join(normalized, name)
        if not os.path.isfile(path):
            continue
        if os.path.splitext(name)[1].lower() not in _BATCH_IMAGE_EXTENSIONS:
            continue
        items.append(
            AgentSearchRequest(
                query=path,
                query_type="image_path",
                client_request_id=name,
            )
        )
    return items


def _resolve_batch_queries(body: AgentBatchSearchRequest) -> List[AgentSearchRequest]:
    expanded = list(body.queries or [])
    if body.image_folder:
        expanded.extend(_expand_image_folder(body.image_folder))
    if not expanded:
        raise ValueError("Provide at least one entry in queries or a non-empty image_folder.")
    if len(expanded) > MAX_BATCH_QUERIES:
        raise ValueError(f"Batch size exceeds limit ({MAX_BATCH_QUERIES}).")
    return [_merge_search_request(item, body) for item in expanded]


def _batch_item_error(
    item: AgentSearchRequest,
    code: str,
    message: str,
    *,
    query_type: Optional[str] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "client_request_id": item.client_request_id,
        "query": item.query or item.preset_id,
        "preset_id": item.preset_id,
        "query_type": query_type or item.query_type,
        "mode": mode,
        "hits": [],
        "error": {"code": code, "message": message},
    }


def execute_agent_batch_search(body: AgentBatchSearchRequest) -> Dict[str, Any]:
    queries = _resolve_batch_queries(body)
    config = load_config()
    default_mode = _normalize_mode(body.mode)
    snapshot = _index_snapshot(default_mode, config=config)
    if _scope_request_is_explicit(body.scope):
        batch_scope = body.scope
        batch_library_paths = _resolve_scope_library_paths(body.scope, config=config)
    else:
        batch_video_paths, batch_library_paths = _resolve_default_active_scope(config=config)
        batch_scope = _scope_from_resolved_paths(batch_video_paths, batch_library_paths)
    if not _search_index_ready_for_request(default_mode, batch_scope, config=config):
        if batch_library_paths and snapshot.get("library_indexes_upgrade_needed"):
            raise IndexNotReadyError(
                "Per-library search indexes are not ready. Restart VideoSeek and wait for startup data migration to finish."
            )
        raise IndexNotReadyError("Search index is not ready. Sync the library in VideoSeek first.")

    results = []
    succeeded = 0
    failed = 0
    for item in queries:
        try:
            payload = execute_agent_search(item)
            payload["ok"] = True
            results.append(payload)
            succeeded += 1
        except ValueError as exc:
            failed += 1
            entry = _batch_item_error(item, "invalid_request", str(exc))
            results.append(entry)
            if not body.continue_on_error:
                break
        except Exception as exc:
            failed += 1
            entry = _batch_item_error(item, "query_failed", str(exc))
            results.append(entry)
            if not body.continue_on_error:
                break

    return {
        "api_version": API_VERSION,
        "ok": failed == 0,
        "results": results,
        "meta": {
            "total": len(queries),
            "processed": len(results),
            "succeeded": succeeded,
            "failed": failed,
            "index_ready": True,
            "global_index_state": snapshot["global_index_state"],
            "continue_on_error": bool(body.continue_on_error),
        },
    }


class IndexNotReadyError(Exception):
    pass


class AgentApiService:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        if _IMPORT_ERROR is not None:
            raise RuntimeError("Missing FastAPI runtime. Install `fastapi` and `uvicorn`.") from _IMPORT_ERROR
        self.host = str(host)
        self.port = int(port)
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._started = threading.Event()
        self._lock = threading.Lock()

        self.app = FastAPI(title="VideoSeek Agent API", version=API_VERSION)
        self._register_exception_handlers()
        self.app.get("/api/v1/health")(self._health)
        self.app.get("/api/v1/search/presets")(self._search_presets)
        self.app.get("/api/v1/search/presets/{preset_id}")(self._search_preset_detail)
        self.app.post("/api/v1/search")(self._search)
        self.app.post("/api/v1/search/batch")(self._search_batch)
        self.app.post("/api/v1/export/manifest")(self._export_manifest)

    def _register_exception_handlers(self):
        from fastapi.exceptions import RequestValidationError

        @self.app.exception_handler(HTTPException)
        async def _handle_http_exception(_request, exc: HTTPException):
            body = exc.detail
            if isinstance(body, dict) and body.get("api_version") and body.get("error"):
                payload = body
            elif isinstance(body, dict) and "error" in body and isinstance(body["error"], dict):
                payload = body
            elif isinstance(body, dict):
                payload = api_error_payload(
                    str(body.get("code") or body.get("error") or "request_failed"),
                    str(body.get("message") or body),
                )
            else:
                payload = api_error_payload("request_failed", str(body))
            return JSONResponse(status_code=exc.status_code, content=payload)

        @self.app.exception_handler(RequestValidationError)
        async def _handle_validation_error(_request, exc: RequestValidationError):
            return JSONResponse(
                status_code=400,
                content=api_error_payload("invalid_request", str(exc.errors())),
            )

    def start(self):
        with self._lock:
            if self.is_running():
                return
            config = uvicorn.Config(
                self.app,
                host=self.host,
                port=self.port,
                log_level="warning",
                access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(target=self._run_server, name="AgentApiServer", daemon=True)
            self._thread.start()

        started = False
        for _ in range(30):
            if self._server is not None and getattr(self._server, "started", False):
                started = True
                break
            if self._thread is None or not self._thread.is_alive():
                break
            time.sleep(0.1)
        if not started:
            raise RuntimeError("Agent API server failed to start within 3 seconds.")
        self._started.set()
        logger.info("Agent API listening on http://%s:%s", self.host, self.port)

    def stop(self):
        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None
            self._started.clear()

        if server is None:
            return

        server.should_exit = True
        if thread is not None:
            thread.join(timeout=3.0)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._started.is_set()

    def get_base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _run_server(self):
        try:
            self._server.run()
        except Exception:
            logger.exception("Agent API server crashed.")
        finally:
            self._started.clear()

    async def _health(self, mode: Optional[str] = None):
        return build_health_payload(mode=mode)

    async def _search_presets(self):
        try:
            return await asyncio.to_thread(list_agent_search_presets)
        except Exception as exc:
            logger.exception("Agent preset list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _search_preset_detail(self, preset_id: str):
        try:
            return await asyncio.to_thread(get_agent_search_preset, preset_id)
        except KeyError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent preset detail failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _search(self, body: AgentSearchRequest):
        started = time.perf_counter()
        timeout_sec = _resolve_search_timeout_sec(body)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_search, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "engine_busy",
                (
                    f"Search timed out after {int(timeout_sec)} seconds. "
                    "For precise image search, allow more time or reduce top_k / pixel rerank settings."
                ),
            )
        except IndexNotReadyError as exc:
            raise_api_error(409, "index_not_ready", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            logger.exception("Agent search failed.")
            raise_api_error(422, "query_failed", str(exc))
        except Exception as exc:
            logger.exception("Agent search failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["meta"]["search_timeout_sec"] = int(timeout_sec)
        return JSONResponse(payload)

    async def _search_batch(self, body: AgentBatchSearchRequest):
        started = time.perf_counter()
        timeout_sec = _resolve_batch_timeout_sec(body)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_batch_search, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "engine_busy",
                (
                    f"Batch search timed out after {int(timeout_sec)} seconds. "
                    "Reduce batch size, use search_precision_mode=fast, or raise agent_api_batch_timeout_sec."
                ),
            )
        except IndexNotReadyError as exc:
            raise_api_error(409, "index_not_ready", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent batch search failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["meta"]["batch_timeout_sec"] = int(timeout_sec)
        return JSONResponse(payload)

    async def _export_manifest(self, body: AgentManifestRequest):
        started = time.perf_counter()
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_export_manifest, body),
                timeout=30.0,
            )
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent manifest export failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return JSONResponse(payload)


def is_agent_api_enabled(config=None) -> bool:
    """Whether the localhost Agent API should run (config + env override)."""
    forced = str(os.environ.get("VIDEOSEEK_AGENT_API", "")).strip().lower()
    if forced in {"0", "false", "no", "off"}:
        return False
    if forced in {"1", "true", "yes", "on"}:
        return True
    if config is None:
        config = load_config()
    return bool(config.get("agent_api_enabled", False))


def agent_api_enabled() -> bool:
    return is_agent_api_enabled()
