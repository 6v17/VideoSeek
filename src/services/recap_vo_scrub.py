"""Drop verbatim ASR / unevidenced speech from recap voiceover lines.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from src.services.recap_match import (
    _JP_KANA_RE,
    _beats_by_id,
    _evidence_for_source_span,
    _has_japanese_kana,
    _text_similarity,
    _time_span,
    is_weak_match_clip,
)
from src.services.recap_vo_budget import _punctuate_vo_sentence

_VO_QUOTE_RE = re.compile(r"[「『]([^」』]{1,120})[」』]")
_VO_WHITESPACE_RE = re.compile(r"\s+")
_SPEECH_ACT_RE = re.compile(
    r"(说|告诉|喊道|叫道|问道|答道|宣布|表示|低声|开口|下令|命令|提醒|警告|质问|反问|承认|否认|发誓)"
)

def _normalize_vo_compare(text: str) -> str:
    return _VO_WHITESPACE_RE.sub("", str(text or "").strip().lower())

def _vo_overlaps_source_line(vo: str, source: str, *, min_chars: int = 6) -> bool:
    left = _normalize_vo_compare(vo)
    right = _normalize_vo_compare(source)
    if len(left) < min_chars or len(right) < min_chars:
        return False
    if left in right or right in left:
        return True
    return _text_similarity(left, right) >= 0.72

def scrub_verbatim_source_dialogue_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Drop Japanese kana / near-verbatim ASR pasted into VO."""
    out: list[dict[str, Any]] = []
    for clip in clips or []:
        row = dict(clip)
        vo = str(row.get("vo") or "").strip()
        if not vo:
            out.append(row)
            continue

        asr_texts: list[str] = []
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or src_in)
        except (TypeError, ValueError):
            src_in, src_out = 0.0, 0.0
        if pack is not None:
            evidence = _evidence_for_source_span(pack, src_in, src_out, asr_limit=12, cap_limit=1)
            asr_texts = [str(item.get("text") or "") for item in evidence.get("asr") or []]

        # Heavy Japanese → drop the whole line (source dialogue pasted as VO).
        kana_hits = _JP_KANA_RE.findall(vo)
        if len(kana_hits) >= 3 or (kana_hits and len(kana_hits) / max(len(vo), 1) >= 0.2):
            row["vo"] = ""
            out.append(row)
            continue

        def _keep_quote(match: re.Match[str]) -> str:
            quoted = str(match.group(1) or "").strip()
            if not quoted:
                return ""
            if _has_japanese_kana(quoted):
                return ""
            if any(_vo_overlaps_source_line(quoted, src) for src in asr_texts):
                return ""
            if len(quoted) > 6:
                return ""
            return match.group(0)

        cleaned = _VO_QUOTE_RE.sub(_keep_quote, vo)
        if _has_japanese_kana(cleaned):
            cleaned = _JP_KANA_RE.sub("", cleaned)
        # Strip leftover separators after kana/quote removal; keep sentence enders.
        cleaned = _VO_WHITESPACE_RE.sub(" ", cleaned).strip(" ，,.;；")
        if cleaned and any(_vo_overlaps_source_line(cleaned, src, min_chars=8) for src in asr_texts):
            cleaned = ""
        if len(re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)) < 2:
            cleaned = ""
        elif cleaned and cleaned[-1] not in "。！？!?…":
            cleaned = _punctuate_vo_sentence(cleaned)
        row["vo"] = cleaned
        out.append(row)
    return out

def _vo_source_span_for_scrub(
    clips: Sequence[Mapping[str, Any]],
    index: int,
) -> tuple[float, float]:
    """Widen to empty same-beat follow shots covered by spanning VO."""
    items = list(clips or [])
    clip = items[index]
    try:
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or src_in)
    except (TypeError, ValueError):
        return 0.0, 0.0
    beat_id = clip.get("beat_id")
    for nxt in items[index + 1 :]:
        if beat_id is None or nxt.get("beat_id") != beat_id:
            break
        if str(nxt.get("vo") or "").strip():
            break
        try:
            nxt_out = float(nxt.get("src_out") or 0.0)
        except (TypeError, ValueError):
            break
        src_out = max(src_out, nxt_out)
    return src_in, src_out

def _vo_evidence_window(
    clips: Sequence[Mapping[str, Any]],
    index: int,
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    pad_sec: float = 8.0,
) -> tuple[float, float]:
    """Widen VO evidence to the beat time window so short cuts still see nearby dialogue."""
    src_in, src_out = _vo_source_span_for_scrub(clips, index)
    pad = max(0.0, float(pad_sec))
    lo, hi = src_in - pad, src_out + pad
    try:
        beat_id = int((clips[index] or {}).get("beat_id") or 0)
    except (TypeError, ValueError, IndexError):
        beat_id = 0
    beat = _beats_by_id(beats).get(beat_id) if beat_id else None
    span = _time_span((beat or {}).get("t")) if beat else None
    if span:
        lo = min(lo, span[0] - 2.0)
        hi = max(hi, span[1] + 2.0)
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi

def scrub_unevidenced_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Drop VO that invents speech/plot without asr/caps in the picture span."""
    if pack is None:
        # Without a pack we cannot verify evidence; leave VO untouched.
        return [dict(clip) for clip in clips or []]
    items = [dict(clip) for clip in clips or []]
    by_id = _beats_by_id(beats)
    out: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        vo = str(row.get("vo") or "").strip()
        if not vo:
            out.append(row)
            continue
        src_in, src_out = _vo_evidence_window(items, index, beats)
        evidence = _evidence_for_source_span(
            pack, src_in, src_out, pad_sec=0.0, asr_limit=24, cap_limit=10
        )
        asr_rows = list(evidence.get("asr") or [])
        cap_rows = list(evidence.get("caps") or [])
        asr_blob = " ".join(str(item.get("text") or "") for item in asr_rows)
        cap_blob = " ".join(str(item.get("cap") or "") for item in cap_rows)
        has_asr = bool(asr_blob.strip())
        has_caps = bool(cap_blob.strip())
        weak = is_weak_match_clip(row)

        if not has_asr and not has_caps:
            row["vo"] = ""
            out.append(row)
            continue

        # Outline parroting with no dialogue: drop if VO ≈ event and barely matches caps.
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        event = str(row.get("event") or (by_id.get(beat_id) or {}).get("event") or "").strip()
        if (
            not has_asr
            and event
            and _text_similarity(_normalize_vo_compare(vo), _normalize_vo_compare(event)) >= 0.55
            and (
                not has_caps
                or _text_similarity(_normalize_vo_compare(vo), _normalize_vo_compare(cap_blob)) < 0.28
            )
        ):
            row["vo"] = ""
            out.append(row)
            continue

        parts = [item for item in re.split(r"(?<=[。！？!?；;])", vo) if str(item or "").strip()]
        if not parts:
            parts = [vo]
        kept: list[str] = []
        for part in parts:
            body = str(part or "").strip()
            if not body:
                continue
            quoted = bool(_VO_QUOTE_RE.search(body))
            speechy = bool(_SPEECH_ACT_RE.search(body)) or quoted
            # No dialogue at all → cannot report speech.
            if speechy and not has_asr:
                continue
            # Quoted invention: must touch source lines. Bare「XX说」narrative with asr is OK
            # (Chinese paraphrase of JP dialogue must not be nuked).
            if quoted and has_asr:
                if not _vo_overlaps_source_line(body, asr_blob, min_chars=4):
                    if _text_similarity(_normalize_vo_compare(body), _normalize_vo_compare(asr_blob)) < 0.22:
                        continue
            if weak and quoted:
                continue
            kept.append(body)
        cleaned = "".join(kept).strip(" ，,")
        if cleaned and cleaned[-1] not in "。！？!?…":
            cleaned = _punctuate_vo_sentence(cleaned)
        if len(re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)) < 2:
            cleaned = ""
        row["vo"] = cleaned
        out.append(row)
    return out
