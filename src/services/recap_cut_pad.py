"""Grow / bridge cuts for TTS and pull drifting inserts back to masters.

Snap / coalesce stay in sibling modules. ``recap_service`` re-exports these names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    INSERT_MAX_GAP_FROM_MASTER_SEC,
    MAX_CLIP_SEC,
    MAX_TTS_CLIP_SEC,
    MIN_BRIDGE_SEC,
    MIN_INSERT_CLIP_SEC,
)
from src.services.recap_match import (
    _beats_by_id,
    overlap_sec,
    time_span,
    keep_chunk_for_recap,
    looks_like_op_ed_text,
    recap_story_window,
)
from src.services.recap_vo_budget import (
    _clip_len,
    looks_like_insert_cut,
    _preferred_clip_vo,
    _vo_cover_span,
    vo_needed_sec,
)

def _chunk_window(pack: Mapping[str, Any], chunk_index: int) -> tuple[float, float] | None:
    for item in pack.get("chunks") or []:
        if int(item.get("i", -1)) == int(chunk_index):
            times = item.get("t") or [0, 0]
            return float(times[0]), float(times[1])
    return None

def _source_hits_op_ed(pack: Mapping[str, Any], start: float, end: float) -> bool:
    if end <= start:
        return False
    for chunk in pack.get("chunks") or []:
        if not str(chunk.get("skip") or "").strip() and not looks_like_op_ed_text(
            chunk.get("cap"), " ".join(str(tag) for tag in (chunk.get("tags") or []))
        ):
            continue
        span = time_span(chunk.get("t"))
        if span and overlap_sec((start, end), span) > 0.25:
            return True
    return False

def _clamp_window_away_from_op_ed(
    pack: Mapping[str, Any],
    lo: float,
    hi: float,
    *,
    src_in: float,
    src_out: float,
) -> tuple[float, float]:
    for chunk in pack.get("chunks") or []:
        skip = str(chunk.get("skip") or "").strip() or looks_like_op_ed_text(
            chunk.get("cap"), " ".join(str(tag) for tag in (chunk.get("tags") or []))
        )
        if not skip:
            continue
        span = time_span(chunk.get("t"))
        if not span:
            continue
        if span[1] <= src_in + 0.35:
            lo = max(lo, span[1])
        if span[0] >= src_out - 0.35:
            hi = min(hi, span[0])
    return lo, hi

def _neighbor_source_window(
    pack: Mapping[str, Any],
    chunk_index: int | None,
    beat_span: tuple[float, float] | None = None,
    *,
    strict: bool = False,
) -> tuple[float, float] | None:
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    chunks = [
        item
        for item in (pack.get("chunks") or [])
        if keep_chunk_for_recap(item, duration) and time_span(item.get("t"))
    ]
    chunks.sort(key=lambda item: ((time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("i") or 0)))
    if not chunks:
        window = _chunk_window(pack, int(chunk_index or 0)) if chunk_index is not None else None
        return window
    index = None
    if chunk_index is not None:
        for pos, item in enumerate(chunks):
            if int(item.get("i", -1)) == int(chunk_index):
                index = pos
                break
    if index is None:
        window = _chunk_window(pack, int(chunk_index or 0)) if chunk_index is not None else None
        return window
    lo, hi = time_span(chunks[index].get("t")) or (0.0, 0.0)
    slack = 0.0 if strict else 10.0
    cursor = index - 1
    while cursor >= 0:
        prev = time_span(chunks[cursor].get("t"))
        if not prev or lo - prev[1] > 0.85:
            break
        if beat_span and prev[0] < beat_span[0] - slack:
            break
        lo = prev[0]
        cursor -= 1
    cursor = index + 1
    while cursor < len(chunks):
        nxt = time_span(chunks[cursor].get("t"))
        if not nxt or nxt[0] - hi > 0.85:
            break
        if beat_span and nxt[1] > beat_span[1] + slack:
            break
        hi = nxt[1]
        cursor += 1
    if beat_span:
        pad = 0.0 if strict else 2.0
        lo = max(lo, beat_span[0] - pad)
        hi = min(hi, beat_span[1] + pad)
    if duration >= 360:
        hi = min(hi, story_end)
    if duration > 0:
        lo = max(float(story_start or 0.0), lo)
        hi = min(duration, hi)
    if hi - lo < 0.8:
        return _chunk_window(pack, int(chunk_index))
    return (lo, hi)

def _expand_clip(
    clip: dict[str, Any],
    pack: Mapping[str, Any],
    extra: float,
    beat_span: tuple[float, float] | None = None,
    *,
    forward_only: bool = False,
    max_len: float | None = None,
) -> float:
    cap = float(MAX_CLIP_SEC if max_len is None else max_len)
    room = min(max(0.0, extra), cap - _clip_len(clip))
    if room <= 0.05:
        return 0.0
    window = _neighbor_source_window(
        pack,
        clip.get("chunk_index"),
        beat_span,
        strict=forward_only,
    )
    src_in = float(clip["src_in"])
    src_out = float(clip["src_out"])
    if not window:
        own = _chunk_window(pack, int(clip.get("chunk_index") or 0)) if clip.get("chunk_index") is not None else None
        window = own or (src_in, src_out + room)
    lo, hi = window
    lo, hi = _clamp_window_away_from_op_ed(pack, lo, hi, src_in=src_in, src_out=src_out)
    take_out = min(max(0.0, hi - src_out), room)
    if take_out > 0 and _source_hits_op_ed(pack, src_out, src_out + take_out):
        take_out = 0.0
    src_out += take_out
    room -= take_out
    take_in = 0.0
    if not forward_only and room > 0.05:
        take_in = min(max(0.0, src_in - lo), room)
        if take_in > 0 and _source_hits_op_ed(pack, src_in - take_in, src_in):
            take_in = 0.0
        src_in -= take_in
    clip["src_in"] = round(src_in, 3)
    clip["src_out"] = round(src_out, 3)
    clip["duration"] = round(src_out - src_in, 3)
    return take_out + take_in

def _make_tts_bridge_clip(
    clip: Mapping[str, Any],
    pack: Mapping[str, Any],
    need: float,
    nxt: Mapping[str, Any] | None,
    beat_span: tuple[float, float] | None,
) -> dict[str, Any] | None:
    window = _neighbor_source_window(pack, clip.get("chunk_index"), beat_span, strict=True)
    if not window:
        return None
    lo, hi = window
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    lo, hi = _clamp_window_away_from_op_ed(pack, lo, hi, src_in=src_in, src_out=src_out)
    take = min(max(MIN_BRIDGE_SEC, float(need or 0.0)), MAX_TTS_CLIP_SEC)
    avail_after = max(0.0, hi - src_out)
    if nxt is not None:
        nxt_in = float(nxt.get("src_in") or 0.0)
        if nxt_in > src_out + 0.2:
            avail_after = min(avail_after, nxt_in - src_out)
    if avail_after < MIN_BRIDGE_SEC:
        return None
    dur = min(take, avail_after)
    start, end = src_out, src_out + dur
    if _source_hits_op_ed(pack, start, end):
        return None
    return {
        "name": "过渡",
        "beat_id": clip.get("beat_id"),
        "chunk_index": clip.get("chunk_index"),
        "src_in": round(start, 3),
        "src_out": round(end, 3),
        "vo": "",
        "reason": "过渡",
    }

def pad_cuts_for_tts(
    cuts: list[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Grow shots or insert bridges when VO speaking time exceeds picture."""
    out = [dict(clip) for clip in cuts]
    by_id: dict[Any, Mapping[str, Any]] = {}
    for beat in beats or []:
        try:
            by_id[int(beat.get("id"))] = beat
        except (TypeError, ValueError):
            continue
    index = 0
    while index < len(out):
        clip = out[index]
        vo = str(clip.get("vo") or "").strip()
        if vo:
            clip["vo"] = _preferred_clip_vo(clip)
            vo = str(clip.get("vo") or "").strip()
        need = vo_needed_sec(vo)
        have, last = _vo_cover_span(out, index)
        if not vo or need <= have + 0.08:
            index += 1
            continue
        beat = None
        try:
            if clip.get("beat_id") is not None:
                beat = by_id.get(int(clip["beat_id"]))
        except (TypeError, ValueError):
            beat = None
        beat_span = time_span((beat or {}).get("t"))
        extra = need - have
        _expand_clip(
            out[last],
            pack,
            extra,
            beat_span,
            forward_only=True,
            max_len=MAX_TTS_CLIP_SEC,
        )
        have, last = _vo_cover_span(out, index)
        still = need - have
        while still > 0.5:
            nxt = out[last + 1] if last + 1 < len(out) else None
            bridge = _make_tts_bridge_clip(out[last], pack, still, nxt, beat_span)
            if not bridge:
                break
            out.insert(last + 1, bridge)
            last += 1
            still = need - _vo_cover_span(out, index)[0]
        index += 1
    return out

def clamp_insert_cuts_to_beat(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    max_gap_sec: float = INSERT_MAX_GAP_FROM_MASTER_SEC,
) -> list[dict[str, Any]]:
    """Pull drifting insert cuts back next to the same-beat master, or drop them.

    Inserts more than ``max_gap_sec`` after the master, or completely outside the
    beat ``t`` window with no overlap, are snapped into the post-master window
    when possible. Otherwise they are discarded so late close-ups do not land
    on earlier beats.
    """
    items = [dict(clip) for clip in cuts or []]
    if not items:
        return items
    by_id = _beats_by_id(beats)
    groups: dict[Any, list[int]] = {}
    for index, clip in enumerate(items):
        groups.setdefault(clip.get("beat_id"), []).append(index)

    drop: set[int] = set()
    for beat_id, indices in groups.items():
        masters = [items[i] for i in indices if not looks_like_insert_cut(items[i])]
        inserts = [i for i in indices if looks_like_insert_cut(items[i])]
        if not inserts:
            continue
        if not masters:
            # No A-roll to anchor against — keep inserts as-is.
            continue
        master = max(masters, key=lambda clip: float(clip.get("src_out") or 0.0))
        master_end = float(master.get("src_out") or 0.0)
        beat = None
        if beat_id is not None:
            try:
                beat = by_id.get(int(beat_id))
            except (TypeError, ValueError):
                beat = None
        beat_span = time_span((beat or {}).get("t"))
        for index in inserts:
            clip = items[index]
            try:
                src_in = float(clip.get("src_in") or 0.0)
                src_out = float(clip.get("src_out") or 0.0)
            except (TypeError, ValueError):
                drop.add(index)
                continue
            span = max(0.0, src_out - src_in)
            far_after = src_in > master_end + float(max_gap_sec)
            outside_beat = False
            if beat_span:
                pad = float(max_gap_sec)
                expanded = (beat_span[0] - pad, beat_span[1] + pad)
                outside_beat = overlap_sec((src_in, src_out), expanded) <= 0.05
            if not far_after and not outside_beat:
                continue
            placed = _place_insert_after_master(
                clip,
                pack,
                master=master,
                beat_span=beat_span,
                want_sec=max(MIN_INSERT_CLIP_SEC, min(span or MIN_INSERT_CLIP_SEC, MAX_CLIP_SEC)),
            )
            if placed is None:
                drop.add(index)
            else:
                items[index] = placed
    return [clip for index, clip in enumerate(items) if index not in drop]

def _place_insert_after_master(
    clip: Mapping[str, Any],
    pack: Mapping[str, Any],
    *,
    master: Mapping[str, Any],
    beat_span: tuple[float, float] | None,
    want_sec: float,
) -> dict[str, Any] | None:
    """Snap an insert into the source window right after the master shot."""
    master_end = float(master.get("src_out") or 0.0)
    window = _neighbor_source_window(
        pack,
        master.get("chunk_index"),
        beat_span,
        strict=False,
    )
    if not window:
        window = _chunk_window(pack, int(master.get("chunk_index") or 0)) if master.get("chunk_index") is not None else None
    if not window:
        return None
    lo, hi = window
    lo, hi = _clamp_window_away_from_op_ed(
        pack,
        lo,
        hi,
        src_in=master_end,
        src_out=master_end,
    )
    start = max(lo, master_end)
    if beat_span:
        start = max(start, beat_span[0])
        hi = min(hi, beat_span[1] + 2.0)
    avail = hi - start
    if avail < MIN_INSERT_CLIP_SEC:
        return None
    dur = min(max(MIN_INSERT_CLIP_SEC, float(want_sec or MIN_INSERT_CLIP_SEC)), avail, MAX_CLIP_SEC)
    end = start + dur
    if _source_hits_op_ed(pack, start, end):
        return None
    out = dict(clip)
    out["src_in"] = round(start, 3)
    out["src_out"] = round(end, 3)
    out["duration"] = round(end - start, 3)
    out["role"] = "insert"
    if out.get("chunk_index") is None and master.get("chunk_index") is not None:
        out["chunk_index"] = master.get("chunk_index")
    out.pop("tl_in", None)
    out.pop("tl_out", None)
    out.pop("vo_tl_in", None)
    out.pop("vo_tl_out", None)
    return out
