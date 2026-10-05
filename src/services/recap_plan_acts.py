"""Plan-act windows, structure brief, and act user prompts.

``resolve_plan_act_windows`` / ``plan_story_beats_by_acts`` stay in the runner.
``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from src.services.recap_constants import PLAN_ACT_TARGET_SEC, RECAP_FOCUS_MODES
from src.services.recap_focus import (
    infer_recap_focus,
    normalize_recap_focus,
    recap_focus_plan_hint,
    story_silent_spans,
)
from src.services.recap_llm_json import _extract_json
from src.services.recap_match import time_span, recap_story_window
from src.services.recap_spine import (
    _DIALOGUE_OUTCOME_RE,
    build_asr_vlm_spine,
    sample_timeline_items,
)

def split_story_into_plan_acts(
    pack: Mapping[str, Any],
    *,
    target_sec: float = PLAN_ACT_TARGET_SEC,
) -> list[tuple[float, float]]:
    """Split the story window into ~7-minute acts, preferring ASR silence as cuts."""
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    width = max(0.0, story_end - story_start)
    goal = max(180.0, float(target_sec or PLAN_ACT_TARGET_SEC))
    if width <= goal * 1.25:
        return [(story_start, story_end)] if width > 1.0 else []

    cues = sorted(
        (
            (float(row.get("start") or 0.0), float(row.get("end") or 0.0))
            for row in (pack.get("ocr") or [])
            if isinstance(row, Mapping)
        ),
        key=lambda item: item[0],
    )
    cuts: list[float] = [story_start]
    cursor = story_start
    silence_need = 18.0
    for start, end in cues:
        if start < story_start or end > story_end + 1.0:
            continue
        if start - cursor >= silence_need and (start - story_start) - (cuts[-1] - story_start) >= goal * 0.55:
            if start - cuts[-1] >= goal * 0.55:
                cuts.append(start)
                cursor = end
                continue
        cursor = max(cursor, end)
    cuts.append(story_end)

    # Merge undersized tails / inflate evenly if ASR gave too few cuts.
    merged: list[tuple[float, float]] = []
    for index in range(len(cuts) - 1):
        lo, hi = cuts[index], cuts[index + 1]
        if hi - lo < 60.0 and merged:
            prev_lo, _prev_hi = merged[-1]
            merged[-1] = (prev_lo, hi)
        else:
            merged.append((lo, hi))
    if len(merged) <= 1:
        n = max(2, int(round(width / goal)))
        step = width / float(n)
        return [
            (
                story_start + index * step,
                story_end if index == n - 1 else story_start + (index + 1) * step,
            )
            for index in range(n)
        ]
    # Cap act length by splitting oversize windows evenly.
    out: list[tuple[float, float]] = []
    for lo, hi in merged:
        span = hi - lo
        if span <= goal * 1.35:
            out.append((lo, hi))
            continue
        pieces = max(2, int(round(span / goal)))
        step = span / float(pieces)
        for index in range(pieces):
            a = lo + index * step
            b = hi if index == pieces - 1 else lo + (index + 1) * step
            out.append((a, b))
    return out

def parse_soft_focus_payload(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(_extract_json(text))
    except (json.JSONDecodeError, TypeError, ValueError, RuntimeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("soft_focus") or payload.get("focus_prior") or payload.get("recap_focus")
    if isinstance(raw, Mapping):
        return dict(raw)
    mode = str(payload.get("mode") or "").strip().lower()
    if mode in RECAP_FOCUS_MODES:
        return {"mode": mode, "confidence": payload.get("confidence"), "note": payload.get("note")}
    return None

def build_plan_structure_brief(
    pack: Mapping[str, Any],
    *,
    asr_limit: int = 220,
    chunk_limit: int = 100,
) -> dict[str, Any]:
    """Compact full-story clock for the structure LLM: timeline + timestamped lines + silent spans."""
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    asr_rows: list[dict[str, Any]] = []
    for row in pack.get("ocr") or []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            continue
        if end < story_start or start > story_end:
            continue
        item = {
            "start": round(start, 2),
            "end": round(end, 2),
            "text": text[:100],
        }
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            item["speaker"] = speaker[:40]
        asr_rows.append(item)
    asr_rows = sample_timeline_items(asr_rows, max(1, int(asr_limit or 220)))
    chunk_rows: list[dict[str, Any]] = []
    for row in pack.get("chunks") or []:
        if not isinstance(row, Mapping):
            continue
        span = time_span(row.get("t"))
        if not span or span[1] < story_start or span[0] > story_end:
            continue
        if str(row.get("skip") or "").strip():
            continue
        item = {
            "i": row.get("i"),
            "t": [round(span[0], 2), round(span[1], 2)],
        }
        cap = str(row.get("cap") or "").strip()
        if cap:
            item["cap"] = cap[:80]
        chunk_rows.append(item)
    chunk_rows = sample_timeline_items(chunk_rows, max(1, int(chunk_limit or 100)))
    soft_prior = infer_recap_focus(pack)
    return {
        "duration_sec": round(duration, 2),
        "story_t": [round(story_start, 2), round(story_end, 2)],
        "people": list(pack.get("people") or [])[:16],
        "asr": asr_rows,
        "chunks": chunk_rows,
        "silent_spans": story_silent_spans(pack),
        "soft_prior": soft_prior,
        "soft_prior_note": "仅供参考；吃不准请输出 generic+低 confidence，禁止硬套。",
    }

def parse_plan_act_windows(text: str) -> list[tuple[float, float]]:
    try:
        payload = json.loads(_extract_json(text))
    except (json.JSONDecodeError, TypeError, ValueError, RuntimeError):
        return []
    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("acts") or payload.get("windows") or payload.get("acts_t") or []
    if not isinstance(raw, list):
        return []
    out: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        span = time_span(item.get("t") or item.get("window") or item.get("span"))
        if not span or span[1] - span[0] < 2.0:
            continue
        out.append((float(span[0]), float(span[1])))
    out.sort(key=lambda item: item[0])
    return out

def normalize_plan_act_windows(
    windows: Sequence[tuple[float, float]],
    *,
    story_start: float,
    story_end: float,
    goal_sec: float = PLAN_ACT_TARGET_SEC,
) -> list[tuple[float, float]]:
    """Clamp LLM act cuts to the story window, fill holes, merge crumbs, split giants."""
    lo0 = float(story_start)
    hi0 = float(story_end)
    if hi0 - lo0 < 1.0:
        return []
    goal = max(180.0, float(goal_sec or PLAN_ACT_TARGET_SEC))
    raw = [
        (max(lo0, float(lo)), min(hi0, float(hi)))
        for lo, hi in windows
        if float(hi) - float(lo) >= 2.0
    ]
    raw = [(lo, hi) for lo, hi in raw if hi > lo + 1.0]
    raw.sort(key=lambda item: item[0])
    if not raw:
        return [(round(lo0, 2), round(hi0, 2))]

    # Merge overlaps / tiny gaps.
    merged: list[tuple[float, float]] = [raw[0]]
    for lo, hi in raw[1:]:
        prev_lo, prev_hi = merged[-1]
        if lo <= prev_hi + 8.0:
            merged[-1] = (prev_lo, max(prev_hi, hi))
        else:
            merged.append((lo, hi))

    # Fill holes so acts cover the whole story clock (incl. silent picture time).
    covered: list[tuple[float, float]] = []
    cursor = lo0
    for lo, hi in merged:
        if lo > cursor + 1.0:
            covered.append((cursor, lo))
        covered.append((max(cursor, lo), hi))
        cursor = max(cursor, hi)
    if cursor < hi0 - 1.0:
        covered.append((cursor, hi0))
    if covered and covered[0][0] > lo0 + 1.0:
        covered.insert(0, (lo0, covered[0][0]))

    # Merge crumbs under 60s into neighbors.
    tightened: list[tuple[float, float]] = []
    for lo, hi in covered:
        if hi - lo < 60.0 and tightened:
            prev_lo, _prev_hi = tightened[-1]
            tightened[-1] = (prev_lo, hi)
        else:
            tightened.append((lo, hi))
    if len(tightened) >= 2 and tightened[-1][1] - tightened[-1][0] < 60.0:
        prev_lo, _ = tightened[-2]
        last_hi = tightened[-1][1]
        tightened = tightened[:-2] + [(prev_lo, last_hi)]

    out: list[tuple[float, float]] = []
    for lo, hi in tightened:
        span = hi - lo
        if span <= goal * 1.45:
            out.append((round(lo, 2), round(hi, 2)))
            continue
        pieces = max(2, int(round(span / goal)))
        step = span / float(pieces)
        for index in range(pieces):
            a = lo + index * step
            b = hi if index == pieces - 1 else lo + (index + 1) * step
            out.append((round(a, 2), round(b, 2)))
    return out or [(round(lo0, 2), round(hi0, 2))]


def clamp_beats_to_act_window(
    beats: Sequence[Mapping[str, Any]],
    window: tuple[float, float],
    *,
    pad_sec: float = 8.0,
) -> list[dict[str, Any]]:
    lo = float(window[0]) - float(pad_sec)
    hi = float(window[1]) + float(pad_sec)
    out: list[dict[str, Any]] = []
    for beat in beats or []:
        row = dict(beat)
        span = time_span(row.get("t"))
        if not span:
            continue
        if span[1] < lo or span[0] > hi:
            continue
        trimmed = (max(span[0], float(window[0])), min(span[1], float(window[1])))
        if trimmed[1] - trimmed[0] < 1.0:
            mid = 0.5 * (float(window[0]) + float(window[1]))
            trimmed = (max(float(window[0]), mid - 4.0), min(float(window[1]), mid + 4.0))
        if trimmed[1] <= trimmed[0]:
            continue
        row["t"] = [round(trimmed[0], 2), round(trimmed[1], 2)]
        out.append(row)
    return out

def recap_plan_act_user_prompt(
    pack: Mapping[str, Any],
    *,
    already: Sequence[Mapping[str, Any]] | None = None,
    act_index: int = 0,
    act_count: int = 1,
    window: tuple[float, float] | None = None,
) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    if window is None:
        spans = [
            span
            for span in (
                time_span(item.get("t"))
                for item in (pack.get("chunks") or [])
            )
            if span
        ]
        if spans:
            window = (min(s[0] for s in spans), max(s[1] for s in spans))
        else:
            window = (0.0, duration)
    lo, hi = float(window[0]), float(window[1])
    seeded = list(pack.get("people") or [])
    prior = [dict(item) for item in (already or [])][-6:]
    spine = build_asr_vlm_spine(pack)
    silent = [
        row
        for row in story_silent_spans(pack)
        if (time_span(row.get("t")) or (0.0, 0.0))[1] >= lo
        and (time_span(row.get("t")) or (0.0, 0.0))[0] <= hi
    ]
    focus = normalize_recap_focus(pack.get("recap_focus") if isinstance(pack, Mapping) else None)
    focus_line = recap_focus_plan_hint(focus)
    return (
        f"第 {act_index + 1}/{max(1, act_count)} 幕，只规划 [{lo:.0f},{hi:.0f}] 秒。\n"
        "spine 的 enter/mid/land 与 silent_spans 都要盖住；禁止只写进场或只写结果。\n"
        + focus_line
        + "有证据写够；禁止为省条数砍展开。进入→展开→本幕落点"
        + ("（可接下一幕）" if act_index + 1 < act_count else "（正片收束，勿写 ED）")
        + "。多段小剧场各自要落点；must_land 每条必须有对应 beat。\n"
        "already 承接勿重复推翻。t 贴 spine/silent；有 asr 的 spine 禁止跳过。\n"
        "importance 只调口播配额。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "act": {"index": act_index + 1, "count": act_count, "t": [round(lo, 2), round(hi, 2)]},
                "already": prior,
                "people": seeded,
                "spine": spine,
                "silent_spans": silent,
                "soft_focus": focus,
                "must_land": _must_land_cues(pack),
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )

def _must_land_cues(pack: Mapping[str, Any], *, limit: int = 24) -> list[dict[str, Any]]:
    """Spoken decisions/outcomes the act plan must land in one pass — no later gap LLM."""
    out: list[dict[str, Any]] = []
    for row in pack.get("ocr") or []:
        if not isinstance(row, Mapping):
            continue
        text = str(row.get("text") or "").strip()
        if not text or not _DIALOGUE_OUTCOME_RE.search(text):
            continue
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            continue
        item = {
            "t": [round(start, 2), round(end, 2)],
            "text": text[:80],
        }
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            item["speaker"] = speaker[:40]
        out.append(item)
        if len(out) >= max(1, int(limit or 24)):
            break
    return out
