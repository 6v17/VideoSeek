"""Frame neighbor rerank and bounded neighbor refine for CLIP search."""

from __future__ import annotations

from typing import List

import numpy as np

from src.app.config import DEFAULT_CONFIG
from src.domain.search_hit import SearchHit
from src.storage.config_store import get_frame_neighbor_rerank_enabled, get_frame_neighbor_rerank_top_n

from src.services.search_hit_utils import _clamp_time_near_seed

_PRECISE_SEED_MAX_SHIFT_SEC = 5.0
_PRECISE_NEIGHBOR_WINDOW_SEC = 5.0
_PRECISE_NEIGHBOR_BLEND = 0.1


def _neighbor_rerank_enabled(config, is_text: bool = False, precise_image: bool = False) -> bool:
    if is_text or precise_image:
        return False
    return bool(get_frame_neighbor_rerank_enabled(config))


def _neighbor_rerank_window_sec(config, is_text: bool, precise_image: bool = False) -> float:
    cfg = config or {}
    if "frame_neighbor_rerank_window_sec" in cfg:
        try:
            return max(0.5, float(cfg["frame_neighbor_rerank_window_sec"]))
        except (TypeError, ValueError):
            pass
    if precise_image and not is_text:
        return 2.0
    try:
        frame_window = int(cfg.get("frame_neighbor_rerank_window", DEFAULT_CONFIG["frame_neighbor_rerank_window"]))
    except (TypeError, ValueError):
        frame_window = int(DEFAULT_CONFIG["frame_neighbor_rerank_window"])
    try:
        fps = float(cfg.get("fps", DEFAULT_CONFIG["fps"]) or DEFAULT_CONFIG["fps"])
    except (TypeError, ValueError):
        fps = float(DEFAULT_CONFIG["fps"])
    return max(1.0, float(frame_window) / max(fps, 0.1))


def _same_scope_video_path(left, right) -> bool:
    return str(left or "") == str(right or "")


def _collect_neighbor_frame_ids(base_id: int, timestamps, video_paths, window_sec: float) -> List[int]:
    total = len(video_paths)
    if base_id < 0 or base_id >= total:
        return []

    base_path = video_paths[base_id]
    base_ts = float(timestamps[base_id])
    window = max(0.0, float(window_sec))
    neighbor_ids = [base_id]

    cursor = base_id - 1
    while cursor >= 0 and _same_scope_video_path(video_paths[cursor], base_path):
        ts = float(timestamps[cursor])
        if base_ts - ts > window:
            break
        neighbor_ids.append(cursor)
        cursor -= 1

    cursor = base_id + 1
    while cursor < total and _same_scope_video_path(video_paths[cursor], base_path):
        ts = float(timestamps[cursor])
        if ts - base_ts > window:
            break
        neighbor_ids.append(cursor)
        cursor += 1

    return neighbor_ids


def _reconstruct_index_vector(search_index, candidate_id: int, cache: dict[int, np.ndarray]) -> np.ndarray | None:
    key = int(candidate_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        vector = np.asarray(search_index.reconstruct(key), dtype=np.float32).reshape(-1)
    except Exception:
        return None
    cache[key] = vector
    return vector


def _resolve_candidate_vector(
    search_index,
    candidate_id: int,
    cache: dict[int, np.ndarray],
    *,
    vector_matrix: np.ndarray | None = None,
) -> np.ndarray | None:
    from src.app.logging_utils import get_logger

    logger = get_logger("search_neighbor_rerank")
    key = int(candidate_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if vector_matrix is not None:
        try:
            if 0 <= key < int(vector_matrix.shape[0]):
                vector = np.asarray(vector_matrix[key], dtype=np.float32).reshape(-1)
                cache[key] = vector
                return vector
        except Exception as exc:
            logger.debug("Vector matrix lookup failed for key %s: %s", key, exc)
    return _reconstruct_index_vector(search_index, key, cache)


def _neighbor_candidate_score(
    query: np.ndarray,
    search_index,
    candidate_id: int,
    vector_cache: dict[int, np.ndarray],
    score_cache: dict[int, float],
    *,
    vector_matrix: np.ndarray | None = None,
) -> float | None:
    key = int(candidate_id)
    if key in score_cache:
        return score_cache[key]
    candidate_vector = _resolve_candidate_vector(
        search_index,
        key,
        vector_cache,
        vector_matrix=vector_matrix,
    )
    if candidate_vector is None:
        return None
    score = float(np.dot(query, candidate_vector))
    score_cache[key] = score
    return score


def _apply_bounded_neighbor_refine(
    results,
    frame_ids,
    query_vector,
    search_index,
    timestamps,
    video_paths,
    *,
    max_top_n: int | None = None,
    max_shift_sec: float = _PRECISE_SEED_MAX_SHIFT_SEC,
    window_sec: float = _PRECISE_NEIGHBOR_WINDOW_SEC,
    neighbor_blend: float = _PRECISE_NEIGHBOR_BLEND,
):
    if not results or not frame_ids:
        return list(results or [])
    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return list(results or [])

    configured_top_n = int(get_frame_neighbor_rerank_top_n({}) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    max_index = min(len(results), len(frame_ids), int(max_top_n or configured_top_n))
    if max_index <= 0:
        return list(results or [])

    reranked = list(results)
    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    blend = max(0.0, min(float(neighbor_blend), 1.0))
    for rank in range(max_index):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue
        hit = reranked[rank]
        seed_time = float(hit.start_sec)
        base_score = float(hit.score)
        best_timestamp = seed_time
        best_neighbor_score = base_score
        base_path = video_paths[base_id]
        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            candidate_ts = float(timestamps[candidate_id])
            if abs(candidate_ts - seed_time) > max_shift_sec:
                continue
            score = _neighbor_candidate_score(
                query,
                search_index,
                int(candidate_id),
                vector_cache,
                score_cache,
            )
            if score is None:
                continue
            if score > best_neighbor_score:
                best_neighbor_score = float(score)
                best_timestamp = candidate_ts
        if best_neighbor_score > base_score:
            adjusted_time = _clamp_time_near_seed(best_timestamp, seed_time, max_shift_sec)
            blended_score = ((1.0 - blend) * base_score) + (blend * best_neighbor_score)
            reranked[rank] = SearchHit(adjusted_time, adjusted_time, blended_score, str(hit.video_path))
    return reranked


def _apply_frame_neighbor_rerank(
    results,
    frame_ids,
    query_vector,
    search_index,
    timestamps,
    video_paths,
    config,
    is_text: bool = False,
    precise_image: bool = False,
):
    from src.app.logging_utils import get_logger

    logger = get_logger("search_neighbor_rerank")
    if not results or not frame_ids:
        return results
    if not _neighbor_rerank_enabled(config, is_text=is_text, precise_image=precise_image):
        return results

    max_top_n = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    window_sec = _neighbor_rerank_window_sec(config, is_text=is_text, precise_image=precise_image)
    if max_top_n <= 0 or window_sec <= 0:
        return results

    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return results

    reranked = list(results)
    max_index = min(len(results), len(frame_ids), max_top_n)
    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    for rank in range(max_index):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue

        base_path = video_paths[base_id]
        hit = reranked[rank]
        best_score = float(hit.score)
        best_timestamp = float(hit.start_sec)

        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            score = _neighbor_candidate_score(
                query,
                search_index,
                int(candidate_id),
                vector_cache,
                score_cache,
            )
            if score is None:
                logger.debug(
                    "Neighbor rerank reconstruct failed for id=%s",
                    candidate_id,
                )
                continue
            if score > best_score:
                best_score = score
                best_timestamp = float(timestamps[candidate_id])

        reranked[rank] = SearchHit(best_timestamp, best_timestamp, best_score, str(base_path))
    return reranked


def _expand_neighbor_rerank_candidates(
    results,
    frame_ids,
    query_vector,
    search_index,
    timestamps,
    video_paths,
    config,
    is_text: bool = False,
    precise_image: bool = False,
    *,
    seed_top_n: int | None = None,
) -> List[SearchHit]:
    """Score every neighbor frame around each FAISS seed (not only the best one)."""
    from src.app.logging_utils import get_logger

    logger = get_logger("search_neighbor_rerank")
    if not results or not frame_ids:
        return list(results or [])
    if not _neighbor_rerank_enabled(config, is_text=is_text, precise_image=precise_image):
        return list(results or [])

    configured_top_n = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    max_top_n = int(seed_top_n) if seed_top_n is not None else configured_top_n
    max_top_n = max(1, min(max_top_n, len(results), len(frame_ids)))
    window_sec = _neighbor_rerank_window_sec(config, is_text=is_text, precise_image=precise_image)
    if window_sec <= 0:
        return list(results or [])

    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return list(results or [])

    candidates: dict[tuple[str, int], SearchHit] = {}
    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    for rank in range(max_top_n):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue
        base_path = str(video_paths[base_id])
        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            score = _neighbor_candidate_score(
                query,
                search_index,
                int(candidate_id),
                vector_cache,
                score_cache,
            )
            if score is None:
                logger.debug(
                    "Neighbor candidate reconstruct failed for id=%s",
                    candidate_id,
                )
                continue
            ts = float(timestamps[candidate_id])
            key = (base_path, int(round(ts * 1000)))
            hit = SearchHit(ts, ts, score, base_path)
            if key not in candidates or score > float(candidates[key].score):
                candidates[key] = hit

    for hit in results:
        key = (str(hit.video_path), int(round(float(hit.start_sec) * 1000)))
        if key not in candidates or float(hit.score) > float(candidates[key].score):
            candidates[key] = hit

    return sorted(candidates.values(), key=lambda item: float(item.score), reverse=True)


def _resolve_neighbor_seed_top_n(
    config,
    fetch_k: int,
    top_k: int,
    *,
    precise_image: bool,
) -> int:
    """How many FAISS seeds get neighbor expansion (CLIP-only, must stay bounded)."""
    if not _neighbor_rerank_enabled(config, is_text=False, precise_image=precise_image):
        return max(1, min(int(fetch_k), int(top_k)))
    try:
        configured = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    except (TypeError, ValueError):
        configured = int(DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    target = max(configured, int(top_k) * 2, 12)
    return max(1, min(int(fetch_k), target, 32))
