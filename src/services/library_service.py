import os

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.storage.asset_store import load_model_metadata, save_model_metadata
from src.storage.config_store import get_local_model_asset_dirs
from src.utils import canonicalize_library_path
from src.services.search_index_schema import (
    clear_library_search_index,
    garbage_collect_orphan_library_indexes,
    get_library_search_index_status,
    get_search_index_schema_version,
    LIBRARY_SEARCH_INDEX_STATUS_STALE,
    needs_search_index_upgrade,
    prune_legacy_search_index_artifacts,
)
from src.services.indexing_runtime_status import get_index_sync_status, library_sync_in_progress

_VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm")


def _iter_library_video_paths(root_path: str):
    for current_root, dir_names, files in os.walk(root_path):
        dir_names[:] = [name for name in dir_names if name.lower() != "__macosx"]
        for filename in files:
            if filename.lower().endswith(_VIDEO_EXTS):
                yield os.path.join(current_root, filename)


def needs_search_index_schema_upgrade(config=None):
    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    return needs_search_index_upgrade(meta, config=cfg)


def get_installed_search_index_schema_version(config=None):
    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    return get_search_index_schema_version(meta)


def resolve_library_card_status(library_path, library_data, texts, meta=None, config=None):
    sync_status = get_index_sync_status()
    if sync_status.get("index_sync_in_progress"):
        target = str(sync_status.get("index_sync_target_library_path") or "").strip()
        if not target or library_sync_in_progress(library_path, sync_status=sync_status):
            total = int(sync_status.get("index_sync_progress_total") or 0)
            current = int(sync_status.get("index_sync_progress_current") or 0)
            if total > 0:
                return (
                    texts.get("lib_syncing_progress", "{current}/{total}").format(
                        current=current,
                        total=total,
                    ),
                    "partial",
                )
            return texts.get("lib_syncing", texts.get("lib_partial", "Partial")), "partial"

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


def count_video_id_refs(
    meta,
    video_id: str,
    *,
    exclude_library_path: str | None = None,
    exclude_rel_path: str | None = None,
) -> int:
    """How many library file rows still point at ``video_id``.

    Lance / visual payloads are per CLIP profile; physical deletes must only run
    when this returns 0 for the active profile meta.
    """
    vid = str(video_id or "").strip()
    if not vid:
        return 0
    exclude_lib = (
        canonicalize_library_path(exclude_library_path) if exclude_library_path else ""
    )
    exclude_rel = str(exclude_rel_path or "").replace("\\", "/").strip()
    count = 0
    libraries = (meta or {}).get("libraries") or {}
    if not isinstance(libraries, dict):
        return 0
    for root_path, lib_data in libraries.items():
        if not isinstance(lib_data, dict):
            continue
        root_key = canonicalize_library_path(root_path)
        files = lib_data.get("files") or {}
        if not isinstance(files, dict):
            continue
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            rel = str(rel_path or "").replace("\\", "/").strip()
            if exclude_lib and root_key == exclude_lib:
                # No rel → exclude the whole library (used by remove_library).
                if not exclude_rel or rel == exclude_rel:
                    continue
            if str(info.get("vid", "") or "").strip() == vid:
                count += 1
    return count


def video_id_is_shared(meta, video_id: str) -> bool:
    return count_video_id_refs(meta, video_id) > 1


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


def list_libraries(*, maintain: bool = False):
    config = load_config()
    meta = load_model_metadata(config=config)
    libraries = meta.get("libraries", {})
    normalized = _normalize_library_map(libraries)
    if maintain:
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


def maintain_library_metadata():
    """Normalize library paths, prune orphan legacy indexes, and drop stale FAISS artifacts."""
    config = load_config()
    meta = load_model_metadata(config=config)
    libraries = list_libraries(maintain=True)
    if _repair_false_partial_library_states(meta):
        save_model_metadata(meta, config=config)
    try:
        from src.storage.lance_store import drop_lance_vector_indexes
        from src.storage.config_store import get_local_model_asset_dirs

        drop_lance_vector_indexes(get_local_model_asset_dirs(config=config)["base_dir"])
    except Exception as exc:
        get_logger("library_service").warning("Lance ANN index cleanup failed: %s", exc)
    try:
        prune_legacy_search_index_artifacts(meta, config=config)
    except Exception as exc:
        get_logger("library_service").warning("Legacy search index cleanup failed: %s", exc)
    return libraries


def _repair_false_partial_library_states(meta) -> bool:
    """Recover from legacy bug that marked every library partial when a full sync was stopped."""
    from src.services.indexing_runtime_status import get_index_sync_status

    if get_index_sync_status().get("index_sync_in_progress"):
        return False
    libraries = (meta or {}).get("libraries", {})
    if not libraries:
        return False
    partial_libraries = [
        path
        for path, data in libraries.items()
        if str((data or {}).get("index_state", "")).strip().lower() == "partial"
    ]
    if not partial_libraries or len(partial_libraries) != len(libraries):
        return False
    changed = False
    for path in partial_libraries:
        data = libraries.get(path, {})
        if not (data or {}).get("files"):
            continue
        data["index_state"] = "ready"
        changed = True
    return changed


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


def register_library_videos(*, config=None, library_path: str | None = None) -> dict:
    """Discover videos under CLIP-profile libraries and ensure meta file records exist.

    Assigns ``video_id`` without building CLIP vectors. Newly seen files get
    ``asset_state=missing_asset``. Existing ready/failed states are left unchanged
    when the source still exists. Subtitle folders use ``register_subtitle_library_videos``.
    """
    from src.utils import get_video_hash

    cfg = config or load_config()
    meta = load_model_metadata(config=cfg)
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    target = canonicalize_library_path(library_path) if library_path else ""

    registered = 0
    updated = 0
    changed = False

    for root_path, lib_data in list(meta.get("libraries", {}).items()):
        if not isinstance(lib_data, dict):
            continue
        root_key = canonicalize_library_path(root_path)
        if target and root_key != target:
            continue
        if not os.path.isdir(root_path):
            continue

        lib_files = lib_data.setdefault("files", {})
        if not isinstance(lib_files, dict):
            lib_files = {}
            lib_data["files"] = lib_files

        for abs_path in _iter_library_video_paths(root_path):
            if not os.path.isfile(abs_path):
                continue
            rel_path = os.path.relpath(abs_path, root_path)
            try:
                video_mod_time = os.path.getmtime(abs_path)
            except OSError:
                continue

            previous = dict(lib_files.get(rel_path, {}) or {})
            video_id = str(previous.get("vid", "") or "").strip()
            if not video_id:
                try:
                    video_id = get_video_hash(abs_path)
                except OSError:
                    continue
                registered += 1

            state = str(previous.get("asset_state", "") or "").strip().lower()
            if state in {"", "missing_source"}:
                state = "missing_asset"

            next_info = dict(previous)
            next_info["vid"] = video_id
            next_info["mod_time"] = video_mod_time
            next_info["asset_state"] = state
            if state != "sync_failed":
                next_info.pop("sync_failure_reason", None)

            if next_info != previous:
                lib_files[rel_path] = next_info
                updated += 1
                changed = True

        lib_data["files"] = lib_files

    if changed:
        save_model_metadata(meta, config=cfg)
    return {"registered": registered, "updated": updated, "changed": changed}


def list_library_video_entries(*, config=None, register: bool = True) -> list[dict]:
    """Registered library videos for UI trees (does not require visual sync)."""
    cfg = config or load_config()
    if register:
        register_library_videos(config=cfg)
    meta = load_model_metadata(config=cfg)
    libraries = _normalize_library_map(meta.get("libraries", {}))
    entries: list[dict] = []
    for root_path, lib_data in libraries.items():
        if not isinstance(lib_data, dict):
            continue
        library_path = canonicalize_library_path(root_path)
        files = lib_data.get("files") or {}
        if not isinstance(files, dict):
            continue
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            video_id = str(info.get("vid", "") or "").strip()
            if not video_id:
                continue
            video_path = os.path.normpath(os.path.join(root_path, str(rel_path or "")))
            source_exists = os.path.isfile(video_path)
            entries.append(
                {
                    "library_path": library_path,
                    "video_path": video_path,
                    "video_rel_path": str(rel_path or "").replace("\\", "/"),
                    "video_id": video_id,
                    "asset_state": str(info.get("asset_state", "") or "").strip().lower(),
                    "source_exists": source_exists,
                    "sync_failure_reason": str(info.get("sync_failure_reason", "") or "").strip().lower(),
                }
            )
    entries.sort(key=lambda item: (item["library_path"].lower(), item["video_rel_path"].lower()))
    return entries


def remove_library(path, delete_video_data, progress_callback=None):
    """Remove a visual library from the active CLIP profile and exclusive Lance data.

    Does not delete shared subtitle OCR (``transcripts.db``). Use
    ``subtitle_library_service.remove_subtitle_library`` for that.

    ``progress_callback(percent, text)`` is optional; heavy Lance work should run
    off the UI thread via ``RemoveLibraryWorker``.
    """
    config = load_config()
    meta = load_model_metadata(config=config)
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    normalized_path = canonicalize_library_path(path)
    library = meta["libraries"].get(normalized_path)

    if library is None:
        return False

    def _progress(percent: int, text: str = "") -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(int(percent), str(text or ""))
        except Exception:
            pass

    # Snapshot exclusive ids before mutating meta. A video_id still referenced by
    # any other library in this CLIP profile must keep its Lance payload.
    removable_video_ids = sorted(
        {
            str(info.get("vid") or "").strip()
            for info in library.get("files", {}).values()
            if isinstance(info, dict)
            and str(info.get("vid") or "").strip()
            and count_video_id_refs(
                meta,
                str(info.get("vid") or "").strip(),
                exclude_library_path=normalized_path,
            )
            == 0
        }
    )

    _progress(2, "remove_library|meta")
    clear_library_search_index(normalized_path, config=config)
    del meta["libraries"][normalized_path]
    try:
        garbage_collect_orphan_library_indexes(meta, config=config)
    except Exception:
        pass
    save_model_metadata(meta, config=config)

    if removable_video_ids:
        total = len(removable_video_ids)
        for index, video_id in enumerate(removable_video_ids):
            _progress(
                int(5 + (index / max(total, 1)) * 80),
                f"remove_library|{index + 1}|{total}|{video_id}",
            )
            try:
                delete_video_data(video_id, config, refresh_lance_state=False)
            except TypeError:
                # Test doubles / older callables may not accept the kwarg.
                delete_video_data(video_id, config)

        _progress(90, "remove_library|compact")
        try:
            from src.storage.lance_store import (
                compact_lance_storage,
                garbage_collect_orphan_lance_videos,
            )

            base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
            # Batch: skip per-orphan refresh/compact; compact refreshes once at end.
            garbage_collect_orphan_lance_videos(
                meta,
                config=config,
                compact=False,
                refresh_state=False,
            )
            compact_lance_storage(base_dir)
        except Exception as exc:
            get_logger("library_service").warning("Post-removal Lance cleanup failed: %s", exc)

    _progress(100, "remove_library|done")
    return True


def _effective_asset_state(info, source_exists, vector_exists, vector_ok, lance_ready):
    """Ready only when Lance has the video. Legacy npy alone is broken/migration pending."""
    stored_state = str(info.get("asset_state", "")).strip().lower()
    if not source_exists:
        return "missing_source"
    if stored_state == "sync_failed" and (not lance_ready):
        return "sync_failed"
    if not lance_ready:
        if vector_exists:
            return "broken_asset"
        return "missing_asset"
    if not vector_ok:
        return "broken_asset"
    return "ready"


def list_local_vector_details(validate_contents=False, *, include_storage_stats=True):
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
    if include_storage_stats:
        lance_video_counts = get_lance_video_row_counts(profile_base_dir) if lance_table_ready else {}
        lance_summary = read_lance_profile_summary(profile_base_dir, include_dir_size=True)
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
    else:
        lance_video_counts = {}
        lance_summary = {"ready": lance_table_ready, "indexed_video_count": len(lance_video_ids)}
        lance_dir_bytes = 0
        legacy_vector_dir_bytes = 0
        lance_active_bytes = 0
        lance_bytes_by_video = {}
    entries = []

    # Fast UI path: trust meta + Lance id set; skip per-file exists()/npy probes.
    probe_filesystem = bool(validate_contents or include_storage_stats)

    for library_path, library_data in libraries.items():
        files = library_data.get("files", {})
        for rel_path, info in files.items():
            video_id = str(info.get("vid", "")).strip()
            if not video_id:
                continue
            video_path = os.path.normpath(os.path.join(library_path, rel_path))
            legacy_npy_file = os.path.normpath(os.path.join(vector_dir, f"{video_id}_vectors.npy"))
            lance_ready = video_id in lance_video_ids
            stored_state = str(info.get("asset_state", "")).strip().lower()
            if probe_filesystem:
                source_exists = os.path.exists(video_path)
                legacy_npy_exists = os.path.exists(legacy_npy_file)
            else:
                source_exists = stored_state != "missing_source"
                legacy_npy_exists = False
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
                asset_state = _effective_asset_state(
                    info,
                    source_exists=source_exists,
                    vector_exists=legacy_npy_exists or lance_ready,
                    vector_ok=lance_ready,
                    lance_ready=lance_ready,
                )
            else:
                if not source_exists:
                    asset_state = "missing_source"
                elif stored_state == "sync_failed" and not lance_ready:
                    asset_state = "sync_failed"
                elif not lance_ready and legacy_npy_exists:
                    asset_state = "broken_asset"
                elif not lance_ready:
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
                    # Legacy export fields kept for older tooling / migration UI.
                    "vector_file": legacy_npy_file,
                    "vector_exists": lance_ready,
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
