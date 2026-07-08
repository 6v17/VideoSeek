import os

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.storage.asset_store import load_model_metadata, load_vector_payload, save_model_metadata
from src.storage.config_store import get_local_model_asset_dirs
from src.utils import canonicalize_library_path
from src.services.search_index_schema import (
    clear_library_search_index,
    garbage_collect_orphan_library_indexes,
    get_library_search_index_status,
    get_search_index_schema_version,
    LIBRARY_SEARCH_INDEX_STATUS_STALE,
    needs_search_index_upgrade,
)


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

    clear_library_search_index(normalized_path, config=config)
    del meta["libraries"][normalized_path]
    try:
        garbage_collect_orphan_library_indexes(meta, config=config)
    except Exception:
        pass
    save_model_metadata(meta, config=config)

    if removable_video_ids:
        for video_id in removable_video_ids:
            delete_video_data(video_id, config)
        try:
            from src.storage.lance_store import compact_lance_storage, garbage_collect_orphan_lance_videos

            garbage_collect_orphan_lance_videos(meta, config=config)
            compact_lance_storage(get_local_model_asset_dirs(config=config)["base_dir"])
        except Exception as exc:
            get_logger("library_service").warning("Post-removal Lance cleanup failed: %s", exc)

    return True


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


def _effective_asset_state(info, source_exists, vector_exists, vector_ok, lance_ready):
    stored_state = str(info.get("asset_state", "")).strip().lower()
    if not source_exists:
        return "missing_source"
    if stored_state == "sync_failed" and (not vector_exists or not vector_ok or not lance_ready):
        return "sync_failed"
    if not vector_exists:
        return "missing_asset"
    if not vector_ok or not lance_ready:
        return "broken_asset"
    return "ready"


def list_local_vector_details(validate_contents=False):
    from src.storage.lance_search_index import (
        get_lance_indexed_video_ids,
        get_lance_video_row_counts,
        lance_search_is_ready,
    )
    from src.storage.lance_store import (
        allocate_lance_dir_bytes_by_weight,
        estimate_lance_video_payload_bytes,
        get_lance_dir,
        read_lance_profile_summary,
        sum_legacy_vector_npy_bytes,
    )

    config = load_config()
    libraries = list_libraries()
    model_dirs = get_local_model_asset_dirs(config=config)
    profile_base_dir = os.path.normpath(model_dirs["base_dir"])
    vector_dir = os.path.normpath(model_dirs["vector_dir"])
    lance_dir = os.path.normpath(get_lance_dir(profile_base_dir))
    lance_table_ready = lance_search_is_ready(profile_base_dir)
    lance_video_ids = get_lance_indexed_video_ids(profile_base_dir) if lance_table_ready else frozenset()
    lance_video_counts = get_lance_video_row_counts(profile_base_dir) if lance_table_ready else {}
    lance_summary = read_lance_profile_summary(profile_base_dir)
    lance_dir_bytes = int(lance_summary.get("lance_dir_bytes", 0) or 0)
    legacy_vector_dir_bytes = sum_legacy_vector_npy_bytes(vector_dir)
    embedding_dim = int(lance_summary.get("dimension", 0) or 0)
    lance_weight_by_video = {
        video_id: estimate_lance_video_payload_bytes(
            counts.get("frame_count", 0),
            counts.get("chunk_count", 0),
            dimension=embedding_dim,
        )
        for video_id, counts in lance_video_counts.items()
    }
    lance_active_bytes = sum(lance_weight_by_video.values())
    lance_bytes_by_video = allocate_lance_dir_bytes_by_weight(lance_active_bytes, lance_weight_by_video)
    entries = []

    for library_path, library_data in libraries.items():
        files = library_data.get("files", {})
        for rel_path, info in files.items():
            video_id = str(info.get("vid", "")).strip()
            if not video_id:
                continue
            video_path = os.path.normpath(os.path.join(library_path, rel_path))
            legacy_npy_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
            source_exists = os.path.exists(video_path)
            legacy_npy_exists = os.path.exists(legacy_npy_file)
            lance_ready = video_id in lance_video_ids
            video_counts = lance_video_counts.get(video_id, {})
            lance_frame_count = int(video_counts.get("frame_count", 0) or 0)
            lance_chunk_count = int(video_counts.get("chunk_count", 0) or 0)
            lance_storage_bytes = int(lance_bytes_by_video.get(video_id, 0) or 0) if lance_ready else 0
            legacy_npy_bytes = 0
            if legacy_npy_exists:
                try:
                    legacy_npy_bytes = os.path.getsize(legacy_npy_file)
                except OSError:
                    legacy_npy_bytes = 0
            storage_bytes = lance_storage_bytes + legacy_npy_bytes
            if validate_contents:
                legacy_npy_ok = False
                if legacy_npy_exists:
                    _, legacy_npy_ok = _read_vector_health(legacy_npy_file)
                asset_state = _effective_asset_state(
                    info,
                    source_exists=source_exists,
                    vector_exists=legacy_npy_exists or lance_ready,
                    vector_ok=legacy_npy_ok or lance_ready,
                    lance_ready=lance_ready,
                )
            else:
                stored_state = str(info.get("asset_state", "")).strip().lower()
                if not source_exists:
                    asset_state = "missing_source"
                elif stored_state == "sync_failed":
                    asset_state = "sync_failed"
                elif not lance_ready and not legacy_npy_exists:
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
                    "lance_ready": lance_ready,
                    "lance_frame_count": lance_frame_count,
                    "lance_chunk_count": lance_chunk_count,
                    "lance_storage_bytes": lance_storage_bytes,
                    "legacy_npy_bytes": legacy_npy_bytes,
                    "storage_bytes": storage_bytes,
                    "legacy_npy_exists": legacy_npy_exists,
                    "legacy_npy_file": legacy_npy_file if legacy_npy_exists else "",
                    "sync_failure_reason": str(info.get("sync_failure_reason", "")).strip().lower(),
                    # Legacy export fields kept for older tooling.
                    "vector_file": legacy_npy_file,
                    "vector_exists": legacy_npy_exists or lance_ready,
                    "index_exists": lance_ready,
                    "index_file": "",
                }
            )

    entries.sort(key=lambda item: (item["library_path"], item["video_rel_path"]))
    total_storage_bytes = lance_active_bytes + legacy_vector_dir_bytes
    return {
        "schema_version": 2,
        "profile_base_dir": profile_base_dir,
        "lance_dir": lance_dir,
        "legacy_vector_dir": vector_dir,
        "lance_summary": lance_summary,
        "storage_summary": {
            "lance_dir_bytes": lance_dir_bytes,
            "lance_active_bytes": lance_active_bytes,
            "legacy_vector_dir_bytes": legacy_vector_dir_bytes,
            "total_storage_bytes": total_storage_bytes,
        },
        "entries": entries,
        "total_entries": len(entries),
        # Deprecated keys retained for exported JSON compatibility.
        "vector_dir": vector_dir,
        "index_dir": os.path.normpath(model_dirs["index_dir"]),
        "library_index_root": "",
        "library_summaries": [],
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
