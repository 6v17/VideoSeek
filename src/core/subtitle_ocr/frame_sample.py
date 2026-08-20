"""Sample frames for subtitle OCR (timeline probe + cheap ROI gates)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence

import cv2
import numpy as np

from src.media.thumbnail import get_single_thumbnail

_FINGERPRINT_SIZE = (48, 16)  # width, height — keep enough detail to tell CJK lines apart
_DEFAULT_FINGERPRINT_MEAN_ABS = 5.0
_BLANK_MIN_STD = 6.0
_BLANK_MIN_EDGE = 2.0
_BLANK_MIN_INK = 0.008


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
    """Sparse timestamps across a full video for subtitle-band probing."""
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


def roi_likely_blank(
    roi: np.ndarray,
    *,
    min_std: float = _BLANK_MIN_STD,
    min_edge: float = _BLANK_MIN_EDGE,
    min_ink: float = _BLANK_MIN_INK,
) -> bool:
    """Cheap gate: skip OCR only when the subtitle band looks empty.

    Thin hardsubs (1px white stroke on dark) often have low Canny density but
    non-trivial std / ink ratio — require *all* signals to say empty.
    """
    if roi is None or not isinstance(roi, np.ndarray) or roi.size <= 0:
        return True
    if roi.ndim == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = np.asarray(roi)
    std = float(np.std(gray))
    edges = cv2.Canny(gray, 40, 120)
    edge_mean = float(np.mean(edges))
    med = float(np.median(gray))
    ink_ratio = float(np.mean(np.abs(gray.astype(np.float32) - med) > 28.0))
    if std < float(min_std) and edge_mean < float(min_edge) and ink_ratio < float(min_ink):
        return True
    return False


def roi_fingerprint(roi: np.ndarray, *, size: tuple[int, int] = _FINGERPRINT_SIZE) -> np.ndarray | None:
    """Compact gray+edge fingerprint for subtitle-band change detection."""
    if roi is None or not isinstance(roi, np.ndarray) or roi.size <= 0:
        return None
    if roi.ndim == 3:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = np.asarray(roi)
    width = max(4, int(size[0]))
    height = max(2, int(size[1]))
    small = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
    edges = cv2.Canny(small, 40, 120)
    # Stack gray + edges so glyph layout changes beat plain luminance drift.
    stacked = np.concatenate(
        [
            np.ascontiguousarray(small, dtype=np.uint8).reshape(-1),
            np.ascontiguousarray(edges, dtype=np.uint8).reshape(-1),
        ]
    )
    return stacked


def roi_fingerprints_similar(
    left: np.ndarray | None,
    right: np.ndarray | None,
    *,
    max_mean_abs: float = _DEFAULT_FINGERPRINT_MEAN_ABS,
) -> bool:
    """True when two fingerprints look like the same subtitle plate."""
    if left is None or right is None:
        return False
    a = np.asarray(left, dtype=np.float32).reshape(-1)
    b = np.asarray(right, dtype=np.float32).reshape(-1)
    if a.size == 0 or b.size == 0 or a.size != b.size:
        return False
    # Half the vector is edges (0/255); weight gray + edges separately.
    mid = a.size // 2
    if mid > 0 and a.size == mid * 2:
        gray_diff = float(np.mean(np.abs(a[:mid] - b[:mid])))
        edge_diff = float(np.mean(np.abs(a[mid:] - b[mid:])))
        # Either channel clearly different → treat as changed.
        return gray_diff <= float(max_mean_abs) and edge_diff <= float(max_mean_abs) * 8.0
    return float(np.mean(np.abs(a - b))) <= float(max_mean_abs)


def roi_changed(
    roi: np.ndarray,
    previous_fingerprint: np.ndarray | None,
    *,
    max_mean_abs: float = _DEFAULT_FINGERPRINT_MEAN_ABS,
) -> tuple[bool, np.ndarray | None]:
    """Return ``(changed, fingerprint)`` for a subtitle ROI.

    ``changed`` means the band should be sent to OCR (first non-blank plate or
    a plate that differs from ``previous_fingerprint``).
    """
    fingerprint = roi_fingerprint(roi)
    if fingerprint is None:
        return False, previous_fingerprint
    if previous_fingerprint is None:
        return True, fingerprint
    if roi_fingerprints_similar(fingerprint, previous_fingerprint, max_mean_abs=max_mean_abs):
        return False, previous_fingerprint
    return True, fingerprint


def grab_frames_at_times(
    video_path: str,
    times_sec: Sequence[float],
) -> list[tuple[float, np.ndarray]]:
    """Return all ``(time_sec, frame)`` pairs (one shared decoder)."""
    return list(iter_frames_at_times(video_path, times_sec))


def iter_frames_at_times(
    video_path: str,
    times_sec: Sequence[float],
) -> Iterator[tuple[float, np.ndarray]]:
    """Yield frames with one VideoCapture; prefer forward ``grab`` for nearby stamps."""
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
                        # Step forward instead of keyframe-seek thrash.
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
                frame = get_single_thumbnail(path, t)
                if frame is not None:
                    last_msec = target_msec
            if frame is not None and isinstance(frame, np.ndarray) and frame.size > 0:
                yield (t, frame)
    finally:
        capture.release()


def _downscale_roi_width(roi: np.ndarray, max_width: int) -> np.ndarray:
    width = int(roi.shape[1]) if getattr(roi, "ndim", 0) >= 2 else 0
    limit = max(320, int(max_width))
    if width <= limit:
        return roi
    scale = limit / float(width)
    new_h = max(1, int(round(roi.shape[0] * scale)))
    return cv2.resize(roi, (limit, new_h), interpolation=cv2.INTER_AREA)


def crop_subtitle_roi(
    frame: np.ndarray,
    *,
    bottom_ratio: float = 0.40,
    max_width: int = 960,
) -> np.ndarray:
    """Keep the lower band where hardsubs usually sit; downscale for OCR speed.

    Slightly taller / wider than a pure dialogue band so PV lower-third titles
    are less often cropped out. Use ``crop_subtitle_rois`` when a top title
    band is also needed.
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
        return frame
    height = int(frame.shape[0])
    if height <= 1:
        return frame
    ratio = min(0.9, max(0.15, float(bottom_ratio)))
    y0 = int(height * (1.0 - ratio))
    return _downscale_roi_width(frame[y0:height, :, ...], max_width)


def crop_subtitle_top_roi(
    frame: np.ndarray,
    *,
    top_ratio: float = 0.20,
    side_crop_ratio: float = 0.20,
    max_width: int = 960,
) -> np.ndarray:
    """Keep the upper band for PV titles / character names.

    Horizontal side margins (default 20% each) drop corner watermarks / logos
    that often sit in the top-left / top-right of anime/PV frames.
    """
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
        return frame
    height = int(frame.shape[0])
    width = int(frame.shape[1]) if frame.ndim >= 2 else 0
    if height <= 1 or width <= 1:
        return frame
    ratio = min(0.45, max(0.08, float(top_ratio)))
    y1 = max(1, int(round(height * ratio)))
    side = min(0.40, max(0.0, float(side_crop_ratio)))
    x0 = int(round(width * side))
    x1 = int(round(width * (1.0 - side)))
    if x1 <= x0 + 1:
        x0, x1 = 0, width
    return _downscale_roi_width(frame[0:y1, x0:x1, ...], max_width)


def crop_subtitle_rois(
    frame: np.ndarray,
    *,
    include_top: bool = False,
    top_ratio: float = 0.20,
    top_side_crop_ratio: float = 0.20,
    bottom_ratio: float = 0.40,
    max_width: int = 960,
) -> list[tuple[str, np.ndarray]]:
    """Return ``[(band, roi), ...]`` — bottom always; optional top title band.

    Band ids: ``top`` | ``bottom``. Top is intended for timeline/PV probing;
    VAD/dialogue paths usually keep ``include_top=False``. Top band also drops
    left/right margins (``top_side_crop_ratio``) to avoid corner logos.
    """
    bands: list[tuple[str, np.ndarray]] = []
    if include_top:
        top = crop_subtitle_top_roi(
            frame,
            top_ratio=top_ratio,
            side_crop_ratio=top_side_crop_ratio,
            max_width=max_width,
        )
        if top is not None and isinstance(top, np.ndarray) and top.size > 0:
            bands.append(("top", top))
    bottom = crop_subtitle_roi(frame, bottom_ratio=bottom_ratio, max_width=max_width)
    if bottom is not None and isinstance(bottom, np.ndarray) and bottom.size > 0:
        bands.append(("bottom", bottom))
    return bands
