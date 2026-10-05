"""Beat VO draft prompts, parse, and stamp onto cuts.

``draft_recap_vo_for_beats`` stays in the runner (LLM + test patches).
``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from src.services.recap_captions import sanitize_generic_role_labels
from src.services.recap_constants import MIN_BEAT_BUDGET_SEC
from src.services.recap_focus import (
    normalize_recap_focus,
    recap_focus_evidence_limits,
    recap_focus_vo_hint,
)
from src.services.recap_llm_json import _extract_json
from src.services.recap_match import (
    _beats_by_id,
    _evidence_for_source_span,
    _time_span,
    normalize_evidence_required,
)
from src.services.recap_spine import _DIALOGUE_OUTCOME_RE
from src.services.recap_vo_budget import (
    _clip_role,
    _looks_like_insert_cut,
    tts_char_budget,
)

_VO_LAND_HINT_RE = re.compile(
    r"(拒|答应|同意|决定|收下|推回|收束|落点|结束|算了|离去|离开|揭穿|识破|赢|输|放过|解决|成交)"
)

def _format_asr_speaker_line(item: Mapping[str, Any]) -> str:
    speaker = str(item.get("speaker") or "").strip() or "未标注说话人"
    text = str(item.get("text") or "").strip()
    if not text:
        return ""
    return f"{speaker}：{text}"

def beat_vo_drops_dialogue_land(
    beat: Mapping[str, Any],
    pack: Mapping[str, Any] | None,
) -> bool:
    """True when this beat's ASR has a spoken outcome but VO never lands it / names speakers."""
    span = _time_span(beat.get("t"))
    if not span:
        return False
    evidence = _evidence_for_source_span(
        pack,
        span[0],
        span[1],
        pad_sec=2.0,
        asr_limit=20,
        cap_limit=4,
    )
    asr = [row for row in (evidence.get("asr") or []) if isinstance(row, Mapping)]
    if not asr:
        return False
    outcomes = [row for row in asr if _DIALOGUE_OUTCOME_RE.search(str(row.get("text") or ""))]
    speakers = [
        str(row.get("speaker") or "").strip()
        for row in asr
        if str(row.get("speaker") or "").strip()
    ]
    vo = str(beat.get("vo") or "").strip()
    if not vo:
        return bool(outcomes or speakers)
    if speakers and not any(label in vo for label in speakers):
        return True
    if not outcomes:
        return False
    if _VO_LAND_HINT_RE.search(vo):
        return False
    for row in outcomes:
        matched = _DIALOGUE_OUTCOME_RE.search(str(row.get("text") or ""))
        if matched and matched.group(0) in vo:
            return False
        snippet = re.sub(r"\s+", "", str(row.get("text") or ""))[:8]
        if snippet and snippet in re.sub(r"\s+", "", vo):
            return False
    return True

def recap_vo_draft_user_prompt(
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]],
    *,
    prev_vo: str = "",
) -> str:
    focus = normalize_recap_focus(pack.get("recap_focus") if isinstance(pack, Mapping) else None)
    asr_lim, cap_lim = recap_focus_evidence_limits(focus, asr_limit=20, cap_limit=10)
    rows: list[dict[str, Any]] = []
    for beat in beats:
        if not isinstance(beat, Mapping):
            continue
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        span = _time_span(beat.get("t")) or (0.0, 0.0)
        budget = float(beat.get("budget_sec") or MIN_BEAT_BUDGET_SEC)
        evidence = _evidence_for_source_span(
            pack,
            span[0],
            span[1],
            pad_sec=2.0,
            asr_limit=asr_lim,
            cap_limit=cap_lim,
        )
        asr_rows = list(evidence.get("asr") or [])
        # Always surface speaker on the line — empty speaker field is easy for the model to ignore.
        asr_lines = [
            line
            for line in (_format_asr_speaker_line(row) for row in asr_rows if isinstance(row, Mapping))
            if line
        ]
        row: dict[str, Any] = {
            "id": beat_id,
            "event": str(beat.get("event") or "").strip()[:120],
            "needed_visual": str(beat.get("needed_visual") or "").strip()[:80],
            "importance": float(beat.get("importance") or 0.5),
            "budget_sec": round(budget, 1),
            "budget_chars": tts_char_budget(budget),
            "t": [round(span[0], 2), round(span[1], 2)],
            "asr": asr_rows,
            "asr_lines": asr_lines,
            "caps": evidence.get("caps") or [],
        }
        required = normalize_evidence_required(beat.get("evidence_required"))
        if required:
            row["evidence_required"] = required
        if beat.get("outcome_forced"):
            row["must_land"] = True
        if not asr_rows and not evidence.get("caps"):
            row["hint"] = "无 asr/caps：text 必须空着"
        elif not asr_rows:
            row["hint"] = "无 asr：只写 caps 可见动作；禁止转述台词"
        else:
            speakers = sorted(
                {
                    str(item.get("speaker") or "").strip()
                    for item in asr_rows
                    if str(item.get("speaker") or "").strip()
                }
            )
            outcome_bits = [
                str(item.get("text") or "").strip()[:24]
                for item in asr_rows
                if _DIALOGUE_OUTCOME_RE.search(str(item.get("text") or ""))
            ]
            land_note = (
                "；本窗对白已有落点（"
                + "、".join(outcome_bits[:3])
                + "）必须写进旁白最后半句，禁止丢掉收束跳下一段"
                if outcome_bits
                else "；有决定/结果必须写落点，禁止进门后直接下场"
            )
            speaker_note = (
                "；主语必须出现 asr_lines 里的说话人（"
                + "、".join(speakers[:6])
                + "），禁止并成「他/她」"
                if speakers
                else "；asr_lines 已标「未标注说话人」时用画面特征称呼，仍禁止并成同一个他"
            )
            row["speakers"] = speakers
            row["hint"] = (
                "先读 asr_lines（说话人：台词）理解局面再写解说；禁止他说/她表示式对白复述；禁止低头抬头抬手"
                + speaker_note
                + land_note
                + "；约 55–80% budget_chars"
            )
        rows.append(row)
    focus_line = recap_focus_vo_hint(focus)
    return (
        "按 beats 写解说草稿。事实只来自该 beat 的 asr_lines/asr/caps；event 不是证据。\n"
        "说话人非空须出现在旁白主语；对白落点写完再下场。\n"
        + focus_line
        + (f"上一句旁白：{prev_vo}\n" if str(prev_vo or "").strip() else "")
        + "\n"
        + json.dumps(
            {
                "people": pack.get("people") or [],
                "soft_focus": focus,
                "beats": rows,
            },
            ensure_ascii=False,
        )
    )

def parse_vo_drafts(text: str, beats: Sequence[Mapping[str, Any]] | None = None) -> dict[int, str]:
    """Map beat id → narration draft. Bad JSON yields empty map (non-fatal)."""
    try:
        payload = json.loads(_extract_json(text))
    except (json.JSONDecodeError, TypeError, ValueError, RuntimeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    items = payload.get("drafts") or payload.get("vos") or payload.get("captions") or []
    if not isinstance(items, list):
        return {}
    known: set[int] = set()
    for beat in beats or []:
        try:
            known.add(int(beat.get("id") or 0))
        except (TypeError, ValueError):
            continue
    known.discard(0)
    out: dict[int, str] = {}
    for item in items:
        if not isinstance(item, Mapping):
            continue
        try:
            beat_id = int(item.get("id") or item.get("beat_id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0 or (known and beat_id not in known):
            continue
        body = sanitize_generic_role_labels(str(item.get("text") or item.get("vo") or "").strip())
        out[beat_id] = body
    return out

def stamp_beat_vo_onto_cuts(
    cuts: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Put each beat.vo on the first primary cut of that beat; clear child VO slots."""
    out = [dict(clip) for clip in cuts or []]
    if not out or not beats:
        return out
    by_id = _beats_by_id(beats)
    seen: set[int] = set()
    for clip in out:
        try:
            beat_id = int(clip.get("beat_id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        body = str((by_id.get(beat_id) or {}).get("vo") or "").strip()
        if not body:
            continue
        role = _clip_role(clip) or ("insert" if _looks_like_insert_cut(clip) else "")
        if role in {"insert", "bridge", "vo_hold"}:
            clip["vo"] = ""
            clip["vo_draft"] = ""
            continue
        if beat_id in seen:
            clip["vo"] = ""
            clip["vo_draft"] = ""
            continue
        clip["vo"] = body
        clip["vo_draft"] = body
        seen.add(beat_id)
    return out
