"""Shared search scope helpers (library roots or explicit video paths)."""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

from src.domain.search_hit import SearchHit


def normalize_scope_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(path or "").strip()))))


def resolve_active_search_library_scope(config=None) -> list[str] | None:
    """Return selected library roots for the current search, or None for all libraries."""
    from src.services.library_service import list_search_scope_library_options, needs_search_index_schema_upgrade
    from src.storage.config_store import get_search_scope_library_paths, get_search_scope_mode

    if needs_search_index_schema_upgrade(config):
        return None
    if len(list_search_scope_library_options()) < 2:
        return None
    if get_search_scope_mode(config) != "selected":
        return None
    paths = get_search_scope_library_paths(config)
    if not paths:
        return None
    return list(paths)


def resolve_active_search_mode(config=None) -> str:
    """Return frame/chunk mode for the current search UI setting."""
    from src.storage.config_store import get_search_mode

    return get_search_mode(config)


def resolve_fetch_top_k(top_k: int, scoped: bool) -> int:
    normalized_top_k = max(1, int(top_k))
    if scoped:
        return min(200, max(normalized_top_k * 5, normalized_top_k + 10))
    return normalized_top_k


def is_search_scoped(
    *,
    video_paths: Optional[Sequence[str]] = None,
    library_paths: Optional[Sequence[str]] = None,
) -> bool:
    if video_paths and any(str(item or "").strip() for item in video_paths):
        return True
    if library_paths and any(str(item or "").strip() for item in library_paths):
        return True
    return False


def _normalized_video_path_set(video_paths: Optional[Sequence[str]]) -> Optional[set[str]]:
    if not video_paths:
        return None
    allowed = {normalize_scope_path(item) for item in video_paths if str(item or "").strip()}
    return allowed or None


def _normalized_library_roots(library_paths: Optional[Sequence[str]]) -> List[str]:
    if not library_paths:
        return []
    roots = []
    for item in library_paths:
        text = str(item or "").strip()
        if text:
            roots.append(normalize_scope_path(text))
    return roots


def video_path_under_library_root(video_path: str, library_root: str) -> bool:
    normalized_video = normalize_scope_path(video_path)
    normalized_root = normalize_scope_path(library_root)
    if normalized_video == normalized_root:
        return True
    return normalized_video.startswith(normalized_root + os.sep)


def filter_hits_by_video_paths(hits: List[SearchHit], video_paths: Optional[Sequence[str]]) -> List[SearchHit]:
    allowed = _normalized_video_path_set(video_paths)
    if not allowed:
        return hits
    return [hit for hit in hits if normalize_scope_path(hit.video_path) in allowed]


def filter_hits_by_library_paths(hits: List[SearchHit], library_paths: Optional[Sequence[str]]) -> List[SearchHit]:
    roots = _normalized_library_roots(library_paths)
    if not roots:
        return hits
    filtered: List[SearchHit] = []
    for hit in hits:
        for root in roots:
            if video_path_under_library_root(hit.video_path, root):
                filtered.append(hit)
                break
    return filtered


def apply_search_scope(
    hits: List[SearchHit],
    *,
    video_paths: Optional[Sequence[str]] = None,
    library_paths: Optional[Sequence[str]] = None,
    top_k: Optional[int] = None,
) -> List[SearchHit]:
    scoped_hits = filter_hits_by_video_paths(hits, video_paths)
    scoped_hits = filter_hits_by_library_paths(scoped_hits, library_paths)
    if top_k is not None and int(top_k) > 0:
        return scoped_hits[: int(top_k)]
    return scoped_hits
