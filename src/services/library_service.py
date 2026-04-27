import os

from src.app.config import load_config
from src.core.faiss_index import load_clip_index, load_vectors
from src.utils import canonicalize_library_path, load_meta, save_meta

GLOBAL_INDEX_STATE_FRESH = "fresh"
GLOBAL_INDEX_STATE_STALE = "stale"


def _normalize_library_map(libraries):
    normalized = {}
    for raw_path, data in libraries.items():
        normalized[canonicalize_library_path(raw_path)] = data
    return normalized


def _paths_overlap(path_a, path_b):
    normalized_a = os.path.normcase(os.path.normpath(path_a))
    normalized_b = os.path.normcase(os.path.normpath(path_b))
    if normalized_a == normalized_b:
        return True
    try:
        common_path = os.path.commonpath([normalized_a, normalized_b])
    except ValueError:
        return False
    return common_path in {normalized_a, normalized_b}


def list_libraries():
    config = load_config()
    meta = load_meta(config["meta_file"])
    libraries = meta.get("libraries", {})
    normalized = _normalize_library_map(libraries)
    if normalized != libraries:
        meta["libraries"] = normalized
        save_meta(meta, config["meta_file"])
    return normalized


def get_global_index_state():
    config = load_config()
    meta = load_meta(config["meta_file"])
    state = _normalize_global_index_state(meta.get("global_index_state", GLOBAL_INDEX_STATE_FRESH))
    if not state:
        return GLOBAL_INDEX_STATE_FRESH
    return state


def _normalize_global_index_state(state):
    normalized_state = str(state or "").strip().lower()
    if normalized_state not in {GLOBAL_INDEX_STATE_FRESH, GLOBAL_INDEX_STATE_STALE}:
        return ""
    return normalized_state


def _set_global_index_state_on_meta(meta, state):
    normalized_state = _normalize_global_index_state(state)
    if not normalized_state:
        return False
    previous_state = _normalize_global_index_state(meta.get("global_index_state", GLOBAL_INDEX_STATE_FRESH))
    if not previous_state:
        previous_state = GLOBAL_INDEX_STATE_FRESH
    if previous_state == normalized_state:
        return False
    meta["global_index_state"] = normalized_state
    return True


def set_global_index_state(state, meta=None):
    if meta is not None:
        return _set_global_index_state_on_meta(meta, state)
    config = load_config()
    meta = load_meta(config["meta_file"])
    if not _set_global_index_state_on_meta(meta, state):
        return False
    save_meta(meta, config["meta_file"])
    return True


def mark_global_index_stale(meta=None):
    return set_global_index_state(GLOBAL_INDEX_STATE_STALE, meta=meta)


def mark_global_index_fresh(meta=None):
    return set_global_index_state(GLOBAL_INDEX_STATE_FRESH, meta=meta)


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
        return {"added": False, "reason": "exists", "path": normalized_path}

    for existing_path in meta["libraries"].keys():
        if _paths_overlap(existing_path, normalized_path):
            return {
                "added": False,
                "reason": "overlap",
                "path": normalized_path,
                "conflict_path": existing_path,
            }

    meta["libraries"][normalized_path] = {"files": {}, "last_scan": "", "index_state": "pending"}
    save_meta(meta, config["meta_file"])
    return {"added": True, "reason": "", "path": normalized_path}


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

    library_changed_search_assets = _library_changes_search_assets(library, config)

    del meta["libraries"][normalized_path]
    if library_changed_search_assets:
        mark_global_index_stale(meta=meta)
    save_meta(meta, config["meta_file"])

    for video_id in removable_video_ids:
        delete_video_data(video_id, config)

    return True


def _library_changes_search_assets(library, config):
    vector_dir = str(config.get("vector_dir", "")).strip()
    index_dir = str(config.get("index_dir", "")).strip()
    for info in library.get("files", {}).values():
        video_id = str(info.get("vid", "")).strip()
        if not video_id:
            continue
        asset_state = str(info.get("asset_state", "")).strip().lower()
        vector_file = os.path.join(vector_dir, f"{video_id}_vectors.npy") if vector_dir else ""
        index_file = os.path.join(index_dir, f"{video_id}_index.faiss") if index_dir else ""
        if (vector_file and os.path.exists(vector_file)) or (index_file and os.path.exists(index_file)):
            return True
        if asset_state and asset_state != "sync_failed":
            return True
    return False


def _read_vector_health(vector_file):
    if not os.path.exists(vector_file):
        return False, False
    try:
        data = load_vectors(vector_file)
    except Exception:
        return True, False
    if not isinstance(data, dict):
        return True, False
    vectors = data.get("vector")
    timestamps = data.get("timestamps")
    if vectors is None or timestamps is None:
        return True, False
    try:
        vector_count = len(vectors)
        timestamp_count = len(timestamps)
    except TypeError:
        return True, False
    if vector_count <= 0 or vector_count != timestamp_count:
        return True, False
    return True, True


def _read_index_health(index_file):
    if not os.path.exists(index_file):
        return False, False
    try:
        return True, load_clip_index(index_file) is not None
    except Exception:
        return True, False


def _effective_asset_state(info, source_exists, vector_exists, vector_ok, index_exists, index_ok):
    stored_state = str(info.get("asset_state", "")).strip().lower()
    if not source_exists:
        return "missing_source"
    if stored_state == "sync_failed" and (not vector_exists or not vector_ok or not index_exists or not index_ok):
        return "sync_failed"
    if not vector_exists or not index_exists:
        return "missing_asset"
    if not vector_ok or not index_ok:
        return "broken_asset"
    return "ready"


def list_local_vector_details(validate_contents=False):
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
            video_path = os.path.normpath(os.path.join(library_path, rel_path))
            vector_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
            index_file = os.path.normpath(os.path.join(index_dir, f"{video_id}_index.faiss"))
            source_exists = os.path.exists(video_path)
            if validate_contents:
                vector_exists, vector_ok = _read_vector_health(vector_file)
                index_exists, index_ok = _read_index_health(index_file)
                asset_state = _effective_asset_state(
                    info,
                    source_exists=source_exists,
                    vector_exists=vector_exists,
                    vector_ok=vector_ok,
                    index_exists=index_exists,
                    index_ok=index_ok,
                )
            else:
                vector_exists = os.path.exists(vector_file)
                index_exists = os.path.exists(index_file)
                stored_state = str(info.get("asset_state", "")).strip().lower()
                if not source_exists:
                    asset_state = "missing_source"
                elif stored_state == "sync_failed":
                    asset_state = "sync_failed"
                elif not vector_exists or not index_exists:
                    asset_state = "missing_asset"
                else:
                    asset_state = "ready"
            entries.append(
                {
                    "library_path": library_path,
                    "video_rel_path": rel_path,
                    "video_id": video_id,
                    "source_exists": source_exists,
                    "asset_state": asset_state,
                    "vector_file": vector_file,
                    "index_file": index_file,
                    "vector_exists": vector_exists,
                    "index_exists": index_exists,
                    "sync_failure_reason": str(info.get("sync_failure_reason", "")).strip().lower(),
                }
            )

    entries.sort(key=lambda item: (item["library_path"], item["video_rel_path"]))
    return {
        "vector_dir": vector_dir,
        "index_dir": index_dir,
        "entries": entries,
        "total_entries": len(entries),
    }
