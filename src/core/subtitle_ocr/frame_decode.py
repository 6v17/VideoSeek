"""Sparse frame decode for subtitle OCR.

Default: one OpenCV ``VideoCapture`` with forward ``grab`` between nearby stamps
(fast for VAD-sparse OCR). Optional FFmpeg CUDA single-frame seek is opt-in only
(``VIDEOSEEK_OCR_CUDA_DECODE=1``) — spawning one FFmpeg per stamp is too slow as
the primary path.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator, Sequence

import cv2
import numpy as np

from src.app.logging_utils import get_logger
from src.infra.ffmpeg_paths import get_ffmpeg_path
from src.media.thumbnail import get_single_thumbnail

logger = get_logger("subtitle_ocr.frame_decode")

_LAST_OCR_DECODE_BACKEND = "opencv"
_OCR_CUDA_DECODE_ENV = "VIDEOSEEK_OCR_CUDA_DECODE"
_CUDA_DECODE_LOGGED = False


def get_last_ocr_frame_decode_backend() -> str:
    return str(_LAST_OCR_DECODE_BACKEND or "opencv")


def cuda_ocr_frame_decode_enabled() -> bool:
    """True only when explicitly forced on — not the default OCR path."""
    force = os.environ.get(_OCR_CUDA_DECODE_ENV, "").strip().lower()
    if force not in {"1", "true", "yes", "on"}:
        return False
    try:
        from src.core.extract_frames import ffmpeg_supports_cuda_hwaccel
        from src.core.inference_providers import is_cuda_inference_mode
    except Exception:
        return False
    return bool(is_cuda_inference_mode() and ffmpeg_supports_cuda_hwaccel())


def _set_last_backend(backend: str) -> None:
    global _LAST_OCR_DECODE_BACKEND
    _LAST_OCR_DECODE_BACKEND = str(backend or "opencv").strip().lower() or "opencv"


def _build_startupinfo():
    startupinfo = None
    if hasattr(subprocess, "STARTUPINFO"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    return startupinfo


def grab_frame_ffmpeg_cuda(video_path: str, time_sec: float, *, timeout_sec: float = 8.0) -> np.ndarray | None:
    """Decode one frame with FFmpeg CUDA hwaccel; return BGR numpy or None."""
    path = str(video_path or "").strip()
    if not path or not os.path.isfile(path):
        return None
    safe_time = max(0.0, float(time_sec))
    preroll_sec = 0.35
    coarse_seek = max(0.0, safe_time - preroll_sec)
    fine_seek = safe_time - coarse_seek
    cmd = [
        get_ffmpeg_path(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-hwaccel",
        "cuda",
        "-ss",
        f"{coarse_seek:.3f}",
        "-i",
        path,
        "-ss",
        f"{fine_seek:.3f}",
        "-frames:v",
        "1",
        "-f",
        "image2",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    try:
        process = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=max(1.0, float(timeout_sec)),
            startupinfo=_build_startupinfo(),
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        buffer = np.frombuffer(process.stdout, np.uint8)
        if len(buffer) <= 0:
            return None
        frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if frame is None or not isinstance(frame, np.ndarray) or frame.size <= 0:
            return None
        return frame
    except Exception as exc:
        logger.debug("FFmpeg CUDA OCR frame grab failed at t=%.3f: %s", safe_time, exc)
        return None


def _iter_frames_opencv(video_path: str, times_sec: Sequence[float]) -> Iterator[tuple[float, np.ndarray]]:
    ordered = sorted(max(0.0, float(t)) for t in times_sec)
    if not ordered:
        return

    path = str(video_path or "").strip()
    if not path:
        return

    capture = cv2.VideoCapture(path)
    try:
        opened = bool(capture.isOpened())
        last_msec = -1e9
        for t in ordered:
            target_msec = t * 1000.0
            frame = None
            if opened:
                try:
                    gap = target_msec - last_msec
                    if 0.0 <= gap <= 3500.0:
                        while True:
                            pos = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
                            if pos >= target_msec - 45.0:
                                break
                            if not capture.grab():
                                break
                            new_pos = float(capture.get(cv2.CAP_PROP_POS_MSEC) or 0.0)
                            if new_pos - pos < 0.5:
                                break
                        ok, grabbed = capture.retrieve()
                        if ok and grabbed is not None and getattr(grabbed, "size", 0) > 0:
                            frame = grabbed
                    if frame is None:
                        capture.set(cv2.CAP_PROP_POS_MSEC, target_msec)
                        ok, grabbed = capture.read()
                        if ok and grabbed is not None and getattr(grabbed, "size", 0) > 0:
                            frame = grabbed
                    if frame is not None:
                        last_msec = float(capture.get(cv2.CAP_PROP_POS_MSEC) or target_msec)
                except Exception:
                    frame = None
            if frame is None:
                # Optional CUDA single-frame rescue when OpenCV soft-decode fails.
                if cuda_ocr_frame_decode_enabled():
                    frame = grab_frame_ffmpeg_cuda(path, t)
                if frame is None:
                    frame = get_single_thumbnail(path, t)
                if frame is not None:
                    last_msec = target_msec
            if frame is not None and isinstance(frame, np.ndarray) and frame.size > 0:
                yield (t, frame)
    finally:
        capture.release()


def _iter_frames_cuda(video_path: str, times_sec: Sequence[float]) -> Iterator[tuple[float, np.ndarray]]:
    """Opt-in path: one FFmpeg CUDA process per stamp (slow; for debugging only)."""
    global _CUDA_DECODE_LOGGED
    ordered = sorted(max(0.0, float(t)) for t in times_sec)
    if not ordered:
        return
    path = str(video_path or "").strip()
    if not path:
        return

    if not _CUDA_DECODE_LOGGED:
        logger.warning(
            "Subtitle OCR frame decode: per-frame FFmpeg CUDA enabled "
            "(VIDEOSEEK_OCR_CUDA_DECODE=1). This is slow; prefer default OpenCV decode."
        )
        _CUDA_DECODE_LOGGED = True

    used_cuda = False
    fell_back = False
    for t in ordered:
        frame = grab_frame_ffmpeg_cuda(path, t)
        if frame is None:
            frame = get_single_thumbnail(path, t)
            if frame is not None:
                fell_back = True
        else:
            used_cuda = True
        if frame is not None and isinstance(frame, np.ndarray) and frame.size > 0:
            yield (t, frame)

    if used_cuda and not fell_back:
        _set_last_backend("ffmpeg_cuda")
    elif used_cuda and fell_back:
        _set_last_backend("ffmpeg_cuda_mixed")
    else:
        _set_last_backend("ffmpeg_cpu_fallback")


def iter_frames_at_times(
    video_path: str,
    times_sec: Sequence[float],
) -> Iterator[tuple[float, np.ndarray]]:
    """Yield ``(time_sec, bgr_frame)`` for sparse OCR timestamps."""
    # Per-frame FFmpeg CUDA is opt-in only; OpenCV is the fast default for sparse OCR.
    if os.environ.get(_OCR_CUDA_DECODE_ENV, "").strip().lower() in {"1", "true", "yes", "on"} and cuda_ocr_frame_decode_enabled():
        yield from _iter_frames_cuda(video_path, times_sec)
        return
    _set_last_backend("opencv")
    yield from _iter_frames_opencv(video_path, times_sec)


def grab_frames_at_times(
    video_path: str,
    times_sec: Sequence[float],
) -> list[tuple[float, np.ndarray]]:
    """Return all ``(time_sec, frame)`` pairs (one shared decode strategy)."""
    return list(iter_frames_at_times(video_path, times_sec))
