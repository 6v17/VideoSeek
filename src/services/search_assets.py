"""Vector asset loading for local and library-scoped search (LanceDB)."""

from __future__ import annotations

import os

import numpy as np

from src.app.logging_utils import get_logger
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.lance_search_index import (
    load_lance_chunk_search_assets,
    load_lance_frame_search_assets,
    lance_cache_key_for_profile,
    lance_search_is_ready,
)
from src.utils import canonicalize_library_path

logger = get_logger("search_assets")

_FRAME_ASSET_CACHE = {"key": None, "value": (None, None, None)}
_CHUNK_ASSET_CACHE = {"key": None, "value": (None, None, None)}
_LIBRARY_FRAME_ASSET_CACHE: dict[tuple, tuple] = {}
_LIBRARY_CHUNK_ASSET_CACHE: dict[tuple, tuple] = {}
_FRAME_ASSET_INFO = {"key": None, "embedding_spec": None, "index_dim": 0}
_CHUNK_ASSET_INFO = {"key": None, "embedding_spec": None, "index_dim": 0}


def _check_asset_profile_compatibility(config, asset_info, asset_label):
    return


def invalidate_search_asset_caches() -> None:
    _FRAME_ASSET_CACHE["key"] = None
    _FRAME_ASSET_CACHE["value"] = (None, None, None)
    _CHUNK_ASSET_CACHE["key"] = None
    _CHUNK_ASSET_CACHE["value"] = (None, None, None)
    _LIBRARY_FRAME_ASSET_CACHE.clear()
    _LIBRARY_CHUNK_ASSET_CACHE.clear()


def _profile_base_dir(config) -> str:
    return get_local_model_asset_dirs(config=config)["base_dir"]


def load_search_assets(config):
    profile_base_dir = _profile_base_dir(config)
    if not lance_search_is_ready(profile_base_dir):
        logger.warning("Lance frame search assets are missing. Please sync vectors first.")
        return None, None, None

    cache_key = lance_cache_key_for_profile(profile_base_dir, table_name="frames")
    if cache_key is not None and _FRAME_ASSET_CACHE["key"] == cache_key:
        return _FRAME_ASSET_CACHE["value"]

    value = load_lance_frame_search_assets(profile_base_dir)
    if value[0] is None:
        logger.warning("Lance frame search assets are missing. Please sync vectors first.")
        return None, None, None
    _FRAME_ASSET_CACHE["key"] = cache_key
    _FRAME_ASSET_CACHE["value"] = value
    return value


def load_chunk_search_assets(config):
    profile_base_dir = _profile_base_dir(config)
    if not lance_search_is_ready(profile_base_dir):
        logger.warning("Lance chunk search assets are missing. Please sync vectors first.")
        return None, None, None

    cache_key = lance_cache_key_for_profile(profile_base_dir, table_name="chunks")
    if cache_key is not None and _CHUNK_ASSET_CACHE["key"] == cache_key:
        return _CHUNK_ASSET_CACHE["value"]

    value = load_lance_chunk_search_assets(profile_base_dir)
    if value[0] is None:
        logger.warning("Lance chunk search assets are missing. Please sync vectors first.")
        return None, None, None
    _CHUNK_ASSET_CACHE["key"] = cache_key
    _CHUNK_ASSET_CACHE["value"] = value
    return value


def _library_indexes_ready(config, library_paths) -> bool:
    profile_base_dir = _profile_base_dir(config)
    if not lance_search_is_ready(profile_base_dir):
        return False
    roots = [str(path or "").strip() for path in (library_paths or []) if str(path or "").strip()]
    return bool(roots)


def load_library_frame_search_assets(library_path, config):
    profile_base_dir = _profile_base_dir(config)
    normalized_library = canonicalize_library_path(library_path)
    cache_key = lance_cache_key_for_profile(
        profile_base_dir,
        library_path=normalized_library,
        table_name="frames",
    )
    if cache_key is not None and cache_key in _LIBRARY_FRAME_ASSET_CACHE:
        return _LIBRARY_FRAME_ASSET_CACHE[cache_key]
    value = load_lance_frame_search_assets(
        profile_base_dir,
        library_path=library_path,
    )
    if cache_key is not None:
        _LIBRARY_FRAME_ASSET_CACHE[cache_key] = value
    return value


def load_library_chunk_search_assets(library_path, config):
    profile_base_dir = _profile_base_dir(config)
    normalized_library = canonicalize_library_path(library_path)
    cache_key = lance_cache_key_for_profile(
        profile_base_dir,
        library_path=normalized_library,
        table_name="chunks",
    )
    if cache_key is not None and cache_key in _LIBRARY_CHUNK_ASSET_CACHE:
        return _LIBRARY_CHUNK_ASSET_CACHE[cache_key]
    value = load_lance_chunk_search_assets(
        profile_base_dir,
        library_path=library_path,
    )
    if cache_key is not None:
        _LIBRARY_CHUNK_ASSET_CACHE[cache_key] = value
    return value


def _load_per_video_frame_assets(video_id, abs_path, config, *, include_vectors: bool = True):
    profile_base_dir = _profile_base_dir(config)
    search_index, timestamps, video_paths = load_lance_frame_search_assets(
        profile_base_dir,
        video_id=video_id,
    )
    if search_index is None or timestamps is None or video_paths is None:
        return None, None, None, None
    ts = np.asarray(timestamps, dtype=np.float32).reshape(-1)
    count = int(search_index.ntotal)
    if count <= 0:
        return None, None, None, None
    vector_matrix = None
    if include_vectors:
        try:
            vector_matrix = np.asarray(search_index.vectors, dtype=np.float32)
        except Exception as exc:
            logger.debug("Per-video Lance vector matrix unavailable for %s: %s", video_id, exc)
    return search_index, ts, video_paths, vector_matrix
