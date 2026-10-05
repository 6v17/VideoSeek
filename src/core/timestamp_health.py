"""Heuristics for synthetic sampling timestamps vs container timing."""

from __future__ import annotations

import json
import os
import subprocess

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.utils import get_ffprobe_path, get_video_duration_seconds, resolve_sampling_fps

logger = get_logger("timestamp_health")


def _parse_ffprobe_rate(value):
    raw = str(value or "").strip()
    if not raw or raw in {"0/0", "N/A", "nan"}:
        return None
    if "/" in raw:
        num_text, den_text = raw.split("/", 1)
        try:
            den = float(den_text)
            if den == 0:
                return None
            return float(num_text) / den
        except ValueError:
            return None
    try:
        parsed = float(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def probe_stream_timing(video_path):
    """Read duration and frame-rate hints from ffprobe (video stream + format)."""
    ffprobe_path = get_ffprobe_path()
    if not ffprobe_path:
        return {
            "duration": None,
            "r_frame_rate": None,
            "avg_frame_rate": None,
        }

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate,avg_frame_rate:format=duration",
        "-of",
        "json",
        os.fspath(video_path),
    ]
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            timeout=12,
        )
        if result.returncode != 0:
            return {"duration": None, "r_frame_rate": None, "avg_frame_rate": None}
        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams") or []
        stream = streams[0] if streams else {}
        format_payload = payload.get("format") or {}
        duration = format_payload.get("duration")
        try:
            duration_value = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_value = None
        if duration_value is not None and duration_value <= 0:
            duration_value = None
        return {
            "duration": duration_value,
            "r_frame_rate": _parse_ffprobe_rate(stream.get("r_frame_rate")),
            "avg_frame_rate": _parse_ffprobe_rate(stream.get("avg_frame_rate")),
        }
    except Exception as exc:
        logger.debug("ffprobe timing probe failed for %s: %s", video_path, exc)
        return {"duration": None, "r_frame_rate": None, "avg_frame_rate": None}


def assess_index_timestamp_health(video_path, timestamps, config=None):
    """Return warning codes when synthetic ``count/fps`` timestamps may misalign playback."""
    runtime_config = dict(config or load_config())
    ts = np.asarray(timestamps, dtype=np.float64).reshape(-1)
    if ts.size == 0:
        return {"warnings": [], "detail": ""}

    warnings = []
    details = []

    duration = get_video_duration_seconds(video_path)
    timing = probe_stream_timing(video_path)
    if timing.get("duration"):
        duration = float(timing["duration"])

    if duration and duration > 0:
        last_ts = float(ts[-1])
        drift = abs(last_ts - duration)
        drift_limit = max(3.0, duration * 0.08)
        if drift > drift_limit:
            warnings.append("duration_drift")
            details.append(
                f"last sampled timestamp {last_ts:.2f}s vs container duration {duration:.2f}s "
                f"(delta {drift:.2f}s)"
            )

    r_rate = timing.get("r_frame_rate")
    avg_rate = timing.get("avg_frame_rate")
    if r_rate and avg_rate:
        rate_delta = abs(float(r_rate) - float(avg_rate))
        relative = rate_delta / max(float(r_rate), float(avg_rate))
        if rate_delta > 0.5 and relative > 0.02:
            warnings.append("vfr_suspected")
            details.append(
                f"stream frame rates differ (r_frame_rate={r_rate:.3f} fps, "
                f"avg_frame_rate={avg_rate:.3f} fps)"
            )

    if ts.size > 1:
        sampling_fps = resolve_sampling_fps(duration, config=runtime_config)
        expected_step = 1.0 / max(float(sampling_fps), 0.01)
        deltas = np.diff(ts)
        if np.any(deltas <= 0):
            warnings.append("non_monotonic_timestamps")
            details.append("timestamps are not strictly increasing")
        elif duration and duration > expected_step * 4:
            max_delta = float(np.max(deltas))
            if max_delta > expected_step * 1.5:
                warnings.append("irregular_sampling")
                details.append(
                    f"timestamp step up to {max_delta:.3f}s (expected ~{expected_step:.3f}s)"
                )

    detail_text = "; ".join(details)
    if warnings:
        logger.info(
            "Timestamp health warnings for %s: %s",
            os.path.basename(video_path),
            detail_text,
        )
    return {"warnings": warnings, "detail": detail_text}
