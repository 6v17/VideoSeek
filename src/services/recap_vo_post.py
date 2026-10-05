"""VO polish / gap-fill helpers and retired no-op scrub stages.

``polish_recap_vo`` / ``fill_recap_vo_gaps`` / ``fit_recap_captions_to_tts`` stay
in the runner. ``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from src.services.recap_caption_prompt import _caption_visual_role
from src.services.recap_captions import (
    _caption_index_span,
    pack_captions_for_tts,
    sanitize_generic_role_labels,
)
from src.services.recap_constants import CHARS_PER_SEC, MIN_STANDALONE_CLIP_SEC, MIN_VO_FILL
from src.services.recap_llm_json import _loads_json_object
from src.services.recap_match import (
    _evidence_for_source_span,
    _is_bridge_clip,
    _people_labels,
)
from src.services.recap_vo_budget import (
    _caption_clip_sec,
    looks_like_insert_cut,
    _max_picture_for_vo,
    _vo_covers,
    tts_char_budget,
)

def clamp_recap_vo_to_picture(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep match VO intact. Fitting length is the captions LLM pass."""
    return [dict(clip) for clip in clips or []]

def fit_recap_vo_picture(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep match VO intact. Fitting length is the captions LLM pass."""
    return [dict(clip) for clip in clips or []]

def scrub_generic_role_labels_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: label cleanup belongs in LLM prompts, not post-processing."""
    return [dict(clip) for clip in clips or []]

def _fallback_role_for_unattested_name(event: str = "", vo: str = "", *, replaced: str = "") -> str:
    del event, vo, replaced
    return "对方"

def attested_people_labels_for_span(
    pack: Mapping[str, Any] | None,
    src_in: float,
    src_out: float,
    people: Sequence[Mapping[str, Any]] | None,
    *,
    event: str = "",
    pad_sec: float = 2.0,
) -> set[str]:
    """People labels proved by ASR speaker/text (or already present in the beat event)."""
    labels = _people_labels(people)
    attested: set[str] = set()
    event_body = str(event or "")
    for label in labels:
        if label and label in event_body:
            attested.add(label)
    evidence = _evidence_for_source_span(
        pack,
        float(src_in or 0.0),
        float(src_out or 0.0),
        pad_sec=pad_sec,
        asr_limit=16,
        cap_limit=1,
    )
    for row in evidence.get("asr") or []:
        if not isinstance(row, Mapping):
            continue
        speaker = str(row.get("speaker") or "").strip()
        if speaker:
            attested.add(speaker)
        text = str(row.get("text") or "")
        for label in labels:
            if label and label in text:
                attested.add(label)
    return attested

def scrub_unattested_people_names(
    clips: Sequence[Mapping[str, Any]],
    *,
    people: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """No-op: unattested-name rewriting was a story patch."""
    del people, pack, beats
    return [dict(clip) for clip in clips or []]

def merge_same_beat_mainline_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: spanning VO is the caption/polish LLM's job."""
    return [dict(clip) for clip in clips or []]

def clear_redundant_insert_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: insert restatement cleanup belongs in LLM stages."""
    return [dict(clip) for clip in clips or []]

def finalize_recap_vo_density(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op: keep LLM output as-is."""
    return [dict(clip) for clip in clips or []]

def scrub_intra_line_duplicate_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]

def recap_vo_polish_user_prompt(
    clips: Sequence[Mapping[str, Any]],
    *,
    people: Sequence[Mapping[str, Any]] | None = None,
    prev_caption: str = "",
) -> str:
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(clips, 1):
        dur = _caption_clip_sec(clip)
        vo = str(clip.get("vo") or "").strip()
        role = _caption_visual_role(clip) or "main"
        row: dict[str, Any] = {
            "i": index,
            "beat_id": clip.get("beat_id"),
            "role": role,
            "dur": round(dur, 3),
            "vo": vo,
            "budget": tts_char_budget(dur),
        }
        if vo:
            row["min_chars"] = max(8, int(round(dur * CHARS_PER_SEC * MIN_VO_FILL)))
        rows.append(row)
    total = sum(float(row.get("dur") or 0.0) for row in rows)
    return (
        f"画面已锁定，本段 {total:.0f} 秒。只润色旁白，不要改镜头。\n"
        "合并近义复读与句内重复，修好病句；可跨同 beat 空镜收成 from→to。\n"
        "不要发明新事实，不要给空镜硬编查漏。初稿偏密可以，方便用户删。\n"
        "没改动的句子也可重新输出以确认；未提到的 i 保持原文。\n"
        + (f"上一句旁白：{prev_caption}\n" if str(prev_caption or "").strip() else "")
        + "\n"
        + json.dumps({"people": list(people or []), "clips": rows}, ensure_ascii=False)
    )

def parse_vo_polish_cues(
    text: str,
    clips: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Parse polish edits; empty text is kept so duplicate lines can be cleared."""
    payload = _loads_json_object(text)
    raw = payload.get("captions") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        raise RuntimeError("LLM 没有返回润色 captions。")
    items = list(clips or [])
    if not items:
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        if "text" not in item and "vo" not in item:
            continue
        body = sanitize_generic_role_labels(str(item.get("text") if "text" in item else item.get("vo") or "").strip())
        start_i, end_i = _caption_index_span(item, items)
        if start_i is None:
            continue
        end_i = min(max(start_i, end_i if end_i is not None else start_i), len(items) - 1)
        out.append(
            {
                "text": body,
                "from": start_i + 1,
                "to": end_i + 1,
            }
        )
    return out

def apply_vo_polish_cues(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Apply polish edits without wiping clips the model did not mention."""
    out = [dict(clip) for clip in clips]
    if not captions:
        return out
    planned: list[tuple[int, int, str]] = []
    touched: set[int] = set()
    for cap in captions:
        if not isinstance(cap, Mapping):
            continue
        start_i, end_i = _caption_index_span(cap, out)
        if start_i is None:
            continue
        end_i = min(max(start_i, end_i), len(out) - 1)
        text = sanitize_generic_role_labels(str(cap.get("text") or "").strip())
        planned.append((start_i, end_i, text))
        for index in range(start_i, end_i + 1):
            touched.add(index)
    for index in touched:
        out[index]["vo"] = ""
        out[index].pop("vo_tl_in", None)
        out[index].pop("vo_tl_out", None)
    for start_i, end_i, text in planned:
        if not text:
            continue
        out[start_i]["vo"] = text
        start = float(out[start_i].get("tl_in") or 0.0)
        end = float(out[end_i].get("tl_out") or start)
        speak_picture = _max_picture_for_vo(text)
        if speak_picture > 0:
            end = min(end, start + max(speak_picture, 0.5))
        if end > start + 0.04:
            out[start_i]["vo_tl_in"] = round(start, 3)
            out[start_i]["vo_tl_out"] = round(end, 3)
    return out

def scrub_adjacent_duplicate_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]

def scrub_restated_insert_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]

def recap_gap_clip_indices(
    clips: Sequence[Mapping[str, Any]],
    captions: Sequence[Mapping[str, Any]] | None = None,
) -> list[int]:
    """True story holes only — not same-beat follow shots reserved for cross-shot VO."""
    items = list(clips or [])
    caps = list(captions if captions is not None else pack_captions_for_tts(items))
    covered: set[int] = set()
    for cap in caps:
        start_i, end_i = _caption_index_span(cap, items)
        if start_i is None:
            continue
        for index in range(start_i, min(end_i, len(items) - 1) + 1):
            covered.add(index)
    beat_has_main_vo: set[Any] = set()
    for clip in items:
        if looks_like_insert_cut(clip) or _is_bridge_clip(clip):
            continue
        if str(clip.get("vo") or "").strip():
            beat_has_main_vo.add(clip.get("beat_id"))
    gaps: list[int] = []
    for index, clip in enumerate(items):
        if index in covered or _is_bridge_clip(clip):
            continue
        if str(clip.get("vo") or "").strip():
            continue
        if _caption_clip_sec(clip) < 1.6:
            continue
        beat_id = clip.get("beat_id")
        # Same-beat follow / insert after a voiced main: keep empty so prior VO can span.
        if beat_id is not None and beat_id in beat_has_main_vo:
            continue
        # Same-beat earlier clip already has VO: not a story hole.
        if beat_id is not None and any(
            str(items[pos].get("vo") or "").strip() and items[pos].get("beat_id") == beat_id
            for pos in range(index)
        ):
            continue
        gaps.append(index)
    return gaps

def parse_gap_fills(
    text: str,
    clips: Sequence[Mapping[str, Any]],
    *,
    allowed: set[int] | None = None,
) -> list[dict[str, Any]]:
    payload = _loads_json_object(text)
    raw = payload.get("fills") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list):
        raise RuntimeError("LLM 没有返回 fills。")
    if not raw:
        return []
    items = list(clips or [])
    fills: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        skip = item.get("skip")
        if skip in (True, "true", "True", 1, "1"):
            continue
        try:
            index = int(item.get("i") or item.get("from") or 0) - 1
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(items):
            continue
        if allowed is not None and index not in allowed:
            continue
        if str(items[index].get("vo") or "").strip():
            continue
        body = str(item.get("text") or item.get("vo") or "").strip()
        if not body:
            continue
        picture = _caption_clip_sec(items[index])
        if picture < MIN_STANDALONE_CLIP_SEC and not looks_like_insert_cut(items[index]):
            continue
        if picture < 1.6:
            continue
        prev = ""
        nxt = ""
        if index > 0:
            prev = str(items[index - 1].get("vo") or items[index - 1].get("vo_draft") or "").strip()
        if index + 1 < len(items):
            nxt = str(items[index + 1].get("vo") or items[index + 1].get("vo_draft") or "").strip()
        if prev and _vo_covers(prev, body):
            continue
        if nxt and _vo_covers(nxt, body):
            continue
        fills.append({"index": index, "text": body})
    return fills

def apply_gap_fills(
    clips: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out = [dict(clip) for clip in clips]
    for fill in fills:
        try:
            index = int(fill.get("index"))
        except (TypeError, ValueError):
            continue
        if index < 0 or index >= len(out):
            continue
        text = sanitize_generic_role_labels(str(fill.get("text") or "").strip())
        if not text or str(out[index].get("vo") or "").strip():
            continue
        out[index]["vo"] = text
        if not str(out[index].get("vo_draft") or "").strip():
            out[index]["vo_draft"] = text
    return out
