"""Hand-edit narration units on a saved recap cut list (no LLM).

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.media.fcpxml import layout_clips_on_timeline, write_srt
from src.services.recap_io import (
    load_recap_cuts,
    recap_cuts_path_for_video,
    write_recap_cuts_file,
)
from src.services.recap_vo_budget import _clip_role, _max_picture_for_vo, vo_sec
from src.services.recap_vo_units import (
    _stamp_unit_vo_on_block,
    _unit_vo_text,
    group_recap_vo_units,
)

def _write_recap_clips_payload(
    media: str,
    payload: Mapping[str, Any],
    clips: Sequence[Mapping[str, Any]],
    *,
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    info = {
        "fps": float(payload.get("fps") or 24.0),
        "width": int(payload.get("width") or 1920),
        "height": int(payload.get("height") or 1080),
    }
    laid = layout_clips_on_timeline(list(clips), fps=float(info["fps"]))
    dest = recap_cuts_path_for_video(media)
    cuts_path = write_recap_cuts_file(
        dest,
        title=str(payload.get("title") or ""),
        video_path=media,
        video_id=str(payload.get("video_id") or ""),
        info=info,
        laid_out=laid,
        beats_path=str(payload.get("beats_path") or ""),
        stage=str(payload.get("stage") or "captions"),
    )
    srt_path = ""
    if rewrite_srt:
        stem = Path(os.path.abspath(os.path.expanduser(media))).stem
        srt_dest = Path(os.path.abspath(os.path.expanduser(media))).parent / f"{stem}_recap.srt"
        srt_path = str(write_srt(laid, srt_dest))
    return {
        "ok": True,
        "cuts_path": str(cuts_path),
        "srt_path": srt_path,
        "clips": laid,
        "units": group_recap_vo_units(laid),
    }

def save_recap_vo_unit(
    video_path: str,
    clip_indices: Sequence[int],
    text: str,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Hand-edit one narration unit: VO on first shot, clear children, stamp cover time."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = sorted({int(i) for i in clip_indices})
    if not indices or indices[0] < 0 or indices[-1] >= len(clips):
        raise RuntimeError("无效的解说单元镜头范围。")
    for expected, got in enumerate(indices):
        if got != indices[0] + expected:
            raise RuntimeError("解说单元镜头必须连续。")
    body = str(text or "").strip()
    speak = _max_picture_for_vo(body) if body else 0.0
    first = indices[0]
    last = indices[-1]
    for pos in indices:
        row = dict(clips[pos])
        if pos == first:
            row["vo"] = body
            row["vo_draft"] = body
        else:
            row["vo"] = ""
            if "vo_draft" in row:
                row["vo_draft"] = ""
            row.pop("vo_tl_in", None)
            row.pop("vo_tl_out", None)
        clips[pos] = row
    head = clips[first]
    tl_in = float(head.get("tl_in") or 0.0)
    unit_out = float(clips[last].get("tl_out") or tl_in)
    if body and speak > 0:
        vo_end = min(unit_out, tl_in + max(speak, 0.5))
        if vo_end > tl_in + 0.04:
            head["vo_tl_in"] = round(tl_in, 3)
            head["vo_tl_out"] = round(vo_end, 3)
        else:
            head.pop("vo_tl_in", None)
            head.pop("vo_tl_out", None)
    else:
        head.pop("vo_tl_in", None)
        head.pop("vo_tl_out", None)
    clips[first] = head
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["start_index"] = first
    result["end_index"] = last
    result["vo"] = body
    result["speak_sec"] = round(vo_sec(body) if body else 0.0, 3)
    return result

def reorder_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    from_offset: int,
    to_offset: int,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Move one child shot inside its narration unit, then re-layout timeline."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if len(indices) < 2:
        raise RuntimeError("至少两个子镜头才能调序。")
    if from_offset < 0 or to_offset < 0 or from_offset >= len(indices) or to_offset >= len(indices):
        raise RuntimeError("子镜头位置无效。")
    if from_offset == to_offset:
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    block = [clips[i] for i in indices]
    item = block.pop(from_offset)
    block.insert(to_offset, item)
    # Keep unit VO on the chronologically first slot after reorder.
    voiced = [str(row.get("vo") or "").strip() for row in block]
    unit_vo = next((text for text in voiced if text), "")
    for offset, row in enumerate(block):
        next_row = dict(row)
        if offset == 0:
            next_row["vo"] = unit_vo
            next_row["vo_draft"] = unit_vo
        else:
            next_row["vo"] = ""
            if "vo_draft" in next_row:
                next_row["vo_draft"] = ""
            next_row.pop("vo_tl_in", None)
            next_row.pop("vo_tl_out", None)
        clips[indices[offset]] = next_row
    if unit_vo:
        head = clips[indices[0]]
        tl_in = float(head.get("tl_in") or 0.0)
        last = clips[indices[-1]]
        unit_out = float(last.get("tl_out") or tl_in)
        speak = _max_picture_for_vo(unit_vo)
        vo_end = min(unit_out, tl_in + max(speak, 0.5)) if speak > 0 else unit_out
        if vo_end > tl_in + 0.04:
            head["vo_tl_in"] = round(tl_in, 3)
            head["vo_tl_out"] = round(vo_end, 3)
        clips[indices[0]] = head
    return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)

def add_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    *,
    src_in: float,
    src_out: float,
    after_offset: int | None = None,
    name: str = "",
    chunk_index: int | None = None,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Insert a child shot into a narration unit (no LLM)."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if not indices:
        raise RuntimeError("无效的解说单元。")
    start = float(src_in)
    end = float(src_out)
    if end <= start + 0.04:
        raise RuntimeError("原片入点/出点无效。")
    anchor = clips[indices[0]]
    # VO-only placeholder: replace with the first real shot, keep narration text.
    if len(indices) == 1 and _clip_role(anchor) == "vo_hold":
        hold_vo = str(anchor.get("vo") or "").strip()
        replacement = {
            "name": str(name or "").strip() or str(anchor.get("name") or f"{len(clips):02d}"),
            "beat_id": anchor.get("beat_id"),
            "src_in": round(start, 3),
            "src_out": round(end, 3),
            "duration": round(end - start, 3),
            "vo": hold_vo,
            "vo_draft": hold_vo,
            "role": "",
            "reason": str(anchor.get("reason") or ""),
            "event": str(anchor.get("event") or ""),
        }
        if chunk_index is not None:
            try:
                replacement["chunk_index"] = int(chunk_index)
            except (TypeError, ValueError):
                pass
        clips[indices[0]] = replacement
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    insert_at = indices[-1] + 1
    if after_offset is not None and 0 <= int(after_offset) < len(indices):
        insert_at = indices[int(after_offset)] + 1
    new_clip = {
        "name": str(name or "").strip() or f"{len(clips) + 1:02d}",
        "beat_id": anchor.get("beat_id"),
        "src_in": round(start, 3),
        "src_out": round(end, 3),
        "duration": round(end - start, 3),
        "vo": "",
        "role": str(anchor.get("role") or ""),
        "reason": str(anchor.get("reason") or ""),
        "event": str(anchor.get("event") or ""),
    }
    if chunk_index is not None:
        try:
            new_clip["chunk_index"] = int(chunk_index)
        except (TypeError, ValueError):
            pass
    clips.insert(insert_at, new_clip)
    return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)

def delete_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    offset: int,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Remove one child shot. Last picture shot may leave a VO-only hold clip."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if not indices:
        raise RuntimeError("无效的解说单元。")
    # Visible shots skip vo_hold; map UI offset → real clip index.
    picture_indices = [
        i for i in indices if _clip_role(clips[i]) != "vo_hold"
    ] if indices and max(indices) < len(clips) else []
    if offset < 0 or offset >= len(picture_indices):
        raise RuntimeError("子镜头位置无效。")
    remove_at = int(picture_indices[offset])
    block = [clips[i] for i in indices]
    unit_vo = _unit_vo_text(block)
    event = str(block[0].get("event") or "").strip()
    beat_id = block[0].get("beat_id")
    removed = dict(clips[remove_at])
    del clips[remove_at]

    remaining_picture = len(picture_indices) - 1
    if remaining_picture <= 0:
        if not unit_vo:
            # No VO and no shots left — drop the unit entirely.
            return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
        speak = max(0.5, float(_max_picture_for_vo(unit_vo) or 0.5))
        src_in = float(removed.get("src_in") or 0.0)
        hold = {
            "name": str(removed.get("name") or "vo"),
            "beat_id": beat_id,
            "src_in": round(src_in, 3),
            "src_out": round(src_in + speak, 3),
            "duration": round(speak, 3),
            "vo": unit_vo,
            "vo_draft": unit_vo,
            "role": "vo_hold",
            "event": event,
            "reason": str(removed.get("reason") or ""),
        }
        clips.insert(remove_at, hold)
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)

    # Rebuild remaining unit block after the deletion (indices shift past remove_at).
    new_indices: list[int] = []
    for old in indices:
        if old == remove_at:
            continue
        new_indices.append(old - 1 if old > remove_at else old)
    remaining = [clips[i] for i in new_indices]
    stamped = _stamp_unit_vo_on_block(remaining, unit_vo)
    for idx, row in zip(new_indices, stamped):
        clips[idx] = row
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["deleted_offset"] = int(offset)
    result["vo_hold"] = False
    return result

def delete_recap_vo_unit(
    video_path: str,
    clip_indices: Sequence[int],
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Remove a whole narration unit (VO + all child shots)."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = sorted({int(i) for i in clip_indices})
    if not indices or indices[0] < 0 or indices[-1] >= len(clips):
        raise RuntimeError("无效的解说单元镜头范围。")
    for expected, got in enumerate(indices):
        if got != indices[0] + expected:
            raise RuntimeError("解说单元镜头必须连续。")
    for index in reversed(indices):
        del clips[index]
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["deleted_unit_clips"] = len(indices)
    return result
