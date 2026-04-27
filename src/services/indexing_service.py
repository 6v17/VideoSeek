import gc
import os

import numpy as np

from src.app.logging_utils import get_logger
from src.core.faiss_index import atomic_save_numpy, create_clip_index, load_clip_index, load_vectors, save_vectors
from src.core.semantic_chunking import build_semantic_chunks, chunk_config_payload, unpack_chunks
from src.core.clip_embedding import generate_vectors_and_index_for_video
from src.utils import canonicalize_library_path, ensure_folder_exists, get_video_duration_seconds, has_readable_video_stream

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


def _ensure_video_index_file(video_id, vectors, config):
    index_file = os.path.join(config["index_dir"], f"{video_id}_index.faiss")
    if os.path.exists(index_file):
        return False
    try:
        create_clip_index(vectors, index_file)
        logger.info("Rebuilt missing per-video index for %s", video_id)
        return True
    except Exception as exc:
        logger.warning("Failed to rebuild missing per-video index for %s: %s", video_id, exc)
        return False


def load_video_vectors_by_id(video_id, config):
    vector_file = os.path.join(config["vector_dir"], f"{video_id}_vectors.npy")
    data = load_vectors(vector_file)
    if isinstance(data, dict):
        vectors = data.get("vector")
        timestamps = data.get("timestamps")
        if vectors is not None and timestamps is not None:
            _ensure_chunk_payload(data, vectors, timestamps, vector_file, config)
        return vectors, timestamps
    return None, None


def load_video_chunks_by_id(video_id, config):
    vector_file = os.path.join(config["vector_dir"], f"{video_id}_vectors.npy")
    data = load_vectors(vector_file)
    if not isinstance(data, dict):
        return []

    vectors = data.get("vector")
    timestamps = data.get("timestamps")
    if vectors is None or timestamps is None:
        return []

    return _ensure_chunk_payload(data, vectors, timestamps, vector_file, config)


def _ensure_chunk_payload(data, vectors, timestamps, vector_file, config):
    current_chunk_config = chunk_config_payload(
        similarity_threshold=config.get("similarity_threshold", 0.85),
        max_chunk_duration=config.get("max_chunk_duration", 5.0),
        min_chunk_size=config.get("min_chunk_size", 2),
        similarity_mode=config.get("chunk_similarity_mode", "chunk"),
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
    save_vectors(vectors, timestamps, vector_file, chunks=chunks, chunk_config=current_chunk_config)
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


def process_single_video(abs_path, rel_path, lib_files, config, get_video_id, library_path=None, issue_callback=None):
    try:
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

        video_id = get_video_id(abs_path)
        saved = lib_files.get(rel_path, {})
        forced_failure = _get_debug_forced_failure()
        if forced_failure is not None:
            raise forced_failure

        if saved.get("vid") == video_id and saved.get("mod_time") == video_mod_time:
            vectors, timestamps = load_video_vectors_by_id(video_id, config)
            if _has_usable_vectors(vectors, timestamps):
                _ensure_video_index_file(video_id, vectors, config)
                metadata_updated = _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, "ready")
                logger.info("Reusing existing frame vectors for %s", os.path.basename(abs_path))
                return vectors, timestamps, metadata_updated, False

        logger.info("Indexing video %s", os.path.basename(abs_path))
        vectors, timestamps, _ = generate_vectors_and_index_for_video(
            abs_path, video_id, config["index_dir"], config["vector_dir"]
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
        return vectors, timestamps, metadata_updated, True
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
            vector_dir = config.get("vector_dir", "")
            index_dir = config.get("index_dir", "")
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

    if include_existing_assets:
        all_vectors, all_timestamps, all_paths = collect_existing_vectors(meta, config, target_lib)
        all_chunk_vectors, all_chunk_ranges, all_chunk_paths = collect_existing_chunks(meta, config, target_lib)
    else:
        all_vectors, all_timestamps, all_paths = [], [], []
        all_chunk_vectors, all_chunk_ranges, all_chunk_paths = [], [], []
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

        for file_index, abs_path in enumerate(valid_files):
            if should_stop_callback and should_stop_callback():
                raise IndexUpdateInterrupted(
                    "Index update stopped before finishing current library",
                    search_assets_changed=search_assets_changed,
                )
            rel_path = os.path.relpath(abs_path, root_path)
            if progress_callback and valid_files:
                progress_callback(int((file_index / len(valid_files)) * 100), f"Processing {os.path.basename(abs_path)}")

            vectors, timestamps, metadata_updated, file_search_assets_changed = process_single_video(
                abs_path,
                rel_path,
                lib_files,
                config,
                get_video_id,
                library_path=root_path,
                issue_callback=issue_callback,
            )
            search_assets_changed = search_assets_changed or file_search_assets_changed
            if metadata_updated and persist_meta_callback:
                persist_meta_callback()
            if vectors is None:
                failed_videos.append(abs_path)
                continue
            all_vectors.append(vectors)
            all_timestamps.extend(timestamps)
            all_paths.extend([abs_path] * len(timestamps))
            for chunk in load_video_chunks_by_id(get_video_id(abs_path), config):
                all_chunk_vectors.append(chunk["embedding"])
                all_chunk_ranges.append((chunk["start"], chunk["end"]))
                all_chunk_paths.append(abs_path)

        lib_data["files"] = lib_files

    return (
        all_vectors,
        all_timestamps,
        all_paths,
        all_chunk_vectors,
        all_chunk_ranges,
        all_chunk_paths,
        failed_videos,
        search_assets_changed,
    )


def clear_global_index(config):
    for path in [
        config["cross_index_file"],
        config["cross_vector_file"],
        config["cross_chunk_index_file"],
        config["cross_chunk_vector_file"],
    ]:
        if os.path.exists(path):
            os.remove(path)


def merge_and_save_all_vectors(all_vectors, all_timestamps, all_paths, config):
    ensure_folder_exists(config["cross_index_file"])
    ensure_folder_exists(config["cross_vector_file"])

    create_clip_index(all_vectors, config["cross_index_file"])
    payload = {
        "format_version": 2,
        "timestamps": all_timestamps,
        "paths": all_paths,
    }
    atomic_save_numpy(config["cross_vector_file"], payload)


def merge_and_save_all_chunks(all_chunk_vectors, all_chunk_ranges, all_chunk_paths, config):
    ensure_folder_exists(config["cross_chunk_index_file"])
    ensure_folder_exists(config["cross_chunk_vector_file"])

    create_clip_index(all_chunk_vectors, config["cross_chunk_index_file"])
    payload = {
        "format_version": 2,
        "ranges": np.asarray(all_chunk_ranges, dtype="float32"),
        "paths": all_chunk_paths,
    }
    atomic_save_numpy(config["cross_chunk_vector_file"], payload)


def build_global_index(
    all_vectors,
    all_timestamps,
    all_paths,
    all_chunk_vectors,
    all_chunk_ranges,
    all_chunk_paths,
    config,
    progress_callback=None,
):
    if progress_callback:
        progress_callback(95, "Building global index")
    logger.info("Building global frame index with %s frame vectors", len(all_paths))

    vector_stack = np.vstack(all_vectors).astype("float32")
    timestamp_array = np.array(all_timestamps).astype("float32")
    merge_and_save_all_vectors(vector_stack, timestamp_array, all_paths, config)
    if all_chunk_vectors:
        logger.info("Building global chunk index with %s chunks", len(all_chunk_paths))
        chunk_vector_stack = np.vstack(all_chunk_vectors).astype("float32")
        merge_and_save_all_chunks(chunk_vector_stack, all_chunk_ranges, all_chunk_paths, config)
    gc.collect()
    return vector_stack, timestamp_array, np.array(all_paths), load_clip_index(config["cross_index_file"])
