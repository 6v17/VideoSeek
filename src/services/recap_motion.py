"""Motion-chunk compaction and VLM gap indices for recap planning.

``fill_recap_motion_for_beats`` stays in the runner (needs ``build_recap_pack``).
``recap_service`` re-exports these names.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import RECAP_CLIMAX_IMPORTANCE, RECAP_VISUAL_EVIDENCE_TAGS
from src.services.recap_match import (
    _overlap_sec,
    _time_span,
    looks_like_op_ed_text,
    recap_story_window,
)


def _caption_one_liner(text: str, limit: int = 72) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    if body.startswith("{"):
        return ""
    line = body.split("\n", 1)[0].strip()
    json_at = line.find("{")
    if json_at > 0:
        line = line[:json_at].strip()
    return line[:limit]

def compact_motion_chunks(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    from src.services.understanding_tags import format_motion_cap_text, parse_motion_vlm_payload

    chunks = []
    for raw in evidence.get("chunks") or []:
        if not isinstance(raw, Mapping):
            continue
        caption = ""
        visible = ""
        change = ""
        inferred = ""
        inferred_weight = 0.0
        vision = ((raw.get("evidence") or {}).get("vision") or {})
        image = vision.get("image_caption") or {}
        if isinstance(image, Mapping):
            visible = str(image.get("visible") or "").strip()
            change = str(image.get("change") or "").strip()
            inferred = str(image.get("inferred") or "").strip()
            try:
                inferred_weight = float(image.get("inferred_weight") or 0.0)
            except (TypeError, ValueError):
                inferred_weight = 0.0
            caption = format_motion_cap_text(visible, change)
            parsed_tags: list[str] = []
            if not caption or (not visible and not change) or not image.get("tags"):
                parsed = parse_motion_vlm_payload(str(image.get("text") or image.get("raw_text") or ""))
                visible = visible or str(parsed.get("visible") or "").strip()
                change = change or str(parsed.get("change") or "").strip()
                if not inferred:
                    inferred = str(parsed.get("inferred") or "").strip()
                    try:
                        inferred_weight = float(parsed.get("inferred_weight") or 0.0)
                    except (TypeError, ValueError):
                        inferred_weight = 0.0
                parsed_tags = [str(t).strip() for t in (parsed.get("tags") or []) if str(t).strip()]
                caption = format_motion_cap_text(visible, change) or _caption_one_liner(
                    str(image.get("text") or ""), limit=160
                )
            tags = [
                str(t).strip()
                for t in (image.get("tags") or parsed_tags or raw.get("tags") or [])
                if str(t).strip()
            ]
        else:
            tags = [str(t).strip() for t in (raw.get("tags") or []) if str(t).strip()]
        tags = [t for t in tags if len(t) <= 12][:8]
        skip = "op_ed" if looks_like_op_ed_text(caption, " ".join(tags), inferred) else ""
        row = {
            "i": int(raw.get("chunk_index", 0) or 0),
            "t": [round(float(raw.get("start_sec", 0.0) or 0.0), 2), round(float(raw.get("end_sec", 0.0) or 0.0), 2)],
            "dur": round(max(0.0, float(raw.get("end_sec", 0.0) or 0.0) - float(raw.get("start_sec", 0.0) or 0.0)), 2),
            "tags": tags,
            "cap": caption,
            "skip": skip,
        }
        if visible:
            row["visible"] = visible[:120]
        if change:
            row["change"] = change[:120]
        if inferred:
            row["inferred"] = inferred[:80]
            row["inferred_weight"] = round(min(1.0, max(0.0, inferred_weight)), 3)
        chunks.append(row)
    return chunks

def compact_index_chunks(raw_chunks: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_chunks or []):
        if not isinstance(raw, Mapping):
            continue
        try:
            start = float(raw.get("start", raw.get("start_sec", 0.0)) or 0.0)
            end = float(raw.get("end", raw.get("end_sec", start)) or start)
        except (TypeError, ValueError):
            continue
        if end < start:
            start, end = end, start
        try:
            chunk_i = int(raw.get("i", raw.get("chunk_index", index)))
        except (TypeError, ValueError):
            chunk_i = index
        out.append(
            {
                "i": chunk_i,
                "t": [round(start, 2), round(end, 2)],
                "dur": round(max(0.0, end - start), 2),
                "tags": [],
                "cap": "",
                "skip": "",
            }
        )
    return out

def overlay_motion_captions(
    chunks: Sequence[Mapping[str, Any]],
    motion_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_i: dict[int, Mapping[str, Any]] = {}
    for row in motion_rows or []:
        try:
            by_i[int(row.get("i"))] = row
        except (TypeError, ValueError):
            continue
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in chunks or []:
        item = dict(row)
        try:
            chunk_i = int(item.get("i"))
        except (TypeError, ValueError):
            chunk_i = None
        extra = by_i.get(chunk_i) if chunk_i is not None else None
        if extra:
            if str(extra.get("cap") or "").strip():
                item["cap"] = extra.get("cap") or ""
            if extra.get("tags"):
                item["tags"] = list(extra.get("tags") or [])
            for key in ("visible", "change", "inferred"):
                if str(extra.get(key) or "").strip():
                    item[key] = str(extra.get(key) or "").strip()
            if extra.get("inferred_weight") is not None:
                try:
                    item["inferred_weight"] = float(extra.get("inferred_weight") or 0.0)
                except (TypeError, ValueError):
                    pass
            if str(extra.get("skip") or "").strip():
                item["skip"] = str(extra.get("skip") or "").strip()
        if chunk_i is not None:
            seen.add(chunk_i)
        out.append(item)
    for extra in motion_rows or []:
        try:
            chunk_i = int(extra.get("i"))
        except (TypeError, ValueError):
            continue
        if chunk_i in seen:
            continue
        out.append(dict(extra))
    out.sort(key=lambda row: (float((row.get("t") or [0.0])[0] or 0.0), int(row.get("i") or 0)))
    return out

def apply_recap_skip_marks(
    chunks: Sequence[Mapping[str, Any]],
    asr: Sequence[Mapping[str, Any]] | None,
    duration_sec: float,
) -> list[dict[str, Any]]:
    cues = list(asr or [])
    _start, story_end = recap_story_window(duration_sec)
    out: list[dict[str, Any]] = []
    for row in chunks or []:
        item = dict(row)
        if str(item.get("skip") or "").strip():
            out.append(item)
            continue
        span = _time_span(item.get("t"))
        if not span:
            out.append(item)
            continue
        lo, _hi = span
        if float(duration_sec or 0.0) >= 360 and lo >= story_end:
            item["skip"] = "op_ed"
            out.append(item)
            continue
        blob = " ".join(
            str(cue.get("text") or "")
            for cue in cues
            if _overlap_sec(
                (float(cue.get("start") or 0.0), float(cue.get("end") or cue.get("start") or 0.0)),
                span,
            )
            > 0.35
        )
        if looks_like_op_ed_text(blob):
            item["skip"] = "op_ed"
        out.append(item)
    return out

def _cue_span(cue: Mapping[str, Any]) -> tuple[float, float] | None:
    if "start" in cue or "end" in cue:
        try:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") if cue.get("end") is not None else start)
        except (TypeError, ValueError):
            return None
        if end < start:
            start, end = end, start
        return start, end
    return _time_span(cue.get("t"))

def _beat_evidence_tags(beat: Mapping[str, Any]) -> set[str]:
    tags: set[str] = set()
    for raw in beat.get("evidence_required") or []:
        text = str(raw or "").strip()
        if text:
            tags.add(text)
    return tags

def _beat_needs_visual_motion(beat: Mapping[str, Any]) -> bool:
    """Unknown requirements still get a caption. Dialogue-only beats can skip."""
    tags = _beat_evidence_tags(beat)
    if not tags:
        return True
    return bool(tags & RECAP_VISUAL_EVIDENCE_TAGS)

def _asr_covers_span(
    span: tuple[float, float],
    cues: Sequence[Mapping[str, Any]] | None,
) -> bool:
    duration = max(0.0, float(span[1]) - float(span[0]))
    if duration <= 0.0:
        return False
    covered = 0.0
    for cue in cues or []:
        cue_span = _cue_span(cue)
        if cue_span:
            covered += _overlap_sec(span, cue_span)
    need = min(8.0, max(2.0, duration * 0.25))
    return covered >= need

def _chunk_motion_beats(
    chunk: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    *,
    pad_sec: float,
) -> list[Mapping[str, Any]]:
    span = _time_span(chunk.get("t"))
    if not span:
        return []
    matched: list[Mapping[str, Any]] = []
    for beat in beats or []:
        beat_span = _time_span(beat.get("t"))
        if not beat_span:
            continue
        window = (beat_span[0] - pad_sec, beat_span[1] + pad_sec)
        if _overlap_sec(span, window) > 0.4:
            matched.append(beat)
    return matched

def recap_motion_gap_chunk_indices(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    *,
    pad_sec: float = 24.0,
) -> list[int]:
    """Chunks in beat windows that still need a VLM caption.

    Dialogue coverage does **not** skip motion: picture must still match the VO,
    and ASR-only planning otherwise leaves Match guessing empty caps.
    """
    pad = max(0.0, float(pad_sec or 0.0))
    windows = []
    for beat in beats or []:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        windows.append((span[0] - pad, span[1] + pad))
    if not windows:
        return []
    indices: list[int] = []
    for chunk in pack.get("chunks") or []:
        if str(chunk.get("skip") or "").strip() or str(chunk.get("cap") or "").strip():
            continue
        span = _time_span(chunk.get("t"))
        if not span:
            continue
        if not any(_overlap_sec(span, window) > 0.4 for window in windows):
            continue
        try:
            indices.append(int(chunk.get("i")))
        except (TypeError, ValueError):
            continue
    return indices

def recap_motion_dense_chunk_indices(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    gap_indices: Sequence[int],
    *,
    pad_sec: float = 24.0,
) -> list[int]:
    """Climax beats that still need a picture get a 4-frame grid in one call."""
    wanted = {int(index) for index in gap_indices}
    if not wanted:
        return []
    pad = max(0.0, float(pad_sec or 0.0))
    dense: list[int] = []
    for chunk in pack.get("chunks") or []:
        try:
            index = int(chunk.get("i"))
        except (TypeError, ValueError):
            continue
        if index not in wanted:
            continue
        if any(
            _beat_needs_visual_motion(beat)
            and float(beat.get("importance") or 0.0) >= RECAP_CLIMAX_IMPORTANCE
            for beat in _chunk_motion_beats(chunk, beats, pad_sec=pad)
        ):
            dense.append(index)
    return dense
