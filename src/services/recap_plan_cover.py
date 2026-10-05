"""Force plan beats onto dialogue lands, silent spans, and ASR/VLM spine.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from src.services.recap_focus import story_silent_spans
from src.services.recap_match import time_span, recap_story_window
from src.services.recap_spine import _DIALOGUE_OUTCOME_RE, _spine_event_label

def _beat_lands_dialogue_outcome(
    spans: Sequence[tuple[float, float]],
    cue_start: float,
    cue_end: float,
    *,
    pad_sec: float = 4.0,
    land_tail_sec: float = 22.0,
) -> bool:
    """True only if some beat includes the cue and ends soon after it (not entry-only)."""
    for span in spans:
        if span[0] - pad_sec <= cue_start and cue_end <= span[1] + pad_sec:
            if span[1] <= cue_end + land_tail_sec:
                return True
    return False

def ensure_beats_land_dialogue_outcomes(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Force a land beat on every spoken decision/outcome — entry overlap is not enough."""
    items = [dict(beat) for beat in beats or []]
    cues = [row for row in (pack.get("ocr") or []) if isinstance(row, Mapping)]
    if not cues:
        return items
    covered_spans = [span for span in (time_span(beat.get("t")) for beat in items) if span]
    used_ids = {int(beat.get("id") or 0) for beat in items if int(beat.get("id") or 0) > 0}
    next_id = max(used_ids) + 1 if used_ids else 1
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration) if duration > 1.0 else (0.0, duration or 1e9)
    for cue in cues:
        text = str(cue.get("text") or "").strip()
        if not text or not _DIALOGUE_OUTCOME_RE.search(text):
            continue
        try:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") or start)
        except (TypeError, ValueError):
            continue
        if duration >= 360 and start >= story_end:
            continue
        if _beat_lands_dialogue_outcome(covered_spans, start, end):
            continue
        while next_id in used_ids:
            next_id += 1
        speaker = str(cue.get("speaker") or "").strip()
        who = speaker or "对白"
        body = re.sub(r"\s+", "", text)[:28]
        lo = max(story_start if duration >= 360 else 0.0, start - 8.0)
        hi = min(story_end if duration >= 360 else max(end + 14.0, duration or end + 14.0), end + 14.0)
        if hi - lo < 3.0:
            hi = lo + 8.0
        beat = {
            "id": next_id,
            "event": f"{who}{body}收束局面"[:120],
            "importance": 0.9,
            "evidence_required": ["人物", "对话"] if speaker else ["对话"],
            "needed_visual": "",
            "t": [round(lo, 2), round(hi, 2)],
            "spine_forced": True,
            "outcome_forced": True,
        }
        items.append(beat)
        used_ids.add(next_id)
        covered_spans.append((lo, hi))
        next_id += 1
    items.sort(key=lambda item: ((time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)))
    return items

def ensure_beats_cover_silent_spans(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    *,
    cover_pad_sec: float = 4.0,
) -> list[dict[str, Any]]:
    """Force beats on no-ASR picture spans that still have caps — silent time is still story time."""
    items = [dict(beat) for beat in beats or []]
    covered = [span for span in (time_span(beat.get("t")) for beat in items) if span]
    used_ids = {int(beat.get("id") or 0) for beat in items if int(beat.get("id") or 0) > 0}
    next_id = max(used_ids) + 1 if used_ids else 1
    for silent in story_silent_spans(pack):
        window = time_span(silent.get("t"))
        if not window:
            continue
        caps = [row for row in (silent.get("caps") or []) if isinstance(row, Mapping)]
        if not caps and not silent.get("has_cap"):
            # Pure dead air with no picture note — still pin a short placeholder if long.
            if window[1] - window[0] < 20.0:
                continue
        if any(
            span[0] - cover_pad_sec <= window[0] and window[1] <= span[1] + cover_pad_sec
            for span in covered
        ):
            continue
        while next_id in used_ids:
            next_id += 1
        cap0 = str((caps[0] or {}).get("cap") or "").strip() if caps else ""
        beat = {
            "id": next_id,
            "event": (f"无对白画面推进：{cap0}" if cap0 else "无对白时段场面推进")[:120],
            "importance": 0.55 if cap0 else 0.4,
            "evidence_required": ["场面", "变化"] if cap0 else ["场面"],
            "needed_visual": cap0 or "无对白画面变化",
            "t": [round(window[0], 2), round(window[1], 2)],
            "spine_forced": True,
            "silent_forced": True,
        }
        items.append(beat)
        used_ids.add(next_id)
        covered.append(window)
        next_id += 1
    items.sort(key=lambda item: ((time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)))
    return items

def ensure_beats_cover_spine(
    beats: Sequence[Mapping[str, Any]],
    spine: Sequence[Mapping[str, Any]],
    *,
    cover_ratio: float = 0.35,
) -> list[dict[str, Any]]:
    """Insert missing spine windows the LLM skipped — shared-clock evidence is law."""
    items = [dict(beat) for beat in beats or []]
    if not spine:
        return items
    covered_spans = [time_span(beat.get("t")) for beat in items]
    covered_spans = [span for span in covered_spans if span]
    used_ids = {int(beat.get("id") or 0) for beat in items if int(beat.get("id") or 0) > 0}
    next_id = max(used_ids) + 1 if used_ids else 1

    def _overlap_ratio(window: tuple[float, float], span: tuple[float, float]) -> float:
        lo = max(window[0], span[0])
        hi = min(window[1], span[1])
        width = max(0.0, window[1] - window[0])
        if width <= 0.05:
            return 0.0
        return max(0.0, hi - lo) / width

    def _phase_dedicated(window: tuple[float, float], spans: Sequence[tuple[float, float]], phase: str) -> bool:
        """True when a beat is about this phase — not a blob that swallows enter+mid+land."""
        phase_dur = max(0.1, window[1] - window[0])
        mid = 0.5 * (window[0] + window[1])
        need = 0.55 if phase in {"enter", "mid", "land"} else float(cover_ratio)
        for span in spans:
            if _overlap_ratio(window, span) < need:
                continue
            beat_dur = max(0.0, span[1] - span[0])
            # A whole-scene blob must not count as the mid/enter beat.
            if phase in {"enter", "mid", "land"} and beat_dur > phase_dur + 28.0:
                if not (span[0] <= mid <= span[1] and beat_dur <= phase_dur * 2.8):
                    continue
            if phase in {"enter", "mid", "land"} and not (span[0] - 2.0 <= mid <= span[1] + 2.0):
                continue
            return True
        return False

    for seg in spine:
        window = time_span(seg.get("t"))
        if not window:
            continue
        if not (seg.get("asr") or seg.get("caps")):
            continue
        phase = str(seg.get("phase") or "full").strip().lower()
        outcome_rows = [
            row
            for row in (seg.get("asr") or [])
            if isinstance(row, Mapping) and _DIALOGUE_OUTCOME_RE.search(str(row.get("text") or ""))
        ]
        # Entry-only overlap must NOT skip a cluster that still lacks a land near the outcome.
        if outcome_rows and phase in {"land", "full"}:
            last = outcome_rows[-1]
            try:
                cue_start = float(last.get("start") or window[0])
                cue_end = float(last.get("end") or cue_start)
            except (TypeError, ValueError):
                cue_start, cue_end = window[0], window[1]
            if not _beat_lands_dialogue_outcome(covered_spans, cue_start, cue_end):
                while next_id in used_ids:
                    next_id += 1
                speaker = str(last.get("speaker") or "").strip()
                speakers = [str(item).strip() for item in (seg.get("speakers") or []) if str(item).strip()]
                who = speaker or (speakers[0] if speakers else "")
                body = re.sub(r"\s+", "", str(last.get("text") or ""))[:28]
                lo = max(window[0], cue_start - 8.0)
                hi = min(window[1] + 4.0, cue_end + 14.0)
                if hi - lo < 3.0:
                    hi = lo + 8.0
                beat = {
                    "id": next_id,
                    "event": (f"{who}{body}收束局面" if who else f"对白收束至{body}")[:120],
                    "importance": 0.9,
                    "evidence_required": ["人物", "对话"] if who else ["对话"],
                    "needed_visual": "",
                    "t": [round(lo, 2), round(hi, 2)],
                    "spine_forced": True,
                    "outcome_forced": True,
                }
                items.append(beat)
                used_ids.add(next_id)
                covered_spans.append((lo, hi))
                next_id += 1
        if _phase_dedicated(window, covered_spans, phase):
            continue
        while next_id in used_ids:
            next_id += 1
        event = _spine_event_label(seg)
        caps = seg.get("caps") or []
        needed = str((caps[0] or {}).get("cap") or "").strip()[:80] if caps else ""
        importance = 0.9 if phase == "land" or outcome_rows else (0.78 if phase == "mid" else 0.68)
        evidence = ["对话"]
        if caps:
            evidence.append("变化")
        if any(str(row.get("speaker") or "").strip() for row in (seg.get("asr") or []) if isinstance(row, Mapping)):
            evidence.insert(0, "人物")
        beat = {
            "id": next_id,
            "event": event[:120],
            "importance": importance,
            "evidence_required": evidence[:4],
            "needed_visual": needed,
            "t": [round(window[0], 2), round(window[1], 2)],
            "spine_forced": True,
            "phase": phase,
        }
        items.append(beat)
        used_ids.add(next_id)
        covered_spans.append(window)
        next_id += 1
    items.sort(key=lambda item: ((time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)))
    return items
