"""Pack clone-match segments onto a Jianying timeline."""

from __future__ import annotations

import os
from typing import Any


def _temporal_match():
    """Prefer plugin temporal_match; fall back to identity helpers."""
    try:
        from videoseek_plugin_clone.core import temporal_match as tm

        return tm
    except Exception as _swallowed:
        from src.app.logging_utils import note_swallowed

        note_swallowed(_swallowed, "src/services/nle_timeline_export.py:temporal_match")
        return None


class _TemporalFallback:
    @staticmethod
    def close_small_query_gaps(segments, max_gap_sec=0.0):
        return list(segments or [])

    @staticmethod
    def pack_segments_by_coverage(segments, blob_grow_sec=0.0):
        return list(segments or [])


def _tm():
    return _temporal_match() or _TemporalFallback()


# Export trust modes: keep NLE tracks by confidence (V3 top / V2 mid / V1 blob).
EXPORT_MODE_STRICT = "strict"  # V3 only — copyright / source proof
EXPORT_MODE_BALANCED = "balanced"  # V3 + V2 — remix review default
EXPORT_MODE_COVERAGE = "coverage"  # V3 + V2 + V1 — max fill
DEFAULT_EXPORT_MODE = EXPORT_MODE_BALANCED

_EXPORT_MODE_MIN_TRACK: dict[str, int] = {
    EXPORT_MODE_STRICT: 3,
    EXPORT_MODE_BALANCED: 2,
    EXPORT_MODE_COVERAGE: 1,
}


def resolve_clone_export_mode(mode_id: str | None) -> str:
    key = str(mode_id or DEFAULT_EXPORT_MODE).strip().lower()
    if key not in _EXPORT_MODE_MIN_TRACK:
        return DEFAULT_EXPORT_MODE
    return key


def filter_segments_for_export_mode(
    segments: list[dict[str, Any]],
    export_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Keep tracks at or above the mode floor. Untagged rows count as V3 (legacy)."""
    mode = resolve_clone_export_mode(export_mode)
    min_track = int(_EXPORT_MODE_MIN_TRACK[mode])
    kept: list[dict[str, Any]] = []
    for segment in segments or []:
        row = dict(segment or {})
        raw_track = row.get("track", None)
        if raw_track is None or int(raw_track or 0) <= 0:
            # Pre-multi-track payloads: treat as strong.
            row["track"] = 3
            if not row.get("layer"):
                row["layer"] = "strong"
            kept.append(row)
            continue
        track = int(raw_track)
        if track >= min_track:
            kept.append(row)
    return kept


def _ensure_positive_span(start: float, end: float, *, fps: float) -> tuple[float, float]:
    start_v = float(start or 0.0)
    end_v = float(end or 0.0)
    min_dur = 1.0 / max(float(fps or 24.0), 1e-6)
    if end_v <= start_v:
        end_v = start_v + min_dur
    return start_v, end_v


def normalize_segments_for_export(
    segments: list[dict[str, Any]],
    *,
    timeline_fps: float = 24.0,
    min_duration_sec: float = 0.5,
    dedupe_overlaps: bool = True,
) -> list[dict[str, Any]]:
    """Pad tiny hits; pack within each track (multi-track) or single-track pack."""
    tm = _tm()
    close_small_query_gaps, pack_segments_by_coverage = tm.close_small_query_gaps, tm.pack_segments_by_coverage

    # Short/point hits stay in the timeline — pad to a drag-friendly minimum.
    min_dur = max(float(min_duration_sec or 0.0), 1.0 / max(float(timeline_fps or 24.0), 1e-6))
    cleaned: list[dict[str, Any]] = []
    for segment in segments or []:
        item = dict(segment or {})
        source_path = str(item.get("source_video_path", "") or "").strip()
        if not source_path:
            continue
        q0, q1 = _ensure_positive_span(item.get("query_start", 0.0), item.get("query_end", 0.0), fps=timeline_fps)
        s0, s1 = _ensure_positive_span(item.get("source_start", 0.0), item.get("source_end", 0.0), fps=timeline_fps)
        q_dur = max(q1 - q0, 0.0)
        s_dur = max(s1 - s0, 0.0)
        dur = max(q_dur, s_dur, min_dur)
        item["query_start"] = q0
        item["query_end"] = q0 + dur
        item["source_start"] = s0
        item["source_end"] = s0 + dur
        item["source_video_path"] = os.path.normpath(source_path)
        item["score"] = float(item.get("score", 0.0) or 0.0)
        if "track" in segment:
            item["track"] = int(segment.get("track") or 1)
        if segment.get("layer"):
            item["layer"] = str(segment.get("layer"))
        cleaned.append(item)

    if not dedupe_overlaps:
        cleaned.sort(
            key=lambda row: (
                -int(row.get("track", 1) or 1),
                float(row.get("query_start", 0.0) or 0.0),
                -float(row.get("score", 0.0) or 0.0),
            )
        )
        return cleaned

    frame = 1.0 / max(float(timeline_fps or 24.0), 1e-6)
    has_tracks = any(int(row.get("track", 0) or 0) > 0 for row in cleaned)
    if not has_tracks:
        packed = pack_segments_by_coverage(cleaned)
        return close_small_query_gaps(packed, max_gap_sec=max(1.0, frame * 8))

    # Pack each track independently so layers stay stacked like an NLE.
    by_track: dict[int, list[dict[str, Any]]] = {}
    for row in cleaned:
        track = max(int(row.get("track", 1) or 1), 1)
        by_track.setdefault(track, []).append(row)
    layered: list[dict[str, Any]] = []
    for track in sorted(by_track.keys(), reverse=True):
        packed = pack_segments_by_coverage(by_track[track], blob_grow_sec=0.0)
        packed = close_small_query_gaps(packed, max_gap_sec=max(0.5, frame * 4))
        for row in packed:
            row["track"] = track
            layered.append(row)
    layered.sort(
        key=lambda row: (
            -int(row.get("track", 1) or 1),
            float(row.get("query_start", 0.0) or 0.0),
        )
    )
    return layered


def _snap_packed_timeline_clips(
    clips: list[dict[str, Any]],
    *,
    max_snap_frames: int = 2,
) -> list[dict[str, Any]]:
    """Close 1–N frame seams caused by seconds→frames rounding."""
    if not clips:
        return []
    ordered = sorted((dict(item) for item in clips), key=lambda row: int(row.get("start", 0) or 0))
    snap = max(int(max_snap_frames or 0), 0)
    if snap <= 0:
        return ordered
    for index in range(len(ordered) - 1):
        curr = ordered[index]
        nxt = ordered[index + 1]
        curr_end = int(curr.get("end", 0) or 0)
        next_start = int(nxt.get("start", 0) or 0)
        gap = next_start - curr_end
        if gap < 0 or (0 < gap <= snap):
            # Trim 1–N frame overlaps from rounding, and close tiny seams.
            curr["end"] = next_start
            curr["duration"] = max(0, int(curr["end"]) - int(curr.get("start", 0) or 0))
            curr["out"] = int(curr.get("in", 0) or 0) + int(curr["duration"])
    kept: list[dict[str, Any]] = []
    for clip in ordered:
        start = int(clip.get("start", 0) or 0)
        end = int(clip.get("end", 0) or 0)
        if end <= start:
            continue
        clip["duration"] = end - start
        clip["out"] = int(clip.get("in", 0) or 0) + int(clip["duration"])
        kept.append(clip)
    return kept


def _probe_media(path: str) -> dict[str, Any]:
    """Probe width/height/duration/fps via shared NLE helper."""
    from src.services.fcpxml_export_service import _probe_media as _nle_probe_media

    info = _nle_probe_media(path) or {}
    return {
        "width": int(info.get("width") or 1920),
        "height": int(info.get("height") or 1080),
        "duration": float(info.get("duration") or 0.0),
        "fps": float(info.get("fps") or 0.0),
    }


def _prepare_clone_timeline_clips(
    segments: list[dict[str, Any]],
    *,
    timeline_fps: float,
    export_mode: str | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, dict[str, Any]], int]:
    """Build per-track timeline clips + media cache. Frames use sequence timebase."""
    from src.services.fcpxml_export_service import _seconds_to_frames

    filtered = filter_segments_for_export_mode(segments, export_mode)
    normalized = normalize_segments_for_export(filtered, timeline_fps=timeline_fps)
    fps = max(float(timeline_fps or 24.0), 1e-6)
    media_cache: dict[str, dict[str, Any]] = {}
    by_track: dict[int, list[dict[str, Any]]] = {}
    max_end = 0
    for segment in normalized:
        source_path = os.path.abspath(os.path.normpath(str(segment.get("source_video_path", "") or "")))
        if not source_path:
            continue
        if source_path not in media_cache:
            media_cache[source_path] = _probe_media(source_path)
        query_start = float(segment.get("query_start", 0.0) or 0.0)
        query_end = float(segment.get("query_end", query_start) or query_start)
        source_start = float(segment.get("source_start", 0.0) or 0.0)
        start_f = _seconds_to_frames(query_start, fps)
        end_f = _seconds_to_frames(query_end, fps)
        if end_f <= start_f:
            end_f = start_f + 1
        dur_frames = end_f - start_f
        # Premiere reads clipitem in/out in sequence timebase on mixed-fps timelines.
        in_f = _seconds_to_frames(source_start, fps)
        out_f = in_f + dur_frames
        track = max(int(segment.get("track", 1) or 1), 1)
        by_track.setdefault(track, []).append(
            {
                "path": source_path,
                "name": os.path.basename(source_path) or "clip",
                "query_start": query_start,
                "query_end": query_end,
                "source_start": source_start,
                "duration_sec": max(query_end - query_start, 1.0 / fps),
                "start": start_f,
                "end": end_f,
                "in": in_f,
                "out": out_f,
                "duration": dur_frames,
                "track": track,
            }
        )
        max_end = max(max_end, end_f)

    for track_id, clips in list(by_track.items()):
        by_track[track_id] = _snap_packed_timeline_clips(clips, max_snap_frames=3)
        max_end = max(max_end, max((int(c.get("end", 0) or 0) for c in by_track[track_id]), default=0))
    return by_track, media_cache, max_end
