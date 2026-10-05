"""Cut coalesce / dedupe / source-span helpers for the recap job.

Snap / clamp / pad / duration trim stay in ``recap_service``. This module owns
the deterministic merge math. ``recap_service`` re-exports the public names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    MIN_FLASH_CLIP_SEC,
    SOURCE_ADJACENT_REUSE_RATIO,
    SOURCE_MERGE_GAP_SEC,
    SOURCE_OVERLAP_MERGE_SEC,
    SOURCE_REUSE_RATIO,
)
from src.services.recap_match import is_bridge_clip, overlap_sec
from src.services.recap_vo_budget import (
    _clip_len,
    _join_vo,
    looks_like_insert_cut,
    _preferred_clip_vo,
    _vo_covers,
)

def recap_cuts_duration(cuts: list[Mapping[str, Any]]) -> float:
    return round(sum(_clip_len(clip) for clip in cuts), 3)

def _clip_beat_id(clip: Mapping[str, Any] | None) -> int | None:
    if not isinstance(clip, Mapping):
        return None
    try:
        return int(clip.get("beat_id"))
    except (TypeError, ValueError):
        return None

def _clip_src_span(clip: Mapping[str, Any]) -> tuple[float, float]:
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    if src_out <= src_in:
        duration = float(clip.get("duration") or 0.0)
        if duration > 0:
            src_out = src_in + duration
    return src_in, src_out

def _source_overlap_sec(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    return overlap_sec(_clip_src_span(left), _clip_src_span(right))

def _source_gap_sec(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    a_in, a_out = _clip_src_span(left)
    b_in, b_out = _clip_src_span(right)
    if a_out < b_in:
        return b_in - a_out
    if b_out < a_in:
        return a_in - b_out
    return 0.0

def _source_adjacent_clips(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    *,
    gap_sec: float = SOURCE_MERGE_GAP_SEC,
) -> bool:
    if _source_overlap_sec(left, right) > 0.04:
        return True
    return _source_gap_sec(left, right) <= max(0.0, float(gap_sec))

def _is_flash_cut(clip: Mapping[str, Any]) -> bool:
    if looks_like_insert_cut(clip):
        return False
    return _clip_len(clip) < MIN_FLASH_CLIP_SEC or (
        is_bridge_clip(clip) and _clip_len(clip) <= MIN_FLASH_CLIP_SEC + 0.05
    )

def _merge_cut_pair(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    a_in, a_out = _clip_src_span(left)
    b_in, b_out = _clip_src_span(right)
    src_in = min(a_in, b_in)
    src_out = max(a_out, b_out)
    left_vo = _preferred_clip_vo(left)
    right_vo = _preferred_clip_vo(right)
    vo = _join_vo(left_vo, right_vo)
    head: Mapping[str, Any] = left
    if is_bridge_clip(left) and not is_bridge_clip(right):
        head = right
    elif not left_vo and right_vo:
        head = right
    out = dict(head)
    out["src_in"] = round(src_in, 3)
    out["src_out"] = round(src_out, 3)
    out["duration"] = round(src_out - src_in, 3)
    out["vo"] = vo
    draft = _join_vo(
        str(left.get("vo_draft") or ""),
        str(right.get("vo_draft") or ""),
        vo,
    )
    if draft:
        out["vo_draft"] = draft
    if vo and is_bridge_clip(out):
        other = right if head is left else left
        out["name"] = str(other.get("name") or out.get("name") or "")
        out["reason"] = str(other.get("reason") or "")
    if not out.get("beat_id") and (left.get("beat_id") or right.get("beat_id")):
        out["beat_id"] = left.get("beat_id") or right.get("beat_id")
    out.pop("tl_in", None)
    out.pop("tl_out", None)
    out.pop("vo_tl_in", None)
    out.pop("vo_tl_out", None)
    return out

def _attach_cut_vo(target: dict[str, Any], victim: Mapping[str, Any]) -> None:
    vo = _join_vo(_preferred_clip_vo(target), _preferred_clip_vo(victim))
    target["vo"] = vo
    draft = _join_vo(
        str(target.get("vo_draft") or ""),
        str(victim.get("vo_draft") or ""),
        vo,
    )
    if draft:
        target["vo_draft"] = draft

def _cut_to_next_shot(prev: dict[str, Any], clip: Mapping[str, Any]) -> dict[str, Any] | None:
    """Resolve overlapping neighbors. Same-beat masters: keep both enter and land when possible."""
    p_in, p_out = _clip_src_span(prev)
    c_in, c_out = _clip_src_span(clip)
    if c_in >= p_out - 0.04:
        return dict(clip)
    insert = looks_like_insert_cut(clip)
    if insert:
        if c_in >= p_in + 0.8:
            prev["src_out"] = round(min(c_in, p_out), 3)
            prev["duration"] = round(float(prev["src_out"]) - p_in, 3)
            return dict(clip)
        return dict(clip)
    if c_in <= p_in + 0.25 and c_out <= p_out + 0.25:
        return None
    same_beat = (
        _clip_beat_id(prev) is not None
        and _clip_beat_id(prev) == _clip_beat_id(clip)
        and not looks_like_insert_cut(prev)
    )
    if c_in >= p_in + 0.35 and (c_in - p_in) >= 1.6:
        prev["src_out"] = round(c_in, 3)
        prev["duration"] = round(c_in - p_in, 3)
        return dict(clip)
    remain = c_out - p_out
    if remain >= MIN_FLASH_CLIP_SEC:
        out = dict(clip)
        out["src_in"] = round(p_out, 3)
        out["src_out"] = round(c_out, 3)
        out["duration"] = round(remain, 3)
        return out
    # Same beat: do not drop the later land/enter shot just because overlap is messy.
    if same_beat and (c_in - p_in) >= MIN_FLASH_CLIP_SEC:
        prev["src_out"] = round(c_in, 3)
        prev["duration"] = round(c_in - p_in, 3)
        return dict(clip)
    if same_beat and (p_out - p_in) >= MIN_FLASH_CLIP_SEC + 0.8:
        keep_head = max(MIN_FLASH_CLIP_SEC, (p_out - p_in) - max(remain, MIN_FLASH_CLIP_SEC))
        split = p_in + keep_head
        if c_out - split >= MIN_FLASH_CLIP_SEC:
            prev["src_out"] = round(split, 3)
            prev["duration"] = round(split - p_in, 3)
            out = dict(clip)
            out["src_in"] = round(split, 3)
            out["src_out"] = round(c_out, 3)
            out["duration"] = round(c_out - split, 3)
            return out
    return None

def _should_merge_source_clips(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Only glue flash leftovers or the same line replayed over overlapping source."""
    overlap = _source_overlap_sec(left, right)
    adjacent = overlap >= SOURCE_OVERLAP_MERGE_SEC or _source_adjacent_clips(left, right)
    if not adjacent:
        return False
    if looks_like_insert_cut(left) or looks_like_insert_cut(right):
        return False
    if _is_flash_cut(left) or _is_flash_cut(right):
        return True
    left_vo = _preferred_clip_vo(left)
    right_vo = _preferred_clip_vo(right)
    if overlap >= SOURCE_OVERLAP_MERGE_SEC and left_vo and right_vo:
        return _vo_covers(left_vo, right_vo) or _vo_covers(right_vo, left_vo)
    return False

def collect_used_source_spans(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Marked used source windows for match prompts / reuse checks."""
    rows: list[dict[str, Any]] = []
    for clip in cuts or []:
        try:
            src_in = float(clip.get("src_in") or 0.0)
            src_out = float(clip.get("src_out") or src_in)
        except (TypeError, ValueError):
            continue
        if src_out - src_in < 0.4:
            continue
        row: dict[str, Any] = {
            "src_in": round(src_in, 2),
            "src_out": round(src_out, 2),
        }
        beat_id = _clip_beat_id(clip)
        if beat_id is not None:
            row["beat_id"] = beat_id
        rows.append(row)
    rows.sort(key=lambda item: (float(item["src_in"]), float(item["src_out"])))
    return rows

def _source_reuse_ratio(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    overlap = _source_overlap_sec(left, right)
    if overlap <= 0.05:
        return 0.0
    left_len = max(0.01, _clip_len(left))
    right_len = max(0.01, _clip_len(right))
    return overlap / min(left_len, right_len)

def drop_reused_source_cuts(
    cuts: Sequence[Mapping[str, Any]],
    *,
    reuse_ratio: float = SOURCE_REUSE_RATIO,
    adjacent_ratio: float = SOURCE_ADJACENT_REUSE_RATIO,
) -> list[dict[str, Any]]:
    """Hard mark: once a source window is taken, later near-copies are dropped.

    Consecutive (src-ordered) overlaps use a stricter bar — the “几个连着重复” case.
    Never strip a beat of its only remaining cut.
    """
    items = [dict(clip) for clip in cuts or []]
    if len(items) < 2:
        return items
    items.sort(
        key=lambda clip: (
            float(clip.get("src_in") or 0.0),
            int(clip.get("beat_id") or 0),
            0 if not looks_like_insert_cut(clip) else 1,
        )
    )
    kept: list[dict[str, Any]] = []
    kept_by_beat: dict[int, int] = {}

    def _beat_count(beat_id: int | None) -> int:
        if beat_id is None:
            return 0
        return int(kept_by_beat.get(beat_id) or 0)

    for clip in items:
        beat_id = _clip_beat_id(clip)
        conflict_at: int | None = None
        conflict_ratio = 0.0
        for index, prev in enumerate(kept):
            ratio = _source_reuse_ratio(prev, clip)
            if ratio <= 0.0:
                continue
            is_adj = index == len(kept) - 1
            prev_beat = _clip_beat_id(prev)
            same_beat = (
                beat_id is not None
                and prev_beat is not None
                and beat_id == prev_beat
            )
            # Same beat: only kill near-copies; partial overlap is trimmed later by coalesce.
            if same_beat:
                need = max(0.55, float(reuse_ratio))
            else:
                need = float(adjacent_ratio) if is_adj else float(reuse_ratio)
            if ratio >= need:
                conflict_at = index
                conflict_ratio = ratio
                break
        if conflict_at is None:
            kept.append(clip)
            if beat_id is not None:
                kept_by_beat[beat_id] = _beat_count(beat_id) + 1
            continue
        prev = kept[conflict_at]
        same_beat = (
            beat_id is not None
            and _clip_beat_id(prev) is not None
            and beat_id == _clip_beat_id(prev)
        )
        # Same-beat master + short insert nesting is intentional reaction CU — keep both.
        if same_beat and looks_like_insert_cut(clip) != looks_like_insert_cut(prev):
            short = min(_clip_len(prev), _clip_len(clip))
            long = max(_clip_len(prev), _clip_len(clip))
            if short <= long * 0.75:
                kept.append(clip)
                if beat_id is not None:
                    kept_by_beat[beat_id] = _beat_count(beat_id) + 1
                continue
        # Near-identical cross-beat replay: always drop later.
        if not same_beat and conflict_ratio >= max(0.55, float(reuse_ratio)):
            continue
        if not same_beat and beat_id is not None and _beat_count(beat_id) <= 0 and conflict_ratio < 0.55:
            prev_beat = _clip_beat_id(prev)
            if prev_beat is not None and _beat_count(prev_beat) >= 2:
                kept.pop(conflict_at)
                kept_by_beat[prev_beat] = _beat_count(prev_beat) - 1
                kept.append(clip)
                kept_by_beat[beat_id] = _beat_count(beat_id) + 1
            else:
                # Still a heavy cross-beat copy — prefer earlier shot.
                continue
            continue
        if same_beat and conflict_ratio >= max(0.55, float(reuse_ratio)):
            continue
        if not same_beat:
            continue
        kept.append(clip)
        if beat_id is not None:
            kept_by_beat[beat_id] = _beat_count(beat_id) + 1
    kept.sort(
        key=lambda clip: (
            float(clip.get("src_in") or 0.0),
            int(clip.get("beat_id") or 0),
        )
    )
    return kept

def dedupe_overlapping_recap_cuts(
    cuts: Sequence[Mapping[str, Any]],
    *,
    overlap_ratio: float = 0.45,
    cross_beat_overlap_ratio: float = 0.55,
) -> list[dict[str, Any]]:
    """Drop near-duplicate source windows. Same beat and cross-beat replays both count."""
    items = [dict(clip) for clip in cuts or []]
    if len(items) < 2:
        return items
    drop: set[int] = set()
    for i in range(len(items)):
        if i in drop:
            continue
        for j in range(i + 1, len(items)):
            if j in drop:
                continue
            left = items[i]
            right = items[j]
            left_beat = _clip_beat_id(left)
            right_beat = _clip_beat_id(right)
            overlap = _source_overlap_sec(left, right)
            if overlap <= 0.08:
                continue
            left_len = max(0.01, _clip_len(left))
            right_len = max(0.01, _clip_len(right))
            ratio = overlap / min(left_len, right_len)
            same_beat = (
                left_beat is not None
                and right_beat is not None
                and left_beat == right_beat
            )
            need = float(overlap_ratio) if same_beat else float(cross_beat_overlap_ratio)
            if ratio < need:
                continue
            left_insert = looks_like_insert_cut(left)
            right_insert = looks_like_insert_cut(right)
            # Keep a short insert over a long master when ranges mostly nest (same beat only).
            if same_beat and left_insert != right_insert:
                if left_insert and left_len <= right_len * 0.75:
                    continue
                if right_insert and right_len <= left_len * 0.75:
                    continue
            # Prefer keeping earlier source / voiced master; drop the replay.
            left_vo = bool(str(left.get("vo") or left.get("vo_draft") or "").strip())
            right_vo = bool(str(right.get("vo") or right.get("vo_draft") or "").strip())
            if left_vo and not right_vo:
                drop.add(j)
                continue
            if right_vo and not left_vo:
                drop.add(i)
                break
            if float(right.get("src_in") or 0.0) + 0.05 >= float(left.get("src_in") or 0.0) and right_len <= left_len * 1.05:
                drop.add(j)
            elif left_len < right_len * 0.92:
                drop.add(i)
                break
            else:
                drop.add(j)
    return [clip for index, clip in enumerate(items) if index not in drop]

def coalesce_recap_cuts(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Drop replayed source, keep real cuts, absorb flash-length leftovers."""
    items = dedupe_overlapping_recap_cuts(
        [
            dict(clip)
            for clip in cuts or []
            if _clip_len(clip) > 0.04 or str(clip.get("vo") or clip.get("vo_draft") or "").strip()
        ]
    )
    items = drop_reused_source_cuts(items)
    items.sort(
        key=lambda clip: (
            float(clip.get("src_in") or 0.0),
            int(clip.get("beat_id") or 0),
        )
    )
    merged: list[dict[str, Any]] = []
    for clip in items:
        if merged and _should_merge_source_clips(merged[-1], clip):
            merged[-1] = _merge_cut_pair(merged[-1], clip)
            continue
        if merged:
            nxt = _cut_to_next_shot(merged[-1], clip)
            if nxt is None:
                _attach_cut_vo(merged[-1], clip)
                continue
            clip = nxt
        merged.append(dict(clip))
    index = 0
    while index < len(merged):
        clip = merged[index]
        if not _is_flash_cut(clip) or len(merged) == 1:
            index += 1
            continue
        prev = merged[index - 1] if index > 0 else None
        nxt = merged[index + 1] if index + 1 < len(merged) else None
        if prev is None and nxt is None:
            break
        into_next = prev is None
        if prev is not None and nxt is not None:
            prev_adj = _source_adjacent_clips(prev, clip)
            nxt_adj = _source_adjacent_clips(clip, nxt)
            into_next = nxt_adj and not prev_adj
        if into_next:
            target = nxt
            if target is None:
                index += 1
                continue
            if _source_adjacent_clips(clip, target):
                merged[index] = _merge_cut_pair(clip, target)
            else:
                _attach_cut_vo(target, clip)
                del merged[index]
                continue
            del merged[index + 1]
            continue
        if prev is None:
            index += 1
            continue
        if _source_adjacent_clips(prev, clip):
            merged[index - 1] = _merge_cut_pair(prev, clip)
        else:
            _attach_cut_vo(prev, clip)
        del merged[index]
        continue
    return merged

def ensure_main_cut_per_beat(cuts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: each-beat main shot is a Match prompt rule, not a code patch."""
    return [dict(clip) for clip in cuts or []]
