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


def add_library(path):
    config = load_config()
    meta = load_meta(config["meta_file"])
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    normalized_path = canonicalize_library_path(path)

    if normalized_path in meta["libraries"]:
        return False

    meta["libraries"][normalized_path] = {"files": {}, "last_scan": ""}
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
