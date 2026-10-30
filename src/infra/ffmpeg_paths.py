"""FFmpeg / ffprobe path resolution and config sync."""

from __future__ import annotations

import os
import shutil
import subprocess

from src.infra.paths import get_app_data_dir, get_app_install_dir

# Real ffmpeg builds are tens of MB. Size alone still accepts a truncated PE
# that is merely larger than this floor, so usability also requires -version.
_MIN_FFMPEG_BYTES = 1024 * 1024
_VERSION_OK: dict[tuple, bool] = {}


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


def _ffmpeg_reports_version(path: str, size: int, mtime: float) -> bool:
    key = (os.path.normcase(os.path.normpath(path)), int(size), float(mtime))
    cached = _VERSION_OK.get(key)
    if cached is not None:
        return cached
    ok = False
    try:
        run_kwargs = {
            "capture_output": True,
            "timeout": 8,
            "check": False,
        }
        if os.name == "nt":
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        completed = subprocess.run([path, "-version"], **run_kwargs)
        blob = (completed.stdout or b"") + (completed.stderr or b"")
        ok = completed.returncode == 0 and b"ffmpeg version" in blob.lower()
    except (OSError, subprocess.TimeoutExpired, ValueError):
        ok = False
    _VERSION_OK[key] = ok
    return ok


def is_ffmpeg_binary_usable(path: str) -> bool:
    """True when ``path`` is a real ffmpeg binary, not a truncated copy.

    Size and PE/ELF magic reject stubs. ``ffmpeg -version`` rejects a larger
    truncated file that still starts with ``MZ``. The version result is cached
    by path, size, and mtime.
    """
    text = os.path.normpath(str(path or "").strip())
    if not text or not os.path.isfile(text):
        return False
    try:
        size = int(os.path.getsize(text))
        mtime = float(os.path.getmtime(text))
    except OSError:
        return False
    if size < _MIN_FFMPEG_BYTES:
        return False
    try:
        with open(text, "rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    if os.name == "nt":
        magic_ok = magic[:2] == b"MZ"
    else:
        magic_ok = magic[:4] == b"\x7fELF" or magic[:2] == b"MZ"
    if not magic_ok:
        return False
    return _ffmpeg_reports_version(text, size, mtime)


def get_ffmpeg_path():
    resolved_path, _ = resolve_ffmpeg_path_info()
    return resolved_path or "ffmpeg"


def has_ffmpeg():
    resolved_path, source = resolve_ffmpeg_path_info()
    return bool(resolved_path) and source != "missing"


def get_ffmpeg_status_text():
    resolved_path, source = resolve_ffmpeg_path_info()
    if source == "system":
        return f"PATH: {resolved_path}"
    return resolved_path or "Unavailable"


def resolve_ffmpeg_path_info():
    from src.app.config import load_config

    config = load_config()
    configured_path = get_configured_ffmpeg_target_path(config)
    if configured_path and is_ffmpeg_binary_usable(configured_path):
        return configured_path, "configured"

    default_path = get_default_ffmpeg_path()
    if is_ffmpeg_binary_usable(default_path):
        return default_path, "managed"

    # Prefer install dir (exe folder when packaged). Never use process cwd — shortcuts
    # and Nuitka launches often have cwd != install root.
    bundled_path = os.path.join(get_app_install_dir(), "ffmpeg.exe")
    if is_ffmpeg_binary_usable(bundled_path):
        return bundled_path, "bundled"

    system_path = shutil.which("ffmpeg")
    if system_path and is_ffmpeg_binary_usable(system_path):
        return system_path, "system"

    return "", "missing"


def install_ffmpeg_executable(ffmpeg_file, config=None):
    """Copy ``ffmpeg.exe`` to the configured target and persist ``ffmpeg_path``.

    Same write as the in-app runtime import: existing ``ffmpeg_path`` when set,
    otherwise ``<app data>/bin/ffmpeg.exe``.
    """
    from src.app.config import load_config, save_config

    source_path = os.path.normpath(os.path.abspath(os.fspath(ffmpeg_file)))
    if os.path.basename(source_path).strip().lower() != "ffmpeg.exe":
        raise RuntimeError("Selected executable is not ffmpeg.exe")
    if not os.path.isfile(source_path):
        raise RuntimeError(f"FFmpeg file not found: {source_path}")
    current = config if config is not None else load_config()
    target_path = os.path.normpath(get_configured_ffmpeg_target_path(config=current))
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    shutil.copy2(source_path, target_path)
    current["ffmpeg_path"] = target_path
    save_config(current)
    return target_path


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
