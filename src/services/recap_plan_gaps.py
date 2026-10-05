"""Plan beat coverage, story gaps, and OP/ED drop helpers.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from src.services.recap_constants import ENDING_COVER_RATIO, MAX_GAP_FILL_WINDOWS, MAX_STORY_BEATS
from src.services.recap_match import (
    _overlap_sec,
    _time_span,
    looks_like_op_ed_text,
    recap_story_window,
)
from src.services.recap_plan_cover import _beat_lands_dialogue_outcome
from src.services.recap_spine import _DIALOGUE_OUTCOME_RE

_TEXTURE_BEAT_RE = re.compile(
    r"(设定|世界观|规则说明|能力说明|教室|空间|角色侧面|性格|态度|习惯|表情|换场|过渡|气氛|环境)"
)
_ACTIVITY_EVENT_KEY_RE = re.compile(r"[\s，,。！？!?…；;：:、\"'「」『』（）()【】\[\]《》<>·\-—_]+")


def opening_deadline_sec(duration_sec: float) -> float:
    duration = max(0.0, float(duration_sec or 0.0))
    if duration < 360:
        return max(20.0, duration * 0.25)
    return min(210.0, max(150.0, duration * 0.12))

def beat_evidence_sec(beat: Mapping[str, Any], chunks: list[Mapping[str, Any]] | None = None) -> float:
    span = _time_span(beat.get("t"))
    if not span:
        return 0.0
    total = 0.0
    for item in chunks or []:
        window = _time_span(item.get("t"))
        if window:
            total += _overlap_sec(span, window)
    if total <= 0.0:
        total = min(max(0.0, span[1] - span[0]), 12.0)
    return round(total, 2)

def beat_evidence_score(evidence_sec: float) -> float:
    capped = min(max(0.0, float(evidence_sec or 0.0)), 12.0)
    return min(1.0, capped / 8.0)

def beats_cover_ending(beats: list[Mapping[str, Any]], duration_sec: float) -> bool:
    duration = float(duration_sec or 0.0)
    if duration <= 1.0 or not beats:
        return True
    _op_start, story_end = recap_story_window(duration)
    last_story = 0.0
    for beat in beats:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        if span[0] >= story_end:
            continue
        last_story = max(last_story, min(span[1], story_end))
    return last_story >= story_end * ENDING_COVER_RATIO

def beats_cover_opening(beats: list[Mapping[str, Any]], duration_sec: float) -> bool:
    duration = float(duration_sec or 0.0)
    if duration <= 1.0 or not beats:
        return True
    first_start: float | None = None
    for beat in beats:
        if looks_like_op_ed_text(beat.get("event"), beat.get("needed_visual")):
            continue
        span = _time_span(beat.get("t"))
        if not span:
            continue
        first_start = span[0] if first_start is None else min(first_start, span[0])
    if first_start is None:
        return False
    return first_start <= opening_deadline_sec(duration)

def story_gap_min_sec(duration_sec: float) -> float:
    """Minimum uncovered window that still warrants a plot-gap pass."""
    duration = max(0.0, float(duration_sec or 0.0))
    # Lower threshold → catch more mid-story holes for a denser plan.
    return round(max(28.0, min(55.0, duration * 0.04)), 1)

def story_beat_gaps(
    beats: Sequence[Mapping[str, Any]],
    duration_sec: float,
    *,
    min_gap_sec: float | None = None,
) -> list[tuple[float, float]]:
    """Uncovered story windows long enough to hide a missing plot beat."""
    duration = float(duration_sec or 0.0)
    if duration <= 1.0:
        return []
    story_start, story_end = recap_story_window(duration)
    spans: list[tuple[float, float]] = []
    for beat in beats:
        if looks_like_op_ed_text(beat.get("event"), beat.get("needed_visual")):
            continue
        span = _time_span(beat.get("t"))
        if not span:
            continue
        lo = max(story_start, span[0])
        hi = min(story_end, span[1])
        if hi - lo > 0.4:
            spans.append((lo, hi))
    spans.sort()
    merged: list[tuple[float, float]] = []
    for lo, hi in spans:
        if merged and lo <= merged[-1][1] + 8.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    threshold = float(min_gap_sec) if min_gap_sec is not None else story_gap_min_sec(duration)
    gaps: list[tuple[float, float]] = []
    cursor = story_start
    for lo, hi in merged:
        if lo - cursor >= threshold:
            gaps.append((round(cursor, 2), round(lo, 2)))
        cursor = max(cursor, hi)
    if story_end - cursor >= threshold:
        gaps.append((round(cursor, 2), round(story_end, 2)))
    return gaps

def prioritize_story_gaps(
    gaps: Sequence[tuple[float, float]],
    *,
    limit: int = MAX_GAP_FILL_WINDOWS,
    pin: Sequence[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """Keep pinned activity-shift holes first, then the largest remaining holes."""
    items = [(float(lo), float(hi)) for lo, hi in gaps if float(hi) - float(lo) > 1.0]
    if not items:
        return []

    def _near(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) < 1.5 and abs(a[1] - b[1]) < 1.5

    pinned: list[tuple[float, float]] = []
    for cand in pin or ():
        target = (float(cand[0]), float(cand[1]))
        for item in items:
            if _near(item, target) and not any(_near(item, kept) for kept in pinned):
                pinned.append(item)
                break
    rest = [item for item in items if not any(_near(item, kept) for kept in pinned)]
    room = max(0, int(limit) - len(pinned))
    largest = sorted(rest, key=lambda item: item[1] - item[0], reverse=True)[:room]
    return sorted([*pinned, *largest], key=lambda item: item[0])

def _event_overlap_ratio(left: str, right: str) -> float:
    """How similar two beat events are; low score means different story beats."""
    a = _ACTIVITY_EVENT_KEY_RE.sub("", str(left or ""))
    b = _ACTIVITY_EVENT_KEY_RE.sub("", str(right or ""))
    if not a or not b:
        return 0.0
    return float(SequenceMatcher(None, a, b).ratio())

def activity_shift_gaps(
    beats: Sequence[Mapping[str, Any]],
    *,
    min_gap_sec: float,
) -> list[tuple[float, float]]:
    """Pin long holes between consecutive beats whose events barely overlap (domain-agnostic)."""
    ordered: list[tuple[float, float, str]] = []
    for beat in beats:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        ordered.append((span[0], span[1], str(beat.get("event") or "")))
    ordered.sort(key=lambda item: (item[0], item[1]))
    out: list[tuple[float, float]] = []
    threshold = max(20.0, float(min_gap_sec or 0.0) * 0.55)
    for prev, cur in zip(ordered, ordered[1:]):
        gap_lo, gap_hi = float(prev[1]), float(cur[0])
        if gap_hi - gap_lo < threshold:
            continue
        # Only pin when the outline itself jumped topics across a long hole.
        if _event_overlap_ratio(prev[2], cur[2]) <= 0.34:
            out.append((round(gap_lo, 2), round(gap_hi, 2)))
    return out

def dialogue_outcome_gaps(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]],
    *,
    cover_pad_sec: float = 4.0,
) -> list[tuple[float, float]]:
    """Pin short windows around spoken decisions/outcomes not covered by a land beat."""
    cues = [row for row in (pack.get("ocr") or []) if isinstance(row, Mapping)]
    if not cues:
        return []
    covered: list[tuple[float, float]] = []
    for beat in beats or []:
        span = _time_span(beat.get("t"))
        if span and span[1] - span[0] > 0.2:
            covered.append((float(span[0]), float(span[1])))
    duration = float(pack.get("duration_sec") or 0.0)
    _story_start, story_end = recap_story_window(duration) if duration > 1.0 else (0.0, duration)
    raw: list[tuple[float, float]] = []
    for cue in cues:
        text = str(cue.get("text") or "")
        if not _DIALOGUE_OUTCOME_RE.search(text):
            continue
        try:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") or start)
        except (TypeError, ValueError):
            continue
        if duration >= 360 and start >= story_end:
            continue
        # Long entry beats that merely overlap the cue do NOT count as a land.
        if _beat_lands_dialogue_outcome(covered, start, end, pad_sec=cover_pad_sec):
            continue
        lo = max(0.0 if duration < 360 else _story_start, start - 8.0)
        hi = min(story_end if duration >= 360 else max(end + 12.0, duration), end + 14.0)
        if hi - lo < 3.0:
            continue
        raw.append((round(lo, 2), round(hi, 2)))
    if not raw:
        return []
    raw.sort()
    merged: list[tuple[float, float]] = [raw[0]]
    for lo, hi in raw[1:]:
        if lo <= merged[-1][1] + 6.0:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged

def trim_story_beats_to_limit(
    beats: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_STORY_BEATS,
) -> list[dict[str, Any]]:
    """Safety valve only for absurd blow-ups. Never used to sparsify evidenced plans."""
    items = [dict(beat) for beat in beats]
    cap = max(8, int(limit or MAX_STORY_BEATS))
    if len(items) <= cap:
        return items
    by_time = sorted(
        items,
        key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)),
    )
    hard: set[int] = set()
    if by_time:
        hard.add(int(by_time[0].get("id") or 0))
        hard.add(int(by_time[-1].get("id") or 0))
    for beat in items:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        importance = float(beat.get("importance") or 0.0)
        event = str(beat.get("event") or "")
        # Keep climax AND enter/exit/bridge texture — never drop story bookends as filler.
        if importance >= 0.85:
            hard.add(beat_id)
        elif _TEXTURE_BEAT_RE.search(event) or any(
            token in event
            for token in (
                "进入",
                "赶到",
                "走进",
                "离开",
                "收束",
                "结局",
                "落点",
                "余波",
                "答应",
                "拒绝",
                "决定",
                "胜负",
                "结果",
                "收下",
                "推回",
            )
        ):
            hard.add(beat_id)
    ranked = sorted(
        items,
        key=lambda item: (
            int(item.get("id") or 0) in hard,
            float(item.get("importance") or 0.5),
            -((_time_span(item.get("t")) or (0.0, 0.0))[1] - (_time_span(item.get("t")) or (0.0, 0.0))[0]),
        ),
        reverse=True,
    )
    kept_ids = {int(item.get("id") or 0) for item in ranked[:cap]}
    kept = [item for item in by_time if int(item.get("id") or 0) in kept_ids]
    return kept or by_time[:cap]

def drop_op_ed_beats(
    beats: list[Mapping[str, Any]],
    duration_sec: float,
) -> list[dict[str, Any]]:
    duration = float(duration_sec or 0.0)
    _op_start, story_end = recap_story_window(duration)
    kept: list[dict[str, Any]] = []
    for beat in beats:
        event = str(beat.get("event") or "")
        needed = str(beat.get("needed_visual") or "")
        if looks_like_op_ed_text(event, needed):
            continue
        span = _time_span(beat.get("t"))
        if span and duration >= 360 and span[0] >= story_end:
            continue
        kept.append(dict(beat))
    return kept or [dict(item) for item in beats]
