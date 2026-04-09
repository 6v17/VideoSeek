import os

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.indexing_service import (
    build_global_index,
    cleanup_missing_library_files,
    clear_global_index,
    scan_target_libraries,
)
from src.utils import get_video_hash, load_meta, save_meta

logger = get_logger("update_video")


def get_video_id(abs_path):
    return get_video_hash(abs_path)


def update_videos_flow(target_lib=None, progress_callback=None):
    logger.info("Starting index update%s", f" for {target_lib}" if target_lib else "")
    garbage_collect_indices()
    config = load_config()
    meta = load_meta(config["meta_file"])

    if progress_callback:
        progress_callback(5, "Cleaning stale index data")

    for video_id in cleanup_missing_library_files(meta, config, target_lib):
        delete_physical_video_data(video_id, config)

    all_vectors, all_timestamps, all_paths, all_chunk_vectors, all_chunk_ranges, all_chunk_paths = scan_target_libraries(
        meta,
        config,
        get_video_id,
        target_lib=target_lib,
        progress_callback=progress_callback,
    )

    save_meta(meta, config["meta_file"])
    if not any(len(lib.get("files", {})) > 0 for lib in meta["libraries"].values()):
        clear_global_index(config)
        logger.info("No libraries remain after cleanup; cleared global indexes")
        return None, None, None, None

    if not all_vectors:
        logger.warning("No valid videos found during indexing")
        clear_global_index(config)
        return None, None, None, None

    return build_global_index(
        all_vectors,
        all_timestamps,
        all_paths,
        all_chunk_vectors,
        all_chunk_ranges,
        all_chunk_paths,
        config,
        progress_callback=progress_callback,
    )


def merge_and_save_all_vectors(all_vectors, all_timestamps, all_paths, config):
    from src.services.indexing_service import merge_and_save_all_vectors as merge_vectors

    merge_vectors(all_vectors, all_timestamps, all_paths, config)


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
