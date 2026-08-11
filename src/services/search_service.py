"""Local frame/chunk semantic search orchestration."""

from __future__ import annotations

import os
from typing import List

import faiss
import numpy as np

from src.core.clip_embedding import get_clip_embeddings_batch, get_engine, get_text_embedding
from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.search_scope import (
    apply_search_scope,
    is_search_scoped,
    resolve_fetch_top_k,
    resolve_scope_video_ids,
    resolve_subtitle_scope_video_ids,
)
from src.services.image_search_rerank import apply_image_pixel_rerank, is_likely_cropped_query_image
from src.services.search_profiling import (
    build_profile_meta_from_config,
    is_profiling_enabled,
    profile_phase,
    record_search_profile_result_count,
    search_profile_session,
)
from src.services.search_progress import (
    clear_search_progress_callback,
    emit_search_progress,
    set_search_progress_callback,
)
from src.services.search_assets import (
    _CHUNK_ASSET_INFO,
    _FRAME_ASSET_INFO,
    _check_asset_profile_compatibility,
    _library_indexes_ready,
    _load_per_video_frame_assets,
    load_chunk_search_assets,
    load_library_chunk_search_assets,
    load_library_frame_search_assets,
    load_scoped_video_chunk_search_assets,
    load_scoped_video_frame_search_assets,
    load_search_assets,
)
from src.services.search_locate import (
    _LOCATE_CROP_MIN_CLIP_SCORE,
    _resolve_rerank_query,
    apply_locate_crop_anchor_stability as _apply_locate_crop_anchor_stability,
    compute_locate_confidence,
    compute_locate_score_margin,
    format_clip_score_percent,
    locate_crop_confidence_warning_key,
    resolve_clip_confidence_label,
    resolve_clip_confidence_tier_key,
    resolve_locate_clip_window_sec,
    should_allow_pixel_refine,
)
from src.services.search_chunk_pipeline import (
    _aggregate_frame_hits_to_chunks,
    _collect_frame_candidates_for_chunk_search,
    _finalize_frame_hits,
    _load_global_chunk_ranges_by_path,
    _prepare_frame_candidates_for_chunk_aggregate,
    _run_chunk_search_via_frames,
    _run_chunk_search_via_precise_frames,
)
from src.services.search_fetch_policy import (
    _precise_pixel_localize_top_n,
    _resolve_frame_fetch_top_k,
    _resolve_stage1_global_fetch_k,
)
from src.services.search_frame_query import (
    _search_chunk_results,
    _search_frame_results_in_time_window,
    _search_frame_results_with_ids,
)
from src.services.search_hit_utils import (
    _merge_search_hits,
    _merge_search_index_steps,
    _reset_search_index_steps,
    _resolve_scoped_video_targets,
    _scope_filter_hits_with_seeds,
    _use_precise_image_pipeline,
)
from src.services.search_locate_pipeline import (
    _refine_precise_seed_hits,
    _resolve_locate_result_top_k,
    _search_locate_anchor_window_hits,
    _search_locate_crop_trusted_hits,
)
from src.services.search_neighbor_rerank import (
    _apply_bounded_neighbor_refine,
    _apply_frame_neighbor_rerank,
    _collect_neighbor_frame_ids,
    _expand_neighbor_rerank_candidates,
    _neighbor_candidate_score,
    _neighbor_rerank_enabled,
)
from src.services.search_query import filter_hits_by_min_score
from src.services.search_video_discovery import (
    _aggregate_hits_to_video_discovery,
    _apply_video_discovery_presentation,
    _cap_hits_per_video,
    _locate_frames_in_recalled_videos,
    _resolve_video_discovery_enabled,
    _top_video_paths_from_hits,
    _use_video_discovery_results,
)
from src.storage.config_store import get_active_model_profile, get_global_model_asset_paths, get_search_mode, get_search_top_k

logger = get_logger("search_service")


def build_query_vector(query_data, is_text=False):
    if is_text:
        query_vector = get_text_embedding(query_data)
    elif isinstance(query_data, str):
        from src.core.image_io import load_image_bgr

        image = load_image_bgr(query_data)
        if image is None:
            raise RuntimeError(
                "Could not load query image. Use JPG/PNG/WEBP, or install pillow-heif for iPhone HEIC photos."
            )
        query_vector = get_clip_embeddings_batch([image])
    else:
        query_vector = get_clip_embeddings_batch([query_data])

    query_vector = query_vector.astype("float32")
    faiss.normalize_L2(query_vector)
    return query_vector


def _coalesce_query_vector(query_data, is_text=False, query_vector=None):
    if query_vector is not None:
        vector = np.asarray(query_vector, dtype=np.float32)
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        elif vector.ndim != 2 or vector.shape[0] != 1:
            raise RuntimeError("Invalid query vector. Please retry the search.")
        faiss.normalize_L2(vector)
        return vector
    return build_query_vector(query_data, is_text=is_text)


def _run_frame_search_per_videos(
    query_vector,
    scope_video_paths,
    top_k,
    config,
    query_data=None,
    is_text=False,
    precise_image=False,
    pixel_query_data=None,
    preview_anchor_sec: float | None = None,
    locate_anchor_score: float | None = None,
    locate_score_margin: float | None = None,
    use_video_discovery: bool = False,
) -> List[SearchHit]:
    targets = _resolve_scoped_video_targets(scope_video_paths, config)
    if not targets:
        return []

    # Locate needs per-video vectors / windows; keep the materialize loop there only.
    if preview_anchor_sec is not None:
        return _run_frame_locate_per_videos(
            query_vector,
            targets,
            top_k,
            config,
            query_data=query_data,
            pixel_query_data=pixel_query_data,
            preview_anchor_sec=preview_anchor_sec,
            locate_anchor_score=locate_anchor_score,
            locate_score_margin=locate_score_margin,
        )

    video_ids = [video_id for _path, video_id in targets]
    scope_paths = [path for path, _video_id in targets]
    fetch_k = _resolve_frame_fetch_top_k(
        top_k,
        True,
        is_text,
        config,
        precise_image=precise_image,
    )
    if use_video_discovery and not precise_image:
        fetch_k = max(int(fetch_k), int(resolve_fetch_top_k(top_k, True)))
    with profile_phase("load_assets"):
        search_index, timestamps, video_paths = load_scoped_video_frame_search_assets(video_ids, config)
    _merge_search_index_steps(video_paths, timestamps)
    if search_index is None:
        return []

    with profile_phase("faiss_search"):
        matched_results, matched_ids = _search_frame_results_with_ids(
            query_vector,
            search_index,
            timestamps,
            video_paths,
            top_k=int(fetch_k),
        )
    clip_seeds = [float(hit.start_sec) for hit in matched_results]
    if precise_image:
        with profile_phase("bounded_neighbor"):
            matched_results = _apply_bounded_neighbor_refine(
                matched_results,
                matched_ids,
                query_vector,
                search_index,
                timestamps,
                video_paths,
            )
        with profile_phase("pixel_rerank"):
            refined = _refine_precise_seed_hits(
                query_data,
                matched_results,
                top_k,
                config,
                seed_times=clip_seeds,
                pixel_query_data=pixel_query_data,
            )
        from src.services.search_scope import filter_hits_by_video_paths

        refined = filter_hits_by_video_paths(refined, scope_paths)
        return _merge_search_hits(refined, top_k)

    with profile_phase("neighbor_rerank"):
        matched_results = _apply_frame_neighbor_rerank(
            matched_results,
            matched_ids,
            query_vector,
            search_index,
            timestamps,
            video_paths,
            config,
            is_text=is_text,
            precise_image=False,
        )
    with profile_phase("scope_filter"):
        # Keep expanded pool until after video-discovery aggregation.
        scope_keep_k = fetch_k if use_video_discovery else top_k
        scoped_hits = apply_search_scope(
            matched_results,
            video_paths=scope_paths,
            top_k=scope_keep_k,
        )
    merge_keep_k = fetch_k if use_video_discovery else top_k
    results = _finalize_frame_hits(
        query_data,
        is_text,
        scoped_hits,
        merge_keep_k,
        config,
        precise_image=False,
        pixel_query_data=pixel_query_data,
    )
    return _apply_video_discovery_presentation(
        results,
        top_k,
        enabled=use_video_discovery,
    )


def _run_frame_locate_per_videos(
    query_vector,
    targets,
    top_k,
    config,
    query_data=None,
    pixel_query_data=None,
    preview_anchor_sec: float | None = None,
    locate_anchor_score: float | None = None,
    locate_score_margin: float | None = None,
) -> List[SearchHit]:
    rerank_query = _resolve_rerank_query(query_data, pixel_query_data)
    crop_query = is_likely_cropped_query_image(rerank_query)
    merged_hits: List[SearchHit] = []
    for abs_path, video_id in targets:
        with profile_phase("load_assets"):
            search_index, timestamps, video_paths, vector_matrix = _load_per_video_frame_assets(
                video_id,
                abs_path,
                config,
                include_vectors=True,
            )
        _merge_search_index_steps(video_paths, timestamps)
        if search_index is None:
            continue
        try:
            anchor_sec = float(preview_anchor_sec)
        except (TypeError, ValueError):
            continue
        emit_search_progress("locate_progress_load")
        with profile_phase("faiss_search"):
            locate_top_k = _resolve_locate_result_top_k(top_k, crop_query=crop_query)
            progress_key = (
                "locate_progress_crop_clip"
                if crop_query
                else "locate_progress_clip"
            )
            emit_search_progress(progress_key)
            if crop_query:
                matched_results = _search_locate_crop_trusted_hits(
                    query_vector,
                    abs_path,
                    anchor_sec,
                    config,
                    per_video_index=search_index,
                    per_video_timestamps=timestamps,
                    per_video_paths=video_paths,
                    per_video_vectors=vector_matrix,
                )
            else:
                clip_window_sec = resolve_locate_clip_window_sec(
                    score=locate_anchor_score,
                    margin=locate_score_margin,
                    is_crop=False,
                    config=config,
                )
                matched_results = _search_locate_anchor_window_hits(
                    query_vector,
                    abs_path,
                    anchor_sec,
                    locate_top_k,
                    config,
                    per_video_index=search_index,
                    per_video_timestamps=timestamps,
                    per_video_paths=video_paths,
                    per_video_vectors=vector_matrix,
                    window_sec=clip_window_sec,
                )
                if matched_results:
                    try:
                        from src.services.locate_telemetry_utils import classify_video_pace
                        from src.services.search_telemetry import record_locate_clip_window

                        record_locate_clip_window(
                            window_sec=clip_window_sec,
                            score=locate_anchor_score,
                            margin=locate_score_margin,
                            anchor_sec=anchor_sec,
                            result_sec=float(matched_results[0].start_sec),
                            is_crop=False,
                            confidence=compute_locate_confidence(
                                locate_anchor_score,
                                locate_score_margin,
                            ),
                            video_pace=classify_video_pace(timestamps, anchor_sec),
                        )
                    except Exception as exc:
                        logger.debug("Locate telemetry record skipped: %s", exc)
        locate_top_k = _resolve_locate_result_top_k(top_k, crop_query=crop_query)
        if not crop_query and should_allow_pixel_refine(
            is_crop=False,
            score=locate_anchor_score,
            margin=locate_score_margin,
        ):
            emit_search_progress("locate_progress_pixel")
        merged_hits.extend(
            _refine_precise_seed_hits(
                query_data,
                matched_results,
                locate_top_k,
                config,
                pixel_query_data=pixel_query_data,
                locate_anchor_sec=anchor_sec,
                locate_anchor_score=locate_anchor_score,
                locate_score_margin=locate_score_margin,
            )
        )
    crop_final = is_likely_cropped_query_image(rerank_query)
    return _merge_search_hits(
        merged_hits,
        _resolve_locate_result_top_k(top_k, crop_query=crop_final),
    )


def _run_chunk_search_per_videos(query_vector, scope_video_paths, top_k, config) -> List[SearchHit]:
    targets = _resolve_scoped_video_targets(scope_video_paths, config)
    if not targets:
        return []
    video_ids = [video_id for _path, video_id in targets]
    with profile_phase("load_assets"):
        search_index, ranges, video_paths = load_scoped_video_chunk_search_assets(video_ids, config)
    if search_index is None:
        return []
    with profile_phase("faiss_search"):
        hits = _search_chunk_results(
            query_vector,
            search_index,
            ranges,
            video_paths,
            top_k=top_k,
        )
    return _merge_search_hits(hits, top_k)


def run_search(
    query_data,
    is_text=False,
    top_k=None,
    search_mode=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
    search_precision_mode=None,
    pixel_query_data=None,
    preview_anchor_sec: float | None = None,
    locate_anchor_score: float | None = None,
    locate_score_margin: float | None = None,
    profile: bool | None = None,
    progress_callback=None,
    video_discovery_enabled: bool | None = None,
) -> List[SearchHit]:
    config = load_config()
    precise_image = _use_precise_image_pipeline(is_text, config, search_precision_mode)
    # Image queries default to frame search (matches search UI hint); callers can
    # pass search_mode="chunk" explicitly when segment aggregation is intended.
    if not is_text and search_mode is None:
        mode = "frame"
    else:
        mode = str(search_mode or get_search_mode(config)).strip().lower()
        if mode not in {"frame", "chunk"}:
            mode = get_search_mode(config)
    profile_enabled = profile if profile is not None else is_profiling_enabled(config)
    profile_meta = build_profile_meta_from_config(
        config,
        precise_image=precise_image,
        search_precision_mode=search_precision_mode,
    )
    logger.info("Running %s search (is_text=%s, precise_image=%s)", mode, is_text, precise_image)
    _reset_search_index_steps()
    set_search_progress_callback(progress_callback)
    try:
        results = _run_search_impl(
            query_data=query_data,
            is_text=is_text,
            top_k=top_k,
            scope_video_paths=scope_video_paths,
            scope_library_paths=scope_library_paths,
            query_vector=query_vector,
            precise_image=precise_image,
            mode=mode,
            config=config,
            profile_enabled=profile_enabled,
            profile_meta=profile_meta,
            search_precision_mode=search_precision_mode,
            pixel_query_data=pixel_query_data,
            preview_anchor_sec=preview_anchor_sec,
            locate_anchor_score=locate_anchor_score,
            locate_score_margin=locate_score_margin,
            video_discovery_enabled=video_discovery_enabled,
        )
        from src.services.search_scope import filter_hits_with_existing_sources, load_searchable_path_index

        path_index = load_searchable_path_index(config=config)
        return filter_hits_with_existing_sources(results, path_index=path_index, config=config)
    finally:
        clear_search_progress_callback()


def _run_search_impl(
    *,
    query_data,
    is_text,
    top_k,
    scope_video_paths,
    scope_library_paths,
    query_vector,
    precise_image,
    mode,
    config,
    profile_enabled,
    profile_meta,
    search_precision_mode=None,
    pixel_query_data,
    preview_anchor_sec,
    locate_anchor_score=None,
    locate_score_margin=None,
    video_discovery_enabled=None,
) -> List[SearchHit]:
    with search_profile_session(
        enabled=profile_enabled,
        search_mode=mode,
        precise_image=precise_image,
        meta=profile_meta,
    ):
        if mode == "chunk":
            results = run_chunk_search(
                query_data,
                is_text=is_text,
                top_k=top_k,
                scope_video_paths=scope_video_paths,
                scope_library_paths=scope_library_paths,
                query_vector=query_vector,
                search_precision_mode=search_precision_mode,
                pixel_query_data=pixel_query_data,
                preview_anchor_sec=preview_anchor_sec,
                locate_anchor_score=locate_anchor_score,
                locate_score_margin=locate_score_margin,
                video_discovery_enabled=video_discovery_enabled,
            )
            record_search_profile_result_count(len(results))
            return results
        if top_k is None:
            top_k = get_search_top_k(config)
        scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
        use_video_discovery = _use_video_discovery_results(
            is_text,
            precise_image,
            scoped,
            video_discovery_enabled=_resolve_video_discovery_enabled(config, video_discovery_enabled),
        )
        with profile_phase("query_vector"):
            query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)

        if scoped and scope_video_paths:
            results = _run_frame_search_per_videos(
                query_vector,
                scope_video_paths,
                top_k,
                config,
                query_data=query_data,
                is_text=is_text,
                precise_image=precise_image,
                pixel_query_data=pixel_query_data,
                preview_anchor_sec=preview_anchor_sec,
                locate_anchor_score=locate_anchor_score,
                locate_score_margin=locate_score_margin,
                use_video_discovery=use_video_discovery,
            )
            record_search_profile_result_count(len(results))
            return results

        if (
            scoped
            and scope_library_paths
            and not scope_video_paths
            and _library_indexes_ready(config, scope_library_paths)
        ):
            merged_hits: List[SearchHit] = []
            library_fetch_k = _resolve_frame_fetch_top_k(top_k, True, is_text, config, precise_image=precise_image)
            if use_video_discovery and not precise_image:
                library_fetch_k = max(int(library_fetch_k), int(resolve_fetch_top_k(top_k, True)))
            for library_path in scope_library_paths:
                with profile_phase("load_assets"):
                    search_index, timestamps, video_paths = load_library_frame_search_assets(library_path, config)
                _merge_search_index_steps(video_paths, timestamps)
                if search_index is None:
                    continue
                with profile_phase("faiss_search"):
                    matched_results, matched_ids = _search_frame_results_with_ids(
                        query_vector,
                        search_index,
                        timestamps,
                        video_paths,
                        top_k=library_fetch_k,
                    )
                clip_seeds = [float(hit.start_sec) for hit in matched_results]
                if precise_image:
                    with profile_phase("bounded_neighbor"):
                        matched_results = _apply_bounded_neighbor_refine(
                            matched_results,
                            matched_ids,
                            query_vector,
                            search_index,
                            timestamps,
                            video_paths,
                        )
                else:
                    with profile_phase("neighbor_rerank"):
                        matched_results = _apply_frame_neighbor_rerank(
                            matched_results,
                            matched_ids,
                            query_vector,
                            search_index,
                            timestamps,
                            video_paths,
                            config,
                            is_text=is_text,
                            precise_image=False,
                        )
                merged_hits.extend(matched_results)
            with profile_phase("scope_filter"):
                # Keep expanded pool until after video-discovery aggregation.
                merge_keep_k = library_fetch_k if use_video_discovery else top_k
                scoped_hits = _merge_search_hits(merged_hits, merge_keep_k)
            results = _finalize_frame_hits(
                query_data,
                is_text,
                scoped_hits,
                merge_keep_k,
                config,
                precise_image=precise_image,
                pixel_query_data=pixel_query_data,
            )
            results = _apply_video_discovery_presentation(
                results,
                top_k,
                enabled=use_video_discovery,
            )
            record_search_profile_result_count(len(results))
            return results

        if precise_image:
            fetch_k = _resolve_stage1_global_fetch_k(top_k, config)
        elif use_video_discovery:
            fetch_k = resolve_fetch_top_k(top_k, True)
        else:
            fetch_k = _resolve_frame_fetch_top_k(top_k, scoped, is_text, config, precise_image=precise_image)
        with profile_phase("load_assets"):
            search_index, timestamps, video_paths = load_search_assets(config)
        _merge_search_index_steps(video_paths, timestamps)
        if search_index is None:
            record_search_profile_result_count(0)
            return []
        _check_asset_profile_compatibility(config, _FRAME_ASSET_INFO, asset_label="frame")

        with profile_phase("faiss_search"):
            matched_results, matched_ids = _search_frame_results_with_ids(
                query_vector,
                search_index,
                timestamps,
                video_paths,
                top_k=fetch_k,
            )
        with profile_phase("neighbor_rerank"):
            if not precise_image:
                matched_results = _apply_frame_neighbor_rerank(
                    matched_results,
                    matched_ids,
                    query_vector,
                    search_index,
                    timestamps,
                    video_paths,
                    config,
                    is_text=is_text,
                    precise_image=False,
                )
        clip_seeds = [float(hit.start_sec) for hit in matched_results]
        if precise_image:
            with profile_phase("bounded_neighbor"):
                matched_results = _apply_bounded_neighbor_refine(
                    matched_results,
                    matched_ids,
                    query_vector,
                    search_index,
                    timestamps,
                    video_paths,
                )
        with profile_phase("scope_filter"):
            if precise_image:
                scoped_hits, scoped_seeds = _scope_filter_hits_with_seeds(
                    matched_results,
                    clip_seeds,
                    video_paths=scope_video_paths,
                    library_paths=scope_library_paths,
                    top_k=fetch_k,
                )
            else:
                # Keep the expanded recall pool until after video-discovery aggregation;
                # truncating to top_k here collapses many videos into one dominant clip.
                scope_keep_k = fetch_k if use_video_discovery else top_k
                scoped_hits = apply_search_scope(
                    matched_results,
                    video_paths=scope_video_paths,
                    library_paths=scope_library_paths,
                    top_k=scope_keep_k,
                )
                scoped_seeds = None
        if precise_image:
            with profile_phase("pixel_rerank"):
                results = _refine_precise_seed_hits(
                    query_data,
                    scoped_hits,
                    top_k,
                    config,
                    seed_times=scoped_seeds,
                    pixel_query_data=pixel_query_data,
                )
        else:
            merge_keep_k = fetch_k if use_video_discovery else top_k
            results = _merge_search_hits(scoped_hits, merge_keep_k)
        if precise_image and scoped and scope_video_paths:
            from src.services.search_scope import filter_hits_by_video_paths

            results = filter_hits_by_video_paths(results, scope_video_paths)
            results = _merge_search_hits(results, top_k)
        results = _apply_video_discovery_presentation(
            results,
            top_k,
            enabled=use_video_discovery,
        )
        record_search_profile_result_count(len(results))
        return results


def run_chunk_search(
    query_data,
    is_text=False,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
    search_precision_mode=None,
    pixel_query_data=None,
    preview_anchor_sec: float | None = None,
    locate_anchor_score: float | None = None,
    locate_score_margin: float | None = None,
    profile: bool | None = None,
    video_discovery_enabled: bool | None = None,
) -> List[SearchHit]:
    config = load_config()
    precise_image = _use_precise_image_pipeline(is_text, config, search_precision_mode)
    profile_enabled = profile if profile is not None else is_profiling_enabled(config)
    profile_meta = build_profile_meta_from_config(
        config,
        precise_image=precise_image,
        search_precision_mode=search_precision_mode,
    )
    _reset_search_index_steps()
    with search_profile_session(
        enabled=profile_enabled,
        search_mode="chunk",
        precise_image=precise_image,
        meta=profile_meta,
    ):
        if not is_text:
            scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
            use_video_discovery = _use_video_discovery_results(
                is_text,
                precise_image,
                scoped,
                video_discovery_enabled=_resolve_video_discovery_enabled(config, video_discovery_enabled),
            )
            if top_k is None:
                top_k = get_search_top_k(config)
            if precise_image and scoped and scope_video_paths:
                results = run_search(
                    query_data,
                    is_text=False,
                    top_k=top_k,
                    scope_video_paths=scope_video_paths,
                    scope_library_paths=scope_library_paths,
                    query_vector=query_vector,
                    search_precision_mode=search_precision_mode,
                    pixel_query_data=pixel_query_data,
                    search_mode="frame",
                    preview_anchor_sec=preview_anchor_sec,
                    locate_anchor_score=locate_anchor_score,
                    locate_score_margin=locate_score_margin,
                    video_discovery_enabled=video_discovery_enabled,
                )
            else:
                results = _run_chunk_search_via_frames(
                    query_data,
                    is_text=is_text,
                    top_k=top_k,
                    scope_video_paths=scope_video_paths,
                    scope_library_paths=scope_library_paths,
                    query_vector=query_vector,
                    search_precision_mode=search_precision_mode,
                    pixel_query_data=pixel_query_data,
                    precise_image=precise_image,
                    config=config,
                )
            results = _apply_video_discovery_presentation(
                results,
                top_k,
                enabled=use_video_discovery,
            )
            record_search_profile_result_count(len(results))
            return results
        if top_k is None:
            top_k = get_search_top_k(config)
        scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
        with profile_phase("query_vector"):
            query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)

        if scoped and scope_video_paths:
            results = _run_chunk_search_per_videos(query_vector, scope_video_paths, top_k, config)
            record_search_profile_result_count(len(results))
            return results

        if (
            scoped
            and scope_library_paths
            and not scope_video_paths
            and _library_indexes_ready(config, scope_library_paths)
        ):
            merged_hits: List[SearchHit] = []
            for library_path in scope_library_paths:
                with profile_phase("load_assets"):
                    search_index, ranges, video_paths = load_library_chunk_search_assets(library_path, config)
                if search_index is None:
                    continue
                with profile_phase("faiss_search"):
                    merged_hits.extend(
                        _search_chunk_results(
                            query_vector,
                            search_index,
                            ranges,
                            video_paths,
                            top_k=top_k,
                        )
                    )
            results = _merge_search_hits(merged_hits, top_k)
            record_search_profile_result_count(len(results))
            return results

        from src.services.search_fetch_policy import resolve_source_filtered_fetch_top_k

        fetch_k = resolve_source_filtered_fetch_top_k(top_k, scoped)
        with profile_phase("load_assets"):
            search_index, ranges, video_paths = load_chunk_search_assets(config)
        if search_index is None:
            record_search_profile_result_count(0)
            return []
        _check_asset_profile_compatibility(config, _CHUNK_ASSET_INFO, asset_label="chunk")

        actual_k = min(fetch_k, search_index.ntotal)
        if actual_k <= 0:
            record_search_profile_result_count(0)
            return []
        with profile_phase("faiss_search"):
            matched_results = _search_chunk_results(
                query_vector,
                search_index,
                ranges,
                video_paths,
                top_k=actual_k,
            )
        with profile_phase("scope_filter"):
            results = apply_search_scope(
                matched_results,
                video_paths=scope_video_paths,
                library_paths=scope_library_paths,
                top_k=top_k,
            )
        record_search_profile_result_count(len(results))
        return results


def warmup_search_runtime():
    get_engine()


def run_dialogue_search(
    query: str,
    *,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    min_score=None,
    config=None,
    query_vector=None,
    match_mode: str = "exact",
) -> tuple[List[SearchHit], str, str]:
    """Dialogue search over shared SQLite transcripts (keyword / fuzzy).

    ``match_mode``: ``exact``/``segment`` (substring), ``fuzzy`` (typo-tolerant),
    ``semantic`` (deferred — empty), or ``auto`` (exact keyword only).

    Returns ``(hits, message, matched_by)`` where ``matched_by`` is
    ``keyword`` / ``keyword_fuzzy`` / ``""``.
    """
    from src.storage.config_store import get_local_model_asset_dirs, get_search_top_k
    from src.storage.lance_dialogue_search import get_dialogue_index_stats, search_dialogue

    cfg = dict(config or load_config())
    text = str(query or "").strip()
    if not text:
        return [], "empty query", ""

    try:
        resolved_top_k = int(top_k) if top_k is not None else get_search_top_k(cfg)
    except (TypeError, ValueError):
        resolved_top_k = get_search_top_k(cfg)
    resolved_top_k = max(1, min(200, resolved_top_k))

    # Over-fetch when scoped so post-filter still has candidates.
    fetch_k = resolve_fetch_top_k(
        resolved_top_k,
        is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths),
    )

    profile_base_dir = get_local_model_asset_dirs(config=cfg)["base_dir"]
    stats = get_dialogue_index_stats(config=cfg, profile_base_dir=profile_base_dir)
    if not stats.get("dialogue_index_ready"):
        return [], "no dialogue index for active profile (build dialogue index first)", ""

    scoped_video_ids = resolve_subtitle_scope_video_ids(
        video_paths=scope_video_paths,
        library_paths=scope_library_paths,
        config=cfg,
    )
    if scoped_video_ids is not None and not scoped_video_ids:
        return [], "no dialogue matches", ""

    # When scoped to concrete videos, fetch_k need not be inflated — the loader
    # already only opens those transcript files.
    search_top_k = resolved_top_k if scoped_video_ids is not None else fetch_k

    routed = search_dialogue(
        text,
        config=cfg,
        profile_base_dir=profile_base_dir,
        top_k=search_top_k,
        query_vector=query_vector,
        match_mode=match_mode,
        video_ids=scoped_video_ids,
    )
    dialogue_hits = list(routed.get("hits") or [])
    matched_by = str(routed.get("matched_by") or "").strip()
    hits = [
        SearchHit(
            start_sec=float(item.start_sec),
            end_sec=float(item.end_sec),
            score=float(item.score),
            video_path=str(item.video_path),
            match_kind="dialogue",
            video_id=str(item.video_id or ""),
            matched_text=str(item.text or ""),
        )
        for item in dialogue_hits
    ]
    from src.services.search_scope import enrich_hits_with_source_paths

    hits = enrich_hits_with_source_paths(hits, config=cfg)
    hits = apply_search_scope(
        hits,
        video_paths=scope_video_paths,
        library_paths=scope_library_paths,
        top_k=resolved_top_k,
    )
    if min_score is not None:
        hits = filter_hits_by_min_score(hits, min_score)

    if not hits:
        message = str(routed.get("message") or "").strip() or "no dialogue matches"
        return [], message, matched_by
    return hits, "", matched_by


__all__ = [
    "_LOCATE_CROP_MIN_CLIP_SCORE",
    "build_query_vector",
    "compute_locate_score_margin",
    "filter_hits_by_min_score",
    "format_clip_score_percent",
    "load_chunk_search_assets",
    "load_search_assets",
    "locate_crop_confidence_warning_key",
    "resolve_clip_confidence_tier_key",
    "run_chunk_search",
    "run_dialogue_search",
    "run_search",
    "warmup_search_runtime",
]
