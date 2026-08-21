"""Shared NLE timeline export builders (FCP7 / EDL / JSON) for host + plugins."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any
from uuid import uuid4


def _temporal_match():
    """Prefer plugin temporal_match; fall back to identity helpers for host shot-list."""
    try:
        from videoseek_plugin_clone.core import temporal_match as tm

        return tm
    except Exception:
        return None


class _TemporalFallback:
    @staticmethod
    def close_small_query_gaps(segments, max_gap_sec=0.0):
        return list(segments or [])

    @staticmethod
    def pack_segments_by_coverage(segments, blob_grow_sec=0.0):
        return list(segments or [])

    @staticmethod
    def flatten_tracks_by_priority(segments):
        return list(segments or [])

    @staticmethod
    def build_segment_explanation(segment):
        return {}

    @staticmethod
    def compute_query_coverage(segments, query_duration_sec=0.0):
        return {
            "query_duration_sec": float(query_duration_sec or 0.0),
            "covered_sec": 0.0,
            "coverage_ratio": 0.0,
        }

    @staticmethod
    def compute_track_layer_stats(segments, query_duration_sec=0.0):
        return {}


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


def list_clone_export_mode_ids() -> list[str]:
    return [EXPORT_MODE_STRICT, EXPORT_MODE_BALANCED, EXPORT_MODE_COVERAGE]


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


def seconds_to_timecode(seconds: float, *, fps: float = 24.0, drop_frame: bool = False) -> str:
    """Format seconds as HH:MM:SS:FF (non-drop by default)."""
    rate = max(float(fps or 24.0), 1e-6)
    frame_rate = max(1, int(round(rate)))
    total_frames = max(0, int(round(float(seconds or 0.0) * rate)))
    frames = total_frames % frame_rate
    total_seconds = total_frames // frame_rate
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    sep = ";" if drop_frame else ":"
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{frames:02d}"


def seconds_to_frames(seconds: float, *, fps: float = 24.0) -> int:
    rate = max(float(fps or 24.0), 1e-6)
    return max(0, int(round(float(seconds or 0.0) * rate)))


def _ensure_positive_span(start: float, end: float, *, fps: float) -> tuple[float, float]:
    start_v = float(start or 0.0)
    end_v = float(end or 0.0)
    min_dur = 1.0 / max(float(fps or 24.0), 1e-6)
    if end_v <= start_v:
        end_v = start_v + min_dur
    return start_v, end_v


def _query_overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a0 = float(a.get("query_start", 0.0) or 0.0)
    a1 = float(a.get("query_end", 0.0) or 0.0)
    b0 = float(b.get("query_start", 0.0) or 0.0)
    b1 = float(b.get("query_end", 0.0) or 0.0)
    return not (a1 <= b0 or b1 <= a0)


# Kept for callers/tests that still import the name.


def normalize_segments_for_export(
    segments: list[dict[str, Any]],
    *,
    timeline_fps: float = 24.0,
    min_duration_sec: float = 0.5,
    dedupe_overlaps: bool = True,
) -> list[dict[str, Any]]:
    """Pad tiny hits; pack within each track (multi-track) or single-track pack."""
    tm = _tm(); close_small_query_gaps, pack_segments_by_coverage = tm.close_small_query_gaps, tm.pack_segments_by_coverage

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
        gap = int(nxt.get("start", 0) or 0) - int(curr.get("end", 0) or 0)
        if 0 < gap <= snap:
            curr["end"] = int(nxt.get("start", 0) or 0)
            curr["duration"] = max(1, int(curr["end"]) - int(curr.get("start", 0) or 0))
            curr["out"] = int(curr.get("in", 0) or 0) + int(curr["duration"])
    return ordered


def build_clone_match_export_payload(
    *,
    query_path: str,
    library_path: str,
    segments: list[dict[str, Any]],
    fps: float = 5.0,
    timeline_fps: float = 24.0,
    component_id: str = "",
    coverage: dict[str, Any] | None = None,
    export_mode: str | None = None,
    track_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tm = _tm()
    build_segment_explanation = tm.build_segment_explanation
    compute_query_coverage = tm.compute_query_coverage
    compute_track_layer_stats = tm.compute_track_layer_stats

    mode = resolve_clone_export_mode(export_mode)
    filtered = filter_segments_for_export_mode(segments, mode)
    normalized = normalize_segments_for_export(filtered, timeline_fps=timeline_fps)
    items = []
    for index, segment in enumerate(normalized, start=1):
        query_start = float(segment.get("query_start", 0.0) or 0.0)
        query_end = float(segment.get("query_end", query_start) or query_start)
        source_start = float(segment.get("source_start", 0.0) or 0.0)
        source_end = float(segment.get("source_end", source_start) or source_start)
        source_path = str(segment.get("source_video_path", "") or "")
        items.append(
            {
                "index": index,
                "track": int(segment.get("track", 1) or 1),
                "layer": str(segment.get("layer", "") or ""),
                "query_start_sec": query_start,
                "query_end_sec": query_end,
                "query_duration_sec": max(0.0, query_end - query_start),
                "query_timecode_in": seconds_to_timecode(query_start, fps=timeline_fps),
                "query_timecode_out": seconds_to_timecode(query_end, fps=timeline_fps),
                "source_path": source_path,
                "source_name": os.path.basename(source_path),
                "source_video_id": str(segment.get("source_video_id", "") or ""),
                "source_start_sec": source_start,
                "source_end_sec": source_end,
                "source_duration_sec": max(0.0, source_end - source_start),
                "source_timecode_in": seconds_to_timecode(source_start, fps=timeline_fps),
                "source_timecode_out": seconds_to_timecode(source_end, fps=timeline_fps),
                "score": float(segment.get("score", 0.0) or 0.0),
                "confidence": float(segment.get("confidence", 0.0) or 0.0),
                "confidence_parts": dict(segment.get("confidence_parts") or {}),
                "hit_count": int(segment.get("hit_count", 0) or 0),
                "layer_reason": str(segment.get("layer_reason", "") or ""),
                "explanation": build_segment_explanation(segment),
            }
        )
    coverage_payload = dict(coverage or {})
    if not coverage_payload:
        flatten_tracks_by_priority = _tm().flatten_tracks_by_priority

        query_duration = 0.0
        flat_for_cov = (
            flatten_tracks_by_priority(normalized)
            if any(int(row.get("track", 0) or 0) > 0 for row in normalized)
            else normalized
        )
        if flat_for_cov:
            query_duration = max(float(item.get("query_end", 0.0) or 0.0) for item in flat_for_cov)
        try:
            from src.media.probe import get_video_duration_seconds

            probed = float(get_video_duration_seconds(query_path) or 0.0)
            if probed > 0:
                query_duration = probed
        except Exception:
            pass
        coverage_payload = compute_query_coverage(flat_for_cov, query_duration_sec=query_duration)
    stats_payload = dict(track_stats or {})
    if not stats_payload:
        # Prefer stats over the unfiltered evidence timeline when possible.
        query_duration = float(coverage_payload.get("query_duration_sec", 0.0) or 0.0)
        stats_payload = compute_track_layer_stats(segments, query_duration_sec=query_duration)
    return {
        "format": "videoseek_clone_match_v1",
        "component_id": str(component_id or ""),
        "query_path": str(query_path or ""),
        "library_path": str(library_path or ""),
        "sample_fps": float(fps or 0.0),
        "timeline_fps": float(timeline_fps or 24.0),
        "export_mode": mode,
        "segment_count": len(items),
        "coverage": coverage_payload,
        "track_stats": stats_payload,
        "segments": items,
        "notes": {
            "resolve": (
                "Prefer companion .fcpxml (File > Import > Timeline). "
                "FCP7 .xml also works. V3=strong (top), V2=soft, V1=blob. "
                "Import source media into Media Pool if offline."
            ),
            "premiere": (
                "File > Import the companion FCP7 .xml. "
                "Multi-track V1–V3 stays stacked; relink if clips are offline."
            ),
            "export_mode": {
                EXPORT_MODE_STRICT: "V3 only (strict provenance)",
                EXPORT_MODE_BALANCED: "V3 + V2 (remix review)",
                EXPORT_MODE_COVERAGE: "V3 + V2 + V1 (max coverage)",
            }.get(mode, mode),
            "track_stats": (
                "track_stats is computed on full match evidence (all tracks), "
                "while segments follow export_mode filtering."
            ),
        },
    }


def write_clone_match_json(path: str, payload: dict[str, Any]) -> str:
    out = os.path.normpath(str(path or ""))
    if not out.lower().endswith(".json"):
        out = f"{out}.json"
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return out


def build_clone_match_edl(
    *,
    title: str,
    segments: list[dict[str, Any]],
    timeline_fps: float = 24.0,
    query_path: str = "",
    export_mode: str | None = None,
) -> str:
    """CMX 3600 EDL: single track = higher-track-wins composite."""
    flatten_tracks_by_priority = _tm().flatten_tracks_by_priority

    filtered = filter_segments_for_export_mode(segments, export_mode)
    normalized = normalize_segments_for_export(filtered, timeline_fps=timeline_fps)
    if any(int(row.get("track", 0) or 0) > 0 for row in normalized):
        normalized = flatten_tracks_by_priority(normalized)
    lines = [
        f"TITLE: {str(title or 'VideoSeek Clone Match').strip() or 'VideoSeek Clone Match'}",
        "FCM: NON-DROP FRAME",
        "",
    ]
    event = 1
    for segment in normalized:
        source_path = os.path.normpath(str(segment.get("source_video_path", "") or ""))
        source_start = float(segment.get("source_start", 0.0) or 0.0)
        source_end = float(segment.get("source_end", source_start) or source_start)
        query_start = float(segment.get("query_start", 0.0) or 0.0)
        query_end = float(segment.get("query_end", query_start) or query_start)
        dur = max(query_end - query_start, source_end - source_start, 1.0 / max(timeline_fps, 1e-6))
        lines.append(
            f"{event:03d}  {'AX':<8} V     C        "
            f"{seconds_to_timecode(source_start, fps=timeline_fps)} "
            f"{seconds_to_timecode(source_start + dur, fps=timeline_fps)} "
            f"{seconds_to_timecode(query_start, fps=timeline_fps)} "
            f"{seconds_to_timecode(query_start + dur, fps=timeline_fps)}"
        )
        clip_name = os.path.basename(source_path) or "AX"
        lines.append(f"* FROM CLIP NAME: {clip_name}")
        if source_path:
            lines.append(f"* SOURCE FILE: {source_path}")
        lines.append("")
        event += 1
    _ = query_path  # reserved for future TITLE/notes
    return "\n".join(lines).rstrip() + "\n"


def write_clone_match_edl(path: str, edl_text: str) -> str:
    out = os.path.normpath(str(path or ""))
    if not out.lower().endswith(".edl"):
        out = f"{out}.edl"
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(str(edl_text or ""))
    return out


def _file_url(path: str) -> str:
    """Premiere/Resolve-safe pathurl (shared with shot-list NLE export)."""
    from src.services.fcpxml_export_service import media_path_to_premiere_pathurl

    return media_path_to_premiere_pathurl(path)


def _file_id(path: str) -> str:
    digest = hashlib.md5(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:10]
    return f"file-{digest}"


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


def build_clone_match_fcp7_xml(
    *,
    title: str,
    segments: list[dict[str, Any]],
    timeline_fps: float = 24.0,
    query_path: str = "",
    export_mode: str | None = None,
) -> str:
    """FCP7 XMEML: multi-track remix timeline (V1 blob / V2 soft / V3 strong) + stereo audio."""
    from src.services.fcpxml_export_service import (
        _fcp7_link_xml,
        _fcp7_rate_fields,
        _fcp7_rate_xml,
        _seconds_to_frames,
        _xml_escape,
        media_path_to_premiere_pathurl,
    )

    project_fps = max(float(timeline_fps or 24.0), 1e-6)
    by_track, media_cache, max_end = _prepare_clone_timeline_clips(
        segments,
        timeline_fps=project_fps,
        export_mode=export_mode,
    )
    timebase, _ntsc = _fcp7_rate_fields(project_fps)

    query_duration_frames = 0
    query_file = str(query_path or "").strip()
    if query_file and os.path.isfile(query_file):
        query_info = _probe_media(query_file)
        query_duration_frames = _seconds_to_frames(float(query_info.get("duration") or 0.0), project_fps)
    seq_duration = max(max_end, query_duration_frames, 1)

    width = 1920
    height = 1080
    if media_cache:
        first = next(iter(media_cache.values()))
        width = int(first.get("width") or 1920)
        height = int(first.get("height") or 1080)

    safe_title = _xml_escape(str(title or "VideoSeek Clone Match").strip() or "VideoSeek Clone Match")
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE xmeml>",
        '<xmeml version="5">',
        "    <sequence>",
        f"        <name>{safe_title}</name>",
        f"        <duration>{seq_duration}</duration>",
        *_fcp7_rate_xml(project_fps, "        "),
        "        <timecode>",
        *_fcp7_rate_xml(project_fps, "            "),
        "            <string>00:00:00:00</string>",
        "            <frame>0</frame>",
        "            <displayformat>NDF</displayformat>",
        "        </timecode>",
        "        <media>",
        "            <video>",
        "                <format>",
        "                    <samplecharacteristics>",
        f"                        <width>{width}</width>",
        f"                        <height>{height}</height>",
        "                        <pixelaspectratio>square</pixelaspectratio>",
        *_fcp7_rate_xml(project_fps, "                        "),
        "                    </samplecharacteristics>",
        "                </format>",
    ]

    # Assign stable ids so video/audio links can cross-reference.
    clip_meta: list[dict[str, Any]] = []
    clip_counter = 0
    track_ids = sorted(by_track.keys()) or [1]
    for track_id in track_ids:
        for clip in by_track.get(track_id, []):
            clip_counter += 1
            clip_meta.append(
                {
                    **clip,
                    "video_id": f"clipitem-{clip_counter}",
                    "audio_id": f"audio-clipitem-{clip_counter}",
                    "audio_id_2": f"audio-clipitem-{clip_counter}b",
                    "clipindex": clip_counter,
                }
            )

    declared_files: set[str] = set()
    meta_by_track: dict[int, list[dict[str, Any]]] = {}
    for entry in clip_meta:
        meta_by_track.setdefault(int(entry["track"]), []).append(entry)

    # Bottom → top (V1, V2, V3).
    for track_id in track_ids:
        lines.append("                <track>")
        for entry in meta_by_track.get(track_id, []):
            source_path = str(entry["path"])
            info = media_cache.get(source_path) or {}
            media_fps = float(info.get("fps") or 0.0)
            if media_fps <= 1:
                media_fps = project_fps
            media_frames = max(
                1,
                _seconds_to_frames(float(info.get("duration") or 0.0), media_fps),
            )
            if media_frames <= int(entry["out"]):
                media_frames = max(int(entry["out"]) + timebase, int(entry["out"]) + 1)
            file_id = _file_id(source_path)
            pathurl = media_path_to_premiere_pathurl(source_path)
            lines.extend(
                [
                    f'                    <clipitem id="{entry["video_id"]}">',
                    f"                        <name>{_xml_escape(entry['name'])}</name>",
                    f"                        <duration>{entry['duration']}</duration>",
                    *_fcp7_rate_xml(project_fps, "                        "),
                    f"                        <start>{entry['start']}</start>",
                    f"                        <end>{entry['end']}</end>",
                    f"                        <in>{entry['in']}</in>",
                    f"                        <out>{entry['out']}</out>",
                ]
            )
            if file_id in declared_files:
                lines.append(f'                        <file id="{file_id}"/>')
            else:
                declared_files.add(file_id)
                lines.extend(
                    [
                        f'                        <file id="{file_id}">',
                        f"                            <name>{_xml_escape(entry['name'])}</name>",
                        f"                            <pathurl>{_xml_escape(pathurl)}</pathurl>",
                        *_fcp7_rate_xml(media_fps, "                            "),
                        f"                            <duration>{media_frames}</duration>",
                        "                            <media>",
                        "                                <video>",
                        f"                                    <duration>{media_frames}</duration>",
                        "                                    <samplecharacteristics>",
                        *_fcp7_rate_xml(media_fps, "                                        "),
                        f"                                        <width>{int(info.get('width') or width)}</width>",
                        f"                                        <height>{int(info.get('height') or height)}</height>",
                        "                                    </samplecharacteristics>",
                        "                                </video>",
                        "                                <audio>",
                        f"                                    <duration>{media_frames}</duration>",
                        "                                    <samplecharacteristics>",
                        "                                        <depth>16</depth>",
                        "                                        <samplerate>48000</samplerate>",
                        "                                    </samplecharacteristics>",
                        "                                    <channelcount>2</channelcount>",
                        "                                </audio>",
                        "                            </media>",
                        "                        </file>",
                    ]
                )
            lines.extend(
                [
                    "                        <sourcetrack>",
                    "                            <mediatype>video</mediatype>",
                    "                            <trackindex>1</trackindex>",
                    "                        </sourcetrack>",
                    *_fcp7_link_xml(
                        video_id=str(entry["video_id"]),
                        audio_ids=[str(entry["audio_id"]), str(entry["audio_id_2"])],
                        clipindex=int(entry["clipindex"]),
                        indent="                        ",
                    ),
                    "                    </clipitem>",
                ]
            )
        lines.append("                </track>")

    lines.extend(
        [
            "            </video>",
            "            <audio>",
            "                <numOutputChannels>2</numOutputChannels>",
            "                <format>",
            "                    <samplecharacteristics>",
            "                        <depth>16</depth>",
            "                        <samplerate>48000</samplerate>",
            "                    </samplecharacteristics>",
            "                </format>",
        ]
    )
    # Per video track: stereo A pair so overlapping V-lanes do not collide on one A track.
    for track_id in track_ids:
        for channel in (1, 2):
            id_key = "audio_id" if channel == 1 else "audio_id_2"
            lines.append("                <track>")
            for entry in meta_by_track.get(track_id, []):
                source_path = str(entry["path"])
                info = media_cache.get(source_path) or {}
                media_fps = float(info.get("fps") or 0.0)
                if media_fps <= 1:
                    media_fps = project_fps
                media_frames = max(
                    1,
                    _seconds_to_frames(float(info.get("duration") or 0.0), media_fps),
                )
                audio_file_id = f"{_file_id(source_path)}-a{track_id}-{channel}"
                pathurl = media_path_to_premiere_pathurl(source_path)
                lines.extend(
                    [
                        f'                    <clipitem id="{entry[id_key]}">',
                        f"                        <name>{_xml_escape(entry['name'])}</name>",
                        f"                        <duration>{entry['duration']}</duration>",
                        *_fcp7_rate_xml(project_fps, "                        "),
                        f"                        <start>{entry['start']}</start>",
                        f"                        <end>{entry['end']}</end>",
                        f"                        <in>{entry['in']}</in>",
                        f"                        <out>{entry['out']}</out>",
                        f'                        <file id="{audio_file_id}">',
                        f"                            <name>{_xml_escape(entry['name'])}</name>",
                        f"                            <pathurl>{_xml_escape(pathurl)}</pathurl>",
                        *_fcp7_rate_xml(media_fps, "                            "),
                        f"                            <duration>{media_frames}</duration>",
                        "                            <media>",
                        "                                <audio>",
                        f"                                    <duration>{media_frames}</duration>",
                        "                                    <samplecharacteristics>",
                        "                                        <depth>16</depth>",
                        "                                        <samplerate>48000</samplerate>",
                        "                                    </samplecharacteristics>",
                        "                                    <channelcount>2</channelcount>",
                        "                                </audio>",
                        "                            </media>",
                        "                        </file>",
                        "                        <sourcetrack>",
                        "                            <mediatype>audio</mediatype>",
                        f"                            <trackindex>{channel}</trackindex>",
                        "                        </sourcetrack>",
                        *_fcp7_link_xml(
                            video_id=str(entry["video_id"]),
                            audio_ids=[str(entry["audio_id"]), str(entry["audio_id_2"])],
                            clipindex=int(entry["clipindex"]),
                            indent="                        ",
                        ),
                        "                    </clipitem>",
                    ]
                )
            lines.append("                </track>")
    lines.extend(
        [
            "            </audio>",
            "        </media>",
            "    </sequence>",
            "</xmeml>",
            "",
        ]
    )
    return "\n".join(lines)


def write_clone_match_fcp7_xml(path: str, xml_text: str) -> str:
    out = os.path.normpath(str(path or ""))
    if not out.lower().endswith(".xml"):
        out = f"{out}.xml"
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(str(xml_text or ""))
    return out


def build_clone_match_fcpxml(
    *,
    title: str,
    segments: list[dict[str, Any]],
    timeline_fps: float = 24.0,
    query_path: str = "",
    export_mode: str | None = None,
) -> str:
    """FCPXML 1.8 multi-lane timeline for DaVinci Resolve (query-aligned, not sequential)."""
    from src.services.fcpxml_export_service import (
        _FCPXML_VERSION,
        _format_name,
        _frame_duration_rational,
        _xml_escape,
        fcpxml_time,
        media_path_to_premiere_pathurl,
    )

    project_fps = max(float(timeline_fps or 24.0), 1e-6)
    by_track, media_cache, max_end = _prepare_clone_timeline_clips(
        segments,
        timeline_fps=project_fps,
        export_mode=export_mode,
    )
    query_duration_sec = 0.0
    query_file = str(query_path or "").strip()
    if query_file and os.path.isfile(query_file):
        query_info = _probe_media(query_file)
        query_duration_sec = float(query_info.get("duration") or 0.0)
    if query_duration_sec <= 0:
        query_duration_sec = max_end / project_fps if max_end > 0 else 1.0 / project_fps
    seq_duration_sec = max(query_duration_sec, max_end / project_fps, 1.0 / project_fps)

    width = 1920
    height = 1080
    if media_cache:
        first = next(iter(media_cache.values()))
        width = int(first.get("width") or 1920)
        height = int(first.get("height") or 1080)

    frame_num, frame_den = _frame_duration_rational(project_fps)
    seq_frame_duration = f"{frame_num}/{frame_den}s"
    safe_title = _xml_escape(str(title or "VideoSeek Clone Match").strip() or "VideoSeek Clone Match")

    # Assets keyed by path.
    asset_order: list[str] = []
    assets: dict[str, dict[str, Any]] = {}
    for path, info in media_cache.items():
        key = os.path.normcase(path)
        if key in assets:
            continue
        media_fps = float(info.get("fps") or 0.0)
        if media_fps <= 1:
            media_fps = project_fps
        asset_id = f"r{3 + len(asset_order) * 2}"
        format_id = f"r{2 + len(asset_order) * 2}"
        assets[key] = {
            "path": path,
            "id": asset_id,
            "format_id": format_id,
            "name": os.path.splitext(os.path.basename(path))[0] or "clip",
            "src": media_path_to_premiere_pathurl(path),
            "duration": float(info.get("duration") or 0.0) or 1.0 / media_fps,
            "fps": media_fps,
            "width": int(info.get("width") or width),
            "height": int(info.get("height") or height),
            "uid": str(uuid4()).upper(),
        }
        asset_order.append(key)

    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        f'<fcpxml version="{_FCPXML_VERSION}">',
        "    <resources>",
        (
            f'        <format id="r1" name="{_format_name(height, project_fps)}" '
            f'frameDuration="{seq_frame_duration}" width="{width}" height="{height}"/>'
        ),
    ]
    for key in asset_order:
        asset = assets[key]
        asset_fps = float(asset["fps"])
        a_num, a_den = _frame_duration_rational(asset_fps)
        lines.append(
            (
                f'        <format id="{asset["format_id"]}" '
                f'name="{_format_name(int(asset["height"]), asset_fps)}" '
                f'frameDuration="{a_num}/{a_den}s" '
                f'width="{int(asset["width"])}" height="{int(asset["height"])}"/>'
            )
        )
        lines.append(
            (
                f'        <asset id="{asset["id"]}" name="{_xml_escape(asset["name"])}" '
                f'uid="{asset["uid"]}" start="0s" '
                f'duration="{fcpxml_time(float(asset["duration"]), asset_fps)}" '
                f'hasVideo="1" hasAudio="1" format="{asset["format_id"]}" '
                f'src="{_xml_escape(asset["src"])}"/>'
            )
        )
    lines.extend(
        [
            "    </resources>",
            "    <library>",
            '        <event name="VideoSeek Clone Match">',
            f'            <project name="{safe_title}">',
            (
                f'                <sequence format="r1" '
                f'duration="{fcpxml_time(seq_duration_sec, project_fps)}" '
                f'tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">'
            ),
            "                    <spine>",
        ]
    )

    # lane = track-1 so V1 is primary spine lane, V2/V3 stack above (Resolve-friendly).
    ordered_clips: list[dict[str, Any]] = []
    for track_id in sorted(by_track.keys()):
        for clip in by_track.get(track_id, []):
            ordered_clips.append(clip)
    ordered_clips.sort(
        key=lambda row: (
            float(row.get("query_start", 0.0) or 0.0),
            int(row.get("track", 1) or 1),
        )
    )
    for clip in ordered_clips:
        key = os.path.normcase(str(clip["path"]))
        asset = assets.get(key)
        if asset is None:
            continue
        lane = max(int(clip.get("track", 1) or 1) - 1, 0)
        asset_fps = float(asset["fps"])
        lane_attr = f' lane="{lane}"' if lane > 0 else ""
        lines.append(
            (
                f'                        <asset-clip name="{_xml_escape(clip["name"])}" '
                f'ref="{asset["id"]}" '
                f'offset="{fcpxml_time(float(clip["query_start"]), project_fps)}" '
                f'start="{fcpxml_time(float(clip["source_start"]), asset_fps)}" '
                f'duration="{fcpxml_time(float(clip["duration_sec"]), project_fps)}" '
                f'format="{asset["format_id"]}" '
                f'tcFormat="NDF"{lane_attr}/>'
            )
        )

    lines.extend(
        [
            "                    </spine>",
            "                </sequence>",
            "            </project>",
            "        </event>",
            "    </library>",
            "</fcpxml>",
            "",
        ]
    )
    return "\n".join(lines)


def write_clone_match_fcpxml(path: str, xml_text: str) -> str:
    out = os.path.normpath(str(path or ""))
    if not out.lower().endswith(".fcpxml"):
        out = f"{out}.fcpxml"
    with open(out, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(str(xml_text or ""))
    return out
