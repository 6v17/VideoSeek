"""FAISS / vector asset loading for local and library-scoped search."""

from __future__ import annotations

import os

import numpy as np

from src.app.logging_utils import get_logger
from src.core.faiss_index import load_clip_index
from src.services.search_index_schema import (
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    get_library_index_paths,
    get_search_index_schema_version,
    library_index_is_ready,
)
from src.storage.asset_store import load_model_metadata
from src.storage.config_store import (
    get_active_model_profile,
    get_global_model_asset_paths,
    get_local_model_asset_dirs,
)

logger = get_logger("search_assets")

_FRAME_ASSET_CACHE = {"key": None, "value": (None, None, None)}
_CHUNK_ASSET_CACHE = {"key": None, "value": (None, None, None)}
_FRAME_ASSET_INFO = {"key": None, "embedding_spec": None, "index_dim": 0}
_CHUNK_ASSET_INFO = {"key": None, "embedding_spec": None, "index_dim": 0}


def _asset_cache_key(index_file, vector_file):
    try:
        return (
            os.path.abspath(index_file),
            os.path.getmtime(index_file),
            os.path.abspath(vector_file),
            os.path.getmtime(vector_file),
        )
    except OSError:
        return None


def _load_asset_metadata(vector_file, required_fields, asset_label):
    try:
        data = np.load(vector_file, allow_pickle=True).item()
    except Exception as exc:
        logger.error("Failed to load %s metadata: %s", asset_label, exc)
        return None

    if not isinstance(data, dict):
        logger.error("Invalid %s metadata payload: expected dict", asset_label)
        return None

    missing_fields = [field for field in required_fields if data.get(field) is None]
    if missing_fields:
        logger.error("Invalid %s metadata payload: missing %s", asset_label, ", ".join(missing_fields))
        return None

    return data


def _reset_asset_info(info_cache):
    info_cache["key"] = None
    info_cache["embedding_spec"] = None
    info_cache["index_dim"] = 0


def _check_asset_profile_compatibility(config, asset_info, asset_label):
    spec = asset_info.get("embedding_spec")
    if not isinstance(spec, dict):
        return
    profile = get_active_model_profile(config=config)
    active_profile_id = str(profile.get("id", "") or "").strip()
    active_provider = str(profile.get("provider", "") or "").strip()
    spec_model_id = str(spec.get("model_id", "") or "").strip()
    spec_provider = str(spec.get("provider", "") or "").strip()
    spec_dimension = spec.get("dimension")
    index_dim = int(asset_info.get("index_dim", 0) or 0)

    if spec_model_id and active_profile_id and spec_model_id != active_profile_id:
        raise RuntimeError(
            f"Search {asset_label} index targets model profile '{spec_model_id}', "
            f"but active profile is '{active_profile_id}'. "
            "Please rebuild the index for the active model profile."
        )
    if spec_provider and active_provider and spec_provider != active_provider:
        raise RuntimeError(
            f"Search {asset_label} index provider mismatch (index={spec_provider}, active={active_provider}). "
            "Please rebuild the index for the active model profile."
        )
    try:
        spec_dimension = int(spec_dimension)
    except (TypeError, ValueError):
        spec_dimension = 0
    if spec_dimension > 0 and index_dim > 0 and spec_dimension != index_dim:
        raise RuntimeError(
            f"Search {asset_label} index dimension mismatch in metadata (spec={spec_dimension}, index={index_dim}). "
            "Please rebuild the index for the active model profile."
        )


def load_search_assets(config):
    global_paths = get_global_model_asset_paths(config=config)
    index_file = global_paths["cross_index_file"]
    vector_file = global_paths["cross_vector_file"]

    if not os.path.exists(index_file) or not os.path.exists(vector_file):
        logger.warning("Global frame search index is missing. Please update the index first.")
        return None, None, None

    cache_key = _asset_cache_key(index_file, vector_file)
    if cache_key is not None and _FRAME_ASSET_CACHE["key"] == cache_key:
        return _FRAME_ASSET_CACHE["value"]

    search_index = load_clip_index(index_file)
    if search_index is None:
        _FRAME_ASSET_CACHE["key"] = None
        _FRAME_ASSET_CACHE["value"] = (None, None, None)
        _reset_asset_info(_FRAME_ASSET_INFO)
        return None, None, None

    data = _load_asset_metadata(vector_file, required_fields=("timestamps", "paths"), asset_label="frame search")
    if data is None:
        _FRAME_ASSET_CACHE["key"] = None
        _FRAME_ASSET_CACHE["value"] = (None, None, None)
        _reset_asset_info(_FRAME_ASSET_INFO)
        return None, None, None

    value = (search_index, data.get("timestamps"), data.get("paths"))
    _FRAME_ASSET_CACHE["key"] = cache_key
    _FRAME_ASSET_CACHE["value"] = value
    _FRAME_ASSET_INFO["key"] = cache_key
    _FRAME_ASSET_INFO["embedding_spec"] = data.get("embedding_spec") if isinstance(data.get("embedding_spec"), dict) else None
    _FRAME_ASSET_INFO["index_dim"] = int(getattr(search_index, "d", 0) or 0)
    return value


def load_chunk_search_assets(config):
    global_paths = get_global_model_asset_paths(config=config)
    index_file = global_paths["cross_chunk_index_file"]
    vector_file = global_paths["cross_chunk_vector_file"]

    if not os.path.exists(index_file) or not os.path.exists(vector_file):
        logger.warning("Global chunk search index is missing. Please update the index first.")
        return None, None, None

    cache_key = _asset_cache_key(index_file, vector_file)
    if cache_key is not None and _CHUNK_ASSET_CACHE["key"] == cache_key:
        return _CHUNK_ASSET_CACHE["value"]

    search_index = load_clip_index(index_file)
    if search_index is None:
        _CHUNK_ASSET_CACHE["key"] = None
        _CHUNK_ASSET_CACHE["value"] = (None, None, None)
        _reset_asset_info(_CHUNK_ASSET_INFO)
        return None, None, None

    data = _load_asset_metadata(vector_file, required_fields=("ranges", "paths"), asset_label="chunk search")
    if data is None:
        _CHUNK_ASSET_CACHE["key"] = None
        _CHUNK_ASSET_CACHE["value"] = (None, None, None)
        _reset_asset_info(_CHUNK_ASSET_INFO)
        return None, None, None

    value = (search_index, data.get("ranges"), data.get("paths"))
    _CHUNK_ASSET_CACHE["key"] = cache_key
    _CHUNK_ASSET_CACHE["value"] = value
    _CHUNK_ASSET_INFO["key"] = cache_key
    _CHUNK_ASSET_INFO["embedding_spec"] = data.get("embedding_spec") if isinstance(data.get("embedding_spec"), dict) else None
    _CHUNK_ASSET_INFO["index_dim"] = int(getattr(search_index, "d", 0) or 0)
    return value


def _library_indexes_ready(config, library_paths) -> bool:
    if get_search_index_schema_version(load_model_metadata(config=config)) < TARGET_SEARCH_INDEX_SCHEMA_VERSION:
        return False
    roots = [str(path or "").strip() for path in (library_paths or []) if str(path or "").strip()]
    if not roots:
        return False
    return all(library_index_is_ready(path, config=config) for path in roots)


def load_library_frame_search_assets(library_path, config):
    if not library_index_is_ready(library_path, config=config):
        return None, None, None
    asset_paths = get_library_index_paths(library_path, config=config)
    search_index = load_clip_index(asset_paths["frame_index_file"])
    if search_index is None:
        return None, None, None
    data = _load_asset_metadata(asset_paths["frame_vector_file"], required_fields=("timestamps", "paths"), asset_label="library frame search")
    if data is None:
        return None, None, None
    return search_index, data.get("timestamps"), data.get("paths")


def load_library_chunk_search_assets(library_path, config):
    asset_paths = get_library_index_paths(library_path, config=config)
    if not os.path.exists(asset_paths["chunk_index_file"]) or not os.path.exists(asset_paths["chunk_vector_file"]):
        return None, None, None
    search_index = load_clip_index(asset_paths["chunk_index_file"])
    if search_index is None:
        return None, None, None
    data = _load_asset_metadata(asset_paths["chunk_vector_file"], required_fields=("ranges", "paths"), asset_label="library chunk search")
    if data is None:
        return None, None, None
    return search_index, data.get("ranges"), data.get("paths")


def _load_per_video_frame_assets(video_id, abs_path, config, *, include_vectors: bool = True):
    model_dirs = get_local_model_asset_dirs(config=config)
    index_file = os.path.join(model_dirs["index_dir"], f"{video_id}_index.faiss")
    if not os.path.isfile(index_file):
        return None, None, None, None
    search_index = load_clip_index(index_file)
    if search_index is None:
        return None, None, None, None
    from src.services.indexing_service import load_video_vectors_by_id

    vectors, timestamps = load_video_vectors_by_id(video_id, config)
    if timestamps is None:
        return None, None, None, None
    ts = np.asarray(timestamps, dtype=np.float32).reshape(-1)
    count = min(int(search_index.ntotal), len(ts))
    if count <= 0:
        return None, None, None, None
    if count < len(ts):
        ts = ts[:count]
    vector_matrix = None
    if include_vectors and vectors is not None:
        try:
            matrix = np.asarray(vectors, dtype=np.float32)
            if matrix.ndim == 2 and matrix.shape[0] >= count:
                vector_matrix = matrix[:count]
        except Exception as exc:
            logger.debug("Per-video vector matrix unavailable for %s: %s", video_id, exc)
            vector_matrix = None
    video_paths = [abs_path] * count
    return search_index, ts, video_paths, vector_matrix
