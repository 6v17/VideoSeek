import gc
import os
import time

import numpy as np

from src.app.indexing_progress import IndexingProgressReporter, build_progress_token
from src.app.logging_utils import get_logger
from src.core.faiss_index import IncrementalClipIndex, atomic_save_numpy, create_clip_index, load_clip_index
from src.core.semantic_chunking import build_semantic_chunks, chunk_config_payload, unpack_chunks
from src.core.clip_embedding import generate_vectors_and_index_for_video
from src.core.extract_frames import FrameExtractionError
from src.core.timestamp_health import assess_index_timestamp_health
from src.storage.asset_store import load_vector_payload, save_vector_payload
from src.storage.config_store import (
    get_active_embedding_spec,
    get_chunk_similarity_mode,
    get_global_model_asset_paths,
    get_local_model_asset_dirs,
    get_max_chunk_duration,
    get_min_chunk_size,
    get_similarity_threshold,
)
from src.services.search_index_schema import (
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    clear_library_search_index,
    get_library_index_paths,
    get_search_index_schema_version,
    library_has_ready_videos,
    mark_search_index_schema_upgraded,
)
from src.utils import (
    canonicalize_library_path,
    ensure_folder_exists,
    get_legacy_video_hash,
    get_video_duration_seconds,
    get_video_hash,
    has_readable_video_stream,
)

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm")
logger = get_logger("indexing_service")


class IndexUpdateInterrupted(InterruptedError):
    def __init__(self, message, search_assets_changed=False):
        super().__init__(message)
        self.search_assets_changed = bool(search_assets_changed)


def _has_usable_vectors(vectors, timestamps):
    if vectors is None or timestamps is None:
        return False
    try:
        vector_count = len(vectors)
        timestamp_count = len(timestamps)
    except TypeError:
        return False
    return vector_count > 0 and vector_count == timestamp_count


def _get_debug_forced_failure():
    gpu_flag = str(os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM", "") or "").strip().lower()
    if gpu_flag in {"1", "true", "yes", "on"}:
        return RuntimeError("DirectML debug injection: GPU out of memory")

    system_flag = str(os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM", "") or "").strip().lower()
    if system_flag in {"1", "true", "yes", "on"}:
        return MemoryError("Debug injection: system out of memory")

    return None


def _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, asset_state, sync_failure_reason=""):
    previous = dict(lib_files.get(rel_path, {}))
    updated = dict(previous)
    updated["vid"] = video_id
    updated["mod_time"] = video_mod_time
    updated["asset_state"] = asset_state
    if asset_state == "sync_failed":
        updated["sync_failure_reason"] = str(sync_failure_reason or "").strip().lower() or "processing_error"
    else:
        updated.pop("sync_failure_reason", None)
    if updated == previous:
        return False
    lib_files[rel_path] = updated
    return True


def _exception_detail(exc):
    if exc is None:
        return ""
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _classify_exception_failure_reason(exc):
    detail = _exception_detail(exc).lower()
    if not detail:
        return "processing_error"

    oom_markers = (
        "out of memory",
        "not enough memory",
        "insufficient memory",
        "cannot allocate memory",
        "failed to allocate memory",
        "bad alloc",
        "bad_alloc",
        "memoryerror",
    )
    if not any(marker in detail for marker in oom_markers):
        return "processing_error"

    gpu_markers = (
        "gpu",
        "directml",
        "dml",
        "directx",
        "d3d12",
        "cuda",
        "vram",
        "video memory",
        "graphics memory",
    )
    if any(marker in detail for marker in gpu_markers):
        return "gpu_out_of_memory"
    return "system_out_of_memory"


def _classify_sync_failure_reason(abs_path, vectors, timestamps, exc=None):
    if exc is not None:
        if isinstance(exc, FrameExtractionError):
            if exc.frame_count > 0:
                return "processing_error"
            duration = get_video_duration_seconds(abs_path)
            if duration is not None and float(duration) < 1.0:
                return "too_short"
            return "no_frames"
        return _classify_exception_failure_reason(exc)
    if vectors is None or timestamps is None:
        duration = get_video_duration_seconds(abs_path)
        if duration is not None and float(duration) < 1.0:
            return "too_short"
        return "no_frames"
    if len(vectors) == 0 or len(timestamps) == 0:
        duration = get_video_duration_seconds(abs_path)
        if duration is not None and float(duration) < 1.0:
            return "too_short"
        return "no_frames"
    return "vector_timestamp_mismatch"


def _emit_issue(issue_callback, library_path, video_rel_path, abs_path, action, reason, detail=""):
    if not callable(issue_callback):
        return
    issue_callback(
        {
            "library_path": library_path,
            "video_rel_path": video_rel_path,
            "abs_path": abs_path,
            "action": str(action or "").strip().lower(),
            "reason": str(reason or "").strip().lower(),
            "detail": str(detail or "").strip(),
        }
    )


def _ensure_video_index_file(video_id, vectors, config, *, force=False):
    model_dirs = get_local_model_asset_dirs(config=config)
    index_file = os.path.join(model_dirs["index_dir"], f"{video_id}_index.faiss")
    if os.path.exists(index_file) and not force:
        return False
    try:
        create_clip_index(vectors, index_file)
        logger.info("Rebuilt per-video index for %s (force=%s)", video_id, bool(force))
        return True
    except Exception as exc:
        logger.warning("Failed to rebuild per-video index for %s: %s", video_id, exc)
        return False


def _per_video_asset_paths(vector_dir, index_dir, video_id):
    return {
        "vectors": os.path.join(vector_dir, f"{video_id}_vectors.npy"),
        "index": os.path.join(index_dir, f"{video_id}_index.faiss"),
    }


def _rename_per_video_assets(vector_dir, index_dir, old_vid, new_vid):
    if not old_vid or not new_vid or old_vid == new_vid:
        return
    for key, folder, suffix in (
        ("vectors", vector_dir, "_vectors.npy"),
        ("index", index_dir, "_index.faiss"),
    ):
        src = os.path.join(folder, f"{old_vid}{suffix}")
        dst = os.path.join(folder, f"{new_vid}{suffix}")
        if os.path.isfile(src) and not os.path.isfile(dst):
            os.replace(src, dst)


def _load_vectors_from_disk(video_id, config):
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_file = os.path.join(model_dirs["vector_dir"], f"{video_id}_vectors.npy")
    if not os.path.isfile(vector_file):
        return None, None, vector_file
    try:
        data = load_vector_payload(vector_file)
    except Exception as exc:
        logger.warning("Unreadable cached vectors for %s: %s", video_id, exc)
        return None, None, vector_file
    if isinstance(data, dict):
        vectors = data.get("vector")
        timestamps = data.get("timestamps")
        if vectors is not None and timestamps is not None:
            _ensure_chunk_payload(data, vectors, timestamps, vector_file, config)
        return vectors, timestamps, vector_file
    return None, None, vector_file


def _resolve_reusable_cached_vectors(abs_path, saved, config):
    """Find on-disk vectors for this file even when meta vid or mtime no longer match current hash."""
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_dir = model_dirs["vector_dir"]
    index_dir = model_dirs["index_dir"]
    try:
        current_vid = get_video_hash(abs_path)
    except OSError:
        return None

    saved_vid = str(saved.get("vid", "") or "").strip()
    candidate_ids = []
    for vid in (current_vid, saved_vid):
        if vid and vid not in candidate_ids:
            candidate_ids.append(vid)
    try:
        legacy_vid = get_legacy_video_hash(abs_path)
    except OSError:
        legacy_vid = ""
    if legacy_vid and legacy_vid not in candidate_ids:
        candidate_ids.append(legacy_vid)

    for disk_vid in candidate_ids:
        vectors, timestamps, _vector_file = _load_vectors_from_disk(disk_vid, config)
        if not _has_usable_vectors(vectors, timestamps):
            continue
        canonical_vid = current_vid
        if disk_vid != canonical_vid:
            paths = _per_video_asset_paths(vector_dir, index_dir, canonical_vid)
            if os.path.isfile(paths["vectors"]):
                vectors, timestamps, _ = _load_vectors_from_disk(canonical_vid, config)
                if not _has_usable_vectors(vectors, timestamps):
                    continue
            else:
                try:
                    _rename_per_video_assets(vector_dir, index_dir, disk_vid, canonical_vid)
                except OSError as exc:
                    logger.warning(
                        "Cannot align cached asset id %s -> %s for %s: %s",
                        disk_vid,
                        canonical_vid,
                        abs_path,
                        exc,
                    )
                    continue
        return {
            "canonical_vid": canonical_vid,
            "disk_vid": disk_vid,
            "vectors": vectors,
            "timestamps": timestamps,
        }
    return None


def load_video_vectors_by_id(video_id, config):
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_file = os.path.join(model_dirs["vector_dir"], f"{video_id}_vectors.npy")
    data = load_vector_payload(vector_file)
    if isinstance(data, dict):
        vectors = data.get("vector")
        timestamps = data.get("timestamps")
        if vectors is not None and timestamps is not None:
            _ensure_chunk_payload(data, vectors, timestamps, vector_file, config)
        return vectors, timestamps
    return None, None


def load_video_chunks_by_id(video_id, config):
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_file = os.path.join(model_dirs["vector_dir"], f"{video_id}_vectors.npy")
    data = load_vector_payload(vector_file)
    if not isinstance(data, dict):
        return []

    vectors = data.get("vector")
    timestamps = data.get("timestamps")
    if vectors is None or timestamps is None:
        return []

    return _ensure_chunk_payload(data, vectors, timestamps, vector_file, config)


def _ensure_chunk_payload(data, vectors, timestamps, vector_file, config):
    current_chunk_config = chunk_config_payload(
        similarity_threshold=get_similarity_threshold(config),
        max_chunk_duration=get_max_chunk_duration(config),
        min_chunk_size=get_min_chunk_size(config),
        similarity_mode=get_chunk_similarity_mode(config),
    )
    saved_chunk_config = data.get("chunk_config")
    chunks = unpack_chunks(data.get("chunks"))
    if chunks and saved_chunk_config == current_chunk_config:
        return chunks

    logger.info("Rebuilding chunk payload from existing frame vectors: %s", os.path.basename(vector_file))
    chunks = build_semantic_chunks(
        vectors,
        timestamps,
        similarity_threshold=current_chunk_config["similarity_threshold"],
        max_chunk_duration=current_chunk_config["max_chunk_duration"],
        min_chunk_size=current_chunk_config["min_chunk_size"],
        similarity_mode=current_chunk_config["similarity_mode"],
    )
    save_vector_payload(
        vectors,
        timestamps,
        vector_file,
        chunks=chunks,
        chunk_config=current_chunk_config,
        embedding_spec=get_active_embedding_spec(config=config),
    )
    return chunks


def _selected_missing_entry_keys(selected_entries):
    keys = set()
    for entry in selected_entries or []:
        library_path = str(entry.get("library_path", "")).strip()
        video_rel_path = str(entry.get("video_rel_path", "")).strip()
        if not library_path or not video_rel_path:
            continue
        keys.add((canonicalize_library_path(library_path), video_rel_path))
    return keys


def cleanup_missing_library_files(meta, config, target_lib=None, selected_entries=None):
    selected_keys = _selected_missing_entry_keys(selected_entries)
    for entry in list_missing_library_files(meta, config, target_lib):
        if selected_keys:
            entry_key = (
                canonicalize_library_path(entry["library_path"]),
                entry["video_rel_path"],
            )
            if entry_key not in selected_keys:
                continue
        lib_files = meta["libraries"][entry["library_path"]].get("files", {})
        rel_path = entry["video_rel_path"]
        if rel_path in lib_files:
            yield lib_files[rel_path].get("vid")
            del lib_files[rel_path]


def list_missing_library_files(meta, config, target_lib=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in list(meta["libraries"].items()):
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            logger.info("Skipping missing-file cleanup for offline library root: %s", root_path)
            continue

        lib_files = lib_data.get("files", {})
        for rel_path in list(lib_files.keys()):
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                yield {
                    "library_path": root_path,
                    "video_rel_path": rel_path,
                    "abs_path": abs_path,
                    "video_id": lib_files[rel_path].get("vid"),
                }


def collect_existing_vectors(meta, config, target_lib=None):
    all_vectors, all_timestamps, all_paths = [], [], []
    target_key = canonicalize_library_path(target_lib) if target_lib else None

    for root_path, lib_data in meta["libraries"].items():
        if target_key and canonicalize_library_path(root_path) == target_key:
            continue

        for rel_path, info in lib_data.get("files", {}).items():
            vectors, timestamps = load_video_vectors_by_id(info["vid"], config)
            if vectors is None:
                continue
            all_vectors.append(vectors)
            all_timestamps.extend(timestamps)
            all_paths.extend([os.path.join(root_path, rel_path)] * len(timestamps))

    return all_vectors, all_timestamps, all_paths


def _library_roots_for_global_merge(meta, target_lib=None, include_all_libraries=True):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in meta.get("libraries", {}).items():
        if not include_all_libraries and target_key and canonicalize_library_path(root_path) != target_key:
            continue
        yield root_path, lib_data


def iter_ready_library_frame_sources(meta, config, target_lib=None, include_all_libraries=True):
    """Yield per-video frame vectors from on-disk payloads (one video in memory at a time)."""
    for root_path, lib_data in _library_roots_for_global_merge(meta, target_lib, include_all_libraries):
        if not os.path.exists(root_path):
            continue
        lib_files = lib_data.get("files", {})
        for rel_path, info in lib_files.items():
            if str(info.get("asset_state", "")).strip().lower() != "ready":
                continue
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                continue
            video_id = info.get("vid")
            if not video_id:
                continue
            vectors, timestamps = load_video_vectors_by_id(video_id, config)
            if not _has_usable_vectors(vectors, timestamps):
                continue
            yield np.asarray(vectors, dtype=np.float32), timestamps, abs_path


def iter_ready_library_chunk_sources(meta, config, target_lib=None, include_all_libraries=True):
    for root_path, lib_data in _library_roots_for_global_merge(meta, target_lib, include_all_libraries):
        if not os.path.exists(root_path):
            continue
        for rel_path, info in lib_data.get("files", {}).items():
            if str(info.get("asset_state", "")).strip().lower() != "ready":
                continue
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                continue
            video_id = info.get("vid")
            if not video_id:
                continue
            chunks = load_video_chunks_by_id(video_id, config)
            if not chunks:
                continue
            for chunk in chunks:
                yield np.asarray(chunk["embedding"], dtype=np.float32), (float(chunk["start"]), float(chunk["end"])), abs_path


def count_searchable_frame_sources(meta, config, target_lib=None, include_all_libraries=True):
    total = 0
    for _vectors, timestamps, _abs_path in iter_ready_library_frame_sources(
        meta, config, target_lib=target_lib, include_all_libraries=include_all_libraries
    ):
        total += len(timestamps)
    return total


def collect_existing_chunks(meta, config, target_lib=None):
    all_chunk_vectors, all_chunk_ranges, all_chunk_paths = [], [], []
    target_key = canonicalize_library_path(target_lib) if target_lib else None

    for root_path, lib_data in meta["libraries"].items():
        if target_key and canonicalize_library_path(root_path) == target_key:
            continue

        for rel_path, info in lib_data.get("files", {}).items():
            chunks = load_video_chunks_by_id(info["vid"], config)
            if not chunks:
                continue
            abs_path = os.path.join(root_path, rel_path)
            for chunk in chunks:
                all_chunk_vectors.append(chunk["embedding"])
                all_chunk_ranges.append((chunk["start"], chunk["end"]))
                all_chunk_paths.append(abs_path)

    return all_chunk_vectors, all_chunk_ranges, all_chunk_paths


def discover_video_files(root_path):
    valid_files = []
    for current_root, dir_names, files in os.walk(root_path):
        dir_names[:] = [name for name in dir_names if name.lower() != "__macosx"]
        for filename in files:
            if filename.lower().endswith(VIDEO_EXTS):
                valid_files.append(os.path.join(current_root, filename))
    return valid_files


def _is_excluded_video_path(abs_path):
    normalized_parts = [part.lower() for part in os.path.normpath(abs_path).split(os.sep)]
    return "__macosx" in normalized_parts


def _is_valid_video_source(abs_path):
    if _is_excluded_video_path(abs_path):
        return False
    return has_readable_video_stream(abs_path)


def cleanup_invalid_library_files(meta, config, target_lib=None, issue_callback=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in list(meta["libraries"].items()):
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue

        lib_files = lib_data.get("files", {})
        for rel_path in list(lib_files.keys()):
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                continue
            if _is_valid_video_source(abs_path):
                continue

            video_id = lib_files[rel_path].get("vid")
            del lib_files[rel_path]
            logger.warning("Removed invalid video source from library metadata: %s", abs_path)
            _emit_issue(
                issue_callback,
                root_path,
                rel_path,
                abs_path,
                action="cleaned",
                reason="invalid_video_source",
            )
            yield video_id


def process_single_video(
    abs_path,
    rel_path,
    lib_files,
    config,
    get_video_id,
    library_path=None,
    issue_callback=None,
    should_stop_callback=None,
    progress_callback=None,
    file_index=1,
    file_total=1,
):
    video_name = os.path.basename(abs_path)
    progress_reporter = (
        IndexingProgressReporter(
            progress_callback,
            video_name=video_name,
            file_index=file_index,
            file_total=file_total,
        )
        if progress_callback
        else None
    )
    try:
        if progress_reporter is not None:
            progress_reporter.emit("file", file_index, file_total, force=True)

        video_mod_time = os.path.getmtime(abs_path)
        if not _is_valid_video_source(abs_path):
            logger.warning("Skipping non-indexable video source: %s", abs_path)
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="skipped",
                reason="invalid_video_source",
                detail="Unreadable or unsupported video stream.",
            )
            return None, None, False, False

        saved = lib_files.get(rel_path, {})
        forced_failure = _get_debug_forced_failure()
        if forced_failure is not None:
            raise forced_failure

        cached = _resolve_reusable_cached_vectors(abs_path, saved, config)
        if cached is not None:
            video_id = cached["canonical_vid"]
            vectors = cached["vectors"]
            timestamps = cached["timestamps"]
            disk_vid = cached["disk_vid"]
            t_reuse = time.perf_counter()
            _ensure_video_index_file(video_id, vectors, config)
            metadata_updated = _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, "ready")
            if progress_reporter is not None:
                progress_reporter.emit("reuse", force=True)
            reuse_s = time.perf_counter() - t_reuse
            if disk_vid != video_id:
                logger.info(
                    "Per-video %s: reuse_cached_vectors aligned id %s -> %s in %.2fs (%d frames)",
                    os.path.basename(abs_path),
                    disk_vid,
                    video_id,
                    reuse_s,
                    len(timestamps),
                )
            else:
                logger.info(
                    "Per-video %s: reuse_cached_vectors %.2fs (%d frames)",
                    os.path.basename(abs_path),
                    reuse_s,
                    len(timestamps),
                )
            return vectors, timestamps, metadata_updated, False

        video_id = get_video_hash(abs_path)
        saved_vid = str(saved.get("vid", "") or "").strip()
        logger.info(
            "Reindexing %s (no reusable on-disk cache: saved_vid=%s current_vid=%s)",
            os.path.basename(abs_path),
            saved_vid or "-",
            video_id,
        )
        logger.info("Indexing video %s", os.path.basename(abs_path))
        model_dirs = get_local_model_asset_dirs(config=config)
        os.makedirs(model_dirs["vector_dir"], exist_ok=True)
        os.makedirs(model_dirs["index_dir"], exist_ok=True)
        t_gen = time.perf_counter()
        vectors, timestamps, _ = generate_vectors_and_index_for_video(
            abs_path,
            video_id,
            model_dirs["index_dir"],
            model_dirs["vector_dir"],
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
            file_index=file_index,
            file_total=file_total,
        )
        gen_s = time.perf_counter() - t_gen
        logger.info(
            "Per-video %s: generate_vectors_and_index_for_video wall %.2fs",
            os.path.basename(abs_path),
            gen_s,
        )
        if not _has_usable_vectors(vectors, timestamps):
            failure_reason = _classify_sync_failure_reason(abs_path, vectors, timestamps)
            metadata_updated = _upsert_file_record(
                lib_files,
                rel_path,
                video_id,
                video_mod_time,
                "sync_failed",
                sync_failure_reason=failure_reason,
            )
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="skipped",
                reason=failure_reason,
            )
            if vectors is None or timestamps is None:
                logger.warning("Vector generation failed for %s and the file was marked sync_failed", abs_path)
            elif len(vectors) == 0 or len(timestamps) == 0:
                logger.warning("Vector generation returned empty data for %s and the file was marked sync_failed", abs_path)
            else:
                logger.warning(
                    "Vector/timestamp counts differ for %s; marked sync_failed: vectors=%s timestamps=%s",
                    abs_path,
                    len(vectors),
                    len(timestamps),
                )
            return None, None, metadata_updated, bool(saved.get("vid"))
        metadata_updated = _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, "ready")
        health = assess_index_timestamp_health(abs_path, timestamps, config=config)
        if health.get("warnings"):
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="warning",
                reason="timestamp_drift",
                detail=health.get("detail", ""),
            )
        return vectors, timestamps, metadata_updated, True
    except InterruptedError:
        raise
    except Exception as exc:
        logger.exception("Failed to process video %s", abs_path)
        metadata_updated = False
        search_assets_changed = False
        try:
            saved = dict(lib_files.get(rel_path, {}))
            video_id = get_video_id(abs_path)
            video_mod_time = os.path.getmtime(abs_path)
            failure_reason = _classify_sync_failure_reason(abs_path, None, None, exc=exc)
            metadata_updated = _upsert_file_record(
                lib_files,
                rel_path,
                video_id,
                video_mod_time,
                "sync_failed",
                sync_failure_reason=failure_reason,
            )
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="skipped",
                reason=failure_reason,
                detail=_exception_detail(exc),
            )
            search_assets_changed = bool(saved.get("vid"))
        except Exception:
            pass
        return None, None, metadata_updated, search_assets_changed


def scan_target_libraries(
    meta,
    config,
    get_video_id,
    target_lib=None,
    progress_callback=None,
    persist_meta_callback=None,
    should_stop_callback=None,
    issue_callback=None,
    include_existing_assets=True,
):
    search_assets_changed = False
    for video_id in list(cleanup_invalid_library_files(meta, config, target_lib, issue_callback=issue_callback)):
        if video_id:
            search_assets_changed = True
            model_dirs = get_local_model_asset_dirs(config=config)
            vector_dir = model_dirs.get("vector_dir", "")
            index_dir = model_dirs.get("index_dir", "")
            vector_file = os.path.join(vector_dir, f"{video_id}_vectors.npy") if vector_dir else ""
            index_file = os.path.join(index_dir, f"{video_id}_index.faiss") if index_dir else ""
            for path in (vector_file, index_file):
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        logger.warning("Failed to remove invalid video asset %s", path)
        if persist_meta_callback:
            persist_meta_callback()

    failed_videos = []
    libraries = list(meta["libraries"].items())
    library_count = len(libraries)
    target_key = canonicalize_library_path(target_lib) if target_lib else None

    for index, (root_path, lib_data) in enumerate(libraries):
        if should_stop_callback and should_stop_callback():
            raise IndexUpdateInterrupted(
                "Index update stopped before finishing library scan",
                search_assets_changed=search_assets_changed,
            )
        if progress_callback and library_count:
            progress_callback(int((index / library_count) * 100), f"Scanning {os.path.basename(root_path)}")

        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue

        lib_files = lib_data.get("files", {})
        valid_files = discover_video_files(root_path)
        file_total = len(valid_files)

        for file_index, abs_path in enumerate(valid_files, start=1):
            if should_stop_callback and should_stop_callback():
                raise IndexUpdateInterrupted(
                    "Index update stopped before finishing current library",
                    search_assets_changed=search_assets_changed,
                )
            rel_path = os.path.relpath(abs_path, root_path)

            vectors, timestamps, metadata_updated, file_search_assets_changed = process_single_video(
                abs_path,
                rel_path,
                lib_files,
                config,
                get_video_id,
                library_path=root_path,
                issue_callback=issue_callback,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
                file_index=file_index,
                file_total=file_total,
            )
            search_assets_changed = search_assets_changed or file_search_assets_changed
            if metadata_updated and persist_meta_callback:
                persist_meta_callback()
            if vectors is None:
                failed_videos.append(abs_path)

        lib_data["files"] = lib_files

    return failed_videos, search_assets_changed


def _count_meta_video_entries(meta, target_lib=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    total = 0
    for root_path, lib_data in (meta.get("libraries") or {}).items():
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue
        total += len(lib_data.get("files") or {})
    return max(total, 1)


def rebuild_indexes_from_cached_vectors(
    meta,
    config,
    *,
    target_lib=None,
    rebuild_per_video=True,
    rebuild_global=True,
    force_per_video=False,
    include_all_libraries=True,
    progress_callback=None,
    should_stop_callback=None,
):
    """Rebuild FAISS indexes from on-disk vectors without FFmpeg or embedding."""
    from src.app.indexing_progress import build_progress_token

    stats = {
        "per_video_rebuilt": 0,
        "per_video_skipped": 0,
        "per_video_failed": 0,
        "per_video_no_vectors": 0,
        "videos_with_vectors": 0,
        "global_built": False,
    }
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    file_total = _count_meta_video_entries(meta, target_lib=target_lib)
    file_index = 0

    if progress_callback:
        progress_callback(2, build_progress_token(stage="rebuild_index", file_index=0, file_total=file_total))

    for root_path, lib_data in (meta.get("libraries") or {}).items():
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue

        lib_files = lib_data.get("files", {})
        for rel_path, info in list(lib_files.items()):
            if should_stop_callback and should_stop_callback():
                raise InterruptedError("Index rebuild from vectors stopped")
            file_index += 1
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.isfile(abs_path):
                stats["per_video_no_vectors"] += 1
                continue

            saved = dict(info)
            cached = _resolve_reusable_cached_vectors(abs_path, saved, config)
            if cached is None:
                saved_vid = str(saved.get("vid", "") or "").strip()
                if saved_vid:
                    vectors, timestamps, _ = _load_vectors_from_disk(saved_vid, config)
                    if _has_usable_vectors(vectors, timestamps):
                        cached = {
                            "canonical_vid": saved_vid,
                            "disk_vid": saved_vid,
                            "vectors": vectors,
                            "timestamps": timestamps,
                        }
            if cached is None:
                stats["per_video_no_vectors"] += 1
                if progress_callback:
                    progress_callback(
                        min(89, int(90 * file_index / file_total)),
                        build_progress_token(
                            stage="rebuild_index",
                            video_name=os.path.basename(abs_path),
                            file_index=file_index,
                            file_total=file_total,
                        ),
                    )
                continue

            stats["videos_with_vectors"] += 1
            video_id = cached["canonical_vid"]
            vectors = cached["vectors"]
            if str(info.get("vid", "") or "").strip() != video_id:
                info["vid"] = video_id
            if str(info.get("asset_state", "") or "").strip().lower() != "ready":
                info["asset_state"] = "ready"

            if rebuild_per_video:
                if _ensure_video_index_file(video_id, vectors, config, force=force_per_video):
                    stats["per_video_rebuilt"] += 1
                else:
                    index_file = os.path.join(
                        get_local_model_asset_dirs(config=config)["index_dir"],
                        f"{video_id}_index.faiss",
                    )
                    if os.path.isfile(index_file):
                        stats["per_video_skipped"] += 1
                    else:
                        stats["per_video_failed"] += 1

            if progress_callback:
                progress_callback(
                    min(89, int(90 * file_index / file_total)),
                    build_progress_token(
                        stage="rebuild_index",
                        video_name=os.path.basename(abs_path),
                        file_index=file_index,
                        file_total=file_total,
                    ),
                )

    if rebuild_global:
        if progress_callback:
            progress_callback(92, build_progress_token(stage="global"))
        result = build_global_index(
            meta,
            config,
            target_lib=target_lib,
            include_all_libraries=include_all_libraries,
            progress_callback=progress_callback,
            should_stop_callback=should_stop_callback,
        )
        stats["global_built"] = result is not None

    if get_search_index_schema_version(meta) >= TARGET_SEARCH_INDEX_SCHEMA_VERSION:
        library_stats = build_library_search_indexes(
            meta,
            config,
            target_lib=target_lib,
            progress_callback=progress_callback,
            should_stop_callback=should_stop_callback,
        )
        stats.update(library_stats)

    if progress_callback:
        progress_callback(100, build_progress_token(stage="rebuild_index", file_index=file_total, file_total=file_total))

    logger.info(
        "Rebuild indexes from cached vectors finished: videos_with_vectors=%s per_video_rebuilt=%s "
        "per_video_skipped=%s per_video_failed=%s per_video_no_vectors=%s global_built=%s",
        stats["videos_with_vectors"],
        stats["per_video_rebuilt"],
        stats["per_video_skipped"],
        stats["per_video_failed"],
        stats["per_video_no_vectors"],
        stats["global_built"],
    )
    return stats


def clear_global_index(config):
    global_paths = get_global_model_asset_paths(config=config)
    for path in [
        global_paths["cross_index_file"],
        global_paths["cross_vector_file"],
        global_paths["cross_chunk_index_file"],
        global_paths["cross_chunk_vector_file"],
    ]:
        if os.path.exists(path):
            os.remove(path)


def merge_and_save_all_vectors(all_vectors, all_timestamps, all_paths, config):
    global_paths = get_global_model_asset_paths(config=config)
    ensure_folder_exists(global_paths["cross_index_file"])
    ensure_folder_exists(global_paths["cross_vector_file"])

    create_clip_index(all_vectors, global_paths["cross_index_file"])
    payload = {
        "format_version": 2,
        "timestamps": np.asarray(all_timestamps, dtype="float32"),
        "paths": all_paths,
        "embedding_spec": get_active_embedding_spec(config=config),
    }
    atomic_save_numpy(global_paths["cross_vector_file"], payload)


def merge_and_save_all_chunks(all_chunk_vectors, all_chunk_ranges, all_chunk_paths, config):
    global_paths = get_global_model_asset_paths(config=config)
    ensure_folder_exists(global_paths["cross_chunk_index_file"])
    ensure_folder_exists(global_paths["cross_chunk_vector_file"])

    create_clip_index(all_chunk_vectors, global_paths["cross_chunk_index_file"])
    payload = {
        "format_version": 2,
        "ranges": np.asarray(all_chunk_ranges, dtype="float32"),
        "paths": all_chunk_paths,
        "embedding_spec": get_active_embedding_spec(config=config),
    }
    atomic_save_numpy(global_paths["cross_chunk_vector_file"], payload)


def _save_global_frame_metadata(all_timestamps, all_paths, config):
    global_paths = get_global_model_asset_paths(config=config)
    ensure_folder_exists(global_paths["cross_vector_file"])
    payload = {
        "format_version": 2,
        "timestamps": np.asarray(all_timestamps, dtype="float32"),
        "paths": all_paths,
        "embedding_spec": get_active_embedding_spec(config=config),
    }
    atomic_save_numpy(global_paths["cross_vector_file"], payload)


def _save_global_chunk_metadata(all_chunk_ranges, all_chunk_paths, config):
    global_paths = get_global_model_asset_paths(config=config)
    ensure_folder_exists(global_paths["cross_chunk_vector_file"])
    payload = {
        "format_version": 2,
        "ranges": np.asarray(all_chunk_ranges, dtype="float32"),
        "paths": all_chunk_paths,
        "embedding_spec": get_active_embedding_spec(config=config),
    }
    atomic_save_numpy(global_paths["cross_chunk_vector_file"], payload)


def build_global_index(
    meta,
    config,
    target_lib=None,
    include_all_libraries=True,
    progress_callback=None,
    should_stop_callback=None,
):
    """Merge per-video on-disk vectors into cross-library search assets without vstacking the whole library."""
    wall_start = time.perf_counter()
    if progress_callback:
        progress_callback(
            95,
            build_progress_token(stage="global"),
        )

    global_paths = get_global_model_asset_paths(config=config)
    ensure_folder_exists(global_paths["cross_index_file"])
    ensure_folder_exists(global_paths["cross_vector_file"])

    frame_builder = IncrementalClipIndex()
    all_timestamps = []
    all_paths = []
    videos_merged = 0

    t_frame = time.perf_counter()
    for vectors, timestamps, abs_path in iter_ready_library_frame_sources(
        meta,
        config,
        target_lib=target_lib,
        include_all_libraries=include_all_libraries,
    ):
        if should_stop_callback and should_stop_callback():
            raise InterruptedError("Index update stopped during global index build")
        frame_builder.add(vectors)
        ts_list = np.asarray(timestamps, dtype="float32").reshape(-1).tolist()
        all_paths.extend([abs_path] * len(ts_list))
        all_timestamps.extend(ts_list)
        videos_merged += 1
        del vectors
        gc.collect()

    if frame_builder.total <= 0:
        clear_global_index(config)
        logger.warning("No searchable frame vectors found while building global index")
        return None

    logger.info(
        "Building global frame index with %s frame vectors from %s videos",
        frame_builder.total,
        videos_merged,
    )
    frame_builder.save(global_paths["cross_index_file"])
    _save_global_frame_metadata(all_timestamps, all_paths, config)
    frame_stage_s = time.perf_counter() - t_frame
    logger.info("Global index: frame incremental merge+save %.2fs", frame_stage_s)

    chunk_builder = IncrementalClipIndex()
    all_chunk_ranges = []
    all_chunk_paths = []
    chunk_stage_s = 0.0
    t_chunk = time.perf_counter()
    for embedding, chunk_range, abs_path in iter_ready_library_chunk_sources(
        meta,
        config,
        target_lib=target_lib,
        include_all_libraries=include_all_libraries,
    ):
        if should_stop_callback and should_stop_callback():
            raise InterruptedError("Index update stopped during global chunk index build")
        chunk_builder.add(embedding.reshape(1, -1))
        all_chunk_ranges.append(chunk_range)
        all_chunk_paths.append(abs_path)

    if chunk_builder.total > 0:
        ensure_folder_exists(global_paths["cross_chunk_index_file"])
        ensure_folder_exists(global_paths["cross_chunk_vector_file"])
        logger.info("Building global chunk index with %s chunks", chunk_builder.total)
        chunk_builder.save(global_paths["cross_chunk_index_file"])
        _save_global_chunk_metadata(all_chunk_ranges, all_chunk_paths, config)
        chunk_stage_s = time.perf_counter() - t_chunk
        logger.info("Global index: chunk incremental merge+save %.2fs", chunk_stage_s)
    else:
        for path in (global_paths["cross_chunk_index_file"], global_paths["cross_chunk_vector_file"]):
            if path and os.path.exists(path):
                os.remove(path)

    gc.collect()
    t_load = time.perf_counter()
    index = load_clip_index(global_paths["cross_index_file"])
    load_s = time.perf_counter() - t_load
    timestamp_array = np.asarray(all_timestamps, dtype="float32")
    parts_s = frame_stage_s + chunk_stage_s + load_s
    logger.info(
        "Global index: load_cross_index %.2fs | parts_sum=%.2fs wall_total=%.2fs",
        load_s,
        parts_s,
        time.perf_counter() - wall_start,
    )
    return timestamp_array, np.array(all_paths), index


def _clear_library_search_index(library_path: str, config) -> None:
    clear_library_search_index(library_path, config=config)


def _save_library_frame_assets(library_path: str, timestamps, paths, config, frame_builder: IncrementalClipIndex) -> None:
    asset_paths = get_library_index_paths(library_path, config=config)
    ensure_folder_exists(asset_paths["frame_index_file"])
    frame_builder.save(asset_paths["frame_index_file"])
    payload = {
        "format_version": 2,
        "timestamps": np.asarray(timestamps, dtype="float32"),
        "paths": paths,
        "embedding_spec": get_active_embedding_spec(config=config),
        "library_path": canonicalize_library_path(library_path),
    }
    atomic_save_numpy(asset_paths["frame_vector_file"], payload)


def _save_library_chunk_assets(library_path: str, chunk_ranges, chunk_paths, config, chunk_builder: IncrementalClipIndex) -> None:
    asset_paths = get_library_index_paths(library_path, config=config)
    ensure_folder_exists(asset_paths["chunk_index_file"])
    chunk_builder.save(asset_paths["chunk_index_file"])
    payload = {
        "format_version": 2,
        "ranges": np.asarray(chunk_ranges, dtype="float32"),
        "paths": chunk_paths,
        "embedding_spec": get_active_embedding_spec(config=config),
        "library_path": canonicalize_library_path(library_path),
    }
    atomic_save_numpy(asset_paths["chunk_vector_file"], payload)


def build_library_search_indexes(
    meta,
    config,
    target_lib=None,
    progress_callback=None,
    should_stop_callback=None,
) -> dict:
    """Build v2 per-library FAISS assets from cached per-video vectors."""
    stats = {"libraries_built": 0, "libraries_cleared": 0, "libraries_skipped": 0}
    libraries = list(_library_roots_for_global_merge(meta, target_lib, include_all_libraries=True))
    total = len(libraries)

    for index, (root_path, _lib_data) in enumerate(libraries, start=1):
        if should_stop_callback and should_stop_callback():
            raise InterruptedError("Search index upgrade stopped during library index build")
        if progress_callback and total:
            progress_callback(
                min(88, int(85 * index / total)),
                build_progress_token(stage="upgrade_index", file_index=index, file_total=total),
            )
        if not os.path.exists(root_path):
            stats["libraries_skipped"] += 1
            continue

        frame_builder = IncrementalClipIndex()
        all_timestamps = []
        all_paths = []
        for vectors, timestamps, abs_path in iter_ready_library_frame_sources(
            meta,
            config,
            target_lib=root_path,
            include_all_libraries=False,
        ):
            if should_stop_callback and should_stop_callback():
                raise InterruptedError("Search index upgrade stopped during library index build")
            frame_builder.add(vectors)
            ts_list = np.asarray(timestamps, dtype="float32").reshape(-1).tolist()
            all_paths.extend([abs_path] * len(ts_list))
            all_timestamps.extend(ts_list)

        if frame_builder.total <= 0:
            _clear_library_search_index(root_path, config)
            stats["libraries_cleared"] += 1
            continue

        _save_library_frame_assets(root_path, all_timestamps, all_paths, config, frame_builder)

        chunk_builder = IncrementalClipIndex()
        all_chunk_ranges = []
        all_chunk_paths = []
        for embedding, chunk_range, abs_path in iter_ready_library_chunk_sources(
            meta,
            config,
            target_lib=root_path,
            include_all_libraries=False,
        ):
            if should_stop_callback and should_stop_callback():
                raise InterruptedError("Search index upgrade stopped during library index build")
            chunk_builder.add(embedding.reshape(1, -1))
            all_chunk_ranges.append(chunk_range)
            all_chunk_paths.append(abs_path)

        if chunk_builder.total > 0:
            _save_library_chunk_assets(root_path, all_chunk_ranges, all_chunk_paths, config, chunk_builder)
        else:
            asset_paths = get_library_index_paths(root_path, config=config)
            for key in ("chunk_index_file", "chunk_vector_file"):
                path = asset_paths.get(key)
                if path and os.path.exists(path):
                    os.remove(path)

        stats["libraries_built"] += 1
        logger.info(
            "Built library search index for %s (%s frame vectors, %s chunks)",
            root_path,
            frame_builder.total,
            chunk_builder.total,
        )

    mark_search_index_schema_upgraded(meta, target_lib=target_lib)
    if progress_callback:
        progress_callback(90, build_progress_token(stage="upgrade_index", file_index=total, file_total=total))
    logger.info(
        "Library search index build finished: built=%s cleared=%s skipped=%s schema=%s",
        stats["libraries_built"],
        stats["libraries_cleared"],
        stats["libraries_skipped"],
        TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    )
    return stats

