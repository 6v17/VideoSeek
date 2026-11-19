"""Place one music file under a timeline, from a start time to the end of the cut."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Mapping, Optional


def probe_audio_duration_seconds(path: str) -> Optional[float]:
    """Best-effort duration of a local audio file. None when it cannot be read."""
    media = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not media or not os.path.isfile(media):
        return None
    duration = _duration_from_mediainfo(media)
    if duration and duration > 0:
        return duration
    return _duration_from_ffmpeg(media)


def place_timeline_audio(
    audio: Mapping[str, Any],
    *,
    timeline_duration_sec: float,
) -> Dict[str, Any]:
    """Lay a local audio file from start_sec until the cut ends, or the file ends.

    ``duration_sec`` on the input, when present, is the file length and skips probing.
    The returned ``duration_sec`` is the length actually placed on the timeline.
    """
    path = os.path.abspath(os.path.expanduser(str(audio.get("path") or "").strip()))
    if not path or not os.path.isfile(path):
        raise ValueError(f"audio file not found: {path or '(empty)'}")
    start = float(audio.get("start_sec") or 0.0)
    if start < 0:
        raise ValueError("audio start_sec must be >= 0.")
    volume = 1.0 if audio.get("volume") is None else float(audio.get("volume"))
    if volume < 0 or volume > 2:
        raise ValueError("audio volume must be between 0 and 2.")
    fade = float(audio.get("fade_out_sec") or 0.0)
    if fade < 0:
        raise ValueError("audio fade_out_sec must be >= 0.")
    timeline = float(timeline_duration_sec)
    if timeline <= 0:
        raise ValueError("timeline has no duration to place audio on.")
    if start >= timeline - 1e-3:
        raise ValueError("audio start_sec is past the end of the timeline.")
    file_duration = audio.get("duration_sec")
    if file_duration is None:
        file_duration = probe_audio_duration_seconds(path)
    file_duration = float(file_duration or 0.0)
    if file_duration <= 0:
        raise ValueError(f"could not read audio duration: {path}")
    span = min(file_duration, timeline - start)
    if span <= 0:
        raise ValueError("audio placement has no duration.")
    return {
        "path": path,
        "start_sec": start,
        "duration_sec": span,
        "file_duration_sec": file_duration,
        "volume": volume,
        "fade_out_sec": min(fade, span),
    }


def _duration_from_mediainfo(path: str) -> Optional[float]:
    try:
        from pymediainfo import MediaInfo
    except ImportError:
        return None
    try:
        info = MediaInfo.parse(path)
    except Exception:
        return None
    general = None
    for track in getattr(info, "tracks", []) or []:
        raw = getattr(track, "duration", None)
        if raw in (None, ""):
            continue
        try:
            seconds = float(raw) / 1000.0
        except (TypeError, ValueError):
            continue
        if seconds <= 0:
            continue
        if getattr(track, "track_type", "") == "Audio":
            return seconds
        if getattr(track, "track_type", "") == "General":
            general = seconds
    return general


def _duration_from_ffmpeg(path: str) -> Optional[float]:
    import subprocess

    try:
        from src.infra.ffmpeg_paths import get_ffmpeg_path
    except Exception:
        return None
    ffmpeg = get_ffmpeg_path()
    if not ffmpeg:
        return None
    run_kwargs: Dict[str, Any] = {}
    try:
        from src.infra.win_process import hidden_subprocess_kwargs

        run_kwargs = hidden_subprocess_kwargs()
    except Exception:
        run_kwargs = {}
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", path],
            capture_output=True,
            text=True,
            timeout=15,
            **run_kwargs,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
