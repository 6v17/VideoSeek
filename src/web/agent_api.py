"""Localhost Agent API (v1): health, search, library discovery, clip export."""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse, PlainTextResponse
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError as exc:
    FastAPI = None
    HTTPException = None
    JSONResponse = None
    PlainTextResponse = None
    BaseModel = object
    Field = lambda *args, **kwargs: None
    uvicorn = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None

from src.services.agent_clip_service import (
    _MAX_BATCH_EXPORT_CLIPS,
    _output_path_allowed,
    _resolve_batch_export_timeout_sec,
    execute_agent_batch_export_clips,
    execute_agent_export_clip,
)
from src.services.agent_evidence_service import (
    AgentEvidenceError,
    build_agent_understanding_health_fields,
    get_agent_video_evidence,
    list_agent_evidence_status,
    resolve_understanding_timeout_sec,
)
from src.utils import normalize_export_encode_mode
from src.services.agent_starter_service import build_agent_doc_payload, build_agent_starter_payload
from src.services.agent_library_service import list_agent_libraries, list_agent_videos
from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.search_index_schema import (
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    get_search_index_schema_version,
    list_library_search_index_summaries,
    needs_search_index_upgrade,
)
from src.services.search_service import load_chunk_search_assets, load_search_assets, run_chunk_search, run_search
from src.services.search_scope import (
    is_search_scoped,
    normalize_scope_path,
    per_library_indexes_ready,
    resolve_default_active_search_scope,
    resolve_effective_search_scope,
    resolve_explicit_scope_library_paths,
    resolve_explicit_scope_video_paths,
    resolve_fetch_top_k,
    scope_request_is_explicit,
)
from src.services.search_request_service import (
    default_agent_image_precision_mode,
    normalize_search_precision_mode,
    resolve_search_query_inputs,
)
from src.storage.config_store import (
    get_active_embedding_spec,
    get_search_mode,
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
    preview_anchor_sec: Optional[float] = None


class AgentBatchSearchExportOptions(BaseModel):
    """Optional: export top hits after batch search (no separate items[] glue)."""

    output_dir: str
    encode_mode: Optional[str] = "copy"
    silent: Optional[bool] = None
    keep_per_source: int = Field(default=1, ge=1, le=50)
    dedupe: bool = True
    continue_on_error: bool = True


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
    export: Optional[AgentBatchSearchExportOptions] = None


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


class AgentExportClipRequest(BaseModel):
    video_path: str
    start_sec: float
    end_sec: float
    output_path: str
    client_request_id: Optional[str] = None
    silent: Optional[bool] = None
    encode_mode: Optional[str] = "copy"


class AgentBatchExportClipItem(BaseModel):
    video_path: str
    start_sec: float
    end_sec: float
    output_path: str
    client_request_id: Optional[str] = None
    silent: Optional[bool] = None
    encode_mode: Optional[str] = None


class AgentBatchExportClipsRequest(BaseModel):
    items: List[AgentBatchExportClipItem] = Field(default_factory=list)
    silent: Optional[bool] = None
    encode_mode: Optional[str] = "copy"
    continue_on_error: bool = True


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


def _build_capabilities(snapshot: Dict[str, Any], *, understanding_ready: bool = False) -> Dict[str, bool]:
    ffmpeg_info = _build_ffmpeg_info()
    return {
        "text_search": True,
        "image_search": True,
        "frame_search": bool(snapshot.get("frame_index_ready")),
        "chunk_search": bool(snapshot.get("chunk_index_ready")),
        "export_manifest": True,
        "export_clip": bool(ffmpeg_info.get("ffmpeg_available")),
        "library_discovery": True,
        "local_ffmpeg_clip": bool(ffmpeg_info.get("ffmpeg_available")),
        "batch_search": True,
        "search_presets": True,
        "search_precision": True,
        "search_telemetry": True,
        "crop_locate": True,
        "video_evidence": True,
        "video_evidence_ready": bool(understanding_ready),
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
    from src.services.search_telemetry import is_telemetry_enabled

    understanding_fields = build_agent_understanding_health_fields(config=config, probe_remote=False)
    from src.services.indexing_runtime_status import get_index_sync_status

    sync_status = get_index_sync_status()
    return {
        "api_version": API_VERSION,
        "ok": True,
        "service": "videoseek-agent-api",
        "index_ready": bool(snapshot["index_ready"]),
        "index_stale": bool(snapshot["index_stale"]),
        "global_index_state": snapshot["global_index_state"],
        **sync_status,
        "index_id": _build_index_id(spec, snapshot),
        "search_mode_default": get_search_mode(config),
        "search_mode_checked": mode,
        "model": spec.get("model_id") or spec.get("provider"),
        "provider": spec.get("provider"),
        "embedding_space": spec.get("embedding_space"),
        "dimension": int(spec.get("dimension") or 0),
        "metric": spec.get("metric"),
        "capabilities": _build_capabilities(
            snapshot,
            understanding_ready=bool(understanding_fields.get("understanding_ready")),
        ),
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
        "agent_api_default_image_precision": default_agent_image_precision_mode(config),
        "max_batch_queries": MAX_BATCH_QUERIES,
        "max_batch_export_clips": _MAX_BATCH_EXPORT_CLIPS,
        "batch_timeout_sec": timeouts["batch_timeout_sec"],
        "search_telemetry_enabled": is_telemetry_enabled(config),
        **understanding_fields,
    }


def _normalize_agent_path(path: str) -> str:
    return normalize_scope_path(path)


def _scope_video_path_set(scope: Optional[AgentSearchScope]) -> Optional[set[str]]:
    paths = resolve_explicit_scope_video_paths(scope)
    if not paths:
        return None
    normalized = {_normalize_agent_path(item) for item in paths}
    return normalized or None


def _scope_library_path_set(scope: Optional[AgentSearchScope]) -> Optional[set[str]]:
    paths = resolve_explicit_scope_library_paths(scope)
    if not paths:
        return None
    normalized = {_normalize_agent_path(item) for item in paths}
    return normalized or None


def _resolve_scope_video_paths(scope: Optional[AgentSearchScope], config=None) -> Optional[List[str]]:
    return resolve_explicit_scope_video_paths(scope, config=config)


def _resolve_scope_library_paths(scope: Optional[AgentSearchScope], config=None) -> Optional[List[str]]:
    return resolve_explicit_scope_library_paths(scope, config=config)


def _per_library_indexes_ready(library_paths: Optional[List[str]], config=None) -> bool:
    return per_library_indexes_ready(library_paths, config=config)


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
    return scope_request_is_explicit(scope)


def _resolve_default_active_scope(config=None) -> tuple[Optional[List[str]], Optional[List[str]]]:
    return resolve_default_active_search_scope(config=config)


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
    return resolve_effective_search_scope(
        body.scope,
        preset_scope_video_paths=preset_scope_video_paths,
        config=config,
    )


def _agent_timeout_settings(config=None) -> Dict[str, float]:
    cfg = config or load_config()
    try:
        fast = float(cfg.get("agent_api_search_timeout_fast_sec", _SEARCH_TIMEOUT_FAST_FALLBACK_SEC))
    except (TypeError, ValueError):
        fast = _SEARCH_TIMEOUT_FAST_FALLBACK_SEC
    try:
        precise = float(cfg.get("agent_api_search_timeout_precise_sec", _SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC))
    except (TypeError, ValueError):
        precise = _SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC
    try:
        batch = float(cfg.get("agent_api_batch_timeout_sec", _BATCH_TIMEOUT_FALLBACK_SEC))
    except (TypeError, ValueError):
        batch = _BATCH_TIMEOUT_FALLBACK_SEC
    return {
        "search_timeout_fast_sec": max(30.0, fast),
        "search_timeout_precise_sec": max(30.0, precise),
        "batch_timeout_sec": max(60.0, batch),
    }


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


def _sanitize_export_filename_stem(stem: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(stem or "").strip())
    cleaned = cleaned.strip(" .") or "clip"
    return cleaned[:80]


def _normalize_export_output_dir(output_dir: str) -> str:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(output_dir or "").strip())))
    if not normalized:
        raise ValueError("export.output_dir is required.")
    if not _output_path_allowed(normalized, config=load_config()):
        raise ValueError("export.output_dir must not be inside an indexed library root.")
    os.makedirs(normalized, exist_ok=True)
    return normalized


def build_batch_export_items_from_search_results(
    search_payload: Dict[str, Any],
    export_opts: AgentBatchSearchExportOptions,
    *,
    mode: str,
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
) -> List[AgentBatchExportClipItem]:
    output_dir = _normalize_export_output_dir(export_opts.output_dir)
    sources = [block for block in (search_payload.get("results") or []) if block.get("ok")]
    raw_items = _manifest_items_from_sources(
        sources,
        keep_per_source=int(export_opts.keep_per_source),
        mode=mode,
        expand_frame_hits=expand_frame_hits,
        pad_before_sec=pad_before_sec,
        pad_after_sec=pad_after_sec,
    )
    if export_opts.dedupe:
        raw_items = dedupe_manifest_items(raw_items, mode=mode)
    if not raw_items:
        return []

    if len(raw_items) > _MAX_BATCH_EXPORT_CLIPS:
        raise ValueError(f"Export item count exceeds limit ({_MAX_BATCH_EXPORT_CLIPS}).")

    items: List[AgentBatchExportClipItem] = []
    used_names: set[str] = set()
    for row in raw_items:
        stem = _sanitize_export_filename_stem(
            row.get("client_request_id") or row.get("query") or row.get("id") or "clip"
        )
        try:
            rank = int(row.get("rank") or 1)
        except (TypeError, ValueError):
            rank = 1
        filename = f"{stem}_rank{rank:02d}.mp4"
        suffix = 1
        while filename.lower() in used_names:
            suffix += 1
            filename = f"{stem}_rank{rank:02d}_{suffix}.mp4"
        used_names.add(filename.lower())
        output_path = os.path.join(output_dir, filename)
        if not _output_path_allowed(output_path):
            raise ValueError(f"export output path is not allowed: {output_path}")
        items.append(
            AgentBatchExportClipItem(
                video_path=str(row["video_path"]),
                start_sec=float(row["start_sec"]),
                end_sec=float(row["end_sec"]),
                output_path=output_path,
                client_request_id=row.get("client_request_id"),
                silent=export_opts.silent,
                encode_mode=export_opts.encode_mode,
            )
        )
    return items


def _attach_batch_search_export(
    search_payload: Dict[str, Any],
    body: AgentBatchSearchRequest,
    *,
    mode: str,
) -> Dict[str, Any]:
    export_opts = body.export
    if export_opts is None:
        return search_payload

    from src.utils import has_ffmpeg

    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available. Install or configure FFmpeg in VideoSeek settings.")

    try:
        items = build_batch_export_items_from_search_results(
            search_payload,
            export_opts,
            mode=mode,
            expand_frame_hits=bool(body.expand_frame_hits),
            pad_before_sec=float(body.pad_before_sec),
            pad_after_sec=float(body.pad_after_sec),
        )
    except ValueError as exc:
        search_payload["export"] = {
            "ok": False,
            "results": [],
            "error": {"code": "invalid_request", "message": str(exc)},
            "meta": {"total": 0, "succeeded": 0, "failed": 0},
        }
        search_payload["ok"] = False
        return search_payload

    if not items:
        search_payload["export"] = {
            "ok": False,
            "results": [],
            "error": {"code": "invalid_request", "message": "No exportable hits from batch search."},
            "meta": {"total": 0, "succeeded": 0, "failed": 0},
        }
        search_payload["ok"] = False
        return search_payload

    export_payload = execute_agent_batch_export_clips(
        AgentBatchExportClipsRequest(
            items=items,
            encode_mode=export_opts.encode_mode,
            silent=export_opts.silent,
            continue_on_error=export_opts.continue_on_error,
        )
    )
    search_payload["export"] = export_payload
    search_payload["ok"] = bool(search_payload.get("ok")) and bool(export_payload.get("ok"))
    search_payload.setdefault("meta", {})["export_output_dir"] = _normalize_export_output_dir(export_opts.output_dir)
    return search_payload


def _resolve_batch_search_export_timeout_sec(body: AgentBatchSearchRequest, config=None) -> float:
    base = _resolve_batch_timeout_sec(body, config=config)
    if body.export is None:
        return base
    try:
        query_count = len(_resolve_batch_queries(body))
    except ValueError:
        query_count = len(body.queries or [])
    item_count = max(1, query_count * int(body.export.keep_per_source))
    encode_mode = normalize_export_encode_mode(body.export.encode_mode or "copy")
    export_sec = _resolve_batch_export_timeout_sec(item_count, encode_mode)
    return min(_BATCH_TIMEOUT_MAX_SEC, base + export_sec)


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
    query_part = resolve_search_query_inputs(
        preset_id=body.preset_id,
        query=body.query,
        query_type=body.query_type,
        config=cfg,
    )
    mode = _normalize_mode(body.mode)
    top_k = _clamp_top_k(body.top_k if body.top_k is not None else query_part.get("default_top_k"))
    min_score = body.min_score if body.min_score is not None else query_part.get("default_min_score")
    search_precision_mode = normalize_search_precision_mode(
        body.search_precision_mode,
        is_text=bool(query_part["is_text"]),
        has_image=bool(query_part["has_image"]),
        config=cfg,
        use_agent_default=True,
    )
    scope_video_paths, scope_library_paths = resolve_effective_search_scope(
        body.scope,
        preset_scope_video_paths=query_part.get("preset_scope_video_paths"),
        config=cfg,
    )

    return {
        "preset": query_part.get("preset"),
        "preset_id": query_part.get("preset_id"),
        "query_label": query_part["query_label"],
        "query_data": query_part["query_data"],
        "query_type": query_part["query_type"],
        "is_text": query_part["is_text"],
        "has_image": query_part["has_image"],
        "query_vector": query_part.get("query_vector"),
        "pixel_query_data": query_part.get("pixel_query_data"),
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


def _resolve_preview_anchor_sec(body: AgentSearchRequest, resolved: Dict[str, Any]) -> Optional[float]:
    if body.preview_anchor_sec is None:
        return None
    try:
        anchor = max(0.0, float(body.preview_anchor_sec))
    except (TypeError, ValueError) as exc:
        raise ValueError("preview_anchor_sec must be a number") from exc
    if not resolved.get("has_image"):
        raise ValueError("preview_anchor_sec requires an image query")
    videos = [str(path or "").strip() for path in (resolved.get("scope_video_paths") or []) if str(path or "").strip()]
    if len(videos) != 1:
        raise ValueError("preview_anchor_sec requires scope.video_paths with exactly one video")
    return anchor


def _record_agent_search_telemetry(
    resolved: Dict[str, Any],
    hits: List[SearchHit],
    *,
    preview_anchor_sec: float | None = None,
) -> None:
    if not resolved.get("has_image") or not hits:
        return
    try:
        from src.services.image_search_rerank import is_likely_cropped_query_image
        from src.services.search_service import resolve_clip_confidence_tier_key
        from src.services.search_telemetry import record_crop_confidence

        query_data = resolved.get("query_data")
        pixel_query_data = resolved.get("pixel_query_data")
        rerank_query = pixel_query_data or query_data
        if not is_likely_cropped_query_image(rerank_query):
            return
        top_score = float(hits[0].score)
        tier_key = resolve_clip_confidence_tier_key(top_score)
        source = "crop_locate" if preview_anchor_sec is not None else "crop_search"
        record_crop_confidence(score=top_score, tier_key=tier_key, source=source)
    except Exception:
        logger.debug("Agent search telemetry skipped", exc_info=True)


def get_agent_search_telemetry(*, locale: str = "zh", config=None) -> Dict[str, Any]:
    from src.services.search_telemetry import (
        format_telemetry_panel,
        get_telemetry_file_path,
        get_telemetry_summary,
        is_telemetry_enabled,
        reload_telemetry_state,
    )

    cfg = config or load_config()
    enabled = is_telemetry_enabled(cfg)
    language = "en" if str(locale or "").lower().startswith("en") else "zh"
    if enabled:
        reload_telemetry_state()
        summary = get_telemetry_summary()
        panel_text = format_telemetry_panel(language=language)
    else:
        summary = {}
        panel_text = format_telemetry_panel(language=language)

    return {
        "api_version": API_VERSION,
        "ok": True,
        "enabled": enabled,
        "summary": summary,
        "panel_text": panel_text,
        "file_path": get_telemetry_file_path(),
    }


def execute_agent_search(body: AgentSearchRequest) -> Dict[str, Any]:
    config = load_config()
    resolved = _resolve_agent_search_inputs(body, config=config)
    preview_anchor_sec = _resolve_preview_anchor_sec(body, resolved)
    if preview_anchor_sec is not None:
        resolved["search_precision_mode"] = "precise"
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
        if preview_anchor_sec is not None:
            search_kwargs["preview_anchor_sec"] = preview_anchor_sec
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
    _record_agent_search_telemetry(resolved, hits, preview_anchor_sec=preview_anchor_sec)
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
    if preview_anchor_sec is not None:
        response["meta"]["preview_anchor_sec"] = preview_anchor_sec
        response["meta"]["crop_locate"] = True
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
        preview_anchor_sec=item.preview_anchor_sec,
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

    payload = {
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
    if body.export is not None:
        payload = _attach_batch_search_export(payload, body, mode=default_mode)
    return payload


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
        self.app.get("/api/v1/agent-starter")(self._agent_starter)
        self.app.get("/api/v1/agent-doc")(self._agent_doc)
        self.app.get("/api/v1/libraries")(self._libraries)
        self.app.get("/api/v1/libraries/videos")(self._library_videos)
        self.app.get("/api/v1/videos")(self._videos)
        self.app.get("/api/v1/search/presets")(self._search_presets)
        self.app.get("/api/v1/search/presets/{preset_id}")(self._search_preset_detail)
        self.app.post("/api/v1/search")(self._search)
        self.app.post("/api/v1/search/batch")(self._search_batch)
        self.app.get("/api/v1/search/telemetry")(self._search_telemetry)
        self.app.get("/api/v1/videos/evidence/status")(self._video_evidence_status)
        self.app.get("/api/v1/videos/evidence")(self._video_evidence)
        self.app.post("/api/v1/export/manifest")(self._export_manifest)
        self.app.post("/api/v1/export/clip")(self._export_clip)
        self.app.post("/api/v1/export/clips/batch")(self._export_clips_batch)

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

    async def _agent_starter(self, mode: Optional[str] = None, locale: Optional[str] = None):
        health = build_health_payload(mode=mode)
        base_url = f"http://{self.host}:{self.port}"
        return build_agent_starter_payload(base_url, health, locale=locale or "zh")

    async def _agent_doc(self, format: Optional[str] = None):
        fmt = str(format or "json").strip().lower()
        if fmt not in {"json", "text"}:
            raise_api_error(400, "invalid_request", "format must be json or text")
        try:
            payload = await asyncio.to_thread(build_agent_doc_payload, api_version=API_VERSION)
        except FileNotFoundError as exc:
            raise_api_error(404, "doc_not_found", str(exc))
        except OSError as exc:
            logger.exception("Agent doc read failed.")
            raise_api_error(500, "query_failed", str(exc))
        if fmt == "text":
            return PlainTextResponse(
                payload["content"],
                media_type="text/markdown; charset=utf-8",
                headers={"X-VideoSeek-Doc-Path": str(payload.get("full_doc_path") or "")},
            )
        return payload

    async def _search_presets(self):
        try:
            return await asyncio.to_thread(list_agent_search_presets)
        except Exception as exc:
            logger.exception("Agent preset list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _libraries(self):
        try:
            return await asyncio.to_thread(list_agent_libraries)
        except Exception as exc:
            logger.exception("Agent library list failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _library_videos(
        self,
        library_path: Optional[str] = None,
        video_id: Optional[str] = None,
        q: Optional[str] = None,
        has_evidence: Optional[bool] = None,
        ready_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ):
        return await self._videos(
            library_path=library_path,
            video_id=video_id,
            q=q,
            has_evidence=has_evidence,
            ready_only=ready_only,
            limit=limit,
            offset=offset,
        )

    async def _videos(
        self,
        library_path: Optional[str] = None,
        video_id: Optional[str] = None,
        q: Optional[str] = None,
        has_evidence: Optional[bool] = None,
        ready_only: bool = True,
        limit: int = 500,
        offset: int = 0,
    ):
        try:
            payload = await asyncio.to_thread(
                list_agent_videos,
                library_path,
                video_id=video_id,
                q=q,
                has_evidence=has_evidence,
                ready_only=ready_only,
                limit=limit,
                offset=offset,
            )
        except KeyError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent synced videos list failed.")
            raise_api_error(500, "query_failed", str(exc))
        return JSONResponse(payload)

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

    async def _search_telemetry(self, locale: Optional[str] = None):
        try:
            return await asyncio.to_thread(get_agent_search_telemetry, locale=locale or "zh")
        except Exception as exc:
            logger.exception("Agent search telemetry failed.")
            raise_api_error(500, "query_failed", str(exc))

    async def _video_evidence_status(self, video_ids: Optional[List[str]] = None):
        ids = [str(item).strip() for item in (video_ids or []) if str(item).strip()]
        if len(ids) == 1 and "," in ids[0]:
            ids = [part.strip() for part in ids[0].split(",") if part.strip()]
        try:
            payload = await asyncio.to_thread(list_agent_evidence_status, ids)
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except Exception as exc:
            logger.exception("Agent evidence status failed.")
            raise_api_error(500, "query_failed", str(exc))
        return JSONResponse(payload)

    async def _video_evidence(
        self,
        video_id: Optional[str] = None,
        video_path: Optional[str] = None,
        start_sec: Optional[float] = None,
        end_sec: Optional[float] = None,
        ensure: bool = False,
    ):
        config = load_config()
        timeout_sec = resolve_understanding_timeout_sec(chunk_count=0, config=config)
        try:
            from src.services.indexing_service import load_video_chunks_by_id
            from src.services.agent_evidence_service import resolve_agent_video_id

            resolved_video_id = await asyncio.to_thread(
                resolve_agent_video_id,
                video_id=video_id,
                video_path=video_path,
                config=config,
            )
            chunks = await asyncio.to_thread(load_video_chunks_by_id, resolved_video_id, config)
            timeout_sec = resolve_understanding_timeout_sec(chunk_count=len(chunks or []), config=config)
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    get_agent_video_evidence,
                    video_id=video_id,
                    video_path=video_path,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    ensure=ensure,
                    config=config,
                ),
                timeout=timeout_sec,
            )
        except AgentEvidenceError as exc:
            raise_api_error(exc.status_code, exc.code, exc.message)
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "understanding_timeout",
                f"Understanding evidence timed out after {int(timeout_sec)} seconds.",
            )
        except Exception as exc:
            logger.exception("Agent video evidence failed.")
            raise_api_error(500, "query_failed", str(exc))
        payload.setdefault("meta", {})
        if isinstance(payload.get("meta"), dict):
            payload["meta"]["understanding_timeout_sec"] = int(timeout_sec)
        return payload

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
        timeout_sec = _resolve_batch_search_export_timeout_sec(body)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_batch_search, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            detail = (
                f"Batch search/export timed out after {int(timeout_sec)} seconds. "
                "Reduce batch size, use search_precision_mode=fast, or raise agent_api_batch_timeout_sec."
            )
            raise_api_error(503, "engine_busy", detail)
        except IndexNotReadyError as exc:
            raise_api_error(409, "index_not_ready", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            message = str(exc)
            if "ffmpeg" in message.lower() and "not available" in message.lower():
                raise_api_error(503, "engine_busy", message)
            raise_api_error(422, "export_failed", message)
        except Exception as exc:
            logger.exception("Agent batch search failed.")
            raise_api_error(422, "query_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["meta"]["batch_timeout_sec"] = int(timeout_sec)
        if body.export is not None:
            payload["meta"]["batch_export_enabled"] = True
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

    async def _export_clip(self, body: AgentExportClipRequest):
        started = time.perf_counter()
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(
                    execute_agent_export_clip,
                    video_path=body.video_path,
                    start_sec=body.start_sec,
                    end_sec=body.end_sec,
                    output_path=body.output_path,
                    client_request_id=body.client_request_id,
                    silent=body.silent,
                    encode_mode=body.encode_mode,
                ),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            raise_api_error(503, "engine_busy", "Clip export timed out after 120 seconds.")
        except FileNotFoundError as exc:
            raise_api_error(404, "invalid_request", str(exc))
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            message = str(exc)
            if "queue is busy" in message.lower():
                raise_api_error(503, "engine_busy", message)
            logger.exception("Agent clip export failed.")
            raise_api_error(422, "export_failed", message)
        except Exception as exc:
            logger.exception("Agent clip export failed.")
            raise_api_error(422, "export_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return JSONResponse(payload)

    async def _export_clips_batch(self, body: AgentBatchExportClipsRequest):
        from src.services.agent_clip_service import _resolve_batch_export_timeout_sec
        from src.utils import normalize_export_encode_mode

        started = time.perf_counter()
        default_mode = normalize_export_encode_mode(body.encode_mode or "copy")
        timeout_sec = _resolve_batch_export_timeout_sec(len(body.items or []), default_mode)
        try:
            payload = await asyncio.wait_for(
                asyncio.to_thread(execute_agent_batch_export_clips, body),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            raise_api_error(
                503,
                "engine_busy",
                (
                    f"Batch clip export timed out after {int(timeout_sec)} seconds. "
                    "Reduce batch size or use encode_mode=copy."
                ),
            )
        except ValueError as exc:
            raise_api_error(400, "invalid_request", str(exc))
        except RuntimeError as exc:
            message = str(exc)
            if "ffmpeg" in message.lower() and "not available" in message.lower():
                raise_api_error(503, "engine_busy", message)
            raise_api_error(422, "export_failed", message)
        except Exception as exc:
            logger.exception("Agent batch clip export failed.")
            raise_api_error(422, "export_failed", str(exc))

        payload.setdefault("meta", {})
        payload["meta"]["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        payload["meta"]["batch_timeout_sec"] = int(timeout_sec)
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
