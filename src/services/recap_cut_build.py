"""Normalize Match cuts, refine the pipeline, and fit beat picture to VO budget.

``recap_service`` re-exports these names. JSON parse salvage stays in the runner.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    MAX_CLIP_SEC,
    MAX_TTS_CLIP_SEC,
    MIN_CLIP_SEC,
    MIN_RECAP_SEC,
    TARGET_RECAP_SEC,
)
from src.services.recap_cut_fit import clamp_cuts_to_beat_window, snap_cuts_to_capped_chunks
from src.services.recap_cut_pad import (
    _chunk_window,
    _expand_clip,
    clamp_insert_cuts_to_beat,
    pad_cuts_for_tts,
)
from src.services.recap_cuts import coalesce_recap_cuts, drop_reused_source_cuts
from src.services.recap_match import _time_span, recap_story_window
from src.services.recap_vo_budget import (
    _clip_len,
    _clip_role,
    _looks_like_insert_cut,
    _trim_group_to_budget,
    vo_needed_sec,
)

def _chunk_is_skipped(pack: Mapping[str, Any], chunk_index: int | None) -> bool:
    if chunk_index is None:
        return False
    for item in pack.get("chunks") or []:
        if int(item.get("i", -1)) == int(chunk_index):
            return bool(str(item.get("skip") or "").strip())
    return False

def normalize_cut_list(raw: Mapping[str, Any], pack: Mapping[str, Any]) -> list[dict[str, Any]]:
    duration = float(pack.get("duration_sec") or 0.0)
    _op_start, story_end = recap_story_window(duration)
    clips_in = raw.get("clips") if isinstance(raw, Mapping) else None
    if not isinstance(clips_in, list) or not clips_in:
        raise RuntimeError("LLM 没有返回 clips。")
    out: list[dict[str, Any]] = []
    for index, item in enumerate(clips_in, 1):
        if not isinstance(item, Mapping):
            continue
        vo = str(item.get("vo") or "").strip()
        try:
            src_in = float(item.get("src_in"))
        except (TypeError, ValueError):
            continue
        src_out = item.get("src_out")
        duration_in = item.get("duration")
        try:
            if src_out is None and duration_in is not None:
                src_out = src_in + float(duration_in)
            else:
                src_out = float(src_out)
        except (TypeError, ValueError):
            continue
        chunk_index = item.get("chunk_index")
        try:
            chunk_index_i = int(chunk_index)
        except (TypeError, ValueError):
            chunk_index_i = None
        window = _chunk_window(pack, chunk_index_i) if chunk_index_i is not None else None
        if window:
            src_in = max(window[0], src_in)
            src_out = min(window[1], src_out)
            # Allow a little spill into the next chunk for merged beats.
            src_out = max(src_out, src_in + 0.4)
        if duration > 0:
            src_in = min(max(0.0, src_in), duration)
            src_out = min(max(src_in + 0.4, src_out), duration)
        span = src_out - src_in
        vo_need = vo_needed_sec(vo) if vo else 0.0
        max_keep = max(MAX_CLIP_SEC, min(MAX_TTS_CLIP_SEC, vo_need)) if vo else MAX_CLIP_SEC
        insert = _looks_like_insert_cut(item)
        floor = MIN_CLIP_SEC if vo else min(MIN_CLIP_SEC, max(2.4, span))
        if insert:
            floor = min(floor, max(2.0, span if span >= 2.0 else 2.0))
        if span > max_keep + 0.15:
            # Keep the establishing head (enter/setup); do not chop into a later stub.
            src_out = round(src_in + max_keep, 2)
        elif span < floor and duration:
            extra = floor - span
            src_out = min(duration, src_out + extra)
            if window:
                src_out = min(window[1], src_out)
            if src_out - src_in < floor:
                src_in = max(0.0 if not window else window[0], src_out - floor)
        if src_out - src_in < 0.8:
            continue
        if _chunk_is_skipped(pack, chunk_index_i):
            continue
        if duration >= 360 and src_in >= story_end:
            continue
        name = str(item.get("name") or "").strip() or f"{index:02d}"
        reason = str(item.get("reason") or "").strip()[:80]
        beat_raw = item.get("beat_id", item.get("beat"))
        try:
            beat_id = int(beat_raw)
        except (TypeError, ValueError):
            beat_id = None
        role = _clip_role(item)
        if not role and insert:
            role = "insert"
        row = {
            "name": name[:40],
            "beat_id": beat_id,
            "chunk_index": chunk_index_i,
            "src_in": round(src_in, 3),
            "src_out": round(src_out, 3),
            "duration": round(src_out - src_in, 3),
            "vo": vo,
            "reason": reason,
        }
        if role:
            row["role"] = role
        out.append(row)
    if not out:
        raise RuntimeError("LLM 剪辑表没有可用镜头。")
    return out

def stash_match_vo_as_draft(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep accidental match VO as caption seed; official narration is written later."""
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        item = dict(clip)
        seed = str(item.get("vo_draft") or item.get("vo") or "").strip()
        item["vo_draft"] = seed
        item["vo"] = ""
        out.append(item)
    return out

def refine_recap_cuts(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Keep cuts and grow picture if needed. Do not edit the script."""
    out = coalesce_recap_cuts(list(cuts or []))
    out = clamp_cuts_to_beat_window(out, pack, beats)
    out = snap_cuts_to_capped_chunks(out, pack, beats)
    out = clamp_insert_cuts_to_beat(out, pack, beats)
    out = pad_cuts_for_tts(out, pack, beats)
    out = coalesce_recap_cuts(out)
    return drop_reused_source_cuts(out)

def apply_recap_duration(
    cuts: list[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
    *,
    target_sec: float = TARGET_RECAP_SEC,
    min_sec: float = MIN_RECAP_SEC,
) -> list[dict[str, Any]]:
    """Fit picture to VO speak time (grow) then trim budget overshoots. Never pad empty beats."""
    _ = (target_sec, min_sec)
    out = [dict(clip) for clip in cuts]
    if not out:
        return out
    by_id = {}
    for beat in beats or []:
        try:
            by_id[int(beat.get("id"))] = dict(beat)
        except (TypeError, ValueError):
            continue
    groups: dict[Any, list[dict[str, Any]]] = {}
    for clip in out:
        groups.setdefault(clip.get("beat_id"), []).append(clip)
    for beat_id, group in groups.items():
        beat = None
        if beat_id is not None:
            try:
                beat = by_id.get(int(beat_id))
            except (TypeError, ValueError):
                beat = None
        budget = float((beat or {}).get("budget_sec") or 0.0)
        if budget <= 0:
            continue
        vo_text = str((beat or {}).get("vo") or "").strip()
        if not vo_text:
            for clip in group:
                vo_text = str(clip.get("vo") or clip.get("vo_draft") or "").strip()
                if vo_text:
                    break
        need = vo_needed_sec(vo_text) if vo_text else 0.0
        have = sum(_clip_len(clip) for clip in group)
        beat_span = _time_span((beat or {}).get("t")) if beat else None
        # Grow toward speak time (capped by budget), not toward empty quota.
        want = min(budget, need) if need > 0.05 else 0.0
        if want > have + 0.25:
            room = want - have
            masters = [clip for clip in group if not _looks_like_insert_cut(clip)]
            targets = masters or list(group)
            for clip in targets:
                if room <= 0.05:
                    break
                grown = _expand_clip(
                    clip,
                    pack,
                    room,
                    beat_span,
                    forward_only=False,
                    max_len=MAX_TTS_CLIP_SEC,
                )
                room -= grown
            have = sum(_clip_len(clip) for clip in group)
        if have > budget + 0.25:
            _trim_group_to_budget(out, group, budget)
    return out
