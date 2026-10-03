"""Post-search time-range filter with candidate-pool backfill."""

from __future__ import annotations

import threading
from typing import Iterable, List, Mapping

from src.app.config import DEFAULT_CONFIG, load_config
from src.domain.search_hit import SearchHit
from src.services.search_scope import normalize_scope_path
from src.services.search_skip_ranges import (
    covered_skip_seconds,
    migrate_legacy_skip_edges_to_ranges,
    normalize_search_skip_ranges_text,
    parse_search_skip_ranges,
    probe_in_skip_intervals,
    resolve_skip_intervals,
)

_EDGE_FETCH_CAP = 500
_MIN_KEEP_SPAN_SEC = 30.0

_video_end_lookup_local = threading.local()


def reset_video_end_lookup() -> None:
    _video_end_lookup_local.lookup = None


def get_video_end_lookup() -> dict[str, float]:
    lookup = getattr(_video_end_lookup_local, "lookup", None)
    return dict(lookup) if isinstance(lookup, dict) else {}


def merge_video_end_lookup(video_paths: Iterable, timestamps: Iterable) -> None:
    paths = list(video_paths or [])
    times = list(timestamps or [])
    if not paths or not times or len(paths) != len(times):
        return
    current = get_video_end_lookup()
    for path, raw_ts in zip(paths, times):
        key = normalize_scope_path(path)
        if not key:
            continue
        try:
            ts = float(raw_ts)
        except (TypeError, ValueError):
            continue
        if ts < 0:
            continue
        prev = current.get(key)
        if prev is None or ts > prev:
            current[key] = ts
    _video_end_lookup_local.lookup = current


def get_search_skip_ranges_text(config=None) -> str:
    cfg = config if isinstance(config, dict) else load_config()
    text = normalize_search_skip_ranges_text(
        cfg.get("search_skip_ranges", DEFAULT_CONFIG.get("search_skip_ranges", ""))
    )
    if text:
        return text
    # Legacy migration for older configs that only stored intro/outro seconds.
    enabled = bool(cfg.get("search_skip_edges_enabled", False))
    if not enabled:
        return ""
    return migrate_legacy_skip_edges_to_ranges(
        cfg.get("search_skip_intro_sec", 0),
        cfg.get("search_skip_outro_sec", 0),
    )


def get_search_skip_edges_enabled(config=None) -> bool:
    return bool(parse_search_skip_ranges(get_search_skip_ranges_text(config)))


def expand_fetch_for_edge_filter(fetch_k: int, top_k: int, config=None) -> int:
    """Grow the candidate pool so edge filtering can backfill to top_k."""
    base = max(1, int(fetch_k))
    if not get_search_skip_edges_enabled(config):
        return base
    want = max(1, int(top_k))
    expanded = max(base, want * 2, base + want)
    return max(base, min(_EDGE_FETCH_CAP, expanded))


def resolve_result_pool_k(
    fetch_k: int,
    top_k: int,
    config=None,
    *,
    force_expand: bool = False,
) -> int:
    """Keep the expanded pool until after edge filtering / video-discovery."""
    want = max(1, int(top_k))
    pool = max(want, int(fetch_k))
    if force_expand or get_search_skip_edges_enabled(config):
        return pool
    return want


def _hit_probe_sec(hit: SearchHit) -> float:
    start = float(getattr(hit, "start_sec", 0.0) or 0.0)
    end = float(getattr(hit, "end_sec", start) or start)
    if end > start + 0.5:
        return (start + end) / 2.0
    return start


def hit_in_skipped_edge(
    hit: SearchHit,
    *,
    ranges=None,
    intro_sec: float | None = None,
    outro_sec: float | None = None,
    end_lookup: Mapping[str, float] | None = None,
) -> bool:
    path = normalize_scope_path(getattr(hit, "video_path", "") or "")
    probe = max(0.0, _hit_probe_sec(hit))
    rules = list(ranges or [])
    if not rules and (intro_sec is not None or outro_sec is not None):
        legacy = migrate_legacy_skip_edges_to_ranges(intro_sec or 0, outro_sec or 0)
        rules = parse_search_skip_ranges(legacy)
    if not rules:
        return False

    end = None
    if end_lookup:
        normalized_lookup = {
            normalize_scope_path(key): float(value)
            for key, value in end_lookup.items()
            if normalize_scope_path(key)
        }
        if path in normalized_lookup:
            end = normalized_lookup[path]

    intervals = resolve_skip_intervals(rules, end)
    if not intervals:
        return False
    if end is not None:
        remaining = max(0.0, float(end) - covered_skip_seconds(intervals))
        if remaining < _MIN_KEEP_SPAN_SEC:
            return False
    return probe_in_skip_intervals(probe, intervals)


def filter_search_edge_hits(
    hits: List[SearchHit] | None,
    config=None,
    *,
    end_lookup: Mapping[str, float] | None = None,
) -> List[SearchHit]:
    """Drop hits inside configured skip ranges. Caller backfills from the pool."""
    prepared = list(hits or [])
    if not prepared or not get_search_skip_edges_enabled(config):
        return prepared
    rules = parse_search_skip_ranges(get_search_skip_ranges_text(config))
    if not rules:
        return prepared
    lookup = dict(end_lookup) if end_lookup is not None else get_video_end_lookup()
    return [
        hit
        for hit in prepared
        if not hit_in_skipped_edge(hit, ranges=rules, end_lookup=lookup)
    ]
