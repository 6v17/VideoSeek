"""FCPXML 1.9 + SRT writers for recap cut lists."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.dom import minidom
import xml.etree.ElementTree as ET


def fps_fraction(fps: float) -> tuple[int, int]:
    candidates = [
        (24000, 1001, 23.976),
        (24, 1, 24.0),
        (25, 1, 25.0),
        (30000, 1001, 29.97),
        (30, 1, 30.0),
        (50, 1, 50.0),
        (60000, 1001, 59.94),
        (60, 1, 60.0),
    ]
    best = min(candidates, key=lambda item: abs(fps - item[2]))
    if abs(fps - best[2]) < 0.08:
        return best[0], best[1]
    rounded = max(1, int(round(fps)))
    return rounded, 1


def quantize_frames(seconds: float, num: int, den: int) -> int:
    return max(0, int(round(float(seconds) * num / den)))


def fcpt(frames: int, num: int, den: int) -> str:
    if frames <= 0:
        return "0s"
    return f"{frames * den}/{num}s"


def srt_clock(seconds: float) -> str:
    ms = int(round(max(0.0, float(seconds)) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(clips: Sequence[Mapping[str, Any]], path: str | Path) -> Path:
    dest = Path(path)
    cues = merge_vo_cues(clips)
    lines: list[str] = []
    for index, cue in enumerate(cues, 1):
        lines.append(str(index))
        lines.append(f"{srt_clock(cue['tl_in'])} --> {srt_clock(cue['tl_out'])}")
        lines.append(str(cue.get("text") or "").strip())
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def merge_vo_cues(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Build SRT cues from TTS span times, falling back to empty-VO clip merging."""
    cues: list[dict[str, Any]] = []
    lock_extend = False
    for clip in clips:
        start = float(clip.get("tl_in") or 0.0)
        end = float(clip.get("tl_out") or 0.0)
        if end <= start:
            continue
        vo = str(clip.get("vo") or "").strip()
        explicit_start = clip.get("vo_tl_in")
        explicit_end = clip.get("vo_tl_out")
        if vo:
            if explicit_start is not None and explicit_end is not None:
                start = float(explicit_start)
                end = float(explicit_end)
                if end <= start:
                    continue
                lock_extend = True
            else:
                lock_extend = False
            cues.append({"tl_in": start, "tl_out": end, "text": vo})
        elif cues and explicit_start is None and explicit_end is None and not lock_extend:
            cues[-1]["tl_out"] = end
    return cues


def write_fcpxml(
    clips: Sequence[Mapping[str, Any]],
    *,
    video_path: str | Path,
    info: Mapping[str, Any],
    dest_path: str | Path,
    project_name: str = "VideoSeek Recap",
) -> Path:
    video = Path(video_path)
    dest = Path(dest_path)
    num, den = fps_fraction(float(info.get("fps") or 24.0))
    width = int(info.get("width") or 1920)
    height = int(info.get("height") or 1080)
    duration = float(info.get("duration") or 0.0)
    src_uri = video.resolve().as_uri()
    last_src = max(int(c["src_out_f"]) for c in clips)
    asset_frames = max(quantize_frames(duration, num, den), last_src + 1)
    seq_frames = int(clips[-1]["tl_out_f"])

    fcpxml = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(fcpxml, "resources")
    rate_name = f"{num / den:.2f}".rstrip("0").rstrip(".") if den != 1 else str(num)
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=f"FFVideoFormat{height}p{rate_name}",
        frameDuration=f"{den}/{num}s",
        width=str(width),
        height=str(height),
    )
    asset = ET.SubElement(
        resources,
        "asset",
        id="r2",
        name=video.stem,
        src=src_uri,
        start="0s",
        duration=fcpt(asset_frames, num, den),
        hasVideo="1",
        hasAudio="1",
        format="r1",
        videoSources="1",
        audioSources="1",
    )
    ET.SubElement(asset, "media-rep", kind="original-media", src=src_uri)
    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="VideoSeek Recap")
    project = ET.SubElement(event, "project", name=project_name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=fcpt(seq_frames, num, den),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")
    for clip in clips:
        ET.SubElement(
            spine,
            "asset-clip",
            name=str(clip.get("name") or "clip"),
            ref="r2",
            offset=fcpt(int(clip["tl_in_f"]), num, den),
            start=fcpt(int(clip["src_in_f"]), num, den),
            duration=fcpt(int(clip["dur_f"]), num, den),
            tcFormat="NDF",
            srcEnable="video",
        )
    rough = ET.tostring(fcpxml, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    text = pretty.decode("utf-8")
    decl, rest = text.split("\n", 1)
    dest.write_text(decl + "\n<!DOCTYPE fcpxml>\n" + rest, encoding="utf-8")
    return dest


def layout_clips_on_timeline(
    raw_clips: Sequence[Mapping[str, Any]],
    *,
    fps: float,
) -> list[dict[str, Any]]:
    num, den = fps_fraction(fps)
    built: list[dict[str, Any]] = []
    tl = 0
    for index, raw in enumerate(raw_clips, 1):
        src_in_f = quantize_frames(raw["src_in"], num, den)
        src_out_f = quantize_frames(raw["src_out"], num, den)
        if src_out_f <= src_in_f:
            src_out_f = src_in_f + max(1, quantize_frames(1.0, num, den))
        dur_f = src_out_f - src_in_f
        item = {
            "name": str(raw.get("name") or f"{index:02d}"),
            "vo": str(raw.get("vo") or "").strip(),
            "src_in_f": src_in_f,
            "src_out_f": src_out_f,
            "dur_f": dur_f,
            "tl_in_f": tl,
            "tl_out_f": tl + dur_f,
            "tl_in": tl * den / num,
            "tl_out": (tl + dur_f) * den / num,
            "src_in": src_in_f * den / num,
            "src_out": src_out_f * den / num,
            "duration": (src_out_f - src_in_f) * den / num,
            "chunk_index": raw.get("chunk_index"),
            "beat_id": raw.get("beat_id"),
            "reason": str(raw.get("reason") or "").strip(),
            "vo_draft": str(raw.get("vo_draft") or "").strip(),
            "role": str(raw.get("role") or "").strip(),
        }
        built.append(item)
        tl += dur_f
    return built


def write_cuts_json(payload: Mapping[str, Any], path: str | Path) -> Path:
    dest = Path(path)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest
