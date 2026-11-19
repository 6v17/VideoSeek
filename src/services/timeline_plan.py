"""Expand a short shot pool into a beat-timed timeline cut list."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence


def beat_duration_sec(*, bpm: float, beats_per_cut: float) -> float:
    rate = float(bpm)
    beats = float(beats_per_cut)
    if rate <= 0:
        raise ValueError("plan.bpm must be > 0.")
    if beats <= 0:
        raise ValueError("plan.beats_per_cut must be > 0.")
    return 60.0 / rate * beats


def expand_timeline_plan(
    plan: Mapping[str, Any],
    *,
    max_clips: int,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Lay shots on a beat grid until total_sec is filled.

    Each cut takes ``min(beat_len, remaining)``. With ``fit_chunk``, a short
    indexed chunk becomes a short cut instead of spilling past its end.
    Shots cycle when the pool is smaller than the cut count.
    """
    shots = list(plan.get("shots") or [])
    if not shots:
        raise ValueError("plan.shots must contain at least one clip.")
    total = float(plan.get("total_sec") or 0.0)
    if total <= 0:
        raise ValueError("plan.total_sec must be > 0.")
    beat_len = beat_duration_sec(
        bpm=float(plan.get("bpm") or 0.0),
        beats_per_cut=float(plan.get("beats_per_cut") if plan.get("beats_per_cut") is not None else 2.0),
    )
    fit_chunk = bool(plan.get("fit_chunk"))
    limit = max(1, int(max_clips))

    items: List[Dict[str, Any]] = []
    cursor = 0.0
    index = 0
    while cursor < total - 1e-6 and len(items) < limit:
        shot = shots[index % len(shots)]
        index += 1
        path = str(shot.get("video_path") if isinstance(shot, Mapping) else getattr(shot, "video_path", "") or "").strip()
        if not path:
            continue
        start = float(shot.get("start_sec") if isinstance(shot, Mapping) else getattr(shot, "start_sec"))
        end_value = shot.get("end_sec") if isinstance(shot, Mapping) else getattr(shot, "end_sec", None)
        chunk_len = None
        if end_value is not None:
            chunk_len = max(0.0, float(end_value) - start)
            if chunk_len <= 1e-6:
                continue
        cut = beat_len
        if fit_chunk and chunk_len is not None:
            cut = min(chunk_len, beat_len)
        cut = min(cut, total - cursor)
        if cut <= 1e-6:
            break
        items.append(
            {
                "video_path": path,
                "start_sec": start,
                "end_sec": start + cut,
            }
        )
        cursor += cut

    if not items:
        raise ValueError("plan produced no timeline clips.")
    if len(items) >= limit and cursor < total - 1e-3:
        raise ValueError(
            f"plan needs more than {limit} clips to cover {total:.3f}s "
            f"(filled {cursor:.3f}s)."
        )

    meta = {
        "bpm": float(plan.get("bpm")),
        "beats_per_cut": float(plan.get("beats_per_cut") if plan.get("beats_per_cut") is not None else 2.0),
        "beat_sec": beat_len,
        "total_sec": total,
        "filled_sec": cursor,
        "shot_pool": len(shots),
        "fit_chunk": fit_chunk,
        "expanded_count": len(items),
    }
    return items, meta
