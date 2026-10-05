"""Match-wave grouping and coverage pin helpers for recap planning.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import MATCH_BEATS_PER_WAVE, MAX_PLAN_BEATS
from src.services.recap_match import _overlap_sec, _time_span
from src.services.recap_plan_gaps import _TEXTURE_BEAT_RE

def split_beats_for_match(
    beats: list[Mapping[str, Any]],
    *,
    per_wave: int = MATCH_BEATS_PER_WAVE,
    max_span_sec: float = 140.0,
    max_gap_sec: float = 48.0,
) -> list[list[dict[str, Any]]]:
    """Group beats for Match: small waves that stay near each other in source time.

    Count alone is not enough — packing 4 beats that span half an episode still
    dumps the whole middle of the film into one prompt and the model picks
    lookalike shots from the wrong act.
    """
    items = sorted(
        (dict(beat) for beat in beats),
        key=lambda item: (
            (_time_span(item.get("t")) or (0.0, 0.0))[0],
            int(item.get("id") or 0),
        ),
    )
    size = max(1, int(per_wave or MATCH_BEATS_PER_WAVE))
    span_cap = max(40.0, float(max_span_sec or 140.0))
    gap_cap = max(12.0, float(max_gap_sec or 48.0))
    if len(items) <= 1:
        return [items] if items else []

    waves: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    wave_lo: float | None = None
    wave_hi: float | None = None
    for beat in items:
        span = _time_span(beat.get("t"))
        if not current:
            current = [beat]
            if span:
                wave_lo, wave_hi = span[0], span[1]
            continue
        start_new = False
        if len(current) >= size:
            start_new = True
        elif span and wave_lo is not None and wave_hi is not None:
            if span[1] - wave_lo > span_cap:
                start_new = True
            elif span[0] - wave_hi > gap_cap:
                start_new = True
        if start_new:
            waves.append(current)
            current = [beat]
            wave_lo, wave_hi = (span[0], span[1]) if span else (None, None)
            continue
        current.append(beat)
        if span:
            wave_lo = span[0] if wave_lo is None else min(wave_lo, span[0])
            wave_hi = span[1] if wave_hi is None else max(wave_hi, span[1])
    if current:
        waves.append(current)
    return waves

def missing_match_beats(
    beats: list[Mapping[str, Any]],
    cuts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    have_ids = {
        int(cut.get("beat_id"))
        for cut in cuts
        if cut.get("beat_id") is not None
    }
    missing: list[dict[str, Any]] = []
    for beat in beats:
        try:
            beat_id = int(beat.get("id"))
        except (TypeError, ValueError):
            beat_id = None
        if beat_id is not None and beat_id in have_ids:
            continue
        span = _time_span(beat.get("t"))
        covered = False
        if span:
            for cut in cuts:
                try:
                    clip_span = (float(cut.get("src_in")), float(cut.get("src_out")))
                except (TypeError, ValueError):
                    continue
                if _overlap_sec(clip_span, span) > 0.5:
                    covered = True
                    break
        if not covered:
            missing.append(dict(beat))
    return missing

def _coverage_pin_ids(beats: list[Mapping[str, Any]]) -> set[int]:
    by_time = sorted(
        beats,
        key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)),
    )
    pins: set[int] = set()
    if by_time:
        pins.add(int(by_time[0].get("id") or 0))
        pins.add(int(by_time[-1].get("id") or 0))
    for beat in beats:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        if float(beat.get("importance") or 0.0) >= 0.65:
            pins.add(beat_id)
    pins.update(_texture_pin_ids(beats))
    return {pin for pin in pins if pin}

def _is_texture_beat(beat: Mapping[str, Any]) -> bool:
    evidence = " ".join(str(tag) for tag in (beat.get("evidence_required") or []))
    body = f"{beat.get('event') or ''} {beat.get('needed_visual') or ''} {evidence}"
    return bool(_TEXTURE_BEAT_RE.search(body))

def _texture_pin_ids(beats: Sequence[Mapping[str, Any]], *, limit: int = 3) -> set[int]:
    """Keep a few setting / character / scene-change beats so allocate does not drop them all."""
    textured: list[tuple[float, int]] = []
    for beat in beats:
        if not _is_texture_beat(beat):
            continue
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        start = (_time_span(beat.get("t")) or (0.0, 0.0))[0]
        textured.append((start, beat_id))
    if not textured:
        return set()
    textured.sort()
    if len(textured) <= limit:
        return {beat_id for _start, beat_id in textured}
    picks = {textured[0][1], textured[-1][1]}
    mid = textured[len(textured) // 2][1]
    picks.add(mid)
    return picks

def _ensure_pinned_rows(
    keep: list[tuple[float, float, dict[str, Any]]],
    scored: list[tuple[float, float, dict[str, Any]]],
    pin_ids: set[int],
) -> list[tuple[float, float, dict[str, Any]]]:
    rows = list(keep)
    have = {int(row[2].get("id") or 0) for row in rows}
    for row in scored:
        beat_id = int(row[2].get("id") or 0)
        if beat_id not in pin_ids or beat_id in have:
            continue
        if len(rows) >= MAX_PLAN_BEATS:
            drop_at = None
            for index in range(len(rows) - 1, -1, -1):
                other_id = int(rows[index][2].get("id") or 0)
                if other_id not in pin_ids:
                    drop_at = index
                    break
            if drop_at is None:
                continue
            dropped = rows.pop(drop_at)
            have.discard(int(dropped[2].get("id") or 0))
        rows.append(row)
        have.add(beat_id)
    return rows
