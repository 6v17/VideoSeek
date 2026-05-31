from __future__ import annotations

import threading
from typing import Iterable, Mapping, Optional

import numpy as np

from src.app.config import DEFAULT_CONFIG
from src.app.logging_utils import get_logger
from src.core.frame_hash import compute_dhash, dhash_similarity
from src.domain.search_hit import SearchHit
from src.services.search_profiling import add_profile_counter, add_profile_ms, profiling_active
from src.services.search_scope import normalize_scope_path
from src.utils import get_single_thumbnail, resolve_sampling_fps

logger = get_logger("image_search_rerank")

_PROBE_TIME_QUANTUM_SEC = 0.1
_PROBE_STEP_MIN_SEC = 0.25
_PROBE_STEP_MAX_SEC = 0.5
_PROBE_WINDOW_MIN_SEC = 0.5
_PROBE_WINDOW_MAX_SEC = 2.0
_PROBE_POINT_WINDOW_MIN_SEC = 3.0
_PROBE_POINT_WINDOW_MAX_SEC = 6.0
_INDEX_STEP_FALLBACK_SEC = 1.0
# CLIP leads; pixel only nudges when it is clearly confident.
_CLIP_SCORE_WEIGHT = 0.6
_PIXEL_SCORE_WEIGHT = 0.4

_index_step_lookup_local = threading.local()


def reset_index_step_lookup() -> None:
    _index_step_lookup_local.lookup = None


def get_index_step_lookup() -> dict[str, float] | None:
    lookup = getattr(_index_step_lookup_local, "lookup", None)
    return dict(lookup) if isinstance(lookup, dict) else None


def merge_index_step_lookup(video_paths: Iterable, timestamps: Iterable) -> None:
    merged = build_index_step_by_video(video_paths, timestamps)
    if not merged:
        return
    current = get_index_step_lookup() or {}
    current.update(merged)
    _index_step_lookup_local.lookup = current


def median_index_step(timestamps: Iterable[float]) -> float:
    values = sorted(float(ts) for ts in timestamps)
    if len(values) < 2:
        return _INDEX_STEP_FALLBACK_SEC
    deltas = [
        values[index + 1] - values[index]
        for index in range(len(values) - 1)
        if values[index + 1] > values[index]
    ]
    if not deltas:
        return _INDEX_STEP_FALLBACK_SEC
    return max(float(np.median(deltas)), 0.01)


def build_index_step_by_video(video_paths: Iterable, timestamps: Iterable) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for path, timestamp in zip(video_paths, timestamps):
        key = normalize_scope_path(str(path or ""))
        if not key:
            continue
        buckets.setdefault(key, []).append(float(timestamp))
    return {key: median_index_step(values) for key, values in buckets.items() if values}


def _image_pixel_probe_mode(config) -> str:
    cfg = config or {}
    mode = str(cfg.get("image_pixel_rerank_probe_mode", DEFAULT_CONFIG.get("image_pixel_rerank_probe_mode", "index"))).strip().lower()
    return mode if mode in {"index", "fixed"} else "index"


def _fixed_probe_step_sec(config) -> float:
    cfg = config or {}
    try:
        step = float(cfg.get("image_pixel_rerank_probe_step_sec", DEFAULT_CONFIG.get("image_pixel_rerank_probe_step_sec", 0.5)))
    except (TypeError, ValueError):
        step = 0.5
    return max(_PROBE_STEP_MIN_SEC, min(_PROBE_STEP_MAX_SEC, step))


def _image_pixel_time_window_sec(config) -> float:
    cfg = config or {}
    try:
        return max(0.0, float(cfg.get("image_pixel_rerank_time_window_sec", DEFAULT_CONFIG.get("image_pixel_rerank_time_window_sec", 2.0))))
    except (TypeError, ValueError):
        return 2.0


def resolve_index_step_for_video(video_path: str, config, lookup: Mapping[str, float] | None = None) -> float:
    key = normalize_scope_path(str(video_path or ""))
    if lookup and key in lookup:
        return max(float(lookup[key]), 0.01)
    try:
        fps = float(resolve_sampling_fps(config=config))
    except (TypeError, ValueError):
        fps = float(DEFAULT_CONFIG.get("fps", 1.0) or 1.0)
    return max(1.0 / max(fps, 0.01), 0.01)


def resolve_probe_params(
    index_step: float,
    config,
    *,
    mode: str | None = None,
) -> tuple[float, float]:
    probe_mode = mode or _image_pixel_probe_mode(config)
    normalized_step = max(float(index_step or _INDEX_STEP_FALLBACK_SEC), 0.01)
    if probe_mode == "fixed":
        return _image_pixel_time_window_sec(config), _fixed_probe_step_sec(config)

    window = max(_PROBE_WINDOW_MIN_SEC, min(_PROBE_WINDOW_MAX_SEC, normalized_step))
    dynamic_step = normalized_step / 2.0
    step = max(_PROBE_STEP_MIN_SEC, min(_PROBE_STEP_MAX_SEC, dynamic_step))
    if step >= normalized_step:
        step = max(_PROBE_STEP_MIN_SEC, normalized_step * 0.5)
    if step >= normalized_step:
        step = max(0.01, normalized_step - 0.01)
    return window, step


def _probe_time_key(video_path: str, time_sec: float) -> tuple[str, int]:
    normalized_path = str(video_path or "").strip()
    quantized_ms = int(round(max(0.0, float(time_sec)) / _PROBE_TIME_QUANTUM_SEC))
    return normalized_path, quantized_ms


def _get_thumbnail_cached(
    video_path: str,
    time_sec: float,
    cache: dict[tuple[str, int], object | None],
) -> Optional[np.ndarray]:
    key = _probe_time_key(video_path, time_sec)
    if key in cache:
        if profiling_active():
            add_profile_counter("thumb_cache_hit", 1)
        cached = cache[key]
        return None if cached is None else cached
    from time import perf_counter

    started = perf_counter()
    frame = get_single_thumbnail(video_path, time_sec)
    if profiling_active():
        add_profile_ms("pixel_decode", int((perf_counter() - started) * 1000))
        add_profile_counter("thumb_decode", 1)
    cache[key] = frame
    return frame


def _get_probe_dhash_cached(
    video_path: str,
    time_sec: float,
    thumbnail_cache: dict[tuple[str, int], object | None],
    probe_hash_cache: dict[tuple[str, int], int],
) -> int:
    key = _probe_time_key(video_path, time_sec)
    if key in probe_hash_cache:
        return probe_hash_cache[key]
    from time import perf_counter

    frame = _get_thumbnail_cached(video_path, time_sec, thumbnail_cache)
    if frame is None or frame.size <= 0:
        probe_hash_cache[key] = 0
        return 0
    started = perf_counter()
    value = int(compute_dhash(frame))
    if profiling_active():
        add_profile_ms("pixel_dhash", int((perf_counter() - started) * 1000))
    probe_hash_cache[key] = value
    return value


def _load_query_image_bgr(query_data) -> Optional[np.ndarray]:
    if isinstance(query_data, str):
        from src.core.image_io import load_image_bgr

        return load_image_bgr(query_data)
    if isinstance(query_data, np.ndarray) and query_data.size > 0:
        return query_data
    return None


def _image_pixel_rerank_enabled(config) -> bool:
    cfg = config or {}
    return bool(cfg.get("image_pixel_rerank_enabled", DEFAULT_CONFIG.get("image_pixel_rerank_enabled", True)))


def _image_pixel_rerank_top_n(config, hit_count: int) -> int:
    cfg = config or {}
    try:
        top_n = int(cfg.get("image_pixel_rerank_top_n", DEFAULT_CONFIG.get("image_pixel_rerank_top_n", 20)))
    except (TypeError, ValueError):
        top_n = 20
    return max(0, min(top_n, int(hit_count)))


def _image_pixel_min_similarity(config) -> float:
    cfg = config or {}
    try:
        return float(cfg.get("image_pixel_rerank_min_similarity", DEFAULT_CONFIG.get("image_pixel_rerank_min_similarity", 0.58)))
    except (TypeError, ValueError):
        return 0.58


def _temporal_probe_times(center_sec: float, window_sec: float, step_sec: float) -> list[float]:
    center = max(0.0, float(center_sec))
    window = max(0.0, float(window_sec))
    step = max(0.01, float(step_sec))
    probes = [center]
    offset = step
    while offset <= window + 1e-6:
        if center - offset >= 0.0:
            probes.append(center - offset)
        probes.append(center + offset)
        offset += step
    return probes


def _hit_probe_center(hit: SearchHit) -> float:
    start = float(hit.start_sec)
    end = float(hit.end_sec)
    if end > start + 0.5:
        return (start + end) / 2.0
    return start


def _hit_probe_plan(hit: SearchHit, config, lookup: Mapping[str, float] | None = None) -> tuple[float, float]:
    start = float(hit.start_sec)
    end = float(hit.end_sec)
    chunk_span = max(0.0, end - start)
    index_step = resolve_index_step_for_video(hit.video_path, config, lookup=lookup)
    window, step = resolve_probe_params(index_step, config)
    if chunk_span > 0.5:
        window = min(window, max(index_step, chunk_span / 4.0))
    else:
        point_window = max(
            _PROBE_POINT_WINDOW_MIN_SEC,
            min(_PROBE_POINT_WINDOW_MAX_SEC, index_step * 0.5),
        )
        window = max(window, point_window)
    return window, step


def _best_pixel_match(
    query_hash: int,
    video_path: str,
    center_sec: float,
    config,
    *,
    window_sec: float,
    step_sec: float,
    thumbnail_cache: dict[tuple[str, int], object | None] | None = None,
    probe_hash_cache: dict[tuple[str, int], int] | None = None,
) -> tuple[float, float]:
    best_time = float(center_sec)
    best_sim = -1.0
    frame_cache = thumbnail_cache if thumbnail_cache is not None else {}
    hash_cache = probe_hash_cache if probe_hash_cache is not None else {}
    for probe_time in _temporal_probe_times(center_sec, window_sec, step_sec):
        probe_hash = _get_probe_dhash_cached(
            video_path,
            probe_time,
            frame_cache,
            hash_cache,
        )
        if probe_hash <= 0:
            continue
        pixel_sim = dhash_similarity(query_hash, probe_hash)
        if pixel_sim > best_sim:
            best_sim = pixel_sim
            best_time = float(probe_time)
    return best_time, best_sim


def apply_image_pixel_rerank(
    query_data,
    hits: List[SearchHit],
    *,
    config=None,
    top_k: int | None = None,
    rerank_limit: int | None = None,
    index_step_lookup: Mapping[str, float] | None = None,
) -> List[SearchHit]:
    if not hits or not _image_pixel_rerank_enabled(config):
        return list(hits or [])

    query_image = _load_query_image_bgr(query_data)
    if query_image is None:
        return list(hits)

    query_hash = compute_dhash(query_image)
    if query_hash <= 0:
        return list(hits)

    if rerank_limit is not None and rerank_limit > 0:
        top_n = min(len(hits), int(rerank_limit))
    else:
        top_n = _image_pixel_rerank_top_n(config, len(hits))
    if top_n <= 0:
        return list(hits)

    lookup = index_step_lookup if index_step_lookup is not None else get_index_step_lookup()
    min_similarity = _image_pixel_min_similarity(config)
    head = list(hits[:top_n])
    reranked: List[tuple[int, SearchHit]] = []
    thumbnail_cache: dict[tuple[str, int], object | None] = {}
    probe_hash_cache: dict[tuple[str, int], int] = {}

    for rank, hit in enumerate(head):
        clip_score = float(getattr(hit, "score", 0.0) or 0.0)
        span_end = float(hit.end_sec)
        span_start = float(hit.start_sec)
        is_chunk_span = span_end > span_start + 0.5
        center = _hit_probe_center(hit)
        window, step = _hit_probe_plan(hit, config, lookup=lookup)
        best_time, pixel_sim = _best_pixel_match(
            query_hash,
            hit.video_path,
            center,
            config,
            window_sec=window,
            step_sec=step,
            thumbnail_cache=thumbnail_cache,
            probe_hash_cache=probe_hash_cache,
        )

        if pixel_sim < min_similarity:
            reranked.append((rank, SearchHit(span_start, span_end, clip_score, hit.video_path)))
            continue

        combined = (_CLIP_SCORE_WEIGHT * clip_score) + (_PIXEL_SCORE_WEIGHT * pixel_sim)
        if is_chunk_span:
            reranked.append((rank, SearchHit(span_start, span_end, combined, hit.video_path)))
        else:
            reranked.append((rank, SearchHit(best_time, best_time, combined, hit.video_path)))

    reranked.sort(key=lambda item: (-float(item[1].score), item[0]))
    merged = [hit for _rank, hit in reranked]
    if top_k is not None and top_k > 0:
        return merged[: int(top_k)]
    return merged
