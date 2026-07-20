import json
import os
import shutil
import time

from src.app.config import get_configured_data_root, load_config, save_config
from src.app.logging_utils import get_logger
from src.storage.asset_store import load_metadata, load_numpy_payload, save_metadata, save_numpy_payload
from src.services.model_package_service import ensure_default_clip_manifest
from src.storage.config_store import (
    get_active_model_profile,
    get_active_model_resource_dir,
    get_global_model_asset_paths,
    get_local_model_asset_dirs,
    get_model_profile_storage_paths,
    resolve_provider_dir,
)
from src.storage.video_id_migration import (
    VIDEO_ID_FORMAT_VERSION,
    _legacy_video_ids_pending_fast,
    _trust_fast_video_id_check,
    legacy_npy_vectors_present,
    migrate_legacy_video_ids,
)

logger = get_logger("migration_runner")
TARGET_SCHEMA_VERSION = 2
DEFAULT_MODEL_PROFILE_ID = "clip_onnx_default"
DEFAULT_EMBEDDING_SPEC = {
    "model_id": DEFAULT_MODEL_PROFILE_ID,
    "provider": "clip_onnx",
    "embedding_space": "clip_onnx_default",
    "dimension": 512,
    "metric": "ip",
}


def _emit(progress_callback, percent, message):
    if callable(progress_callback):
        progress_callback(int(percent), str(message))


def _migration_state_file(config):
    data_root = get_configured_data_root(config)
    data_dir = os.path.join(data_root, "data")
    return os.path.join(data_dir, "migration_state.json")


def _read_schema_version(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _read_migration_state(config):
    state_file = _migration_state_file(config)
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _ensure_expected_asset_dirs(config):
    """Create empty asset folders so a completed migration is not re-run after missing dirs."""
    try:
        model_dirs = get_local_model_asset_dirs(config=config)
        global_paths = get_global_model_asset_paths(config=config)
        for path in (
            model_dirs.get("vector_dir"),
            model_dirs.get("index_dir"),
            model_dirs.get("base_dir"),
            global_paths.get("global_dir"),
            os.path.dirname(model_dirs.get("meta_file", "") or ""),
        ):
            if path:
                os.makedirs(path, exist_ok=True)
    except Exception:
        logger.warning("Failed to ensure expected asset directories exist", exc_info=True)


def _profile_meta_store_exists(meta_file: str) -> bool:
    """True when profile metadata exists as meta.json and/or library.db."""
    path = os.path.normpath(str(meta_file or ""))
    if not path:
        return False
    if os.path.exists(path):
        return True
    # After the SQLite library store switch, meta may live only in library.db.
    library_db = os.path.join(os.path.dirname(path), "library.db")
    return os.path.isfile(library_db)


def _already_migrated(config, meta):
    config_version = _read_schema_version(config.get("schema_version"), default=1)
    meta_version = _read_schema_version(meta.get("schema_version"), default=1)
    if not (config_version >= TARGET_SCHEMA_VERSION and meta_version >= TARGET_SCHEMA_VERSION):
        return False
    state = _read_migration_state(config)
    if not (bool(state.get("completed")) and _read_schema_version(state.get("schema_version"), default=0) >= TARGET_SCHEMA_VERSION):
        return False
    _ensure_expected_asset_dirs(config)
    try:
        model_dirs = get_local_model_asset_dirs(config=config)
    except Exception:
        return False
    if not (os.path.isdir(model_dirs["vector_dir"]) and os.path.isdir(model_dirs["index_dir"])):
        return False
    if not _profile_meta_store_exists(model_dirs["meta_file"]):
        return False
    try:
        global_paths = get_global_model_asset_paths(config=config)
    except Exception:
        return False
    if not os.path.isdir(global_paths["global_dir"]):
        return False
    return True


def ensure_config_schema_v2_bootstrap():
    """Upgrade config.json to schema v2 before the UI reads model profiles.

    Disk layout migration (vectors, meta, etc.) may still run later via ``begin_startup_migration``.
    """
    config = load_config()
    if _read_schema_version(config.get("schema_version"), default=1) >= TARGET_SCHEMA_VERSION:
        return config
    logger.info("Bootstrapping config schema_version to %s before main window", TARGET_SCHEMA_VERSION)
    save_config(_normalize_config_v2(config))
    return load_config()


def _normalize_config_v2(config):
    normalized = dict(config)
    original_version = _read_schema_version(config.get("schema_version"), default=1)
    normalized["schema_version"] = TARGET_SCHEMA_VERSION
    models = normalized.get("models")
    if not isinstance(models, dict):
        models = {}

    profiles = models.get("profiles")
    should_seed_default_profile = original_version < TARGET_SCHEMA_VERSION
    if not isinstance(profiles, list):
        profiles = []
    if should_seed_default_profile and not profiles:
        profiles = [
            {
                "id": DEFAULT_MODEL_PROFILE_ID,
                "provider": "clip_onnx",
                "display_name": "OpenAI CLIP",
                "enabled": True,
                "runtime": {
                    "prefer_gpu": bool(normalized.get("prefer_gpu", True)),
                    "model_dir": str(normalized.get("model_dir", "") or ""),
                },
                "files": {
                    "visual_model": "clip_visual.onnx",
                    "text_model": "clip_text.onnx",
                    "tokenizer_vocab": "bpe_simple_vocab_16e6.txt.gz",
                },
                "capabilities": {
                    "text_query": True,
                    "image_query": True,
                    "video_embedding": True,
                    "cross_modal_search": True,
                },
            }
        ]
    models["profiles"] = profiles
    active_profile = str(models.get("active_profile", "") or "").strip()
    if not active_profile and profiles:
        active_profile = str(profiles[0].get("id", "") or "").strip()
    models["active_profile"] = active_profile
    normalized["models"] = models
    return normalized


def _normalize_meta_v2(meta, config):
    normalized = dict(meta or {})
    normalized["schema_version"] = TARGET_SCHEMA_VERSION
    normalized.setdefault("libraries", {})

    global_state = str(normalized.get("global_index_state", "fresh") or "fresh").strip().lower()
    if global_state not in {"fresh", "stale"}:
        global_state = "fresh"

    global_indexes = normalized.get("global_indexes")
    if not isinstance(global_indexes, dict):
        global_indexes = {}
    global_paths = get_global_model_asset_paths(config=config)
    if DEFAULT_MODEL_PROFILE_ID not in global_indexes:
        global_indexes[DEFAULT_MODEL_PROFILE_ID] = {
            "state": global_state,
            "frame": {
                "index_file": global_paths["cross_index_file"],
                "metadata_file": global_paths["cross_vector_file"],
                "embedding_space": DEFAULT_EMBEDDING_SPEC["embedding_space"],
            },
            "chunk": {
                "index_file": global_paths["cross_chunk_index_file"],
                "metadata_file": global_paths["cross_chunk_vector_file"],
                "embedding_space": DEFAULT_EMBEDDING_SPEC["embedding_space"],
            },
        }
    normalized["global_indexes"] = global_indexes
    return normalized


def _inject_embedding_spec(payload, asset_type):
    if not isinstance(payload, dict):
        return payload, False
    changed = False
    if _read_schema_version(payload.get("schema_version"), default=1) < TARGET_SCHEMA_VERSION:
        payload["schema_version"] = TARGET_SCHEMA_VERSION
        changed = True
    if str(payload.get("asset_type", "") or "").strip() != asset_type:
        payload["asset_type"] = asset_type
        changed = True
    spec = payload.get("embedding_spec")
    if not isinstance(spec, dict):
        payload["embedding_spec"] = dict(DEFAULT_EMBEDDING_SPEC)
        changed = True
    else:
        for key, value in DEFAULT_EMBEDDING_SPEC.items():
            if key not in spec:
                spec[key] = value
                changed = True
    return payload, changed


def _migrate_vector_dir_payloads(config):
    model_dirs = get_local_model_asset_dirs(config=config)
    vector_dir = str(model_dirs["vector_dir"] or "").strip()
    if not vector_dir or not os.path.isdir(vector_dir):
        return 0
    migrated = 0
    for file_name in os.listdir(vector_dir):
        if not file_name.lower().endswith("_vectors.npy"):
            continue
        path = os.path.join(vector_dir, file_name)
        try:
            payload = load_numpy_payload(path)
        except Exception as exc:
            logger.warning("Skipping unreadable vector payload during migration: %s (%s)", path, exc)
            continue
        payload, changed = _inject_embedding_spec(payload, asset_type="video_frame_vectors")
        if not changed:
            continue
        save_numpy_payload(path, payload)
        migrated += 1
    return migrated


def _migrate_local_asset_dirs(config):
    profile = get_active_model_profile(config=config)
    profile_id = str(profile.get("id", "") or "").strip()
    data_root = get_configured_data_root(config)
    legacy_model_base = os.path.join(data_root, "data", "model_assets", profile_id) if profile_id else ""
    model_dirs = get_local_model_asset_dirs(config=config)
    target_vector_dir = model_dirs["vector_dir"]
    target_index_dir = model_dirs["index_dir"]
    os.makedirs(target_vector_dir, exist_ok=True)
    os.makedirs(target_index_dir, exist_ok=True)

    migrated_files = 0
    legacy_vector_dir = str(config.get("vector_dir", "") or "").strip()
    legacy_index_dir = str(config.get("index_dir", "") or "").strip()
    for src_dir, dst_dir, suffix in (
        (legacy_vector_dir, target_vector_dir, "_vectors.npy"),
        (legacy_index_dir, target_index_dir, "_index.faiss"),
        (os.path.join(legacy_model_base, "vector"), target_vector_dir, "_vectors.npy"),
        (os.path.join(legacy_model_base, "index"), target_index_dir, "_index.faiss"),
    ):
        if not src_dir or not os.path.isdir(src_dir):
            continue
        if os.path.normcase(os.path.normpath(src_dir)) == os.path.normcase(os.path.normpath(dst_dir)):
            continue
        for name in os.listdir(src_dir):
            if not name.lower().endswith(suffix.lower()):
                continue
            src_file = os.path.join(src_dir, name)
            dst_file = os.path.join(dst_dir, name)
            if os.path.exists(dst_file):
                continue
            shutil.move(src_file, dst_file)
            migrated_files += 1
    return migrated_files


def _migrate_meta_file(config):
    model_paths = get_model_profile_storage_paths(config=config)
    target_meta = model_paths["meta_file"]
    os.makedirs(os.path.dirname(target_meta), exist_ok=True)
    legacy_meta = str(config.get("meta_file", "") or "").strip()
    profile = get_active_model_profile(config=config)
    profile_id = str(profile.get("id", "") or "").strip()
    legacy_model_meta = (
        os.path.join(get_configured_data_root(config), "data", "model_assets", profile_id, "meta.json")
        if profile_id
        else ""
    )
    if (not legacy_meta or not os.path.exists(legacy_meta)) and legacy_model_meta and os.path.exists(legacy_model_meta):
        legacy_meta = legacy_model_meta
    if legacy_meta and os.path.exists(legacy_meta):
        if os.path.normcase(os.path.normpath(legacy_meta)) == os.path.normcase(os.path.normpath(target_meta)):
            return 0
        if not os.path.exists(target_meta):
            shutil.move(legacy_meta, target_meta)
            return 1
    if not os.path.exists(target_meta):
        # Profile metadata may already live only in library.db (no meta.json).
        # Seeding an empty {"libraries": {}} through save_metadata would wipe
        # existing SQLite library/video rows via save_profile_meta.
        profile_base = os.path.dirname(os.path.normpath(target_meta))
        library_db = os.path.join(profile_base, "library.db")
        if os.path.isfile(library_db):
            logger.info(
                "Skip empty meta.json seed: library.db already present at %s",
                library_db,
            )
            return 0
        save_metadata({"schema_version": TARGET_SCHEMA_VERSION, "libraries": {}}, target_meta)
    return 0


def _migrate_global_asset_files(config):
    profile = get_active_model_profile(config=config)
    profile_id = str(profile.get("id", "") or "").strip()
    legacy_global_dir = (
        os.path.join(get_configured_data_root(config), "data", "model_assets", profile_id, "global")
        if profile_id
        else ""
    )
    global_paths = get_global_model_asset_paths(config=config)
    os.makedirs(global_paths["global_dir"], exist_ok=True)

    migrated_files = 0
    legacy_targets = (
        (str(config.get("cross_index_file", "") or "").strip(), global_paths["cross_index_file"]),
        (str(config.get("cross_vector_file", "") or "").strip(), global_paths["cross_vector_file"]),
        (str(config.get("cross_chunk_index_file", "") or "").strip(), global_paths["cross_chunk_index_file"]),
        (str(config.get("cross_chunk_vector_file", "") or "").strip(), global_paths["cross_chunk_vector_file"]),
        (os.path.join(legacy_global_dir, "cross_video_index.faiss"), global_paths["cross_index_file"]),
        (os.path.join(legacy_global_dir, "cross_video_vectors.npy"), global_paths["cross_vector_file"]),
        (os.path.join(legacy_global_dir, "cross_chunk_index.faiss"), global_paths["cross_chunk_index_file"]),
        (os.path.join(legacy_global_dir, "cross_chunk_vectors.npy"), global_paths["cross_chunk_vector_file"]),
    )
    for legacy_file, target_file in legacy_targets:
        if not legacy_file or not os.path.exists(legacy_file):
            continue
        if os.path.normcase(os.path.normpath(legacy_file)) == os.path.normcase(os.path.normpath(target_file)):
            continue
        os.makedirs(os.path.dirname(target_file), exist_ok=True)
        if os.path.exists(target_file):
            continue
        shutil.move(legacy_file, target_file)
        migrated_files += 1
    return migrated_files


def _migrate_model_resource_files(config):
    profile = get_active_model_profile(config=config)
    files = dict(profile.get("files") or {})
    target_dir = get_active_model_resource_dir(config=config)
    os.makedirs(target_dir, exist_ok=True)
    runtime = dict(profile.get("runtime") or {})
    legacy_root = str(runtime.get("model_dir", "") or "").strip()
    migrated_files = 0
    provider = str(profile.get("provider", "") or "").strip()
    profile_id = str(profile.get("id", "") or "").strip()
    model_variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip() or "vit-base-patch32"
    provider_dir = resolve_provider_dir(provider)
    legacy_provider_dirs = {provider_dir, provider.replace("_", "-"), provider}
    if provider == "chinese_clip_onnx":
        legacy_provider_dirs.add("chinese-clip-onnx")
    legacy_candidate_dirs = []
    if legacy_root:
        for item in legacy_provider_dirs:
            if not item:
                continue
            legacy_candidate_dirs.extend(
                [
                    os.path.join(legacy_root, item),
                    os.path.join(legacy_root, item, "32"),
                    os.path.join(legacy_root, item, model_variant),
                    os.path.join(legacy_root, item, profile_id),
                    os.path.join(legacy_root, item, profile_id, "32"),
                    os.path.join(legacy_root, item, profile_id, model_variant),
                ]
            )
        legacy_candidate_dirs.extend(
            [
                legacy_root,
            ]
        )
    deduped_dirs = []
    seen = set()
    for directory in legacy_candidate_dirs:
        normalized = os.path.normcase(os.path.normpath(str(directory or "")))
        if not normalized or normalized in seen:
            continue
        deduped_dirs.append(directory)
        seen.add(normalized)

    for file_name in files.values():
        name = str(file_name or "").strip()
        if not name:
            continue
        dst = os.path.join(target_dir, name)
        if os.path.exists(dst):
            continue
        for directory in deduped_dirs:
            src = os.path.join(directory, name)
            if not os.path.exists(src):
                continue
            if os.path.normcase(os.path.normpath(src)) == os.path.normcase(os.path.normpath(dst)):
                continue
            shutil.move(src, dst)
            migrated_files += 1
            break
    return migrated_files


def _cleanup_legacy_empty_dirs(config):
    removed = 0
    data_root = get_configured_data_root(config)
    data_dir = os.path.join(data_root, "data")
    model_paths = get_model_profile_storage_paths(config=config)
    profile = get_active_model_profile(config=config)
    provider = str(profile.get("provider", "") or "").strip()
    profile_id = str(profile.get("id", "") or "").strip()

    candidates = [
        str(config.get("vector_dir", "") or "").strip(),
        str(config.get("index_dir", "") or "").strip(),
        str(config.get("cross_index_file", "") or "").strip(),
        str(config.get("cross_vector_file", "") or "").strip(),
        str(config.get("cross_chunk_index_file", "") or "").strip(),
        str(config.get("cross_chunk_vector_file", "") or "").strip(),
        str(config.get("remote_index_file", "") or "").strip(),
        str(config.get("remote_vector_file", "") or "").strip(),
        os.path.join(data_dir, "global"),
        os.path.join(data_dir, "remote"),
        os.path.join(data_root, "models", provider, profile_id, "32"),
        os.path.join(data_root, "models", provider, profile_id),
        os.path.join(data_root, "models", provider, "32"),
        os.path.join(data_root, "models", provider),
    ]
    for path in candidates:
        if not path:
            continue
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        folder = os.path.normpath(folder)
        if not folder or not os.path.isdir(folder):
            continue
        if os.path.normcase(folder).startswith(os.path.normcase(model_paths["base_dir"])):
            continue
        try:
            if os.listdir(folder):
                continue
            os.rmdir(folder)
            removed += 1
        except OSError:
            continue
    return removed


def _migrate_global_payloads(config):
    global_paths = get_global_model_asset_paths(config=config)
    targets = [
        (global_paths["cross_vector_file"], "global_frame_index_meta"),
        (global_paths["cross_chunk_vector_file"], "global_chunk_index_meta"),
    ]
    migrated = 0
    for path, asset_type in targets:
        path = str(path or "").strip()
        if not path or not os.path.exists(path):
            continue
        try:
            payload = load_numpy_payload(path)
        except Exception as exc:
            logger.warning("Skipping unreadable global payload during migration: %s (%s)", path, exc)
            continue
        payload, changed = _inject_embedding_spec(payload, asset_type=asset_type)
        if not changed:
            continue
        save_numpy_payload(path, payload)
        migrated += 1
    return migrated


def _data_dir_has_user_payload(config):
    """True when ``data/`` exists and contains at least one file (new installs are skipped)."""
    data_dir = os.path.join(get_configured_data_root(config), "data")
    if not os.path.isdir(data_dir):
        return False
    try:
        for _root, _dirs, files in os.walk(data_dir):
            if files:
                return True
    except OSError:
        return False
    return False


def _create_backup(config):
    if not _data_dir_has_user_payload(config):
        return ""
    data_root = get_configured_data_root(config)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    backup_root = os.path.join(data_root, f"data.backup-pre-v{TARGET_SCHEMA_VERSION}-{timestamp}")
    data_dir = os.path.join(data_root, "data")
    shutil.copytree(data_dir, backup_root)
    return backup_root


def _prune_backup_dirs(config, keep_count=1):
    data_root = get_configured_data_root(config)
    if not os.path.isdir(data_root):
        return 0
    prefix = f"data.backup-pre-v{TARGET_SCHEMA_VERSION}-"
    backup_dirs = []
    for name in os.listdir(data_root):
        if not name.startswith(prefix):
            continue
        full_path = os.path.join(data_root, name)
        if os.path.isdir(full_path):
            backup_dirs.append((os.path.getmtime(full_path), full_path))
    backup_dirs.sort(reverse=True)
    removed = 0
    for _, path in backup_dirs[max(0, int(keep_count)):]:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError:
            continue
    return removed


def _write_migration_state(config, backup_dir):
    state_file = _migration_state_file(config)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    # Preserve Lance / video-id stamps written by later maintenance steps.
    payload = dict(_read_migration_state(config))
    payload.update(
        {
            "completed": True,
            "schema_version": TARGET_SCHEMA_VERSION,
            "finished_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "backup_dir": backup_dir,
        }
    )
    temp_path = f"{state_file}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, state_file)


def needs_search_index_schema_migration(config=None):
    """True when Lance startup migration still has pending import/cleanup work."""
    runtime_config = config or load_config()
    try:
        from src.storage.lance_migration_runner import needs_lance_startup_migration

        return needs_lance_startup_migration(runtime_config)
    except Exception:
        logger.warning("Failed to evaluate search index schema migration need", exc_info=True)
        return False


def _empty_search_index_migration_result(**extra):
    payload = {
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
    payload.update(extra)
    return payload


def _migrate_search_index_v2(config, progress_callback=None):
    from src.storage.lance_migration_runner import (
        needs_lance_startup_migration,
        run_lance_startup_migration,
    )

    if needs_lance_startup_migration(config):
        logger.info("Running Lance vector startup migration")
        return run_lance_startup_migration(config, progress_callback=progress_callback)

    logger.info("Lance vector storage is active; no FAISS search index migration required.")
    return _empty_search_index_migration_result()


def _apply_post_schema_maintenance(config, progress_callback=None):
    _emit(progress_callback, 8, "正在检查视频索引 ID")
    video_id_result = migrate_legacy_video_ids(config=config, progress_callback=progress_callback)
    search_index_result = _migrate_search_index_v2(config, progress_callback=progress_callback)
    return video_id_result, search_index_result


def _attach_maintenance_summary(payload, video_id_result, search_index_result):
    merged = dict(payload or {})
    merged["migrated_video_ids"] = int(video_id_result.get("migrated_video_ids", 0) or 0)
    merged["failed_video_ids"] = int(video_id_result.get("failed_video_ids", 0) or 0)
    merged["video_id_format"] = int(video_id_result.get("video_id_format", VIDEO_ID_FORMAT_VERSION))
    merged["pending_legacy"] = bool(video_id_result.get("pending_legacy"))
    merged["search_index_upgraded"] = bool(search_index_result.get("upgraded"))
    merged["search_index_libraries_built"] = int(search_index_result.get("libraries_built", 0) or 0)
    merged["search_index_global_built"] = bool(search_index_result.get("global_built"))
    merged["lance_videos_imported"] = int(search_index_result.get("lance_videos_imported", 0) or 0)
    merged["lance_videos_failed"] = int(search_index_result.get("lance_videos_failed", 0) or 0)
    merged["lance_legacy_removed"] = int(search_index_result.get("lance_legacy_removed", 0) or 0)
    if search_index_result.get("upgraded"):
        merged["migrated"] = True
    return merged


def _load_meta_for_startup(config):
    config_version = _read_schema_version(config.get("schema_version"), default=1)
    if config_version >= TARGET_SCHEMA_VERSION:
        model_paths = get_model_profile_storage_paths(config=config)
        existing_meta_file = model_paths["meta_file"]
        if not os.path.exists(existing_meta_file):
            legacy_meta_file = str(config.get("meta_file", "") or "").strip()
            existing_meta_file = (
                legacy_meta_file if legacy_meta_file and os.path.exists(legacy_meta_file) else model_paths["meta_file"]
            )
    else:
        existing_meta_file = str(config.get("meta_file", "") or "").strip()
        if not existing_meta_file:
            data_root = get_configured_data_root(config)
            existing_meta_file = os.path.join(data_root, "data", "meta.json")
    return load_metadata(existing_meta_file)


def needs_background_startup_migration(config=None):
    """True when startup must run full migration off the UI thread."""
    from src.storage.video_id_migration import is_lance_migration_completed

    runtime_config = config or load_config()
    meta = _load_meta_for_startup(runtime_config)
    if not _already_migrated(runtime_config, meta):
        return True
    # Trust the recorded Lance flag: leftover npy sidecars after completed migration
    # must not force a vector-dir listdir (or video-id scan) on every launch.
    if not is_lance_migration_completed(runtime_config) and legacy_npy_vectors_present(runtime_config):
        if not _trust_fast_video_id_check(runtime_config):
            return True
        if _legacy_video_ids_pending_fast(runtime_config, verify_saved_ids=False):
            return True
    return needs_search_index_schema_migration(runtime_config)


def run_startup_migration_quick(progress_callback=None):
    """Fast synchronous checks; defer heavy work when needs_background_startup_migration()."""
    _emit(progress_callback, 3, "正在快速检查数据结构")
    config = load_config()
    if needs_background_startup_migration(config):
        logger.info("Startup migration deferred to background worker")
        config_version = _read_schema_version(config.get("schema_version"), default=1)
        return {
            "needs_background": True,
            "migrated": False,
            "schema_version": max(config_version, 1),
            "backup_dir": "",
            "migrated_local_payloads": 0,
            "migrated_local_asset_files": 0,
            "migrated_global_payloads": 0,
            "migrated_remote_payloads": 0,
            "migrated_video_ids": 0,
            "failed_video_ids": 0,
            "video_id_format": int(_read_migration_state(config).get("video_id_format", 0) or 0),
            "pending_legacy": False,
        }

    meta = _load_meta_for_startup(config)
    try:
        ensure_default_clip_manifest(config=config)
    except Exception:
        logger.warning("Failed to backfill default CLIP model manifest on quick startup check", exc_info=True)
    logger.info("Startup migration quick path: schema_version=%s", TARGET_SCHEMA_VERSION)
    latest_config = load_config()
    video_id_result, search_index_result = _apply_post_schema_maintenance(
        latest_config,
        progress_callback=progress_callback,
    )
    _emit(progress_callback, 100, "数据结构检查完成")
    return _attach_maintenance_summary(
        {
            "needs_background": False,
            "migrated": bool(video_id_result.get("migrated")),
            "schema_version": TARGET_SCHEMA_VERSION,
            "backup_dir": "",
            "migrated_local_payloads": 0,
            "migrated_local_asset_files": 0,
            "migrated_global_payloads": 0,
            "migrated_remote_payloads": 0,
        },
        video_id_result,
        search_index_result,
    )


def run_startup_migration(progress_callback=None):
    _emit(progress_callback, 3, "正在检查数据结构版本")
    config = load_config()
    meta = _load_meta_for_startup(config)

    if _already_migrated(config, meta):
        try:
            ensure_default_clip_manifest(config=config)
        except Exception:
            logger.warning("Failed to backfill default CLIP model manifest on already-migrated config", exc_info=True)
        logger.info("Startup migration skipped: already at schema_version=%s", TARGET_SCHEMA_VERSION)
        latest_config = load_config()
        video_id_result, search_index_result = _apply_post_schema_maintenance(
            latest_config,
            progress_callback=progress_callback,
        )
        return _attach_maintenance_summary(
            {
                "migrated": bool(video_id_result.get("migrated")),
                "schema_version": TARGET_SCHEMA_VERSION,
                "backup_dir": "",
                "migrated_local_payloads": 0,
                "migrated_local_asset_files": 0,
                "migrated_global_payloads": 0,
                "migrated_remote_payloads": 0,
            },
            video_id_result,
            search_index_result,
        )

    prior_state = _read_migration_state(config)
    prior_schema_done = bool(prior_state.get("completed")) and _read_schema_version(
        prior_state.get("schema_version"), default=0
    ) >= TARGET_SCHEMA_VERSION
    if prior_schema_done:
        backup_dir = str(prior_state.get("backup_dir", "") or "").strip()
        logger.info(
            "Skipping pre-migration backup: schema migration already completed (backup_dir=%s)",
            backup_dir or "n/a",
        )
        _emit(progress_callback, 12, "正在升级配置结构（跳过重复备份）")
    else:
        if _data_dir_has_user_payload(config):
            _emit(progress_callback, 12, "正在备份现有数据")
            backup_dir = _create_backup(config)
            logger.info("Created pre-migration backup: %s", backup_dir)
        else:
            backup_dir = ""
            logger.info("Skipping pre-migration backup: no existing user data to copy")
            _emit(progress_callback, 12, "正在准备数据结构升级")

    _emit(progress_callback, 30, "正在升级配置结构")
    normalized_config = _normalize_config_v2(config)
    save_config(normalized_config)
    latest_config = load_config()

    _emit(progress_callback, 44, "正在迁移模型元数据文件")
    migrated_meta_file = _migrate_meta_file(latest_config)

    _emit(progress_callback, 50, "正在升级元数据结构")
    model_paths = get_model_profile_storage_paths(config=latest_config)
    latest_meta = load_metadata(model_paths["meta_file"])
    save_metadata(_normalize_meta_v2(latest_meta, latest_config), model_paths["meta_file"])

    _emit(progress_callback, 60, "正在迁移本地模型资产目录")
    local_asset_files = _migrate_local_asset_dirs(latest_config)

    _emit(progress_callback, 70, "正在升级本地向量载荷结构")
    local_count = _migrate_vector_dir_payloads(latest_config)

    _emit(progress_callback, 76, "正在迁移全局索引资产目录")
    global_asset_files = _migrate_global_asset_files(latest_config)

    _emit(progress_callback, 82, "正在迁移模型资源目录")
    model_resource_files = _migrate_model_resource_files(latest_config)

    _emit(progress_callback, 86, "正在升级全局索引元数据结构")
    global_count = _migrate_global_payloads(latest_config)

    _emit(progress_callback, 90, "正在清理旧目录")
    cleaned_legacy_dirs = _cleanup_legacy_empty_dirs(latest_config)

    _emit(progress_callback, 94, "正在写入迁移状态")
    try:
        ensure_default_clip_manifest(config=latest_config)
    except Exception:
        logger.warning("Failed to write default CLIP model manifest after migration", exc_info=True)
    _write_migration_state(latest_config, backup_dir)
    _prune_backup_dirs(latest_config, keep_count=1)

    video_id_result, search_index_result = _apply_post_schema_maintenance(
        latest_config,
        progress_callback=progress_callback,
    )

    _emit(progress_callback, 100, "数据结构迁移完成")
    logger.info(
        "Startup migration finished: schema_version=%s migrated_local=%s migrated_global=%s search_index_upgraded=%s",
        TARGET_SCHEMA_VERSION,
        local_count,
        global_count,
        bool(search_index_result.get("upgraded")),
    )
    return _attach_maintenance_summary(
        {
            "migrated": True,
            "schema_version": TARGET_SCHEMA_VERSION,
            "backup_dir": backup_dir,
            "migrated_local_payloads": int(local_count),
            "migrated_meta_file": int(migrated_meta_file),
            "migrated_local_asset_files": int(local_asset_files),
            "migrated_global_asset_files": int(global_asset_files),
            "migrated_remote_asset_files": 0,
            "migrated_model_resource_files": int(model_resource_files),
            "migrated_global_payloads": int(global_count),
            "migrated_remote_payloads": 0,
            "cleaned_legacy_dirs": int(cleaned_legacy_dirs),
        },
        video_id_result,
        search_index_result,
    )
