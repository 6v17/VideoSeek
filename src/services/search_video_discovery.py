"""Video discovery presentation and stage-2 per-video frame recall."""

from __future__ import annotations

from typing import List, Sequence

from src.domain.search_hit import SearchHit
from src.services.search_assets import _load_per_video_frame_assets
from src.services.search_hit_utils import _merge_search_hits, _merge_search_index_steps, _resolve_scoped_video_targets
from src.services.search_neighbor_rerank import _apply_frame_neighbor_rerank
from src.services.search_scope import normalize_scope_path

from src.services.search_frame_query import _search_frame_results_with_ids

_GLOBAL_VIDEO_RECALL_LIMIT = 20
_GLOBAL_PER_VIDEO_SEED_CAP = 5
_GLOBAL_STAGE2_PER_VIDEO_K = 100


def _cap_hits_per_video(hits: List[SearchHit], cap: int) -> List[SearchHit]:
    if not hits or cap <= 0:
        return list(hits or [])
    buckets: dict[str, List[SearchHit]] = {}
    for hit in hits:
        path = str(hit.video_path or "")
        buckets.setdefault(path, []).append(hit)
    capped: List[SearchHit] = []
    for items in buckets.values():
        ordered = sorted(items, key=lambda item: float(item.score), reverse=True)
        capped.extend(ordered[: int(cap)])
    return sorted(capped, key=lambda item: float(item.score), reverse=True)


def _use_video_discovery_results(
    is_text: bool,
    precise_image: bool,
    scoped: bool = False,
    *,
    video_discovery_enabled: bool = False,
) -> bool:
    """Enable best-per-video presentation for fast image search (any scope)."""
    del scoped  # kept for call-site compatibility; discovery is no longer global-only
    if not video_discovery_enabled:
        return False
    return (not is_text) and (not precise_image)


def _resolve_video_discovery_enabled(config, explicit: bool | None) -> bool:
    if explicit is not None:
        return bool(explicit)
    from src.storage.config_store import get_search_video_discovery_enabled

    return get_search_video_discovery_enabled(config)


def _aggregate_hits_to_video_discovery(hits: List[SearchHit], top_k: int) -> List[SearchHit]:
    best: dict[str, SearchHit] = {}
    for hit in hits or []:
        path = str(hit.video_path or "").strip()
        if not path:
            continue
        current = best.get(path)
        if current is None or float(hit.score) > float(current.score):
            best[path] = hit
    ordered = sorted(best.values(), key=lambda item: float(item.score), reverse=True)
    limit = max(1, int(top_k))
    discovery: List[SearchHit] = []
    for hit in ordered[:limit]:
        preview_sec = float(hit.start_sec)
        if float(hit.end_sec) > float(hit.start_sec) + 0.5:
            preview_sec = (float(hit.start_sec) + float(hit.end_sec)) / 2.0
        discovery.append(
            SearchHit(
                preview_sec,
                preview_sec,
                float(hit.score),
                str(hit.video_path),
                match_kind="video",
            )
        )
    return discovery


def _apply_video_discovery_presentation(
    hits: List[SearchHit],
    top_k: int,
    *,
    enabled: bool,
) -> List[SearchHit]:
    if not enabled or not hits:
        return list(hits or [])
    diversified = _cap_hits_per_video(hits, _GLOBAL_PER_VIDEO_SEED_CAP)
    aggregated = _aggregate_hits_to_video_discovery(diversified, top_k)
    return aggregated or list(hits or [])


def _top_video_paths_from_hits(hits: List[SearchHit], limit: int) -> List[str]:
    best: dict[str, float] = {}
    for hit in hits or []:
        path = str(hit.video_path or "").strip()
        if not path:
            continue
        score = float(getattr(hit, "score", 0.0) or 0.0)
        prev = best.get(path)
        if prev is None or score > prev:
            best[path] = score
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    cap = max(1, int(limit))
    return [path for path, _ in ranked[:cap]]


def _locate_frames_in_recalled_videos(
    query_vector,
    stage1_hits: List[SearchHit],
    config,
    *,
    is_text=False,
    ensure_video_paths: Sequence[str] | None = None,
) -> List[SearchHit]:
    """Stage2: refine inside recalled videos without discarding stage1 seeds."""
    if is_text or not stage1_hits:
        return list(stage1_hits or [])
    diversified = _cap_hits_per_video(stage1_hits, _GLOBAL_PER_VIDEO_SEED_CAP)
    candidate_videos = _top_video_paths_from_hits(diversified, _GLOBAL_VIDEO_RECALL_LIMIT)
    if not candidate_videos:
        candidate_videos = _top_video_paths_from_hits(stage1_hits, _GLOBAL_VIDEO_RECALL_LIMIT)
    if ensure_video_paths:
        required = [
            abs_path
            for abs_path, _video_id in _resolve_scoped_video_targets(ensure_video_paths, config)
        ]
        merged: List[str] = []
        seen: set[str] = set()
        for path in list(required) + list(candidate_videos):
            key = str(path or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(key)
        candidate_videos = merged[: max(_GLOBAL_VIDEO_RECALL_LIMIT, len(required))]
    if not candidate_videos:
        return list(stage1_hits)
    stage1_by_video: dict[str, List[SearchHit]] = {}
    for hit in stage1_hits:
        key = normalize_scope_path(str(hit.video_path or ""))
        if not key:
            continue
        stage1_by_video.setdefault(key, []).append(hit)
    frame_hits: List[SearchHit] = []
    per_k = int(_GLOBAL_STAGE2_PER_VIDEO_K)
    processed_videos: set[str] = set()
    for abs_path, video_id in _resolve_scoped_video_targets(candidate_videos, config):
        path_key = normalize_scope_path(abs_path)
        processed_videos.add(path_key)
        stage1_video_hits = stage1_by_video.get(path_key, [])
        search_index, timestamps, video_paths, _vector_matrix = _load_per_video_frame_assets(
            video_id,
            abs_path,
            config,
        )
        if search_index is None:
            frame_hits.extend(stage1_video_hits)
            continue
        _merge_search_index_steps(video_paths, timestamps)
        matched_results, matched_ids = _search_frame_results_with_ids(
            query_vector,
            search_index,
            timestamps,
            video_paths,
            top_k=per_k,
        )
        matched_results = _apply_frame_neighbor_rerank(
            matched_results,
            matched_ids,
            query_vector,
            search_index,
            timestamps,
            video_paths,
            config,
            is_text=is_text,
            precise_image=True,
        )
        frame_hits.extend(_merge_search_hits(stage1_video_hits + matched_results, per_k))
    if not frame_hits:
        return list(stage1_hits)
    stage1_preserved = [
        hit
        for hit in stage1_hits
        if normalize_scope_path(str(hit.video_path or "")) not in processed_videos
    ]
    combined = frame_hits + stage1_preserved
    merge_limit = max(len(stage1_hits), per_k * len(candidate_videos))
    return _merge_search_hits(combined, merge_limit)
