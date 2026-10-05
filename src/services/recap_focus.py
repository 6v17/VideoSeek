"""Soft recap focus prior and silent-span clock helpers.

``recap_service`` re-exports these names. LLM parse of soft_focus stays in the runner.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from src.services.recap_constants import (
    RECAP_FOCUS_BOND,
    RECAP_FOCUS_FLEX,
    RECAP_FOCUS_GENERIC,
    RECAP_FOCUS_MODES,
    RECAP_FOCUS_ORDEAL,
    RECAP_FOCUS_SOFT_MIN,
)
from src.services.recap_match import time_span, recap_story_window

_FOCUS_FLEX_RE = re.compile(
    r"(瞧不起|废物|弱者|蝼蚁|不可能|居然|震惊|跪下|臣服|天才|碾压|秒杀|打脸|装逼|"
    r"小看|不堪一击|笑话|蝼蚁|不自量力|放马过来|受死)",
)
_FOCUS_ORDEAL_RE = re.compile(
    r"(活下去|好痛|好冷|救救|绝望|撑不住|一个人|遗弃|饿|崩溃|好累|好怕|血|"
    r"为什么.*我|孤单|死掉|撑不下去|好难受)",
)
_FOCUS_BOND_RE = re.compile(
    r"(喜欢你|保护你|跟我走|相信我|谢谢你|别死|救你|牵手|靠近|心动|"
    r"我会保护|交给我|一起走|不要离开)",
)

def story_silent_spans(
    pack: Mapping[str, Any],
    *,
    min_sec: float = 12.0,
    limit: int = 48,
) -> list[dict[str, Any]]:
    """Picture-time windows with little/no ASR — still belong on the story clock."""
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    if story_end - story_start < 1.0:
        return []
    spoken: list[tuple[float, float]] = []
    for row in pack.get("ocr") or []:
        if not isinstance(row, Mapping) or not str(row.get("text") or "").strip():
            continue
        try:
            start = float(row.get("start") or 0.0)
            end = float(row.get("end") or start)
        except (TypeError, ValueError):
            continue
        if end < story_start or start > story_end:
            continue
        spoken.append((max(story_start, start), min(story_end, end)))
    spoken.sort()
    merged: list[tuple[float, float]] = []
    for lo, hi in spoken:
        if not merged or lo > merged[-1][1] + 1.0:
            merged.append((lo, hi))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
    gaps: list[tuple[float, float]] = []
    cursor = story_start
    for lo, hi in merged:
        if lo - cursor >= float(min_sec):
            gaps.append((cursor, lo))
        cursor = max(cursor, hi)
    if story_end - cursor >= float(min_sec):
        gaps.append((cursor, story_end))
    chunks = [row for row in (pack.get("chunks") or []) if isinstance(row, Mapping)]
    out: list[dict[str, Any]] = []
    for lo, hi in gaps:
        caps: list[dict[str, Any]] = []
        for chunk in chunks:
            span = time_span(chunk.get("t"))
            if not span:
                continue
            if span[1] < lo - 1.0 or span[0] > hi + 1.0:
                continue
            cap = str(chunk.get("cap") or "").strip()
            if not cap:
                continue
            caps.append(
                {
                    "i": chunk.get("i"),
                    "t": [round(span[0], 2), round(span[1], 2)],
                    "cap": cap[:80],
                }
            )
            if len(caps) >= 4:
                break
        out.append(
            {
                "t": [round(lo, 2), round(hi, 2)],
                "kind": "no_asr",
                "caps": caps,
                "has_cap": bool(caps),
            }
        )
        if len(out) >= max(1, int(limit or 48)):
            break
    return out

def normalize_recap_focus(raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Clamp soft focus to known modes; low confidence → generic (no forced trope)."""
    item = dict(raw or {})
    mode = str(item.get("mode") or RECAP_FOCUS_GENERIC).strip().lower()
    if mode not in RECAP_FOCUS_MODES:
        mode = RECAP_FOCUS_GENERIC
    try:
        confidence = float(item.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    if confidence < RECAP_FOCUS_SOFT_MIN:
        mode = RECAP_FOCUS_GENERIC
    return {
        "mode": mode,
        "confidence": round(confidence, 3),
        "note": str(item.get("note") or "").strip()[:120],
        "active": mode != RECAP_FOCUS_GENERIC and confidence >= RECAP_FOCUS_SOFT_MIN,
    }

def infer_recap_focus(pack: Mapping[str, Any]) -> dict[str, Any]:
    """Heuristic soft prior from ASR patterns + speaker mix + silent picture share."""
    texts: list[str] = []
    speakers: set[str] = set()
    for row in pack.get("ocr") or []:
        if not isinstance(row, Mapping):
            continue
        body = str(row.get("text") or "").strip()
        if body:
            texts.append(body)
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            speakers.add(speaker)
    blob = "\n".join(texts)
    flex_hits = len(_FOCUS_FLEX_RE.findall(blob))
    ordeal_hits = len(_FOCUS_ORDEAL_RE.findall(blob))
    bond_hits = len(_FOCUS_BOND_RE.findall(blob))
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration) if duration > 1.0 else (0.0, duration)
    story_dur = max(1.0, story_end - story_start)
    silent = story_silent_spans(pack)
    silent_dur = sum(
        max(0.0, (span[1] - span[0]))
        for span in (time_span(row.get("t")) for row in silent)
        if span
    )
    silent_ratio = silent_dur / story_dur
    speaker_n = len(speakers)

    scores = {
        RECAP_FOCUS_FLEX: float(flex_hits) + (0.8 if speaker_n >= 3 else 0.0),
        RECAP_FOCUS_ORDEAL: float(ordeal_hits) + (1.2 if silent_ratio >= 0.22 and speaker_n <= 2 else 0.0),
        RECAP_FOCUS_BOND: float(bond_hits) + (0.6 if 2 <= speaker_n <= 3 else 0.0),
    }
    best_mode, best_score = max(scores.items(), key=lambda item: item[1])
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    if best_score < 2.0 or best_score < second + 1.0:
        return normalize_recap_focus(
            {"mode": RECAP_FOCUS_GENERIC, "confidence": 0.25, "note": "heuristic_unclear"}
        )
    confidence = min(0.92, 0.45 + 0.12 * best_score + 0.08 * max(0.0, best_score - second))
    note = {
        RECAP_FOCUS_FLEX: "heuristic_flex_npc_side",
        RECAP_FOCUS_ORDEAL: "heuristic_ordeal_picture",
        RECAP_FOCUS_BOND: "heuristic_bond_secondary",
    }.get(best_mode, "")
    return normalize_recap_focus({"mode": best_mode, "confidence": confidence, "note": note})

def merge_recap_focus(
    heuristic: Mapping[str, Any] | None,
    llm_focus: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Blend LLM soft_focus with heuristic; never force when both are weak."""
    base = normalize_recap_focus(heuristic)
    other = normalize_recap_focus(llm_focus) if llm_focus else normalize_recap_focus(None)
    if not other.get("active") and not base.get("active"):
        return normalize_recap_focus(
            {"mode": RECAP_FOCUS_GENERIC, "confidence": max(float(base.get("confidence") or 0.0), float(other.get("confidence") or 0.0)), "note": "soft_inactive"}
        )
    if other.get("active") and (
        not base.get("active") or float(other.get("confidence") or 0.0) >= float(base.get("confidence") or 0.0)
    ):
        note = str(other.get("note") or "") or "llm_soft_focus"
        return normalize_recap_focus(
            {"mode": other.get("mode"), "confidence": other.get("confidence"), "note": note}
        )
    return base

def recap_focus_plan_hint(focus: Mapping[str, Any] | None) -> str:
    info = normalize_recap_focus(focus)
    if not info.get("active"):
        return "【软先验】未识别套路：通用进入→展开→收束；禁止硬套标签。\n"
    mode = str(info.get("mode") or "")
    if mode == RECAP_FOCUS_FLEX:
        return (
            "【软先验·flex】材料支撑时偏：轻视→打脸→收束；多写 NPC 反应，asr 偏重。"
            "不像就退回通用。\n"
        )
    if mode == RECAP_FOCUS_ORDEAL:
        return (
            "【软先验·ordeal】材料支撑时偏：抬 silent/caps 画面权；独白与压迫场面同权。"
            "不像就退回通用。\n"
        )
    if mode == RECAP_FOCUS_BOND:
        return (
            "【软先验·bond】材料支撑时偏：盯副1态度转折；对白推关系、画面吃反应。"
            "不像就退回通用。\n"
        )
    return ""

def recap_focus_vo_hint(focus: Mapping[str, Any] | None) -> str:
    info = normalize_recap_focus(focus)
    if not info.get("active"):
        return ""
    mode = str(info.get("mode") or "")
    if mode == RECAP_FOCUS_FLEX:
        return "软写法：写清谁轻视、谁被打脸、场上结果；NPC 反应可写。\n"
    if mode == RECAP_FOCUS_ORDEAL:
        return "软写法：绝境画面与崩溃都要落到旁白；无 asr 可用 caps。\n"
    if mode == RECAP_FOCUS_BOND:
        return "软写法：副1态度怎么变、主1做了什么让局面转。\n"
    return ""

def recap_focus_evidence_limits(
    focus: Mapping[str, Any] | None,
    *,
    asr_limit: int = 20,
    cap_limit: int = 10,
) -> tuple[int, int]:
    """Soft-bias how many asr vs caps rows the LLM sees for a span (never hard-drop either)."""
    info = normalize_recap_focus(focus)
    base_asr = max(1, int(asr_limit or 20))
    base_cap = max(1, int(cap_limit or 10))
    if not info.get("active"):
        return base_asr, base_cap
    mode = str(info.get("mode") or "")
    if mode == RECAP_FOCUS_FLEX:
        # Dialogue / NPC reactions drive flex; keep caps for reaction close-ups.
        return min(36, int(round(base_asr * 1.35))), max(base_cap, int(round(base_cap * 0.9)))
    if mode == RECAP_FOCUS_ORDEAL:
        # Silent / picture pressure shares weight with ASR.
        return max(base_asr, int(round(base_asr * 0.95))), min(24, int(round(base_cap * 1.5)))
    if mode == RECAP_FOCUS_BOND:
        # Attitude turns live in dialogue; reaction faces in caps.
        return min(32, int(round(base_asr * 1.15))), min(16, int(round(base_cap * 1.2)))
    return base_asr, base_cap
