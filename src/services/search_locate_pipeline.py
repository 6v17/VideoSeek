"""In-video locate (anchor window / crop) frame search pipeline."""

from __future__ import annotations

from typing import List, Sequence

from src.domain.search_hit import SearchHit
from src.services.image_search_rerank import apply_image_pixel_rerank, is_likely_cropped_query_image
from src.services.search_assets import load_search_assets
from src.services.search_fetch_policy import (
    _precise_pixel_localize_top_n,
    _resolve_frame_fetch_top_k,
)
from src.services.search_frame_query import (
    _search_frame_results_in_time_window,
    _search_frame_results_with_ids,
)
from src.services.search_hit_utils import (
    _clamp_time_near_seed,
    _dedupe_nearby_hits,
    _merge_search_hits,
)
from src.services.search_locate import (
    _resolve_rerank_query,
    apply_locate_crop_anchor_stability,
    should_allow_pixel_refine,
)
from src.services.search_neighbor_rerank import _apply_bounded_neighbor_refine
from src.services.search_scope import normalize_scope_path

_LOCATE_ANCHOR_WINDOW_SEC = 30.0
_LOCATE_CROP_ANCHOR_WINDOW_SEC = 5.0
_LOCATE_PIXEL_MAX_SHIFT_SEC = 5.0
_LOCATE_PIXEL_LOCALIZE_TOP_N = 3
_LOCATE_RESULT_TOP_K = 3
_LOCATE_CROP_RESULT_TOP_K = 1
_LOCATE_CROP_STABILITY_POOL_K = 12
_PRECISE_SEED_MAX_SHIFT_SEC = 5.0


def _resolve_locate_result_top_k(top_k: int, *, crop_query: bool = False) -> int:
    if crop_query:
        return _LOCATE_CROP_RESULT_TOP_K
    try:
        requested = int(top_k)
    except (TypeError, ValueError):
        requested = _LOCATE_RESULT_TOP_K
    return max(1, min(requested, _LOCATE_RESULT_TOP_K))


def _locate_anchor_window_hits_from_index(
    query_vector,
    anchor_sec: float,
    locate_k: int,
    window_sec: float,
    *,
    search_index,
    timestamps,
    video_paths,
    preloaded_vectors=None,
    skip_neighbor_refine: bool = False,
) -> List[SearchHit]:
    matched_results, matched_ids = _search_frame_results_in_time_window(
        query_vector,
        search_index,
        timestamps,
        video_paths,
        center_sec=anchor_sec,
        window_sec=window_sec,
        top_k=locate_k,
        preloaded_vectors=preloaded_vectors,
    )
    if not matched_results:
        return []
    if skip_neighbor_refine:
        return _merge_search_hits(matched_results, locate_k)
    refined = _apply_bounded_neighbor_refine(
        matched_results,
        matched_ids,
        query_vector,
        search_index,
        timestamps,
        video_paths,
    )
    return _merge_search_hits(refined, locate_k)


def _search_locate_anchor_window_hits(
    query_vector,
    target_video_path: str,
    anchor_sec: float,
    top_k: int,
    config,
    *,
    per_video_index=None,
    per_video_timestamps=None,
    per_video_paths=None,
    per_video_vectors=None,
    window_sec: float | None = None,
    skip_neighbor_refine: bool = False,
) -> List[SearchHit]:
    """Locate stage1: per-video anchor window first; global index only as fallback."""
    locate_k = max(1, int(top_k))
    anchor = max(0.0, float(anchor_sec))
    window = max(1.0, float(window_sec if window_sec is not None else _LOCATE_ANCHOR_WINDOW_SEC))
    target_key = normalize_scope_path(str(target_video_path or ""))

    if per_video_index is not None:
        per_video_hits = _locate_anchor_window_hits_from_index(
            query_vector,
            anchor,
            locate_k,
            window,
            search_index=per_video_index,
            timestamps=per_video_timestamps,
            video_paths=per_video_paths,
            preloaded_vectors=per_video_vectors,
            skip_neighbor_refine=skip_neighbor_refine,
        )
        if per_video_hits:
            return per_video_hits

    global_index, global_ts, global_paths = load_search_assets(config)
    if global_index is not None and int(getattr(global_index, "ntotal", 0) or 0) > 0:
        fetch_k = _resolve_frame_fetch_top_k(locate_k, True, False, config, precise_image=True)
        global_hits, global_ids = _search_frame_results_with_ids(
            query_vector,
            global_index,
            global_ts,
            global_paths,
            top_k=fetch_k,
        )
        in_window: List[SearchHit] = []
        in_window_ids: List[int] = []
        for hit, frame_id in zip(global_hits, global_ids):
            if normalize_scope_path(str(hit.video_path or "")) != target_key:
                continue
            if abs(float(hit.start_sec) - anchor) > window:
                continue
            in_window.append(hit)
            in_window_ids.append(int(frame_id))
        if in_window:
            if skip_neighbor_refine:
                merged = _merge_search_hits(in_window, locate_k)
            else:
                refined = _apply_bounded_neighbor_refine(
                    in_window,
                    in_window_ids,
                    query_vector,
                    global_index,
                    global_ts,
                    global_paths,
                )
                merged = _merge_search_hits(refined, locate_k)
            if merged:
                return merged

    if window <= _LOCATE_PIXEL_MAX_SHIFT_SEC + 1e-6:
        return [SearchHit(anchor, anchor, 0.0, str(target_video_path))]
    return []


def _search_locate_crop_trusted_hits(
    query_vector,
    target_video_path: str,
    anchor_sec: float,
    config,
    *,
    per_video_index=None,
    per_video_timestamps=None,
    per_video_paths=None,
    per_video_vectors=None,
) -> List[SearchHit]:
    """Screenshot locate: trust fast-search anchor, only score frames within ±5s."""
    pool = _search_locate_anchor_window_hits(
        query_vector,
        target_video_path,
        anchor_sec,
        _LOCATE_CROP_STABILITY_POOL_K,
        config,
        per_video_index=per_video_index,
        per_video_timestamps=per_video_timestamps,
        per_video_paths=per_video_paths,
        per_video_vectors=per_video_vectors,
        window_sec=_LOCATE_CROP_ANCHOR_WINDOW_SEC,
        skip_neighbor_refine=True,
    )
    return apply_locate_crop_anchor_stability(pool, anchor_sec, target_video_path)


def _refine_precise_seed_hits(
    query_data,
    hits: List[SearchHit],
    top_k: int,
    config,
    *,
    seed_times: Sequence[float] | None = None,
    pixel_query_data=None,
    locate_anchor_sec: float | None = None,
    locate_anchor_score: float | None = None,
    locate_score_margin: float | None = None,
) -> List[SearchHit]:
    """Localize frozen recall seeds: pixel (and optional bounded neighbor upstream) only."""
    if not hits:
        return []
    prepared = _dedupe_nearby_hits(hits, bucket_sec=1.0)
    frozen = _merge_search_hits(prepared, top_k)
    if not frozen:
        return []
    rerank_query = _resolve_rerank_query(query_data, pixel_query_data)
    crop_query = is_likely_cropped_query_image(rerank_query)
    clip_seeds = [float(t) for t in (seed_times or [hit.start_sec for hit in frozen])]
    if len(clip_seeds) != len(frozen):
        clip_seeds = [float(hit.start_sec) for hit in frozen]

    if crop_query:
        limit = 1 if locate_anchor_sec is not None else max(1, int(top_k))
        return frozen[:limit]

    if locate_anchor_sec is not None:
        if not should_allow_pixel_refine(
            is_crop=False,
            score=locate_anchor_score,
            margin=locate_score_margin,
        ):
            return frozen[: max(1, int(top_k))]

        anchor = max(0.0, float(locate_anchor_sec))
        locate_limit = max(1, min(_LOCATE_PIXEL_LOCALIZE_TOP_N, len(frozen)))
        head = frozen[:locate_limit]
        clip_seeds = [
            _clamp_time_near_seed(float(hit.start_sec), anchor, _LOCATE_PIXEL_MAX_SHIFT_SEC)
            for hit in head
        ]
        pixel_head = apply_image_pixel_rerank(
            rerank_query,
            head,
            config=config,
            top_k=locate_limit,
            seed_times=clip_seeds,
            max_time_shift_sec=_LOCATE_PIXEL_MAX_SHIFT_SEC,
            preserve_order=True,
        ) if head else []
        output: List[SearchHit] = []
        for index, hit in enumerate(frozen):
            if index < len(pixel_head):
                output.append(pixel_head[index])
            else:
                output.append(hit)
        return output[: max(1, int(top_k))]

    localize_n = _precise_pixel_localize_top_n(config, frozen)
    head = frozen[:localize_n]
    pixel_head = apply_image_pixel_rerank(
        rerank_query,
        head,
        config=config,
        top_k=localize_n,
        seed_times=clip_seeds[:localize_n],
        max_time_shift_sec=_PRECISE_SEED_MAX_SHIFT_SEC,
        preserve_order=True,
    ) if head else []
    output: List[SearchHit] = []
    for index, hit in enumerate(frozen):
        if index < len(pixel_head):
            output.append(pixel_head[index])
        else:
            output.append(hit)
    return output[: max(1, int(top_k))]
