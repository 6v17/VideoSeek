"""Preview / export clip ffmpeg command builders and runners."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import uuid

from src.infra.ffmpeg_paths import get_ffmpeg_path
from src.infra.paths import ensure_folder_exists, get_app_data_dir
from src.media.probe import get_video_duration_seconds

EXPORT_ENCODE_MODE_ORIGINAL = "original"
EXPORT_ENCODE_MODE_COPY = "copy"
_EXPORT_ENCODE_MODES = {EXPORT_ENCODE_MODE_ORIGINAL, EXPORT_ENCODE_MODE_COPY}


def create_preview_clip(input_path, start_sec, output_path, duration_sec=None):
    from src.app.config import load_config

    ffmpeg = get_ffmpeg_path()
    config = load_config()
    preview_seconds = float(config.get("preview_seconds", 6))
    preview_width = config.get("preview_width", 640)
    preview_height = config.get("preview_height", 360)
    encode = _preview_encode_settings(config)

    input_path = os.fspath(input_path)
    output_path = os.fspath(output_path)
    start_sec = max(0.0, float(start_sec))
    clip_duration = preview_seconds if duration_sec is None else max(0.1, float(duration_sec))

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    fast_seek = max(0.0, start_sec - 1.0)
    precise_seek = start_sec - fast_seek

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{fast_seek:.3f}",
        "-i",
        input_path,
        "-ss",
        f"{precise_seek:.3f}",
        "-t",
        f"{clip_duration:.3f}",
        "-s",
        f"{preview_width}x{preview_height}",
        "-c:v",
        "libx264",
        "-preset",
        encode["preset"],
        "-tune",
        encode["tune"],
        "-crf",
        encode["crf"],
        "-c:a",
        "aac",
        "-b:a",
        encode["audio_bitrate"],
        "-movflags",
        "+faststart",
        output_path,
    ]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    return subprocess.run(cmd, startupinfo=startupinfo, capture_output=True)


def _resolve_base_clip_window(video_path, start_sec, end_sec=None, *, config=None):
    """Centered preview window or explicit [start_sec, end_sec] — no export padding."""
    from src.app.config import load_config

    cfg = config or load_config()
    start_sec = float(start_sec)
    video_duration = get_video_duration_seconds(video_path)
    if video_duration is not None:
        video_duration = max(0.0, float(video_duration))

    if end_sec is not None and float(end_sec) > start_sec + 1e-3:
        clip_start = max(0.0, start_sec)
        clip_end = float(end_sec)
        if video_duration is not None:
            clip_end = min(clip_end, video_duration)
        clip_duration = max(0.1, clip_end - clip_start)
        return clip_start, clip_duration

    preview_seconds = float(cfg.get("preview_seconds", 6))
    clip_duration = max(0.1, preview_seconds)
    half = clip_duration / 2.0
    center = max(0.0, start_sec)
    if video_duration is not None:
        center = min(center, video_duration)

    clip_start = center - half
    clip_end = center + half
    if clip_start < 0.0:
        clip_end -= clip_start
        clip_start = 0.0
    if video_duration is not None and clip_end > video_duration:
        shift = clip_end - video_duration
        clip_start = max(0.0, clip_start - shift)
        clip_end = video_duration
    clip_duration = max(0.1, clip_end - clip_start)
    return clip_start, clip_duration


def estimate_export_copy_duration_sec(config=None, *, explicit_range_sec=None) -> float:
    """Approximate clip length shown in the fast-export dialog."""
    from src.app.config import load_config

    cfg = config or load_config()
    margin = float(cfg.get("export_copy_margin_sec", 2.0))
    extra = float(cfg.get("export_copy_extra_sec", 4))
    if explicit_range_sec is not None:
        return max(0.1, float(explicit_range_sec) + margin * 2.0)
    preview_seconds = float(cfg.get("preview_seconds", 6))
    return max(0.1, preview_seconds + extra)


def resolve_export_clip_window(
    video_path,
    start_sec,
    end_sec=None,
    *,
    encode_mode=None,
    config=None,
):
    """Export window; fast (copy) mode adds padding to reduce keyframe cut misses."""
    from src.app.config import load_config

    cfg = config or load_config()
    clip_start, clip_duration = _resolve_base_clip_window(
        video_path,
        start_sec,
        end_sec=end_sec,
        config=cfg,
    )
    if normalize_export_encode_mode(encode_mode) != EXPORT_ENCODE_MODE_COPY:
        return clip_start, clip_duration

    margin = float(cfg.get("export_copy_margin_sec", 2.0))
    extra = float(cfg.get("export_copy_extra_sec", 4))
    has_explicit_range = end_sec is not None and float(end_sec) > float(start_sec) + 1e-3
    pad = margin if has_explicit_range else extra / 2.0

    video_duration = get_video_duration_seconds(video_path)
    if video_duration is not None:
        video_duration = max(0.0, float(video_duration))

    clip_end = clip_start + clip_duration
    new_start = max(0.0, clip_start - pad)
    new_end = clip_end + pad
    if video_duration is not None:
        new_end = min(new_end, video_duration)
    if video_duration is not None and new_end > video_duration:
        shift = new_end - video_duration
        new_start = max(0.0, new_start - shift)
        new_end = video_duration
    if new_start < 0.0:
        new_end -= new_start
        new_start = 0.0
    if video_duration is not None and new_end > video_duration:
        shift = new_end - video_duration
        new_start = max(0.0, new_start - shift)
        new_end = video_duration
    clip_duration = max(0.1, new_end - new_start)
    return new_start, clip_duration


def normalize_export_encode_mode(mode) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"copy", "stream_copy", "stream-copy"}:
        return EXPORT_ENCODE_MODE_COPY
    return EXPORT_ENCODE_MODE_ORIGINAL


def export_original_clip(
    input_path,
    start_sec,
    duration_sec,
    output_path,
    *,
    silent=False,
    encode_mode=None,
):
    cmd = build_export_original_clip_command(
        input_path,
        start_sec,
        duration_sec,
        output_path,
        silent=silent,
        encode_mode=encode_mode,
    )
    return subprocess.run(cmd, startupinfo=_build_hidden_startupinfo(), capture_output=True)


def start_export_original_clip_process(
    input_path,
    start_sec,
    duration_sec,
    output_path,
    *,
    silent=False,
    encode_mode=None,
):
    cmd = build_export_original_clip_command(
        input_path,
        start_sec,
        duration_sec,
        output_path,
        silent=silent,
        encode_mode=encode_mode,
    )
    return subprocess.Popen(
        cmd,
        startupinfo=_build_hidden_startupinfo(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def build_export_original_clip_command(
    input_path,
    start_sec,
    duration_sec,
    output_path,
    *,
    silent=False,
    encode_mode=None,
    config=None,
):
    from src.app.config import load_config

    ffmpeg = get_ffmpeg_path()
    cfg = config or load_config()
    encode = _export_encode_settings(cfg)
    input_path = os.fspath(input_path)
    output_path = os.fspath(output_path)
    start_sec = max(0.0, float(start_sec))
    duration_sec = max(0.1, float(duration_sec))
    silent = bool(silent)
    encode_mode = normalize_export_encode_mode(encode_mode)

    ensure_folder_exists(output_path)
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        input_path,
        "-t",
        f"{duration_sec:.3f}",
        "-map",
        "0:v:0",
    ]
    if encode_mode == EXPORT_ENCODE_MODE_COPY:
        if silent:
            cmd.append("-an")
        else:
            cmd.extend(["-map", "0:a?"])
        cmd.extend(
            [
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                "-movflags",
                "+faststart",
                output_path,
            ]
        )
        return cmd

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            encode["preset"],
            "-crf",
            encode["crf"],
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if silent:
        cmd.extend(["-an", "-movflags", "+faststart", output_path])
    else:
        cmd.extend(
            [
                "-map",
                "0:a?",
                "-c:a",
                "aac",
                "-b:a",
                encode["audio_bitrate"],
                "-movflags",
                "+faststart",
                output_path,
            ]
        )
    return cmd


def _preview_encode_settings(config):
    return {
        "preset": str(config.get("preview_encode_preset", "ultrafast")),
        "tune": str(config.get("preview_encode_tune", "zerolatency")),
        "crf": str(int(config.get("preview_encode_crf", 32))),
        "audio_bitrate": str(config.get("preview_encode_audio_bitrate", "128k")),
    }


def _export_encode_settings(config):
    return {
        "preset": str(config.get("export_encode_preset", "fast")),
        "crf": str(int(config.get("export_encode_crf", 18))),
        "audio_bitrate": str(config.get("export_encode_audio_bitrate", "192k")),
    }


def _build_hidden_startupinfo():
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return startupinfo


def build_preview_cache_path(video_path, start_sec):
    from src.app.config import get_data_storage_paths

    cache_dir = get_data_storage_paths().get("preview_cache_dir", "")
    if not cache_dir:
        cache_dir = os.path.join(get_app_data_dir(), "cache")
    os.makedirs(cache_dir, exist_ok=True)
    key = f"{video_path}|{int(start_sec)}|{uuid.uuid4().hex}"
    filename = f"preview_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}.mp4"
    return os.path.join(cache_dir, filename)
