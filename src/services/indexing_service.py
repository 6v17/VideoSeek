import gc
import os

import numpy as np

from src.core.clip_embedding import generate_vectors_and_index_for_video
from src.core.faiss_index import create_clip_index, load_clip_index, load_vectors
from src.utils import canonicalize_library_path, ensure_folder_exists

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm")


def load_video_vectors_by_id(video_id, config):
    vector_file = os.path.join(config["vector_dir"], f"{video_id}_vectors.npy")
    data = load_vectors(vector_file)
    if isinstance(data, dict):
        return data.get("vector"), data.get("timestamps")
    return None, None


def cleanup_missing_library_files(meta, config, target_lib=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in list(meta["libraries"].items()):
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue

        lib_files = lib_data.get("files", {})
        for rel_path in list(lib_files.keys()):
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                yield lib_files[rel_path].get("vid")
                del lib_files[rel_path]


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


def discover_video_files(root_path):
    valid_files = []
    for current_root, _, files in os.walk(root_path):
        for filename in files:
            if filename.lower().endswith(VIDEO_EXTS):
                valid_files.append(os.path.join(current_root, filename))
    return valid_files


def process_single_video(abs_path, rel_path, lib_files, config, get_video_id):
    try:
        video_id = get_video_id(abs_path)
        video_mod_time = os.path.getmtime(abs_path)
        saved = lib_files.get(rel_path, {})

        if saved.get("vid") == video_id and saved.get("mod_time") == video_mod_time:
            vectors, timestamps = load_video_vectors_by_id(video_id, config)
            if vectors is not None:
                return vectors, timestamps

        print(f"[Indexing] {os.path.basename(abs_path)}")
        vectors, timestamps, _ = generate_vectors_and_index_for_video(
            abs_path, video_id, config["index_dir"], config["vector_dir"]
        )
        lib_files[rel_path] = {"vid": video_id, "mod_time": video_mod_time}
        return vectors, timestamps
    except Exception as exc:
        print(f"Failed to process video {abs_path}: {exc}")
        return None, None


def scan_target_libraries(meta, config, get_video_id, target_lib=None, progress_callback=None):
    all_vectors, all_timestamps, all_paths = collect_existing_vectors(meta, config, target_lib)
    libraries = list(meta["libraries"].items())
    library_count = len(libraries)
    target_key = canonicalize_library_path(target_lib) if target_lib else None

    for index, (root_path, lib_data) in enumerate(libraries):
        if progress_callback and library_count:
            progress_callback(int((index / library_count) * 100), f"Scanning {os.path.basename(root_path)}")

        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue

        lib_files = lib_data.get("files", {})
        valid_files = discover_video_files(root_path)

        for file_index, abs_path in enumerate(valid_files):
            rel_path = os.path.relpath(abs_path, root_path)
            if progress_callback and valid_files:
                progress_callback(int((file_index / len(valid_files)) * 100), f"Processing {os.path.basename(abs_path)}")

            vectors, timestamps = process_single_video(abs_path, rel_path, lib_files, config, get_video_id)
            if vectors is None:
                continue
            all_vectors.append(vectors)
            all_timestamps.extend(timestamps)
            all_paths.extend([abs_path] * len(timestamps))

        lib_data["files"] = lib_files

    return all_vectors, all_timestamps, all_paths


def clear_global_index(config):
    for path in [config["cross_index_file"], config["cross_vector_file"]]:
        if os.path.exists(path):
            os.remove(path)


def merge_and_save_all_vectors(all_vectors, all_timestamps, all_paths, config):
    ensure_folder_exists(config["cross_index_file"])
    ensure_folder_exists(config["cross_vector_file"])

    create_clip_index(all_vectors, config["cross_index_file"])
    payload = {
        "vector": all_vectors,
        "timestamps": all_timestamps,
        "paths": all_paths,
    }
    np.save(config["cross_vector_file"], payload)


def build_global_index(all_vectors, all_timestamps, all_paths, config, progress_callback=None):
    if progress_callback:
        progress_callback(95, "Building global index")

    vector_stack = np.vstack(all_vectors).astype("float32")
    timestamp_array = np.array(all_timestamps).astype("float32")
    merge_and_save_all_vectors(vector_stack, timestamp_array, all_paths, config)
    gc.collect()
    return vector_stack, timestamp_array, np.array(all_paths), load_clip_index(config["cross_index_file"])
