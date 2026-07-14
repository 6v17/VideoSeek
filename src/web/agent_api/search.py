"""Search and batch search execution and related helpers."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.search_request_service import (
    normalize_search_precision_mode,
    resolve_search_query_inputs,
)
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
from src.services.search_service import run_chunk_search, run_search
from src.storage.config_store import get_search_mode, get_search_scope_mode, get_search_top_k

from .constants import (
    API_VERSION,
    _BATCH_IMAGE_EXTENSIONS,
    _BATCH_TIMEOUT_MAX_SEC,
    MAX_BATCH_QUERIES,
    _duration_cache,
    _duration_cache_lock,
    _search_semaphore,
)
from .errors import IndexNotReadyError
from .export_ops import _attach_batch_search_export, _format_timecode
from .health import _agent_timeout_settings, _index_snapshot, _normalize_mode
from .schemas import AgentBatchSearchRequest, AgentSearchRequest, AgentSearchScope

logger = get_logger("agent_api")


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
