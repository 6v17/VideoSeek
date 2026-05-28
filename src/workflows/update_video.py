import os
import time

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.indexing_service import (
    IndexUpdateInterrupted,
    build_global_index,
    build_library_search_indexes,
    cleanup_missing_library_files,
    clear_global_index,
    rebuild_indexes_from_cached_vectors,
    scan_target_libraries,
)
from src.services.library_service import mark_global_index_fresh, mark_global_index_stale
from src.services.search_index_schema import (
    TARGET_SEARCH_INDEX_SCHEMA_VERSION,
    get_search_index_schema_version,
)
from src.storage.asset_store import load_model_metadata, save_model_metadata
from src.storage.config_store import get_local_model_asset_dirs
from src.utils import canonicalize_library_path, get_video_hash

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
    cleanup_missing_entries=None,
    issue_callback=None,
    include_existing_assets=True,
    rebuild_global_assets=True,
):
    # Retained intentionally: imported dynamically inside IndexUpdateWorker.run().
    flow_start = time.perf_counter()
    logger.info("Starting index update%s", f" for {target_lib}" if target_lib else "")
    garbage_collect_indices()
    config = load_config()
    meta = load_model_metadata(config=config)
    _set_library_index_state(meta, "partial", target_lib=target_lib)
    save_model_metadata(meta, config=config)

    should_cleanup_missing_files = force_cleanup_missing_files or config.get("auto_cleanup_missing_files", False)
    search_assets_changed = False

    t_cleanup = time.perf_counter()
    if should_cleanup_missing_files:
        if progress_callback:
            progress_callback(5, "Cleaning stale index source")
        removed_any = False
        for video_id in cleanup_missing_library_files(
            meta,
            config,
            target_lib,
            selected_entries=cleanup_missing_entries,
        ):
            removed_any = True
            delete_physical_video_data(video_id, config)
        if removed_any:
            search_assets_changed = True
            save_model_metadata(meta, config=config)
    else:
        if progress_callback:
            progress_callback(5, "Keeping vectors for offline or missing files")
        logger.info("Automatic cleanup for missing files is disabled; keeping cached vectors and indexes")
    cleanup_s = time.perf_counter() - t_cleanup

    t_scan = time.perf_counter()
    try:
        scan_result = scan_target_libraries(
            meta,
            config,
            get_video_id,
            target_lib=target_lib,
            progress_callback=progress_callback,
            persist_meta_callback=lambda: save_model_metadata(meta, config=config),
            should_stop_callback=should_stop_callback,
            issue_callback=issue_callback,
            include_existing_assets=include_existing_assets,
        )
    except IndexUpdateInterrupted as exc:
        scan_s = time.perf_counter() - t_scan
        logger.info(
            "Index update interrupted: cleanup=%.2fs scan_libraries=%.2fs total=%.2fs",
            cleanup_s,
            scan_s,
            time.perf_counter() - flow_start,
        )
        if getattr(exc, "search_assets_changed", False):
            mark_global_index_stale(meta=meta)
            save_model_metadata(meta, config=config)
        raise
    scan_s = time.perf_counter() - t_scan
    failed_videos, scan_search_assets_changed = scan_result
    search_assets_changed = search_assets_changed or scan_search_assets_changed

    if should_stop_callback and should_stop_callback():
        if search_assets_changed:
            mark_global_index_stale(meta=meta)
            save_model_metadata(meta, config=config)
        logger.info(
            "Index update stopped before global rebuild: cleanup=%.2fs scan_libraries=%.2fs total=%.2fs",
            cleanup_s,
            scan_s,
            time.perf_counter() - flow_start,
        )
        raise InterruptedError("Index update stopped before rebuilding global index")

    if failed_videos:
        logger.warning(
            "Index update skipped %s videos because vectors were not generated successfully: %s",
            len(failed_videos),
            failed_videos,
        )

    if _mark_missing_source_entries(meta, target_lib=target_lib):
        save_model_metadata(meta, config=config)

    save_model_metadata(meta, config=config)
    if not any(len(lib.get("files", {})) > 0 for lib in meta["libraries"].values()):
        _finalize_library_index_state(meta, target_lib=target_lib)
        if rebuild_global_assets:
            mark_global_index_fresh(meta=meta)
        elif search_assets_changed:
            mark_global_index_stale(meta=meta)
        save_model_metadata(meta, config=config)
        if rebuild_global_assets:
            clear_global_index(config)
            logger.info("No libraries remain after cleanup; cleared global indexes")
        logger.info(
            "Index update finished (no libraries): cleanup=%.2fs scan_libraries=%.2fs global_build=n/a total=%.2fs",
            cleanup_s,
            scan_s,
            time.perf_counter() - flow_start,
        )
        return None, None, None, None

    if not rebuild_global_assets:
        _finalize_library_index_state(meta, target_lib=target_lib)
        if search_assets_changed:
            mark_global_index_stale(meta=meta)
        if (
            target_lib
            and get_search_index_schema_version(meta) >= TARGET_SEARCH_INDEX_SCHEMA_VERSION
        ):
            build_library_search_indexes(
                meta,
                config,
                target_lib=target_lib,
                progress_callback=progress_callback,
                should_stop_callback=should_stop_callback,
            )
        save_model_metadata(meta, config=config)
        logger.info(
            "Skipped global index rebuild (rebuild_global_assets=False).",
        )
        logger.info(
            "Index update finished (skip global): cleanup=%.2fs scan_libraries=%.2fs global_build=n/a total=%.2fs",
            cleanup_s,
            scan_s,
            time.perf_counter() - flow_start,
        )
        return None, None, None, None

    t_global = time.perf_counter()
    result = build_global_index(
        meta,
        config,
        target_lib=target_lib,
        include_all_libraries=include_existing_assets,
        progress_callback=progress_callback,
        should_stop_callback=should_stop_callback,
    )
    global_s = time.perf_counter() - t_global
    if result is None:
        _finalize_library_index_state(meta, target_lib=target_lib)
        if rebuild_global_assets:
            mark_global_index_fresh(meta=meta)
        elif search_assets_changed:
            mark_global_index_stale(meta=meta)
        save_model_metadata(meta, config=config)
        logger.warning("No valid videos found during indexing")
        logger.info(
            "Index update finished (no vectors): cleanup=%.2fs scan_libraries=%.2fs global_build=%.2fs total=%.2fs",
            cleanup_s,
            scan_s,
            global_s,
            time.perf_counter() - flow_start,
        )
        return None, None, None, None
    _finalize_library_index_state(meta, target_lib=target_lib)
    mark_global_index_fresh(meta=meta)
    if get_search_index_schema_version(meta) >= TARGET_SEARCH_INDEX_SCHEMA_VERSION:
        build_library_search_indexes(
            meta,
            config,
            target_lib=target_lib,
            progress_callback=progress_callback,
            should_stop_callback=should_stop_callback,
        )
    save_model_metadata(meta, config=config)
    logger.info(
        "Index update complete: cleanup=%.2fs scan_libraries=%.2fs global_build=%.2fs total=%.2fs",
        cleanup_s,
        scan_s,
        global_s,
        time.perf_counter() - flow_start,
    )
    return result

def rebuild_indexes_from_vectors_flow(
    target_lib=None,
    progress_callback=None,
    should_stop_callback=None,
    *,
    rebuild_per_video=True,
    rebuild_global=True,
    force_per_video=False,
    include_all_libraries=True,
):
    """Rebuild per-video and/or global FAISS assets from existing vector files only."""
    flow_start = time.perf_counter()
    logger.info(
        "Starting index rebuild from cached vectors%s",
        f" for {target_lib}" if target_lib else "",
    )
    config = load_config()
    meta = load_model_metadata(config=config)
    _set_library_index_state(meta, "partial", target_lib=target_lib)
    save_model_metadata(meta, config=config)

    stats = rebuild_indexes_from_cached_vectors(
        meta,
        config,
        target_lib=target_lib,
        rebuild_per_video=rebuild_per_video,
        rebuild_global=rebuild_global,
        force_per_video=force_per_video,
        include_all_libraries=include_all_libraries,
        progress_callback=progress_callback,
        should_stop_callback=should_stop_callback,
    )

    _finalize_library_index_state(meta, target_lib=target_lib)
    if rebuild_global:
        if stats.get("global_built"):
            mark_global_index_fresh(meta=meta)
        else:
            mark_global_index_stale(meta=meta)
    save_model_metadata(meta, config=config)

    logger.info(
        "Index rebuild from vectors finished in %.2fs: %s",
        time.perf_counter() - flow_start,
        stats,
    )
    return stats


def upgrade_search_index_flow(
    target_lib=None,
    progress_callback=None,
    should_stop_callback=None,
    *,
    rebuild_global=True,
):
    """Upgrade to v2 per-library search indexes from cached vectors (no re-embedding)."""
    flow_start = time.perf_counter()
    logger.info(
        "Starting search index schema upgrade%s",
        f" for {target_lib}" if target_lib else "",
    )
    config = load_config()
    meta = load_model_metadata(config=config)
    _set_library_index_state(meta, "partial", target_lib=target_lib)
    save_model_metadata(meta, config=config)

    stats = build_library_search_indexes(
        meta,
        config,
        target_lib=target_lib,
        progress_callback=progress_callback,
        should_stop_callback=should_stop_callback,
    )
    global_built = False
    if rebuild_global:
        if progress_callback:
            progress_callback(92, "global")
        result = build_global_index(
            meta,
            config,
            target_lib=target_lib,
            include_all_libraries=True,
            progress_callback=progress_callback,
            should_stop_callback=should_stop_callback,
        )
        global_built = result is not None

    _finalize_library_index_state(meta, target_lib=target_lib)
    if rebuild_global and global_built:
        mark_global_index_fresh(meta=meta)
    save_model_metadata(meta, config=config)

    logger.info(
        "Search index schema upgrade finished in %.2fs: %s global_built=%s",
        time.perf_counter() - flow_start,
        stats,
        global_built,
    )
    return {"global_built": global_built, **stats}


def delete_physical_video_data(video_id, config):
    if not video_id:
        return

    model_dirs = get_local_model_asset_dirs(config=config)
    vector_file = os.path.join(model_dirs["vector_dir"], f"{video_id}_vectors.npy")
    index_file = os.path.join(model_dirs["index_dir"], f"{video_id}_index.faiss")

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
    meta = load_model_metadata(config=config)

    valid_ids = set()
    for library in meta["libraries"].values():
        for info in library.get("files", {}).values():
            if info.get("vid"):
                valid_ids.add(info["vid"])

    model_dirs = get_local_model_asset_dirs(config=config)
    for folder in [model_dirs["vector_dir"], model_dirs["index_dir"]]:
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
