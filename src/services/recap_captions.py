"""Caption packing and VO/picture span helpers for the recap job.

LLM caption rewrite / polish / gap-fill stay in ``recap_service``. This module
owns the deterministic pack/apply math. ``recap_service`` re-exports the public
names for existing callers.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    CAPTION_CLIPS_PER_WAVE,
    MIN_STANDALONE_CLIP_SEC,
)
from src.services.recap_match import is_bridge_clip
from src.services.recap_vo_budget import (
    _caption_clip_sec,
    _join_vo,
    looks_like_insert_cut,
    _max_picture_for_vo,
    _normalize_vo_key,
    _vo_covers,
    _vo_needs_more_picture,
    _vo_underfills_picture,
)

def split_clips_for_captions(
    clips: Sequence[Mapping[str, Any]],
    *,
    per_wave: int = CAPTION_CLIPS_PER_WAVE,
) -> list[list[dict[str, Any]]]:
    """Pack caption waves by consecutive beat_id so one story beat stays in one LLM call."""
    items = [dict(clip) for clip in clips]
    size = max(1, int(per_wave or CAPTION_CLIPS_PER_WAVE))
    if len(items) <= size:
        return [items] if items else []

    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_beat: Any = object()
    for clip in items:
        beat_id = clip.get("beat_id")
        if current and beat_id != current_beat:
            groups.append(current)
            current = []
        current.append(clip)
        current_beat = beat_id
    if current:
        groups.append(current)

    waves: list[list[dict[str, Any]]] = []
    wave: list[dict[str, Any]] = []
    for group in groups:
        if len(group) > size:
            if wave:
                waves.append(wave)
                wave = []
            for index in range(0, len(group), size):
                waves.append(group[index : index + size])
            continue
        if wave and len(wave) + len(group) > size:
            waves.append(wave)
            wave = []
        wave.extend(group)
    if wave:
        waves.append(wave)
    return waves

def sanitize_generic_role_labels(text: str) -> str:
    """Identity: story wording is left to LLM stages, not code patches."""
    return str(text or "")

def _clip_vo_text(clip: Mapping[str, Any], *, use_draft: bool = False) -> str:
    if use_draft:
        return str(clip.get("vo_draft") or clip.get("vo") or "").strip()
    return str(clip.get("vo") or clip.get("vo_draft") or "").strip()

def _fold_short_captions(
    captions: Sequence[Mapping[str, Any]],
    clips: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Join flash-length captions into the previous (or next) line instead of chopping them."""
    items = [dict(cap) for cap in captions if str(cap.get("text") or "").strip()]
    if len(items) < 2:
        return items

    def _dur(cap: Mapping[str, Any]) -> float:
        return max(0.0, float(cap.get("tl_out") or 0.0) - float(cap.get("tl_in") or 0.0))

    def _is_insert_cap(cap: Mapping[str, Any]) -> bool:
        if not clips:
            return False
        try:
            start = int(cap.get("from") or 1) - 1
            end = int(cap.get("to") or start + 1) - 1
        except (TypeError, ValueError):
            return False
        if start < 0 or end >= len(clips) or start > end:
            return False
        return all(looks_like_insert_cut(clips[index]) for index in range(start, end + 1))

    out: list[dict[str, Any]] = [items[0]]
    for cap in items[1:]:
        if _dur(cap) < MIN_STANDALONE_CLIP_SEC and not _is_insert_cap(cap):
            prev = out[-1]
            prev["text"] = _join_vo(str(prev.get("text") or ""), str(cap.get("text") or ""))
            prev["to"] = cap.get("to", prev.get("to"))
            prev["tl_out"] = round(float(cap.get("tl_out") or prev.get("tl_out") or 0.0), 3)
            continue
        out.append(cap)
    if len(out) >= 2 and _dur(out[0]) < MIN_STANDALONE_CLIP_SEC and not _is_insert_cap(out[0]):
        head, nxt = out[0], out[1]
        nxt["text"] = _join_vo(str(head.get("text") or ""), str(nxt.get("text") or ""))
        nxt["from"] = head.get("from", nxt.get("from"))
        nxt["tl_in"] = round(float(head.get("tl_in") or nxt.get("tl_in") or 0.0), 3)
        out = [nxt, *out[2:]]
    return out

def pack_captions_for_tts(
    clips: Sequence[Mapping[str, Any]],
    *,
    use_draft: bool = False,
) -> list[dict[str, Any]]:
    """Keep VO on its own shot.

    Later empty same-beat cuts are covered only while this line still overflows
    ~87% of the picture it already has. Distinct VO shots keep their own caption
    unless a line is shorter than MIN_STANDALONE_CLIP_SEC; those fold into a neighbor
    instead of becoming a chopped flash subtitle.
    """
    items = list(clips or [])
    if not items:
        return []
    captions: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        text = _clip_vo_text(items[index], use_draft=use_draft)
        if not text:
            index += 1
            continue
        beat_id = items[index].get("beat_id")
        start_i = index
        end_i = index
        covered = _caption_clip_sec(items[index])
        cursor = index + 1
        while cursor < len(items):
            nxt_beat = items[cursor].get("beat_id")
            if beat_id is not None and nxt_beat is not None and nxt_beat != beat_id:
                break
            nxt_vo = _clip_vo_text(items[cursor], use_draft=use_draft)
            if nxt_vo:
                if _vo_covers(text, nxt_vo):
                    covered += _caption_clip_sec(items[cursor])
                    end_i = cursor
                    cursor += 1
                    continue
                if _vo_covers(nxt_vo, text):
                    text = nxt_vo
                    covered += _caption_clip_sec(items[cursor])
                    end_i = cursor
                    cursor += 1
                    continue
                break
            if looks_like_insert_cut(items[cursor]):
                break
            if not _vo_needs_more_picture(text, covered):
                break
            covered += _caption_clip_sec(items[cursor])
            end_i = cursor
            cursor += 1
        start = float(items[start_i].get("tl_in") or 0.0)
        end = float(items[end_i].get("tl_out") or 0.0)
        if end <= start + 0.04:
            index = end_i + 1
            continue
        if text:
            captions.append(
                {
                    "text": text,
                    "from": start_i + 1,
                    "to": end_i + 1,
                    "tl_in": round(start, 3),
                    "tl_out": round(end, 3),
                }
            )
        index = end_i + 1
    return _fold_short_captions(captions, items)

def normalize_caption_cues(
    raw: Sequence[Mapping[str, Any]],
    clips: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    items = list(clips or [])
    if not items:
        return []
    out: list[dict[str, Any]] = []
    last_end = -1
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        body = str(item.get("text") or item.get("vo") or "").strip()
        if not body:
            continue
        start_i, end_i = _caption_index_span(item, items)
        if start_i is None:
            continue
        start_i = max(last_end + 1, start_i)
        if start_i >= len(items):
            continue
        end_i = min(max(start_i, end_i if end_i is not None else start_i), len(items) - 1)
        # Same-beat mainline may span; stop before a different beat or a voiced insert.
        beat_id = items[start_i].get("beat_id")
        stop = start_i
        for index in range(start_i, end_i + 1):
            if beat_id is not None and items[index].get("beat_id") != beat_id:
                break
            if index > start_i and looks_like_insert_cut(items[index]):
                break
            if index > start_i and is_bridge_clip(items[index]):
                break
            stop = index
        end_i = stop
        start = float(items[start_i].get("tl_in") or 0.0)
        end = float(items[end_i].get("tl_out") or 0.0)
        clamped = clamp_caption_spans_to_vo(
            [
                {
                    "text": body,
                    "from": start_i + 1,
                    "to": end_i + 1,
                    "tl_in": round(start, 3),
                    "tl_out": round(end, 3),
                }
            ],
            items,
        )
        if not clamped:
            continue
        row = clamped[0]
        out.append(row)
        last_end = int(row["to"]) - 1
    if not out:
        raise RuntimeError("LLM 字幕没有可用条目。")
    return out

def clamp_caption_spans_to_vo(
    captions: Sequence[Mapping[str, Any]],
    clips: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Shrink caption spans so short VO cannot pretend to cover long stretches of picture."""
    items = list(clips or [])
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for cap in captions:
        if not isinstance(cap, Mapping):
            continue
        text = str(cap.get("text") or "").strip()
        if not text:
            continue
        start_i, end_i = _caption_index_span(cap, items)
        if start_i is None:
            continue
        end_i = min(max(start_i, end_i), len(items) - 1)
        budget = _max_picture_for_vo(text)
        if budget <= 0:
            continue
        covered = 0.0
        stop = start_i
        for index in range(start_i, end_i + 1):
            covered += _caption_clip_sec(items[index])
            stop = index
            if covered >= budget - 0.05:
                break
        start = float(items[start_i].get("tl_in") or 0.0)
        full_end = float(items[stop].get("tl_out") or 0.0)
        if stop == start_i and _caption_clip_sec(items[start_i]) > budget + 0.15:
            end = min(full_end, start + budget)
        else:
            end = full_end
        if end <= start + 0.04:
            continue
        out.append(
            {
                "text": text,
                "from": start_i + 1,
                "to": stop + 1,
                "tl_in": round(start, 3),
                "tl_out": round(end, 3),
            }
        )
    return out

def _caption_index_span(
    item: Mapping[str, Any],
    clips: Sequence[Mapping[str, Any]],
) -> tuple[int | None, int]:
    count = len(clips)
    from_raw = item.get("from", item.get("clip_from"))
    to_raw = item.get("to", item.get("clip_to", from_raw))
    try:
        start_i = int(from_raw) - 1
        end_i = int(to_raw) - 1
    except (TypeError, ValueError):
        start_i = None
        end_i = -1
    if start_i is not None and 0 <= start_i < count:
        end_i = min(max(start_i, end_i), count - 1)
        return start_i, end_i
    try:
        tl_in = float(item.get("tl_in"))
        tl_out = float(item.get("tl_out"))
    except (TypeError, ValueError):
        return None, -1
    overlapping = [
        index
        for index, clip in enumerate(clips)
        if not (
            float(clip.get("tl_out") or 0.0) <= tl_in + 0.04
            or float(clip.get("tl_in") or 0.0) >= tl_out - 0.04
        )
    ]
    if not overlapping:
        return None, -1
    return overlapping[0], overlapping[-1]

def apply_caption_cues(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(clip) for clip in clips]
    for clip in out:
        clip.setdefault("vo_draft", str(clip.get("vo_draft") or clip.get("vo") or "").strip())
        clip["vo"] = ""
        clip.pop("vo_tl_in", None)
        clip.pop("vo_tl_out", None)
    for cap in captions:
        start_i, end_i = _caption_index_span(cap, out)
        if start_i is None:
            continue
        text = sanitize_generic_role_labels(str(cap.get("text") or "").strip())
        if not text:
            continue
        out[start_i]["vo"] = text
        start = float(out[start_i].get("tl_in") or 0.0)
        end = float(out[end_i].get("tl_out") or 0.0)
        if cap.get("tl_in") is not None:
            start = float(cap["tl_in"])
        if cap.get("tl_out") is not None:
            end = float(cap["tl_out"])
        # Keep subtitle window near speaking time across the spanned clips.
        speak_picture = _max_picture_for_vo(text)
        if speak_picture > 0:
            end = min(end, start + max(speak_picture, 0.5))
        span_end = float(out[end_i].get("tl_out") or end)
        end = min(end, span_end)
        if end > start + 0.04:
            out[start_i]["vo_tl_in"] = round(start, 3)
            out[start_i]["vo_tl_out"] = round(end, 3)
        for index in range(start_i + 1, end_i + 1):
            out[index]["vo"] = ""
    return out

def split_underfilled_vo_clips(
    clips: Sequence[Mapping[str, Any]],
    *,
    min_tail_sec: float = MIN_STANDALONE_CLIP_SEC,
) -> list[dict[str, Any]]:
    """Split long shots whose VO is much shorter than the picture, leaving an empty tail for gap-fill."""
    out: list[dict[str, Any]] = []
    for clip in clips or []:
        row = dict(clip)
        text = str(row.get("vo") or "").strip()
        if not text or looks_like_insert_cut(row) or is_bridge_clip(row):
            out.append(row)
            continue
        picture = _caption_clip_sec(row)
        budget = _max_picture_for_vo(text)
        if budget <= 0 or not _vo_underfills_picture(text, picture):
            if text and budget > 0:
                start = float(row.get("tl_in") or 0.0)
                end = float(row.get("tl_out") or 0.0)
                vo_end = min(end, start + budget)
                if vo_end > start + 0.04:
                    row["vo_tl_in"] = round(start, 3)
                    row["vo_tl_out"] = round(vo_end, 3)
            out.append(row)
            continue
        tail = picture - budget
        if tail < float(min_tail_sec or 0.0):
            start = float(row.get("tl_in") or 0.0)
            end = float(row.get("tl_out") or 0.0)
            vo_end = min(end, start + budget)
            if vo_end > start + 0.04:
                row["vo_tl_in"] = round(start, 3)
                row["vo_tl_out"] = round(vo_end, 3)
            out.append(row)
            continue
        tl_in = float(row.get("tl_in") or 0.0)
        tl_out = float(row.get("tl_out") or 0.0)
        src_in = float(row.get("src_in") or 0.0)
        src_out = float(row.get("src_out") or 0.0)
        split_at = tl_in + budget
        ratio = budget / max(picture, 0.01)
        src_split = src_in + (src_out - src_in) * ratio
        head = dict(row)
        head["tl_out"] = round(split_at, 3)
        head["src_out"] = round(src_split, 3)
        head["duration"] = round(max(0.0, src_split - src_in), 3)
        head["vo_tl_in"] = round(tl_in, 3)
        head["vo_tl_out"] = round(split_at, 3)
        tail_clip = dict(row)
        tail_clip["tl_in"] = round(split_at, 3)
        tail_clip["tl_out"] = round(tl_out, 3)
        tail_clip["src_in"] = round(src_split, 3)
        tail_clip["src_out"] = round(src_out, 3)
        tail_clip["duration"] = round(max(0.0, src_out - src_split), 3)
        tail_clip["vo"] = ""
        if "vo_draft" in tail_clip:
            tail_clip["vo_draft"] = ""
        tail_clip.pop("vo_tl_in", None)
        tail_clip.pop("vo_tl_out", None)
        name = str(row.get("name") or "").strip()
        if name:
            tail_clip["name"] = f"{name}·续"
        out.append(head)
        out.append(tail_clip)
    return out

def _vo_restates_prior(prior: str, text: str) -> bool:
    left = str(prior or "").strip()
    right = str(text or "").strip()
    if not left or not right:
        return False
    if _vo_covers(left, right) or _vo_covers(right, left):
        return True
    a = _normalize_vo_key(left)
    b = _normalize_vo_key(right)
    if not a or not b:
        return False
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 8 and short in long:
        return True
    # Paraphrase restatement: high char-ngram overlap on short adjacent lines.
    if min(len(a), len(b)) < 10:
        return False
    size = 3
    grams_a = {a[i : i + size] for i in range(len(a) - size + 1)} or {a}
    grams_b = {b[i : i + size] for i in range(len(b) - size + 1)} or {b}
    overlap = len(grams_a & grams_b) / max(1, min(len(grams_a), len(grams_b)))
    return overlap >= 0.45

def recap_vo_coverage_ratio(clips: Sequence[Mapping[str, Any]]) -> float:
    """Share of story picture that already has narration draft/final text.

    Same-beat follow shots often keep empty ``vo`` while the head line spans them
    for TTS — count by beat (any voiced master) so cross-shot packing doesn't
    look "uncovered" and burn another caption/polish bill.
    """
    items = list(clips or [])
    if not items:
        return 1.0
    mains = [
        clip
        for clip in items
        if not looks_like_insert_cut(clip) and not is_bridge_clip(clip)
    ]
    rows = mains or items
    by_beat: dict[Any, list[Mapping[str, Any]]] = {}
    orphan: list[Mapping[str, Any]] = []
    for clip in rows:
        try:
            beat_id = int(clip.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        if beat_id > 0:
            by_beat.setdefault(beat_id, []).append(clip)
        else:
            orphan.append(clip)
    units: list[bool] = []
    for group in by_beat.values():
        units.append(
            any(str(clip.get("vo") or clip.get("vo_draft") or "").strip() for clip in group)
        )
    for clip in orphan:
        units.append(bool(str(clip.get("vo") or clip.get("vo_draft") or "").strip()))
    if not units:
        return 1.0
    return sum(1 for hit in units if hit) / float(len(units))
