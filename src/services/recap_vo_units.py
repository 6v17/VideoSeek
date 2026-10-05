"""Group recap clips into narration units and review rows.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import MATCH_STATUS_OK
from src.services.recap_match import _beats_by_id, _is_bridge_clip, is_weak_match_clip
from src.services.recap_vo_budget import (
    _clip_role,
    looks_like_insert_cut,
    _max_picture_for_vo,
    _vo_underfills_picture,
    vo_sec,
)

def group_recap_vo_units(
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group flat clips into narration units: one parent VO covering child shots.

    A unit starts at each clip that owns VO, or at the first empty clip after the
    previous unit. Following empty same-beat shots stay as children until the next
    VO-bearing clip (or beat change).
    """
    items = [dict(clip) for clip in clips or [] if isinstance(clip, Mapping)]
    by_id = _beats_by_id(beats)
    units: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        start = index
        head = items[start]
        vo = str(head.get("vo") or "").strip()
        beat_id = head.get("beat_id")
        end = start
        cursor = start + 1
        while cursor < len(items):
            nxt = items[cursor]
            nxt_vo = str(nxt.get("vo") or "").strip()
            if nxt_vo:
                break
            nxt_beat = nxt.get("beat_id")
            if beat_id is not None and nxt_beat is not None and nxt_beat != beat_id:
                break
            end = cursor
            cursor += 1
        indices = list(range(start, end + 1))
        shots: list[dict[str, Any]] = []
        picture = 0.0
        src_lo = float(items[start].get("src_in") or 0.0)
        src_hi = float(items[start].get("src_out") or src_lo)
        tl_lo = float(items[start].get("tl_in") or 0.0)
        tl_hi = float(items[end].get("tl_out") or tl_lo)
        for offset, clip_i in enumerate(indices):
            clip = items[clip_i]
            role = _clip_role(clip) or ("insert" if looks_like_insert_cut(clip) else "")
            if _is_bridge_clip(clip):
                role = "bridge"
            if role == "vo_hold":
                # Narration placeholder with no picture shot — keep unit, hide from children.
                continue
            src_in = float(clip.get("src_in") or 0.0)
            src_out = float(clip.get("src_out") or src_in)
            tl_in = float(clip.get("tl_in") or 0.0)
            tl_out = float(clip.get("tl_out") or tl_in)
            span = max(0.0, tl_out - tl_in)
            if span <= 0.04 and clip.get("duration") is not None:
                span = max(0.0, float(clip.get("duration") or 0.0))
            picture += span
            src_lo = min(src_lo, src_in)
            src_hi = max(src_hi, src_out)
            shots.append(
                {
                    "offset": offset,
                    "clip_index": clip_i,
                    "name": str(clip.get("name") or f"{clip_i + 1:02d}"),
                    "role": role,
                    "src_in": round(src_in, 3),
                    "src_out": round(src_out, 3),
                    "tl_in": round(tl_in, 3),
                    "tl_out": round(tl_out, 3),
                    "picture_sec": round(span, 3),
                }
            )
        # Re-number shot offsets so UI delete/reorder match visible children.
        for shot_i, shot in enumerate(shots):
            shot["offset"] = shot_i
        try:
            beat_int = int(beat_id) if beat_id is not None else 0
        except (TypeError, ValueError):
            beat_int = 0
        beat = by_id.get(beat_int) or {}
        speak = vo_sec(vo) if vo else 0.0
        units.append(
            {
                "unit_index": len(units),
                "clip_indices": indices,
                "start_index": start,
                "end_index": end,
                "vo": vo,
                "beat_id": beat_int or None,
                "event": str(head.get("event") or beat.get("event") or "").strip(),
                "picture_sec": round(picture, 3),
                "speak_sec": round(speak, 3),
                "cover_sec": round(max(speak, 0.0), 3),
                "src_in": round(src_lo, 3),
                "src_out": round(src_hi, 3),
                "tl_in": round(tl_lo, 3),
                "tl_out": round(tl_hi, 3),
                "shots": shots,
                "shortfall_sec": round(max(0.0, speak - picture), 3),
            }
        )
        index = end + 1
    return units

def owned_chunk_indices_for_clips(
    chunks: Sequence[Mapping[str, Any]] | None,
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    overlap_ratio: float = 0.45,
) -> set[int]:
    """Chunks covered by the given clips (by chunk_index or time overlap)."""
    return set(
        classify_chunk_usage_for_clips(
            chunks,
            unit_clips=clips,
            all_clips=clips,
            overlap_ratio=overlap_ratio,
        )
    )

def classify_chunk_usage_for_clips(
    chunks: Sequence[Mapping[str, Any]] | None,
    *,
    unit_clips: Sequence[Mapping[str, Any]] | None = None,
    all_clips: Sequence[Mapping[str, Any]] | None = None,
    overlap_ratio: float = 0.45,
) -> dict[int, str]:
    """Map chunk index -> ``unit`` | ``used`` for picker coloring.

    - ``unit``: already in the current narration unit
    - ``used``: used by some other shot in the full cut list (not in the unit)
    """

    def _covered(shots: Sequence[Mapping[str, Any]] | None) -> set[int]:
        owned: set[int] = set()
        rows = [dict(row) for row in chunks or [] if isinstance(row, Mapping)]
        items = [dict(row) for row in shots or [] if isinstance(row, Mapping)]
        if not rows or not items:
            return owned
        for index, chunk in enumerate(rows):
            try:
                c0 = float(chunk.get("start") or chunk.get("src_in") or 0.0)
                c1 = float(chunk.get("end") or chunk.get("src_out") or c0)
            except (TypeError, ValueError):
                continue
            if c1 <= c0 + 0.04:
                continue
            span = max(0.001, c1 - c0)
            for shot in items:
                try:
                    if int(shot.get("chunk_index")) == index:
                        owned.add(index)
                        break
                except (TypeError, ValueError):
                    pass
                try:
                    s0 = float(shot.get("src_in") or 0.0)
                    s1 = float(shot.get("src_out") or s0)
                except (TypeError, ValueError):
                    continue
                overlap = max(0.0, min(c1, s1) - max(c0, s0))
                if overlap >= max(0.5, span * float(overlap_ratio)):
                    owned.add(index)
                    break
        return owned

    unit_set = _covered(unit_clips)
    all_set = _covered(all_clips if all_clips is not None else unit_clips)
    usage: dict[int, str] = {}
    for index in sorted(all_set | unit_set):
        if index in unit_set:
            usage[index] = "unit"
        else:
            usage[index] = "used"
    return usage

def _unit_vo_text(block: Sequence[Mapping[str, Any]]) -> str:
    for row in block:
        text = str(row.get("vo") or "").strip()
        if text:
            return text
    return ""

def _stamp_unit_vo_on_block(block: list[dict[str, Any]], unit_vo: str) -> list[dict[str, Any]]:
    stamped: list[dict[str, Any]] = []
    for offset, row in enumerate(block):
        next_row = dict(row)
        if offset == 0:
            next_row["vo"] = unit_vo
            next_row["vo_draft"] = unit_vo
            if unit_vo:
                tl_in = float(next_row.get("tl_in") or 0.0)
                last = block[-1]
                unit_out = float(last.get("tl_out") or next_row.get("tl_out") or tl_in)
                speak = _max_picture_for_vo(unit_vo)
                vo_end = min(unit_out, tl_in + max(speak, 0.5)) if speak > 0 else unit_out
                if vo_end > tl_in + 0.04:
                    next_row["vo_tl_in"] = round(tl_in, 3)
                    next_row["vo_tl_out"] = round(vo_end, 3)
                else:
                    next_row.pop("vo_tl_in", None)
                    next_row.pop("vo_tl_out", None)
            else:
                next_row.pop("vo_tl_in", None)
                next_row.pop("vo_tl_out", None)
        else:
            next_row["vo"] = ""
            if "vo_draft" in next_row:
                next_row["vo_draft"] = ""
            next_row.pop("vo_tl_in", None)
            next_row.pop("vo_tl_out", None)
        stamped.append(next_row)
    return stamped

def recap_clip_review_rows(
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Readonly review rows for the understanding-page QC table (not an NLE)."""
    by_id = _beats_by_id(beats)
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(clips or []):
        if not isinstance(clip, Mapping):
            continue
        tl_in = float(clip.get("tl_in") or 0.0)
        tl_out = float(clip.get("tl_out") or 0.0)
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or 0.0)
        picture = max(0.0, tl_out - tl_in)
        if picture <= 0.04 and clip.get("duration") is not None:
            picture = max(0.0, float(clip.get("duration") or 0.0))
        text = str(clip.get("vo") or "").strip()
        speak = vo_sec(text) if text else 0.0
        fill = (speak / picture) if picture > 0.08 else 0.0
        try:
            beat_id = int(clip.get("beat_id"))
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) or {}
        event = str(clip.get("event") or beat.get("event") or "").strip()
        flags: list[str] = []
        if looks_like_insert_cut(clip):
            flags.append("insert")
        if _is_bridge_clip(clip):
            flags.append("bridge")
        if not text:
            if "bridge" not in flags:
                flags.append("empty_vo")
        elif _vo_underfills_picture(text, picture):
            flags.append("underfill")
        if is_weak_match_clip(clip):
            flags.append("weak_match")
        support = clip.get("evidence_support")
        if not isinstance(support, Mapping):
            support = {}
        evidence_flags: list[str] = []
        if support.get("asr"):
            evidence_flags.append("asr")
        if support.get("vlm"):
            evidence_flags.append("vlm")
        if support.get("character"):
            evidence_flags.append("character")
        if is_weak_match_clip(clip) and "vlm" not in evidence_flags and "asr" not in evidence_flags:
            evidence_flags.append("thin")
        rows.append(
            {
                "index": index,
                "name": str(clip.get("name") or f"{index + 1:02d}"),
                "tl_in": round(tl_in, 3),
                "tl_out": round(tl_out, 3),
                "src_in": round(src_in, 3),
                "src_out": round(src_out, 3),
                "beat_id": beat_id or None,
                "event": event,
                "vo": text,
                "vo_owns_shot": bool(text),
                "fill_ratio": round(fill, 3),
                "flags": flags,
                "evidence_flags": evidence_flags,
                "match_status": str(clip.get("match_status") or MATCH_STATUS_OK),
                "match_score": clip.get("match_score"),
                "picture_sec": round(picture, 3),
                "reason": str(clip.get("reason") or "").strip(),
                "evidence_required": list(
                    beat.get("evidence_required") or clip.get("evidence_required") or []
                ),
            }
        )
    return rows
