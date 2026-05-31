"""Shared search scope helpers (library roots or explicit video paths)."""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from src.domain.search_hit import SearchHit


def normalize_scope_path(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.path.expanduser(str(path or "").strip()))))


def iter_indexed_video_entries(meta) -> Iterable[Tuple[str, str, dict]]:
    """Yield (abs_video_path, video_id, file_info) for entries under meta['libraries']."""
    libraries = meta.get("libraries", {}) if isinstance(meta, dict) else {}
    if not isinstance(libraries, dict):
        return
    for root_path, lib_data in libraries.items():
        root_text = str(root_path or "").strip()
        if not root_text or not isinstance(lib_data, dict):
            continue
        files = lib_data.get("files", {})
        if not isinstance(files, dict):
            continue
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            rel_text = str(rel_path or "").strip()
            if not rel_text:
                continue
            video_id = str(info.get("vid", "") or "").strip()
            if not video_id:
                continue
            abs_path = normalize_scope_path(os.path.join(root_text, rel_text))
            yield abs_path, video_id, info


def build_indexed_video_lookup(meta) -> Dict[str, str]:
    return {abs_path: video_id for abs_path, video_id, _info in iter_indexed_video_entries(meta)}


def list_ready_video_paths_for_libraries(library_paths: Optional[Sequence[str]], config=None) -> List[str]:
    from src.storage.asset_store import load_model_metadata
    from src.app.config import load_config

    meta = load_model_metadata(config=config or load_config())
    roots = _normalized_library_roots(library_paths)
    if not roots:
        return []
    paths: List[str] = []
    seen: set[str] = set()
    for abs_path, _video_id, info in iter_indexed_video_entries(meta):
        if str(info.get("asset_state", "")).strip().lower() != "ready":
            continue
        if not any(video_path_under_library_root(abs_path, root) for root in roots):
            continue
        if abs_path in seen:
            continue
        seen.add(abs_path)
        paths.append(abs_path)
    return paths


def count_indexed_ready_videos(config=None) -> int:
    from src.services.library_service import list_local_vector_details

    try:
        detail = list_local_vector_details(validate_contents=False)
    except Exception:
        return 0
    count = 0
    for ent in detail.get("entries", []):
        if not ent.get("source_exists"):
            continue
        if str(ent.get("asset_state", "")).strip().lower() != "ready":
            continue
        count += 1
    return count


def resolve_active_search_library_scope(config=None) -> list[str] | None:
    """Return selected library roots for the current search, or None for all libraries."""
    from src.services.library_service import list_search_scope_library_options, needs_search_index_schema_upgrade
    from src.storage.config_store import get_search_scope_library_paths, get_search_scope_mode, get_search_scope_video_paths

    if needs_search_index_schema_upgrade(config):
        return None
    if get_search_scope_mode(config) != "selected":
        return None
    if get_search_scope_video_paths(config):
        return None
    if len(list_search_scope_library_options()) < 2:
        return None
    paths = get_search_scope_library_paths(config)
    if not paths:
        return None
    return list(paths)


def resolve_active_search_video_scope(config=None) -> list[str] | None:
    """Return selected indexed video paths, or None to search all indexed videos."""
    from src.services.library_service import needs_search_index_schema_upgrade
    from src.storage.config_store import (
        get_search_scope_library_paths,
        get_search_scope_mode,
        get_search_scope_video_paths,
    )

    if needs_search_index_schema_upgrade(config):
        return None
    if get_search_scope_mode(config) != "selected":
        return None
    video_paths = get_search_scope_video_paths(config)
    if video_paths:
        return list(video_paths)
    library_paths = get_search_scope_library_paths(config)
    if library_paths:
        if per_library_indexes_ready(library_paths, config=config):
            return None
        expanded = list_ready_video_paths_for_libraries(library_paths, config=config)
        return expanded or None
    return None


def resolve_default_active_search_scope(
    config=None,
) -> tuple[list[str] | None, list[str] | None]:
    """Mirror desktop Search scope picker: selected videos, else selected libraries, else all."""
    scope_video_paths = resolve_active_search_video_scope(config=config)
    scope_library_paths = None if scope_video_paths else resolve_active_search_library_scope(config=config)
    return scope_video_paths, scope_library_paths


def _read_scope_fields(scope) -> tuple[Optional[List[str]], Optional[List[str]], bool]:
    if scope is None:
        return None, None, False
    if isinstance(scope, dict):
        video_paths = scope.get("video_paths")
        library_paths = scope.get("library_paths")
        use_saved_scope = bool(scope.get("use_saved_scope", False))
    else:
        video_paths = getattr(scope, "video_paths", None)
        library_paths = getattr(scope, "library_paths", None)
        use_saved_scope = bool(getattr(scope, "use_saved_scope", False))
    videos = [str(item).strip() for item in (video_paths or []) if str(item or "").strip()] or None
    libraries = [str(item).strip() for item in (library_paths or []) if str(item or "").strip()] or None
    return videos, libraries, use_saved_scope


def scope_request_is_explicit(scope) -> bool:
    videos, libraries, use_saved_scope = _read_scope_fields(scope)
    if videos or libraries:
        return True
    return use_saved_scope


def resolve_explicit_scope_video_paths(scope, config=None) -> Optional[List[str]]:
    videos, _libraries, use_saved_scope = _read_scope_fields(scope)
    if videos:
        return videos
    if scope is None or not use_saved_scope:
        return None
    from src.app.config import load_config
    from src.storage.config_store import get_search_scope_mode, get_search_scope_video_paths

    cfg = config or load_config()
    if get_search_scope_mode(cfg) != "selected":
        return None
    saved = [str(item).strip() for item in get_search_scope_video_paths(cfg) if str(item or "").strip()]
    return saved or None


def resolve_explicit_scope_library_paths(scope, config=None) -> Optional[List[str]]:
    _videos, libraries, use_saved_scope = _read_scope_fields(scope)
    if libraries:
        return libraries
    if scope is None or not use_saved_scope:
        return None
    from src.app.config import load_config
    from src.storage.config_store import (
        get_search_scope_library_paths,
        get_search_scope_mode,
        get_search_scope_video_paths,
    )

    cfg = config or load_config()
    if get_search_scope_mode(cfg) != "selected":
        return None
    if get_search_scope_video_paths(cfg):
        return None
    saved = [str(item).strip() for item in get_search_scope_library_paths(cfg) if str(item or "").strip()]
    return saved or None


def resolve_effective_search_scope(
    scope,
    *,
    preset_scope_video_paths: Optional[Sequence[str]] = None,
    config=None,
) -> tuple[Optional[List[str]], Optional[List[str]]]:
    """Explicit request scope, else preset-owned videos, else desktop active scope."""
    if scope_request_is_explicit(scope):
        return (
            resolve_explicit_scope_video_paths(scope, config=config),
            resolve_explicit_scope_library_paths(scope, config=config),
        )
    preset_videos = [str(item).strip() for item in (preset_scope_video_paths or []) if str(item or "").strip()]
    if preset_videos:
        return preset_videos, None
    return resolve_default_active_search_scope(config=config)


def per_library_indexes_ready(library_paths: Optional[Sequence[str]], config=None) -> bool:
    if not library_paths:
        return False
    from src.app.config import load_config
    from src.services.search_index_schema import (
        TARGET_SEARCH_INDEX_SCHEMA_VERSION,
        get_search_index_schema_version,
        library_index_is_ready,
    )
    from src.storage.asset_store import load_model_metadata

    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    if get_search_index_schema_version(meta) < TARGET_SEARCH_INDEX_SCHEMA_VERSION:
        return False
    return all(library_index_is_ready(path, config=cfg) for path in library_paths)


def resolve_active_search_mode(config=None) -> str:
    """Return frame/chunk mode for the current search UI setting."""
    from src.storage.config_store import get_search_mode

    return get_search_mode(config)


def resolve_fetch_top_k(top_k: int, scoped: bool) -> int:
    normalized_top_k = max(1, int(top_k))
    if scoped:
        return min(200, max(normalized_top_k * 5, normalized_top_k + 10))
    return normalized_top_k


def resolve_per_video_fetch_top_k(top_k: int, video_count: int) -> int:
    normalized_top_k = max(1, int(top_k))
    if int(video_count) <= 1:
        return min(200, max(normalized_top_k * 5, normalized_top_k + 10))
    return min(200, max(normalized_top_k * 2, normalized_top_k + 5))


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
