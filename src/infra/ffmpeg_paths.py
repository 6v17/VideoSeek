"""FFmpeg / ffprobe path resolution and config sync."""

from __future__ import annotations

import os
import shutil

from src.infra.paths import get_app_data_dir, get_app_install_dir


def get_default_ffmpeg_path():
    return os.path.join(get_app_data_dir(), "bin", "ffmpeg.exe")


def get_configured_ffmpeg_target_path(config=None):
    from src.app.config import load_config

    current_config = dict(config or load_config())
    configured_path = str(current_config.get("ffmpeg_path", "") or "").strip()
    if configured_path:
        normalized_path = os.path.normpath(configured_path)
        if os.path.isabs(normalized_path) or os.path.dirname(normalized_path):
            return normalized_path
    return os.path.normpath(get_default_ffmpeg_path())


def get_ffmpeg_path():
    resolved_path, _ = resolve_ffmpeg_path_info()
    return resolved_path or "ffmpeg"


def has_ffmpeg():
    ffmpeg_path = get_ffmpeg_path()
    return os.path.exists(ffmpeg_path) or shutil.which(ffmpeg_path) is not None


def get_ffmpeg_status_text():
    resolved_path, source = resolve_ffmpeg_path_info()
    if source == "system":
        return f"PATH: {resolved_path}"
    return resolved_path or "Unavailable"


def resolve_ffmpeg_path_info():
    from src.app.config import load_config

    config = load_config()
    configured_path = get_configured_ffmpeg_target_path(config)
    if configured_path and os.path.exists(configured_path):
        return configured_path, "configured"

    default_path = get_default_ffmpeg_path()
    if os.path.exists(default_path):
        return default_path, "managed"

    # Prefer install dir (exe folder when packaged). Never use process cwd — shortcuts
    # and Nuitka launches often have cwd != install root.
    bundled_path = os.path.join(get_app_install_dir(), "ffmpeg.exe")
    if os.path.exists(bundled_path):
        return bundled_path, "bundled"

    system_path = shutil.which("ffmpeg")
    if system_path:
        return system_path, "system"

    return "", "missing"


def sync_ffmpeg_path_to_config():
    from src.app.config import load_config, save_config

    config = load_config()
    configured_path = str(config.get("ffmpeg_path", "") or "").strip()
    if configured_path:
        normalized_path = os.path.normpath(configured_path)
        if normalized_path != configured_path:
            config["ffmpeg_path"] = normalized_path
            save_config(config)
        return normalized_path

    resolved_path, source = resolve_ffmpeg_path_info()
    if source == "missing" or not resolved_path:
        return ""

    config["ffmpeg_path"] = resolved_path
    save_config(config)
    return resolved_path


def get_ffprobe_path():
    ffmpeg_path = get_ffmpeg_path()
    ffmpeg_dir = os.path.dirname(ffmpeg_path)
    ffmpeg_name = os.path.basename(ffmpeg_path).lower()
    if ffmpeg_name.startswith("ffmpeg"):
        candidate_name = ffmpeg_name.replace("ffmpeg", "ffprobe", 1)
        candidate_path = os.path.join(ffmpeg_dir, candidate_name)
        if os.path.exists(candidate_path):
            return candidate_path
    return shutil.which("ffprobe") or ""
