import gc
import hashlib
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

import numpy as np

from src.app.indexing_progress import IndexingProgressReporter
from src.app.logging_utils import get_logger
from src.core.semantic_chunking import build_semantic_chunks, chunk_builder_kwargs, normalize_chunk_config_snapshot
from src.core.extract_frames import FrameExtractionError
from src.storage.config_store import (
    build_chunk_config,
    get_active_embedding_spec,
    get_local_model_asset_dirs,
)
from src.infra.paths import ensure_folder_exists
from src.media.formats import VIDEO_EXTS
from src.storage.video_identity import (
    canonicalize_library_path,
    canonicalize_library_rel_path,
    get_legacy_video_hash,
    get_video_hash,
)


def get_video_duration_seconds(path):
    from src.media.probe import get_video_duration_seconds as _impl

    return _impl(path)


def has_readable_video_stream(path):
    from src.media.probe import has_readable_video_stream as _impl

    return _impl(path)

DISCOVER_CACHE_KEY = "discover_cache"
INFORMATIONAL_INDEX_ISSUE_REASONS = frozenset({"path_reconciled"})
_SKIP_VIDEO_ALREADY_INDEXED = object()
_INDEX_VIDEO_WORKERS_MIN = 1
_INDEX_VIDEO_WORKERS_MAX = 2
logger = get_logger("indexing_service")


def resolve_indexing_video_workers(config=None) -> int:
    """How many videos may compute (decode/embed) in parallel during a scan.

    Commits (meta / Lance) stay single-threaded. Env ``VIDEOSEEK_INDEX_VIDEO_WORKERS``
    overrides config when set.
    """
    raw_env = os.environ.get("VIDEOSEEK_INDEX_VIDEO_WORKERS", "").strip()
    if raw_env:
        try:
            return max(_INDEX_VIDEO_WORKERS_MIN, min(_INDEX_VIDEO_WORKERS_MAX, int(raw_env)))
        except ValueError:
            pass
    try:
        from src.app.config import DEFAULT_CONFIG

        default = int(DEFAULT_CONFIG.get("indexing_video_workers", 2))
    except Exception:
        default = 2
    try:
        value = int((config or {}).get("indexing_video_workers", default))
    except (TypeError, ValueError):
        value = default
    return max(_INDEX_VIDEO_WORKERS_MIN, min(_INDEX_VIDEO_WORKERS_MAX, value))


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
) -> bool:
    """Write frame/chunk rows to Lance. Returns True only on a successful upsert."""
    try:
        from src.storage.lance_store import upsert_profile_video_vectors_from_arrays

        if vectors is None or timestamps is None:
            logger.warning(
                "Skip Lance sync for %s: frame arrays required (legacy npy upsert removed)",
                video_id,
            )
            return False
        result = upsert_profile_video_vectors_from_arrays(
            video_id,
            vectors,
            timestamps,
            config=config,
            library_path=library_path or "",
            video_path=abs_path,
            chunks=chunks,
            chunk_config=chunk_config,
        )
        error = str((result or {}).get("error", "") or "").strip()
        if error:
            logger.error("Lance upsert rejected for %s: %s", video_id, error)
            return False
        return True
    except Exception as exc:
        logger.error("Failed to sync Lance vectors for %s: %s", video_id, exc, exc_info=True)
        return False


def _delete_lance_video_vectors(video_id, config) -> None:
    video_id = str(video_id or "").strip()
    if not video_id:
        return
    try:
        from src.storage.lance_store import delete_profile_video_vectors

        delete_profile_video_vectors(video_id, config=config)
    except Exception as exc:
        logger.warning("Failed to delete Lance vectors for old video id %s: %s", video_id, exc)


def _safe_delete_unreferenced_video_data(
    meta,
    video_id,
    config,
    *,
    exclude_library_path: str | None = None,
    exclude_rel_path: str | None = None,
    refresh_lance_state: bool = True,
) -> bool:
    """Delete Lance/legacy payloads only when no library file still references the id."""
    from src.services.library_service import count_video_id_refs
    from src.workflows.update_video import delete_physical_video_data

    video_id = str(video_id or "").strip()
    if not video_id:
        return False
    refs = count_video_id_refs(
        meta,
        video_id,
        exclude_library_path=exclude_library_path,
        exclude_rel_path=exclude_rel_path,
    )
    if refs > 0:
        logger.info(
            "Keeping shared index payload for video_id=%s (%s remaining reference(s))",
            video_id,
            refs,
        )
        return False
    try:
        delete_physical_video_data(
            video_id,
            config,
            refresh_lance_state=refresh_lance_state,
        )
    except TypeError:
        delete_physical_video_data(video_id, config)
    return True


def _mark_lance_sync_failed(
    lib_files,
    rel_path,
    video_id,
    video_mod_time,
    *,
    issue_callback,
    library_path,
    abs_path,
    detail="",
):
    metadata_updated = _upsert_file_record(
        lib_files,
        rel_path,
        video_id,
        video_mod_time,
        "sync_failed",
        sync_failure_reason="processing_error",
    )
    _emit_issue(
        issue_callback,
        library_path or "",
        rel_path,
        abs_path,
        action="skipped",
        reason="processing_error",
        detail=detail or "Lance vector sync failed.",
    )
    return metadata_updated


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


def _upsert_file_record(
    lib_files,
    rel_path,
    video_id,
    video_mod_time,
    asset_state,
    sync_failure_reason="",
    *,
    file_size=None,
    content_fp="",
):
    key = canonicalize_library_rel_path(rel_path)
    previous = dict(lib_files.get(key) or lib_files.get(rel_path) or {})
    updated = dict(previous)
    updated["vid"] = video_id
    updated["mod_time"] = video_mod_time
    updated["asset_state"] = asset_state
    if file_size is not None:
        try:
            updated["file_size"] = int(file_size)
        except (TypeError, ValueError):
            pass
    content_fp = str(content_fp or "").strip()
    if content_fp:
        updated["content_fp"] = content_fp
    if asset_state == "sync_failed":
        updated["sync_failure_reason"] = str(sync_failure_reason or "").strip().lower() or "processing_error"
    else:
        updated.pop("sync_failure_reason", None)
    if updated == previous and key in lib_files and rel_path == key:
        return False
    lib_files[key] = updated
    if rel_path != key and rel_path in lib_files:
        del lib_files[rel_path]
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
    """Find Lance vectors for this file even when meta vid no longer matches current hash."""
    saved_vid = str(saved.get("vid", "") or "").strip()
    try:
        video_mod_time = os.path.getmtime(abs_path)
    except OSError:
        video_mod_time = None

    # Fast path: unchanged mtime → reuse saved vid without hashing 10MiB.
    saved_mtime = saved.get("mod_time")
    if (
        video_mod_time is not None
        and saved_vid
        and saved_mtime is not None
        and float(saved_mtime) == float(video_mod_time)
    ):
        vectors, timestamps, _vector_file = _load_vectors_from_disk(saved_vid, config)
        if _has_usable_vectors(vectors, timestamps):
            return {
                "canonical_vid": saved_vid,
                "disk_vid": saved_vid,
                "vectors": vectors,
                "timestamps": timestamps,
            }

    try:
        current_vid = get_video_hash(abs_path)
    except OSError:
        return None

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
        return {
            "canonical_vid": current_vid,
            "disk_vid": disk_vid,
            "vectors": vectors,
            "timestamps": timestamps,
        }
    return None


def _try_reuse_lance_indexed_video(
    abs_path,
    saved,
    config,
    *,
    indexed_ids=None,
    library_path: str = "",
):
    """Skip vector load and Lance upsert when meta and Lance already agree on this file.

    Trusts ``mod_time`` before hashing. When ``indexed_ids`` is provided (scan batch
    cache), avoids per-video Lance count queries.

    If Lance still stores another library_path for this video_id (cross-library copy
    reuse), return None so the caller re-upserts and refreshes location columns used
    by library-scoped search.
    """
    if str(saved.get("asset_state", "")).strip().lower() != "ready":
        return None
    saved_vid = str(saved.get("vid", "") or "").strip()
    if not saved_vid:
        return None
    try:
        video_mod_time = os.path.getmtime(abs_path)
    except OSError:
        return None
    saved_mtime = saved.get("mod_time")
    if saved_mtime is None or float(saved_mtime) != float(video_mod_time):
        return None
    # mtime unchanged → keep saved_vid; do not re-hash the file body.
    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    if indexed_ids is not None:
        if saved_vid not in indexed_ids:
            return None
    else:
        from src.storage.lance_search_index import lance_video_has_vectors

        if not lance_video_has_vectors(profile_base_dir, saved_vid):
            return None
    want_lib = canonicalize_library_path(library_path) if library_path else ""
    if want_lib:
        from src.storage.lance_search_index import get_lance_video_library_path

        stored_lib = get_lance_video_library_path(profile_base_dir, saved_vid)
        if stored_lib and stored_lib != want_lib:
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

    from src.storage.lance_search_index import load_lance_video_chunks, load_lance_video_frame_arrays
    from src.storage.lance_store import get_stored_chunk_config

    profile_base_dir = model_dirs["base_dir"]
    current_chunk_config = build_chunk_config(config)
    existing = load_lance_video_chunks(profile_base_dir, video_id)
    saved_chunk_config = get_stored_chunk_config(profile_base_dir, video_id)
    if (
        existing
        and normalize_chunk_config_snapshot(saved_chunk_config) == current_chunk_config
    ):
        return existing

    vectors, timestamps = load_lance_video_frame_arrays(profile_base_dir, video_id)
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


def discover_video_files_incremental(root_path, lib_data):
    """Discover videos with per-directory snapshots.

    Always ``scandir`` every directory. An earlier optimization reused a whole
    cached subtree when a parent folder's *immediate* listing looked unchanged,
    which missed new files added deeper (e.g. drop into ``lib/A/B/``).
    ``scandir`` is cheap; missing brand-new videos is not.
    """
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


def _looks_like_video_file(abs_path: str) -> bool:
    """Cheap extension/size check — no ffprobe / OpenCV."""
    if _is_excluded_video_path(abs_path):
        return False
    if not os.path.isfile(abs_path):
        return False
    lower = abs_path.lower()
    if not lower.endswith(VIDEO_EXTS):
        return False
    try:
        return os.path.getsize(abs_path) > 0
    except OSError:
        return False


def _file_record_source_ready(root_path, rel_path):
    abs_path = os.path.join(root_path, rel_path)
    return os.path.exists(abs_path) and _is_valid_video_source(abs_path, probe=False)


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


def _content_fingerprint_for_path(abs_path) -> tuple[str, int]:
    """mtime-independent fingerprint: sha256(size + first 10MiB), plus size."""
    try:
        stat = os.stat(abs_path)
        size = int(stat.st_size)
    except OSError:
        return "", 0
    digest = hashlib.sha256()
    digest.update(str(size).encode("utf-8"))
    try:
        with open(abs_path, "rb") as handle:
            digest.update(handle.read(10 * 1024 * 1024))
    except OSError:
        return "", size
    return digest.hexdigest(), size


def _fingerprint_kwargs(abs_path) -> dict:
    content_fp, file_size = _content_fingerprint_for_path(abs_path)
    out = {}
    if file_size:
        out["file_size"] = file_size
    if content_fp:
        out["content_fp"] = content_fp
    return out


def _orphan_identity_map(root_path, lib_files, *, known_abs_paths=None) -> dict:
    """Map orphan rel_path -> identity for files present on disk but not source-ready in meta."""
    satisfied_paths = {
        canonicalize_library_rel_path(rel)
        for rel in list(lib_files.keys())
        if _file_record_source_ready(root_path, rel)
    }
    source_paths = known_abs_paths if known_abs_paths is not None else discover_video_files(root_path)
    identity_by_rel = {}
    for abs_path in source_paths:
        rel_path = canonicalize_library_rel_path(os.path.relpath(abs_path, root_path))
        if rel_path in satisfied_paths:
            continue
        if not _is_valid_video_source(abs_path, probe=False):
            continue
        current_vid, legacy_vid = _video_identity_for_path(abs_path)
        if not current_vid:
            continue
        content_fp, file_size = _content_fingerprint_for_path(abs_path)
        identity_by_rel[rel_path] = {
            "current_vid": current_vid,
            "legacy_vid": legacy_vid,
            "content_fp": content_fp,
            "file_size": file_size,
            "basename": os.path.basename(rel_path).lower(),
            "abs_path": abs_path,
        }
    return identity_by_rel


def _match_orphan_for_missing(info, identity_by_rel, used_candidates):
    """Return (matched_rel, identity) for a missing meta row, or (None, None)."""
    saved_vid = str(info.get("vid", "") or "").strip()
    saved_fp = str(info.get("content_fp", "") or "").strip()
    try:
        saved_size = int(info.get("file_size")) if info.get("file_size") is not None else None
    except (TypeError, ValueError):
        saved_size = None
    saved_name = os.path.basename(str(info.get("_rel_path", "") or "")).lower()

    # 1) Strong: video_id / legacy content hash
    if saved_vid:
        for rel_path, identity in identity_by_rel.items():
            if rel_path in used_candidates:
                continue
            if saved_vid in {identity.get("current_vid"), identity.get("legacy_vid")}:
                return rel_path, identity

    # 2) mtime-drift tolerant: content fingerprint recorded at last sync
    if saved_fp:
        for rel_path, identity in identity_by_rel.items():
            if rel_path in used_candidates:
                continue
            if identity.get("content_fp") and identity.get("content_fp") == saved_fp:
                return rel_path, identity

    # 3) Weak unique fallback: basename + size (only when unambiguous)
    if saved_size is not None and saved_name:
        hits = []
        for rel_path, identity in identity_by_rel.items():
            if rel_path in used_candidates:
                continue
            if identity.get("basename") == saved_name and int(identity.get("file_size") or -1) == saved_size:
                hits.append((rel_path, identity))
        if len(hits) == 1:
            return hits[0]

    return None, None


def _pop_library_rel_path(lib_files, rel_path) -> bool:
    """Delete all ``files`` keys that canonicalize to ``rel_path``."""
    want = canonicalize_library_rel_path(rel_path)
    removed = False
    for key in list(lib_files.keys()):
        if canonicalize_library_rel_path(key) == want:
            del lib_files[key]
            removed = True
    return removed


def _apply_source_transfer(lib_files, old_rel, info, matched_rel, identity) -> bool:
    """Move a meta row onto matched_rel inside lib_files. Returns True when applied."""
    saved_vid = str(info.get("vid", "") or "").strip()
    existing = lib_files.get(matched_rel) or lib_files.get(canonicalize_library_rel_path(matched_rel))
    if existing:
        existing_vid = str(existing.get("vid", "") or "").strip()
        if existing_vid and saved_vid and existing_vid != saved_vid:
            return False
        if existing_vid == saved_vid and canonicalize_library_rel_path(old_rel) != matched_rel:
            _pop_library_rel_path(lib_files, old_rel)
            return True

    transferred = dict(info)
    transferred.pop("_rel_path", None)
    transferred.pop("_library_path", None)
    matched_abs = str(identity.get("abs_path", "") or "")
    if matched_abs:
        try:
            transferred["mod_time"] = os.path.getmtime(matched_abs)
        except OSError:
            pass
    if identity.get("file_size"):
        transferred["file_size"] = int(identity["file_size"])
    if identity.get("content_fp"):
        transferred["content_fp"] = str(identity["content_fp"])
    # Source is back; keep prior readiness when vectors were already ready.
    if str(transferred.get("asset_state", "")).strip().lower() == "missing_source":
        transferred["asset_state"] = "ready"
    lib_files[matched_rel] = transferred
    if canonicalize_library_rel_path(old_rel) != matched_rel:
        _pop_library_rel_path(lib_files, old_rel)
    return True


def reconcile_library_file_paths(root_path, lib_files, *, known_abs_paths=None):
    """Align meta paths after in-library rename/move when video identity is unchanged."""
    if not root_path or not os.path.exists(root_path):
        return 0

    missing_entries = []
    for rel_path, info in list(lib_files.items()):
        if _file_record_source_ready(root_path, rel_path):
            continue
        row = dict(info)
        row["_rel_path"] = canonicalize_library_rel_path(rel_path)
        missing_entries.append((canonicalize_library_rel_path(rel_path), row))

    if not missing_entries:
        return 0

    identity_by_rel = _orphan_identity_map(root_path, lib_files, known_abs_paths=known_abs_paths)
    if not identity_by_rel:
        return collapse_duplicate_library_file_rows(root_path, lib_files)

    used_candidates = set()
    reconciled = 0
    for old_rel, info in missing_entries:
        matched_rel, identity = _match_orphan_for_missing(info, identity_by_rel, used_candidates)
        if not matched_rel or not identity:
            continue
        if not _apply_source_transfer(lib_files, old_rel, info, matched_rel, identity):
            continue
        reconciled += 1
        used_candidates.add(matched_rel)
        logger.info(
            "Reconciled relocated library file %s -> %s (video_id=%s)",
            old_rel,
            matched_rel,
            str(info.get("vid", "") or "").strip(),
        )

    collapsed = collapse_duplicate_library_file_rows(root_path, lib_files)
    return reconciled + collapsed


def collapse_duplicate_library_file_rows(root_path, lib_files) -> int:
    """Drop missing-source rows when the same video_id already has a living file.

    ``register_library_videos`` can add the renamed path before reconcile runs, so the
    new file is no longer an orphan and the old key would otherwise stay forever.
    """
    if not root_path or not isinstance(lib_files, dict):
        return 0
    by_vid: dict[str, list[str]] = {}
    for rel_path, info in list(lib_files.items()):
        if not isinstance(info, dict):
            continue
        video_id = str(info.get("vid", "") or "").strip()
        if not video_id:
            continue
        by_vid.setdefault(video_id, []).append(str(rel_path))
    dropped = 0
    for rels in by_vid.values():
        if len(rels) < 2:
            continue
        ready = [rel for rel in rels if _file_record_source_ready(root_path, rel)]
        if not ready:
            continue
        for rel in rels:
            if rel in ready:
                continue
            if _pop_library_rel_path(lib_files, rel):
                dropped += 1
                logger.info(
                    "Dropped stale library path %s (video_id still at %s)",
                    rel,
                    ready[0],
                )
    return dropped


def _library_files_dict(meta, library_path: str):
    """Return the mutable ``files`` dict for ``library_path``, or None."""
    want = canonicalize_library_path(library_path)
    libraries = (meta or {}).get("libraries") or {}
    for key, lib_data in libraries.items():
        if not isinstance(lib_data, dict):
            continue
        if canonicalize_library_path(key) != want:
            continue
        files = lib_data.setdefault("files", {})
        return files if isinstance(files, dict) else None
    return None


def relink_relocated_library_sources(meta, root_path, lib_files, *, known_abs_paths=None) -> int:
    """Relink indexed videos whose files reappeared under ``root_path`` (incl. cross-library).

    Does not manage folders — only repairs meta links so existing vectors keep working after
    users move files between libraries or into arbitrary subfolders. Lance path columns are
    refreshed later by the normal per-file sync/reuse path.
    """
    if not meta or not root_path or not os.path.exists(root_path):
        return 0

    target_root = canonicalize_library_path(root_path)
    identity_by_rel = _orphan_identity_map(root_path, lib_files, known_abs_paths=known_abs_paths)
    if not identity_by_rel:
        return 0

    missing_entries = []
    libraries = meta.get("libraries") or {}
    for lib_root, lib_data in list(libraries.items()):
        if not isinstance(lib_data, dict):
            continue
        files = lib_data.get("files") or {}
        if not isinstance(files, dict):
            continue
        canon_root = canonicalize_library_path(lib_root)
        # Same-library moves are handled by reconcile_library_file_paths.
        if canon_root == target_root:
            continue
        for rel_path, info in list(files.items()):
            if not isinstance(info, dict):
                continue
            if _file_record_source_ready(lib_root, rel_path):
                continue
            row = dict(info)
            row["_rel_path"] = canonicalize_library_rel_path(rel_path)
            missing_entries.append((canon_root, canonicalize_library_rel_path(rel_path), row))

    if not missing_entries:
        return 0

    used_candidates = set()
    relinked = 0
    for src_root, old_rel, info in missing_entries:
        saved_vid = str(info.get("vid", "") or "").strip()
        if not saved_vid and not str(info.get("content_fp", "") or "").strip():
            continue
        matched_rel, identity = _match_orphan_for_missing(info, identity_by_rel, used_candidates)
        if not matched_rel or not identity:
            continue

        existing = lib_files.get(matched_rel)
        if existing:
            existing_vid = str(existing.get("vid", "") or "").strip()
            if existing_vid and saved_vid and existing_vid != saved_vid:
                continue

        transferred = dict(info)
        transferred.pop("_rel_path", None)
        matched_abs = str(identity.get("abs_path", "") or "")
        if matched_abs:
            try:
                transferred["mod_time"] = os.path.getmtime(matched_abs)
            except OSError:
                pass
        if identity.get("file_size"):
            transferred["file_size"] = int(identity["file_size"])
        if identity.get("content_fp"):
            transferred["content_fp"] = str(identity["content_fp"])
        if str(transferred.get("asset_state", "")).strip().lower() in {"", "missing_source", "sync_failed"}:
            # Prefer ready so reuse path can refresh Lance location without re-embed.
            transferred["asset_state"] = "ready"
            transferred.pop("sync_failure_reason", None)
        lib_files[matched_rel] = transferred

        src_files = _library_files_dict(meta, src_root)
        if isinstance(src_files, dict):
            _pop_library_rel_path(src_files, old_rel)

        relinked += 1
        used_candidates.add(matched_rel)
        logger.info(
            "Relinked indexed video across libraries %s:%s -> %s:%s (video_id=%s)",
            src_root,
            old_rel,
            target_root,
            matched_rel,
            saved_vid,
        )

    return relinked


def _is_excluded_video_path(abs_path):
    normalized_parts = [part.lower() for part in os.path.normpath(abs_path).split(os.sep)]
    return "__macosx" in normalized_parts


def _is_valid_video_source(abs_path, *, probe: bool = True):
    if not _looks_like_video_file(abs_path):
        return False
    if not probe:
        return True
    return has_readable_video_stream(abs_path)


def cleanup_invalid_library_files(meta, config, target_lib=None, issue_callback=None):
    """Drop meta rows that are clearly not video files (no stream probe at 10k scale)."""
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
            if _looks_like_video_file(abs_path):
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


def _index_video_compute(
    abs_path,
    rel_path,
    saved,
    config,
    get_video_id,
    library_path=None,
    should_stop_callback=None,
    progress_callback=None,
    file_index=1,
    file_total=1,
    indexed_ids=None,
) -> dict[str, Any]:
    """Decode/embed (or decide reuse) without mutating meta or writing Lance.

    Returns a result dict consumed by ``_index_video_commit``.
    """
    del get_video_id  # hash via get_video_hash; callback kept for call-site parity
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
    rel_path = canonicalize_library_rel_path(rel_path)
    saved = dict(saved or {})
    had_saved_vid = bool(saved.get("vid"))
    base = {
        "abs_path": abs_path,
        "rel_path": rel_path,
        "library_path": library_path or "",
        "had_saved_vid": had_saved_vid,
        "file_index": file_index,
        "file_total": file_total,
    }

    if progress_reporter is not None:
        progress_reporter.emit("file", file_index, file_total, force=True)

    if not _is_valid_video_source(abs_path, probe=False):
        logger.warning("Skipping non-indexable video source: %s", abs_path)
        return {
            **base,
            "kind": "invalid_source",
            "detail": "Missing file or unsupported extension.",
            "video_mod_time": None,
        }

    video_mod_time = os.path.getmtime(abs_path)
    base["video_mod_time"] = video_mod_time
    forced_failure = _get_debug_forced_failure()
    if forced_failure is not None:
        raise forced_failure

    lance_cached = _try_reuse_lance_indexed_video(
        abs_path,
        saved,
        config,
        indexed_ids=indexed_ids,
        library_path=library_path or "",
    )
    if lance_cached is not None:
        video_id = lance_cached["canonical_vid"]
        if progress_reporter is not None:
            progress_reporter.emit("reuse", force=True)
        logger.info(
            "Per-video %s: reuse_lance_index %.2fs (vid=%s)",
            video_name,
            0.0,
            video_id,
        )
        return {
            **base,
            "kind": "lance_reuse",
            "video_id": video_id,
        }

    cached = _resolve_reusable_cached_vectors(abs_path, saved, config)
    if cached is not None:
        video_id = cached["canonical_vid"]
        vectors = cached["vectors"]
        timestamps = cached["timestamps"]
        disk_vid = cached["disk_vid"]
        t_reuse = time.perf_counter()
        if progress_reporter is not None:
            progress_reporter.emit("reuse", force=True)
        reuse_s = time.perf_counter() - t_reuse
        if disk_vid != video_id:
            logger.info(
                "Per-video %s: reuse_cached_vectors aligned id %s -> %s in %.2fs (%d frames)",
                video_name,
                disk_vid,
                video_id,
                reuse_s,
                len(timestamps),
            )
        else:
            logger.info(
                "Per-video %s: reuse_cached_vectors %.2fs (%d frames)",
                video_name,
                reuse_s,
                len(timestamps),
            )
        chunk_source_id = disk_vid if disk_vid != video_id else video_id
        chunks, chunks_rebuilt, chunk_config = _ensure_video_chunks(
            chunk_source_id,
            vectors,
            timestamps,
            config,
        )
        return {
            **base,
            "kind": "cache_reuse",
            "video_id": video_id,
            "disk_vid": disk_vid,
            "vectors": vectors,
            "timestamps": timestamps,
            "chunks": chunks,
            "chunk_config": chunk_config,
            "write_chunks": bool(chunks_rebuilt or disk_vid != video_id),
        }

    if not _is_valid_video_source(abs_path, probe=True):
        logger.warning("Skipping non-indexable video source: %s", abs_path)
        return {
            **base,
            "kind": "invalid_stream",
            "detail": "Unreadable or unsupported video stream.",
        }

    video_id = get_video_hash(abs_path)
    saved_vid = str(saved.get("vid", "") or "").strip()
    logger.info(
        "Reindexing %s (no reusable on-disk cache: saved_vid=%s current_vid=%s)",
        video_name,
        saved_vid or "-",
        video_id,
    )
    logger.info("Indexing video %s", video_name)
    model_dirs = get_local_model_asset_dirs(config=config)
    os.makedirs(model_dirs["vector_dir"], exist_ok=True)
    t_gen = time.perf_counter()
    from src.core.clip_embedding import generate_vectors_and_index_for_video

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
        video_name,
        gen_s,
    )
    if not _has_usable_vectors(vectors, timestamps):
        failure_reason = _classify_sync_failure_reason(abs_path, vectors, timestamps)
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
        return {
            **base,
            "kind": "generate_failed",
            "video_id": video_id,
            "failure_reason": failure_reason,
            "vectors": vectors,
            "timestamps": timestamps,
        }

    return {
        **base,
        "kind": "generated",
        "video_id": video_id,
        "vectors": vectors,
        "timestamps": timestamps,
        "chunks": chunks,
        "chunk_config": build_chunk_config(config),
    }


def _index_video_commit(
    lib_files,
    result: dict[str, Any],
    *,
    config,
    issue_callback=None,
    meta=None,
) -> tuple[Any, Any, bool, bool]:
    """Apply compute result: meta upsert + Lance write. Single-threaded only."""
    if not isinstance(result, dict):
        return None, None, False, False

    kind = str(result.get("kind") or "")
    abs_path = str(result.get("abs_path") or "")
    rel_path = canonicalize_library_rel_path(result.get("rel_path") or "")
    library_path = str(result.get("library_path") or "")
    video_mod_time = result.get("video_mod_time")
    had_saved_vid = bool(result.get("had_saved_vid"))
    video_id = str(result.get("video_id") or "").strip()

    if kind in {"invalid_source", "invalid_stream"}:
        _emit_issue(
            issue_callback,
            library_path,
            rel_path,
            abs_path,
            action="skipped",
            reason="invalid_video_source",
            detail=str(result.get("detail") or ""),
        )
        return None, None, False, False

    if kind == "lance_reuse":
        metadata_updated = _upsert_file_record(
            lib_files,
            rel_path,
            video_id,
            video_mod_time,
            "ready",
            **_fingerprint_kwargs(abs_path),
        )
        return _SKIP_VIDEO_ALREADY_INDEXED, None, metadata_updated, False

    if kind == "cache_reuse":
        vectors = result.get("vectors")
        timestamps = result.get("timestamps")
        disk_vid = str(result.get("disk_vid") or video_id)
        chunks = result.get("chunks")
        chunk_config = result.get("chunk_config")
        write_chunks = bool(result.get("write_chunks"))
        synced = _sync_video_vectors_to_lance(
            video_id,
            config,
            library_path,
            abs_path,
            vectors=vectors,
            timestamps=timestamps,
            chunks=chunks if write_chunks else None,
            chunk_config=chunk_config if write_chunks else None,
        )
        if not synced:
            metadata_updated = _mark_lance_sync_failed(
                lib_files,
                rel_path,
                video_id,
                video_mod_time,
                issue_callback=issue_callback,
                library_path=library_path,
                abs_path=abs_path,
                detail=f"reuse sync failed (disk_vid={disk_vid})",
            )
            return None, None, metadata_updated, had_saved_vid
        metadata_updated = _upsert_file_record(
            lib_files,
            rel_path,
            video_id,
            video_mod_time,
            "ready",
            **_fingerprint_kwargs(abs_path),
        )
        if disk_vid != video_id:
            ref_meta = meta
            if ref_meta is None:
                from src.storage.asset_store import load_model_metadata

                ref_meta = load_model_metadata(config=config)
            _safe_delete_unreferenced_video_data(
                ref_meta,
                disk_vid,
                config,
                exclude_library_path=library_path,
                exclude_rel_path=rel_path,
                refresh_lance_state=True,
            )
        return vectors, timestamps, metadata_updated, False

    if kind == "generate_failed":
        failure_reason = str(result.get("failure_reason") or "sync_failed")
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
            library_path,
            rel_path,
            abs_path,
            action="skipped",
            reason=failure_reason,
        )
        return None, None, metadata_updated, had_saved_vid

    if kind == "generated":
        vectors = result.get("vectors")
        timestamps = result.get("timestamps")
        chunks = result.get("chunks")
        chunk_config = result.get("chunk_config")
        synced = _sync_video_vectors_to_lance(
            video_id,
            config,
            library_path,
            abs_path,
            vectors=vectors,
            timestamps=timestamps,
            chunks=chunks,
            chunk_config=chunk_config,
        )
        if not synced:
            metadata_updated = _mark_lance_sync_failed(
                lib_files,
                rel_path,
                video_id,
                video_mod_time,
                issue_callback=issue_callback,
                library_path=library_path,
                abs_path=abs_path,
                detail="full index Lance sync failed",
            )
            return None, None, metadata_updated, had_saved_vid
        metadata_updated = _upsert_file_record(
            lib_files,
            rel_path,
            video_id,
            video_mod_time,
            "ready",
            **_fingerprint_kwargs(abs_path),
        )
        from src.core.timestamp_health import assess_index_timestamp_health

        health = assess_index_timestamp_health(abs_path, timestamps, config=config)
        if health.get("warnings"):
            _emit_issue(
                issue_callback,
                library_path,
                rel_path,
                abs_path,
                action="warning",
                reason="timestamp_drift",
                detail=health.get("detail", ""),
            )
        return vectors, timestamps, metadata_updated, True

    if kind == "error":
        exc = result.get("exc")
        failure_reason = str(
            result.get("failure_reason")
            or _classify_sync_failure_reason(abs_path, None, None, exc=exc if isinstance(exc, Exception) else None)
        )
        try:
            if video_mod_time is None and abs_path:
                video_mod_time = os.path.getmtime(abs_path)
        except OSError:
            video_mod_time = video_mod_time
        if not video_id and abs_path:
            try:
                video_id = get_video_hash(abs_path)
            except Exception:
                video_id = ""
        metadata_updated = False
        if video_id and video_mod_time is not None:
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
            library_path,
            rel_path,
            abs_path,
            action="skipped",
            reason=failure_reason,
            detail=str(result.get("detail") or ""),
        )
        return None, None, metadata_updated, had_saved_vid

    return None, None, False, False


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
    indexed_ids=None,
    meta=None,
):
    """Index one video: compute then commit (serial API for tests and workers=1)."""
    rel_path = canonicalize_library_rel_path(rel_path)
    saved = dict(lib_files.get(rel_path, {}))
    try:
        result = _index_video_compute(
            abs_path,
            rel_path,
            saved,
            config,
            get_video_id,
            library_path=library_path,
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
            file_index=file_index,
            file_total=file_total,
            indexed_ids=indexed_ids,
        )
    except InterruptedError:
        raise
    except Exception as exc:
        logger.exception("Failed to process video %s", abs_path)
        try:
            video_mod_time = os.path.getmtime(abs_path)
        except OSError:
            video_mod_time = None
        try:
            video_id = get_video_id(abs_path)
        except Exception:
            video_id = ""
        result = {
            "kind": "error",
            "abs_path": abs_path,
            "rel_path": rel_path,
            "library_path": library_path or "",
            "video_mod_time": video_mod_time,
            "video_id": video_id,
            "had_saved_vid": bool(saved.get("vid")),
            "failure_reason": _classify_sync_failure_reason(abs_path, None, None, exc=exc),
            "detail": _exception_detail(exc),
            "exc": exc,
        }
    try:
        return _index_video_commit(
            lib_files,
            result,
            config=config,
            issue_callback=issue_callback,
            meta=meta,
        )
    except Exception as exc:
        logger.warning(
            "Failed to persist skipped indexing issue for %s: %s",
            abs_path,
            exc,
            exc_info=True,
        )
        return None, None, False, bool(saved.get("vid"))


def _run_planned_videos_with_prefetch(
    planned_files,
    *,
    root_path,
    lib_files,
    config,
    get_video_id,
    issue_callback,
    should_stop_callback,
    progress_callback,
    indexed_ids,
    meta,
    workers: int,
    global_file_index_start: int,
    total_files: int,
    report_scan_progress,
    queue_meta_persist,
) -> tuple[list[str], bool, int]:
    """Compute up to ``workers`` videos ahead; commit in plan order on this thread."""
    failed_videos: list[str] = []
    search_assets_changed = False
    workers = max(_INDEX_VIDEO_WORKERS_MIN, min(_INDEX_VIDEO_WORKERS_MAX, int(workers or 1)))
    global_file_index = int(global_file_index_start)

    def _commit_one(abs_path: str, rel_path: str, file_index: int, result: dict[str, Any] | BaseException):
        nonlocal search_assets_changed
        report_scan_progress(file_index, total_files, library_path=root_path)
        if isinstance(result, BaseException):
            if isinstance(result, InterruptedError):
                raise result
            logger.exception("Failed to process video %s", abs_path, exc_info=result)
            saved = dict(lib_files.get(rel_path, {}))
            try:
                video_mod_time = os.path.getmtime(abs_path)
            except OSError:
                video_mod_time = None
            try:
                video_id = get_video_id(abs_path)
            except Exception:
                video_id = ""
            result = {
                "kind": "error",
                "abs_path": abs_path,
                "rel_path": rel_path,
                "library_path": root_path or "",
                "video_mod_time": video_mod_time,
                "video_id": video_id,
                "had_saved_vid": bool(saved.get("vid")),
                "failure_reason": _classify_sync_failure_reason(
                    abs_path, None, None, exc=result if isinstance(result, Exception) else None
                ),
                "detail": _exception_detail(result) if isinstance(result, Exception) else str(result),
                "exc": result if isinstance(result, Exception) else None,
            }
        vectors, _timestamps, metadata_updated, file_search_assets_changed = _index_video_commit(
            lib_files,
            result,
            config=config,
            issue_callback=issue_callback,
            meta=meta,
        )
        search_assets_changed = search_assets_changed or file_search_assets_changed
        if metadata_updated:
            queue_meta_persist()
        if vectors is _SKIP_VIDEO_ALREADY_INDEXED:
            return
        if vectors is None:
            failed_videos.append(abs_path)

    if workers <= 1:
        for abs_path in planned_files:
            if should_stop_callback and should_stop_callback():
                raise IndexUpdateInterrupted(
                    "Index update stopped before finishing current library",
                    search_assets_changed=search_assets_changed,
                )
            rel_path = canonicalize_library_rel_path(os.path.relpath(abs_path, root_path))
            global_file_index += 1
            report_scan_progress(global_file_index, total_files, library_path=root_path)
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
                indexed_ids=indexed_ids,
                meta=meta,
            )
            search_assets_changed = search_assets_changed or file_search_assets_changed
            if vectors is _SKIP_VIDEO_ALREADY_INDEXED:
                if metadata_updated:
                    queue_meta_persist()
                continue
            if metadata_updated:
                queue_meta_persist()
            if vectors is None:
                failed_videos.append(abs_path)
        return failed_videos, search_assets_changed, global_file_index

    pending: list[tuple[str, str, int, Future]] = []
    paths = list(planned_files)

    def _submit(executor: ThreadPoolExecutor, abs_path: str, file_index: int) -> tuple[str, str, int, Future]:
        rel_path = canonicalize_library_rel_path(os.path.relpath(abs_path, root_path))
        saved = dict(lib_files.get(rel_path, {}))
        future = executor.submit(
            _index_video_compute,
            abs_path,
            rel_path,
            saved,
            config,
            get_video_id,
            root_path,
            should_stop_callback,
            progress_callback,
            file_index,
            total_files or 1,
            indexed_ids,
        )
        return abs_path, rel_path, file_index, future

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="VSIndexPrefetch") as executor:
        path_iter = iter(paths)
        try:
            while True:
                if should_stop_callback and should_stop_callback():
                    for _a, _r, _i, fut in pending:
                        fut.cancel()
                    raise IndexUpdateInterrupted(
                        "Index update stopped before finishing current library",
                        search_assets_changed=search_assets_changed,
                    )
                while len(pending) < workers:
                    try:
                        abs_path = next(path_iter)
                    except StopIteration:
                        break
                    global_file_index += 1
                    pending.append(_submit(executor, abs_path, global_file_index))
                if not pending:
                    break
                abs_path, rel_path, file_index, future = pending.pop(0)
                try:
                    result = future.result()
                except InterruptedError:
                    for _a, _r, _i, fut in pending:
                        fut.cancel()
                    raise
                except Exception as exc:
                    result = exc
                _commit_one(abs_path, rel_path, file_index, result)
        except BaseException:
            for _a, _r, _i, fut in pending:
                fut.cancel()
            raise

    return failed_videos, search_assets_changed, global_file_index


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
    video_ids=None,
):
    from src.storage.lance_store import META_PERSIST_INTERVAL, begin_lance_index_batch, end_lance_index_batch
    from src.services.indexing_runtime_status import set_index_sync_progress

    selected_video_ids = None
    if video_ids is not None:
        selected_video_ids = {str(v).strip() for v in video_ids if str(v or "").strip()}

    search_assets_changed = False
    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    # One Lance id set for the whole scan — reuse path avoids per-file count queries.
    try:
        from src.storage.lance_search_index import get_lance_indexed_video_ids

        indexed_ids = get_lance_indexed_video_ids(profile_base_dir)
    except Exception as exc:
        logger.debug("Lance indexed-id cache unavailable for scan: %s", exc)
        indexed_ids = None
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

        from src.services.library_scan_selection import plan_library_scan_paths

        total_files = 0
        for root_path, lib_data, valid_files in scan_plan:
            lib_files = lib_data.get("files", {}) if isinstance(lib_data, dict) else {}
            total_files += len(
                plan_library_scan_paths(root_path, lib_files, valid_files, selected_video_ids)
            )

        if selected_video_ids is not None and selected_video_ids and total_files == 0:
            sample_root = scan_plan[0][0] if scan_plan else (target_lib or "")
            logger.error(
                "Index sync selection matched no on-disk files (%s ids, %s libraries). "
                "This usually means path-key mismatch or missing sources.",
                len(selected_video_ids),
                len(scan_plan),
            )
            _emit_issue(
                issue_callback,
                sample_root or "",
                "",
                sample_root or "",
                action="skipped",
                reason="selection_matched_none",
                detail=(
                    f"selected={len(selected_video_ids)} planned=0 libraries={len(scan_plan)}"
                ),
            )

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
            relinked_count = relink_relocated_library_sources(
                meta,
                root_path,
                lib_files,
                known_abs_paths=valid_files,
            )
            if relinked_count:
                _queue_meta_persist()

            planned_files = plan_library_scan_paths(
                root_path, lib_files, valid_files, selected_video_ids
            )
            try:
                workers = resolve_indexing_video_workers(config)
                if workers > 1:
                    logger.info(
                        "Index scan prefetch workers=%d for library %s (%d files)",
                        workers,
                        root_path,
                        len(planned_files),
                    )
                batch_failed, batch_changed, global_file_index = _run_planned_videos_with_prefetch(
                    planned_files,
                    root_path=root_path,
                    lib_files=lib_files,
                    config=config,
                    get_video_id=get_video_id,
                    issue_callback=issue_callback,
                    should_stop_callback=should_stop_callback,
                    progress_callback=progress_callback,
                    indexed_ids=indexed_ids,
                    meta=meta,
                    workers=workers,
                    global_file_index_start=global_file_index,
                    total_files=total_files or 1,
                    report_scan_progress=_report_scan_progress,
                    queue_meta_persist=_queue_meta_persist,
                )
                failed_videos.extend(batch_failed)
                search_assets_changed = search_assets_changed or batch_changed

                lib_data["files"] = lib_files
                if selected_video_ids is None:
                    discover_video_files_incremental(root_path, lib_data)
                lib_data["index_state"] = _library_index_state_after_scan(lib_data)
            except IndexUpdateInterrupted:
                lib_data["files"] = lib_files
                raise

        return failed_videos, search_assets_changed
    finally:
        _flush_meta(force=True)
        end_lance_index_batch(profile_base_dir)

