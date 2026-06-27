"""Fetch-k and pixel-localize limits for search pipelines."""

from __future__ import annotations

from typing import List

from src.app.config import DEFAULT_CONFIG
from src.domain.search_hit import SearchHit
from src.services.search_scope import resolve_fetch_top_k

_GLOBAL_STAGE1_FETCH_CAP = 400
_PRECISE_FETCH_CAP = 200
_PRECISE_PIXEL_LOCALIZE_TOP_N = 3
_IN_VIDEO_PIXEL_LOCALIZE_CAP = 15


def _resolve_stage1_global_fetch_k(top_k: int, config) -> int:
    base = resolve_fetch_top_k(top_k, True)
    try:
        multiplier = int(config.get("image_search_fetch_multiplier", DEFAULT_CONFIG["image_search_fetch_multiplier"]))
    except (TypeError, ValueError):
        multiplier = int(DEFAULT_CONFIG["image_search_fetch_multiplier"])
    multiplier = max(1, min(multiplier, 8))
    expanded = max(base * multiplier, base + 15)
    return min(_GLOBAL_STAGE1_FETCH_CAP, expanded)


def _precise_pixel_localize_top_n(config, hits: List[SearchHit] | None = None) -> int:
    from src.services.image_search_rerank import _image_pixel_rerank_top_n

    prepared_count = len(hits or [])
    unique_videos = {
        str(getattr(hit, "video_path", "") or "").strip()
        for hit in (hits or [])
        if str(getattr(hit, "video_path", "") or "").strip()
    }
    if len(unique_videos) == 1 and prepared_count > 0:
        configured = _image_pixel_rerank_top_n(config, prepared_count)
        return max(1, min(configured, _IN_VIDEO_PIXEL_LOCALIZE_CAP, prepared_count))
    configured = _image_pixel_rerank_top_n(config, _PRECISE_PIXEL_LOCALIZE_TOP_N)
    return max(1, min(configured, _PRECISE_PIXEL_LOCALIZE_TOP_N, prepared_count or _PRECISE_PIXEL_LOCALIZE_TOP_N))


def _resolve_frame_fetch_top_k(
    top_k: int,
    scoped: bool,
    is_text: bool,
    config,
    precise_image: bool = False,
) -> int:
    if is_text or not precise_image:
        return resolve_fetch_top_k(top_k, scoped)
    fetch_k = resolve_fetch_top_k(top_k, scoped or True)
    try:
        multiplier = int(config.get("image_search_fetch_multiplier", DEFAULT_CONFIG["image_search_fetch_multiplier"]))
    except (TypeError, ValueError):
        multiplier = int(DEFAULT_CONFIG["image_search_fetch_multiplier"])
    multiplier = max(1, min(multiplier, 8))
    expanded = max(fetch_k * multiplier, fetch_k + 15)
    return min(_PRECISE_FETCH_CAP, expanded)


def _resolve_chunk_precise_frame_fetch_k(top_k: int, scoped: bool) -> int:
    normalized = max(1, int(top_k))
    expanded = max(normalized * 6, normalized + 30)
    if scoped:
        expanded = max(expanded, normalized * 3 + 15)
    return min(200, expanded)
