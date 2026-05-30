import os
from typing import List

import cv2
import faiss
import numpy as np

from src.core.clip_embedding import get_clip_embeddings_batch, get_engine, get_text_embedding
from src.app.config import DEFAULT_CONFIG, load_config
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit
from src.services.indexing_service import load_video_chunks_by_id
from src.services.search_scope import (
    apply_search_scope,
    build_indexed_video_lookup,
    is_search_scoped,
    normalize_scope_path,
    resolve_fetch_top_k,
    resolve_per_video_fetch_top_k,
)
from src.storage.config_store import get_local_model_asset_dirs
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
    get_global_model_asset_paths,
    get_search_mode,
    get_search_top_k,
    is_precise_image_search,
)
from src.services.image_search_rerank import apply_image_pixel_rerank

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


def _resolve_scoped_video_targets(scope_video_paths, config):
    meta = load_model_metadata(config=config)
    lookup = build_indexed_video_lookup(meta)
    targets = []
    seen: set[str] = set()
    for raw in scope_video_paths or []:
        abs_path = normalize_scope_path(raw)
        video_id = lookup.get(abs_path)
        if not video_id or abs_path in seen:
            continue
        seen.add(abs_path)
        targets.append((abs_path, video_id))
    return targets


def _load_per_video_frame_assets(video_id, abs_path, config):
    model_dirs = get_local_model_asset_dirs(config=config)
    index_file = os.path.join(model_dirs["index_dir"], f"{video_id}_index.faiss")
    if not os.path.isfile(index_file):
        return None, None, None
    search_index = load_clip_index(index_file)
    if search_index is None:
        return None, None, None
    from src.services.indexing_service import load_video_vectors_by_id

    _vectors, timestamps = load_video_vectors_by_id(video_id, config)
    if timestamps is None:
        return None, None, None
    ts = np.asarray(timestamps, dtype=np.float32).reshape(-1)
    count = min(int(search_index.ntotal), len(ts))
    if count <= 0:
        return None, None, None
    if count < len(ts):
        ts = ts[:count]
    video_paths = [abs_path] * count
    return search_index, ts, video_paths


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


def _run_frame_search_per_videos(
    query_vector,
    scope_video_paths,
    top_k,
    config,
    query_data=None,
    is_text=False,
    precise_image=False,
    pixel_query_data=None,
) -> List[SearchHit]:
    targets = _resolve_scoped_video_targets(scope_video_paths, config)
    if not targets:
        return []
    per_k = resolve_per_video_fetch_top_k(top_k, len(targets))
    if precise_image:
        per_k = _resolve_frame_fetch_top_k(per_k, scoped=True, is_text=False, config=config, precise_image=True)
    merged_hits: List[SearchHit] = []
    for abs_path, video_id in targets:
        search_index, timestamps, video_paths = _load_per_video_frame_assets(video_id, abs_path, config)
        if search_index is None:
            continue
        matched_results, matched_ids = _search_frame_results_with_ids(
            query_vector,
            search_index,
            timestamps,
            video_paths,
            top_k=per_k,
        )
        matched_results = _apply_frame_neighbor_rerank(
            matched_results,
            matched_ids,
            query_vector,
            search_index,
            timestamps,
            video_paths,
            config,
            is_text=is_text,
            precise_image=precise_image,
        )
        merged_hits.extend(matched_results)
    return _finalize_frame_hits(
        query_data,
        is_text,
        merged_hits,
        top_k,
        config,
        precise_image=precise_image,
        pixel_query_data=pixel_query_data,
    )


def _run_chunk_search_per_videos(query_vector, scope_video_paths, top_k, config) -> List[SearchHit]:
    targets = _resolve_scoped_video_targets(scope_video_paths, config)
    if not targets:
        return []
    try:
        query = query_vector[0]
    except Exception:
        return []
    merged_hits: List[SearchHit] = []
    for abs_path, video_id in targets:
        chunks = load_video_chunks_by_id(video_id, config)
        if not chunks:
            continue
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if embedding is None:
                continue
            vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
            if vector.size <= 0:
                continue
            score = float(np.dot(query, vector))
            merged_hits.append(
                SearchHit(float(chunk["start"]), float(chunk["end"]), score, abs_path)
            )
    return _merge_search_hits(merged_hits, top_k)


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


def _neighbor_rerank_enabled(config, is_text: bool = False, precise_image: bool = False) -> bool:
    if get_frame_neighbor_rerank_enabled(config):
        return True
    return (not bool(is_text)) and bool(precise_image)


def _resolve_frame_fetch_top_k(
    top_k: int,
    scoped: bool,
    is_text: bool,
    config,
    precise_image: bool = False,
) -> int:
    fetch_k = resolve_fetch_top_k(top_k, scoped)
    if is_text or not precise_image:
        return fetch_k
    try:
        multiplier = int(config.get("image_search_fetch_multiplier", DEFAULT_CONFIG["image_search_fetch_multiplier"]))
    except (TypeError, ValueError):
        multiplier = int(DEFAULT_CONFIG["image_search_fetch_multiplier"])
    multiplier = max(1, min(multiplier, 8))
    expanded = max(fetch_k * multiplier, fetch_k + 15)
    return min(200, expanded)


def _finalize_frame_hits(
    query_data,
    is_text: bool,
    hits: List[SearchHit],
    top_k: int,
    config,
    precise_image: bool = False,
    pixel_query_data=None,
) -> List[SearchHit]:
    if is_text or not precise_image:
        return _merge_search_hits(hits, top_k)
    rerank_query = pixel_query_data if pixel_query_data is not None else query_data
    reranked = apply_image_pixel_rerank(rerank_query, hits, config=config, top_k=top_k)
    deduped = _dedupe_nearby_hits(reranked, bucket_sec=1.0)
    return _merge_search_hits(deduped, top_k)


def _neighbor_rerank_window_sec(config, is_text: bool, precise_image: bool = False) -> float:
    cfg = config or {}
    if "frame_neighbor_rerank_window_sec" in cfg:
        try:
            return max(0.5, float(cfg["frame_neighbor_rerank_window_sec"]))
        except (TypeError, ValueError):
            pass
    if precise_image and not is_text:
        return 4.0
    try:
        frame_window = int(cfg.get("frame_neighbor_rerank_window", DEFAULT_CONFIG["frame_neighbor_rerank_window"]))
    except (TypeError, ValueError):
        frame_window = int(DEFAULT_CONFIG["frame_neighbor_rerank_window"])
    try:
        fps = float(cfg.get("fps", DEFAULT_CONFIG["fps"]) or DEFAULT_CONFIG["fps"])
    except (TypeError, ValueError):
        fps = float(DEFAULT_CONFIG["fps"])
    return max(1.0, float(frame_window) / max(fps, 0.1))


def _same_scope_video_path(left, right) -> bool:
    return str(left or "") == str(right or "")


def _collect_neighbor_frame_ids(base_id: int, timestamps, video_paths, window_sec: float) -> List[int]:
    total = len(video_paths)
    if base_id < 0 or base_id >= total:
        return []

    base_path = video_paths[base_id]
    base_ts = float(timestamps[base_id])
    window = max(0.0, float(window_sec))
    neighbor_ids = [base_id]

    cursor = base_id - 1
    while cursor >= 0 and _same_scope_video_path(video_paths[cursor], base_path):
        ts = float(timestamps[cursor])
        if base_ts - ts > window:
            break
        neighbor_ids.append(cursor)
        cursor -= 1

    cursor = base_id + 1
    while cursor < total and _same_scope_video_path(video_paths[cursor], base_path):
        ts = float(timestamps[cursor])
        if ts - base_ts > window:
            break
        neighbor_ids.append(cursor)
        cursor += 1

    return neighbor_ids


def _apply_frame_neighbor_rerank(
    results,
    frame_ids,
    query_vector,
    search_index,
    timestamps,
    video_paths,
    config,
    is_text: bool = False,
    precise_image: bool = False,
):
    if not results or not frame_ids:
        return results
    if not _neighbor_rerank_enabled(config, is_text=is_text, precise_image=precise_image):
        return results

    max_top_n = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    window_sec = _neighbor_rerank_window_sec(config, is_text=is_text, precise_image=precise_image)
    if max_top_n <= 0 or window_sec <= 0:
        return results

    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
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

        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            try:
                candidate_vector = np.asarray(search_index.reconstruct(int(candidate_id)), dtype=np.float32).reshape(-1)
            except Exception as exc:
                logger.debug(
                    "Neighbor rerank reconstruct failed for id=%s: %s",
                    candidate_id,
                    exc,
                )
                continue
            score = float(np.dot(query, candidate_vector))
            if score > best_score:
                best_score = score
                best_timestamp = float(timestamps[candidate_id])

        reranked[rank] = SearchHit(best_timestamp, best_timestamp, best_score, str(base_path))
    return reranked


def _expand_neighbor_rerank_candidates(
    results,
    frame_ids,
    query_vector,
    search_index,
    timestamps,
    video_paths,
    config,
    is_text: bool = False,
    precise_image: bool = False,
    *,
    seed_top_n: int | None = None,
) -> List[SearchHit]:
    """Score every neighbor frame around each FAISS seed (not only the best one)."""
    if not results or not frame_ids:
        return list(results or [])
    if not _neighbor_rerank_enabled(config, is_text=is_text, precise_image=precise_image):
        return list(results or [])

    configured_top_n = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    max_top_n = int(seed_top_n) if seed_top_n is not None else configured_top_n
    max_top_n = max(1, min(max_top_n, len(results), len(frame_ids)))
    window_sec = _neighbor_rerank_window_sec(config, is_text=is_text, precise_image=precise_image)
    if window_sec <= 0:
        return list(results or [])

    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return list(results or [])

    candidates: dict[tuple[str, int], SearchHit] = {}
    for rank in range(max_top_n):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue
        base_path = str(video_paths[base_id])
        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            try:
                candidate_vector = np.asarray(search_index.reconstruct(int(candidate_id)), dtype=np.float32).reshape(-1)
            except Exception as exc:
                logger.debug(
                    "Neighbor candidate reconstruct failed for id=%s: %s",
                    candidate_id,
                    exc,
                )
                continue
            score = float(np.dot(query, candidate_vector))
            ts = float(timestamps[candidate_id])
            key = (base_path, int(round(ts * 1000)))
            hit = SearchHit(ts, ts, score, base_path)
            if key not in candidates or score > float(candidates[key].score):
                candidates[key] = hit

    for hit in results:
        key = (str(hit.video_path), int(round(float(hit.start_sec) * 1000)))
        if key not in candidates or float(hit.score) > float(candidates[key].score):
            candidates[key] = hit

    return sorted(candidates.values(), key=lambda item: float(item.score), reverse=True)


def _resolve_neighbor_seed_top_n(
    config,
    fetch_k: int,
    top_k: int,
    *,
    precise_image: bool,
) -> int:
    """How many FAISS seeds get neighbor expansion (CLIP-only, must stay bounded)."""
    if not _neighbor_rerank_enabled(config, is_text=False, precise_image=precise_image):
        return max(1, min(int(fetch_k), int(top_k)))
    try:
        configured = int(get_frame_neighbor_rerank_top_n(config) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    except (TypeError, ValueError):
        configured = int(DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    target = max(configured, int(top_k) * 2, 12)
    return max(1, min(int(fetch_k), target, 32))


def _prepare_frame_candidates_for_chunk_aggregate(hits: List[SearchHit]) -> List[SearchHit]:
    if not hits:
        return []
    # CLIP-only pool for chunk aggregation. Pixel rerank runs after aggregation
    # on the final top-k segments; doing it here on hundreds of frames is too slow.
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
    query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)
    fetch_k = _resolve_chunk_precise_frame_fetch_k(top_k, scoped)
    neighbor_seed_n = _resolve_neighbor_seed_top_n(config, fetch_k, top_k, precise_image=precise_image)
    candidates: List[SearchHit] = []

    if scoped and scope_video_paths:
        per_k = resolve_per_video_fetch_top_k(fetch_k, len(scope_video_paths))
        per_seed_n = _resolve_neighbor_seed_top_n(config, per_k, top_k, precise_image=precise_image)
        for abs_path, video_id in _resolve_scoped_video_targets(scope_video_paths, config):
            search_index, timestamps, video_paths = _load_per_video_frame_assets(video_id, abs_path, config)
            if search_index is None:
                continue
            matched_results, matched_ids = _search_frame_results_with_ids(
                query_vector,
                search_index,
                timestamps,
                video_paths,
                top_k=per_k,
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
                    seed_top_n=per_seed_n,
                )
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
    from src.services.search_scope import build_indexed_video_lookup, normalize_scope_path
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
    frame_start = float(frame_hit.start_sec)
    start = float(chunk_start)
    end = float(chunk_end)
    anchor = min(max(frame_start, start), end)
    return SearchHit(anchor, end, float(frame_hit.score), str(frame_hit.video_path))


def _load_global_chunk_ranges_by_path(config) -> dict[str, list[tuple[float, float]]]:
    assets = load_chunk_search_assets(config)
    if not assets:
        return {}
    _index, ranges, paths = assets
    if _index is None or ranges is None or paths is None:
        return {}
    by_path: dict[str, list[tuple[float, float]]] = {}
    range_count = min(len(ranges), len(paths))
    for idx in range(range_count):
        path = normalize_scope_path(str(paths[idx]))
        time_range = ranges[idx]
        by_path.setdefault(path, []).append((float(time_range[0]), float(time_range[1])))
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
    chunks = load_video_chunks_by_id(video_id, config)
    return [(float(chunk["start"]), float(chunk["end"])) for chunk in chunks]


def _resolve_chunk_precise_frame_fetch_k(top_k: int, scoped: bool) -> int:
    normalized = max(1, int(top_k))
    expanded = max(normalized * 4, normalized + 15)
    if scoped:
        expanded = max(expanded, normalized * 2 + 10)
    return min(80, expanded)


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
) -> List[SearchHit]:
    # Retained intentionally: exported via src.core.core and reached by
    # worker-side runtime imports that static analysis can miss.
    config = load_config()
    precise_image = _use_precise_image_pipeline(is_text, config, search_precision_mode)
    mode = str(search_mode or get_search_mode(config)).strip().lower()
    if mode not in {"frame", "chunk"}:
        mode = get_search_mode(config)
    logger.info("Running %s search (is_text=%s, precise_image=%s)", mode, is_text, precise_image)
    if mode == "chunk":
        return run_chunk_search(
            query_data,
            is_text=is_text,
            top_k=top_k,
            scope_video_paths=scope_video_paths,
            scope_library_paths=scope_library_paths,
            query_vector=query_vector,
            search_precision_mode=search_precision_mode,
            pixel_query_data=pixel_query_data,
        )
    if top_k is None:
        top_k = get_search_top_k(config)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)

    if scoped and scope_video_paths:
        return _run_frame_search_per_videos(
            query_vector,
            scope_video_paths,
            top_k,
            config,
            query_data=query_data,
            is_text=is_text,
            precise_image=precise_image,
            pixel_query_data=pixel_query_data,
        )

    if (
        scoped
        and scope_library_paths
        and not scope_video_paths
        and _library_indexes_ready(config, scope_library_paths)
    ):
        merged_hits: List[SearchHit] = []
        library_fetch_k = _resolve_frame_fetch_top_k(top_k, True, is_text, config, precise_image=precise_image)
        for library_path in scope_library_paths:
            search_index, timestamps, video_paths = load_library_frame_search_assets(library_path, config)
            if search_index is None:
                continue
            matched_results, matched_ids = _search_frame_results_with_ids(
                query_vector,
                search_index,
                timestamps,
                video_paths,
                top_k=library_fetch_k,
            )
            matched_results = _apply_frame_neighbor_rerank(
                matched_results,
                matched_ids,
                query_vector,
                search_index,
                timestamps,
                video_paths,
                config,
                is_text=is_text,
                precise_image=precise_image,
            )
            merged_hits.extend(matched_results)
        scoped_hits = _merge_search_hits(merged_hits, library_fetch_k)
        return _finalize_frame_hits(
            query_data,
            is_text,
            scoped_hits,
            top_k,
            config,
            precise_image=precise_image,
            pixel_query_data=pixel_query_data,
        )

    fetch_k = _resolve_frame_fetch_top_k(top_k, scoped, is_text, config, precise_image=precise_image)
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
        is_text=is_text,
        precise_image=precise_image,
    )
    scoped_hits = apply_search_scope(
        matched_results,
        video_paths=scope_video_paths,
        library_paths=scope_library_paths,
        top_k=fetch_k if precise_image else top_k,
    )
    return _finalize_frame_hits(
        query_data,
        is_text,
        scoped_hits,
        top_k,
        config,
        precise_image=precise_image,
        pixel_query_data=pixel_query_data,
    )


def run_chunk_search(
    query_data,
    is_text=False,
    top_k=None,
    scope_video_paths=None,
    scope_library_paths=None,
    query_vector=None,
    search_precision_mode=None,
    pixel_query_data=None,
) -> List[SearchHit]:
    config = load_config()
    precise_image = _use_precise_image_pipeline(is_text, config, search_precision_mode)
    if not is_text:
        return _run_chunk_search_via_frames(
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
    if top_k is None:
        top_k = get_search_top_k(config)
    scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
    query_vector = _coalesce_query_vector(query_data, is_text=is_text, query_vector=query_vector)

    if scoped and scope_video_paths:
        return _run_chunk_search_per_videos(query_vector, scope_video_paths, top_k, config)

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
