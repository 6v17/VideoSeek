"""Match QC and shared span / evidence helpers for the recap job.

``recap_service`` re-exports these names so existing callers stay unchanged.
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any, Mapping, Sequence

from src.services.recap_constants import (
    BEAT_SRC_PAD_SEC,
    MATCH_STATUS_OK,
    MATCH_STATUS_WEAK,
    MATCH_WEAK_SCORE,
    MATCH_WEAK_SCORE_INSERT,
)
from src.services.recap_prompts import RECAP_EVIDENCE_REQUIRED_TAGS
from src.services.recap_vo_budget import _looks_like_insert_cut

_JP_KANA_RE = re.compile(r"[\u3040-\u30ff]")

_OP_ED_RE = re.compile(
    r"(片头曲|片尾曲|片頭曲|オープニング|エンディング|opening\s*theme|ending\s*theme|"
    r"作词|作曲|编曲|作詞|作曲|編曲|主题曲|主題曲|主题歌|主題歌|"
    r"演职员表|演職員表|制作委员会|製作委員会|下集预告|下一集预告|下集預告|"
    r"to\s*be\s*continued|\bending\s*credits\b)",
    re.IGNORECASE,
)


def looks_like_op_ed_text(*parts: Any) -> bool:
    body = " ".join(str(part or "") for part in parts).strip()
    if not body:
        return False
    return bool(_OP_ED_RE.search(body))


def recap_story_window(duration_sec: float) -> tuple[float, float]:
    """Keep cold open from 0. Only exclude typical ED at the tail."""
    duration = max(0.0, float(duration_sec or 0.0))
    if duration < 360:
        return 0.0, duration
    skip = 90.0 if duration >= 900 else 50.0
    end = max(30.0, duration - skip)
    return 0.0, round(end, 2)

def keep_chunk_for_recap(chunk: Mapping[str, Any], duration_sec: float) -> bool:
    if str(chunk.get("skip") or "").strip():
        return False
    span = _time_span(chunk.get("t"))
    if not span:
        return True
    _op_start, story_end = recap_story_window(duration_sec)
    if float(duration_sec or 0.0) >= 360 and span[0] >= story_end:
        return False
    return True

def _time_span(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        start = float(value[0])
        end = float(value[1])
    except (TypeError, ValueError):
        return None
    if end < start:
        start, end = end, start
    return start, end

def _overlap_sec(left: tuple[float, float], right: tuple[float, float]) -> float:
    return max(0.0, min(left[1], right[1]) - max(left[0], right[0]))

def _beats_by_id(beats: Sequence[Mapping[str, Any]] | None) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for beat in beats or []:
        if not isinstance(beat, Mapping):
            continue
        try:
            beat_id = int(beat.get("id"))
        except (TypeError, ValueError):
            continue
        if beat_id > 0:
            out[beat_id] = dict(beat)
    return out

def normalize_evidence_required(raw: Any) -> list[str]:
    """Keep Plan evidence tags in a small controlled vocabulary."""
    allowed = {tag: tag for tag in RECAP_EVIDENCE_REQUIRED_TAGS}
    aliases = {
        "角色": "人物",
        "人": "人物",
        "person": "人物",
        "people": "人物",
        "character": "人物",
        "characters": "人物",
        "行为": "动作",
        "动作结果": "动作",
        "action": "动作",
        "actions": "动作",
        "表情": "反应",
        "情绪": "反应",
        "reaction": "反应",
        "reactions": "反应",
        "道具": "物品",
        "线索": "物品",
        "信息": "物品",
        "object": "物品",
        "objects": "物品",
        "item": "物品",
        "items": "物品",
        "prop": "物品",
        "props": "物品",
        "台词": "对话",
        "对白": "对话",
        "asr": "对话",
        "dialogue": "对话",
        "dialog": "对话",
        "speech": "对话",
        "变化说明": "变化",
        "前后": "变化",
        "change": "变化",
        "changes": "变化",
        "场景": "场面",
        "换场": "场面",
        "空间": "场面",
        "scene": "场面",
        "scenes": "场面",
        "setting": "场面",
    }
    items: list[Any]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        items = re.split(r"[,，、/\s]+", text)
    elif isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        items = list(raw)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        lowered = token.lower()
        tag = allowed.get(token) or allowed.get(lowered) or aliases.get(token) or aliases.get(lowered)
        if not tag:
            haystack = lowered
            for key, value in list(allowed.items()) + list(aliases.items()):
                needle = str(key).lower()
                if needle and (needle in haystack or haystack in needle):
                    tag = value if value in allowed else allowed.get(value, value)
                    break
        if tag and tag not in allowed:
            tag = allowed.get(tag)
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
        if len(out) >= 4:
            break
    return out

def _has_japanese_kana(text: str) -> bool:
    return bool(_JP_KANA_RE.search(str(text or "")))

def _evidence_for_source_span(
    pack: Mapping[str, Any] | None,
    src_in: float,
    src_out: float,
    *,
    pad_sec: float = 1.25,
    asr_limit: int = 8,
    cap_limit: int = 6,
) -> dict[str, list[dict[str, Any]]]:
    """ASR lines + VLM caps overlapping a source span (for caption rewrite)."""
    from src.services.understanding_tags import format_motion_cap_text

    if not pack:
        return {"asr": [], "caps": []}
    try:
        start = float(src_in)
        end = float(src_out)
    except (TypeError, ValueError):
        return {"asr": [], "caps": []}
    if end < start:
        start, end = end, start
    pad = max(0.0, float(pad_sec or 0.0))
    window = (start - pad, end + pad)
    asr_rows: list[dict[str, Any]] = []
    for row in pack.get("ocr") or []:
        if not isinstance(row, Mapping):
            continue
        try:
            cue_start = float(row.get("start") or 0.0)
            cue_end = float(row.get("end") or cue_start)
        except (TypeError, ValueError):
            continue
        if _overlap_sec((cue_start, cue_end), window) <= 0.05:
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        item = {
            "t": [round(cue_start, 2), round(cue_end, 2)],
            "text": text[:100],
        }
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            item["speaker"] = speaker[:40]
        if _has_japanese_kana(text):
            # Hint for caption LLM: treat as evidence, never paste into VO.
            item["copy_ban"] = True
        asr_rows.append(item)
        if len(asr_rows) >= max(1, int(asr_limit or 8)):
            break
    cap_rows: list[dict[str, Any]] = []
    for chunk in pack.get("chunks") or []:
        if not isinstance(chunk, Mapping):
            continue
        cap = format_motion_cap_text(
            str(chunk.get("visible") or ""),
            str(chunk.get("change") or ""),
        ) or str(chunk.get("cap") or "").strip()
        if not cap:
            continue
        span = _time_span(chunk.get("t"))
        if not span or _overlap_sec(span, window) <= 0.05:
            continue
        if str(chunk.get("skip") or "").strip():
            continue
        row = {
            "i": chunk.get("i"),
            "t": [round(span[0], 2), round(span[1], 2)],
            "cap": cap[:160],
        }
        # Soft signal only — never treat as hard fact in prompts that read caps.
        inferred = str(chunk.get("inferred") or "").strip()
        try:
            weight = float(chunk.get("inferred_weight") or 0.0)
        except (TypeError, ValueError):
            weight = 0.0
        if inferred and weight >= 0.55:
            row["inferred"] = inferred[:60]
            row["inferred_weight"] = round(min(1.0, weight), 2)
        cap_rows.append(row)
        if len(cap_rows) >= max(1, int(cap_limit or 6)):
            break
    return {"asr": asr_rows, "caps": cap_rows}

def _text_similarity(left: str, right: str) -> float:
    a = str(left or "").strip()
    b = str(right or "").strip()
    if not a or not b:
        return 0.0
    ratio = float(SequenceMatcher(None, a, b).ratio())
    # CJK event↔cap often share keywords without long contiguous matches.
    a_chars = set(re.findall(r"[\u4e00-\u9fff]", a))
    b_chars = set(re.findall(r"[\u4e00-\u9fff]", b))
    if len(a_chars) >= 2 and len(b_chars) >= 2:
        inter = len(a_chars & b_chars)
        if inter:
            jaccard = inter / float(len(a_chars | b_chars))
            cover = inter / float(len(a_chars))
            ratio = max(ratio, 0.50 * jaccard + 0.50 * cover)
    return float(ratio)

def _beat_visual_anchor(beat: Mapping[str, Any] | None, clip: Mapping[str, Any] | None = None) -> str:
    beat = beat if isinstance(beat, Mapping) else {}
    clip = clip if isinstance(clip, Mapping) else {}
    parts = [
        str(clip.get("event") or beat.get("event") or "").strip(),
        str(beat.get("needed_visual") or clip.get("needed_visual") or "").strip(),
        " ".join(normalize_evidence_required(beat.get("evidence_required") or clip.get("evidence_required"))),
    ]
    return " ".join(part for part in parts if part).strip()

def _cap_match_score_for_anchor(anchor: str, cap: str, *, asr_blob: str = "") -> float:
    body = str(cap or "").strip()
    if not body:
        return 0.0
    score = _text_similarity(anchor, body)
    if asr_blob:
        score = max(score, 0.55 * score + 0.45 * _text_similarity(anchor, asr_blob))
    return float(score)

def _people_labels(people: Sequence[Mapping[str, Any]] | None) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()
    for item in people or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or item.get("name") or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        labels.append(label)
    return labels

def is_weak_match_clip(clip: Mapping[str, Any] | None) -> bool:
    if not isinstance(clip, Mapping):
        return False
    status = str(clip.get("match_status") or "").strip().lower()
    return status in {MATCH_STATUS_WEAK, "weak", "low"}

def _clamp_match_threshold(value: Any, default: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = float(default)
    return min(0.95, max(0.05, score))

def resolve_match_qc_thresholds(
    config: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Resolve Match QC thresholds from config / env; defaults stay conservative."""
    weak = float(MATCH_WEAK_SCORE)
    weak_insert = float(MATCH_WEAK_SCORE_INSERT)
    raw: Mapping[str, Any] | None = None
    if isinstance(config, Mapping):
        understanding = config.get("understanding")
        if isinstance(understanding, Mapping):
            candidate = understanding.get("recap_match_qc")
            if isinstance(candidate, Mapping):
                raw = candidate
        if raw is None:
            candidate = config.get("recap_match_qc")
            if isinstance(candidate, Mapping):
                raw = candidate
    if raw is not None:
        if raw.get("weak") is not None:
            weak = _clamp_match_threshold(raw.get("weak"), weak)
        if raw.get("weak_insert") is not None:
            weak_insert = _clamp_match_threshold(raw.get("weak_insert"), weak_insert)
    env_weak = str(os.environ.get("VIDEOSEEK_RECAP_MATCH_WEAK") or "").strip()
    env_insert = str(os.environ.get("VIDEOSEEK_RECAP_MATCH_WEAK_INSERT") or "").strip()
    if env_weak:
        weak = _clamp_match_threshold(env_weak, weak)
    if env_insert:
        weak_insert = _clamp_match_threshold(env_insert, weak_insert)
    return {"weak": round(weak, 3), "weak_insert": round(weak_insert, 3)}

def list_weak_match_beat_ids(clips: Sequence[Mapping[str, Any]] | None) -> list[int]:
    """Unique beat ids that still have at least one weak-match cut, in timeline order."""
    ordered: list[int] = []
    seen: set[int] = set()
    for clip in clips or []:
        if not is_weak_match_clip(clip):
            continue
        try:
            beat_id = int(clip.get("beat_id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0 or beat_id in seen:
            continue
        seen.add(beat_id)
        ordered.append(beat_id)
    return ordered

def score_recap_cut_match(
    clip: Mapping[str, Any],
    *,
    beat: Mapping[str, Any] | None = None,
    pack: Mapping[str, Any] | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Heuristic Match QC: refuse auto-caption when evidence is too thin."""
    limits = resolve_match_qc_thresholds(None)
    if isinstance(thresholds, Mapping):
        if thresholds.get("weak") is not None:
            limits["weak"] = _clamp_match_threshold(thresholds.get("weak"), limits["weak"])
        if thresholds.get("weak_insert") is not None:
            limits["weak_insert"] = _clamp_match_threshold(
                thresholds.get("weak_insert"),
                limits["weak_insert"],
            )
    beat = beat if isinstance(beat, Mapping) else {}
    event = str(clip.get("event") or beat.get("event") or "").strip()
    needed = str(beat.get("needed_visual") or clip.get("needed_visual") or "").strip()
    required = normalize_evidence_required(
        beat.get("evidence_required") or clip.get("evidence_required")
    )
    reason = str(clip.get("reason") or "").strip()
    evidence = _evidence_for_source_span(
        pack,
        float(clip.get("src_in") or 0.0),
        float(clip.get("src_out") or 0.0),
    )
    asr_blob = " ".join(
        f"{item.get('speaker') or ''} {item.get('text') or ''}".strip()
        for item in evidence.get("asr") or []
    ).strip()
    cap_blob = " ".join(str(item.get("cap") or "") for item in evidence.get("caps") or []).strip()
    anchor = " ".join(part for part in (event, needed, " ".join(required)) if part).strip()
    vlm_score = max(_text_similarity(anchor, cap_blob), _text_similarity(event, cap_blob))
    asr_score = max(_text_similarity(anchor, asr_blob), _text_similarity(event, asr_blob))
    reason_score = max(_text_similarity(anchor, reason), _text_similarity(event, reason))

    labels = _people_labels(people)
    if not labels:
        labels = [token for token in re.findall(r"[\u4e00-\u9fff]{2,8}", event) if token]
    # Never score character hits from the beat event itself — LLM always writes the name there.
    hay = f"{cap_blob} {asr_blob} {reason}"
    if labels:
        hits = sum(1 for label in labels if label and label in hay)
        character_score = min(1.0, hits / max(1.0, min(3.0, float(len(labels)))))
    else:
        character_score = 0.35

    has_asr = bool(asr_blob)
    has_vlm = bool(cap_blob)
    coverage = 0.0
    if required:
        met = 0
        for tag in required:
            if tag == "对话" and has_asr:
                met += 1
            elif tag in {"动作", "变化"} and has_vlm:
                met += 1
            elif tag == "场面" and (has_vlm or _looks_like_scene_shift_text(reason, cap_blob)):
                met += 1
            elif tag == "反应" and (has_vlm or _looks_like_insert_cut(clip)):
                met += 1
            elif tag == "物品" and (has_vlm or has_asr):
                met += 1
            elif tag == "人物" and character_score >= 0.34:
                met += 1
        coverage = met / float(len(required))
    elif has_asr or has_vlm:
        coverage = 0.5

    insert = _looks_like_insert_cut(clip)
    bridge = _is_bridge_clip(clip) or _looks_like_scene_shift_text(reason, event, cap_blob)
    # Reason is self-justifying Match prose — do not let it alone prove the shot.
    if has_vlm:
        visual_score = max(vlm_score, reason_score * 0.35)
    elif has_asr:
        visual_score = max(vlm_score, reason_score * 0.25, asr_score * 0.45)
    else:
        visual_score = max(vlm_score, reason_score * 0.12)

    if insert:
        total = (
            0.30 * visual_score
            + 0.32 * vlm_score
            + 0.14 * asr_score
            + 0.12 * character_score
            + 0.12 * coverage
        )
        threshold = float(limits["weak_insert"])
    elif bridge:
        total = (
            0.28 * visual_score
            + 0.30 * vlm_score
            + 0.16 * asr_score
            + 0.10 * character_score
            + 0.16 * coverage
        )
        threshold = float(limits["weak_insert"])
    else:
        total = (
            0.24 * visual_score
            + 0.34 * vlm_score
            + 0.22 * asr_score
            + 0.10 * character_score
            + 0.10 * coverage
        )
        threshold = float(limits["weak"])

    # Time alignment: wrong-act lookalikes must lose even when reason prose looks good.
    time_score = 1.0
    beat_span = _time_span(beat.get("t"))
    try:
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or 0.0)
    except (TypeError, ValueError):
        src_in, src_out = 0.0, 0.0
    if beat_span and src_out > src_in:
        pad = float(BEAT_SRC_PAD_SEC)
        expanded = (beat_span[0] - pad, beat_span[1] + pad)
        overlap = _overlap_sec((src_in, src_out), expanded)
        time_score = max(0.0, min(1.0, overlap / max(0.2, src_out - src_in)))
        total = 0.78 * total + 0.22 * time_score

    forced_weak = False
    if "弱证据" in reason:
        forced_weak = True
    # No real evidence on the span: refuse. Reason parroting the beat does not count.
    if not has_asr and not has_vlm:
        forced_weak = True
    if required and coverage < 0.34 and (not has_vlm or vlm_score < 0.22):
        forced_weak = True
    # High reason / low VLM = classic “semantic lookalike, wrong shot”.
    if reason_score >= 0.55 and vlm_score < 0.28 and asr_score < 0.28:
        forced_weak = True
    if time_score < 0.40:
        forced_weak = True
    # Better capped chunk exists in this beat → current pick is a lookalike.
    if beat_span and pack is not None and not insert:
        anchor = " ".join(part for part in (event, needed) if part).strip()
        if anchor:
            best_alt = 0.0
            duration = float(pack.get("duration_sec") or 0.0)
            for chunk in pack.get("chunks") or []:
                if not keep_chunk_for_recap(chunk, duration):
                    continue
                cap = str(chunk.get("cap") or "").strip()
                if not cap:
                    continue
                window = _time_span(chunk.get("t"))
                if not window or _overlap_sec(window, beat_span) <= 0.5:
                    continue
                best_alt = max(best_alt, _cap_match_score_for_anchor(anchor, cap))
            if best_alt >= 0.28 and vlm_score + 0.12 < best_alt:
                forced_weak = True

    status = MATCH_STATUS_WEAK if forced_weak or total < threshold else MATCH_STATUS_OK
    support = {
        "asr": has_asr and asr_score >= 0.18,
        "vlm": has_vlm and vlm_score >= 0.18,
        "character": character_score >= 0.34,
        "coverage": round(coverage, 3),
        "time": round(time_score, 3),
    }
    return {
        "match_score": round(float(total), 3),
        "match_status": status,
        "match_threshold": round(float(threshold), 3),
        "visual_score": round(visual_score, 3),
        "asr_score": round(asr_score, 3),
        "vlm_score": round(vlm_score, 3),
        "character_score": round(character_score, 3),
        "time_score": round(time_score, 3),
        "evidence_support": support,
    }

def annotate_recap_match_quality(
    cuts: Sequence[Mapping[str, Any]],
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    thresholds: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    limits = thresholds if isinstance(thresholds, Mapping) else resolve_match_qc_thresholds(config)
    by_id = _beats_by_id(beats)
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        row = dict(clip)
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        scored = score_recap_cut_match(
            row,
            beat=by_id.get(beat_id) or {},
            pack=pack,
            people=people,
            thresholds=limits,
        )
        row.update(scored)
        out.append(row)
    return out

def clear_vo_on_weak_matches(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deprecated no-op: weak_match is a rematch flag, not a VO wipe.

    Keeping the helper so older callers/tests stay import-safe.
    """
    return [dict(clip) for clip in clips or []]

def _looks_like_scene_shift_text(*parts: Any) -> bool:
    body = " ".join(str(part or "") for part in parts)
    return bool(
        re.search(
            r"换场|过场|过渡|赶到|赶来|离开|来到|进门|出门|转场|另一处|街道|室外|室内|回到|前往",
            body,
        )
    )

def _is_bridge_clip(clip: Mapping[str, Any]) -> bool:
    name = str(clip.get("name") or "").strip()
    reason = str(clip.get("reason") or "").strip()
    return name == "过渡" or reason == "过渡"
