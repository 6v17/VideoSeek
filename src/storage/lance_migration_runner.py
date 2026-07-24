"""Startup migration: import legacy npy/faiss into Lance and remove redundant files."""

from __future__ import annotations

import json
import os
import shutil
from typing import Callable

from src.app.logging_utils import get_logger
from src.services.search_index_schema import mark_search_index_schema_upgraded
from src.storage.asset_store import load_metadata, save_metadata
from src.storage.lance_search_index import lance_search_is_ready
from src.storage.lance_store import import_npy_to_lance
from src.storage.migration_runner import _migration_state_file, _read_migration_state
from src.storage.video_id_migration import iter_model_asset_storage_roots

logger = get_logger("lance_migration_runner")

ProgressCallback = Callable[[int, str], None]


def _emit(progress_callback: ProgressCallback | None, percent: int, message: str) -> None:
    if callable(progress_callback):
        progress_callback(int(percent), str(message))


def _read_lance_migration_state(config) -> dict:
    state = _read_migration_state(config)
    payload = state.get("lance_migration")
    return payload if isinstance(payload, dict) else {}


def _write_lance_migration_state(config, payload: dict) -> None:
    state_file = _migration_state_file(config)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state = _read_migration_state(config)
    state["lance_migration"] = payload
    temp_path = f"{state_file}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, state_file)


def collect_legacy_vector_paths(profile_base_dir: str) -> list[str]:
    paths: list[str] = []
    vector_dir = os.path.join(profile_base_dir, "vector")
    index_dir = os.path.join(profile_base_dir, "index")
    global_dir = os.path.join(profile_base_dir, "global")

    for folder, suffix in ((vector_dir, "_vectors.npy"), (index_dir, "_index.faiss")):
        if not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            if name.lower().endswith(suffix.lower()):
                paths.append(os.path.join(folder, name))

    if os.path.isdir(global_dir):
        for name in os.listdir(global_dir):
            lower = name.lower()
            if lower.endswith(".faiss") or lower.endswith(".npy"):
                paths.append(os.path.join(global_dir, name))
        library_root = os.path.join(global_dir, "library_indexes")
        if os.path.isdir(library_root):
            paths.append(library_root)
    return paths


def profile_has_npy_vectors(profile_base_dir: str) -> bool:
    vector_dir = os.path.join(profile_base_dir, "vector")
    if not os.path.isdir(vector_dir):
        return False
    return any(name.lower().endswith("_vectors.npy") for name in os.listdir(vector_dir))


def cleanup_legacy_vector_paths(paths: list[str]) -> int:
    removed = 0
    for path in paths:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            elif os.path.isfile(path):
                os.remove(path)
            removed += 1
        except OSError as exc:
            logger.warning("Failed to remove legacy vector path %s: %s", path, exc)
    return removed


def cleanup_legacy_vector_files_for_profile(profile_base_dir: str) -> int:
    if not lance_search_is_ready(profile_base_dir):
        return 0
    return cleanup_legacy_vector_paths(collect_legacy_vector_paths(profile_base_dir))


def _estimate_path_bytes(path: str) -> int:
    try:
        if os.path.isfile(path):
            return int(os.path.getsize(path))
        if os.path.isdir(path):
            total = 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    file_path = os.path.join(root, name)
                    try:
                        total += int(os.path.getsize(file_path))
                    except OSError:
                        continue
            return total
    except OSError:
        return 0
    return 0


def cleanup_safe_legacy_vector_sidecars(*, config=None) -> dict:
    """User-facing cleanup of legacy npy/faiss after Lance search is ready.

    Uses the active model profile. Safe only when ``lance_search_is_ready``;
    search no longer reads these sidecars.
    """
    from src.app.config import load_config
    from src.storage.config_store import get_local_model_asset_dirs

    runtime_config = config or load_config()
    base_dir = get_local_model_asset_dirs(config=runtime_config)["base_dir"]
    if not lance_search_is_ready(base_dir):
        return {
            "ready": False,
            "removed": 0,
            "bytes_freed_estimate": 0,
            "message_key": "library_vectors_legacy_cleanup_not_ready",
            "profile_base_dir": base_dir,
        }

    pending = collect_legacy_vector_paths(base_dir)
    if not pending:
        return {
            "ready": True,
            "removed": 0,
            "bytes_freed_estimate": 0,
            "message_key": "library_vectors_legacy_cleanup_empty",
            "profile_base_dir": base_dir,
        }

    bytes_estimate = sum(_estimate_path_bytes(path) for path in pending)
    removed = cleanup_legacy_vector_files_for_profile(base_dir)
    return {
        "ready": True,
        "removed": int(removed),
        "bytes_freed_estimate": int(bytes_estimate),
        "message_key": "library_vectors_legacy_cleanup_done",
        "profile_base_dir": base_dir,
    }

def _mark_profile_search_index_ready(profile_base_dir: str) -> None:
    from src.storage.profile_library_store import get_library_db_path

    meta_file = os.path.join(profile_base_dir, "meta.json")
    if not os.path.isfile(meta_file) and not os.path.isfile(get_library_db_path(profile_base_dir)):
        return
    meta = load_metadata(meta_file)
    if not isinstance(meta, dict):
        return
    mark_search_index_schema_upgraded(meta)
    save_metadata(meta, meta_file)


def _legacy_cleanup_paths(paths: list[str]) -> list[str]:
    pending = []
    for path in paths:
        lower = str(path or "").lower()
        if lower.endswith("_vectors.npy"):
            continue
        if lower.endswith("_chunk_cache.npz"):
            continue
        pending.append(path)
    return pending


def is_lance_migration_completed(config=None) -> bool:
    from src.app.config import load_config

    state = _read_lance_migration_state(config or load_config())
    if not bool(state.get("completed")):
        return False
    # Partial imports must retry on the next startup.
    return int(state.get("videos_failed", 0) or 0) == 0


def needs_lance_startup_migration(config=None) -> bool:
    from src.app.config import load_config

    runtime_config = config or load_config()
    state = _read_lance_migration_state(runtime_config)
    # Once recorded complete with zero failures, do not re-listdir vector/index dirs
    # every startup. Sidecar ``*_vectors.npy`` may remain by design after import.
    if is_lance_migration_completed(runtime_config):
        return False

    # Previous run imported some videos but failed others — retry even if Lance
    # already looks "ready" from the partial table.
    if int(state.get("videos_failed", 0) or 0) > 0:
        return True

    profiles = list(iter_model_asset_storage_roots(config=runtime_config))
    if not profiles:
        return False

    pending_import = False
    pending_cleanup = False
    for root in profiles:
        base_dir = root["base_dir"]
        if profile_has_npy_vectors(base_dir) and not lance_search_is_ready(base_dir):
            pending_import = True
        if lance_search_is_ready(base_dir):
            legacy_paths = collect_legacy_vector_paths(base_dir)
            if legacy_paths:
                pending_cleanup = True

    return pending_import or pending_cleanup


def run_lance_startup_migration(config=None, progress_callback: ProgressCallback | None = None) -> dict:
    from src.app.config import load_config

    runtime_config = config or load_config()
    previous_state = _read_lance_migration_state(runtime_config)
    previous_failed = int(previous_state.get("videos_failed", 0) or 0)
    profiles = list(iter_model_asset_storage_roots(config=runtime_config))
    if not profiles:
        return {
            "upgraded": False,
            "libraries_built": 0,
            "libraries_cleared": 0,
            "libraries_skipped": 0,
            "global_built": False,
            "lance_profiles_migrated": 0,
            "lance_videos_imported": 0,
            "lance_videos_failed": 0,
            "lance_legacy_removed": 0,
        }

    total = len(profiles)
    profiles_migrated = 0
    videos_imported = 0
    videos_failed = 0
    legacy_removed = 0
    upgraded = False
    previously_complete = is_lance_migration_completed(runtime_config)

    for index, root in enumerate(profiles, start=1):
        base_dir = root["base_dir"]
        label = str(root.get("label", "") or os.path.basename(base_dir))
        percent = 90 + int((index - 1) * 8 / max(total, 1))
        _emit(progress_callback, percent, f"正在迁移 Lance 向量：{label}")

        profile_failed = 0
        needs_import = profile_has_npy_vectors(base_dir) and (
            not lance_search_is_ready(base_dir) or previous_failed > 0
        )
        if needs_import:
            summary = import_npy_to_lance(
                base_dir,
                replace_existing=True,
            )
            if summary.get("videos_imported"):
                profiles_migrated += 1
                upgraded = True
            videos_imported += int(summary.get("videos_imported", 0) or 0)
            profile_failed = int(summary.get("videos_failed", 0) or 0)
            videos_failed += profile_failed
            if summary.get("errors"):
                for error in summary["errors"][:3]:
                    logger.warning("Lance import issue (%s): %s", label, error)

        if lance_search_is_ready(base_dir):
            legacy_paths = collect_legacy_vector_paths(base_dir)
            # Keep ``*_vectors.npy`` when:
            # - migration was already fully complete (sidecars by design), or
            # - this profile still has import failures (needed for retry).
            if previously_complete or profile_failed > 0:
                legacy_paths = _legacy_cleanup_paths(legacy_paths)
            removed = cleanup_legacy_vector_paths(legacy_paths)
            if removed:
                legacy_removed += removed
                upgraded = True
            _mark_profile_search_index_ready(base_dir)

    completed = videos_failed == 0
    _write_lance_migration_state(
        runtime_config,
        {
            "completed": completed,
            "profiles_total": total,
            "profiles_migrated": profiles_migrated,
            "videos_imported": videos_imported,
            "videos_failed": videos_failed,
            "legacy_paths_removed": legacy_removed,
        },
    )
    if completed:
        _emit(progress_callback, 99, "Lance 向量迁移完成")
    else:
        _emit(
            progress_callback,
            99,
            f"Lance 向量迁移部分完成（失败 {videos_failed} 个视频，下次启动将重试）",
        )
        logger.warning(
            "Lance migration incomplete: videos_failed=%s imported=%s",
            videos_failed,
            videos_imported,
        )
    return {
        "upgraded": upgraded,
        "libraries_built": profiles_migrated,
        "libraries_cleared": 0,
        "libraries_skipped": 0,
        "global_built": False,
        "lance_profiles_migrated": profiles_migrated,
        "lance_videos_imported": videos_imported,
        "lance_videos_failed": videos_failed,
        "lance_legacy_removed": legacy_removed,
    }
