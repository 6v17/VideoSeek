"""Search index schema version and per-library index layout (v2)."""

from __future__ import annotations

import hashlib
import os
import shutil

from src.utils import canonicalize_library_path

SEARCH_INDEX_SCHEMA_V1 = 1
SEARCH_INDEX_SCHEMA_V2 = 2
TARGET_SEARCH_INDEX_SCHEMA_VERSION = SEARCH_INDEX_SCHEMA_V2

LIBRARY_SEARCH_INDEX_STATUS_NEEDS_UPGRADE = "needs_upgrade"
LIBRARY_SEARCH_INDEX_STATUS_NOT_APPLICABLE = "not_applicable"
LIBRARY_SEARCH_INDEX_STATUS_READY = "ready"
LIBRARY_SEARCH_INDEX_STATUS_STALE = "stale"


def normalize_search_index_schema_version(value) -> int:
    try:
        version = int(value)
    except (TypeError, ValueError):
        return SEARCH_INDEX_SCHEMA_V1
    if version < SEARCH_INDEX_SCHEMA_V1:
        return SEARCH_INDEX_SCHEMA_V1
    return version


def library_index_key(library_path: str) -> str:
    normalized = canonicalize_library_path(library_path)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return digest[:16]


def get_library_index_paths(library_path: str, config=None) -> dict:
    from src.storage.config_store import get_global_model_asset_paths

    global_paths = get_global_model_asset_paths(config=config)
    lib_dir = os.path.join(global_paths["global_dir"], "library_indexes", library_index_key(library_path))
    return {
        "library_dir": lib_dir,
        "frame_index_file": os.path.join(lib_dir, "frame_index.faiss"),
        "frame_vector_file": os.path.join(lib_dir, "frame_vectors.npy"),
        "chunk_index_file": os.path.join(lib_dir, "chunk_index.faiss"),
        "chunk_vector_file": os.path.join(lib_dir, "chunk_vectors.npy"),
    }


def get_search_index_schema_version(meta) -> int:
    # Do not confuse with meta/config top-level "schema_version" (app migration format).
    return normalize_search_index_schema_version((meta or {}).get("search_index_schema_version", SEARCH_INDEX_SCHEMA_V1))


def needs_search_index_upgrade(meta, config=None) -> bool:
    return False


def library_index_is_ready(library_path: str, config=None) -> bool:
    from src.storage.asset_store import load_model_metadata
    from src.storage.config_store import get_local_model_asset_dirs
    from src.storage.lance_search_index import lance_search_is_ready

    meta = load_model_metadata(config=config)
    if not library_has_ready_videos(meta, library_path):
        return False
    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    if not lance_search_is_ready(profile_base_dir):
        return False
    lib_key = canonicalize_library_path(library_path)
    for root_path, lib_data in (meta or {}).get("libraries", {}).items():
        if canonicalize_library_path(root_path) != lib_key:
            continue
        for info in (lib_data or {}).get("files", {}).values():
            if str(info.get("asset_state", "")).strip().lower() != "ready":
                continue
            if str(info.get("vid", "")).strip():
                return True
    return False


def clear_library_search_index(library_path: str, config=None) -> None:
    asset_paths = get_library_index_paths(library_path, config=config)
    for key in ("frame_index_file", "frame_vector_file", "chunk_index_file", "chunk_vector_file"):
        path = asset_paths.get(key)
        if path and os.path.exists(path):
            os.remove(path)
    lib_dir = asset_paths.get("library_dir")
    if lib_dir and os.path.isdir(lib_dir):
        try:
            if not os.listdir(lib_dir):
                os.rmdir(lib_dir)
        except OSError:
            pass


def get_library_search_index_status(meta, library_path: str, config=None) -> str:
    if not library_has_ready_videos(meta, library_path):
        return LIBRARY_SEARCH_INDEX_STATUS_NOT_APPLICABLE
    if library_index_is_ready(library_path, config=config):
        return LIBRARY_SEARCH_INDEX_STATUS_READY
    return LIBRARY_SEARCH_INDEX_STATUS_STALE


def legacy_faiss_index_artifacts_present(config=None) -> bool:
    from src.storage.config_store import get_global_model_asset_paths, get_local_model_asset_dirs
    from src.storage.video_id_migration import legacy_npy_vectors_present

    if legacy_npy_vectors_present(config):
        return True

    model_dirs = get_local_model_asset_dirs(config=config)
    index_dir = str(model_dirs.get("index_dir", "") or "")
    if index_dir and os.path.isdir(index_dir):
        for name in os.listdir(index_dir):
            if name.lower().endswith("_index.faiss"):
                return True

    global_dir = str(get_global_model_asset_paths(config=config).get("global_dir", "") or "")
    if not global_dir or not os.path.isdir(global_dir):
        return False
    for name in os.listdir(global_dir):
        lower = name.lower()
        if lower.endswith(".faiss") or lower.endswith(".npy"):
            return True
    library_root = os.path.join(global_dir, "library_indexes")
    return os.path.isdir(library_root) and bool(os.listdir(library_root))


def prune_legacy_search_index_artifacts(meta, config=None) -> dict:
    """Remove legacy FAISS/global index files once Lance search is active."""
    from src.storage.config_store import get_global_model_asset_paths, get_local_model_asset_dirs
    from src.storage.lance_search_index import lance_search_is_ready
    from src.storage.video_id_migration import legacy_npy_vectors_present

    if legacy_npy_vectors_present(config):
        return {"removed_files": 0, "removed_dirs": 0, "skipped": "legacy_npy_present"}

    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    if not lance_search_is_ready(profile_base_dir):
        return {"removed_files": 0, "removed_dirs": 0, "skipped": "lance_not_ready"}

    removed_files = 0
    removed_dirs = 0

    model_dirs = get_local_model_asset_dirs(config=config)
    index_dir = str(model_dirs.get("index_dir", "") or "")
    if index_dir and os.path.isdir(index_dir):
        for name in os.listdir(index_dir):
            if not name.lower().endswith("_index.faiss"):
                continue
            try:
                os.remove(os.path.join(index_dir, name))
                removed_files += 1
            except OSError:
                pass

    global_dir = str(get_global_model_asset_paths(config=config).get("global_dir", "") or "")
    if global_dir and os.path.isdir(global_dir):
        for name in os.listdir(global_dir):
            lower = name.lower()
            if not (lower.endswith(".faiss") or lower.endswith(".npy")):
                continue
            try:
                os.remove(os.path.join(global_dir, name))
                removed_files += 1
            except OSError:
                pass
        library_root = os.path.join(global_dir, "library_indexes")
        if os.path.isdir(library_root):
            try:
                shutil.rmtree(library_root)
                removed_dirs += 1
            except OSError:
                pass

    removed_dirs += garbage_collect_orphan_library_indexes(meta, config=config)
    return {"removed_files": removed_files, "removed_dirs": removed_dirs, "skipped": ""}


def list_library_search_index_summaries(meta, config=None) -> list[dict]:
    summaries = []
    for library_path in sorted((meta or {}).get("libraries", {}).keys()):
        status = get_library_search_index_status(meta, library_path, config=config)
        lance_ready = status == LIBRARY_SEARCH_INDEX_STATUS_READY
        summaries.append(
            {
                "library_path": library_path,
                "status": status,
                "library_index_dir": "",
                "frame_index_ready": lance_ready,
                "chunk_index_ready": lance_ready,
            }
        )
    return summaries


def garbage_collect_orphan_library_indexes(meta, config=None) -> int:
    from src.storage.video_id_migration import legacy_npy_vectors_present

    if not legacy_faiss_index_artifacts_present(config) and not legacy_npy_vectors_present(config):
        global_dir = ""
        try:
            from src.storage.config_store import get_global_model_asset_paths

            global_dir = get_global_model_asset_paths(config=config).get("global_dir", "")
        except Exception:
            pass
        library_root = os.path.join(global_dir, "library_indexes") if global_dir else ""
        if library_root and os.path.isdir(library_root):
            try:
                shutil.rmtree(library_root)
                return 1
            except OSError:
                pass
        return 0

    from src.storage.config_store import get_global_model_asset_paths

    global_dir = get_global_model_asset_paths(config=config).get("global_dir", "")
    lib_indexes_root = os.path.join(global_dir, "library_indexes")
    if not lib_indexes_root or not os.path.isdir(lib_indexes_root):
        return 0
    valid_keys = {library_index_key(path) for path in (meta or {}).get("libraries", {}).keys()}
    removed = 0
    for name in os.listdir(lib_indexes_root):
        full_path = os.path.join(lib_indexes_root, name)
        if not os.path.isdir(full_path):
            continue
        if name in valid_keys:
            continue
        shutil.rmtree(full_path, ignore_errors=True)
        removed += 1
    return removed


def library_has_ready_videos(meta, library_path: str) -> bool:
    lib_key = canonicalize_library_path(library_path)
    for root_path, lib_data in (meta or {}).get("libraries", {}).items():
        if canonicalize_library_path(root_path) != lib_key:
            continue
        for info in (lib_data or {}).get("files", {}).values():
            if str(info.get("asset_state", "")).strip().lower() == "ready":
                return True
    return False


def _library_search_index_is_marked_ready(lib_data) -> bool:
    if not isinstance(lib_data, dict):
        return False
    return (
        normalize_search_index_schema_version(lib_data.get("search_index_schema_version"))
        >= TARGET_SEARCH_INDEX_SCHEMA_VERSION
    )


def mark_search_index_schema_upgraded(meta, *, target_lib=None) -> None:
    meta["search_index_schema_version"] = TARGET_SEARCH_INDEX_SCHEMA_VERSION
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in (meta or {}).get("libraries", {}).items():
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not isinstance(lib_data, dict):
            continue
        if library_has_ready_videos(meta, root_path):
            lib_data["search_index_schema_version"] = TARGET_SEARCH_INDEX_SCHEMA_VERSION
