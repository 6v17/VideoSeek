import os

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.indexing_service import (
    build_global_index,
    cleanup_missing_library_files,
    clear_global_index,
    scan_target_libraries,
)
from src.utils import canonicalize_library_path, get_video_hash, load_meta, save_meta

logger = get_logger("update_video")


def get_video_id(abs_path):
    return get_video_hash(abs_path)


def _iter_target_library_paths(meta, target_lib=None, include_offline=False):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path in list(meta.get("libraries", {}).keys()):
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if include_offline or os.path.exists(root_path):
            yield root_path


def _set_library_index_state(meta, state, target_lib=None, include_offline=False):
    for root_path in _iter_target_library_paths(meta, target_lib=target_lib, include_offline=include_offline):
        library = meta["libraries"].setdefault(root_path, {})
        library["index_state"] = state


def _finalize_library_index_state(meta, target_lib=None):
    for root_path in _iter_target_library_paths(meta, target_lib=target_lib, include_offline=True):
        library = meta["libraries"].get(root_path, {})
        if not os.path.exists(root_path):
            continue
        has_files = bool(library.get("files", {}))
        library["index_state"] = "ready" if has_files else "pending"


def _mark_missing_source_entries(meta, target_lib=None):
    changed = False
    for root_path in _iter_target_library_paths(meta, target_lib=target_lib, include_offline=False):
        library = meta["libraries"].get(root_path, {})
        for rel_path, info in library.get("files", {}).items():
            abs_path = os.path.join(root_path, rel_path)
            if os.path.exists(abs_path):
                continue
            if info.get("asset_state") == "missing_source":
                continue
            info["asset_state"] = "missing_source"
            changed = True
    return changed


def update_videos_flow(
    target_lib=None,
    progress_callback=None,
    force_cleanup_missing_files=False,
    should_stop_callback=None,
):
    # Retained intentionally: imported dynamically inside IndexUpdateWorker.run().
    logger.info("Starting index update%s", f" for {target_lib}" if target_lib else "")
    garbage_collect_indices()
    config = load_config()
    meta = load_meta(config["meta_file"])
    meta_file = config["meta_file"]
    _set_library_index_state(meta, "partial", target_lib=target_lib)
    save_meta(meta, meta_file)

    should_cleanup_missing_files = force_cleanup_missing_files or config.get("auto_cleanup_missing_files", False)

    if should_cleanup_missing_files:
        if progress_callback:
            progress_callback(5, "Cleaning stale index source")
        removed_any = False
        for video_id in cleanup_missing_library_files(meta, config, target_lib):
            removed_any = True
            delete_physical_video_data(video_id, config)
        if removed_any:
            save_meta(meta, meta_file)
    else:
        if progress_callback:
            progress_callback(5, "Keeping vectors for offline or missing files")
        logger.info("Automatic cleanup for missing files is disabled; keeping cached vectors and indexes")

    scan_result = scan_target_libraries(
        meta,
        config,
        get_video_id,
        target_lib=target_lib,
        progress_callback=progress_callback,
        persist_meta_callback=lambda: save_meta(meta, meta_file),
        should_stop_callback=should_stop_callback,
    )
    if len(scan_result) == 7:
        (
            all_vectors,
            all_timestamps,
            all_paths,
            all_chunk_vectors,
            all_chunk_ranges,
            all_chunk_paths,
            failed_videos,
        ) = scan_result
    else:
        (
            all_vectors,
            all_timestamps,
            all_paths,
            all_chunk_vectors,
            all_chunk_ranges,
            all_chunk_paths,
        ) = scan_result
        failed_videos = []

    if should_stop_callback and should_stop_callback():
        raise InterruptedError("Index update stopped before rebuilding global index")

    if failed_videos:
        logger.warning(
            "Index update skipped %s videos because vectors were not generated successfully: %s",
            len(failed_videos),
            failed_videos,
        )

    if _mark_missing_source_entries(meta, target_lib=target_lib):
        save_meta(meta, meta_file)

    save_meta(meta, meta_file)
    if not any(len(lib.get("files", {})) > 0 for lib in meta["libraries"].values()):
        _finalize_library_index_state(meta, target_lib=target_lib)
        save_meta(meta, meta_file)
        clear_global_index(config)
        logger.info("No libraries remain after cleanup; cleared global indexes")
        return None, None, None, None

    if not all_vectors:
        _finalize_library_index_state(meta, target_lib=target_lib)
        save_meta(meta, meta_file)
        logger.warning("No valid videos found during indexing")
        clear_global_index(config)
        return None, None, None, None

    result = build_global_index(
        all_vectors,
        all_timestamps,
        all_paths,
        all_chunk_vectors,
        all_chunk_ranges,
        all_chunk_paths,
        config,
        progress_callback=progress_callback,
    )
    _finalize_library_index_state(meta, target_lib=target_lib)
    save_meta(meta, meta_file)
    return result

def delete_physical_video_data(video_id, config):
    if not video_id:
        return

    vector_file = os.path.join(config["vector_dir"], f"{video_id}_vectors.npy")
    index_file = os.path.join(config["index_dir"], f"{video_id}_index.faiss")

    try:
        if os.path.exists(vector_file):
            os.remove(vector_file)
            logger.info("Removed vector file for %s", video_id)
        if os.path.exists(index_file):
            os.remove(index_file)
            logger.info("Removed index file for %s", video_id)
    except Exception as exc:
        logger.error("Failed to remove files for %s: %s", video_id, exc)


def garbage_collect_indices():
    config = load_config()
    meta = load_meta(config["meta_file"])

    valid_ids = set()
    for library in meta["libraries"].values():
        for info in library.get("files", {}).values():
            if info.get("vid"):
                valid_ids.add(info["vid"])

    for folder in [config["vector_dir"], config["index_dir"]]:
        if not os.path.exists(folder):
            continue
        for filename in os.listdir(folder):
            video_id = filename.split("_")[0]
            if video_id not in valid_ids and len(video_id) > 10:
                try:
                    os.remove(os.path.join(folder, filename))
                    logger.info("Removed orphan file %s", filename)
                except OSError:
                    pass
