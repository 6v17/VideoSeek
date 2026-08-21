"""Video duration / stream probing via ffprobe + OpenCV fallback."""

from __future__ import annotations

import json
import os
import subprocess

from src.infra.ffmpeg_paths import get_ffprobe_path
from src.media.formats import is_transport_like_video_path


def get_video_duration_seconds(video_path):
    stream_info = get_video_stream_info(video_path)
    duration = stream_info.get("duration")
    if duration is not None and duration > 0:
        return duration
    return _probe_video_duration_with_opencv(video_path)


def get_video_stream_info(video_path):
    empty = {
        "width": None,
        "height": None,
        "duration": None,
        "codec_name": "",
        "pix_fmt": "",
        "bits_per_raw_sample": None,
        "profile": "",
    }
    ffprobe_path = get_ffprobe_path()
    if not ffprobe_path:
        return dict(empty)

    path = os.fspath(video_path)
    transport_like = is_transport_like_video_path(path)
    # TS/PS often need a larger probe window before duration/stream metadata appears.
    analyze_duration = "100M" if transport_like else "10M"
    probe_size = "50M" if transport_like else "5M"
    timeout_sec = 20 if transport_like else 10

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-analyzeduration",
        analyze_duration,
        "-probesize",
        probe_size,
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,codec_name,pix_fmt,bits_per_raw_sample,profile,duration"
        ":format=duration",
        "-of",
        "json",
        path,
    ]

    run_kwargs = {}
    try:
        from src.infra.win_process import hidden_subprocess_kwargs

        run_kwargs = hidden_subprocess_kwargs()
    except Exception:
        run_kwargs = {}

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            **run_kwargs,
        )
        if result.returncode != 0:
            return dict(empty)

        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        stream = streams[0] if streams else {}
        format_payload = payload.get("format") or {}
        duration = _pick_duration(
            format_payload.get("duration"),
            stream.get("duration"),
        )
        return {
            "width": _safe_int(stream.get("width")),
            "height": _safe_int(stream.get("height")),
            "duration": duration,
            "codec_name": str(stream.get("codec_name") or "").strip().lower(),
            "pix_fmt": str(stream.get("pix_fmt") or "").strip().lower(),
            "bits_per_raw_sample": _safe_int(stream.get("bits_per_raw_sample")),
            "profile": str(stream.get("profile") or "").strip().lower(),
        }
    except Exception:
        return dict(empty)


def has_readable_video_stream(video_path):
    stream_info = get_video_stream_info(video_path)
    if stream_info.get("width") and stream_info.get("height"):
        return True

    fallback_info = _probe_video_stream_with_opencv(video_path)
    return bool(fallback_info.get("width") and fallback_info.get("height"))


def _pick_duration(*candidates):
    """Prefer the first positive duration; format then stream (TS often only has stream)."""
    for value in candidates:
        parsed = _safe_float(value)
        if parsed is not None:
            return parsed
    return None


def _probe_video_duration_with_opencv(video_path):
    return _probe_video_stream_with_opencv(video_path).get("duration")


def _probe_video_stream_with_opencv(video_path):
    import cv2
    from src.app.logging_utils import apply_opencv_log_level

    apply_opencv_log_level()
    path = os.fspath(video_path)
    capture = cv2.VideoCapture(path)
    if not capture.isOpened():
        capture.release()
        return {"width": None, "height": None, "duration": None, "fps": None, "frame_count": None}

    width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)
    height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    capture.release()

    duration = None
    if fps > 0.0 and frame_count > 0.0:
        duration = frame_count / fps

    return {
        "width": int(width) if width > 0.0 else None,
        "height": int(height) if height > 0.0 else None,
        "duration": duration,
        "fps": float(fps) if fps > 0.0 else None,
        "frame_count": int(frame_count) if frame_count > 0.0 else None,
    }


def _safe_float(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
