"""Crop static top/bottom bars out of portrait videos before indexing.

A vertical canvas often keeps a blurred or solid fill above and below the real
picture. A few frames taken across the file show that fill as rows that barely
change. The band that does change is the content. Landscape videos, title cards
that never move, and thin bars are left alone.
"""

from __future__ import annotations

import os

import cv2
import numpy as np

# Taller than 1.2× wide. A slightly tall 4:3 frame is not this case.
_PORTRAIT_RATIO = 1.2
_SAMPLE_COUNT = 4
_MIN_FRAMES = 3
_PROBE_WIDTH = 48
# Each side must be a real bar, and together they must cover a large share.
_MIN_SIDE = 0.12
_MIN_BARS = 0.30
_MIN_CONTENT = 0.18
_MAX_CONTENT = 0.82
# Content rows must move clearly more than the bars.
_ACTIVITY_RATIO = 3.0
# Below this (8-bit), the whole frame is effectively still.
_STILL_PEAK = 4.0


def content_band_fractions(frames) -> tuple[float, float] | None:
    """Return ``(y0, y1)`` as fractions of frame height, or None to keep the full frame."""
    grays = [_gray_small(frame) for frame in frames or []]
    grays = [gray for gray in grays if gray is not None]
    if len(grays) < _MIN_FRAMES:
        return None
    height, width = grays[0].shape[:2]
    if width <= 0 or height < width * _PORTRAIT_RATIO:
        return None
    if any(gray.shape[:2] != (height, width) for gray in grays[1:]):
        return None
    stack = np.stack(grays, axis=0).astype(np.float32)
    median = np.median(stack, axis=0)
    delta = np.mean(np.abs(stack - median[None, :, :]), axis=(0, 2))
    peak = float(delta.max()) if delta.size else 0.0
    if peak < _STILL_PEAK:
        return None
    active = delta >= (peak / _ACTIVITY_RATIO)
    if not bool(active.any()):
        return None
    indices = np.flatnonzero(active)
    y0 = int(indices[0])
    y1 = int(indices[-1]) + 1
    span = active[y0:y1]
    if span.size == 0 or float(span.mean()) < 0.70:
        return None
    top = y0 / float(height)
    bottom = (height - y1) / float(height)
    content = (y1 - y0) / float(height)
    if top < _MIN_SIDE or bottom < _MIN_SIDE:
        return None
    if top + bottom < _MIN_BARS:
        return None
    if content < _MIN_CONTENT or content > _MAX_CONTENT:
        return None
    top_mean = float(delta[:y0].mean()) if y0 else 0.0
    bottom_mean = float(delta[y1:].mean()) if y1 < height else 0.0
    mid_mean = float(delta[y0:y1].mean())
    bar_mean = max(top_mean, bottom_mean)
    if bar_mean > 1.0 and mid_mean < bar_mean * _ACTIVITY_RATIO:
        return None
    return (y0 / float(height), y1 / float(height))


def crop_filter_from_fractions(width: int, height: int, y0: float, y1: float) -> str:
    """FFmpeg ``crop`` for a full-width band, or empty when the band is the whole frame."""
    src_w = int(width)
    src_h = int(height)
    if src_w < 2 or src_h < 2:
        return ""
    top = _even(int(round(float(y0) * src_h)))
    bottom = _even(int(round(float(y1) * src_h)))
    if bottom <= top:
        return ""
    crop_h = _even(bottom - top)
    if top + crop_h > src_h:
        crop_h = _even(src_h - top)
    crop_w = _even(src_w)
    if crop_w < 2 or crop_h < 2:
        return ""
    if crop_h >= src_h - 1 or top <= 0 and crop_h >= src_h - 1:
        return ""
    if crop_h / float(src_h) < _MIN_CONTENT or crop_h / float(src_h) > _MAX_CONTENT:
        return ""
    return f"crop={crop_w}:{crop_h}:0:{top}"


def portrait_content_crop(video_path: str) -> tuple[str, int, int]:
    """Return ``(ffmpeg crop filter, cropped width, cropped height)``.

    The filter is empty when this video should be indexed whole. Cropped size is
    ``(0, 0)`` in that case.
    """
    path = str(video_path or "").strip()
    if not path or path.lower().startswith(("http://", "https://")):
        return "", 0, 0
    from src.core.extract_frames import get_video_duration_seconds, get_video_stream_info

    info = get_video_stream_info(path) or {}
    src_w = int(info.get("width") or 0)
    src_h = int(info.get("height") or 0)
    if src_w <= 0 or src_h < src_w * _PORTRAIT_RATIO:
        return "", 0, 0
    try:
        duration = float(get_video_duration_seconds(path) or 0.0)
    except Exception:
        duration = 0.0
    frames = _sample_frames(path, duration)
    band = content_band_fractions(frames)
    if band is None:
        return "", 0, 0
    filt = crop_filter_from_fractions(src_w, src_h, band[0], band[1])
    if not filt:
        return "", 0, 0
    crop_w, crop_h, _x, top = _parse_crop(filt)
    from src.app.logging_utils import get_logger

    get_logger("portrait_content_band").info(
        "portrait content crop y=%s h=%s of %s (%s)",
        top,
        crop_h,
        src_h,
        os.path.basename(path),
    )
    return filt, crop_w, crop_h


def _sample_frames(video_path: str, duration: float) -> list:
    from src.media.thumbnail import get_single_thumbnail

    frames = []
    for stamp in _sample_times(duration):
        frame = get_single_thumbnail(video_path, stamp)
        if frame is None or getattr(frame, "size", 0) <= 0:
            continue
        frames.append(frame)
    return frames


def _sample_times(duration: float) -> list[float]:
    span = max(0.0, float(duration or 0.0))
    if span < 1.5:
        return [0.0, min(0.4, span), min(0.8, span)]
    start = min(1.0, span * 0.08)
    end = max(start + 0.3, span * 0.92)
    step = (end - start) / float(_SAMPLE_COUNT - 1)
    return [start + step * index for index in range(_SAMPLE_COUNT)]


def _gray_small(frame):
    if frame is None or getattr(frame, "ndim", 0) < 2 or getattr(frame, "size", 0) <= 0:
        return None
    if int(frame.ndim) == 2:
        gray = frame
    elif int(frame.shape[2]) >= 3:
        gray = cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)
    else:
        return None
    height, width = int(gray.shape[0]), int(gray.shape[1])
    if width < 2 or height < 2:
        return None
    target_w = min(_PROBE_WIDTH, width)
    target_h = max(2, int(round(height * (target_w / float(width)))))
    if target_h == height and target_w == width:
        return gray
    return cv2.resize(gray, (target_w, target_h), interpolation=cv2.INTER_AREA)


def _even(value: int) -> int:
    number = int(value)
    if number < 0:
        return 0
    return number - (number % 2)


def _parse_crop(filt: str) -> tuple[int, int, int, int]:
    body = str(filt or "").split("=", 1)[-1]
    width, height, x, y = (int(part) for part in body.split(":"))
    return width, height, x, y
