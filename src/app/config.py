import json
import os
import shutil

from src.app.app_meta import get_app_meta
from src.app.logging_utils import get_logger
from src.utils import get_app_data_dir, get_default_model_dir, get_resource_path

logger = get_logger("config")
_LAST_MIGRATION_NOTICE = None

APP_DATA_DIR = get_app_data_dir()
DATA_DIR = os.path.join(APP_DATA_DIR, "data")
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
LEGACY_CONFIG_FILE = get_resource_path("config.json")
LEGACY_DATA_DIR = get_resource_path("data")

DEFAULT_CONFIG = {
    "fps": 1,
    "search_top_k": 20,
    "preview_seconds": 6,
    "preview_width": 640,
    "preview_height": 360,
    "thumb_width": 130,
    "thumb_height": 75,
    "prefer_gpu": True,
    "similarity_threshold": 0.85,
    "max_chunk_duration": 5.0,
    "min_chunk_size": 2,
    "chunk_similarity_mode": "chunk",
    "search_mode": "frame",
    "ffmpeg_path": "",
    "model_dir": get_default_model_dir(),
    "meta_file": os.path.join(DATA_DIR, "meta.json"),
    "vector_dir": os.path.join(DATA_DIR, "vector"),
    "index_dir": os.path.join(DATA_DIR, "index"),
    "cross_index_file": os.path.join(DATA_DIR, "global", "cross_video_index.faiss"),
    "cross_vector_file": os.path.join(DATA_DIR, "global", "cross_video_vectors.npy"),
    "cross_chunk_index_file": os.path.join(DATA_DIR, "global", "cross_chunk_index.faiss"),
    "cross_chunk_vector_file": os.path.join(DATA_DIR, "global", "cross_chunk_vectors.npy"),
    "remote_index_file": os.path.join(DATA_DIR, "remote", "remote_index.faiss"),
    "remote_vector_file": os.path.join(DATA_DIR, "remote", "remote_vectors.npy"),
    "remote_max_frames": 2000,
    "auto_cleanup_missing_files": False,
    "theme": "dark",
    "language": "zh",
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

LEGACY_DEFAULT_CONFIG = {
    **DEFAULT_CONFIG,
    "meta_file": os.path.join(LEGACY_DATA_DIR, "meta.json"),
    "vector_dir": os.path.join(LEGACY_DATA_DIR, "vector"),
    "index_dir": os.path.join(LEGACY_DATA_DIR, "index"),
    "cross_index_file": os.path.join(LEGACY_DATA_DIR, "global", "cross_video_index.faiss"),
    "cross_vector_file": os.path.join(LEGACY_DATA_DIR, "global", "cross_video_vectors.npy"),
    "cross_chunk_index_file": os.path.join(LEGACY_DATA_DIR, "global", "cross_chunk_index.faiss"),
    "cross_chunk_vector_file": os.path.join(LEGACY_DATA_DIR, "global", "cross_chunk_vectors.npy"),
    "remote_index_file": os.path.join(LEGACY_DATA_DIR, "remote", "remote_index.faiss"),
    "remote_vector_file": os.path.join(LEGACY_DATA_DIR, "remote", "remote_vectors.npy"),
}

def get_app_version():
    return str(get_app_meta().get("version", "1.0.0"))


def _ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
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


def _normalize_storage_paths(config, config_base_dir):
    normalized = dict(config)
    for key in PATH_KEYS:
        normalized[key] = _normalize_path_value(normalized.get(key, DEFAULT_CONFIG[key]), config_base_dir)
    return normalized


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
        logger.info("Migrating legacy data directory from %s to %s", LEGACY_DATA_DIR, DATA_DIR)
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
        config = _load_json(config_path)
        config = _apply_default_values(config)
        config = _normalize_storage_paths(config, os.path.dirname(config_path))
        config = _sanitize_runtime_resource_paths(
            config,
            is_legacy_config=os.path.normpath(config_path) == os.path.normpath(LEGACY_CONFIG_FILE),
        )
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
    save_config(config)
    return config


def save_config(config):
    _ensure_parent_dir(CONFIG_FILE)
    with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=4, ensure_ascii=False)


def pop_migration_notice():
    global _LAST_MIGRATION_NOTICE
    notice = _LAST_MIGRATION_NOTICE
    _LAST_MIGRATION_NOTICE = None
    return notice
