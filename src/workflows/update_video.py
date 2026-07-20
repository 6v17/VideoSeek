import os
import time

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.indexing_service import (
    IndexUpdateInterrupted,
    cleanup_missing_library_files,
    scan_target_libraries,
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


def _has_ready_search_assets(meta):
    for library in (meta or {}).get("libraries", {}).values():
        for info in library.get("files", {}).values():
            if str(info.get("asset_state", "")).strip().lower() == "ready":
                return True
    return False


def update_videos_flow(
    target_lib=None,
    progress_callback=None,
    force_cleanup_missing_files=False,
    should_stop_callback=None,
    cleanup_missing_entries=None,
    issue_callback=None,
    include_existing_assets=True,
    rebuild_global_assets=True,
    video_ids=None,
):
    # Retained intentionally: imported dynamically inside IndexUpdateWorker.run().
    del rebuild_global_assets
    flow_start = time.perf_counter()
    selected_note = ""
    if video_ids is not None:
        selected_note = f" video_ids={len({str(v).strip() for v in video_ids if str(v or '').strip()})}"
    logger.info(
        "Starting index update%s%s",
        f" for {target_lib}" if target_lib else "",
        selected_note,
    )
    garbage_collect_indices()
    config = load_config()
    meta = load_model_metadata(config=config)

    should_cleanup_missing_files = force_cleanup_missing_files or config.get("auto_cleanup_missing_files", False)

    t_cleanup = time.perf_counter()
    if should_cleanup_missing_files:
        if progress_callback:
            progress_callback(5, "Cleaning stale index source")
        removed_any = False
        from src.services.library_service import count_video_id_refs

        for video_id in cleanup_missing_library_files(
            meta,
            config,
            target_lib,
            selected_entries=cleanup_missing_entries,
        ):
            removed_any = True
            # cleanup_missing already removed the file row; only wipe payload when
            # no other library still references this video_id.
            if count_video_id_refs(meta, video_id) == 0:
                delete_physical_video_data(video_id, config)
            else:
                logger.info(
                    "Keeping shared index payload after missing-file cleanup for video_id=%s",
                    video_id,
                )
        if removed_any:
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
            persist_meta_callback=lambda: save_model_metadata(
                meta,
                config=config,
                pretty=False,
                invalidate_path_index=False,
            ),
            should_stop_callback=should_stop_callback,
            issue_callback=issue_callback,
            include_existing_assets=include_existing_assets,
            video_ids=video_ids,
        )
    except IndexUpdateInterrupted as exc:
        scan_s = time.perf_counter() - t_scan
        logger.info(
            "Index update interrupted: cleanup=%.2fs scan_libraries=%.2fs total=%.2fs",
            cleanup_s,
            scan_s,
            time.perf_counter() - flow_start,
        )
        save_model_metadata(meta, config=config)
        raise
    scan_s = time.perf_counter() - t_scan
    failed_videos, _scan_search_assets_changed = scan_result

    if should_stop_callback and should_stop_callback():
        save_model_metadata(meta, config=config)
        logger.info(
            "Index update stopped after library scan: cleanup=%.2fs scan_libraries=%.2fs total=%.2fs",
            cleanup_s,
            scan_s,
            time.perf_counter() - flow_start,
        )
        raise InterruptedError("Index update stopped before finalizing library state")

    if failed_videos:
        logger.warning(
            "Index update skipped %s videos because vectors were not generated successfully: %s",
            len(failed_videos),
            failed_videos,
        )

    # Finalize in memory, then one pretty meta write (+ path-index invalidate).
    _mark_missing_source_entries(meta, target_lib=target_lib)
    _finalize_library_index_state(meta, target_lib=target_lib)
    save_model_metadata(meta, config=config)
    try:
        # Artifact cleanup only — avoid maintain_library_metadata() reloading/rewriting meta.
        from src.services.library_service import prune_legacy_search_index_artifacts
        from src.storage.config_store import get_local_model_asset_dirs
        from src.storage.lance_store import drop_lance_vector_indexes

        drop_lance_vector_indexes(get_local_model_asset_dirs(config=config)["base_dir"])
        prune_legacy_search_index_artifacts(meta, config=config)
    except Exception as exc:
        logger.warning("Post-index library artifact cleanup failed: %s", exc)
    has_search_assets = _has_ready_search_assets(meta)
    logger.info(
        "Index update complete: cleanup=%.2fs scan_libraries=%.2fs has_search_assets=%s total=%.2fs",
        cleanup_s,
        scan_s,
        has_search_assets,
        time.perf_counter() - flow_start,
    )
    return (True, None, None, None) if has_search_assets else (None, None, None, None)


def upgrade_search_index_flow(
    target_lib=None,
    progress_callback=None,
    should_stop_callback=None,
    *,
    rebuild_global=True,
):
    """Legacy FAISS per-library indexes are no longer built; Lance stores search vectors."""
    del target_lib, progress_callback, should_stop_callback, rebuild_global
    logger.info("Search index schema upgrade skipped: Lance vector storage is active.")
    return {
        "global_built": False,
        "libraries_built": 0,
        "libraries_cleared": 0,
        "libraries_skipped": 0,
    }


def delete_physical_video_data(video_id, config, *, refresh_lance_state: bool = True):
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

    try:
        from src.storage.lance_store import delete_profile_video_vectors

        delete_profile_video_vectors(
            video_id,
            config=config,
            refresh_state=bool(refresh_lance_state),
        )
    except Exception as exc:
        logger.warning("Failed to remove Lance vectors for %s: %s", video_id, exc)


def garbage_collect_indices():
    from src.storage.video_id_migration import legacy_npy_vectors_present

    config = load_config()
    if not legacy_npy_vectors_present(config):
        return

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
