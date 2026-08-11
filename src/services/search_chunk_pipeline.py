"""Chunk search via frame recall and frame-to-chunk aggregation."""

from __future__ import annotations

import os
from typing import List

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.search_assets import (
    _FRAME_ASSET_INFO,
    _check_asset_profile_compatibility,
    _library_indexes_ready,
    _profile_base_dir,
    load_library_frame_search_assets,
    load_scoped_video_frame_search_assets,
    load_search_assets,
)
from src.services.search_fetch_policy import (
    _resolve_chunk_precise_frame_fetch_k,
    _resolve_frame_fetch_top_k,
    _resolve_stage1_global_fetch_k,
)
from src.services.search_frame_query import _search_frame_results_with_ids
from src.services.search_hit_utils import (
    _merge_search_index_steps,
    _merge_search_hits,
    _resolve_scoped_video_targets,
)
from src.services.search_locate_pipeline import _refine_precise_seed_hits
from src.services.search_neighbor_rerank import (
    _expand_neighbor_rerank_candidates,
    _resolve_neighbor_seed_top_n,
)
from src.services.search_profiling import profile_phase
from src.services.search_scope import apply_search_scope, is_search_scoped, normalize_scope_path
from src.storage.config_store import get_search_top_k
from src.storage.lance_search_index import load_lance_chunk_time_ranges, load_lance_video_chunks

logger = get_logger("search_chunk_pipeline")


def _prepare_frame_candidates_for_chunk_aggregate(hits: List[SearchHit]) -> List[SearchHit]:
    if not hits:
        return []
    return sorted(hits, key=lambda item: float(item.score), reverse=True)



def _collect_frame_candidates_for_chunk_search(
    query_data,
    *,
    is_text=False,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
    search_precision_mode=None,
    pixel_query_data=None,
    precise_image=False,
    config=None,
) -> List[SearchHit]:
    config = config or load_config()
    if top_k is None:
        top_k = get_search_top_k(config)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    from src.services.search_service import _coalesce_query_vector

    query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)
    if precise_image:
        fetch_k = (
            _resolve_stage1_global_fetch_k(top_k, config)
            if not scoped
            else _resolve_frame_fetch_top_k(top_k, scoped, is_text=False, config=config, precise_image=True)
        )
    else:
        if is_text:
            from src.services.search_fetch_policy import resolve_source_filtered_fetch_top_k

            fetch_k = resolve_source_filtered_fetch_top_k(top_k, scoped)
        else:
            fetch_k = _resolve_chunk_precise_frame_fetch_k(top_k, scoped)
    neighbor_seed_n = _resolve_neighbor_seed_top_n(config, fetch_k, top_k, precise_image=precise_image)
    candidates: List[SearchHit] = []

    if scoped and scope_video_paths:
        targets = _resolve_scoped_video_targets(scope_video_paths, config)
        if not targets:
            return []
        video_ids = [video_id for _path, video_id in targets]
        scope_paths = [path for path, _video_id in targets]
        search_index, timestamps, video_paths = load_scoped_video_frame_search_assets(video_ids, config)
        if search_index is None:
            return []
        _merge_search_index_steps(video_paths, timestamps)
        matched_results, matched_ids = _search_frame_results_with_ids(
            query_vector,
            search_index,
            timestamps,
            video_paths,
            top_k=fetch_k,
        )
        candidates = _expand_neighbor_rerank_candidates(
            matched_results,
            matched_ids,
            query_vector,
            search_index,
            timestamps,
            video_paths,
            config,
            is_text=is_text,
            precise_image=precise_image,
            seed_top_n=neighbor_seed_n,
        )
        candidates = apply_search_scope(
            candidates,
            video_paths=scope_paths,
            top_k=None,
        )
    elif (
        scoped
        and scope_library_paths
        and not scope_video_paths
        and _library_indexes_ready(config, scope_library_paths)
    ):
        library_fetch_k = fetch_k
        library_seed_n = neighbor_seed_n
        for library_path in scope_library_paths:
            search_index, timestamps, video_paths = load_library_frame_search_assets(library_path, config)
            if search_index is None:
                continue
            _merge_search_index_steps(video_paths, timestamps)
            matched_results, matched_ids = _search_frame_results_with_ids(
                query_vector,
                search_index,
                timestamps,
                video_paths,
                top_k=library_fetch_k,
            )
            candidates.extend(
                _expand_neighbor_rerank_candidates(
                    matched_results,
                    matched_ids,
                    query_vector,
                    search_index,
                    timestamps,
                    video_paths,
                    config,
                    is_text=is_text,
                    precise_image=precise_image,
                    seed_top_n=library_seed_n,
                )
            )
    else:
        global_fetch_k = fetch_k
        search_index, timestamps, video_paths = load_search_assets(config)
        if search_index is None:
            return []
        _merge_search_index_steps(video_paths, timestamps)
        _check_asset_profile_compatibility(config, _FRAME_ASSET_INFO, asset_label="frame")
        matched_results, matched_ids = _search_frame_results_with_ids(
            query_vector,
            search_index,
            timestamps,
            video_paths,
            top_k=global_fetch_k,
        )
        candidates = _expand_neighbor_rerank_candidates(
            matched_results,
            matched_ids,
            query_vector,
            search_index,
            timestamps,
            video_paths,
            config,
            is_text=is_text,
            precise_image=precise_image,
            seed_top_n=neighbor_seed_n,
        )
        candidates = apply_search_scope(
            candidates,
            video_paths=scope_video_paths,
            library_paths=scope_library_paths,
            top_k=None,
        )

    return _prepare_frame_candidates_for_chunk_aggregate(candidates)


def _resolve_video_id_for_path(video_path: str, config) -> str | None:
    from src.services.search_scope import build_indexed_video_lookup

    from src.storage.asset_store import load_model_metadata

    lookup = build_indexed_video_lookup(load_model_metadata(config=config))
    normalized = normalize_scope_path(video_path)
    video_id = lookup.get(normalized)
    if video_id:
        return video_id
    normalized_case = os.path.normcase(normalized)
    for path, candidate_id in lookup.items():
        if os.path.normcase(str(path)) == normalized_case:
            return candidate_id
    return None


def _chunk_hit_from_range(frame_hit: SearchHit, chunk_start: float, chunk_end: float) -> SearchHit:
    start = float(chunk_start)
    end = float(chunk_end)
    if end <= start:
        end = start + 0.1
    return SearchHit(start, end, float(frame_hit.score), str(frame_hit.video_path))


def _load_global_chunk_ranges_by_path(config) -> dict[str, list[tuple[float, float]]]:
    """Map normalized video_path -> chunk time ranges from Lance (no embedding dump)."""
    profile_base_dir = _profile_base_dir(config)
    raw = load_lance_chunk_time_ranges(profile_base_dir)
    if not raw:
        return {}
    by_path: dict[str, list[tuple[float, float]]] = {}
    for path, ranges in raw.items():
        key = normalize_scope_path(str(path))
        if not key:
            continue
        by_path.setdefault(key, []).extend((float(start), float(end)) for start, end in ranges)
    return by_path


def _lookup_path_in_index(path_index: dict[str, list[tuple[float, float]]], video_path: str):
    normalized = normalize_scope_path(video_path)
    values = path_index.get(normalized)
    if values:
        return values
    normalized_case = os.path.normcase(normalized)
    for path, items in path_index.items():
        if os.path.normcase(path) == normalized_case:
            return items
    return None


def _find_range_for_timestamp(ranges, timestamp: float):
    ts = float(timestamp)
    tolerance = 0.25
    for index, (start, end) in enumerate(ranges or []):
        if (start - tolerance) <= ts <= (end + tolerance):
            return index, start, end
    return None, None, None


def _chunk_ranges_for_video(
    video_path: str,
    config,
    *,
    range_index: dict[str, list[tuple[float, float]]] | None = None,
) -> list[tuple[float, float]]:
    range_index = range_index if range_index is not None else _load_global_chunk_ranges_by_path(config)
    indexed = _lookup_path_in_index(range_index, video_path)
    if indexed:
        return indexed
    video_id = _resolve_video_id_for_path(video_path, config)
    if not video_id:
        return []
    # Prefer chunk table only; avoid load_video_chunks_by_id frame materialize.
    chunks = load_lance_video_chunks(_profile_base_dir(config), video_id)
    return [(float(chunk["start"]), float(chunk["end"])) for chunk in chunks]


def _aggregate_frame_hits_to_chunks(hits: List[SearchHit], top_k: int, config) -> List[SearchHit]:
    if not hits:
        return []
    range_index = _load_global_chunk_ranges_by_path(config)
    range_cache: dict[str, list[tuple[float, float]]] = {}
    seen: set[tuple[str, int]] = set()
    aggregated: List[SearchHit] = []
    limit = max(1, int(top_k))
    ordered_hits = sorted(hits, key=lambda item: float(item.score), reverse=True)

    for hit in ordered_hits:
        video_path = str(hit.video_path or "")
        path_key = normalize_scope_path(video_path)
        if path_key not in range_cache:
            range_cache[path_key] = _chunk_ranges_for_video(
                video_path,
                config,
                range_index=range_index,
            )
        chunk_idx, chunk_start, chunk_end = _find_range_for_timestamp(range_cache[path_key], hit.start_sec)
        if chunk_idx is None:
            logger.debug(
                "Chunk aggregate skipped hit outside indexed ranges: %s @ %.3fs",
                video_path,
                float(hit.start_sec),
            )
            continue
        dedupe_key = (path_key, int(chunk_idx))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        aggregated.append(_chunk_hit_from_range(hit, chunk_start, chunk_end))
        if len(aggregated) >= limit:
            break
    return aggregated


def _finalize_frame_hits(
    query_data,
    is_text: bool,
    hits: List[SearchHit],
    top_k: int,
    config,
    precise_image: bool = False,
    pixel_query_data=None,
    seed_times=None,
) -> List[SearchHit]:
    if is_text or not precise_image:
        return _merge_search_hits(hits, top_k)
    return _refine_precise_seed_hits(
        query_data,
        hits,
        top_k,
        config,
        seed_times=seed_times,
        pixel_query_data=pixel_query_data,
    )


def _run_chunk_search_via_frames(
    query_data,
    *,
    is_text=False,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
    search_precision_mode=None,
    pixel_query_data=None,
    precise_image=False,
    config=None,
) -> List[SearchHit]:
    config = config or load_config()
    if top_k is None:
        top_k = get_search_top_k(config)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    if precise_image:
        frame_fetch_k = _resolve_frame_fetch_top_k(top_k, scoped, is_text=False, config=config, precise_image=True)
    else:
        frame_fetch_k = _resolve_chunk_precise_frame_fetch_k(top_k, scoped)
    logger.info(
        "Chunk image search via frames (precise=%s, frame_fetch_k=%s)",
        precise_image,
        frame_fetch_k,
    )
    frame_hits = _collect_frame_candidates_for_chunk_search(
        query_data,
        is_text=is_text,
        top_k=top_k,
        scope_video_paths=scope_video_paths,
        scope_library_paths=scope_library_paths,
        query_vector=query_vector,
        search_precision_mode=search_precision_mode if precise_image else "fast",
        pixel_query_data=pixel_query_data,
        precise_image=precise_image,
        config=config,
    )
    if precise_image:
        return _finalize_frame_hits(
            query_data,
            is_text,
            frame_hits,
            top_k,
            config,
            precise_image=True,
            pixel_query_data=pixel_query_data,
        )
    with profile_phase("chunk_aggregate"):
        aggregated = _aggregate_frame_hits_to_chunks(frame_hits, top_k, config)
    if aggregated:
        return _finalize_frame_hits(
            query_data,
            is_text,
            aggregated,
            top_k,
            config,
            precise_image=precise_image,
            pixel_query_data=pixel_query_data,
        )
    if frame_hits:
        logger.warning(
            "Chunk aggregate mapped 0 segments from %s frame hits; returning frame results",
            len(frame_hits),
        )
        return _merge_search_hits(frame_hits, top_k)
    return []


def _run_chunk_search_via_precise_frames(
    query_data,
    *,
    is_text=False,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
    search_precision_mode=None,
    pixel_query_data=None,
    config=None,
) -> List[SearchHit]:
    return _run_chunk_search_via_frames(
        query_data,
        is_text=is_text,
        top_k=top_k,
        scope_video_paths=scope_video_paths,
        scope_library_paths=scope_library_paths,
        query_vector=query_vector,
        search_precision_mode=search_precision_mode,
        pixel_query_data=pixel_query_data,
        precise_image=True,
        config=config,
    )
