import os

from src.app.config import load_config
from src.utils import canonicalize_library_path, load_meta, save_meta


def _normalize_library_map(libraries):
    normalized = {}
    for raw_path, data in libraries.items():
        normalized[canonicalize_library_path(raw_path)] = data
    return normalized


def list_libraries():
    config = load_config()
    meta = load_meta(config["meta_file"])
    libraries = meta.get("libraries", {})
    normalized = _normalize_library_map(libraries)
    if normalized != libraries:
        meta["libraries"] = normalized
        save_meta(meta, config["meta_file"])
    return normalized


def list_partial_libraries(include_offline=False):
    libraries = list_libraries()
    partial = []
    for path, data in libraries.items():
        if str(data.get("index_state", "")).strip().lower() != "partial":
            continue
        if not include_offline and not os.path.exists(path):
            continue
        partial.append(path)
    return partial


def add_library(path):
    config = load_config()
    meta = load_meta(config["meta_file"])
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    normalized_path = canonicalize_library_path(path)

    if normalized_path in meta["libraries"]:
        return False

    meta["libraries"][normalized_path] = {"files": {}, "last_scan": "", "index_state": "pending"}
    save_meta(meta, config["meta_file"])
    return True


def remove_library(path, delete_video_data):
    config = load_config()
    meta = load_meta(config["meta_file"])
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    normalized_path = canonicalize_library_path(path)
    library = meta["libraries"].get(normalized_path)

    if library is None:
        return False

    remaining_video_ids = set()
    for root_path, lib_data in meta["libraries"].items():
        if root_path == normalized_path:
            continue
        for info in lib_data.get("files", {}).values():
            video_id = info.get("vid")
            if video_id:
                remaining_video_ids.add(video_id)

    removable_video_ids = {
        info.get("vid")
        for info in library.get("files", {}).values()
        if info.get("vid") and info.get("vid") not in remaining_video_ids
    }

    del meta["libraries"][normalized_path]
    save_meta(meta, config["meta_file"])

    for video_id in removable_video_ids:
        delete_video_data(video_id, config)

    return True


def list_local_vector_details():
    config = load_config()
    libraries = list_libraries()
    vector_dir = os.path.normpath(config.get("vector_dir", ""))
    index_dir = os.path.normpath(config.get("index_dir", ""))
    entries = []

    for library_path, library_data in libraries.items():
        files = library_data.get("files", {})
        for rel_path, info in files.items():
            video_id = str(info.get("vid", "")).strip()
            if not video_id:
                continue
            vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
            index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))
            entries.append(
                {
                    "library_path": library_path,
                    "video_rel_path": rel_path,
                    "video_id": video_id,
                    "vector_file": vector_file,
                    "index_file": index_file,
                    "vector_exists": os.path.exists(vector_file),
                    "index_exists": os.path.exists(index_file),
                }
            )

    entries.sort(key=lambda item: (item["library_path"], item["video_rel_path"]))
    return {
        "vector_dir": vector_dir,
        "index_dir": index_dir,
        "entries": entries,
        "total_entries": len(entries),
    }
