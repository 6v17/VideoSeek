"""Hit merge, dedupe, and scoped filtering helpers for search pipelines."""

from __future__ import annotations

from typing import List, Sequence

from src.domain.search_hit import SearchHit
from src.services.image_search_rerank import merge_index_step_lookup, reset_index_step_lookup
from src.services.search_scope import apply_search_scope, normalize_scope_path
from src.storage.config_store import is_precise_image_search


def _reset_search_index_steps() -> None:
    reset_index_step_lookup()


def _merge_search_index_steps(video_paths, timestamps) -> None:
    if video_paths is None or timestamps is None:
        return
    merge_index_step_lookup(video_paths, timestamps)


def _merge_search_hits(hits: List[SearchHit], top_k: int) -> List[SearchHit]:
    if top_k <= 0:
        return []
    ordered = sorted(hits or [], key=lambda item: float(item.score), reverse=True)
    return ordered[: int(top_k)]


def _resolve_scoped_video_targets(scope_video_paths, config):
    from src.services.search_scope import build_indexed_video_lookup, normalize_scope_path
    from src.storage.asset_store import load_model_metadata

    lookup = build_indexed_video_lookup(load_model_metadata(config=config))
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw_path in scope_video_paths or []:
        normalized = normalize_scope_path(str(raw_path or ""))
        if not normalized or normalized in seen:
            continue
        video_id = lookup.get(normalized)
        if not video_id:
            continue
        seen.add(normalized)
        targets.append((normalized, video_id))
    return targets


def _use_precise_image_pipeline(is_text: bool, config, search_precision_mode=None) -> bool:
    if is_text:
        return False
    return is_precise_image_search(config, search_precision_mode)


def _dedupe_nearby_hits(hits: List[SearchHit], bucket_sec: float = 1.0) -> List[SearchHit]:
    if not hits:
        return []
    bucket = max(0.25, float(bucket_sec))
    best: dict[tuple[str, int], SearchHit] = {}
    for hit in hits:
        key = (str(hit.video_path), int(float(hit.start_sec) / bucket))
        if key not in best or float(hit.score) > float(best[key].score):
            best[key] = hit
    return sorted(best.values(), key=lambda item: float(item.score), reverse=True)


def _clamp_time_near_seed(time_sec: float, seed_sec: float, max_shift_sec: float) -> float:
    seed = max(0.0, float(seed_sec))
    delta = max(0.0, float(max_shift_sec))
    value = max(0.0, float(time_sec))
    return min(max(value, seed - delta), seed + delta)


def _scope_filter_hits_with_seeds(
    hits: List[SearchHit],
    seed_times: List[float],
    *,
    video_paths: Sequence[str] | None = None,
    library_paths: Sequence[str] | None = None,
    top_k: int | None = None,
) -> tuple[List[SearchHit], List[float]]:
    if not hits:
        return [], []
    if len(seed_times) != len(hits):
        seed_times = [float(hit.start_sec) for hit in hits]
    scoped_hits = apply_search_scope(
        hits,
        video_paths=video_paths,
        library_paths=library_paths,
        top_k=top_k,
    )
    if len(scoped_hits) == len(hits):
        return scoped_hits, list(seed_times)
    allowed = {
        (
            normalize_scope_path(str(hit.video_path or "")),
            round(float(hit.start_sec), 3),
            round(float(hit.end_sec), 3),
        )
        for hit in scoped_hits
    }
    filtered_hits: List[SearchHit] = []
    filtered_seeds: List[float] = []
    for hit, seed in zip(hits, seed_times):
        key = (
            normalize_scope_path(str(hit.video_path or "")),
            round(float(hit.start_sec), 3),
            round(float(hit.end_sec), 3),
        )
        if key in allowed:
            filtered_hits.append(hit)
            filtered_seeds.append(float(seed))
    if top_k is not None and int(top_k) > 0:
        filtered_hits = filtered_hits[: int(top_k)]
        filtered_seeds = filtered_seeds[: int(top_k)]
    return filtered_hits, filtered_seeds
