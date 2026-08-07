"""Build NLE timeline XML for DaVinci Resolve (FCPXML) and Premiere Pro (FCP7 XMEML)."""

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

# FCPXML 1.8 is widely accepted by DaVinci Resolve (not Premiere Pro).
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
    """Convert a local filesystem path to a file:// URL (Resolve / FCPXML)."""
    abs_path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not abs_path:
        raise ValueError("empty media path")
    return Path(abs_path).resolve().as_uri()


def media_path_to_premiere_pathurl(path: str) -> str:
    """FCP7 ``pathurl`` for Premiere and Resolve on Windows.

    Premiere misreads ``file:///E:/...`` as ``\\\\\\E:\\...``.
    Resolve often fails on ``file://localhost/E%3a/...`` (encoded colon).
    ``file://localhost/E:/...`` keeps localhost for Premiere and a real ``:`` for Resolve.
    """
    uri = media_path_to_file_url(path)
    if uri.startswith("file:///"):
        return "file://localhost/" + uri[len("file:///") :]
    if uri.startswith("file://"):
        return uri
    return media_path_to_file_url(path)


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


def _snap_fps(value: Optional[float], *, derived: Optional[float] = None) -> Optional[float]:
    """Prefer a standard rate when container metadata disagrees with frame_count/duration."""
    candidates: List[float] = []
    if value is not None and float(value) > 1:
        candidates.append(float(value))
    if derived is not None and float(derived) > 1:
        candidates.append(float(derived))
    if not candidates:
        return None
    standards = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)
    # If metadata and derived disagree, trust derived when it lands on a standard rate.
    if (
        value is not None
        and derived is not None
        and abs(float(value) - float(derived)) > 0.5
    ):
        for std in standards:
            if abs(float(derived) - std) < 0.08:
                return float(std)
    primary = float(candidates[0])
    for std in standards:
        if abs(primary - std) < 0.08:
            return float(std)
    return primary


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
        avg = timing.get("avg_frame_rate")
        if fps is not None and float(fps) > 0:
            derived = float(avg) if avg is not None and float(avg) > 0 else None
            info["fps"] = _snap_fps(float(fps), derived=derived)
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
            if info["width"] is None and opencv.get("width"):
                info["width"] = float(opencv["width"])
            if info["height"] is None and opencv.get("height"):
                info["height"] = float(opencv["height"])
            if info["duration"] is None and opencv.get("duration"):
                info["duration"] = float(opencv["duration"])
            derived = None
            frame_count = opencv.get("frame_count")
            duration = info.get("duration") or opencv.get("duration")
            if frame_count and duration and float(duration) > 0:
                derived = float(frame_count) / float(duration)
            if info["fps"] is None or derived is not None:
                info["fps"] = _snap_fps(info.get("fps") or opencv.get("fps"), derived=derived)
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


def _seconds_to_frames(seconds: float, fps: float) -> int:
    num, den = _frame_duration_rational(fps)
    return max(0, int(round(float(seconds) * den / num)))


def _fcp7_rate_fields(fps: float) -> Tuple[int, bool]:
    """Return (timebase, ntsc) for FCP7 / Premiere XML."""
    rate = float(fps) if float(fps or 0.0) > 0 else _DEFAULT_FPS
    if abs(rate - 23.976) < 0.02 or abs(rate - 24000 / 1001) < 0.02:
        return 24, True
    if abs(rate - 29.97) < 0.02 or abs(rate - 30000 / 1001) < 0.02:
        return 30, True
    if abs(rate - 59.94) < 0.02 or abs(rate - 60000 / 1001) < 0.02:
        return 60, True
    return max(1, int(round(rate))), False


def _fcp7_rate_xml(fps: float, indent: str) -> List[str]:
    timebase, ntsc = _fcp7_rate_fields(fps)
    return [
        f"{indent}<rate>",
        f"{indent}    <timebase>{timebase}</timebase>",
        f"{indent}    <ntsc>{'TRUE' if ntsc else 'FALSE'}</ntsc>",
        f"{indent}</rate>",
    ]


def _fcp7_link_xml(
    *,
    video_id: str,
    audio_ids: Sequence[str],
    clipindex: int,
    indent: str,
) -> List[str]:
    """Premiere-style A/V link block so picture and sound stay grouped."""
    lines = [
        f"{indent}<link>",
        f"{indent}    <linkclipref>{_xml_escape(video_id)}</linkclipref>",
        f"{indent}    <mediatype>video</mediatype>",
        f"{indent}    <trackindex>1</trackindex>",
        f"{indent}    <clipindex>{int(clipindex)}</clipindex>",
        f"{indent}</link>",
    ]
    for track_index, audio_id in enumerate(audio_ids, start=1):
        lines.extend(
            [
                f"{indent}<link>",
                f"{indent}    <linkclipref>{_xml_escape(audio_id)}</linkclipref>",
                f"{indent}    <mediatype>audio</mediatype>",
                f"{indent}    <trackindex>{track_index}</trackindex>",
                f"{indent}    <clipindex>{int(clipindex)}</clipindex>",
                f"{indent}    <groupindex>1</groupindex>",
                f"{indent}</link>",
            ]
        )
    return lines


def _prepare_shot_list_timeline(
    items: Sequence[ShotListItem],
    *,
    fps: Optional[float] = None,
) -> Dict[str, Any]:
    """Shared timeline model for FCPXML and FCP7 XML exporters."""
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
            "No local media files available for NLE XML export. "
            "Remote team play URLs and missing files cannot be linked into Premiere/Resolve."
        )

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
                start, duration = _clip_span_seconds(other, asset_fps, media_duration=None)
                asset_duration = max(float(asset_duration), start + duration)
            asset_duration = max(float(asset_duration), 1.0 / asset_fps)
        asset_by_path[key] = {
            "path": abs_path,
            "src": media_path_to_file_url(abs_path),
            "pathurl": media_path_to_premiere_pathurl(abs_path),
            "name": os.path.splitext(os.path.basename(abs_path))[0] or "clip",
            "duration": float(asset_duration),
            "fps": asset_fps,
            "width": width,
            "height": height,
            "tc_start": tc_start,
            "uid": str(uuid4()).upper(),
            "file_id": f"file-{len(asset_order) + 1}",
        }
        asset_order.append(key)

    for index, key in enumerate(asset_order):
        asset_by_path[key]["format_id"] = f"r{2 + index * 2}"
        asset_by_path[key]["id"] = f"r{3 + index * 2}"

    project_fps = float(fps) if fps and float(fps) > 0 else _choose_project_fps(local_items, asset_by_path)
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
        max_dur = max(float(asset["duration"]) - content_start, 1.0 / asset_fps)
        duration_sec = min(duration_sec, max_dur)
        source_start = float(asset["tc_start"]) + content_start
        base_name = os.path.splitext(os.path.basename(abs_path))[0] or "clip"
        clip_name = f"{index:02d}_{base_name}_{int(content_start)}"
        spine_clips.append(
            {
                "ref": asset["id"],
                "file_id": asset["file_id"],
                "asset_key": key,
                "name": clip_name,
                "offset": timeline_offset,
                "content_start": content_start,
                "start": source_start,
                "duration": duration_sec,
                "fps": asset_fps,
                "format_id": asset["format_id"],
            }
        )
        timeline_offset += duration_sec

    return {
        "local_items": local_items,
        "asset_by_path": asset_by_path,
        "asset_order": asset_order,
        "spine_clips": spine_clips,
        "project_fps": project_fps,
        "sequence_duration": max(timeline_offset, 1.0 / project_fps),
        "seq_width": int(asset_by_path[asset_order[0]]["width"]),
        "seq_height": int(asset_by_path[asset_order[0]]["height"]),
        "skipped_remote": skipped_remote,
        "skipped_missing": skipped_missing,
    }


def build_fcpxml_document(
    items: Sequence[ShotListItem],
    *,
    project_name: str = "VideoSeek",
    event_name: str = "VideoSeek Shot List",
    fps: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (FCPXML text, meta) for Resolve / Final Cut (not Premiere)."""
    prepared = _prepare_shot_list_timeline(items, fps=fps)
    asset_by_path = prepared["asset_by_path"]
    asset_order = prepared["asset_order"]
    spine_clips = prepared["spine_clips"]
    project_fps = float(prepared["project_fps"])
    sequence_duration = float(prepared["sequence_duration"])
    seq_width = int(prepared["seq_width"])
    seq_height = int(prepared["seq_height"])
    skipped_remote = int(prepared["skipped_remote"])
    skipped_missing = int(prepared["skipped_missing"])
    local_items = prepared["local_items"]

    seq_frame_num, seq_frame_den = _frame_duration_rational(project_fps)
    seq_frame_duration = f"{seq_frame_num}/{seq_frame_den}s"
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
                f'src="{_xml_escape(asset["pathurl"])}"/>'
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
        "format": "fcpxml",
    }
    return "\n".join(lines), meta


def build_fcp7_xml_document(
    items: Sequence[ShotListItem],
    *,
    project_name: str = "VideoSeek",
    fps: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (FCP7 XMEML text, meta) for Premiere Pro and Resolve."""
    prepared = _prepare_shot_list_timeline(items, fps=fps)
    asset_by_path = prepared["asset_by_path"]
    asset_order = prepared["asset_order"]
    spine_clips = prepared["spine_clips"]
    project_fps = float(prepared["project_fps"])
    seq_width = int(prepared["seq_width"])
    seq_height = int(prepared["seq_height"])
    skipped_remote = int(prepared["skipped_remote"])
    skipped_missing = int(prepared["skipped_missing"])
    local_items = prepared["local_items"]
    safe_project = _xml_escape(project_name or "VideoSeek")

    # Accumulate integer frames so consecutive clips never overlap from seconds→frames rounding
    # (e.g. frames(24s)=575 vs frames(18s)+frames(6s)=576).
    timeline_clips: List[Dict[str, Any]] = []
    tl_cursor = 0
    for index, clip in enumerate(spine_clips, start=1):
        tl_dur = max(1, _seconds_to_frames(clip["duration"], project_fps))
        source_in = _seconds_to_frames(clip["content_start"], project_fps)
        timeline_clips.append(
            {
                "index": index,
                "clip": clip,
                "asset": asset_by_path[clip["asset_key"]],
                "tl_start": tl_cursor,
                "tl_dur": tl_dur,
                "tl_end": tl_cursor + tl_dur,
                "source_in": source_in,
                "source_out": source_in + tl_dur,
                "video_id": f"clipitem-{index}",
                "audio_id": f"audio-clipitem-{index}",
                "audio_id_2": f"audio-clipitem-{index}b",
            }
        )
        tl_cursor += tl_dur
    seq_frames = max(1, tl_cursor)

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE xmeml>",
        '<xmeml version="5">',
        "    <sequence>",
        f"        <name>{safe_project}</name>",
        f"        <duration>{seq_frames}</duration>",
    ]
    lines.extend(_fcp7_rate_xml(project_fps, "        "))
    lines.extend(
        [
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
            f"                        <width>{seq_width}</width>",
            f"                        <height>{seq_height}</height>",
            "                        <pixelaspectratio>square</pixelaspectratio>",
            *_fcp7_rate_xml(project_fps, "                        "),
            "                    </samplecharacteristics>",
            "                </format>",
            "                <track>",
        ]
    )

    emitted_files: set[str] = set()
    for entry in timeline_clips:
        clip = entry["clip"]
        asset = entry["asset"]
        clip_fps = float(clip["fps"])
        file_id = str(clip["file_id"])
        index = int(entry["index"])
        # Premiere treats clipitem duration/in/out in the *sequence* timebase on mixed-fps
        # timelines. Encoding those in media fps made only non-sequence-rate clips drift
        # (e.g. 44:48 @29.97 became ~55:56 when read as 23.976). File rate stays native.
        lines.extend(
            [
                f'                    <clipitem id="{entry["video_id"]}">',
                f"                        <name>{_xml_escape(clip['name'])}</name>",
                f"                        <duration>{entry['tl_dur']}</duration>",
                *_fcp7_rate_xml(project_fps, "                        "),
                f"                        <start>{entry['tl_start']}</start>",
                f"                        <end>{entry['tl_end']}</end>",
                f"                        <in>{entry['source_in']}</in>",
                f"                        <out>{entry['source_out']}</out>",
            ]
        )
        if file_id in emitted_files:
            lines.append(f'                        <file id="{file_id}"/>')
        else:
            emitted_files.add(file_id)
            media_frames = max(1, _seconds_to_frames(float(asset["duration"]), clip_fps))
            lines.extend(
                [
                    f'                        <file id="{file_id}">',
                    f"                            <name>{_xml_escape(asset['name'])}</name>",
                    f"                            <pathurl>{_xml_escape(asset['pathurl'])}</pathurl>",
                    *_fcp7_rate_xml(clip_fps, "                            "),
                    f"                            <duration>{media_frames}</duration>",
                    "                            <media>",
                    "                                <video>",
                    f"                                    <duration>{media_frames}</duration>",
                    "                                    <samplecharacteristics>",
                    *_fcp7_rate_xml(clip_fps, "                                        "),
                    f"                                        <width>{int(asset['width'])}</width>",
                    f"                                        <height>{int(asset['height'])}</height>",
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
                    clipindex=index,
                    indent="                        ",
                ),
                "                    </clipitem>",
            ]
        )

    lines.extend(
        [
            "                </track>",
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
    # Premiere-style stereo: A1 + A2, each with its own full file block.
    # Resolve fails on bare <file id="file-N"/> audio refs ("not found in search directory")
    # and also on partial re-declarations of the same id — use distinct ids + full pathurl.
    for track_index, id_key in ((1, "audio_id"), (2, "audio_id_2")):
        lines.append("                <track>")
        for entry in timeline_clips:
            clip = entry["clip"]
            asset = entry["asset"]
            clip_fps = float(clip["fps"])
            index = int(entry["index"])
            audio_id = str(entry[id_key])
            audio_file_id = f"{clip['file_id']}-a{track_index}"
            media_frames = max(1, _seconds_to_frames(float(asset["duration"]), clip_fps))
            lines.extend(
                [
                    f'                    <clipitem id="{audio_id}">',
                    f"                        <name>{_xml_escape(clip['name'])}</name>",
                    f"                        <duration>{entry['tl_dur']}</duration>",
                    *_fcp7_rate_xml(project_fps, "                        "),
                    f"                        <start>{entry['tl_start']}</start>",
                    f"                        <end>{entry['tl_end']}</end>",
                    f"                        <in>{entry['source_in']}</in>",
                    f"                        <out>{entry['source_out']}</out>",
                    f'                        <file id="{audio_file_id}">',
                    f"                            <name>{_xml_escape(asset['name'])}</name>",
                    f"                            <pathurl>{_xml_escape(asset['pathurl'])}</pathurl>",
                    *_fcp7_rate_xml(clip_fps, "                            "),
                    f"                            <duration>{media_frames}</duration>",
                    "                            <media>",
                    "                                <video>",
                    f"                                    <duration>{media_frames}</duration>",
                    "                                    <samplecharacteristics>",
                    *_fcp7_rate_xml(clip_fps, "                                        "),
                    f"                                        <width>{int(asset['width'])}</width>",
                    f"                                        <height>{int(asset['height'])}</height>",
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
                    "                        <sourcetrack>",
                    "                            <mediatype>audio</mediatype>",
                    f"                            <trackindex>{track_index}</trackindex>",
                    "                        </sourcetrack>",
                    *_fcp7_link_xml(
                        video_id=str(entry["video_id"]),
                        audio_ids=[str(entry["audio_id"]), str(entry["audio_id_2"])],
                        clipindex=index,
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
        "format": "fcp7_xml",
    }
    return "\n".join(lines), meta


def export_shot_list_nle_xml(
    items: Sequence[ShotListItem],
    *,
    write_path: str,
    project_name: str = "VideoSeek",
    event_name: str = "VideoSeek Shot List",
    fps: Optional[float] = None,
) -> Dict[str, Any]:
    """Write NLE XML; `.xml` → FCP7 (Premiere/Resolve), `.fcpxml` → FCPXML (Resolve)."""
    target = os.path.abspath(os.path.expanduser(str(write_path or "").strip()))
    if not target:
        raise ValueError("write_path is required.")
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    lower = target.lower()
    if lower.endswith(".fcpxml"):
        xml_text, meta = build_fcpxml_document(
            items,
            project_name=project_name,
            event_name=event_name,
            fps=fps,
        )
        fmt = "fcpxml"
    else:
        if not lower.endswith(".xml"):
            target = f"{target}.xml"
        xml_text, meta = build_fcp7_xml_document(
            items,
            project_name=project_name,
            fps=fps,
        )
        fmt = "fcp7_xml"
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(xml_text)
    return {
        "ok": True,
        "write_path": target,
        "format": fmt,
        "clip_count": int(meta.get("exported_count") or 0),
        "exported_count": int(meta.get("exported_count") or 0),
        "skipped_remote": int(meta.get("skipped_remote") or 0),
        "skipped_missing": int(meta.get("skipped_missing") or 0),
        "fcpxml_version": _FCPXML_VERSION if fmt == "fcpxml" else None,
    }


def export_shot_list_fcpxml(
    items: Sequence[ShotListItem],
    *,
    write_path: str,
    project_name: str = "VideoSeek",
    event_name: str = "VideoSeek Shot List",
    fps: Optional[float] = None,
) -> Dict[str, Any]:
    """Back-compat wrapper: writes FCPXML or FCP7 XML based on file extension."""
    return export_shot_list_nle_xml(
        items,
        write_path=write_path,
        project_name=project_name,
        event_name=event_name,
        fps=fps,
    )
