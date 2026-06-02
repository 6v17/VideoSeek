import os
from typing import List, Sequence

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
from src.services.image_search_rerank import (
    apply_image_pixel_rerank,
    is_likely_cropped_query_image,
    merge_index_step_lookup,
    reset_index_step_lookup,
    refine_hit_time_with_pixel,
)
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
        if not video_id:
            normalized_case = os.path.normcase(abs_path)
            for path, candidate_id in lookup.items():
                if os.path.normcase(str(path)) == normalized_case:
                    video_id = candidate_id
                    abs_path = normalize_scope_path(str(path))
                    break
        if not video_id or abs_path in seen:
            continue
        seen.add(abs_path)
        targets.append((abs_path, video_id))
    return targets


def _load_per_video_frame_assets(video_id, abs_path, config):
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
    if vectors is not None:
        try:
            matrix = np.asarray(vectors, dtype=np.float32)
            if matrix.ndim == 2 and matrix.shape[0] >= count:
                vector_matrix = matrix[:count]
        except Exception:
            vector_matrix = None
    video_paths = [abs_path] * count
    return search_index, ts, video_paths, vector_matrix


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


_GLOBAL_VIDEO_RECALL_LIMIT = 20
_GLOBAL_PER_VIDEO_SEED_CAP = 5
_GLOBAL_STAGE1_FETCH_CAP = 400
_GLOBAL_STAGE2_PER_VIDEO_K = 100
_PRECISE_PIXEL_LOCALIZE_TOP_N = 3
_PRECISE_FETCH_CAP = 200
_PRECISE_SEED_MAX_SHIFT_SEC = 5.0
_PRECISE_NEIGHBOR_WINDOW_SEC = 5.0
_PRECISE_NEIGHBOR_BLEND = 0.1
_LOCATE_ANCHOR_WINDOW_SEC = 30.0
_LOCATE_CROP_ANCHOR_WINDOW_SEC = 5.0
_LOCATE_PIXEL_MAX_SHIFT_SEC = 5.0
_LOCATE_PIXEL_LOCALIZE_TOP_N = 3
_LOCATE_RESULT_TOP_K = 3
_LOCATE_CROP_RESULT_TOP_K = 1
_LOCATE_CROP_MIN_CLIP_SCORE = 0.6
_LOCATE_CROP_STABILITY_POOL_K = 12
_LOCATE_CROP_ANCHOR_MIN_GAIN = 0.03
_CLIP_CONFIDENCE_VERY_HIGH = 0.85
_CLIP_CONFIDENCE_HIGH = 0.70
_CLIP_CONFIDENCE_MEDIUM = 0.60
_ANCHOR_BRUTEFORCE_MAX_FRAMES = 48
_ANCHOR_BRUTEFORCE_PREFILTER_MULTIPLIER = 2


def _search_frame_results_in_time_window(
    query_vector,
    index,
    timestamps,
    video_paths,
    *,
    center_sec: float,
    window_sec: float,
    top_k: int,
    preloaded_vectors=None,
):
    actual_k = min(max(1, int(top_k)), int(getattr(index, "ntotal", 0) or 0))
    if actual_k <= 0:
        return [], []
    if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
        return [], []
    query_dim = int(query_vector.shape[1])
    index_dim = int(getattr(index, "d", 0))
    if index_dim > 0 and query_dim != index_dim:
        raise RuntimeError(
            f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
            "Current model uses a different embedding space. Please rebuild the index for the active model."
        )

    center = max(0.0, float(center_sec))
    window = max(1.0, float(window_sec))
    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return [], []

    candidate_ids: List[int] = []
    total = min(len(video_paths), len(timestamps), int(getattr(index, "ntotal", 0) or 0))
    for idx in range(total):
        if abs(float(timestamps[idx]) - center) <= window:
            candidate_ids.append(idx)
    if not candidate_ids:
        return [], []
    if len(candidate_ids) > _ANCHOR_BRUTEFORCE_MAX_FRAMES:
        prefilter_limit = min(
            len(candidate_ids),
            _ANCHOR_BRUTEFORCE_MAX_FRAMES * _ANCHOR_BRUTEFORCE_PREFILTER_MULTIPLIER,
        )
        candidate_ids.sort(key=lambda idx: abs(float(timestamps[idx]) - center))
        candidate_ids = candidate_ids[:prefilter_limit]

    vector_matrix = None
    if preloaded_vectors is not None:
        try:
            matrix = np.asarray(preloaded_vectors, dtype=np.float32)
            if matrix.ndim == 2 and matrix.shape[0] >= total:
                vector_matrix = matrix
        except Exception:
            vector_matrix = None

    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    scored: List[tuple[float, int]] = []
    for idx in candidate_ids:
        score = _neighbor_candidate_score(
            query,
            index,
            int(idx),
            vector_cache,
            score_cache,
            vector_matrix=vector_matrix,
        )
        if score is None:
            continue
        scored.append((float(score), int(idx)))
    if not scored:
        return [], []

    scored.sort(key=lambda item: (-item[0], item[1]))
    if len(scored) > _ANCHOR_BRUTEFORCE_MAX_FRAMES:
        scored = scored[: _ANCHOR_BRUTEFORCE_MAX_FRAMES]
    matched_results: List[SearchHit] = []
    matched_ids: List[int] = []
    for score, idx in scored[:actual_k]:
        timestamp = float(timestamps[idx])
        matched_results.append(
            SearchHit(timestamp, timestamp, score, str(video_paths[idx]))
        )
        matched_ids.append(int(idx))
    return matched_results, matched_ids


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


def _resolve_locate_result_top_k(top_k: int, *, crop_query: bool = False) -> int:
    if crop_query:
        return _LOCATE_CROP_RESULT_TOP_K
    try:
        requested = int(top_k)
    except (TypeError, ValueError):
        requested = _LOCATE_RESULT_TOP_K
    return max(1, min(requested, _LOCATE_RESULT_TOP_K))


def _resolve_rerank_query(query_data, pixel_query_data):
    return pixel_query_data if pixel_query_data is not None else query_data


def format_clip_score_percent(score: float) -> str:
    pct = max(0.0, float(score)) * 100.0
    if pct >= 100.0:
        return "100%"
    if pct >= 10.0:
        return f"{pct:.1f}%"
    return f"{pct:.2f}%"


def resolve_clip_confidence_tier_key(score: float) -> str:
    value = max(0.0, float(score))
    if value >= _CLIP_CONFIDENCE_VERY_HIGH:
        return "clip_confidence_very_high"
    if value >= _CLIP_CONFIDENCE_HIGH:
        return "clip_confidence_high"
    if value >= _CLIP_CONFIDENCE_MEDIUM:
        return "clip_confidence_medium"
    return "clip_confidence_low"


def resolve_clip_confidence_label(score: float, texts) -> str:
    key = resolve_clip_confidence_tier_key(score)
    return str((texts or {}).get(key, "") or "").strip()


def _apply_locate_crop_anchor_stability(
    hits: List[SearchHit],
    anchor_sec: float,
    target_video_path: str,
) -> List[SearchHit]:
    """Keep preview anchor unless CLIP gain over nearest anchor frame is meaningful."""
    anchor = max(0.0, float(anchor_sec))
    path = str(target_video_path or "")
    if not hits:
        return [SearchHit(anchor, anchor, 0.0, path)]

    best = hits[0]
    anchor_hit = min(hits, key=lambda item: abs(float(item.start_sec) - anchor))
    best_time = float(best.start_sec)
    best_score = float(best.score)
    anchor_score = float(anchor_hit.score)

    if abs(best_time - anchor) <= 0.05:
        result = [best]
        anchor_kept = True
    elif (best_score - anchor_score) < _LOCATE_CROP_ANCHOR_MIN_GAIN:
        stable_score = anchor_score if anchor_score > 0 else best_score
        stable_path = str(best.video_path or path or anchor_hit.video_path)
        result = [SearchHit(anchor, anchor, stable_score, stable_path)]
        anchor_kept = True
    else:
        result = [best]
        anchor_kept = False

    try:
        from src.services.search_telemetry import record_crop_locate_anchor

        record_crop_locate_anchor(
            anchor_sec=anchor,
            result_sec=float(result[0].start_sec),
            anchor_kept=anchor_kept,
            best_sec=best_time,
            best_score=best_score,
            anchor_score=anchor_score,
            clip_score=float(result[0].score),
            video_path=path,
        )
    except Exception:
        pass

    return result


def locate_crop_confidence_warning_key(
    hits: List[SearchHit],
    query_data,
    *,
    preview_anchor_sec: float | None = None,
    pixel_query_data=None,
    min_score: float | None = None,
) -> str | None:
    """Return i18n key when screenshot locate confidence is low (still returns hits)."""
    if preview_anchor_sec is None:
        return None
    rerank_query = _resolve_rerank_query(query_data, pixel_query_data)
    if not is_likely_cropped_query_image(rerank_query):
        return None
    threshold = float(min_score if min_score is not None else _LOCATE_CROP_MIN_CLIP_SCORE)
    if not hits:
        return "locate_crop_low_confidence_empty"
    if float(hits[0].score) < threshold:
        return "locate_crop_low_confidence"
    return None


def _search_locate_anchor_window_hits(
    query_vector,
    target_video_path: str,
    anchor_sec: float,
    top_k: int,
    config,
    *,
    per_video_index=None,
    per_video_timestamps=None,
    per_video_paths=None,
    per_video_vectors=None,
    window_sec: float | None = None,
    skip_neighbor_refine: bool = False,
) -> List[SearchHit]:
    """Locate stage1: global CLIP hits in anchor window, per-video fallback."""
    locate_k = max(1, int(top_k))
    anchor = max(0.0, float(anchor_sec))
    window = max(1.0, float(window_sec if window_sec is not None else _LOCATE_ANCHOR_WINDOW_SEC))
    target_key = normalize_scope_path(str(target_video_path or ""))

    global_index, global_ts, global_paths = load_search_assets(config)
    if global_index is not None and int(getattr(global_index, "ntotal", 0) or 0) > 0:
        fetch_k = _resolve_frame_fetch_top_k(locate_k, True, False, config, precise_image=True)
        global_hits, global_ids = _search_frame_results_with_ids(
            query_vector,
            global_index,
            global_ts,
            global_paths,
            top_k=fetch_k,
        )
        in_window: List[SearchHit] = []
        in_window_ids: List[int] = []
        for hit, frame_id in zip(global_hits, global_ids):
            if normalize_scope_path(str(hit.video_path or "")) != target_key:
                continue
            if abs(float(hit.start_sec) - anchor) > window:
                continue
            in_window.append(hit)
            in_window_ids.append(int(frame_id))
        if in_window:
            if skip_neighbor_refine:
                merged = _merge_search_hits(in_window, locate_k)
            else:
                refined = _apply_bounded_neighbor_refine(
                    in_window,
                    in_window_ids,
                    query_vector,
                    global_index,
                    global_ts,
                    global_paths,
                )
                merged = _merge_search_hits(refined, locate_k)
            if merged:
                return merged

    if per_video_index is not None:
        matched_results, _matched_ids = _search_frame_results_in_time_window(
            query_vector,
            per_video_index,
            per_video_timestamps,
            per_video_paths,
            center_sec=anchor,
            window_sec=window,
            top_k=locate_k,
            preloaded_vectors=per_video_vectors,
        )
        if matched_results:
            return matched_results

    if window <= _LOCATE_PIXEL_MAX_SHIFT_SEC + 1e-6:
        return [SearchHit(anchor, anchor, 0.0, str(target_video_path))]
    return []


def _search_locate_crop_trusted_hits(
    query_vector,
    target_video_path: str,
    anchor_sec: float,
    config,
    *,
    per_video_index=None,
    per_video_timestamps=None,
    per_video_paths=None,
    per_video_vectors=None,
) -> List[SearchHit]:
    """Screenshot locate: trust fast-search anchor, only score frames within ±5s."""
    pool = _search_locate_anchor_window_hits(
        query_vector,
        target_video_path,
        anchor_sec,
        _LOCATE_CROP_STABILITY_POOL_K,
        config,
        per_video_index=per_video_index,
        per_video_timestamps=per_video_timestamps,
        per_video_paths=per_video_paths,
        per_video_vectors=per_video_vectors,
        window_sec=_LOCATE_CROP_ANCHOR_WINDOW_SEC,
        skip_neighbor_refine=True,
    )
    return _apply_locate_crop_anchor_stability(pool, anchor_sec, target_video_path)


def _apply_bounded_neighbor_refine(
    results,
    frame_ids,
    query_vector,
    search_index,
    timestamps,
    video_paths,
    *,
    max_top_n: int | None = None,
    max_shift_sec: float = _PRECISE_SEED_MAX_SHIFT_SEC,
    window_sec: float = _PRECISE_NEIGHBOR_WINDOW_SEC,
    neighbor_blend: float = _PRECISE_NEIGHBOR_BLEND,
):
    if not results or not frame_ids:
        return list(results or [])
    try:
        query = np.asarray(query_vector[0], dtype=np.float32).reshape(-1)
    except Exception:
        return list(results or [])

    configured_top_n = int(get_frame_neighbor_rerank_top_n({}) or DEFAULT_CONFIG["frame_neighbor_rerank_top_n"])
    max_index = min(len(results), len(frame_ids), int(max_top_n or configured_top_n))
    if max_index <= 0:
        return list(results or [])

    reranked = list(results)
    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    blend = max(0.0, min(float(neighbor_blend), 1.0))
    for rank in range(max_index):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue
        hit = reranked[rank]
        seed_time = float(hit.start_sec)
        base_score = float(hit.score)
        best_timestamp = seed_time
        best_neighbor_score = base_score
        base_path = video_paths[base_id]
        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            candidate_ts = float(timestamps[candidate_id])
            if abs(candidate_ts - seed_time) > max_shift_sec:
                continue
            score = _neighbor_candidate_score(
                query,
                search_index,
                int(candidate_id),
                vector_cache,
                score_cache,
            )
            if score is None:
                continue
            if score > best_neighbor_score:
                best_neighbor_score = float(score)
                best_timestamp = candidate_ts
        if best_neighbor_score > base_score:
            adjusted_time = _clamp_time_near_seed(best_timestamp, seed_time, max_shift_sec)
            blended_score = ((1.0 - blend) * base_score) + (blend * best_neighbor_score)
            reranked[rank] = SearchHit(adjusted_time, adjusted_time, blended_score, str(hit.video_path))
    return reranked


def _refine_precise_seed_hits(
    query_data,
    hits: List[SearchHit],
    top_k: int,
    config,
    *,
    seed_times: Sequence[float] | None = None,
    pixel_query_data=None,
    locate_anchor_sec: float | None = None,
) -> List[SearchHit]:
    """Localize frozen recall seeds: pixel (and optional bounded neighbor upstream) only."""
    if not hits:
        return []
    prepared = _dedupe_nearby_hits(hits, bucket_sec=1.0)
    frozen = _merge_search_hits(prepared, top_k)
    if not frozen:
        return []
    rerank_query = _resolve_rerank_query(query_data, pixel_query_data)
    crop_query = is_likely_cropped_query_image(rerank_query)
    clip_seeds = [float(t) for t in (seed_times or [hit.start_sec for hit in frozen])]
    if len(clip_seeds) != len(frozen):
        clip_seeds = [float(hit.start_sec) for hit in frozen]

    if crop_query:
        limit = 1 if locate_anchor_sec is not None else max(1, int(top_k))
        return frozen[:limit]

    if locate_anchor_sec is not None:
        anchor = max(0.0, float(locate_anchor_sec))
        locate_limit = max(1, min(_LOCATE_PIXEL_LOCALIZE_TOP_N, len(frozen)))
        head = frozen[:locate_limit]
        clip_seeds = [
            _clamp_time_near_seed(float(hit.start_sec), anchor, _LOCATE_PIXEL_MAX_SHIFT_SEC)
            for hit in head
        ]
        pixel_head = apply_image_pixel_rerank(
            rerank_query,
            head,
            config=config,
            top_k=locate_limit,
            seed_times=clip_seeds,
            max_time_shift_sec=_LOCATE_PIXEL_MAX_SHIFT_SEC,
            preserve_order=True,
        ) if head else []
        output: List[SearchHit] = []
        for index, hit in enumerate(frozen):
            if index < len(pixel_head):
                output.append(pixel_head[index])
            else:
                output.append(hit)
        return output[: max(1, int(top_k))]

    localize_n = _precise_pixel_localize_top_n(config, frozen)
    head = frozen[:localize_n]
    pixel_head = apply_image_pixel_rerank(
        rerank_query,
        head,
        config=config,
        top_k=localize_n,
        seed_times=clip_seeds[:localize_n],
        max_time_shift_sec=_PRECISE_SEED_MAX_SHIFT_SEC,
        preserve_order=True,
    ) if head else []
    # Keep CLIP recall order; pixel may nudge time but must not reshuffle candidates.
    output: List[SearchHit] = []
    for index, hit in enumerate(frozen):
        if index < len(pixel_head):
            output.append(pixel_head[index])
        else:
            output.append(hit)
    return output[: max(1, int(top_k))]


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
) -> List[SearchHit]:
    targets = _resolve_scoped_video_targets(scope_video_paths, config)
    if not targets:
        return []
    per_k = resolve_per_video_fetch_top_k(top_k, len(targets))
    if precise_image:
        per_k = _resolve_frame_fetch_top_k(per_k, scoped=True, is_text=False, config=config, precise_image=True)
    rerank_query = _resolve_rerank_query(query_data, pixel_query_data)
    crop_query = is_likely_cropped_query_image(rerank_query)
    merged_hits: List[SearchHit] = []
    for abs_path, video_id in targets:
        with profile_phase("load_assets"):
            search_index, timestamps, video_paths, vector_matrix = _load_per_video_frame_assets(
                video_id,
                abs_path,
                config,
            )
        _merge_search_index_steps(video_paths, timestamps)
        if search_index is None:
            continue
        anchor_sec = None
        if preview_anchor_sec is not None:
            try:
                anchor_sec = float(preview_anchor_sec)
            except (TypeError, ValueError):
                anchor_sec = None
        if anchor_sec is not None:
            emit_search_progress("locate_progress_load")
        with profile_phase("faiss_search"):
            if anchor_sec is not None:
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
                    )
            elif precise_image:
                clip_seeds: List[float] = []
                matched_results = []
                global_index, global_ts, global_paths = load_search_assets(config)
                if global_index is not None:
                    fetch_k = _resolve_frame_fetch_top_k(top_k, True, False, config, precise_image=True)
                    global_hits, global_ids = _search_frame_results_with_ids(
                        query_vector,
                        global_index,
                        global_ts,
                        global_paths,
                        top_k=fetch_k,
                    )
                    clip_seeds = [float(hit.start_sec) for hit in global_hits]
                    global_hits = _apply_bounded_neighbor_refine(
                        global_hits,
                        global_ids,
                        query_vector,
                        global_index,
                        global_ts,
                        global_paths,
                    )
                    matched_results, clip_seeds = _scope_filter_hits_with_seeds(
                        global_hits,
                        clip_seeds,
                        video_paths=[abs_path],
                        top_k=top_k,
                    )
                if not matched_results and search_index is not None:
                    matched_results, matched_ids = _search_frame_results_with_ids(
                        query_vector,
                        search_index,
                        timestamps,
                        video_paths,
                        top_k=min(int(top_k), 32),
                    )
                    clip_seeds = [float(hit.start_sec) for hit in matched_results]
                    matched_results = _apply_bounded_neighbor_refine(
                        matched_results,
                        matched_ids,
                        query_vector,
                        search_index,
                        timestamps,
                        video_paths,
                    )
                merged_hits.extend(
                    _refine_precise_seed_hits(
                        query_data,
                        matched_results,
                        top_k,
                        config,
                        seed_times=clip_seeds,
                        pixel_query_data=pixel_query_data,
                    )
                )
                continue
            else:
                matched_results, matched_ids = _search_frame_results_with_ids(
                    query_vector,
                    search_index,
                    timestamps,
                    video_paths,
                    top_k=int(per_k),
                )
        if anchor_sec is not None:
            locate_top_k = _resolve_locate_result_top_k(top_k, crop_query=crop_query)
            if not crop_query:
                emit_search_progress("locate_progress_pixel")
            merged_hits.extend(
                _refine_precise_seed_hits(
                    query_data,
                    matched_results,
                    locate_top_k,
                    config,
                    pixel_query_data=pixel_query_data,
                    locate_anchor_sec=anchor_sec,
                )
            )
        else:
            merged_hits.extend(matched_results)
    if preview_anchor_sec is not None:
        crop_final = is_likely_cropped_query_image(rerank_query)
        return _merge_search_hits(
            merged_hits,
            _resolve_locate_result_top_k(top_k, crop_query=crop_final),
        )
    if precise_image:
        return _merge_search_hits(merged_hits, top_k)
    return _finalize_frame_hits(
        query_data,
        is_text,
        merged_hits,
        top_k,
        config,
        precise_image=False,
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
    if is_text or precise_image:
        return False
    return bool(get_frame_neighbor_rerank_enabled(config))


def _cap_hits_per_video(hits: List[SearchHit], cap: int) -> List[SearchHit]:
    if not hits or cap <= 0:
        return list(hits or [])
    buckets: dict[str, List[SearchHit]] = {}
    for hit in hits:
        path = str(hit.video_path or "")
        buckets.setdefault(path, []).append(hit)
    capped: List[SearchHit] = []
    for items in buckets.values():
        ordered = sorted(items, key=lambda item: float(item.score), reverse=True)
        capped.extend(ordered[: int(cap)])
    return sorted(capped, key=lambda item: float(item.score), reverse=True)


def _use_video_discovery_results(is_text: bool, precise_image: bool, scoped: bool) -> bool:
    return (not is_text) and (not precise_image) and (not scoped)


def _aggregate_hits_to_video_discovery(hits: List[SearchHit], top_k: int) -> List[SearchHit]:
    best: dict[str, SearchHit] = {}
    for hit in hits or []:
        path = str(hit.video_path or "").strip()
        if not path:
            continue
        current = best.get(path)
        if current is None or float(hit.score) > float(current.score):
            best[path] = hit
    ordered = sorted(best.values(), key=lambda item: float(item.score), reverse=True)
    limit = max(1, int(top_k))
    discovery: List[SearchHit] = []
    for hit in ordered[:limit]:
        preview_sec = float(hit.start_sec)
        if float(hit.end_sec) > float(hit.start_sec) + 0.5:
            preview_sec = (float(hit.start_sec) + float(hit.end_sec)) / 2.0
        discovery.append(
            SearchHit(
                preview_sec,
                preview_sec,
                float(hit.score),
                str(hit.video_path),
                match_kind="video",
            )
        )
    return discovery


def _apply_video_discovery_presentation(
    hits: List[SearchHit],
    top_k: int,
    *,
    enabled: bool,
) -> List[SearchHit]:
    if not enabled or not hits:
        return list(hits or [])
    diversified = _cap_hits_per_video(hits, _GLOBAL_PER_VIDEO_SEED_CAP)
    aggregated = _aggregate_hits_to_video_discovery(diversified, top_k)
    return aggregated or list(hits or [])


def _top_video_paths_from_hits(hits: List[SearchHit], limit: int) -> List[str]:
    best: dict[str, float] = {}
    for hit in hits or []:
        path = str(hit.video_path or "").strip()
        if not path:
            continue
        score = float(getattr(hit, "score", 0.0) or 0.0)
        prev = best.get(path)
        if prev is None or score > prev:
            best[path] = score
    ranked = sorted(best.items(), key=lambda item: (-item[1], item[0]))
    cap = max(1, int(limit))
    return [path for path, _ in ranked[:cap]]


def _locate_frames_in_recalled_videos(
    query_vector,
    stage1_hits: List[SearchHit],
    config,
    *,
    is_text=False,
    ensure_video_paths: Sequence[str] | None = None,
) -> List[SearchHit]:
    """Stage2: refine inside recalled videos without discarding stage1 seeds."""
    if is_text or not stage1_hits:
        return list(stage1_hits or [])
    diversified = _cap_hits_per_video(stage1_hits, _GLOBAL_PER_VIDEO_SEED_CAP)
    candidate_videos = _top_video_paths_from_hits(diversified, _GLOBAL_VIDEO_RECALL_LIMIT)
    if not candidate_videos:
        candidate_videos = _top_video_paths_from_hits(stage1_hits, _GLOBAL_VIDEO_RECALL_LIMIT)
    if ensure_video_paths:
        required = [
            abs_path
            for abs_path, _video_id in _resolve_scoped_video_targets(ensure_video_paths, config)
        ]
        merged: List[str] = []
        seen: set[str] = set()
        for path in list(required) + list(candidate_videos):
            key = str(path or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(key)
        candidate_videos = merged[: max(_GLOBAL_VIDEO_RECALL_LIMIT, len(required))]
    if not candidate_videos:
        return list(stage1_hits)
    stage1_by_video: dict[str, List[SearchHit]] = {}
    for hit in stage1_hits:
        key = normalize_scope_path(str(hit.video_path or ""))
        if not key:
            continue
        stage1_by_video.setdefault(key, []).append(hit)
    frame_hits: List[SearchHit] = []
    per_k = int(_GLOBAL_STAGE2_PER_VIDEO_K)
    processed_videos: set[str] = set()
    for abs_path, video_id in _resolve_scoped_video_targets(candidate_videos, config):
        path_key = normalize_scope_path(abs_path)
        processed_videos.add(path_key)
        stage1_video_hits = stage1_by_video.get(path_key, [])
        search_index, timestamps, video_paths, _vector_matrix = _load_per_video_frame_assets(video_id, abs_path, config)
        if search_index is None:
            frame_hits.extend(stage1_video_hits)
            continue
        _merge_search_index_steps(video_paths, timestamps)
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
            precise_image=True,
        )
        frame_hits.extend(_merge_search_hits(stage1_video_hits + matched_results, per_k))
    if not frame_hits:
        return list(stage1_hits)
    stage1_preserved = [
        hit
        for hit in stage1_hits
        if normalize_scope_path(str(hit.video_path or "")) not in processed_videos
    ]
    combined = frame_hits + stage1_preserved
    merge_limit = max(len(stage1_hits), per_k * len(candidate_videos))
    return _merge_search_hits(combined, merge_limit)


def _resolve_stage1_global_fetch_k(top_k: int, config) -> int:
    base = resolve_fetch_top_k(top_k, True)
    try:
        multiplier = int(config.get("image_search_fetch_multiplier", DEFAULT_CONFIG["image_search_fetch_multiplier"]))
    except (TypeError, ValueError):
        multiplier = int(DEFAULT_CONFIG["image_search_fetch_multiplier"])
    multiplier = max(1, min(multiplier, 8))
    expanded = max(base * multiplier, base + 15)
    return min(_GLOBAL_STAGE1_FETCH_CAP, expanded)


_IN_VIDEO_PIXEL_LOCALIZE_CAP = 15


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


def _reset_search_index_steps() -> None:
    reset_index_step_lookup()


def _merge_search_index_steps(video_paths, timestamps) -> None:
    if video_paths is None or timestamps is None:
        return
    merge_index_step_lookup(video_paths, timestamps)


def _finalize_frame_hits(
    query_data,
    is_text: bool,
    hits: List[SearchHit],
    top_k: int,
    config,
    precise_image: bool = False,
    pixel_query_data=None,
    seed_times: Sequence[float] | None = None,
) -> List[SearchHit]:
    if is_text or not precise_image:
        return _merge_search_hits(hits, top_k)
    return _refine_precise_seed_hits(
        query_data,
        hits,
        top_k,
        config,
        seed_times=seed_times,
        pixel_query_data=pixel_query_data,
    )


def _neighbor_rerank_window_sec(config, is_text: bool, precise_image: bool = False) -> float:
    cfg = config or {}
    if "frame_neighbor_rerank_window_sec" in cfg:
        try:
            return max(0.5, float(cfg["frame_neighbor_rerank_window_sec"]))
        except (TypeError, ValueError):
            pass
    if precise_image and not is_text:
        return 2.0
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


def _reconstruct_index_vector(search_index, candidate_id: int, cache: dict[int, np.ndarray]) -> np.ndarray | None:
    key = int(candidate_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        vector = np.asarray(search_index.reconstruct(key), dtype=np.float32).reshape(-1)
    except Exception:
        return None
    cache[key] = vector
    return vector


def _resolve_candidate_vector(
    search_index,
    candidate_id: int,
    cache: dict[int, np.ndarray],
    *,
    vector_matrix: np.ndarray | None = None,
) -> np.ndarray | None:
    key = int(candidate_id)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if vector_matrix is not None:
        try:
            if 0 <= key < int(vector_matrix.shape[0]):
                vector = np.asarray(vector_matrix[key], dtype=np.float32).reshape(-1)
                cache[key] = vector
                return vector
        except Exception:
            pass
    return _reconstruct_index_vector(search_index, key, cache)


def _neighbor_candidate_score(
    query: np.ndarray,
    search_index,
    candidate_id: int,
    vector_cache: dict[int, np.ndarray],
    score_cache: dict[int, float],
    *,
    vector_matrix: np.ndarray | None = None,
) -> float | None:
    key = int(candidate_id)
    if key in score_cache:
        return score_cache[key]
    candidate_vector = _resolve_candidate_vector(
        search_index,
        key,
        vector_cache,
        vector_matrix=vector_matrix,
    )
    if candidate_vector is None:
        return None
    score = float(np.dot(query, candidate_vector))
    score_cache[key] = score
    return score


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
    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
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
            score = _neighbor_candidate_score(
                query,
                search_index,
                int(candidate_id),
                vector_cache,
                score_cache,
            )
            if score is None:
                logger.debug(
                    "Neighbor rerank reconstruct failed for id=%s",
                    candidate_id,
                )
                continue
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
    vector_cache: dict[int, np.ndarray] = {}
    score_cache: dict[int, float] = {}
    for rank in range(max_top_n):
        base_id = frame_ids[rank]
        if base_id < 0 or base_id >= len(video_paths):
            continue
        base_path = str(video_paths[base_id])
        for candidate_id in _collect_neighbor_frame_ids(base_id, timestamps, video_paths, window_sec):
            if not _same_scope_video_path(video_paths[candidate_id], base_path):
                continue
            score = _neighbor_candidate_score(
                query,
                search_index,
                int(candidate_id),
                vector_cache,
                score_cache,
            )
            if score is None:
                logger.debug(
                    "Neighbor candidate reconstruct failed for id=%s",
                    candidate_id,
                )
                continue
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
    if precise_image:
        fetch_k = (
            _resolve_stage1_global_fetch_k(top_k, config)
            if not scoped
            else _resolve_frame_fetch_top_k(top_k, scoped, is_text=False, config=config, precise_image=True)
        )
    else:
        fetch_k = _resolve_chunk_precise_frame_fetch_k(top_k, scoped)
    neighbor_seed_n = _resolve_neighbor_seed_top_n(config, fetch_k, top_k, precise_image=precise_image)
    candidates: List[SearchHit] = []

    if scoped and scope_video_paths:
        per_k = resolve_per_video_fetch_top_k(fetch_k, len(scope_video_paths))
        per_seed_n = _resolve_neighbor_seed_top_n(config, per_k, top_k, precise_image=precise_image)
        for abs_path, video_id in _resolve_scoped_video_targets(scope_video_paths, config):
            search_index, timestamps, video_paths, _vector_matrix = _load_per_video_frame_assets(video_id, abs_path, config)
            if search_index is None:
                continue
            _merge_search_index_steps(video_paths, timestamps)
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
            _merge_search_index_steps(video_paths, timestamps)
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
        _merge_search_index_steps(video_paths, timestamps)
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
    start = float(chunk_start)
    end = float(chunk_end)
    if end <= start:
        end = start + 0.1
    return SearchHit(start, end, float(frame_hit.score), str(frame_hit.video_path))


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
    expanded = max(normalized * 6, normalized + 30)
    if scoped:
        expanded = max(expanded, normalized * 3 + 15)
    return min(200, expanded)


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
    if precise_image:
        frame_fetch_k = _resolve_frame_fetch_top_k(top_k, scoped, is_text=False, config=config, precise_image=True)
    else:
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
    if precise_image:
        return _finalize_frame_hits(
            query_data,
            is_text,
            frame_hits,
            top_k,
            config,
            precise_image=True,
            pixel_query_data=pixel_query_data,
        )
    with profile_phase("chunk_aggregate"):
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
    preview_anchor_sec: float | None = None,
    profile: bool | None = None,
    progress_callback=None,
) -> List[SearchHit]:
    config = load_config()
    precise_image = _use_precise_image_pipeline(is_text, config, search_precision_mode)
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
        return _run_search_impl(
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
        )
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
            )
            record_search_profile_result_count(len(results))
            return results
        if top_k is None:
            top_k = get_search_top_k(config)
        scoped = is_search_scoped(video_paths=scope_video_paths, library_paths=scope_library_paths)
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
                scoped_hits = _merge_search_hits(merged_hits, library_fetch_k)
            results = _finalize_frame_hits(
                query_data,
                is_text,
                scoped_hits,
                top_k,
                config,
                precise_image=precise_image,
                pixel_query_data=pixel_query_data,
            )
            record_search_profile_result_count(len(results))
            return results

        if precise_image:
            fetch_k = _resolve_stage1_global_fetch_k(top_k, config)
        elif _use_video_discovery_results(is_text, precise_image, scoped):
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
                scoped_hits = apply_search_scope(
                    matched_results,
                    video_paths=scope_video_paths,
                    library_paths=scope_library_paths,
                    top_k=top_k,
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
            results = _merge_search_hits(scoped_hits, top_k)
        if precise_image and scoped and scope_video_paths:
            from src.services.search_scope import filter_hits_by_video_paths

            results = filter_hits_by_video_paths(results, scope_video_paths)
            results = _merge_search_hits(results, top_k)
        results = _apply_video_discovery_presentation(
            results,
            top_k,
            enabled=_use_video_discovery_results(is_text, precise_image, scoped),
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
    profile: bool | None = None,
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
                enabled=_use_video_discovery_results(is_text, precise_image, scoped),
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
                actual_k = min(top_k, search_index.ntotal)
                if actual_k <= 0:
                    continue
                with profile_phase("faiss_search"):
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
            results = _merge_search_hits(merged_hits, top_k)
            record_search_profile_result_count(len(results))
            return results

        fetch_k = resolve_fetch_top_k(top_k, scoped)
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
        if getattr(query_vector, "ndim", 0) != 2 or query_vector.shape[0] <= 0:
            raise RuntimeError("Invalid query vector. Please retry the search.")
        query_dim = int(query_vector.shape[1])
        index_dim = int(getattr(search_index, "d", 0))
        if index_dim > 0 and query_dim != index_dim:
            raise RuntimeError(
                f"Search index dimension mismatch (query={query_dim}, index={index_dim}). "
                "Current model uses a different embedding space. Please rebuild the index for the active model."
            )

        with profile_phase("faiss_search"):
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
    config = load_config()
    get_engine()
    load_search_assets(config)
    load_chunk_search_assets(config)
