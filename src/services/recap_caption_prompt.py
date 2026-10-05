"""Caption / gap user prompts and clip evidence rows for VO writing.

LLM orchestrators stay in the runner.
``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from src.services.recap_captions import normalize_caption_cues, pack_captions_for_tts
from src.services.recap_constants import CHARS_PER_SEC, MIN_VO_FILL, TTS_SPEED, VO_FILL_RATIO
from src.services.recap_focus import (
    normalize_recap_focus,
    recap_focus_evidence_limits,
    recap_focus_vo_hint,
)
from src.services.recap_llm_json import _loads_json_object
from src.services.recap_match import (
    _beats_by_id,
    _evidence_for_source_span,
    _looks_like_scene_shift_text,
    _time_span,
    is_weak_match_clip,
    normalize_evidence_required,
)
from src.services.recap_vo_budget import (
    _clip_role,
    _looks_like_insert_cut,
    tts_char_budget,
)

def recap_caption_user_prompt(
    clips: list[Mapping[str, Any]],
    people: Sequence[Mapping[str, Any]] | None = None,
    prev_caption: str = "",
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
) -> str:
    rows = _caption_clip_rows(clips, beats=beats, pack=pack)
    seed = pack_captions_for_tts(clips, use_draft=True)
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    has_draft = any(
        str(clip.get("vo") or clip.get("vo_draft") or "").strip() for clip in clips or []
    )
    focus = normalize_recap_focus(pack.get("recap_focus") if isinstance(pack, Mapping) else None)
    focus_line = recap_focus_vo_hint(focus)
    return (
        f"画面已锁定，本段 {total:.0f} 秒。TTS 预设 {TTS_SPEED:.2f} 倍（约 {CHARS_PER_SEC:.2f} 字/秒，fill={VO_FILL_RATIO}）。\n"
        + (
            "有草稿：只润色对齐 asr/caps，保留进入→变化→落点，禁止掐头去尾重写。\n"
            if has_draft
            else "无草稿：按 asr/caps 新写。\n"
        )
        + "同 beat_id 连续主镜合并 from→to；insert 短句或空；bridge 才真换场。\n"
        + "事实只来自 asr[]/caps[]；outline 非证据。weak_match 只写 caps 短句或空着。\n"
        + focus_line
        + "上一句旁白是接榫。只输出 captions。\n"
        + (f"上一句旁白：{prev_caption}\n" if str(prev_caption or "").strip() else "")
        + "\n"
        + json.dumps(
            {
                "people": list(people or []),
                "soft_focus": focus,
                "clips": rows,
                "seed": seed,
            },
            ensure_ascii=False,
        )
    )

def recap_gap_user_prompt(
    clips: list[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
    gap_indices: Sequence[int],
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
) -> str:
    rows = _caption_clip_rows(clips, beats=beats, pack=pack)
    gaps = [index + 1 for index in gap_indices]
    for row in rows:
        row["gap"] = int(row["i"]) in gaps
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    return (
        f"画面已锁定，成片 {total:.0f} 秒。TTS 预设 {TTS_SPEED:.2f} 倍。已有字幕不要改。\n"
        "gaps 是目前没有字幕盖住、且整段 beat 仍真空的镜头。只给真正漏解说的镜头补 fills。\n"
        "同 beat 主线已有旁白时，后续空镜留给跨镜，不要补近义复读。\n"
        "只按本镜 asr（绝对）/ caps（辅助）写；outline/event/reason 不是证据。无 asr+caps 请 skip。\n"
        "纯无信息走路可 skip；换场/过场且 gaps 点名时才补短过渡，禁止直接扔结果。\n"
        "无 asr 禁止编台词/转述；有 caps 只写可见动作。\n"
        "谁说话只看 asr[].speaker；people 未在本段 asr 证实的人名禁止使用。\n"
        "match_status=weak_match：短句场面或 skip，禁止编结果。\n"
        "禁止把两个人写成同一个他。可用男主/女主等临时称呼，有真名优先真名。\n\n"
        + json.dumps(
            {
                "people": list(people or []),
                "clips": rows,
                "captions": list(captions or []),
                "gaps": gaps,
            },
            ensure_ascii=False,
        )
    )

def _caption_visual_role(clip: Mapping[str, Any]) -> str:
    """Discrete shot role for captions. Never pass raw VLM / reason text."""
    if _looks_like_insert_cut(clip):
        return "insert"
    if _clip_role(clip) == "bridge":
        return "bridge"
    blob = f"{clip.get('name') or ''} {clip.get('reason') or ''}"
    if re.search(r"换场|过场|过渡", blob):
        return "bridge"
    return ""

def _caption_clip_rows(
    clips: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    by_id = _beats_by_id(beats)
    items = list(clips or [])
    focus = normalize_recap_focus(pack.get("recap_focus") if isinstance(pack, Mapping) else None)
    asr_main, cap_main = recap_focus_evidence_limits(focus, asr_limit=20, cap_limit=10)
    asr_ins, cap_ins = recap_focus_evidence_limits(focus, asr_limit=16, cap_limit=8)
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(items, 1):
        start = float(clip.get("tl_in") or 0.0)
        end = float(clip.get("tl_out") or 0.0)
        dur = max(0.0, end - start)
        try:
            beat_id = int(clip.get("beat_id"))
        except (TypeError, ValueError):
            beat_id = None
        beat = by_id.get(beat_id or 0) or {}
        event = str(clip.get("event") or beat.get("event") or "").strip()
        reason = str(clip.get("reason") or "").strip()
        role = _caption_visual_role(clip)
        budget = tts_char_budget(dur)
        if role == "insert":
            budget = max(4, min(budget, max(8, int(budget * 0.45))))
        row = {
            "i": index,
            "name": str(clip.get("name") or f"{index:02d}"),
            "tl": [round(start, 3), round(end, 3)],
            "src": [
                round(float(clip.get("src_in") or 0.0), 3),
                round(float(clip.get("src_out") or 0.0), 3),
            ],
            "dur": round(dur, 3),
            "budget": budget,
            "beat_id": beat_id,
            # Outline only — not factual evidence for VO.
            "outline": event,
            "outline_only": True,
        }
        if role:
            row["role"] = role
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or src_in)
        # Prefer the whole beat window so JP dialogue near the cut still reaches the writer.
        beat_span = _time_span(beat.get("t"))
        if beat_span and role not in {"insert"}:
            ev_in = min(src_in, beat_span[0])
            ev_out = max(src_out, beat_span[1])
            evidence = (
                _evidence_for_source_span(
                    pack, ev_in, ev_out, pad_sec=4.0, asr_limit=asr_main, cap_limit=cap_main
                )
                if pack is not None
                else {"asr": [], "caps": []}
            )
        else:
            evidence = (
                _evidence_for_source_span(
                    pack, src_in, src_out, pad_sec=8.0, asr_limit=asr_ins, cap_limit=cap_ins
                )
                if pack is not None
                else {"asr": [], "caps": []}
            )
        has_asr = bool(evidence.get("asr"))
        has_caps = bool(evidence.get("caps"))
        pack_known = pack is not None
        if has_asr:
            row["asr"] = evidence["asr"]
        if has_caps:
            row["caps"] = evidence["caps"]
        match_status = str(clip.get("match_status") or "").strip()
        if match_status:
            row["match_status"] = match_status
        if clip.get("match_score") is not None:
            row["match_score"] = clip.get("match_score")
        required = normalize_evidence_required(
            beat.get("evidence_required") or clip.get("evidence_required")
        )
        if required:
            row["evidence_required"] = required
        support = clip.get("evidence_support")
        if isinstance(support, Mapping):
            row["evidence_support"] = dict(support)
        cap_blob = " ".join(str(item.get("cap") or "") for item in evidence.get("caps") or [])
        need_transition = False
        if role == "bridge":
            need_transition = True
        elif role != "insert" and _looks_like_scene_shift_text(
            reason, event, cap_blob, clip.get("name")
        ):
            need_transition = True
        if pack_known and not has_asr and not has_caps:
            row["budget"] = min(int(row["budget"] or 0), 8)
            row["hint"] = "无 asr/caps：text 必须空着；禁止用 outline 编剧情/台词"
        elif need_transition:
            row["need_transition"] = True
            row["hint"] = "真换场承上启下：只用 asr/caps；禁止用 outline 编结果；禁止场面转到"
        elif is_weak_match_clip(clip):
            row["budget"] = min(int(row["budget"] or 0), max(8, int(budget * 0.45)))
            row["hint"] = "弱证据：只用 caps 短写场面或空着；禁止编台词/结果；禁止用 outline"
        elif pack_known and not has_asr:
            row["hint"] = "无 asr：只写 caps 可见动作；禁止说/告诉/宣布等转述台词；outline 非证据"
        elif role == "insert":
            row["hint"] = "同场反应短句或空着；禁止复述主事件；禁止XX说/觉得；禁止念 caps"
        else:
            row["hint"] = "同 beat 连续主镜请合并 from→to；事实只来自 asr/caps；禁止心里/觉得"
            row["min_chars"] = max(8, int(round(dur * CHARS_PER_SEC * MIN_VO_FILL)))
        rows.append(row)

    # Annotate merge spans so the LLM sees one budget for consecutive same-beat mainline.
    index = 0
    while index < len(rows):
        role = str(rows[index].get("role") or "")
        if role in {"insert", "bridge"}:
            index += 1
            continue
        beat_id = rows[index].get("beat_id")
        end = index
        total_dur = float(rows[index].get("dur") or 0.0)
        cursor = index + 1
        while cursor < len(rows):
            nxt_role = str(rows[cursor].get("role") or "")
            if nxt_role in {"insert", "bridge"}:
                break
            if beat_id is None or rows[cursor].get("beat_id") != beat_id:
                break
            total_dur += float(rows[cursor].get("dur") or 0.0)
            end = cursor
            cursor += 1
        if end > index:
            rows[index]["span_to"] = rows[end]["i"]
            # Merge evidence across the span so the caption LLM sees all asr/caps.
            span_asr: list[dict[str, Any]] = []
            span_caps: list[dict[str, Any]] = []
            seen_asr: set[str] = set()
            seen_cap: set[str] = set()
            for covered in range(index, end + 1):
                for item in rows[covered].get("asr") or []:
                    key = f"{item.get('t')}|{item.get('text')}"
                    if key in seen_asr:
                        continue
                    seen_asr.add(key)
                    span_asr.append(item)
                for item in rows[covered].get("caps") or []:
                    key = f"{item.get('i')}|{item.get('cap')}"
                    if key in seen_cap:
                        continue
                    seen_cap.add(key)
                    span_caps.append(item)
            if span_asr:
                rows[index]["asr"] = span_asr
            if span_caps:
                rows[index]["caps"] = span_caps
            has_asr = bool(span_asr)
            has_caps = bool(span_caps)
            rows[index]["budget"] = tts_char_budget(total_dur)
            if not has_asr and not has_caps:
                rows[index]["budget"] = min(int(rows[index]["budget"] or 0), 8)
                rows[index].pop("min_chars", None)
                rows[index]["hint"] = (
                    f"同 beat 主镜合并 from={rows[index]['i']} to={rows[end]['i']}；"
                    "无 asr/caps：text 必须空着；禁止用 outline 编剧情"
                )
            else:
                rows[index]["min_chars"] = max(
                    8,
                    int(round(total_dur * CHARS_PER_SEC * MIN_VO_FILL)),
                )
                rows[index]["hint"] = (
                    f"同 beat 主镜必须合并一条：from={rows[index]['i']} to={rows[end]['i']}；"
                    f"至少 {rows[index]['min_chars']} 字；事实只来自 asr/caps；禁止用 outline 编台词"
                )
            for covered in range(index + 1, end + 1):
                rows[covered]["covered_by"] = rows[index]["i"]
                rows[covered]["budget"] = 0
                rows[covered]["hint"] = f"已并进 caption from={rows[index]['i']}；本行不要单独写旁白"
        index = end + 1
    return rows

def parse_caption_cues(text: str, clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload = _loads_json_object(text)
    raw = payload.get("captions") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("LLM 没有返回 captions。")
    return normalize_caption_cues(raw, clips)
