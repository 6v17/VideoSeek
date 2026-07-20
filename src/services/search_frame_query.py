"""Low-level FAISS frame search helpers."""

from __future__ import annotations

from typing import List

import numpy as np

from src.domain.search_hit import SearchHit
from src.storage.lance_search_index import LanceTableSearchIndex

from src.services.search_neighbor_rerank import _neighbor_candidate_score

_ANCHOR_BRUTEFORCE_MAX_FRAMES = 48
_ANCHOR_BRUTEFORCE_PREFILTER_MULTIPLIER = 2


def _search_lance_frame_results_with_ids(index: LanceTableSearchIndex, query_vector, top_k):
    rows = index.search_rows(query_vector, top_k)
    matched_results: List[SearchHit] = []
    matched_ids: List[int] = []
    for row_index, row in enumerate(rows):
        timestamp = float(row.timestamp or 0.0)
        matched_results.append(
            SearchHit(
                timestamp,
                timestamp,
                float(row.score),
                str(row.video_path or ""),
                video_id=str(row.video_id or ""),
            )
        )
        matched_ids.append(int(row_index))
    return matched_results, matched_ids


def _search_lance_chunk_results(index: LanceTableSearchIndex, query_vector, top_k) -> List[SearchHit]:
    rows = index.search_rows(query_vector, top_k)
    matched_results: List[SearchHit] = []
    for row in rows:
        start_time = float(row.start or 0.0)
        end_time = float(row.end or start_time)
        matched_results.append(
            SearchHit(
                start_time,
                end_time,
                float(row.score),
                str(row.video_path or ""),
                video_id=str(row.video_id or ""),
            )
        )
    return matched_results


def _search_frame_results_with_ids(query_vector, index, timestamps, video_paths, top_k):
    if isinstance(index, LanceTableSearchIndex):
        return _search_lance_frame_results_with_ids(index, query_vector, top_k)

    actual_k = min(top_k, index.ntotal)
    if actual_k <= 0:
        return [], []
    if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
        raise RuntimeError("Invalid query vector. Please retry the search.")
    query_dim = int(query_vector.shape[1])
    index_dim = int(getattr(index, "d", 0))
    if index_dim > 0 and query_dim != index_dim:
        raise RuntimeError(
            f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
            "Current model uses a different embedding space. Please rebuild the index for the active model."
        )

    distances, indices = index.search(query_vector, actual_k)
    matched_results = []
    matched_ids = []
    for rank, index_value in enumerate(indices[0]):
        if index_value == -1 or index_value >= len(video_paths):
            continue
        timestamp = float(timestamps[index_value])
        video_path = str(video_paths[index_value] or "")
        matched_results.append(SearchHit(timestamp, timestamp, float(distances[0][rank]), video_path))
        matched_ids.append(int(index_value))
    return matched_results, matched_ids


def _search_chunk_results(query_vector, index, ranges, video_paths, top_k) -> List[SearchHit]:
    if isinstance(index, LanceTableSearchIndex):
        return _search_lance_chunk_results(index, query_vector, top_k)

    actual_k = min(top_k, index.ntotal)
    if actual_k <= 0:
        return []
    if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
        raise RuntimeError("Invalid query vector. Please retry the search.")
    query_dim = int(query_vector.shape[1])
    index_dim = int(getattr(index, "d", 0))
    if index_dim > 0 and query_dim != index_dim:
        raise RuntimeError(
            f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
            "Current model uses a different embedding space. Please rebuild the index for the active model."
        )

    distances, indices = index.search(query_vector, actual_k)
    matched_results = []
    for rank, index_value in enumerate(indices[0]):
        if index_value == -1 or index_value >= len(video_paths):
            continue
        time_range = ranges[index_value]
        start_time = float(time_range[0])
        end_time = float(time_range[1])
        matched_results.append(
            SearchHit(start_time, end_time, float(distances[0][rank]), video_paths[index_value])
        )
    return matched_results


def _search_frame_results_in_time_window(
    query_vector,
    index,
    timestamps,
    video_paths,
    *,
    center_sec: float,
    window_sec: float,
    top_k: int,
    preloaded_vectors=None,
):
    actual_k = min(max(1, int(top_k)), int(getattr(index, "ntotal", 0) or 0))
    if actual_k <= 0:
        return [], []
    if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
        return [], []
    query_dim = int(query_vector.shape[1])
    index_dim = int(getattr(index, "d", 0))
    if index_dim > 0 and query_dim != index_dim:
        raise RuntimeError(
            f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
            "Current model uses a different embedding space. Please rebuild the index for the active model."
        )

    center = max(0.0, float(center_sec))
    window = max(1.0, float(window_sec))
    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return [], []

    candidate_ids: List[int] = []
    total = min(len(video_paths), len(timestamps), int(getattr(index, "ntotal", 0) or 0))
    for idx in range(total):
        if abs(float(timestamps[idx]) - center) <= window:
            candidate_ids.append(idx)
    if not candidate_ids:
        return [], []
    if len(candidate_ids) > _ANCHOR_BRUTEFORCE_MAX_FRAMES:
        prefilter_limit = min(
            len(candidate_ids),
            _ANCHOR_BRUTEFORCE_MAX_FRAMES * _ANCHOR_BRUTEFORCE_PREFILTER_MULTIPLIER,
        )
        candidate_ids.sort(key=lambda idx: abs(float(timestamps[idx]) - center))
        candidate_ids = candidate_ids[:prefilter_limit]

    vector_matrix = None
    if preloaded_vectors is not None:
        try:
            matrix = np.asarray(preloaded_vectors, dtype=np.float32)
            if matrix.ndim == 2 and matrix.shape[0] >= total:
                vector_matrix = matrix
        except Exception:
            vector_matrix = None

    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    scored: List[tuple[float, int]] = []
    for idx in candidate_ids:
        score = _neighbor_candidate_score(
            query,
            index,
            int(idx),
            vector_cache,
            score_cache,
            vector_matrix=vector_matrix,
        )
        if score is None:
            continue
        scored.append((float(score), int(idx)))
    if not scored:
        return [], []

    scored.sort(key=lambda item: (-item[0], item[1]))
    if len(scored) > _ANCHOR_BRUTEFORCE_MAX_FRAMES:
        scored = scored[: _ANCHOR_BRUTEFORCE_MAX_FRAMES]
    matched_results: List[SearchHit] = []
    matched_ids: List[int] = []
    for score, idx in scored[:actual_k]:
        timestamp = float(timestamps[idx])
        matched_results.append(
            SearchHit(timestamp, timestamp, score, str(video_paths[idx]))
        )
        matched_ids.append(int(idx))
    return matched_results, matched_ids
