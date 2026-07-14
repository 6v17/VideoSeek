"""Index snapshot, health payload, ffmpeg, and capabilities helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.config import load_config
from src.services.agent_evidence_service import build_agent_understanding_health_fields
from src.services.search_index_schema import (
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    get_search_index_schema_version,
    list_library_search_index_summaries,
    needs_search_index_upgrade,
)
from src.services.search_request_service import default_agent_image_precision_mode
from src.services.search_service import load_chunk_search_assets, load_search_assets
from src.services.agent_clip_service import _MAX_BATCH_EXPORT_CLIPS
from src.storage.config_store import (
    get_active_embedding_spec,
    get_search_mode,
    get_search_scope_mode,
)

from .constants import (
    API_VERSION,
    _BATCH_TIMEOUT_FALLBACK_SEC,
    MAX_BATCH_QUERIES,
    MAX_CONCURRENT_SEARCHES,
    _SEARCH_TIMEOUT_FAST_FALLBACK_SEC,
    _SEARCH_TIMEOUT_PRECISE_FALLBACK_SEC,
)


def _normalize_mode(mode: Optional[str]) -> str:
    config = load_config()
    normalized = str(mode or get_search_mode(config)).strip().lower()
    if normalized not in {"frame", "chunk"}:
        normalized = get_search_mode(config)
    return normalized


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
    if video_paths:
        indexed_video_paths = len({str(path) for path in video_paths if path})
    elif frame_index is not None:
        from src.storage.config_store import get_local_model_asset_dirs
        from src.storage.lance_search_index import get_lance_indexed_video_ids

        profile_base_dir = get_local_model_asset_dirs(config=cfg)["base_dir"]
        indexed_video_paths = len(get_lance_indexed_video_ids(profile_base_dir))
    else:
        indexed_video_paths = 0
    index_ready = search_index is not None and vector_count > 0
    global_state = "fresh"
    frame_vector_count = _index_vector_count(frame_index)
    chunk_vector_count = _index_vector_count(chunk_index)
    library_snapshot = _library_index_snapshot(cfg)
    return {
        "index_ready": index_ready,
        "vector_count": vector_count,
        "indexed_video_paths": indexed_video_paths,
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
