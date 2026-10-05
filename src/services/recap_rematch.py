"""Splice / filter helpers for one-beat rematch.

LLM rematch orchestration stays in ``recap_service``. This module re-exports
the splice math. ``recap_service`` re-exports the public names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import BEAT_SRC_PAD_SEC, MAX_CLIP_SEC, MIN_FLASH_CLIP_SEC
from src.services.recap_cut_fit import _snap_src_into_beat_window
from src.services.recap_cut_pad import _source_hits_op_ed
from src.services.recap_cuts import _clip_beat_id
from src.services.recap_match import _overlap_sec, _time_span

def _splice_recap_beat_cuts(
    existing: Sequence[Mapping[str, Any]],
    new_cuts: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> list[dict[str, Any]]:
    """Replace every clip for ``beat_id`` with ``new_cuts``, keeping other beats intact.

    Removes *all* clips of the target beat (even if non-contiguous), then inserts the
    new block at the first removed position so neighbors stay in narrative order.
    """
    target = int(beat_id)
    kept: list[dict[str, Any]] = []
    insert_at: int | None = None
    for clip in existing or []:
        row = dict(clip)
        if _clip_beat_id(row) == target:
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(row)
    mid: list[dict[str, Any]] = []
    for clip in new_cuts or []:
        row = dict(clip)
        row["beat_id"] = target
        mid.append(row)
    if not mid:
        return kept
    if insert_at is None:
        # No prior clips for this beat — place by ascending beat id among neighbors.
        insert_at = len(kept)
        for index, clip in enumerate(kept):
            bid = _clip_beat_id(clip)
            if bid is not None and bid > target:
                insert_at = index
                break
    return kept[:insert_at] + mid + kept[insert_at:]

def _neighbor_beats_for_rematch(
    allocated: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
    ordered = [dict(item) for item in allocated or []]
    target_index = None
    for index, item in enumerate(ordered):
        try:
            if int(item.get("id")) == int(beat_id):
                target_index = index
                break
        except (TypeError, ValueError):
            continue
    if target_index is None:
        raise RuntimeError(f"规划里没有拍 #{beat_id}。")
    prev_beat = ordered[target_index - 1] if target_index > 0 else None
    next_beat = ordered[target_index + 1] if target_index + 1 < len(ordered) else None
    return prev_beat, ordered[target_index], next_beat

def _locked_vo_context(
    clips: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Return (prev VO lines, next VO lines, old cuts for this beat)."""
    target = int(beat_id)
    prev: list[str] = []
    nxt: list[str] = []
    old: list[dict[str, Any]] = []
    phase = "before"
    for clip in clips or []:
        row = dict(clip)
        bid = _clip_beat_id(row)
        vo = str(row.get("vo") or "").strip()
        if bid == target:
            phase = "after"
            old.append(row)
            continue
        if phase == "before":
            if vo:
                prev.append(vo)
        else:
            if vo:
                nxt.append(vo)
    return prev[-3:], nxt[:3], old

def _filter_rematch_cuts_to_beat(
    cuts: Sequence[Mapping[str, Any]],
    beat: Mapping[str, Any],
    *,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep only target-beat clips that still touch the beat time window."""
    target = int(beat.get("id"))
    span = _time_span(beat.get("t"))
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        row = dict(clip)
        bid = _clip_beat_id(row)
        if bid not in (None, 0, target):
            continue
        row["beat_id"] = target
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            continue
        if src_out <= src_in + 0.4:
            continue
        pad = float(BEAT_SRC_PAD_SEC)
        if span and _overlap_sec((src_in, src_out), (span[0] - pad, span[1] + pad)) <= 0.05:
            # Far outside beat window — try snap, else drop.
            placed = None
            if pack is not None:
                placed = _snap_src_into_beat_window(
                    pack,
                    span,
                    want_sec=max(MIN_FLASH_CLIP_SEC, min(src_out - src_in, MAX_CLIP_SEC)),
                    pad_sec=pad,
                )
            if placed is None:
                continue
            row["src_in"], row["src_out"] = placed
            row["duration"] = round(placed[1] - placed[0], 3)
            src_in, src_out = placed
        if pack is not None and _source_hits_op_ed(pack, src_in, src_out):
            continue
        out.append(row)
    return out
