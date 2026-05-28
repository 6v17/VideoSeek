import os

from src.app.config import load_config
from src.core.faiss_index import load_clip_index
from src.storage.asset_store import load_model_metadata, load_vector_payload, save_model_metadata
from src.storage.config_store import get_local_model_asset_dirs
from src.utils import canonicalize_library_path
from src.services.search_index_schema import (
    clear_library_search_index,
    garbage_collect_orphan_library_indexes,
    get_library_search_index_status,
    get_search_index_schema_version,
    LIBRARY_SEARCH_INDEX_STATUS_STALE,
    list_library_search_index_summaries,
    needs_search_index_upgrade,
)

GLOBAL_INDEX_STATE_FRESH = "fresh"
GLOBAL_INDEX_STATE_STALE = "stale"


def needs_search_index_schema_upgrade(config=None):
    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    return needs_search_index_upgrade(meta, config=cfg)


def get_installed_search_index_schema_version(config=None):
    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    return get_search_index_schema_version(meta)


def resolve_library_card_status(library_path, library_data, texts, meta=None, config=None):
    exists = os.path.exists(library_path)
    has_index = len((library_data or {}).get("files", {})) > 0
    state = str((library_data or {}).get("index_state", "")).strip().lower()
    if not exists:
        return _fallback_library_text(texts, "lib_offline", "离线/不可用", "Offline"), "offline"
    if state == "partial":
        return _fallback_library_text(texts, "lib_partial", "部分完成", "Partial"), "partial"
    if not has_index:
        return texts.get("lib_pending", "Pending"), "pending"
    cfg = config or load_config()
    meta_payload = meta if meta is not None else load_model_metadata(config=cfg)
    index_status = get_library_search_index_status(meta_payload, library_path, config=cfg)
    if index_status == LIBRARY_SEARCH_INDEX_STATUS_STALE:
        return texts.get("lib_search_index_stale", texts.get("lib_partial", "Partial")), "partial"
    return texts.get("lib_ready", "Ready"), "ready"


def _fallback_library_text(texts, key, zh_text, en_text):
    if key in texts:
        return texts[key]
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


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
    meta = load_model_metadata(config=config)
    libraries = meta.get("libraries", {})
    normalized = _normalize_library_map(libraries)
    if normalized != libraries:
        removed_paths = set(libraries.keys()) - set(normalized.keys())
        for old_path in removed_paths:
            try:
                clear_library_search_index(old_path, config=config)
            except Exception:
                pass
        meta["libraries"] = normalized
        save_model_metadata(meta, config=config)
    try:
        garbage_collect_orphan_library_indexes(meta, config=config)
    except Exception:
        pass
    return normalized


def get_global_index_state():
    config = load_config()
    meta = load_model_metadata(config=config)
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
    meta = load_model_metadata(config=config)
    if not _set_global_index_state_on_meta(meta, state):
        return False
    save_model_metadata(meta, config=config)
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
    meta = load_model_metadata(config=config)
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
    save_model_metadata(meta, config=config)
    return {"added": True, "reason": "", "path": normalized_path}


def remove_library(path, delete_video_data):
    config = load_config()
    meta = load_model_metadata(config=config)
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

    clear_library_search_index(normalized_path, config=config)
    del meta["libraries"][normalized_path]
    if library_changed_search_assets:
        mark_global_index_stale(meta=meta)
    try:
        garbage_collect_orphan_library_indexes(meta, config=config)
    except Exception:
        pass
    save_model_metadata(meta, config=config)

    for video_id in removable_video_ids:
        delete_video_data(video_id, config)

    return True


def _library_changes_search_assets(library, config):
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_dir = str(model_dirs.get("vector_dir", "")).strip()
    index_dir = str(model_dirs.get("index_dir", "")).strip()
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
        data = load_vector_payload(vector_file)
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
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_dir = os.path.normpath(model_dirs["vector_dir"])
    index_dir = os.path.normpath(model_dirs["index_dir"])
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
    meta = load_model_metadata(config=config)
    library_index_root = ""
    summaries = list_library_search_index_summaries(meta, config=config)
    if summaries:
        library_index_root = str(summaries[0].get("library_index_dir", "") or "")
        library_index_root = os.path.dirname(library_index_root) if library_index_root else ""
    return {
        "vector_dir": vector_dir,
        "index_dir": index_dir,
        "library_index_root": library_index_root,
        "library_summaries": summaries,
        "entries": entries,
        "total_entries": len(entries),
    }


def list_search_scope_library_options():
    libraries = list_libraries()
    options = []
    for library_path, library_data in sorted(libraries.items()):
        files = library_data.get("files") or {}
        ready_count = 0
        for info in files.values():
            state = str(info.get("asset_state", "")).strip().lower()
            if state == "sync_failed":
                continue
            if state in {"", "ready"}:
                ready_count += 1
        options.append(
            {
                "path": library_path,
                "display_name": os.path.basename(library_path.rstrip("\\/")) or library_path,
                "ready_count": ready_count,
                "total_count": len(files),
            }
        )
    return options
