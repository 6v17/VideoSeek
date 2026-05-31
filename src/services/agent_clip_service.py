"""Agent API clip export (FFmpeg), shared with desktop preview export."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Optional

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.search_scope import normalize_scope_path, video_path_under_library_root
from src.utils import export_original_clip, get_ffmpeg_path, get_video_duration_seconds

logger = get_logger("agent_clip_service")

_EXPORT_CLIP_TIMEOUT_SEC = 120.0
_export_semaphore = threading.Semaphore(1)


def resolve_clip_window(
    video_path: str,
    start_sec: float,
    end_sec: Optional[float] = None,
    config=None,
) -> tuple[float, float]:
    """Return (clip_start, clip_duration) — same rules as desktop preview export."""
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


def _output_path_allowed(output_path: str, config=None) -> bool:
    """Reject writes into indexed library roots (avoid overwriting source media)."""
    from src.services.library_service import list_libraries

    normalized_output = normalize_scope_path(output_path)
    for library_path in list_libraries().keys():
        if video_path_under_library_root(normalized_output, library_path):
            return False
    return True


def execute_agent_export_clip(
    *,
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_path: str,
    client_request_id: Optional[str] = None,
    silent: Optional[bool] = None,
    config=None,
) -> Dict[str, Any]:
    cfg = config or load_config()
    source = os.path.normpath(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"video_path does not exist: {video_path}")

    destination = os.path.normpath(os.path.abspath(os.path.expanduser(str(output_path or "").strip())))
    if not destination:
        raise ValueError("output_path is required.")
    if not destination.lower().endswith((".mp4", ".mkv", ".mov")):
        raise ValueError("output_path must end with .mp4, .mkv, or .mov")
    if not _output_path_allowed(destination, config=cfg):
        raise ValueError("output_path must not be inside an indexed library root.")

    if float(end_sec) <= float(start_sec):
        raise ValueError("end_sec must be greater than start_sec.")

    clip_start, clip_duration = resolve_clip_window(source, start_sec, end_sec=end_sec, config=cfg)
    clip_end = clip_start + clip_duration
    use_silent = bool(cfg.get("export_video_silent", False)) if silent is None else bool(silent)

    from src.utils import has_ffmpeg

    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available. Install or configure FFmpeg in VideoSeek settings.")

    started = time.perf_counter()
    acquired = _export_semaphore.acquire(timeout=_EXPORT_CLIP_TIMEOUT_SEC)
    if not acquired:
        raise RuntimeError("Clip export queue is busy. Retry shortly.")
    try:
        result = export_original_clip(source, clip_start, clip_duration, destination, silent=use_silent)
    finally:
        _export_semaphore.release()

    if result.returncode != 0:
        stderr = ""
        try:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        except Exception:
            stderr = ""
        message = stderr or f"FFmpeg exited with code {result.returncode}"
        raise RuntimeError(message[:2000])

    payload: Dict[str, Any] = {
        "api_version": "1",
        "ok": True,
        "output_path": destination,
        "video_path": source,
        "start_sec": clip_start,
        "end_sec": clip_end,
        "duration_sec": clip_duration,
        "ffmpeg_path": get_ffmpeg_path(),
        "meta": {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "encode_mode": "libx264_crf18",
            "silent": use_silent,
        },
    }
    if client_request_id:
        payload["client_request_id"] = str(client_request_id)
    return payload
