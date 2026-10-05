"""VO timing / picture budget math for the recap job.

Owned here so ``recap_service`` can stay a runner. ``recap_service`` re-exports
the public names for existing callers.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    BASE_CHARS_PER_SEC,
    CHARS_PER_SEC,
    MAX_CLIP_SEC,
    MAX_TTS_CLIP_SEC,
    MAX_VO_SENTENCE_CHARS,
    MIN_CLIP_SEC,
    MIN_VO_FILL,
    TTS_SPEED,
    VO_COVER_RATIO,
    VO_FILL_RATIO,
)


def _counted_chars(text: str) -> int:
    return sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff" or ch.isalnum())


def tts_char_budget(
    duration_sec: float,
    *,
    speed: float = TTS_SPEED,
    fill_ratio: float = VO_FILL_RATIO,
) -> int:
    rate = BASE_CHARS_PER_SEC * max(0.1, float(speed or 1.0)) * max(0.1, float(fill_ratio or 1.0))
    return max(0, int(float(duration_sec or 0.0) * rate))


def vo_sec(text: str, chars_per_sec: float | None = None) -> float:
    n = _counted_chars(text)
    rate = float(chars_per_sec) if chars_per_sec is not None else CHARS_PER_SEC
    return round(n / max(0.1, rate), 2)


def vo_needed_sec(text: str) -> float:
    """Picture seconds needed to speak ``text`` at the preset TTS speed."""
    return round(vo_sec(text) / max(0.1, VO_FILL_RATIO), 2)


def _caption_clip_sec(clip: Mapping[str, Any]) -> float:
    if clip.get("tl_out") is not None and clip.get("tl_in") is not None:
        return max(0.0, float(clip["tl_out"]) - float(clip["tl_in"]))
    if clip.get("duration") is not None:
        return max(0.0, float(clip["duration"]))
    return _clip_len(clip)


def _vo_needs_more_picture(text: str, picture_sec: float) -> bool:
    """True when this line still overflows the picture it currently covers.

    A shot that is already near the fill target does not absorb later empty cuts.
    Overflow still covers later empty bridges that were added for speaking time.
    """
    picture = max(0.0, float(picture_sec or 0.0))
    need = vo_needed_sec(text)
    if picture <= 0.08:
        return need > 0.08
    return need > picture * VO_COVER_RATIO + 0.08


def _vo_underfills_picture(text: str, picture_sec: float) -> bool:
    """True when speaking time is far shorter than the picture it claims to cover."""
    picture = max(0.0, float(picture_sec or 0.0))
    speak = vo_sec(text)
    if picture <= 0.35 or speak <= 0:
        return False
    return speak < picture * MIN_VO_FILL - 0.08


def _max_picture_for_vo(text: str) -> float:
    """Picture seconds this line should cover so fill stays near the TTS target."""
    speak = vo_sec(text)
    if speak <= 0:
        return 0.0
    return round(speak / MIN_VO_FILL, 2)


def _clip_duration_for_vo(text: str) -> float:
    needed = max(MIN_CLIP_SEC, vo_sec(text) / VO_FILL_RATIO)
    return min(MAX_TTS_CLIP_SEC, needed)


def _join_vo(*parts: str) -> str:
    out = ""
    for part in parts:
        body = str(part or "").strip()
        if not body:
            continue
        if not out:
            out = body
            continue
        if _vo_covers(out, body):
            continue
        if _vo_covers(body, out):
            out = body
            continue
        if out[-1] not in "。！？!?…":
            out += "。"
        out += body
    return out


def _normalize_vo_key(text: str) -> str:
    body = re.sub(r"[\s，,。！？!?…；;：:、]+", "", str(text or "").strip())
    body = body.replace("番", "号").replace("兩", "两")
    return body


def _vo_covers(long: str, short: str) -> bool:
    a = _normalize_vo_key(long)
    b = _normalize_vo_key(short)
    return bool(a and b and (a == b or b in a))


def trim_vo_to_budget(text: str, budget: int) -> str:
    body = str(text or "").strip()
    if budget <= 0 or not body:
        return ""
    if _counted_chars(body) <= budget:
        return body
    pieces = [item for item in re.split(r"(?<=[。！？!?；;])", body) if str(item or "").strip()]
    kept: list[str] = []
    used = 0
    for piece in pieces:
        take = _counted_chars(piece)
        if kept and used + take > budget:
            break
        kept.append(piece)
        used += take
        if used >= budget:
            break
    return "".join(kept).strip() or body


def _take_vo_chars(text: str, budget: int) -> str:
    body = str(text or "").strip()
    if budget <= 0 or not body:
        return ""
    buf: list[str] = []
    count = 0
    for ch in body:
        step = 1 if ("\u4e00" <= ch <= "\u9fff" or ch.isalnum()) else 0
        if count + step > budget:
            break
        buf.append(ch)
        count += step
    return "".join(buf).strip()


def _punctuate_vo_sentence(text: str) -> str:
    body = str(text or "").strip()
    if not body:
        return ""
    if body[-1] not in "。！？!?…":
        return body + "。"
    return body


def _vo_sentence_pieces(text: str) -> list[str]:
    body = str(text or "").strip()
    if not body:
        return []
    parts = [item.strip() for item in re.split(r"(?<=[。！？!?；;])", body) if str(item or "").strip()]
    return parts or [body]


def _break_long_vo_sentence(text: str, max_chars: int = MAX_VO_SENTENCE_CHARS) -> list[str]:
    body = str(text or "").strip()
    if not body:
        return []
    if _counted_chars(body) <= max_chars:
        return [_punctuate_vo_sentence(body)]
    clauses = [item.strip() for item in re.split(r"[，、,]", body) if item.strip()]
    if len(clauses) <= 1:
        return [_punctuate_vo_sentence(_take_vo_chars(body, max_chars))]
    out: list[str] = []
    buf = ""
    for clause in clauses:
        cand = clause if not buf else f"{buf}，{clause}"
        if buf and _counted_chars(cand) > max_chars:
            out.append(_punctuate_vo_sentence(buf))
            buf = clause
            continue
        buf = cand
    if buf:
        if _counted_chars(buf) > max_chars:
            out.append(_punctuate_vo_sentence(_take_vo_chars(buf, max_chars)))
        else:
            out.append(_punctuate_vo_sentence(buf))
    return out


def tighten_vo_text(
    text: str,
    budget: int,
    *,
    max_sentence_chars: int = MAX_VO_SENTENCE_CHARS,
) -> str:
    """Keep short sentences that fit the speaking budget; drop leftover overflow."""
    body = str(text or "").strip()
    if budget <= 0 or not body:
        return ""
    sentences: list[str] = []
    for piece in _vo_sentence_pieces(body):
        sentences.extend(_break_long_vo_sentence(piece, max_sentence_chars))
    if not sentences:
        return trim_vo_to_budget(body, budget)
    kept: list[str] = []
    used = 0
    for sent in sentences:
        take = _counted_chars(sent)
        if kept and used + take > budget:
            break
        if not kept and take > budget:
            return _punctuate_vo_sentence(_take_vo_chars(sent, budget))
        kept.append(sent)
        used += take
        if used >= budget:
            break
    return "".join(kept).strip()


def _clip_len(clip: Mapping[str, Any]) -> float:
    return max(0.0, float(clip.get("src_out") or 0.0) - float(clip.get("src_in") or 0.0))


_INSERT_ROLES = {
    "insert",
    "closeup",
    "close-up",
    "cu",
    "reaction",
    "特写",
    "反应",
    "近景",
    "表情",
}
_BRIDGE_ROLES = {"bridge", "transition", "换场", "过场", "过渡"}


def _clip_role(clip: Mapping[str, Any]) -> str:
    raw = str(clip.get("role") or "").strip().lower()
    if raw in _INSERT_ROLES:
        return "insert"
    if raw in _BRIDGE_ROLES:
        return "bridge"
    return raw


def _looks_like_insert_cut(clip: Mapping[str, Any]) -> bool:
    """Only trust explicit role=insert from the match LLM."""
    return _clip_role(clip) == "insert"


def _shrink_clip(
    clip: dict[str, Any],
    extra: float,
    min_len: float = MIN_CLIP_SEC,
    *,
    from_head: bool = False,
) -> float:
    """Trim picture. ``from_head=True`` keeps the landing tail; default keeps the enter head."""
    have = _clip_len(clip)
    take = min(max(0.0, extra), max(0.0, have - min_len))
    if take <= 0.05:
        return 0.0
    src_in = float(clip.get("src_in") or 0.0)
    src_out = float(clip.get("src_out") or 0.0)
    if from_head:
        clip["src_in"] = round(src_in + take, 3)
        clip["duration"] = round(src_out - float(clip["src_in"]), 3)
    else:
        clip["src_out"] = round(src_out - take, 3)
        clip["duration"] = round(float(clip["src_out"]) - src_in, 3)
    return take


def _trim_group_to_budget(
    out: list[dict[str, Any]],
    group: list[dict[str, Any]],
    budget: float,
) -> None:
    extra = sum(_clip_len(clip) for clip in group) - budget
    if extra <= 0.25:
        return

    def _has_vo(clip: Mapping[str, Any]) -> bool:
        return bool(str(clip.get("vo") or clip.get("vo_draft") or "").strip())

    inserts = [clip for clip in group if _looks_like_insert_cut(clip)]
    masters = [clip for clip in group if clip not in inserts]
    # Never delete the first/last master — those are enter / land for the beat.
    head_id = id(masters[0]) if masters else None
    tail_id = id(masters[-1]) if masters else None
    edge_ids = {item for item in (head_id, tail_id) if item is not None}
    empties = [clip for clip in masters if not _has_vo(clip) and id(clip) not in edge_ids]
    voiced = [clip for clip in masters if _has_vo(clip)]
    # Floor for voiced masters: keep enough picture for the narration line.
    def _vo_floor(clip: Mapping[str, Any]) -> float:
        body = str(clip.get("vo") or clip.get("vo_draft") or "").strip()
        if not body:
            return MIN_CLIP_SEC
        return max(MIN_CLIP_SEC, min(MAX_CLIP_SEC, vo_needed_sec(body) * 0.85))

    # Shrink inserts first, then spare empty middles, then voiced — protect head/tail.
    for clip in inserts:
        if extra <= 0.05:
            return
        extra -= _shrink_clip(clip, extra, min_len=2.0)
    for clip in sorted(empties, key=_clip_len, reverse=True):
        if extra <= 0.05:
            return
        extra -= _shrink_clip(clip, extra, min_len=2.4)
    for clip in sorted(voiced, key=_clip_len, reverse=True):
        if extra <= 0.05:
            return
        if id(clip) in edge_ids and len(voiced) > 1:
            continue
        from_head = tail_id is not None and id(clip) == tail_id and id(clip) != head_id
        extra -= _shrink_clip(clip, extra, min_len=_vo_floor(clip), from_head=from_head)
    for clip in voiced:
        if extra <= 0.05:
            return
        if id(clip) not in edge_ids:
            continue
        from_head = tail_id is not None and id(clip) == tail_id and id(clip) != head_id
        # Never chop the sole/edge VO master below speak floor.
        extra -= _shrink_clip(clip, extra, min_len=_vo_floor(clip), from_head=from_head)
    # Still over: shrink edge masters (sole enter/land, or empty head/tail). Never delete them.
    for clip in masters:
        if extra <= 0.05:
            return
        from_head = tail_id is not None and id(clip) == tail_id and id(clip) != head_id
        floor = _vo_floor(clip) if _has_vo(clip) else MIN_CLIP_SEC
        extra -= _shrink_clip(clip, extra, min_len=floor, from_head=from_head)
    while extra > 0.25 and len(group) > 1 and empties:
        victim = max(empties, key=_clip_len)
        extra -= _clip_len(victim)
        empties.remove(victim)
        group.remove(victim)
        out.remove(victim)


trim_group_to_budget = _trim_group_to_budget


def _vo_cover_span(clips: Sequence[Mapping[str, Any]], start: int) -> tuple[float, int]:
    """Picture seconds covering this spoken line.

    Later empty same-beat shots count only while the line still overflows ~87%
    of the picture it already has, so extra B-roll is not treated as VO time.
    """
    if start < 0 or start >= len(clips):
        return 0.0, start
    head = clips[start]
    beat_id = head.get("beat_id")
    total = _clip_len(head)
    last = start
    cursor = start + 1
    vo = str(head.get("vo") or "").strip()
    while cursor < len(clips):
        nxt = clips[cursor]
        if beat_id is not None and nxt.get("beat_id") is not None and nxt.get("beat_id") != beat_id:
            break
        if str(nxt.get("vo") or "").strip():
            break
        if vo and not _vo_needs_more_picture(vo, total):
            break
        total += _clip_len(nxt)
        last = cursor
        cursor += 1
    return total, last


def _preferred_clip_vo(clip: Mapping[str, Any]) -> str:
    vo = str(clip.get("vo") or "").strip()
    draft = str(clip.get("vo_draft") or "").strip()
    if _counted_chars(draft) > _counted_chars(vo):
        return draft
    return vo


def restore_recap_vo_text(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Use the longer draft line on shots that still have VO. Leave packed empty follows empty."""
    out = [dict(clip) for clip in clips]
    for clip in out:
        if not str(clip.get("vo") or "").strip():
            continue
        text = _preferred_clip_vo(clip)
        if text:
            clip["vo"] = text
    return out


def stretch_recap_clips_for_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    media_duration: float = 0.0,
) -> list[dict[str, Any]]:
    """If this line needs more time at configured TTS speed than its shot, extend that same shot forward."""
    out = restore_recap_vo_text(clips)
    media_hi = max(0.0, float(media_duration or 0.0))
    index = 0
    while index < len(out):
        vo = str(out[index].get("vo") or "").strip()
        if not vo:
            index += 1
            continue
        need = vo_needed_sec(vo)
        have, last = _vo_cover_span(out, index)
        extra = need - have
        if extra > 0.08:
            grow = out[last]
            src_in = float(grow.get("src_in") or 0.0)
            src_out = float(grow.get("src_out") or 0.0)
            room = max(0.0, MAX_TTS_CLIP_SEC - (src_out - src_in))
            if media_hi > 0:
                room = min(room, max(0.0, media_hi - src_out))
            take = min(extra, room)
            if take > 0.05:
                grow["src_out"] = round(src_out + take, 3)
                grow["duration"] = round(float(grow["src_out"]) - src_in, 3)
        index += 1
    return out

looks_like_insert_cut = _looks_like_insert_cut
