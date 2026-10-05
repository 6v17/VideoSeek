"""Merge / filter plan beats and slice evidence packs for match waves.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from src.services.recap_constants import MATCH_PACK_PAD_SEC
from src.services.recap_match import (
    overlap_sec,
    time_span,
    keep_chunk_for_recap,
    recap_story_window,
)
from src.services.recap_plan_gaps import opening_deadline_sec

def _beats_brief(existing: list[Mapping[str, Any]]) -> tuple[float, float, list[dict[str, Any]]]:
    first_start = 0.0
    last_end = 0.0
    brief: list[dict[str, Any]] = []
    for beat in existing:
        span = time_span(beat.get("t")) or (0.0, 0.0)
        if brief:
            first_start = min(first_start, span[0])
            last_end = max(last_end, span[1])
        else:
            first_start, last_end = span
        brief.append(
            {
                "id": beat.get("id"),
                "event": beat.get("event"),
                "t": [round(span[0], 2), round(span[1], 2)],
            }
        )
    return first_start, last_end, brief

def recap_plan_head_user_prompt(pack: Mapping[str, Any], existing: list[Mapping[str, Any]]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    first_start, _last_end, brief = _beats_brief(existing)
    until = min(duration, max(opening_deadline_sec(duration), first_start))
    return (
        f"原片时长 {duration:.0f} 秒。已有 beats 最早从 {first_start:.0f} 秒才开始。\n"
        f"只规划 0 秒到 {until:.0f} 秒的开场 2–5 条 beats：冷开场（如有）+ 片头曲之后第一场及紧随推进。\n"
        "密稿供用户删减，开场因果宁可多一条。沿用或补全 people 稳定称呼。不要 OP/片头曲/歌词/标题动画，不要重复下面 already。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "until_sec": round(until, 2),
                "people": pack.get("people") or [],
                "already": brief,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )

def recap_plan_tail_user_prompt(pack: Mapping[str, Any], existing: list[Mapping[str, Any]]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    last_end = 0.0
    brief = []
    for beat in existing:
        span = time_span(beat.get("t")) or (0.0, 0.0)
        last_end = max(last_end, span[1])
        brief.append(
            {
                "id": beat.get("id"),
                "event": beat.get("event"),
                "t": [round(span[0], 2), round(span[1], 2)],
            }
        )
    _op_start, story_end = recap_story_window(duration)
    start = min(story_end, max(0.0, last_end))
    return (
        f"原片时长 {duration:.0f} 秒。已有 beats 最晚只覆盖到 {start:.0f} 秒。\n"
        f"只规划 {start:.0f} 秒到正片结束（约 {story_end:.0f} 秒、片尾曲之前）的 2–5 条收尾 beats。\n"
        "密稿供用户删减：收束与余波要盖住。沿用或补全 people 稳定称呼。不要 ED/片尾曲/演职员表/预告，不要重复下面 already。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "from_sec": round(start, 2),
                "people": pack.get("people") or [],
                "already": brief,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )

def recap_plan_gap_user_prompt(
    pack: Mapping[str, Any],
    existing: list[Mapping[str, Any]],
    gaps: Sequence[tuple[float, float]],
) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    _first, _last, brief = _beats_brief(existing)
    windows = [{"t": [round(float(lo), 2), round(float(hi), 2)]} for lo, hi in gaps]
    return (
        f"原片时长 {duration:.0f} 秒。下面 gaps 是当前要检查的正片空档。\n"
        "每个 gap 短空档补 1–2 条，长空档可到 3 条；进入/展开/落点都要盖住。t 必须落在对应 gap 内。\n"
        "若空档两端活动变了，优先补进入拍，但 gap 内对白已有的决定/结果必须写成落点，禁止丢掉收束。\n"
        "密稿供用户删减：补关键过程与对白支撑的落点；不要只钉半截，也不要拆成表情碎拍。不要重复 already，不要补纯走路气氛。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "gaps": windows,
                "already": brief,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )

def _beat_event_key(text: str) -> str:
    return re.sub(r"[\s，,。！？!?…；;：:、\"'「」『』（）()【】\[\]《》<>·\-—_]+", "", str(text or "").strip())

def _char_ngrams(text: str, size: int = 3) -> set[str]:
    body = str(text or "")
    if not body:
        return set()
    if len(body) < size:
        return {body}
    return {body[index : index + size] for index in range(len(body) - size + 1)}

def _events_near_duplicate(left: str, right: str) -> bool:
    a = _beat_event_key(left)
    b = _beat_event_key(right)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 8 and short in long:
        return True
    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio >= 0.42:
        return True
    shared4 = len(_char_ngrams(a, 4) & _char_ngrams(b, 4))
    if shared4 >= 1 and ratio >= 0.30 and min(len(a), len(b)) >= 12:
        return True
    grams_a = _char_ngrams(a)
    grams_b = _char_ngrams(b)
    if not grams_a or not grams_b:
        return False
    shared = len(grams_a & grams_b)
    return shared >= 4 and shared / float(min(len(grams_a), len(grams_b))) >= 0.55

def _span_cover_ratio(span: tuple[float, float], covers: Sequence[tuple[float, float]]) -> float:
    lo, hi = span
    width = max(hi - lo, 1e-6)
    pieces: list[tuple[float, float]] = []
    for start, end in covers:
        left = max(lo, float(start))
        right = min(hi, float(end))
        if right - left > 1e-6:
            pieces.append((left, right))
    if not pieces:
        return 0.0
    pieces.sort()
    merged = [pieces[0]]
    for start, end in pieces[1:]:
        if start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    covered = sum(end - start for start, end in merged)
    return covered / width

def _beats_time_conflict(left: tuple[float, float], right: tuple[float, float]) -> bool:
    overlap = overlap_sec(left, right)
    if overlap <= 0.05:
        return False
    left_w = max(left[1] - left[0], 0.4)
    right_w = max(right[1] - right[0], 0.4)
    return (
        overlap > 0.55 * min(left_w, right_w)
        or overlap > 0.45 * left_w
        or overlap > 0.55 * right_w
    )

def _beat_inside_windows(span: tuple[float, float], windows: Sequence[tuple[float, float]]) -> bool:
    if not windows:
        return True
    return _span_cover_ratio(span, windows) >= 0.55

def merge_story_beats(
    head: list[Mapping[str, Any]],
    tail: list[Mapping[str, Any]],
    *,
    allowed_windows: Sequence[tuple[float, float]] | None = None,
) -> list[dict[str, Any]]:
    out = [dict(item) for item in head]
    used = {int(item.get("id") or 0) for item in out}
    next_id = max(used) + 1 if used else 1
    existing_spans = [span for span in (time_span(item.get("t")) for item in out) if span]
    for raw in tail:
        item = dict(raw)
        span = time_span(item.get("t"))
        event = str(item.get("event") or "")
        if span and allowed_windows is not None and not _beat_inside_windows(span, allowed_windows):
            continue
        if span and _span_cover_ratio(span, existing_spans) >= 0.4:
            continue
        if any(_events_near_duplicate(event, str(prev.get("event") or "")) for prev in out):
            continue
        if span:
            dup = False
            for prev in out:
                prev_span = time_span(prev.get("t"))
                if prev_span and _beats_time_conflict(span, prev_span):
                    dup = True
                    break
            if dup:
                continue
        try:
            beat_id = int(item.get("id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        if beat_id in used or beat_id <= 0:
            beat_id = next_id
        item["id"] = beat_id
        used.add(beat_id)
        next_id = max(next_id, beat_id + 1)
        out.append(item)
        if span:
            existing_spans.append(span)
    out.sort(key=lambda item: ((time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)))
    return out

def filter_pack_to_spans(
    pack: Mapping[str, Any],
    windows: Sequence[tuple[float, float]],
    *,
    pad_sec: float = 20.0,
) -> dict[str, Any]:
    padded = [
        (float(lo) - float(pad_sec), float(hi) + float(pad_sec))
        for lo, hi in windows
        if float(hi) > float(lo)
    ]
    if not padded:
        out = dict(pack)
        out["chunks"] = []
        out["ocr"] = []
        return out
    chunks = []
    for item in pack.get("chunks") or []:
        span = time_span(item.get("t"))
        if span and any(overlap_sec(span, window) > 0 for window in padded):
            chunks.append(item)
    ocr = []
    for row in pack.get("ocr") or []:
        try:
            span = (float(row.get("start") or 0.0), float(row.get("end") or 0.0))
        except (TypeError, ValueError):
            continue
        if any(overlap_sec(span, window) > 0 for window in padded):
            ocr.append(row)
    out = dict(pack)
    out["chunks"] = chunks
    out["ocr"] = ocr
    return out

def filter_pack_to_span(
    pack: Mapping[str, Any],
    start_sec: float,
    end_sec: float,
    *,
    pad_sec: float = 20.0,
) -> dict[str, Any]:
    lo = float(start_sec) - float(pad_sec)
    hi = float(end_sec) + float(pad_sec)
    window = (lo, hi)
    chunks = []
    for item in pack.get("chunks") or []:
        span = time_span(item.get("t"))
        if span and overlap_sec(span, window) > 0:
            chunks.append(item)
    ocr = []
    for row in pack.get("ocr") or []:
        try:
            span = (float(row.get("start") or 0.0), float(row.get("end") or 0.0))
        except (TypeError, ValueError):
            continue
        if overlap_sec(span, window) > 0:
            ocr.append(row)
    out = dict(pack)
    out["chunks"] = chunks
    out["ocr"] = ocr
    return out

def pack_for_beats(
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]],
    *,
    pad_sec: float = MATCH_PACK_PAD_SEC,
) -> dict[str, Any]:
    starts: list[float] = []
    ends: list[float] = []
    for beat in beats:
        span = time_span(beat.get("t"))
        if not span:
            continue
        starts.append(span[0])
        ends.append(span[1])
    if not starts:
        out = dict(pack)
    else:
        out = filter_pack_to_span(pack, min(starts), max(ends), pad_sec=pad_sec)
    duration = float(pack.get("duration_sec") or 0.0)
    out["chunks"] = [item for item in (out.get("chunks") or []) if keep_chunk_for_recap(item, duration)]
    if pack.get("people") and not out.get("people"):
        out["people"] = list(pack.get("people") or [])
    return out
