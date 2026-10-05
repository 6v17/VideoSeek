"""Normalize/parse story beats and allocate per-beat time budgets.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from src.services.recap_captions import sanitize_generic_role_labels
from src.services.recap_constants import (
    HARD_MIN_BEAT_SEC,
    MAX_BEAT_BUDGET_SEC,
    MIN_BEAT_BUDGET_SEC,
    TARGET_RECAP_SEC,
    TEXTURE_BEAT_RE,
)
from src.services.recap_llm_json import loads_json_object
from src.services.recap_match import time_span, normalize_evidence_required
from src.services.recap_plan_gaps import (
    beat_evidence_score,
    beat_evidence_sec,
    drop_op_ed_beats,
)

def normalize_story_beats(raw: Mapping[str, Any] | list[Any]) -> list[dict[str, Any]]:
    items = raw.get("beats") if isinstance(raw, Mapping) else raw
    if not isinstance(items, list) or not items:
        raise RuntimeError("LLM 没有返回剧情节拍。")
    out: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    next_id = 1
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            continue
        event = sanitize_generic_role_labels(str(item.get("event") or "").strip())
        if not event:
            continue
        try:
            importance = float(item.get("importance") or 0.5)
        except (TypeError, ValueError):
            importance = 0.5
        importance = min(1.0, max(0.05, importance))
        span = time_span(item.get("t")) or (0.0, 0.0)
        try:
            beat_id = int(item.get("id"))
        except (TypeError, ValueError):
            beat_id = index
        if beat_id in used_ids or beat_id <= 0:
            while next_id in used_ids:
                next_id += 1
            beat_id = next_id
        used_ids.add(beat_id)
        next_id = max(next_id, beat_id + 1)
        needed = sanitize_generic_role_labels(
            str(item.get("needed_visual") or item.get("needed") or "").strip()
        )[:80]
        evidence_required = normalize_evidence_required(
            item.get("evidence_required") or item.get("evidence") or item.get("needed_evidence")
        )
        if not evidence_required:
            # Legacy beats / thin LLM output: infer a minimal evidence ask from needed_visual.
            evidence_required = normalize_evidence_required(needed) or ["动作"]
        row = {
            "id": beat_id,
            "event": event[:120],
            "importance": round(importance, 3),
            "evidence_required": evidence_required,
            "needed_visual": needed,
            "t": [round(span[0], 2), round(span[1], 2)],
        }
        out.append(row)
    if not out:
        raise RuntimeError("LLM 剧情节拍没有可用条目。")
    return out

def normalize_story_people(raw: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    items = raw.get("people") if isinstance(raw, Mapping) else raw
    if not isinstance(items, list):
        return []
    bad_label = re.compile(
        r"^(npc|语气助词.*|说话人\d*|声线\d*)$|"
        r"^(ed|op|bgm)$|.*(片头曲|片尾曲|主题曲)|^ed音乐$|^op音乐$|^bgm音乐$",
        re.IGNORECASE,
    )
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(items, 1):
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()[:40]
        if not label or bad_label.match(label):
            continue
        look = str(item.get("look") or item.get("needed_visual") or "").strip()[:60]
        who_id = str(item.get("id") or f"p{index}").strip()[:16] or f"p{index}"
        if who_id in used:
            who_id = f"p{index}"
        used.add(who_id)
        out.append({"id": who_id, "label": label, "look": look})
        if len(out) >= 12:
            break
    return out

def merge_story_people(*groups: list[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    visual_nick = re.compile(
        r"(金发|蓝发|黑发|红发|白发|粉发|银发|绿发).{0,3}(青年|少女|少年|男子|女子|女孩|男孩|男人|女人)"
    )
    seeded_labels: set[str] = set()
    for index, group in enumerate(groups):
        for item in normalize_story_people({"people": list(group or [])}):
            key = str(item.get("label") or "").strip()
            if not key or key in seen:
                continue
            # Later LLM people often invent hair-color nicknames; keep dialogue names authoritative.
            if index > 0 and seeded_labels and visual_nick.fullmatch(key):
                continue
            seen.add(key)
            if index == 0:
                seeded_labels.add(key)
            merged.append(item)
    return merged

def parse_story_plan(text: str) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        payload = loads_json_object(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("语言模型返回的剧情节拍不是合法 JSON。请再生成一次。") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("LLM 输出不是 JSON 对象。")
    title = str(payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    return title, normalize_story_beats(payload), normalize_story_people(payload)

def parse_story_beats(text: str) -> tuple[str, list[dict[str, Any]]]:
    title, beats, _people = parse_story_plan(text)
    del _people
    return title, beats

def allocate_beat_budgets(
    beats: list[Mapping[str, Any]],
    *,
    chunks: list[Mapping[str, Any]] | None = None,
    target_sec: float = TARGET_RECAP_SEC,
    duration_sec: float = 0.0,
) -> list[dict[str, Any]]:
    """Keep every planned beat and scale quotas so each beat has room near target_sec."""
    items = drop_op_ed_beats(beats, duration_sec)
    if not items:
        raise RuntimeError("没有可分配的剧情节拍。")
    chunk_list = list(chunks or [])
    scored: list[tuple[dict[str, Any], float, float]] = []
    for beat in items:
        evidence = beat_evidence_sec(beat, chunk_list)
        evid_score = beat_evidence_score(evidence)
        importance = float(beat.get("importance") or 0.5)
        span = time_span(beat.get("t")) or (0.0, 0.0)
        span_dur = max(0.0, span[1] - span[0])
        # High-importance beats: don't let thin/short source windows tank quota.
        if importance >= 0.8 and evid_score > 0.0:
            evid_score = max(evid_score, 0.75)
        weight = importance * (0.35 + 0.65 * evid_score)
        if importance >= 0.8:
            weight = max(weight, importance * 0.72)
        if importance >= 0.75 and span_dur <= 24.0:
            weight = max(weight, importance * 0.85)
        if importance >= 0.85 and span_dur <= 12.0:
            weight = max(weight, importance * 0.92)
        # Shared-clock evidence beats must not starve because LLM set low importance.
        if beat.get("spine_forced") or evid_score >= 0.35 or span_dur >= 10.0:
            weight = max(weight, 0.48)
        scored.append((dict(beat), evidence, weight))
    budgets = _fit_budgets_to_target(
        [item[2] for item in scored],
        float(target_sec or TARGET_RECAP_SEC),
    )
    allocated: list[dict[str, Any]] = []
    for (beat, evidence, weight), budget in zip(scored, budgets):
        out = dict(beat)
        out["evidence_sec"] = round(evidence, 2)
        out["weight"] = round(weight, 4)
        out["budget_sec"] = budget
        importance = float(out.get("importance") or 0.5)
        event = str(out.get("event") or "")
        # Enter→land needs ≥2 masters; climax beats often need a third beat of reaction.
        min_shots = 2
        if importance < 0.22 and not TEXTURE_BEAT_RE.search(event):
            min_shots = 1
        if importance >= 0.75:
            min_shots = 3
        if any(token in event for token in ("进入", "赶到", "走进", "离开", "收束", "结局", "落点", "余波")):
            min_shots = max(min_shots, 2)
        out["shots"] = min(5, max(min_shots, int(round(budget / 5.5))))
        if str(beat.get("vo") or "").strip():
            out["vo"] = str(beat.get("vo") or "").strip()
        allocated.append(out)
    allocated.sort(key=lambda item: ((item.get("t") or [0.0, 0.0])[0], int(item.get("id") or 0)))
    return allocated

def _fit_budgets_to_target(
    weights: Sequence[float],
    target_sec: float,
    *,
    min_sec: float = MIN_BEAT_BUDGET_SEC,
    max_sec: float = MAX_BEAT_BUDGET_SEC,
) -> list[float]:
    """Assign per-beat quotas up to ``target_sec`` by plot weight.

    Quotas themselves may fill the target so each beat has room for enter→land
    shots. Actual picture must not be padded just to spend leftover seconds
    (see ``apply_recap_duration`` trim-only).
    """
    n = len(weights)
    if n <= 0:
        return []
    target = max(n * HARD_MIN_BEAT_SEC, float(target_sec or TARGET_RECAP_SEC))
    floor = float(min_sec)
    if n * floor > target:
        floor = max(HARD_MIN_BEAT_SEC, target / n)
    cap = max(floor, float(max_sec))
    remaining = max(0.0, target - n * floor)
    wsum = sum(max(0.05, float(weight or 0.0)) for weight in weights) or float(n)
    budgets = [
        min(cap, floor + remaining * (max(0.05, float(weight or 0.0)) / wsum))
        for weight in weights
    ]
    for _ in range(8):
        total = sum(budgets)
        diff = target - total
        if abs(diff) < 0.2:
            break
        if diff > 0:
            room = [max(0.0, cap - item) for item in budgets]
            rsum = sum(room)
            if rsum <= 0.05:
                break
            budgets = [item + diff * (slot / rsum) for item, slot in zip(budgets, room)]
        else:
            slack = [max(0.0, item - floor) for item in budgets]
            ssum = sum(slack)
            if ssum <= 0.05:
                break
            budgets = [item + diff * (slot / ssum) for item, slot in zip(budgets, slack)]
    return [round(min(cap, max(floor, item)), 1) for item in budgets]
