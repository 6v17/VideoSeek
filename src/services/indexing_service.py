import gc
import os
import time

import numpy as np

from src.app.indexing_progress import IndexingProgressReporter
from src.app.logging_utils import get_logger
from src.core.semantic_chunking import build_semantic_chunks, chunk_builder_kwargs, normalize_chunk_config_snapshot
from src.core.clip_embedding import generate_vectors_and_index_for_video
from src.core.extract_frames import FrameExtractionError
from src.core.timestamp_health import assess_index_timestamp_health
from src.storage.config_store import (
    build_chunk_config,
    get_active_embedding_spec,
    get_local_model_asset_dirs,
)
from src.utils import (
    canonicalize_library_path,
    ensure_folder_exists,
    get_legacy_video_hash,
    get_video_duration_seconds,
    get_video_hash,
    has_readable_video_stream,
)

VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm")
DISCOVER_CACHE_KEY = "discover_cache"
INFORMATIONAL_INDEX_ISSUE_REASONS = frozenset({"path_reconciled"})
_SKIP_VIDEO_ALREADY_INDEXED = object()
logger = get_logger("indexing_service")


def _sync_video_vectors_to_lance(
    video_id,
    config,
    library_path,
    abs_path,
    *,
    vectors=None,
    timestamps=None,
    chunks=None,
    chunk_config=None,
):
    try:
        from src.storage.lance_store import upsert_profile_video_vectors_from_arrays

        if vectors is None or timestamps is None:
            logger.warning(
                "Skip Lance sync for %s: frame arrays required (legacy npy upsert removed)",
                video_id,
            )
            return
        upsert_profile_video_vectors_from_arrays(
            video_id,
            vectors,
            timestamps,
            config=config,
            library_path=library_path or "",
            video_path=abs_path,
            chunks=chunks,
            chunk_config=chunk_config,
        )
    except Exception as exc:
        logger.warning("Failed to sync Lance vectors for %s: %s", video_id, exc)


class IndexUpdateInterrupted(InterruptedError):
    def __init__(self, message, search_assets_changed=False):
        super().__init__(message)
        self.search_assets_changed = bool(search_assets_changed)


def _has_usable_vectors(vectors, timestamps):
    if vectors is None or timestamps is None:
        return False
    try:
        vector_count = len(vectors)
        timestamp_count = len(timestamps)
    except TypeError:
        return False
    return vector_count > 0 and vector_count == timestamp_count


def _get_debug_forced_failure():
    gpu_flag = str(os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM", "") or "").strip().lower()
    if gpu_flag in {"1", "true", "yes", "on"}:
        return RuntimeError("DirectML debug injection: GPU out of memory")

    system_flag = str(os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM", "") or "").strip().lower()
    if system_flag in {"1", "true", "yes", "on"}:
        return MemoryError("Debug injection: system out of memory")

    return None


def _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, asset_state, sync_failure_reason=""):
    previous = dict(lib_files.get(rel_path, {}))
    updated = dict(previous)
    updated["vid"] = video_id
    updated["mod_time"] = video_mod_time
    updated["asset_state"] = asset_state
    if asset_state == "sync_failed":
        updated["sync_failure_reason"] = str(sync_failure_reason or "").strip().lower() or "processing_error"
    else:
        updated.pop("sync_failure_reason", None)
    if updated == previous:
        return False
    lib_files[rel_path] = updated
    return True


def _exception_detail(exc):
    if exc is None:
        return ""
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"


def _classify_exception_failure_reason(exc):
    detail = _exception_detail(exc).lower()
    if not detail:
        return "processing_error"

    oom_markers = (
        "out of memory",
        "not enough memory",
        "insufficient memory",
        "cannot allocate memory",
        "failed to allocate memory",
        "bad alloc",
        "bad_alloc",
        "memoryerror",
    )
    if not any(marker in detail for marker in oom_markers):
        return "processing_error"

    gpu_markers = (
        "gpu",
        "directml",
        "dml",
        "directx",
        "d3d12",
        "cuda",
        "vram",
        "video memory",
        "graphics memory",
    )
    if any(marker in detail for marker in gpu_markers):
        return "gpu_out_of_memory"
    return "system_out_of_memory"


def _classify_sync_failure_reason(abs_path, vectors, timestamps, exc=None):
    if exc is not None:
        if isinstance(exc, FrameExtractionError):
            if exc.frame_count > 0:
                return "processing_error"
            duration = get_video_duration_seconds(abs_path)
            if duration is not None and float(duration) < 1.0:
                return "too_short"
            return "no_frames"
        return _classify_exception_failure_reason(exc)
    if vectors is None or timestamps is None:
        duration = get_video_duration_seconds(abs_path)
        if duration is not None and float(duration) < 1.0:
            return "too_short"
        return "no_frames"
    if len(vectors) == 0 or len(timestamps) == 0:
        duration = get_video_duration_seconds(abs_path)
        if duration is not None and float(duration) < 1.0:
            return "too_short"
        return "no_frames"
    return "vector_timestamp_mismatch"


def _emit_issue(issue_callback, library_path, video_rel_path, abs_path, action, reason, detail=""):
    if not callable(issue_callback):
        return
    issue_callback(
        {
            "library_path": library_path,
            "video_rel_path": video_rel_path,
            "abs_path": abs_path,
            "action": str(action or "").strip().lower(),
            "reason": str(reason or "").strip().lower(),
            "detail": str(detail or "").strip(),
        }
    )


def is_index_problem_issue(issue):
    reason = str((issue or {}).get("reason", "") or "").strip().lower()
    return reason not in INFORMATIONAL_INDEX_ISSUE_REASONS


def filter_index_problem_issues(issues):
    return [item for item in (issues or []) if is_index_problem_issue(item)]


def _per_video_asset_paths(vector_dir, index_dir, video_id):
    return {
        "vectors": os.path.join(vector_dir, f"{video_id}_vectors.npy"),
        "index": os.path.join(index_dir, f"{video_id}_index.faiss"),
    }


def _rename_per_video_assets(vector_dir, index_dir, old_vid, new_vid):
    if not old_vid or not new_vid or old_vid == new_vid:
        return
    for key, folder, suffix in (
        ("vectors", vector_dir, "_vectors.npy"),
        ("index", index_dir, "_index.faiss"),
    ):
        src = os.path.join(folder, f"{old_vid}{suffix}")
        dst = os.path.join(folder, f"{new_vid}{suffix}")
        if os.path.isfile(src) and not os.path.isfile(dst):
            os.replace(src, dst)


def _load_vectors_from_disk(video_id, config):
    """Load frame vectors for a video id from Lance only.

    Legacy ``*_vectors.npy`` is migration-only. If Lance has no rows but an npy
    sidecar still exists, log a clear hint and return a miss so callers re-index
    or wait for startup Lance import.
    """
    from src.storage.lance_search_index import load_lance_video_frame_arrays

    model_dirs = get_local_model_asset_dirs(config=config)
    vector_file = os.path.join(model_dirs["vector_dir"], f"{video_id}_vectors.npy")
    vectors, timestamps = load_lance_video_frame_arrays(model_dirs["base_dir"], video_id)
    if _has_usable_vectors(vectors, timestamps):
        return vectors, timestamps, vector_file

    if os.path.isfile(vector_file):
        logger.warning(
            "Lance has no vectors for %s but legacy npy still exists (%s). "
            "Run startup migration or re-index; indexing no longer reads npy.",
            video_id,
            vector_file,
        )
    return None, None, vector_file


def _resolve_reusable_cached_vectors(abs_path, saved, config):
    """Find on-disk vectors for this file even when meta vid or mtime no longer match current hash."""
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_dir = model_dirs["vector_dir"]
    index_dir = model_dirs["index_dir"]
    try:
        current_vid = get_video_hash(abs_path)
    except OSError:
        return None

    saved_vid = str(saved.get("vid", "") or "").strip()
    candidate_ids = []
    for vid in (current_vid, saved_vid):
        if vid and vid not in candidate_ids:
            candidate_ids.append(vid)
    try:
        legacy_vid = get_legacy_video_hash(abs_path)
    except OSError:
        legacy_vid = ""
    if legacy_vid and legacy_vid not in candidate_ids:
        candidate_ids.append(legacy_vid)

    for disk_vid in candidate_ids:
        vectors, timestamps, _vector_file = _load_vectors_from_disk(disk_vid, config)
        if not _has_usable_vectors(vectors, timestamps):
            continue
        canonical_vid = current_vid
        if disk_vid != canonical_vid:
            paths = _per_video_asset_paths(vector_dir, index_dir, canonical_vid)
            if os.path.isfile(paths["vectors"]):
                vectors, timestamps, _ = _load_vectors_from_disk(canonical_vid, config)
                if not _has_usable_vectors(vectors, timestamps):
                    continue
            else:
                try:
                    _rename_per_video_assets(vector_dir, index_dir, disk_vid, canonical_vid)
                except OSError as exc:
                    logger.warning(
                        "Cannot align cached asset id %s -> %s for %s: %s",
                        disk_vid,
                        canonical_vid,
                        abs_path,
                        exc,
                    )
                    continue
        return {
            "canonical_vid": canonical_vid,
            "disk_vid": disk_vid,
            "vectors": vectors,
            "timestamps": timestamps,
        }
    return None


def _try_reuse_lance_indexed_video(abs_path, saved, config):
    """Skip vector load and Lance upsert when meta and Lance already agree on this file."""
    from src.storage.lance_search_index import lance_video_has_vectors

    if str(saved.get("asset_state", "")).strip().lower() != "ready":
        return None
    saved_vid = str(saved.get("vid", "") or "").strip()
    if not saved_vid:
        return None
    try:
        current_vid = get_video_hash(abs_path)
        video_mod_time = os.path.getmtime(abs_path)
    except OSError:
        return None
    if saved_vid != current_vid:
        return None
    saved_mtime = saved.get("mod_time")
    if saved_mtime is None or float(saved_mtime) != float(video_mod_time):
        return None
    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    if not lance_video_has_vectors(profile_base_dir, saved_vid):
        return None
    return {"canonical_vid": saved_vid}


def load_video_vectors_by_id(video_id, config):
    vectors, timestamps, _vector_file = _load_vectors_from_disk(video_id, config)
    return vectors, timestamps


def load_video_chunks_by_id(video_id, config):
    model_dirs = get_local_model_asset_dirs(config=config)
    video_id = str(video_id or "").strip()
    if not video_id:
        return []

    from src.storage.lance_search_index import load_lance_video_frame_arrays

    vectors, timestamps = load_lance_video_frame_arrays(model_dirs["base_dir"], video_id)
    if not _has_usable_vectors(vectors, timestamps):
        return []
    chunks, rebuilt, chunk_config = _ensure_video_chunks(
        video_id,
        vectors,
        timestamps,
        config,
    )
    if rebuilt:
        from src.storage.lance_store import upsert_profile_video_vectors_from_arrays

        upsert_profile_video_vectors_from_arrays(
            video_id,
            vectors,
            timestamps,
            config=config,
            chunks=chunks,
            chunk_config=chunk_config,
        )
    return chunks


def _ensure_video_chunks(video_id, vectors, timestamps, config):
    from src.storage.lance_store import get_stored_chunk_config
    from src.storage.lance_search_index import load_lance_video_chunks

    current_chunk_config = build_chunk_config(config)
    video_id = str(video_id or "").strip()

    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    chunks = load_lance_video_chunks(profile_base_dir, video_id)
    saved_chunk_config = get_stored_chunk_config(profile_base_dir, video_id)
    if (
        chunks
        and normalize_chunk_config_snapshot(saved_chunk_config) == current_chunk_config
    ):
        return chunks, False, current_chunk_config

    logger.info("Rebuilding semantic chunks in Lance for video %s", video_id)
    chunks = build_semantic_chunks(
        vectors,
        timestamps,
        **chunk_builder_kwargs(current_chunk_config),
    )
    return chunks, True, current_chunk_config


def _selected_missing_entry_keys(selected_entries):
    keys = set()
    for entry in selected_entries or []:
        library_path = str(entry.get("library_path", "")).strip()
        video_rel_path = str(entry.get("video_rel_path", "")).strip()
        if not library_path or not video_rel_path:
            continue
        keys.add((canonicalize_library_path(library_path), video_rel_path))
    return keys


def cleanup_missing_library_files(meta, config, target_lib=None, selected_entries=None):
    selected_keys = _selected_missing_entry_keys(selected_entries)
    for entry in list_missing_library_files(meta, config, target_lib):
        if selected_keys:
            entry_key = (
                canonicalize_library_path(entry["library_path"]),
                entry["video_rel_path"],
            )
            if entry_key not in selected_keys:
                continue
        lib_files = meta["libraries"][entry["library_path"]].get("files", {})
        rel_path = entry["video_rel_path"]
        if rel_path in lib_files:
            yield lib_files[rel_path].get("vid")
            del lib_files[rel_path]


def list_missing_library_files(meta, config, target_lib=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in list(meta["libraries"].items()):
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            logger.info("Skipping missing-file cleanup for offline library root: %s", root_path)
            continue

        lib_files = lib_data.get("files", {})
        for rel_path in list(lib_files.keys()):
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                yield {
                    "library_path": root_path,
                    "video_rel_path": rel_path,
                    "abs_path": abs_path,
                    "video_id": lib_files[rel_path].get("vid"),
                }


def discover_video_files(root_path):
    valid_files = []
    for current_root, dir_names, files in os.walk(root_path):
        dir_names[:] = [name for name in dir_names if name.lower() != "__macosx"]
        for filename in files:
            if filename.lower().endswith(VIDEO_EXTS):
                valid_files.append(os.path.join(current_root, filename))
    return valid_files


def _discover_snapshot_key(rel_dir: str) -> str:
    return rel_dir if rel_dir and rel_dir != "." else "."


def _snapshot_directory_videos(abs_dir: str) -> dict | None:
    try:
        entries = list(os.scandir(abs_dir))
    except OSError:
        return None
    videos = []
    subdirs = []
    max_mtime_ns = 0
    for entry in entries:
        name = entry.name
        if name.lower() == "__macosx":
            continue
        try:
            if entry.is_dir(follow_symlinks=False):
                subdirs.append(name)
            elif entry.is_file(follow_symlinks=False) and name.lower().endswith(VIDEO_EXTS):
                videos.append(name)
                max_mtime_ns = max(max_mtime_ns, entry.stat(follow_symlinks=False).st_mtime_ns)
        except OSError:
            continue
    return {
        "videos": sorted(videos),
        "subdirs": sorted(subdirs),
        "max_mtime_ns": max_mtime_ns,
    }


def _build_dir_snapshots_from_walk(root_path: str) -> dict[str, dict]:
    snapshots: dict[str, dict] = {}
    for current_root, dir_names, files in os.walk(root_path):
        dir_names[:] = [name for name in dir_names if name.lower() != "__macosx"]
        rel_dir = os.path.relpath(current_root, root_path)
        rel_key = _discover_snapshot_key(rel_dir)
        videos = sorted(name for name in files if name.lower().endswith(VIDEO_EXTS))
        subdirs = sorted(name for name in dir_names if name.lower() != "__macosx")
        max_mtime_ns = 0
        for name in videos:
            try:
                max_mtime_ns = max(max_mtime_ns, os.stat(os.path.join(current_root, name)).st_mtime_ns)
            except OSError:
                continue
        snapshots[rel_key] = {
            "videos": videos,
            "subdirs": subdirs,
            "max_mtime_ns": max_mtime_ns,
        }
    return snapshots


def _append_snapshotted_subtree(
    root_path: str,
    rel_dir: str,
    dir_snapshots: dict[str, dict],
    discovered: list[str],
    updated_snapshots: dict[str, dict],
) -> None:
    rel_key = _discover_snapshot_key(rel_dir)
    snap = dir_snapshots.get(rel_key)
    if not snap:
        return
    abs_dir = root_path if rel_key == "." else os.path.join(root_path, rel_dir)
    for name in snap.get("videos", []):
        discovered.append(os.path.join(abs_dir, name))
    updated_snapshots[rel_key] = snap
    prefix = "" if rel_key == "." else f"{rel_key}{os.sep}"
    for key, value in dir_snapshots.items():
        if key == rel_key or key in updated_snapshots:
            continue
        if rel_key != "." and not key.startswith(prefix):
            continue
        sub_rel = "" if key == "." else key
        sub_abs = root_path if key == "." else os.path.join(root_path, sub_rel)
        for name in value.get("videos", []):
            discovered.append(os.path.join(sub_abs, name))
        updated_snapshots[key] = value


def discover_video_files_incremental(root_path, lib_data):
    cache = lib_data.get(DISCOVER_CACHE_KEY) or {}
    dir_snapshots = dict(cache.get("dir_snapshots") or {})
    if not dir_snapshots:
        return refresh_library_video_file_list(root_path, lib_data)

    discovered: list[str] = []
    updated_snapshots: dict[str, dict] = {}

    def visit(abs_dir: str, rel_dir: str) -> None:
        snap = _snapshot_directory_videos(abs_dir)
        if snap is None:
            return
        rel_key = _discover_snapshot_key(rel_dir)
        for name in snap["videos"]:
            discovered.append(os.path.join(abs_dir, name))
        updated_snapshots[rel_key] = snap
        for subdir in snap["subdirs"]:
            if subdir.lower() == "__macosx":
                continue
            sub_abs = os.path.join(abs_dir, subdir)
            sub_rel = os.path.join(rel_dir, subdir) if rel_dir else subdir
            sub_key = _discover_snapshot_key(sub_rel)
            sub_snap = _snapshot_directory_videos(sub_abs)
            if sub_snap is None:
                continue
            if dir_snapshots.get(sub_key) == sub_snap:
                _append_snapshotted_subtree(root_path, sub_rel, dir_snapshots, discovered, updated_snapshots)
            else:
                visit(sub_abs, sub_rel)

    visit(root_path, "")
    discovered.sort()
    rel_paths = sorted(os.path.relpath(path, root_path) for path in discovered)
    lib_data[DISCOVER_CACHE_KEY] = {
        "rel_paths": rel_paths,
        "dir_snapshots": updated_snapshots,
    }
    return discovered


def refresh_library_video_file_list(root_path, lib_data):
    abs_paths = discover_video_files(root_path)
    rel_paths = sorted(os.path.relpath(path, root_path) for path in abs_paths)
    lib_data[DISCOVER_CACHE_KEY] = {
        "rel_paths": rel_paths,
        "dir_snapshots": _build_dir_snapshots_from_walk(root_path),
    }
    return abs_paths


def load_library_video_file_list(root_path, lib_data, *, refresh=False):
    if refresh or not isinstance(lib_data.get(DISCOVER_CACHE_KEY), dict):
        return refresh_library_video_file_list(root_path, lib_data)

    rel_paths = lib_data.get(DISCOVER_CACHE_KEY, {}).get("rel_paths")
    if not isinstance(rel_paths, list):
        return refresh_library_video_file_list(root_path, lib_data)

    abs_paths = []
    stale = False
    for rel_path in rel_paths:
        abs_path = os.path.join(root_path, rel_path)
        if os.path.isfile(abs_path):
            abs_paths.append(abs_path)
        else:
            stale = True
    if stale:
        return refresh_library_video_file_list(root_path, lib_data)
    return abs_paths


def _library_index_state_after_scan(lib_data) -> str:
    if bool((lib_data or {}).get("files", {})):
        return "ready"
    return "pending"


def _collect_library_scan_plan(meta, target_lib=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    plan = []
    for root_path, lib_data in meta.get("libraries", {}).items():
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue
        if not isinstance(lib_data, dict):
            lib_data = {}
            meta["libraries"][root_path] = lib_data
        abs_paths = discover_video_files_incremental(root_path, lib_data)
        plan.append((root_path, lib_data, abs_paths))
    return plan


def _file_record_source_ready(root_path, rel_path):
    abs_path = os.path.join(root_path, rel_path)
    return os.path.exists(abs_path) and _is_valid_video_source(abs_path)


def _video_identity_for_path(abs_path):
    try:
        current_vid = get_video_hash(abs_path)
    except OSError:
        return None, None
    try:
        legacy_vid = get_legacy_video_hash(abs_path)
    except OSError:
        legacy_vid = ""
    return current_vid, legacy_vid


def reconcile_library_file_paths(root_path, lib_files, *, known_abs_paths=None):
    """Align meta paths after in-library rename/move when video content (video_id) is unchanged."""
    if not root_path or not os.path.exists(root_path):
        return 0

    missing_entries = []
    satisfied_paths = set()
    for rel_path, info in list(lib_files.items()):
        if _file_record_source_ready(root_path, rel_path):
            satisfied_paths.add(rel_path)
            continue
        missing_entries.append((rel_path, dict(info)))

    if not missing_entries:
        return 0

    orphan_candidates = []
    source_paths = known_abs_paths if known_abs_paths is not None else discover_video_files(root_path)
    for abs_path in source_paths:
        rel_path = os.path.relpath(abs_path, root_path)
        if rel_path in satisfied_paths:
            continue
        if not _is_valid_video_source(abs_path):
            continue
        orphan_candidates.append((rel_path, abs_path))

    if not orphan_candidates:
        return 0

    identity_by_rel = {}
    for rel_path, abs_path in orphan_candidates:
        current_vid, legacy_vid = _video_identity_for_path(abs_path)
        if not current_vid:
            continue
        identity_by_rel[rel_path] = {
            "current_vid": current_vid,
            "legacy_vid": legacy_vid,
            "abs_path": abs_path,
        }

    used_candidates = set()
    reconciled = 0
    for old_rel, info in missing_entries:
        saved_vid = str(info.get("vid", "") or "").strip()
        if not saved_vid:
            continue

        matched_rel = None
        matched_abs = ""
        for rel_path, identity in identity_by_rel.items():
            if rel_path in used_candidates:
                continue
            current_vid = identity.get("current_vid")
            legacy_vid = identity.get("legacy_vid")
            if saved_vid not in {current_vid, legacy_vid}:
                continue
            matched_rel = rel_path
            matched_abs = identity.get("abs_path", "")
            break

        if not matched_rel:
            continue

        existing = lib_files.get(matched_rel)
        if existing:
            existing_vid = str(existing.get("vid", "") or "").strip()
            if existing_vid and existing_vid != saved_vid:
                continue
            if existing_vid == saved_vid and old_rel != matched_rel:
                del lib_files[old_rel]
                reconciled += 1
                used_candidates.add(matched_rel)
                continue

        transferred = dict(info)
        if matched_abs:
            try:
                transferred["mod_time"] = os.path.getmtime(matched_abs)
            except OSError:
                pass
        lib_files[matched_rel] = transferred
        if old_rel != matched_rel and old_rel in lib_files:
            del lib_files[old_rel]
        reconciled += 1
        used_candidates.add(matched_rel)
        logger.info(
            "Reconciled relocated library file %s -> %s (video_id=%s)",
            old_rel,
            matched_rel,
            saved_vid,
        )

    return reconciled


def _is_excluded_video_path(abs_path):
    normalized_parts = [part.lower() for part in os.path.normpath(abs_path).split(os.sep)]
    return "__macosx" in normalized_parts


def _is_valid_video_source(abs_path):
    if _is_excluded_video_path(abs_path):
        return False
    return has_readable_video_stream(abs_path)


def cleanup_invalid_library_files(meta, config, target_lib=None, issue_callback=None):
    target_key = canonicalize_library_path(target_lib) if target_lib else None
    for root_path, lib_data in list(meta["libraries"].items()):
        if target_key and canonicalize_library_path(root_path) != target_key:
            continue
        if not os.path.exists(root_path):
            continue

        lib_files = lib_data.get("files", {})
        for rel_path in list(lib_files.keys()):
            abs_path = os.path.join(root_path, rel_path)
            if not os.path.exists(abs_path):
                continue
            if _is_valid_video_source(abs_path):
                continue

            video_id = lib_files[rel_path].get("vid")
            del lib_files[rel_path]
            logger.warning("Removed invalid video source from library metadata: %s", abs_path)
            _emit_issue(
                issue_callback,
                root_path,
                rel_path,
                abs_path,
                action="cleaned",
                reason="invalid_video_source",
            )
            yield video_id


def process_single_video(
    abs_path,
    rel_path,
    lib_files,
    config,
    get_video_id,
    library_path=None,
    issue_callback=None,
    should_stop_callback=None,
    progress_callback=None,
    file_index=1,
    file_total=1,
):
    video_name = os.path.basename(abs_path)
    progress_reporter = (
        IndexingProgressReporter(
            progress_callback,
            video_name=video_name,
            file_index=file_index,
            file_total=file_total,
        )
        if progress_callback
        else None
    )
    try:
        if progress_reporter is not None:
            progress_reporter.emit("file", file_index, file_total, force=True)

        video_mod_time = os.path.getmtime(abs_path)
        if not _is_valid_video_source(abs_path):
            logger.warning("Skipping non-indexable video source: %s", abs_path)
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="skipped",
                reason="invalid_video_source",
                detail="Unreadable or unsupported video stream.",
            )
            return None, None, False, False

        saved = lib_files.get(rel_path, {})
        forced_failure = _get_debug_forced_failure()
        if forced_failure is not None:
            raise forced_failure

        lance_cached = _try_reuse_lance_indexed_video(abs_path, saved, config)
        if lance_cached is not None:
            video_id = lance_cached["canonical_vid"]
            metadata_updated = _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, "ready")
            if progress_reporter is not None:
                progress_reporter.emit("reuse", force=True)
            logger.info(
                "Per-video %s: reuse_lance_index %.2fs (vid=%s)",
                os.path.basename(abs_path),
                0.0,
                video_id,
            )
            return _SKIP_VIDEO_ALREADY_INDEXED, None, metadata_updated, False

        cached = _resolve_reusable_cached_vectors(abs_path, saved, config)
        if cached is not None:
            video_id = cached["canonical_vid"]
            vectors = cached["vectors"]
            timestamps = cached["timestamps"]
            disk_vid = cached["disk_vid"]
            t_reuse = time.perf_counter()
            metadata_updated = _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, "ready")
            if progress_reporter is not None:
                progress_reporter.emit("reuse", force=True)
            reuse_s = time.perf_counter() - t_reuse
            if disk_vid != video_id:
                logger.info(
                    "Per-video %s: reuse_cached_vectors aligned id %s -> %s in %.2fs (%d frames)",
                    os.path.basename(abs_path),
                    disk_vid,
                    video_id,
                    reuse_s,
                    len(timestamps),
                )
            else:
                logger.info(
                    "Per-video %s: reuse_cached_vectors %.2fs (%d frames)",
                    os.path.basename(abs_path),
                    reuse_s,
                    len(timestamps),
                )
            chunks, chunks_rebuilt, chunk_config = _ensure_video_chunks(
                video_id,
                vectors,
                timestamps,
                config,
            )
            _sync_video_vectors_to_lance(
                video_id,
                config,
                library_path,
                abs_path,
                vectors=vectors,
                timestamps=timestamps,
                chunks=chunks if chunks_rebuilt else None,
                chunk_config=chunk_config if chunks_rebuilt else None,
            )
            return vectors, timestamps, metadata_updated, False

        video_id = get_video_hash(abs_path)
        saved_vid = str(saved.get("vid", "") or "").strip()
        logger.info(
            "Reindexing %s (no reusable on-disk cache: saved_vid=%s current_vid=%s)",
            os.path.basename(abs_path),
            saved_vid or "-",
            video_id,
        )
        logger.info("Indexing video %s", os.path.basename(abs_path))
        model_dirs = get_local_model_asset_dirs(config=config)
        os.makedirs(model_dirs["vector_dir"], exist_ok=True)
        t_gen = time.perf_counter()
        vectors, timestamps, _, chunks = generate_vectors_and_index_for_video(
            abs_path,
            video_id,
            model_dirs["index_dir"],
            model_dirs["vector_dir"],
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
            file_index=file_index,
            file_total=file_total,
        )
        gen_s = time.perf_counter() - t_gen
        logger.info(
            "Per-video %s: generate_vectors_and_index_for_video wall %.2fs",
            os.path.basename(abs_path),
            gen_s,
        )
        if not _has_usable_vectors(vectors, timestamps):
            failure_reason = _classify_sync_failure_reason(abs_path, vectors, timestamps)
            metadata_updated = _upsert_file_record(
                lib_files,
                rel_path,
                video_id,
                video_mod_time,
                "sync_failed",
                sync_failure_reason=failure_reason,
            )
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="skipped",
                reason=failure_reason,
            )
            if vectors is None or timestamps is None:
                logger.warning("Vector generation failed for %s and the file was marked sync_failed", abs_path)
            elif len(vectors) == 0 or len(timestamps) == 0:
                logger.warning("Vector generation returned empty data for %s and the file was marked sync_failed", abs_path)
            else:
                logger.warning(
                    "Vector/timestamp counts differ for %s; marked sync_failed: vectors=%s timestamps=%s",
                    abs_path,
                    len(vectors),
                    len(timestamps),
                )
            return None, None, metadata_updated, bool(saved.get("vid"))
        metadata_updated = _upsert_file_record(lib_files, rel_path, video_id, video_mod_time, "ready")
        health = assess_index_timestamp_health(abs_path, timestamps, config=config)
        if health.get("warnings"):
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="warning",
                reason="timestamp_drift",
                detail=health.get("detail", ""),
            )
        _sync_video_vectors_to_lance(
            video_id,
            config,
            library_path,
            abs_path,
            vectors=vectors,
            timestamps=timestamps,
            chunks=chunks,
            chunk_config=build_chunk_config(config),
        )
        return vectors, timestamps, metadata_updated, True
    except InterruptedError:
        raise
    except Exception as exc:
        logger.exception("Failed to process video %s", abs_path)
        metadata_updated = False
        search_assets_changed = False
        try:
            saved = dict(lib_files.get(rel_path, {}))
            video_id = get_video_id(abs_path)
            video_mod_time = os.path.getmtime(abs_path)
            failure_reason = _classify_sync_failure_reason(abs_path, None, None, exc=exc)
            metadata_updated = _upsert_file_record(
                lib_files,
                rel_path,
                video_id,
                video_mod_time,
                "sync_failed",
                sync_failure_reason=failure_reason,
            )
            _emit_issue(
                issue_callback,
                library_path or "",
                rel_path,
                abs_path,
                action="skipped",
                reason=failure_reason,
                detail=_exception_detail(exc),
            )
            search_assets_changed = bool(saved.get("vid"))
        except Exception as exc:
            logger.warning(
                "Failed to persist skipped indexing issue for %s: %s",
                abs_path,
                exc,
                exc_info=True,
            )
        return None, None, metadata_updated, search_assets_changed


def scan_target_libraries(
    meta,
    config,
    get_video_id,
    target_lib=None,
    progress_callback=None,
    persist_meta_callback=None,
    should_stop_callback=None,
    issue_callback=None,
    include_existing_assets=True,
):
    from src.storage.lance_store import META_PERSIST_INTERVAL, begin_lance_index_batch, end_lance_index_batch
    from src.services.indexing_runtime_status import set_index_sync_progress

    search_assets_changed = False
    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    begin_lance_index_batch(profile_base_dir, progress_callback=progress_callback)
    pending_meta_saves = 0

    def _report_scan_progress(current: int, total: int, library_path: str = "") -> None:
        set_index_sync_progress(current=current, total=total, library_path=library_path)
        if not progress_callback:
            return
        percent = int((current / max(total, 1)) * 100)
        progress_callback(
            percent,
            f"index_progress|scan|{current}|{total}|0|0|{os.path.basename(library_path) if library_path else ''}",
        )

    def _flush_meta(*, force: bool = False) -> None:
        nonlocal pending_meta_saves
        if not persist_meta_callback:
            return
        if force or pending_meta_saves >= META_PERSIST_INTERVAL:
            persist_meta_callback()
            pending_meta_saves = 0

    def _queue_meta_persist() -> None:
        nonlocal pending_meta_saves
        if not persist_meta_callback:
            return
        pending_meta_saves += 1
        _flush_meta(force=False)

    try:
        for video_id in list(cleanup_invalid_library_files(meta, config, target_lib, issue_callback=issue_callback)):
            if video_id:
                search_assets_changed = True
                model_dirs = get_local_model_asset_dirs(config=config)
                vector_dir = model_dirs.get("vector_dir", "")
                index_dir = model_dirs.get("index_dir", "")
                vector_file = os.path.join(vector_dir, f"{video_id}_vectors.npy") if vector_dir else ""
                index_file = os.path.join(index_dir, f"{video_id}_index.faiss") if index_dir else ""
                for path in (vector_file, index_file):
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except OSError:
                            logger.warning("Failed to remove invalid video asset %s", path)
            _queue_meta_persist()

        failed_videos = []
        scan_plan = _collect_library_scan_plan(meta, target_lib=target_lib)
        total_files = sum(len(abs_paths) for _root, _lib_data, abs_paths in scan_plan)
        global_file_index = 0
        _report_scan_progress(0, total_files)

        for root_path, lib_data, valid_files in scan_plan:
            if should_stop_callback and should_stop_callback():
                raise IndexUpdateInterrupted(
                    "Index update stopped before finishing library scan",
                    search_assets_changed=search_assets_changed,
                )

            lib_data["index_state"] = "partial"
            lib_files = lib_data.get("files", {})
            reconciled_count = reconcile_library_file_paths(
                root_path,
                lib_files,
                known_abs_paths=valid_files,
            )
            if reconciled_count:
                _queue_meta_persist()

            try:
                for abs_path in valid_files:
                    if should_stop_callback and should_stop_callback():
                        raise IndexUpdateInterrupted(
                            "Index update stopped before finishing current library",
                            search_assets_changed=search_assets_changed,
                        )
                    rel_path = os.path.relpath(abs_path, root_path)
                    global_file_index += 1
                    _report_scan_progress(global_file_index, total_files, library_path=root_path)

                    vectors, timestamps, metadata_updated, file_search_assets_changed = process_single_video(
                        abs_path,
                        rel_path,
                        lib_files,
                        config,
                        get_video_id,
                        library_path=root_path,
                        issue_callback=issue_callback,
                        should_stop_callback=should_stop_callback,
                        progress_callback=progress_callback,
                        file_index=global_file_index,
                        file_total=total_files or 1,
                    )
                    search_assets_changed = search_assets_changed or file_search_assets_changed
                    if vectors is _SKIP_VIDEO_ALREADY_INDEXED:
                        if metadata_updated:
                            _queue_meta_persist()
                        continue
                    if metadata_updated:
                        _queue_meta_persist()
                    if vectors is None:
                        failed_videos.append(abs_path)

                lib_data["files"] = lib_files
                discover_video_files_incremental(root_path, lib_data)
                lib_data["index_state"] = _library_index_state_after_scan(lib_data)
            except IndexUpdateInterrupted:
                lib_data["files"] = lib_files
                raise

        return failed_videos, search_assets_changed
    finally:
        _flush_meta(force=True)
        end_lance_index_batch(profile_base_dir)

