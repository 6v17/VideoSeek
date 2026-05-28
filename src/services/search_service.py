import os
from typing import List

import cv2
import faiss
import numpy as np

from src.core.clip_embedding import get_clip_embeddings_batch, get_engine, get_text_embedding
from src.app.config import DEFAULT_CONFIG, load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.search_scope import apply_search_scope, is_search_scoped, resolve_fetch_top_k
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
    get_frame_neighbor_rerank_enabled,
    get_frame_neighbor_rerank_top_n,
    get_frame_neighbor_rerank_window,
    get_global_model_asset_paths,
    get_search_mode,
    get_search_top_k,
)

logger = get_logger("search_service")
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


def _merge_search_hits(hits: List[SearchHit], top_k: int) -> List[SearchHit]:
    if top_k <= 0:
        return []
    ordered = sorted(hits, key=lambda item: float(item.score), reverse=True)
    return ordered[:top_k]


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


def filter_hits_by_min_score(hits, min_score) -> List[SearchHit]:
    if min_score is None:
        return list(hits or [])
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        return list(hits or [])
    return [hit for hit in (hits or []) if float(getattr(hit, "score", 0.0) or 0.0) >= threshold]


def _search_frame_results_with_ids(query_vector, index, timestamps, video_paths, top_k):
    actual_k = min(top_k, index.ntotal)
    if actual_k <= 0:
        return [], []
    if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
        raise RuntimeError("Invalid query vector. Please retry the search.")
    query_dim = int(query_vector.shape[1])
    index_dim = int(getattr(index, "d", 0))
    if index_dim > 0 and query_dim != index_dim:
        raise RuntimeError(
            f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
            "Current model uses a different embedding space. Please rebuild the index for the active model."
        )

    distances, indices = index.search(query_vector, actual_k)
    matched_results = []
    matched_ids = []
    for rank, index_value in enumerate(indices[0]):
        if index_value == -1 or index_value >= len(video_paths):
            continue
        timestamp = float(timestamps[index_value])
        video_path = video_paths[index_value]
        matched_results.append(SearchHit(timestamp, timestamp, float(distances[0][rank]), video_path))
        matched_ids.append(int(index_value))
    return matched_results, matched_ids


def _apply_frame_neighbor_rerank(results, frame_ids, query_vector, search_index, timestamps, video_paths, config):
    if not results or not frame_ids:
        return results
    if not get_frame_neighbor_rerank_enabled(config):
        return results

    max_top_n = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    neighbor_window = int(get_frame_neighbor_rerank_window(config) or DEFAULT_CONFIG["frame_neighbor_rerank_window"])
    if max_top_n <= 0 or neighbor_window <= 0:
        return results

    try:
        query = query_vector[0]
    except Exception:
        return results

    reranked = list(results)
    max_index = min(len(results), len(frame_ids), max_top_n)
    for rank in range(max_index):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue

        base_path = video_paths[base_id]
        hit = reranked[rank]
        best_score = float(hit.score)
        best_timestamp = float(hit.start_sec)

        start = max(0, base_id - neighbor_window)
        end = min(len(video_paths) - 1, base_id + neighbor_window)
        for candidate_id in range(start, end + 1):
            if video_paths[candidate_id] != base_path:
                continue
            try:
                candidate_vector = search_index.reconstruct(int(candidate_id))
            except Exception as exc:
                logger.debug("Neighbor rerank skipped due to reconstruct failure: %s", exc)
                return results
            score = float(np.dot(query, candidate_vector))
            if score > best_score:
                best_score = score
                best_timestamp = float(timestamps[candidate_id])

        reranked[rank] = SearchHit(best_timestamp, best_timestamp, best_score, base_path)
    return reranked


def run_search(
    query_data,
    is_text=False,
    top_k=None,
    search_mode=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
) -> List[SearchHit]:
    # Retained intentionally: exported via src.core.core and reached by
    # worker-side runtime imports that static analysis can miss.
    config = load_config()
    mode = str(search_mode or get_search_mode(config)).strip().lower()
    if mode not in {"frame", "chunk"}:
        mode = get_search_mode(config)
    logger.info("Running %s search (is_text=%s)", mode, is_text)
    if mode == "chunk":
        return run_chunk_search(
            query_data,
            is_text=is_text,
            top_k=top_k,
            scope_video_paths=scope_video_paths,
            scope_library_paths=scope_library_paths,
            query_vector=query_vector,
        )
    if top_k is None:
        top_k = get_search_top_k(config)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)

    if (
        scoped
        and scope_library_paths
        and not scope_video_paths
        and _library_indexes_ready(config, scope_library_paths)
    ):
        merged_hits: List[SearchHit] = []
        for library_path in scope_library_paths:
            search_index, timestamps, video_paths = load_library_frame_search_assets(library_path, config)
            if search_index is None:
                continue
            matched_results, matched_ids = _search_frame_results_with_ids(
                query_vector,
                search_index,
                timestamps,
                video_paths,
                top_k=top_k,
            )
            matched_results = _apply_frame_neighbor_rerank(
                matched_results,
                matched_ids,
                query_vector,
                search_index,
                timestamps,
                video_paths,
                config,
            )
            merged_hits.extend(matched_results)
        return _merge_search_hits(merged_hits, top_k)

    fetch_k = resolve_fetch_top_k(top_k, scoped)
    search_index, timestamps, video_paths = load_search_assets(config)
    if search_index is None:
        return []
    _check_asset_profile_compatibility(config, _FRAME_ASSET_INFO, asset_label="frame")

    matched_results, matched_ids = _search_frame_results_with_ids(
        query_vector,
        search_index,
        timestamps,
        video_paths,
        top_k=fetch_k,
    )
    matched_results = _apply_frame_neighbor_rerank(
        matched_results,
        matched_ids,
        query_vector,
        search_index,
        timestamps,
        video_paths,
        config,
    )
    return apply_search_scope(
        matched_results,
        video_paths=scope_video_paths,
        library_paths=scope_library_paths,
        top_k=top_k,
    )


def run_chunk_search(
    query_data,
    is_text=False,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
) -> List[SearchHit]:
    config = load_config()
    if top_k is None:
        top_k = get_search_top_k(config)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)

    if (
        scoped
        and scope_library_paths
        and not scope_video_paths
        and _library_indexes_ready(config, scope_library_paths)
    ):
        merged_hits: List[SearchHit] = []
        for library_path in scope_library_paths:
            search_index, ranges, video_paths = load_library_chunk_search_assets(library_path, config)
            if search_index is None:
                continue
            actual_k = min(top_k, search_index.ntotal)
            if actual_k <= 0:
                continue
            distances, indices = search_index.search(query_vector, actual_k)
            for rank, index_value in enumerate(indices[0]):
                if index_value == -1 or index_value >= len(video_paths):
                    continue
                time_range = ranges[index_value]
                merged_hits.append(
                    SearchHit(
                        float(time_range[0]),
                        float(time_range[1]),
                        float(distances[0][rank]),
                        video_paths[index_value],
                    )
                )
        return _merge_search_hits(merged_hits, top_k)

    fetch_k = resolve_fetch_top_k(top_k, scoped)
    search_index, ranges, video_paths = load_chunk_search_assets(config)
    if search_index is None:
        return []
    _check_asset_profile_compatibility(config, _CHUNK_ASSET_INFO, asset_label="chunk")

    actual_k = min(fetch_k, search_index.ntotal)
    if actual_k <= 0:
        return []
    if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
        raise RuntimeError("Invalid query vector. Please retry the search.")
    query_dim = int(query_vector.shape[1])
    index_dim = int(getattr(search_index, "d", 0))
    if index_dim > 0 and query_dim != index_dim:
        raise RuntimeError(
            f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
            "Current model uses a different embedding space. Please rebuild the index for the active model."
        )

    distances, indices = search_index.search(query_vector, actual_k)
    matched_results = []
    for rank, index_value in enumerate(indices[0]):
        if index_value == -1 or index_value >= len(video_paths):
            continue
        time_range = ranges[index_value]
        start_time = float(time_range[0])
        end_time = float(time_range[1])
        matched_results.append(
            SearchHit(start_time, end_time, float(distances[0][rank]), video_paths[index_value])
        )
    return apply_search_scope(
        matched_results,
        video_paths=scope_video_paths,
        library_paths=scope_library_paths,
        top_k=top_k,
    )


def warmup_search_runtime():
    config = load_config()
    get_engine()
    load_search_assets(config)
    load_chunk_search_assets(config)
