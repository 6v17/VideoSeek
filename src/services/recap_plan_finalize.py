"""Deterministic plan finalize: scrub empty windows and force spine/lands.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import ENDING_COVER_RATIO, MAX_STORY_BEATS
from src.services.recap_match import (
    _evidence_for_source_span,
    _looks_like_scene_shift_text,
    _time_span,
    recap_story_window,
)
from src.services.recap_match_waves import _is_texture_beat
from src.services.recap_plan_cover import (
    ensure_beats_cover_silent_spans,
    ensure_beats_cover_spine,
    ensure_beats_land_dialogue_outcomes,
)
from src.services.recap_plan_gaps import (
    beats_cover_ending,
    beats_cover_opening,
    drop_op_ed_beats,
    opening_deadline_sec,
    trim_story_beats_to_limit,
)
from src.services.recap_spine import build_asr_vlm_spine

def scrub_unevidenced_beats(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any] | None,
    *,
    pad_sec: float = 14.0,
) -> list[dict[str, Any]]:
    """Drop invented plot beats whose time window has no asr and no caps."""
    items = [dict(beat) for beat in beats or []]
    if not items or pack is None:
        return items
    kept: list[dict[str, Any]] = []
    for beat in items:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        evidence = _evidence_for_source_span(
            pack,
            span[0],
            span[1],
            pad_sec=pad_sec,
            asr_limit=24,
            cap_limit=12,
        )
        has_asr = bool(evidence.get("asr"))
        has_caps = bool(evidence.get("caps"))
        if has_asr or has_caps:
            kept.append(beat)
            continue
        # Empty window = wrong t or pure hallucination. Keep only soft texture/bridge.
        try:
            importance = float(beat.get("importance") or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
        if importance >= 0.45:
            continue
        if _is_texture_beat(beat) or _looks_like_scene_shift_text(beat.get("event")):
            # Still drop — no picture/dialogue to land on.
            continue
    if not kept:
        return items
    return kept

def finalize_recap_plan_beats(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    *,
    duration_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Deterministic bookends/spine/lands after the one-shot act plan — zero extra LLM."""
    duration = float(duration_sec if duration_sec is not None else pack.get("duration_sec") or 0.0)
    items = drop_op_ed_beats([dict(beat) for beat in beats or []], duration)
    items = scrub_unevidenced_beats(items, pack)
    items = ensure_beats_cover_spine(items, build_asr_vlm_spine(pack))
    items = ensure_beats_land_dialogue_outcomes(items, pack)
    items = ensure_beats_cover_silent_spans(items, pack)
    if duration > 1.0 and not beats_cover_opening(items, duration):
        deadline = opening_deadline_sec(duration)
        spine = build_asr_vlm_spine(pack)
        head = next((seg for seg in spine if (_time_span(seg.get("t")) or (1e9, 1e9))[0] <= deadline), None)
        if head is None:
            cues = [
                row
                for row in (pack.get("ocr") or [])
                if isinstance(row, Mapping) and float(row.get("start") or 0.0) <= deadline
            ]
            if cues:
                lo = float(cues[0].get("start") or 0.0)
                hi = max(float(cues[-1].get("end") or lo), lo + 8.0)
                head = {"t": [lo, min(hi, deadline + 12.0)], "asr": cues[:8], "caps": [], "speakers": []}
        if head is not None:
            items = ensure_beats_cover_spine(items, [head], cover_ratio=0.99)
    if duration > 1.0 and not beats_cover_ending(items, duration):
        _story_start, story_end = recap_story_window(duration)
        spine = build_asr_vlm_spine(pack)
        tail = None
        for seg in reversed(spine):
            span = _time_span(seg.get("t"))
            if span and span[1] >= story_end * ENDING_COVER_RATIO:
                tail = seg
                break
        if tail is not None:
            items = ensure_beats_cover_spine(items, [tail], cover_ratio=0.99)
        items = ensure_beats_land_dialogue_outcomes(items, pack)
        items = ensure_beats_cover_silent_spans(items, pack)
    if len(items) > MAX_STORY_BEATS:
        items = trim_story_beats_to_limit(items, limit=MAX_STORY_BEATS)
    return items
