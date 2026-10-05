"""Snap cuts to evidence chunks and clamp them into beat time windows.

Insert clamp / TTS pad / duration trim stay in ``recap_service``. ``recap_service``
re-exports these names for existing callers.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    BEAT_SRC_PAD_SEC,
    MAX_CLIP_SEC,
    MIN_CLIP_SEC,
    MIN_FLASH_CLIP_SEC,
)
from src.services.recap_match import (
    _beat_visual_anchor,
    _beats_by_id,
    _cap_match_score_for_anchor,
    _evidence_for_source_span,
    _overlap_sec,
    _time_span,
    keep_chunk_for_recap,
    recap_story_window,
)

def snap_cuts_to_capped_chunks(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    min_gain: float = 0.10,
) -> list[dict[str, Any]]:
    """Realign cuts to the best VLM-captioned chunk inside each beat.

    Having caps is not enough — Match still picks lookalike wrong scenes.
    Prefer the capped chunk whose ``cap`` best matches the beat event /
    needed_visual, and replace the current pick when the gain is clear.
    """
    items = [dict(clip) for clip in cuts or []]
    if not items or not beats:
        return items
    duration = float(pack.get("duration_sec") or 0.0)
    by_id = _beats_by_id(beats)
    capped: list[tuple[tuple[float, float], dict[str, Any]]] = []
    for chunk in pack.get("chunks") or []:
        if not keep_chunk_for_recap(chunk, duration):
            continue
        if not str(chunk.get("cap") or "").strip():
            continue
        span = _time_span(chunk.get("t"))
        if not span or span[1] - span[0] < MIN_FLASH_CLIP_SEC:
            continue
        capped.append((span, dict(chunk)))
    if not capped:
        return items

    gain = max(0.04, float(min_gain or 0.10))
    used_chunk_spans: list[tuple[float, float]] = []
    out: list[dict[str, Any]] = []
    for clip in items:
        row = dict(clip)
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            out.append(row)
            continue
        if src_out <= src_in + 0.2:
            out.append(row)
            continue
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) if beat_id else None
        beat_span = _time_span((beat or {}).get("t")) if beat else None
        if not beat_span:
            out.append(row)
            continue

        anchor = _beat_visual_anchor(beat, row)
        current_ev = _evidence_for_source_span(
            pack, src_in, src_out, pad_sec=1.0, asr_limit=8, cap_limit=6
        )
        current_cap = " ".join(str(item.get("cap") or "") for item in current_ev.get("caps") or [])
        current_asr = " ".join(str(item.get("text") or "") for item in current_ev.get("asr") or [])
        current_score = _cap_match_score_for_anchor(anchor, current_cap, asr_blob=current_asr)

        want = max(MIN_FLASH_CLIP_SEC, min(src_out - src_in, MAX_CLIP_SEC))
        best: tuple[float, float, dict[str, Any], float] | None = None
        for span, chunk in capped:
            overlap = _overlap_sec(span, beat_span)
            if overlap <= 0.5:
                continue
            # Don't snap every beat onto the same already-used capped window.
            if any(_overlap_sec(span, used) / max(0.2, span[1] - span[0]) >= 0.55 for used in used_chunk_spans):
                continue
            cap = str(chunk.get("cap") or "")
            # Local ASR on the candidate chunk helps when event is dialogue-shaped.
            cand_ev = _evidence_for_source_span(
                pack, span[0], span[1], pad_sec=0.5, asr_limit=8, cap_limit=1
            )
            cand_asr = " ".join(str(item.get("text") or "") for item in cand_ev.get("asr") or [])
            score = _cap_match_score_for_anchor(anchor, cap, asr_blob=cand_asr)
            # Slight preference for staying near the LLM pick when scores are close.
            score += 0.04 * min(1.0, _overlap_sec(span, (src_in, src_out)) / max(0.2, want))
            if best is None or score > best[3]:
                best = (span[0], span[1], chunk, score)

        if best is None:
            used_chunk_spans.append((src_in, src_out))
            out.append(row)
            continue
        lo, hi, chunk, best_score = best
        should_move = False
        if not current_cap.strip() and best_score >= 0.12:
            should_move = True
        elif best_score >= current_score + gain and best_score >= 0.16:
            should_move = True
        elif current_score < 0.14 and best_score >= 0.22:
            should_move = True
        if not should_move:
            used_chunk_spans.append((src_in, src_out))
            out.append(row)
            continue

        take = min(want, hi - lo)
        start = max(lo, min(0.5 * (lo + hi) - take * 0.5, hi - take))
        end = start + take
        # Avoid no-op rewrites.
        if abs(start - src_in) < 0.35 and abs(end - src_out) < 0.35:
            used_chunk_spans.append((src_in, src_out))
            out.append(row)
            continue
        row["src_in"] = round(start, 3)
        row["src_out"] = round(end, 3)
        row["duration"] = round(end - start, 3)
        if chunk.get("i") is not None:
            row["chunk_index"] = chunk.get("i")
        reason = str(row.get("reason") or "").strip()
        tag = "已对齐最佳画面描述"
        if tag not in reason:
            row["reason"] = f"{reason}｜{tag}".strip("｜")
        used_chunk_spans.append((start, end))
        out.append(row)
    return out

def _snap_src_into_beat_window(
    pack: Mapping[str, Any],
    beat_span: tuple[float, float],
    *,
    want_sec: float,
    pad_sec: float = BEAT_SRC_PAD_SEC,
    preferred: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    """Place a clip inside beat.t (±pad), preferring overlapping chunks / residual overlap."""
    pad = float(pad_sec)
    lo = float(beat_span[0]) - pad
    hi = float(beat_span[1]) + pad
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    lo = max(float(story_start or 0.0), lo)
    if duration > 0:
        hi = min(float(story_end or duration), hi, duration)
    if hi - lo < MIN_FLASH_CLIP_SEC:
        return None
    want = max(MIN_FLASH_CLIP_SEC, min(float(want_sec or MIN_CLIP_SEC), hi - lo, MAX_CLIP_SEC))

    if preferred:
        try:
            p_in, p_out = float(preferred[0]), float(preferred[1])
        except (TypeError, ValueError, IndexError):
            p_in, p_out = 0.0, 0.0
        if p_out > p_in:
            ov_lo = max(p_in, lo)
            ov_hi = min(p_out, hi)
            if ov_hi - ov_lo >= min(want, MIN_FLASH_CLIP_SEC):
                if ov_hi - ov_lo > want:
                    ov_hi = ov_lo + want
                return round(ov_lo, 3), round(ov_hi, 3)

    best: tuple[float, float] | None = None
    best_overlap = -1.0
    for item in pack.get("chunks") or []:
        if not keep_chunk_for_recap(item, duration):
            continue
        window = _time_span(item.get("t"))
        if not window:
            continue
        overlap = _overlap_sec(window, beat_span)
        if overlap <= 0.4:
            continue
        cand_lo = max(window[0], lo)
        cand_hi = min(window[1], hi)
        if cand_hi - cand_lo < MIN_FLASH_CLIP_SEC:
            continue
        take = min(want, cand_hi - cand_lo)
        # Prefer the middle of the overlapping chunk when room allows.
        mid = 0.5 * (cand_lo + cand_hi)
        start = max(cand_lo, min(mid - take * 0.5, cand_hi - take))
        end = start + take
        if overlap > best_overlap:
            best_overlap = overlap
            best = (round(start, 3), round(end, 3))
    if best:
        return best
    return round(lo, 3), round(min(hi, lo + want), 3)

def clamp_cuts_to_beat_window(
    cuts: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    pad_sec: float = BEAT_SRC_PAD_SEC,
) -> list[dict[str, Any]]:
    """Hard-clamp every cut into its beat.t window so Match cannot borrow later acts."""
    items = [dict(clip) for clip in cuts or []]
    if not items or not beats:
        return items
    by_id = _beats_by_id(beats)
    pad = float(pad_sec)
    out: list[dict[str, Any]] = []
    for clip in items:
        row = dict(clip)
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) if beat_id else None
        span = _time_span((beat or {}).get("t")) if beat else None
        if not span:
            out.append(row)
            continue
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            out.append(row)
            continue
        if src_out <= src_in + 0.2:
            out.append(row)
            continue
        expanded = (span[0] - pad, span[1] + pad)
        overlap = _overlap_sec((src_in, src_out), expanded)
        clip_len = src_out - src_in
        if overlap >= min(clip_len * 0.85, clip_len - 0.05) and overlap > 0.4:
            # Mostly inside — trim any spill past the pad.
            trimmed_in = max(src_in, expanded[0])
            trimmed_out = min(src_out, expanded[1])
            if trimmed_out - trimmed_in >= MIN_FLASH_CLIP_SEC:
                row["src_in"] = round(trimmed_in, 3)
                row["src_out"] = round(trimmed_out, 3)
                row["duration"] = round(trimmed_out - trimmed_in, 3)
            out.append(row)
            continue
        placed = _snap_src_into_beat_window(
            pack,
            span,
            want_sec=max(MIN_FLASH_CLIP_SEC, min(clip_len, MAX_CLIP_SEC)),
            pad_sec=pad,
            preferred=(src_in, src_out) if overlap > 0.05 else None,
        )
        if placed is None:
            out.append(row)
            continue
        row["src_in"], row["src_out"] = placed
        row["duration"] = round(placed[1] - placed[0], 3)
        reason = str(row.get("reason") or "").strip()
        if "弱证据" not in reason:
            row["reason"] = f"{reason}｜已钳回拍时间窗".strip("｜")
        out.append(row)
    return out
