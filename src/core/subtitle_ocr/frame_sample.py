"""Sample frames inside speech segments for subtitle OCR."""

from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np

from src.core.subtitle_ocr.frame_decode import grab_frames_at_times, iter_frames_at_times


def sample_times_in_segment(
    start_sec: float,
    end_sec: float,
    *,
    interval_sec: float = 1.2,
    max_frames: int = 0,
    edge_pad_sec: float = 0.2,
) -> list[float]:
    """Pick timestamps inside ``[start, end]`` for OCR sampling.

    ``max_frames <= 0`` means no per-segment cap (density follows ``interval_sec`` only).
    """
    start = max(0.0, float(start_sec) + float(edge_pad_sec))
    end = max(start, float(end_sec) - float(edge_pad_sec))
    duration = end - start
    if duration <= 1e-3:
        return [start]
    interval = max(0.1, float(interval_sec))
    max_n = int(max_frames)
    if duration <= interval * 1.25:
        return [start + duration * 0.5]
    times = [start]
    t = start + interval
    while t < end - 1e-6:
        times.append(t)
        t += interval
        if max_n > 0 and len(times) >= max_n:
            break
    if times[-1] < end - 0.08 and (max_n <= 0 or len(times) < max_n):
        times.append(end)
    if max_n > 0 and len(times) > max_n:
        idxs = np.linspace(0, len(times) - 1, num=max_n, dtype=int)
        times = [times[int(i)] for i in idxs]
    return times


def sample_times_across_timeline(
    duration_sec: float,
    *,
    interval_sec: float = 2.0,
    max_frames: int = 1800,
    start_sec: float = 0.0,
) -> list[float]:
    """Sparse timestamps across a video (helper only; subtitle index does not use this)."""
    duration = max(0.0, float(duration_sec))
    start = max(0.0, float(start_sec))
    if duration <= 1e-3:
        return [start]
    return sample_times_in_segment(
        start,
        duration,
        interval_sec=interval_sec,
        max_frames=max_frames,
        edge_pad_sec=0.05,
    )


def roi_likely_blank(roi: np.ndarray, *, min_std: float = 12.0, min_edge: float = 6.0) -> bool:
    """Cheap gate: skip OCR when the subtitle band looks empty."""
    if roi is None or not isinstance(roi, np.ndarray) or roi.size <= 0:
        return True
    if roi.ndim == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = roi
    if float(np.std(gray)) < float(min_std):
        return True
    edges = cv2.Canny(gray, 60, 140)
    if float(np.mean(edges)) < float(min_edge):
        return True
    return False


def crop_subtitle_roi(
    frame: np.ndarray,
    *,
    bottom_ratio: float = 0.32,
    max_width: int = 720,
) -> np.ndarray:
    """Keep the lower band where hardsubs usually sit; downscale for OCR speed."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
        return frame
    height = int(frame.shape[0])
    if height <= 1:
        return frame
    ratio = min(0.9, max(0.15, float(bottom_ratio)))
    y0 = int(height * (1.0 - ratio))
    roi = frame[y0:height, :, ...]
    width = int(roi.shape[1]) if roi.ndim >= 2 else 0
    limit = max(320, int(max_width))
    if width > limit:
        scale = limit / float(width)
        new_h = max(1, int(round(roi.shape[0] * scale)))
        roi = cv2.resize(roi, (limit, new_h), interpolation=cv2.INTER_AREA)
    return roi


# Keep type checkers aware of re-exported iterators.
__all__ = [
    "sample_times_in_segment",
    "sample_times_across_timeline",
    "roi_likely_blank",
    "crop_subtitle_roi",
    "iter_frames_at_times",
    "grab_frames_at_times",
]
