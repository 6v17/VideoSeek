from __future__ import annotations

from typing import Sequence

import numpy as np


def classify_video_pace(timestamps: Sequence[float] | None, anchor_sec: float | None = None) -> str:
    """Estimate scene pace from indexed frame timestamps near the anchor."""
    try:
        ts = np.asarray(timestamps, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return "unknown"
    if ts.size < 2:
        return "unknown"
    ts.sort()

    if anchor_sec is not None:
        center = max(0.0, float(anchor_sec))
        local = ts[(ts >= center - 60.0) & (ts <= center + 60.0)]
        if local.size >= 2:
            density = float(local.size) / 120.0
            if density >= 0.75:
                return "fast_cut"
            if density <= 0.20:
                return "stable"
            return "normal"

    diffs = np.diff(ts)
    diffs = diffs[diffs > 1e-3]
    if diffs.size == 0:
        return "unknown"
    median_gap = float(np.median(diffs))
    if median_gap <= 0.8:
        return "fast_cut"
    if median_gap >= 2.5:
        return "stable"
    return "normal"


def pearson_correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3 or len(ys) < 3 or len(xs) != len(ys):
        return None
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    if float(np.std(x)) <= 1e-9 or float(np.std(y)) <= 1e-9:
        return None
    return float(np.corrcoef(x, y)[0, 1])
