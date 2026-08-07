"""Build Final Cut Pro XML (FCPXML) timelines for Premiere / DaVinci Resolve."""

from __future__ import annotations

import os
import re
import xml.sax.saxutils
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from src.app.logging_utils import get_logger
from src.services.shot_list_service import ShotListItem

logger = get_logger("fcpxml_export")

# FCPXML 1.8 is widely accepted by Premiere Pro and DaVinci Resolve.
_FCPXML_VERSION = "1.8"
_DEFAULT_FPS = 25.0
_DEFAULT_WIDTH = 1920
_DEFAULT_HEIGHT = 1080


def _xml_escape(text: str) -> str:
    return xml.sax.saxutils.escape(str(text or ""), {'"': "&quot;", "'": "&apos;"})


def _is_remote_media_path(path: str) -> bool:
    text = str(path or "").strip().lower()
    return text.startswith(("http://", "https://"))


def media_path_to_file_url(path: str) -> str:
    """Convert a local filesystem path to a file:// URL (Windows-safe)."""
    abs_path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not abs_path:
        raise ValueError("empty media path")
    return Path(abs_path).resolve().as_uri()


def _frame_duration_rational(fps: float) -> Tuple[int, int]:
    """Return (num, den) such that one frame = num/den seconds."""
    value = float(fps or 0.0)
    if abs(value - 23.976) < 0.02 or abs(value - 24000 / 1001) < 0.02:
        return 1001, 24000
    if abs(value - 29.97) < 0.02 or abs(value - 30000 / 1001) < 0.02:
        return 1001, 30000
    if abs(value - 59.94) < 0.02 or abs(value - 60000 / 1001) < 0.02:
        return 1001, 60000
    rounded = int(round(value))
    if rounded <= 0:
        rounded = int(_DEFAULT_FPS)
    # Match Final Cut exports: frameDuration="1/25s"
    return 1, rounded


def fcpxml_time(seconds: float, fps: float) -> str:
    """Format seconds as a frame-aligned FCPXML time value for the given rate."""
    rate = float(fps) if float(fps or 0.0) > 0 else _DEFAULT_FPS
    num, den = _frame_duration_rational(rate)
    # Snap to whole frames in this timebase: frames = round(seconds / frameDuration)
    frames = max(0, int(round(float(seconds) * den / num)))
    if frames == 0:
        return "0s"
    return f"{frames * num}/{den}s"


def _format_name(height: int, fps: float) -> str:
    h = int(height) if height and height > 0 else _DEFAULT_HEIGHT
    rate = float(fps) if float(fps or 0.0) > 0 else _DEFAULT_FPS
    if abs(rate - 23.976) < 0.02 or abs(rate - 24000 / 1001) < 0.02:
        return f"FFVideoFormat{h}p2398"
    if abs(rate - 29.97) < 0.02 or abs(rate - 30000 / 1001) < 0.02:
        return f"FFVideoFormat{h}p2997"
    if abs(rate - 59.94) < 0.02 or abs(rate - 60000 / 1001) < 0.02:
        return f"FFVideoFormat{h}p5994"
    return f"FFVideoFormat{h}p{int(round(rate))}"


def _parse_smpte_timecode(value: str, fps: float) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    parts = re.split(r"[:;]", text)
    if len(parts) != 4:
        return None
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError:
        return None
    if min(hours, minutes, seconds, frames) < 0:
        return None
    rate = float(fps) if float(fps or 0.0) > 0 else _DEFAULT_FPS
    frame_num, frame_den = _frame_duration_rational(rate)
    frame_seconds = (frame_num / frame_den) * frames
    return float(hours * 3600 + minutes * 60 + seconds) + float(frame_seconds)


_FRAME_HIT_PAD_SEC = 3.0


def _min_frame_seconds(fps: float) -> float:
    frame_num, frame_den = _frame_duration_rational(fps)
    return float(frame_num) / float(frame_den)


def _is_point_or_frame_hit(item: ShotListItem, fps: float) -> bool:
    """True when the shot-list row is a single-frame hit (no real in/out range)."""
    start = float(item.start_sec or 0.0)
    end = float(item.end_sec if item.end_sec is not None else start)
    duration = abs(end - start)
    frame = _min_frame_seconds(fps)
    kind = str(getattr(item, "match_kind", "") or "").strip().lower()
    if kind in {"clip", "segment", "dialogue", "video"} and duration >= max(0.05, frame * 0.5):
        return False
    return duration < max(0.05, frame * 0.5)


def _clip_span_seconds(
    item: ShotListItem,
    fps: float,
    media_duration: Optional[float] = None,
) -> Tuple[float, float]:
    """Return (content_start, duration) for FCPXML.

    - Segment / preview-selected ranges: keep in/out as stored.
    - Frame-level hits: export anchor±3s (6s total), clamped to media bounds.
    """
    start = max(0.0, float(item.start_sec or 0.0))
    end = max(0.0, float(item.end_sec if item.end_sec is not None else start))
    if end < start:
        start, end = end, start
    frame = _min_frame_seconds(fps)
    media_len = float(media_duration) if media_duration is not None and float(media_duration) > 0 else None

    if _is_point_or_frame_hit(item, fps):
        anchor = start
        if media_len is not None:
            anchor = min(max(0.0, anchor), media_len)
        clip_start = anchor - _FRAME_HIT_PAD_SEC
        clip_end = anchor + _FRAME_HIT_PAD_SEC
        if clip_start < 0.0:
            clip_end -= clip_start
            clip_start = 0.0
        if media_len is not None and clip_end > media_len:
            shift = clip_end - media_len
            clip_start = max(0.0, clip_start - shift)
            clip_end = media_len
    else:
        clip_start = start
        clip_end = end

    if media_len is not None:
        clip_start = max(0.0, min(clip_start, media_len))
        clip_end = max(clip_start, min(clip_end, media_len))
    else:
        clip_start = max(0.0, clip_start)
        clip_end = max(clip_start, clip_end)

    duration = clip_end - clip_start
    if duration < frame:
        if media_len is not None:
            if clip_start + frame <= media_len:
                clip_end = clip_start + frame
            else:
                clip_start = max(0.0, media_len - frame)
                clip_end = media_len
            duration = max(frame, clip_end - clip_start)
        else:
            duration = frame
    return clip_start, duration


def _probe_media(path: str) -> Dict[str, Optional[float]]:
    info: Dict[str, Optional[float]] = {
        "duration": None,
        "fps": None,
        "width": None,
        "height": None,
        "tc_start": 0.0,
    }
    try:
        from src.core.timestamp_health import probe_stream_timing

        timing = probe_stream_timing(path) or {}
        info["duration"] = timing.get("duration")
        fps = timing.get("r_frame_rate") or timing.get("avg_frame_rate")
        if fps is not None and float(fps) > 0:
            info["fps"] = float(fps)
    except Exception:
        logger.debug("timing probe failed for %s", path, exc_info=True)
    try:
        from src.media.probe import get_video_stream_info

        stream = get_video_stream_info(path) or {}
        if info["duration"] is None and stream.get("duration"):
            info["duration"] = float(stream["duration"])
        if stream.get("width"):
            info["width"] = float(stream["width"])
        if stream.get("height"):
            info["height"] = float(stream["height"])
    except Exception:
        logger.debug("stream probe failed for %s", path, exc_info=True)

    # Bundled installs often ship ffmpeg.exe without ffprobe — OpenCV fills fps/size.
    if info["fps"] is None or info["width"] is None or info["height"] is None or info["duration"] is None:
        try:
            from src.media.probe import _probe_video_stream_with_opencv

            opencv = _probe_video_stream_with_opencv(path) or {}
            if info["fps"] is None and opencv.get("fps"):
                info["fps"] = float(opencv["fps"])
            if info["width"] is None and opencv.get("width"):
                info["width"] = float(opencv["width"])
            if info["height"] is None and opencv.get("height"):
                info["height"] = float(opencv["height"])
            if info["duration"] is None and opencv.get("duration"):
                info["duration"] = float(opencv["duration"])
        except Exception:
            logger.debug("opencv media probe failed for %s", path, exc_info=True)

    if info["duration"] is None:
        try:
            from src.media.probe import get_video_duration_seconds

            duration = get_video_duration_seconds(path)
            if duration is not None and float(duration) > 0:
                info["duration"] = float(duration)
        except Exception:
            logger.debug("duration probe failed for %s", path, exc_info=True)

    tc = _probe_embedded_timecode(path, float(info["fps"] or _DEFAULT_FPS))
    if tc is not None and tc > 0:
        info["tc_start"] = float(tc)
    return info


def _probe_embedded_timecode(path: str, fps: float) -> Optional[float]:
    """Read reel/SMPTE timecode so Resolve/Premiere land on the same frame as ffmpeg -ss."""
    try:
        from src.infra.ffmpeg_paths import get_ffprobe_path
        import json
        import subprocess
        import sys

        ffprobe_path = get_ffprobe_path()
        if not ffprobe_path:
            return None
        command = [
            ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format_tags=timecode:stream_tags=timecode",
            "-select_streams",
            "v:0",
            "-of",
            "json",
            os.fspath(path),
        ]
        startupinfo = None
        if sys.platform == "win32" and hasattr(subprocess, "STARTUPINFO"):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            startupinfo=startupinfo,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        payload = json.loads(result.stdout or "{}")
        candidates: List[str] = []
        format_tags = (payload.get("format") or {}).get("tags") or {}
        if format_tags.get("timecode"):
            candidates.append(str(format_tags.get("timecode")))
        for stream in payload.get("streams") or []:
            tags = stream.get("tags") or {}
            if tags.get("timecode"):
                candidates.append(str(tags.get("timecode")))
        for raw in candidates:
            parsed = _parse_smpte_timecode(raw, fps)
            if parsed is not None:
                return parsed
    except Exception:
        logger.debug("timecode probe failed for %s", path, exc_info=True)
    return None


def _choose_project_fps(items: Sequence[ShotListItem], asset_meta: Dict[str, Dict[str, Any]]) -> float:
    for item in items:
        path = str(item.video_path or "").strip()
        if not path or _is_remote_media_path(path):
            continue
        abs_path = os.path.abspath(os.path.expanduser(path))
        key = os.path.normcase(abs_path)
        meta = asset_meta.get(key) or {}
        probed = meta.get("fps")
        if probed is not None and float(probed) > 1:
            return float(probed)
    return _DEFAULT_FPS


def build_fcpxml_document(
    items: Sequence[ShotListItem],
    *,
    project_name: str = "VideoSeek",
    event_name: str = "VideoSeek Shot List",
    fps: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (FCPXML text, meta) for a linear timeline of shot-list clips."""
    rows = [item for item in items if isinstance(item, ShotListItem)]
    if not rows:
        raise ValueError("Shot list is empty.")

    local_items: List[ShotListItem] = []
    skipped_remote = 0
    skipped_missing = 0
    for item in rows:
        path = str(item.video_path or "").strip()
        if not path:
            skipped_missing += 1
            continue
        if _is_remote_media_path(path):
            skipped_remote += 1
            continue
        if not os.path.isfile(path):
            skipped_missing += 1
            continue
        local_items.append(item)
    if not local_items:
        raise ValueError(
            "No local media files available for FCPXML export. "
            "Remote team play URLs and missing files cannot be linked into Premiere/Resolve."
        )

    # Probe each unique media file once.
    asset_by_path: Dict[str, Dict[str, Any]] = {}
    asset_order: List[str] = []
    for item in local_items:
        abs_path = os.path.abspath(os.path.expanduser(str(item.video_path)))
        key = os.path.normcase(abs_path)
        if key in asset_by_path:
            continue
        probed = _probe_media(abs_path)
        asset_fps = float(probed.get("fps") or 0.0)
        if asset_fps <= 1:
            asset_fps = float(fps) if fps and float(fps) > 0 else _DEFAULT_FPS
        width = int(probed.get("width") or _DEFAULT_WIDTH)
        height = int(probed.get("height") or _DEFAULT_HEIGHT)
        tc_start = float(probed.get("tc_start") or 0.0)
        asset_duration = probed.get("duration")
        if asset_duration is None or float(asset_duration) <= 0:
            asset_duration = 0.0
            for other in local_items:
                other_path = os.path.abspath(os.path.expanduser(str(other.video_path)))
                if os.path.normcase(other_path) != key:
                    continue
                start, duration = _clip_span_seconds(
                    other,
                    asset_fps,
                    media_duration=None,
                )
                asset_duration = max(float(asset_duration), start + duration)
            asset_duration = max(float(asset_duration), 1.0 / asset_fps)
        asset_by_path[key] = {
            "path": abs_path,
            "src": media_path_to_file_url(abs_path),
            "name": os.path.splitext(os.path.basename(abs_path))[0] or "clip",
            "duration": float(asset_duration),
            "fps": asset_fps,
            "width": width,
            "height": height,
            "tc_start": tc_start,
            "uid": str(uuid4()).upper(),
        }
        asset_order.append(key)

    # Assign stable resource ids: r1 = sequence format, then format/asset pairs.
    # formats: r2,r4,r6... assets: r3,r5,r7...
    for index, key in enumerate(asset_order):
        asset_by_path[key]["format_id"] = f"r{2 + index * 2}"
        asset_by_path[key]["id"] = f"r{3 + index * 2}"

    project_fps = float(fps) if fps and float(fps) > 0 else _choose_project_fps(local_items, asset_by_path)
    seq_frame_num, seq_frame_den = _frame_duration_rational(project_fps)
    seq_frame_duration = f"{seq_frame_num}/{seq_frame_den}s"
    seq_width = int(asset_by_path[asset_order[0]]["width"])
    seq_height = int(asset_by_path[asset_order[0]]["height"])

    spine_clips: List[Dict[str, Any]] = []
    timeline_offset = 0.0
    for index, item in enumerate(local_items, start=1):
        abs_path = os.path.abspath(os.path.expanduser(str(item.video_path)))
        key = os.path.normcase(abs_path)
        asset = asset_by_path[key]
        asset_fps = float(asset["fps"])
        content_start, duration_sec = _clip_span_seconds(
            item,
            asset_fps,
            media_duration=float(asset["duration"]),
        )
        # Clamp into media duration (content timeline, not including reel TC).
        max_dur = max(float(asset["duration"]) - content_start, 1.0 / asset_fps)
        duration_sec = min(duration_sec, max_dur)
        # Resolve/Premiere place clips on the asset timeline which starts at reel TC.
        source_start = float(asset["tc_start"]) + content_start
        base_name = os.path.splitext(os.path.basename(abs_path))[0] or "clip"
        clip_name = f"{index:02d}_{base_name}_{int(content_start)}"
        spine_clips.append(
            {
                "ref": asset["id"],
                "name": clip_name,
                "offset": timeline_offset,
                "start": source_start,
                "duration": duration_sec,
                "fps": asset_fps,
                "format_id": asset["format_id"],
            }
        )
        timeline_offset += duration_sec

    sequence_duration = max(timeline_offset, 1.0 / project_fps)
    safe_project = _xml_escape(project_name or "VideoSeek")
    safe_event = _xml_escape(event_name or "VideoSeek Shot List")

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        f'<fcpxml version="{_FCPXML_VERSION}">',
        "    <resources>",
        (
            f'        <format id="r1" name="{_format_name(seq_height, project_fps)}" '
            f'frameDuration="{seq_frame_duration}" width="{seq_width}" height="{seq_height}"/>'
        ),
    ]
    for key in asset_order:
        asset = asset_by_path[key]
        asset_fps = float(asset["fps"])
        frame_num, frame_den = _frame_duration_rational(asset_fps)
        frame_duration = f"{frame_num}/{frame_den}s"
        lines.append(
            (
                f'        <format id="{asset["format_id"]}" '
                f'name="{_format_name(int(asset["height"]), asset_fps)}" '
                f'frameDuration="{frame_duration}" '
                f'width="{int(asset["width"])}" height="{int(asset["height"])}"/>'
            )
        )
        lines.append(
            (
                f'        <asset id="{asset["id"]}" name="{_xml_escape(asset["name"])}" '
                f'uid="{asset["uid"]}" '
                f'start="{fcpxml_time(float(asset["tc_start"]), asset_fps)}" '
                f'duration="{fcpxml_time(float(asset["duration"]), asset_fps)}" '
                f'hasVideo="1" hasAudio="1" format="{asset["format_id"]}" '
                f'src="{_xml_escape(asset["src"])}"/>'
            )
        )
    lines.extend(
        [
            "    </resources>",
            "    <library>",
            f'        <event name="{safe_event}">',
            f'            <project name="{safe_project}">',
            (
                f'                <sequence format="r1" '
                f'duration="{fcpxml_time(sequence_duration, project_fps)}" '
                f'tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">'
            ),
            "                    <spine>",
        ]
    )
    for clip in spine_clips:
        clip_fps = float(clip["fps"])
        lines.append(
            (
                f'                        <asset-clip name="{_xml_escape(clip["name"])}" '
                f'ref="{clip["ref"]}" '
                f'offset="{fcpxml_time(clip["offset"], project_fps)}" '
                f'start="{fcpxml_time(clip["start"], clip_fps)}" '
                f'duration="{fcpxml_time(clip["duration"], clip_fps)}" '
                f'format="{clip["format_id"]}" '
                f'tcFormat="NDF"/>'
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
    if skipped_remote or skipped_missing:
        comment = (
            f"<!-- skipped_remote={skipped_remote} skipped_missing={skipped_missing} "
            f"exported={len(local_items)} -->"
        )
        lines.insert(3, comment)
    meta = {
        "exported_count": len(local_items),
        "skipped_remote": skipped_remote,
        "skipped_missing": skipped_missing,
        "fps": project_fps,
        "asset_count": len(asset_order),
    }
    return "\n".join(lines), meta


def export_shot_list_fcpxml(
    items: Sequence[ShotListItem],
    *,
    write_path: str,
    project_name: str = "VideoSeek",
    event_name: str = "VideoSeek Shot List",
    fps: Optional[float] = None,
) -> Dict[str, Any]:
    """Write a Premiere/Resolve-friendly FCPXML file and return a small result dict."""
    target = os.path.abspath(os.path.expanduser(str(write_path or "").strip()))
    if not target:
        raise ValueError("write_path is required.")
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    xml_text, meta = build_fcpxml_document(
        items,
        project_name=project_name,
        event_name=event_name,
        fps=fps,
    )
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)
    return {
        "ok": True,
        "write_path": target,
        "clip_count": int(meta.get("exported_count") or 0),
        "exported_count": int(meta.get("exported_count") or 0),
        "skipped_remote": int(meta.get("skipped_remote") or 0),
        "skipped_missing": int(meta.get("skipped_missing") or 0),
        "fcpxml_version": _FCPXML_VERSION,
    }
