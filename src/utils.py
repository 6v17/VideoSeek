"""Compatibility facade — prefer ``src.infra`` / ``src.media`` / ``src.storage`` modules."""

from __future__ import annotations

import gc
import os
import subprocess
import sys
import time

from src.app.logging_utils import get_logger
from src.infra.ffmpeg_paths import (
    get_configured_ffmpeg_target_path,
    get_default_ffmpeg_path,
    get_ffmpeg_path,
    get_ffmpeg_status_text,
    get_ffprobe_path,
    has_ffmpeg,
    resolve_ffmpeg_path_info,
    sync_ffmpeg_path_to_config,
)
from src.infra.model_paths import (
    ensure_model_files,
    get_configured_model_dir,
    get_missing_model_files,
    get_model_path,
    resolve_model_dir_info,
    sync_model_dir_to_config,
)
from src.infra.paths import (
    ensure_folder_exists,
    get_app_data_dir,
    get_app_install_dir,
    get_default_model_dir,
    get_resource_path,
    resolve_resource_path,
)
from src.media.export_clip import (
    EXPORT_ENCODE_MODE_COPY,
    EXPORT_ENCODE_MODE_ORIGINAL,
    build_export_original_clip_command,
    build_preview_cache_path,
    create_preview_clip,
    estimate_export_copy_duration_sec,
    export_original_clip,
    normalize_export_encode_mode,
    resolve_export_clip_window,
    start_export_original_clip_process,
)
from src.media.probe import (
    get_video_duration_seconds,
    get_video_stream_info,
    has_readable_video_stream,
)
from src.media.sampling_fps import (
    ensure_sampling_fps_rules_open_tail,
    normalize_sampling_fps_mode,
    normalize_sampling_fps_rules_text,
    parse_sampling_fps_rules,
    resolve_sampling_fps,
    validate_sampling_fps_rules,
    validate_sampling_fps_rules_full_coverage,
)
from src.media.thumbnail import get_single_thumbnail
from src.storage.meta_io import load_meta, save_meta
from src.storage.video_identity import (
    canonicalize_library_path,
    get_legacy_video_hash,
    get_video_hash,
)

logger = get_logger("utils")


def format_timecode_seconds(seconds) -> str:
    """MM:SS, or H:MM:SS when one hour or more (integer seconds, floor)."""
    total = max(0, int(float(seconds)))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_timecode_range(start_sec, end_sec, *, min_range_sec: float = 0.2) -> str:
    """Format one timecode or a start–end range for display."""
    start_text = format_timecode_seconds(start_sec)
    end_text = format_timecode_seconds(end_sec)
    if abs(float(end_sec) - float(start_sec)) < float(min_range_sec):
        return start_text
    return f"{start_text}–{end_text}"


def measure_time(message=""):
    def decorator(func):
        def wrapper(*args, **kwargs):
            started = time.time()
            result = func(*args, **kwargs)
            logger.info("%s %s took %.2fs", message, func.__name__, time.time() - started)
            return result

        return wrapper

    return decorator


def free_memory():
    gc.collect()
    logger.debug("Memory cleanup completed")


def libx264_param():
    # Retained intentionally until ffmpeg codec selection is fully inlined.
    return "libx264"


def is_windows_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def open_in_explorer(video_path):
    path = os.fspath(video_path)
    if not str(path or "").strip():
        logger.warning("File does not exist: %s", video_path)
        return False
    if not os.path.exists(path):
        logger.warning("File does not exist: %s", video_path)
        return False

    path = os.path.normpath(os.path.abspath(path))

    if sys.platform == "win32":
        try:
            subprocess.run(["explorer", "/select,", path], check=False)
        except Exception as exc:
            logger.warning("Windows locate failed: %s", exc)
            os.startfile(os.path.dirname(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", "-R", path], check=False)
    else:
        subprocess.run(["xdg-open", os.path.dirname(path)], check=False)
    return True


def open_folder_in_explorer(folder_path):
    if not os.path.exists(folder_path):
        logger.warning("Folder does not exist: %s", folder_path)
        return

    path = os.path.normpath(os.path.abspath(folder_path))

    if sys.platform == "win32":
        try:
            os.startfile(path)
        except OSError as exc:
            logger.warning("Windows folder open failed: %s", exc)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
