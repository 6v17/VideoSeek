from __future__ import annotations

from typing import List, Optional

import numpy as np

from src.app.config import DEFAULT_CONFIG
from src.app.logging_utils import get_logger
from src.core.frame_hash import compute_dhash, dhash_similarity
from src.domain.search_hit import SearchHit
from src.utils import get_single_thumbnail

logger = get_logger("image_search_rerank")


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


def _image_pixel_time_window_sec(config) -> float:
    cfg = config or {}
    try:
        return max(0.0, float(cfg.get("image_pixel_rerank_time_window_sec", DEFAULT_CONFIG.get("image_pixel_rerank_time_window_sec", 2.0))))
    except (TypeError, ValueError):
        return 2.0


def _temporal_probe_times(center_sec: float, window_sec: float, step_sec: float = 0.5) -> List[float]:
    center = max(0.0, float(center_sec))
    window = max(0.0, float(window_sec))
    step = max(0.25, float(step_sec))
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


def _hit_probe_window_sec(hit: SearchHit, config) -> float:
    start = float(hit.start_sec)
    end = float(hit.end_sec)
    chunk_span = max(0.0, end - start)
    default_window = _image_pixel_time_window_sec(config)
    if chunk_span > 0.5:
        return max(default_window, chunk_span / 2.0)
    return default_window


def _best_pixel_match(
    query_hash: int,
    video_path: str,
    center_sec: float,
    config,
    *,
    window_sec: float | None = None,
) -> tuple[float, float]:
    best_time = float(center_sec)
    best_sim = -1.0
    probe_window = _image_pixel_time_window_sec(config) if window_sec is None else max(0.0, float(window_sec))
    for probe_time in _temporal_probe_times(center_sec, probe_window):
        frame = get_single_thumbnail(video_path, probe_time)
        if frame is None or frame.size <= 0:
            continue
        pixel_sim = dhash_similarity(query_hash, compute_dhash(frame))
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
) -> List[SearchHit]:
    if not hits or not _image_pixel_rerank_enabled(config):
        return list(hits or [])

    query_image = _load_query_image_bgr(query_data)
    if query_image is None:
        return list(hits)

    query_hash = compute_dhash(query_image)
    if query_hash <= 0:
        return list(hits)

    top_n = _image_pixel_rerank_top_n(config, len(hits))
    if top_n <= 0:
        return list(hits)

    min_similarity = _image_pixel_min_similarity(config)
    head = list(hits[:top_n])
    tail = list(hits[top_n:])
    reranked_head: List[SearchHit] = []
    deferred: List[SearchHit] = []

    for hit in head:
        clip_score = float(getattr(hit, "score", 0.0) or 0.0)
        center = _hit_probe_center(hit)
        window = _hit_probe_window_sec(hit, config)
        best_time, pixel_sim = _best_pixel_match(
            query_hash,
            hit.video_path,
            center,
            config,
            window_sec=window,
        )
        span_end = float(hit.end_sec)
        span_start = float(hit.start_sec)
        is_chunk_span = span_end > span_start + 0.5
        if pixel_sim < 0.0:
            reranked_head.append(SearchHit(hit.start_sec, hit.end_sec, clip_score, hit.video_path))
            continue

        if pixel_sim < min_similarity:
            end_sec = span_end if is_chunk_span else best_time
            deferred.append(SearchHit(best_time, end_sec, clip_score * 0.5, hit.video_path))
            continue

        combined = (0.35 * clip_score) + (0.65 * pixel_sim)
        end_sec = span_end if is_chunk_span else best_time
        reranked_head.append(SearchHit(best_time, end_sec, combined, hit.video_path))

    reranked_head.sort(key=lambda item: float(item.score), reverse=True)
    merged = reranked_head + deferred + tail
    if top_k is not None and top_k > 0:
        return merged[: int(top_k)]
    return merged
