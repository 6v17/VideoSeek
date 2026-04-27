import json
import os
import shutil

from src.app.app_meta import get_app_meta
from src.app.logging_utils import get_logger
from src.utils import (
    get_app_data_dir,
    get_default_model_dir,
    get_resource_path,
    normalize_sampling_fps_mode,
    normalize_sampling_fps_rules_text,
)

logger = get_logger("config")
_LAST_MIGRATION_NOTICE = None
STORAGE_DIR_NAME = "data"

APP_DATA_DIR = get_app_data_dir()
DATA_DIR = os.path.join(APP_DATA_DIR, STORAGE_DIR_NAME)
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
LEGACY_CONFIG_FILE = get_resource_path("config.json")
LEGACY_DATA_DIR = get_resource_path("data")


def build_data_storage_paths(data_root, storage_dir_name=STORAGE_DIR_NAME):
    normalized_root = os.path.normpath(str(data_root or APP_DATA_DIR))
    storage_dir = os.path.join(normalized_root, storage_dir_name)
    return {
        "meta_file": os.path.join(storage_dir, "meta.json"),
        "vector_dir": os.path.join(storage_dir, "vector"),
        "index_dir": os.path.join(storage_dir, "index"),
        "cross_index_file": os.path.join(storage_dir, "global", "cross_video_index.faiss"),
        "cross_vector_file": os.path.join(storage_dir, "global", "cross_video_vectors.npy"),
        "cross_chunk_index_file": os.path.join(storage_dir, "global", "cross_chunk_index.faiss"),
        "cross_chunk_vector_file": os.path.join(storage_dir, "global", "cross_chunk_vectors.npy"),
        "remote_index_file": os.path.join(storage_dir, "remote", "remote_index.faiss"),
        "remote_vector_file": os.path.join(storage_dir, "remote", "remote_vectors.npy"),
    }

DEFAULT_CONFIG = {
    "fps": 1,
    "sampling_fps_mode": "dynamic",
    "sampling_fps_rules": "0-10m=2; 10m-60m=1; 60m-=0.5",
    "search_top_k": 20,
    "preview_seconds": 6,
    "preview_width": 640,
    "preview_height": 360,
    "thumb_width": 130,
    "thumb_height": 75,
    "prefer_gpu": True,
    "embedding_batch_size": 16,
    "similarity_threshold": 0.85,
    "max_chunk_duration": 5.0,
    "min_chunk_size": 2,
    "chunk_similarity_mode": "chunk",
    "search_mode": "frame",
    "ffmpeg_path": "",
    "model_dir": get_default_model_dir(),
    "data_root": APP_DATA_DIR,
    **build_data_storage_paths(APP_DATA_DIR),
    "remote_max_frames": 2000,
    "auto_cleanup_missing_files": False,
    "show_debug_test_buttons": False,
    "theme": "dark",
    "language": "zh",
}

CONFIG_BOUNDS = {
    "fps": (0.01, 24.0),
    "search_top_k": (1, 200),
    "preview_seconds": (2, 20),
    "preview_width": (160, 1920),
    "preview_height": (90, 1080),
    "thumb_width": (80, 480),
    "thumb_height": (45, 320),
    "remote_max_frames": (200, 20000),
    "embedding_batch_size": (1, 64),
    "similarity_threshold": (0.1, 1.0),
    "max_chunk_duration": (1.0, 60.0),
    "min_chunk_size": (1, 50),
}

CONFIG_INT_KEYS = {
    "search_top_k",
    "preview_seconds",
    "preview_width",
    "preview_height",
    "thumb_width",
    "thumb_height",
    "remote_max_frames",
    "embedding_batch_size",
    "min_chunk_size",
}

CONFIG_ENUMS = {
    "chunk_similarity_mode": {"chunk", "frame"},
    "search_mode": {"frame", "chunk"},
    "theme": {"dark", "light"},
    "language": {"zh", "en"},
}

PATH_KEYS = {
    "meta_file",
    "vector_dir",
    "index_dir",
    "cross_index_file",
    "cross_vector_file",
    "cross_chunk_index_file",
    "cross_chunk_vector_file",
    "remote_index_file",
    "remote_vector_file",
}

DERIVED_DATA_PATH_KEYS = {
    "data_dir",
    "global_dir",
    "remote_dir",
    "preview_cache_dir",
    "mobile_upload_dir",
    "remote_build_cache_dir",
    "link_cache_dir",
    "remote_build_report_file",
}

LEGACY_DEFAULT_CONFIG = {
    **DEFAULT_CONFIG,
    **build_data_storage_paths(os.path.dirname(LEGACY_DATA_DIR)),
}

def get_app_version():
    return str(get_app_meta().get("version", "1.0.0"))


def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _load_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _normalize_path_value(value, base_dir):
    if not isinstance(value, str) or not value.strip():
        return value
    normalized = value.strip().replace("/", os.sep)
    if os.path.isabs(normalized):
        return os.path.normpath(normalized)
    return os.path.normpath(os.path.join(base_dir, normalized))


def _clone_data_tree(src_dir, dst_dir):
    if not os.path.exists(src_dir):
        return
    for current_root, dirs, files in os.walk(src_dir):
        rel_root = os.path.relpath(current_root, src_dir)
        target_root = dst_dir if rel_root == "." else os.path.join(dst_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            src_file = os.path.join(current_root, name)
            dst_file = os.path.join(target_root, name)
            if os.path.exists(dst_file):
                continue
            shutil.copy2(src_file, dst_file)


def _apply_default_values(config):
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    return config


def _normalize_data_root(config, config_base_dir):
    normalized = dict(config)
    normalized["data_root"] = _normalize_path_value(normalized.get("data_root", DEFAULT_CONFIG["data_root"]), config_base_dir)
    return normalized


def _normalize_storage_paths(config, config_base_dir):
    normalized = dict(config)
    for key in PATH_KEYS:
        normalized[key] = _normalize_path_value(normalized.get(key, DEFAULT_CONFIG[key]), config_base_dir)
    return normalized


def _apply_data_root_storage_paths(config):
    normalized = dict(config)
    data_root = str(normalized.get("data_root", "") or "").strip()
    if not data_root:
        return normalized
    normalized.update(build_data_storage_paths(data_root))
    return normalized


def _infer_data_root_from_storage_paths(config):
    meta_file = str(config.get("meta_file", "") or "").strip()
    if not meta_file:
        return ""
    meta_dir = os.path.dirname(os.path.normpath(meta_file))
    if os.path.basename(meta_dir).lower() != STORAGE_DIR_NAME:
        return ""
    candidate_root = os.path.dirname(meta_dir)
    expected_paths = build_data_storage_paths(candidate_root)
    for key in PATH_KEYS:
        actual = os.path.normpath(str(config.get(key, "") or ""))
        expected = os.path.normpath(expected_paths[key])
        if actual != expected:
            return ""
    return os.path.normpath(candidate_root)


def _sanitize_runtime_resource_paths(config, is_legacy_config=False):
    sanitized = dict(config)

    model_dir = str(sanitized.get("model_dir", "") or "").strip()
    if not model_dir:
        sanitized["model_dir"] = get_default_model_dir()
    elif is_legacy_config and os.path.isabs(model_dir) and not os.path.exists(model_dir):
        sanitized["model_dir"] = get_default_model_dir()

    ffmpeg_path = str(sanitized.get("ffmpeg_path", "") or "").strip()
    if is_legacy_config and ffmpeg_path and os.path.isabs(ffmpeg_path) and not os.path.exists(ffmpeg_path):
        sanitized["ffmpeg_path"] = ""

    return sanitized


def _sanitize_sampling_settings(config):
    sanitized = dict(config)
    for obsolete_key in ("dynamic_fps_reference_duration", "dynamic_fps_min", "dynamic_fps_max"):
        sanitized.pop(obsolete_key, None)

    try:
        fps_value = float(sanitized.get("fps", DEFAULT_CONFIG["fps"]))
        sanitized["fps"] = fps_value if fps_value >= 0.01 else DEFAULT_CONFIG["fps"]
    except (TypeError, ValueError):
        sanitized["fps"] = DEFAULT_CONFIG["fps"]
    sanitized["sampling_fps_mode"] = normalize_sampling_fps_mode(
        sanitized.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
    )
    sanitized["sampling_fps_rules"] = normalize_sampling_fps_rules_text(
        sanitized.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
    )
    return sanitized


def _coerce_bounded_value(raw_value, default_value, minimum, maximum, as_int=False):
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        value = float(default_value)
    value = min(maximum, max(minimum, value))
    return int(round(value)) if as_int else float(value)


def _coerce_bool(raw_value, default_value):
    if isinstance(raw_value, bool):
        return raw_value
    if raw_value is None:
        return bool(default_value)
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
        return bool(default_value)
    if isinstance(raw_value, (int, float)):
        return bool(raw_value)
    return bool(raw_value)


def _sanitize_general_settings(config):
    sanitized = dict(config)

    for key, (minimum, maximum) in CONFIG_BOUNDS.items():
        sanitized[key] = _coerce_bounded_value(
            sanitized.get(key, DEFAULT_CONFIG[key]),
            DEFAULT_CONFIG[key],
            minimum,
            maximum,
            as_int=key in CONFIG_INT_KEYS,
        )

    for key, allowed_values in CONFIG_ENUMS.items():
        value = str(sanitized.get(key, DEFAULT_CONFIG[key]) or "").strip().lower()
        sanitized[key] = value if value in allowed_values else DEFAULT_CONFIG[key]

    sanitized["prefer_gpu"] = _coerce_bool(
        sanitized.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"]),
        DEFAULT_CONFIG["prefer_gpu"],
    )
    sanitized["auto_cleanup_missing_files"] = _coerce_bool(
        sanitized.get("auto_cleanup_missing_files", DEFAULT_CONFIG["auto_cleanup_missing_files"]),
        DEFAULT_CONFIG["auto_cleanup_missing_files"],
    )
    sanitized["show_debug_test_buttons"] = _coerce_bool(
        sanitized.get("show_debug_test_buttons", DEFAULT_CONFIG["show_debug_test_buttons"]),
        DEFAULT_CONFIG["show_debug_test_buttons"],
    )
    return sanitized


def _should_migrate_to_user_data(config):
    for key in PATH_KEYS:
        value = os.path.normpath(str(config.get(key, "") or ""))
        if value == os.path.normpath(LEGACY_DEFAULT_CONFIG[key]):
            return True
    return False


def _migrate_legacy_storage_if_needed(config):
    global _LAST_MIGRATION_NOTICE
    migrated = dict(config)
    if not _should_migrate_to_user_data(migrated):
        return migrated

    if os.path.exists(LEGACY_DATA_DIR):
        logger.info("Migrating legacy source directory from %s to %s", LEGACY_DATA_DIR, DATA_DIR)
        _clone_data_tree(LEGACY_DATA_DIR, DATA_DIR)
        _LAST_MIGRATION_NOTICE = {
            "legacy_data_dir": LEGACY_DATA_DIR,
            "data_dir": DATA_DIR,
            "legacy_config_file": LEGACY_CONFIG_FILE,
            "config_file": CONFIG_FILE,
        }

    for key in PATH_KEYS:
        if os.path.normpath(str(migrated.get(key, "") or "")) == os.path.normpath(LEGACY_DEFAULT_CONFIG[key]):
            migrated[key] = DEFAULT_CONFIG[key]
    migrated["data_root"] = DEFAULT_CONFIG["data_root"]
    return migrated


def _resolve_config_path():
    if os.path.exists(CONFIG_FILE):
        return CONFIG_FILE
    if os.path.exists(LEGACY_CONFIG_FILE):
        return LEGACY_CONFIG_FILE
    return CONFIG_FILE


def load_config():
    config_path = _resolve_config_path()
    if os.path.exists(config_path):
        raw_config = _load_json(config_path)
        has_explicit_data_root = bool(str(raw_config.get("data_root", "") or "").strip())
        has_explicit_storage_paths = any(key in raw_config for key in PATH_KEYS)
        config = _apply_default_values(raw_config)
        if has_explicit_data_root:
            config = _normalize_data_root(config, os.path.dirname(config_path))
            config = _apply_data_root_storage_paths(config)
        elif has_explicit_storage_paths:
            config["data_root"] = ""
            config = _normalize_storage_paths(config, os.path.dirname(config_path))
            inferred_data_root = _infer_data_root_from_storage_paths(config)
            if inferred_data_root:
                config["data_root"] = inferred_data_root
                config = _apply_data_root_storage_paths(config)
        else:
            config["data_root"] = os.path.dirname(config_path)
            config = _apply_data_root_storage_paths(config)
        config = _sanitize_runtime_resource_paths(
            config,
            is_legacy_config=os.path.normpath(config_path) == os.path.normpath(LEGACY_CONFIG_FILE),
        )
        config = _sanitize_sampling_settings(config)
        config = _sanitize_general_settings(config)
        config = _migrate_legacy_storage_if_needed(config)
        # Migrate legacy cap from old builds; 300 causes long videos to look capped at ~299s.
        try:
            if int(config.get("remote_max_frames", 0)) == 300:
                config["remote_max_frames"] = DEFAULT_CONFIG["remote_max_frames"]
        except Exception:
            config["remote_max_frames"] = DEFAULT_CONFIG["remote_max_frames"]
        if os.path.normpath(config_path) != os.path.normpath(CONFIG_FILE):
            save_config(config)
        return config

    logger.info("Config file %s not found, using default values", CONFIG_FILE)
    config = DEFAULT_CONFIG.copy()
    config["data_root"] = os.path.dirname(CONFIG_FILE)
    config = _apply_data_root_storage_paths(config)
    save_config(config)
    return config


def save_config(config):
    raw_config = dict(config)
    has_explicit_data_root = bool(str(raw_config.get("data_root", "") or "").strip())
    has_explicit_storage_paths = any(key in raw_config for key in PATH_KEYS)
    config = _sanitize_sampling_settings(_apply_default_values(raw_config))
    if has_explicit_data_root:
        config = _normalize_data_root(config, os.path.dirname(CONFIG_FILE))
        config = _apply_data_root_storage_paths(config)
    elif has_explicit_storage_paths:
        config["data_root"] = ""
        config = _normalize_storage_paths(config, os.path.dirname(CONFIG_FILE))
        inferred_data_root = _infer_data_root_from_storage_paths(config)
        if inferred_data_root:
            config["data_root"] = inferred_data_root
            config = _apply_data_root_storage_paths(config)
    else:
        config["data_root"] = os.path.dirname(CONFIG_FILE)
        config = _apply_data_root_storage_paths(config)
    config = _sanitize_general_settings(config)
    _ensure_parent_dir(CONFIG_FILE)
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=4, ensure_ascii=False)


def get_configured_data_root(config=None):
    normalized = dict(config or load_config())
    data_root = str(normalized.get("data_root", "") or "").strip()
    if data_root:
        return os.path.normpath(data_root)

    inferred_data_root = _infer_data_root_from_storage_paths(normalized)
    if inferred_data_root:
        return inferred_data_root

    meta_file = str(normalized.get("meta_file", "") or "").strip()
    if meta_file:
        meta_dir = os.path.dirname(os.path.normpath(meta_file))
        if os.path.basename(meta_dir).lower() == STORAGE_DIR_NAME:
            return os.path.normpath(os.path.dirname(meta_dir))
    return os.path.normpath(APP_DATA_DIR)


def get_data_storage_paths(config=None):
    data_root = get_configured_data_root(config)
    storage_paths = build_data_storage_paths(data_root)
    data_dir = os.path.dirname(storage_paths["meta_file"])
    derived_paths = {
        "data_dir": data_dir,
        "global_dir": os.path.join(data_dir, "global"),
        "remote_dir": os.path.join(data_dir, "remote"),
        "preview_cache_dir": os.path.join(data_dir, "cache"),
        "mobile_upload_dir": os.path.join(data_dir, "mobile_uploads"),
        "remote_build_cache_dir": os.path.join(data_dir, "remote_build_cache"),
        "link_cache_dir": os.path.join(data_dir, "link_cache"),
        "remote_build_report_file": os.path.join(data_dir, "remote", "build_report.json"),
    }
    storage_paths.update(derived_paths)
    return storage_paths


def pop_migration_notice():
    global _LAST_MIGRATION_NOTICE
    notice = _LAST_MIGRATION_NOTICE
    _LAST_MIGRATION_NOTICE = None
    return notice
