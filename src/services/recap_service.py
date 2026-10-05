"""Recap job runner: motion evidence + dialogue cues → LLM cut list + SRT.

Stage modules: ``recap_vo_budget``, ``recap_match``, ``recap_captions``,
``recap_cuts``, ``recap_cut_fit``, ``recap_cut_pad``, ``recap_cut_build``,
``recap_io``, ``recap_focus``, ``recap_rematch``, ``recap_motion``,
``recap_spine``, ``recap_llm_json``, ``recap_plan_cover``, ``recap_plan_acts``,
``recap_plan_gaps``, ``recap_plan_merge``, ``recap_constants``,
``recap_prompts``. This file re-exports those surfaces and
owns remaining plan / LLM / rematch / export orchestration. Jianying / FCPXML
are separate exports.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.media.fcpxml import (
    layout_clips_on_timeline,
    write_cuts_json,
    write_fcpxml,
    write_srt,
)
from src.services.llm_settings import call_remote_llm, get_remote_llm_settings
from src.services.recap_prompts import (  # facade: prompt policy lives in recap_prompts
    RECAP_CAPTION_SYSTEM as RECAP_CAPTION_SYSTEM,
    RECAP_CAPTION_SYSTEM_EN as RECAP_CAPTION_SYSTEM_EN,
    RECAP_EVIDENCE_POLICY as RECAP_EVIDENCE_POLICY,
    RECAP_EVIDENCE_POLICY_EN as RECAP_EVIDENCE_POLICY_EN,
    RECAP_EVIDENCE_POLICY_PLAN_EN as RECAP_EVIDENCE_POLICY_PLAN_EN,
    RECAP_EVIDENCE_REQUIRED_TAGS as RECAP_EVIDENCE_REQUIRED_TAGS,
    RECAP_FACT_POLICY as RECAP_FACT_POLICY,
    RECAP_GAP_SYSTEM,
    RECAP_GAP_SYSTEM_EN,
    RECAP_NAME_POLICY as RECAP_NAME_POLICY,
    RECAP_PLAN_ACT_SYSTEM as RECAP_PLAN_ACT_SYSTEM,
    RECAP_PLAN_GAP_SYSTEM as RECAP_PLAN_GAP_SYSTEM,
    RECAP_PLAN_HEAD_SYSTEM as RECAP_PLAN_HEAD_SYSTEM,
    RECAP_PLAN_STRUCTURE_SYSTEM as RECAP_PLAN_STRUCTURE_SYSTEM,
    RECAP_PLAN_SYSTEM as RECAP_PLAN_SYSTEM,
    RECAP_PLAN_SYSTEM_EN as RECAP_PLAN_SYSTEM_EN,
    RECAP_PLAN_TAIL_SYSTEM as RECAP_PLAN_TAIL_SYSTEM,
    RECAP_SYSTEM as RECAP_SYSTEM,
    RECAP_SYSTEM_EN as RECAP_SYSTEM_EN,
    RECAP_VO_CONTINUITY_POLICY as RECAP_VO_CONTINUITY_POLICY,
    RECAP_VO_CONTINUITY_POLICY_EN as RECAP_VO_CONTINUITY_POLICY_EN,
    RECAP_VO_DRAFT_SYSTEM as RECAP_VO_DRAFT_SYSTEM,
    RECAP_VO_DRAFT_SYSTEM_EN as RECAP_VO_DRAFT_SYSTEM_EN,
    RECAP_VO_POLISH_SYSTEM as RECAP_VO_POLISH_SYSTEM,
    RECAP_VO_POLISH_SYSTEM_EN as RECAP_VO_POLISH_SYSTEM_EN,
    RECAP_VO_STYLE_POLICY as RECAP_VO_STYLE_POLICY,
    default_recap_caption_prompt,
    default_recap_gap_prompt,
    default_recap_match_prompt,
    default_recap_plan_act_prompt,
    default_recap_plan_gap_prompt as default_recap_plan_gap_prompt,
    default_recap_plan_head_prompt as default_recap_plan_head_prompt,
    default_recap_plan_prompt,
    default_recap_plan_structure_prompt as default_recap_plan_structure_prompt,
    default_recap_plan_tail_prompt as default_recap_plan_tail_prompt,
    default_recap_polish_prompt,
    default_recap_vo_draft_prompt,
)
from src.services.recap_constants import (  # facade: knobs live in recap_constants
    BASE_CHARS_PER_SEC as BASE_CHARS_PER_SEC,
    BEAT_SRC_PAD_SEC as BEAT_SRC_PAD_SEC,
    CAPTION_CLIPS_PER_WAVE as CAPTION_CLIPS_PER_WAVE,
    CHARS_PER_SEC as CHARS_PER_SEC,
    ENDING_COVER_RATIO as ENDING_COVER_RATIO,
    HARD_MIN_BEAT_SEC as HARD_MIN_BEAT_SEC,
    INSERT_MAX_GAP_FROM_MASTER_SEC as INSERT_MAX_GAP_FROM_MASTER_SEC,
    MATCH_BEATS_PER_WAVE as MATCH_BEATS_PER_WAVE,
    MATCH_PACK_PAD_SEC as MATCH_PACK_PAD_SEC,
    MATCH_STATUS_OK as MATCH_STATUS_OK,
    MATCH_STATUS_WEAK as MATCH_STATUS_WEAK,
    MATCH_WEAK_SCORE as MATCH_WEAK_SCORE,
    MATCH_WEAK_SCORE_INSERT as MATCH_WEAK_SCORE_INSERT,
    MAX_BEAT_BUDGET_SEC as MAX_BEAT_BUDGET_SEC,
    MAX_CAPTION_SEC as MAX_CAPTION_SEC,
    MAX_CLIP_SEC as MAX_CLIP_SEC,
    MAX_GAP_FILL_WINDOWS as MAX_GAP_FILL_WINDOWS,
    MAX_PLAN_BEATS as MAX_PLAN_BEATS,
    MAX_RECAP_SEC as MAX_RECAP_SEC,
    MAX_STORY_BEATS as MAX_STORY_BEATS,
    MAX_TTS_CLIP_SEC as MAX_TTS_CLIP_SEC,
    MAX_VO_FILL as MAX_VO_FILL,
    MAX_VO_SENTENCE_CHARS as MAX_VO_SENTENCE_CHARS,
    MAX_WEAK_REMATCH_BEATS as MAX_WEAK_REMATCH_BEATS,
    MIN_BEAT_BUDGET_SEC as MIN_BEAT_BUDGET_SEC,
    MIN_BRIDGE_SEC as MIN_BRIDGE_SEC,
    MIN_CLIP_SEC as MIN_CLIP_SEC,
    MIN_FLASH_CLIP_SEC as MIN_FLASH_CLIP_SEC,
    MIN_INSERT_CLIP_SEC as MIN_INSERT_CLIP_SEC,
    MIN_RECAP_SEC as MIN_RECAP_SEC,
    MIN_STANDALONE_CLIP_SEC as MIN_STANDALONE_CLIP_SEC,
    MIN_VO_FILL as MIN_VO_FILL,
    PLAN_ACT_ASR_LIMIT as PLAN_ACT_ASR_LIMIT,
    PLAN_ACT_TARGET_SEC as PLAN_ACT_TARGET_SEC,
    RECAP_CLIMAX_IMPORTANCE as RECAP_CLIMAX_IMPORTANCE,
    RECAP_FOCUS_BOND as RECAP_FOCUS_BOND,
    RECAP_FOCUS_FLEX as RECAP_FOCUS_FLEX,
    RECAP_FOCUS_GENERIC as RECAP_FOCUS_GENERIC,
    RECAP_FOCUS_MODES as RECAP_FOCUS_MODES,
    RECAP_FOCUS_ORDEAL as RECAP_FOCUS_ORDEAL,
    RECAP_FOCUS_SOFT_MIN as RECAP_FOCUS_SOFT_MIN,
    RECAP_OCR_LIMIT as RECAP_OCR_LIMIT,
    RECAP_START_CAPTIONS as RECAP_START_CAPTIONS,
    RECAP_START_MATCH as RECAP_START_MATCH,
    RECAP_START_PLAN as RECAP_START_PLAN,
    RECAP_START_PLAN_ONLY as RECAP_START_PLAN_ONLY,
    RECAP_STORY_RATIO as RECAP_STORY_RATIO,
    RECAP_VISUAL_EVIDENCE_TAGS as RECAP_VISUAL_EVIDENCE_TAGS,
    SOURCE_ADJACENT_REUSE_RATIO as SOURCE_ADJACENT_REUSE_RATIO,
    SOURCE_MERGE_GAP_SEC as SOURCE_MERGE_GAP_SEC,
    SOURCE_OVERLAP_MERGE_SEC as SOURCE_OVERLAP_MERGE_SEC,
    SOURCE_REUSE_RATIO as SOURCE_REUSE_RATIO,
    TARGET_RECAP_SEC as TARGET_RECAP_SEC,
    TTS_SPEED as TTS_SPEED,
    VO_COVER_RATIO as VO_COVER_RATIO,
    VO_DRAFT_BEATS_PER_WAVE as VO_DRAFT_BEATS_PER_WAVE,
    VO_FILL_RATIO as VO_FILL_RATIO,
)
from src.services.recap_vo_budget import (  # facade: VO budget math lives in recap_vo_budget
    _clip_len as _clip_len,
    _clip_role as _clip_role,
    _counted_chars as _counted_chars,
    _join_vo as _join_vo,
    _looks_like_insert_cut as _looks_like_insert_cut,
    _max_picture_for_vo as _max_picture_for_vo,
    _normalize_vo_key as _normalize_vo_key,
    _preferred_clip_vo as _preferred_clip_vo,
    _shrink_clip as _shrink_clip,
    _trim_group_to_budget as _trim_group_to_budget,
    _vo_cover_span as _vo_cover_span,
    _vo_covers as _vo_covers,
    _vo_needs_more_picture as _vo_needs_more_picture,
    _vo_underfills_picture as _vo_underfills_picture,
    _caption_clip_sec as _caption_clip_sec,
    _clip_duration_for_vo as _clip_duration_for_vo,
    _break_long_vo_sentence as _break_long_vo_sentence,
    _punctuate_vo_sentence as _punctuate_vo_sentence,
    _take_vo_chars as _take_vo_chars,
    _vo_sentence_pieces as _vo_sentence_pieces,
    restore_recap_vo_text as restore_recap_vo_text,
    stretch_recap_clips_for_vo as stretch_recap_clips_for_vo,
    tighten_vo_text as tighten_vo_text,
    trim_group_to_budget as trim_group_to_budget,
    trim_vo_to_budget as trim_vo_to_budget,
    tts_char_budget as tts_char_budget,
    vo_needed_sec as vo_needed_sec,
    vo_sec as vo_sec,
)

from src.services.recap_match import (  # facade: match QC + span/evidence helpers
    _beat_visual_anchor as _beat_visual_anchor,
    _beats_by_id as _beats_by_id,
    _cap_match_score_for_anchor as _cap_match_score_for_anchor,
    _clamp_match_threshold as _clamp_match_threshold,
    _evidence_for_source_span as _evidence_for_source_span,
    _has_japanese_kana as _has_japanese_kana,
    _is_bridge_clip as _is_bridge_clip,
    _looks_like_scene_shift_text as _looks_like_scene_shift_text,
    _overlap_sec as _overlap_sec,
    _people_labels as _people_labels,
    _text_similarity as _text_similarity,
    _time_span as _time_span,
    annotate_recap_match_quality as annotate_recap_match_quality,
    clear_vo_on_weak_matches as clear_vo_on_weak_matches,
    is_weak_match_clip as is_weak_match_clip,
    keep_chunk_for_recap as keep_chunk_for_recap,
    looks_like_op_ed_text as looks_like_op_ed_text,
    list_weak_match_beat_ids as list_weak_match_beat_ids,
    normalize_evidence_required as normalize_evidence_required,
    recap_story_window as recap_story_window,
    resolve_match_qc_thresholds as resolve_match_qc_thresholds,
    score_recap_cut_match as score_recap_cut_match,
)

from src.services.recap_captions import (  # facade: caption pack/apply math
    _caption_index_span as _caption_index_span,
    _clip_vo_text as _clip_vo_text,
    _fold_short_captions as _fold_short_captions,
    _vo_restates_prior as _vo_restates_prior,
    apply_caption_cues as apply_caption_cues,
    clamp_caption_spans_to_vo as clamp_caption_spans_to_vo,
    normalize_caption_cues as normalize_caption_cues,
    pack_captions_for_tts as pack_captions_for_tts,
    recap_vo_coverage_ratio as recap_vo_coverage_ratio,
    sanitize_generic_role_labels as sanitize_generic_role_labels,
    split_clips_for_captions as split_clips_for_captions,
    split_underfilled_vo_clips as split_underfilled_vo_clips,
)

from src.services.recap_cuts import (  # facade: cut coalesce / dedupe math
    _attach_cut_vo as _attach_cut_vo,
    _clip_beat_id as _clip_beat_id,
    _clip_src_span as _clip_src_span,
    _cut_to_next_shot as _cut_to_next_shot,
    _is_flash_cut as _is_flash_cut,
    _merge_cut_pair as _merge_cut_pair,
    _should_merge_source_clips as _should_merge_source_clips,
    _source_adjacent_clips as _source_adjacent_clips,
    _source_gap_sec as _source_gap_sec,
    _source_overlap_sec as _source_overlap_sec,
    _source_reuse_ratio as _source_reuse_ratio,
    coalesce_recap_cuts as coalesce_recap_cuts,
    collect_used_source_spans as collect_used_source_spans,
    dedupe_overlapping_recap_cuts as dedupe_overlapping_recap_cuts,
    drop_reused_source_cuts as drop_reused_source_cuts,
    ensure_main_cut_per_beat as ensure_main_cut_per_beat,
    recap_cuts_duration as recap_cuts_duration,
)

from src.services.recap_cut_fit import (  # facade: snap / beat-window clamp
    _snap_src_into_beat_window as _snap_src_into_beat_window,
    clamp_cuts_to_beat_window as clamp_cuts_to_beat_window,
    snap_cuts_to_capped_chunks as snap_cuts_to_capped_chunks,
)

from src.services.recap_cut_pad import (  # facade: TTS pad / insert clamp
    _chunk_window as _chunk_window,
    _clamp_window_away_from_op_ed as _clamp_window_away_from_op_ed,
    _expand_clip as _expand_clip,
    _make_tts_bridge_clip as _make_tts_bridge_clip,
    _neighbor_source_window as _neighbor_source_window,
    _place_insert_after_master as _place_insert_after_master,
    _source_hits_op_ed as _source_hits_op_ed,
    clamp_insert_cuts_to_beat as clamp_insert_cuts_to_beat,
    pad_cuts_for_tts as pad_cuts_for_tts,
)

from src.services.recap_cut_build import (  # facade: normalize / refine / duration
    _chunk_is_skipped as _chunk_is_skipped,
    apply_recap_duration as apply_recap_duration,
    normalize_cut_list as normalize_cut_list,
    refine_recap_cuts as refine_recap_cuts,
    stash_match_vo_as_draft as stash_match_vo_as_draft,
)

from src.services.recap_io import (  # facade: sidecar load / write
    _load_recap_sidecar as _load_recap_sidecar,
    _read_recap_sidecar as _read_recap_sidecar,
    _recap_clip_records as _recap_clip_records,
    _recap_sidecar_path as _recap_sidecar_path,
    load_recap_beats as load_recap_beats,
    load_recap_cuts as load_recap_cuts,
    recap_beats_path_for_video as recap_beats_path_for_video,
    recap_cuts_path_for_video as recap_cuts_path_for_video,
    write_recap_beats_file as write_recap_beats_file,
    write_recap_cuts_file as write_recap_cuts_file,
)

from src.services.recap_focus import (  # facade: soft focus prior
    infer_recap_focus as infer_recap_focus,
    merge_recap_focus as merge_recap_focus,
    normalize_recap_focus as normalize_recap_focus,
    recap_focus_evidence_limits as recap_focus_evidence_limits,
    recap_focus_plan_hint as recap_focus_plan_hint,
    recap_focus_vo_hint as recap_focus_vo_hint,
    story_silent_spans as story_silent_spans,
)

from src.services.recap_rematch import (  # facade: rematch splice / filter
    _filter_rematch_cuts_to_beat as _filter_rematch_cuts_to_beat,
    _locked_vo_context as _locked_vo_context,
    _neighbor_beats_for_rematch as _neighbor_beats_for_rematch,
    _splice_recap_beat_cuts as _splice_recap_beat_cuts,
)

from src.services.recap_motion import (  # facade: motion chunks / VLM gaps
    _asr_covers_span as _asr_covers_span,
    _beat_evidence_tags as _beat_evidence_tags,
    _beat_needs_visual_motion as _beat_needs_visual_motion,
    _caption_one_liner as _caption_one_liner,
    _chunk_motion_beats as _chunk_motion_beats,
    _cue_span as _cue_span,
    apply_recap_skip_marks as apply_recap_skip_marks,
    compact_index_chunks as compact_index_chunks,
    compact_motion_chunks as compact_motion_chunks,
    overlay_motion_captions as overlay_motion_captions,
    recap_motion_dense_chunk_indices as recap_motion_dense_chunk_indices,
    recap_motion_gap_chunk_indices as recap_motion_gap_chunk_indices,
)

from src.services.recap_spine import (  # facade: OCR cues / ASR-VLM spine
    _DIALOGUE_OUTCOME_RE as _DIALOGUE_OUTCOME_RE,
    _normalize_ocr_text as _normalize_ocr_text,
    _spine_event_label as _spine_event_label,
    build_asr_vlm_spine as build_asr_vlm_spine,
    compact_ocr_cues as compact_ocr_cues,
    compact_ocr_cues_in_span as compact_ocr_cues_in_span,
    expand_spine_plot_phases as expand_spine_plot_phases,
    sample_timeline_items as sample_timeline_items,
)

from src.services.recap_llm_json import (  # facade: LLM JSON salvage
    _extract_balanced_object as _extract_balanced_object,
    _extract_json as _extract_json,
    _loads_cut_list_json as _loads_cut_list_json,
    _loads_json_object as _loads_json_object,
    _repair_llm_json as _repair_llm_json,
    _salvage_cut_list_payload as _salvage_cut_list_payload,
)

from src.services.recap_plan_cover import (  # facade: spine / land / silent beats
    _beat_lands_dialogue_outcome as _beat_lands_dialogue_outcome,
    ensure_beats_cover_silent_spans as ensure_beats_cover_silent_spans,
    ensure_beats_cover_spine as ensure_beats_cover_spine,
    ensure_beats_land_dialogue_outcomes as ensure_beats_land_dialogue_outcomes,
)

from src.services.recap_plan_acts import (  # facade: act windows / structure brief
    _must_land_cues as _must_land_cues,
    build_plan_structure_brief as build_plan_structure_brief,
    clamp_beats_to_act_window as clamp_beats_to_act_window,
    normalize_plan_act_windows as normalize_plan_act_windows,
    parse_plan_act_windows as parse_plan_act_windows,
    parse_soft_focus_payload as parse_soft_focus_payload,
    recap_plan_act_user_prompt as recap_plan_act_user_prompt,
    split_story_into_plan_acts as split_story_into_plan_acts,
)

from src.services.recap_plan_gaps import (  # facade: coverage / gaps / OP-ED
    _ACTIVITY_EVENT_KEY_RE as _ACTIVITY_EVENT_KEY_RE,
    _TEXTURE_BEAT_RE as _TEXTURE_BEAT_RE,
    _event_overlap_ratio as _event_overlap_ratio,
    activity_shift_gaps as activity_shift_gaps,
    beat_evidence_score as beat_evidence_score,
    beat_evidence_sec as beat_evidence_sec,
    beats_cover_ending as beats_cover_ending,
    beats_cover_opening as beats_cover_opening,
    dialogue_outcome_gaps as dialogue_outcome_gaps,
    drop_op_ed_beats as drop_op_ed_beats,
    opening_deadline_sec as opening_deadline_sec,
    prioritize_story_gaps as prioritize_story_gaps,
    story_beat_gaps as story_beat_gaps,
    story_gap_min_sec as story_gap_min_sec,
    trim_story_beats_to_limit as trim_story_beats_to_limit,
)

from src.services.recap_plan_merge import (  # facade: merge beats / filter pack
    _beat_event_key as _beat_event_key,
    _beat_inside_windows as _beat_inside_windows,
    _beats_brief as _beats_brief,
    _beats_time_conflict as _beats_time_conflict,
    _char_ngrams as _char_ngrams,
    _events_near_duplicate as _events_near_duplicate,
    _span_cover_ratio as _span_cover_ratio,
    filter_pack_to_span as filter_pack_to_span,
    filter_pack_to_spans as filter_pack_to_spans,
    merge_story_beats as merge_story_beats,
    pack_for_beats as pack_for_beats,
    recap_plan_gap_user_prompt as recap_plan_gap_user_prompt,
    recap_plan_head_user_prompt as recap_plan_head_user_prompt,
    recap_plan_tail_user_prompt as recap_plan_tail_user_prompt,
)

from src.services.understanding_resource_service import (
    CAPTION_LANGUAGE_ZH,
    UNDERSTANDING_MODE_MOTION,
    normalize_caption_language,
)

_VO_LAND_HINT_RE = re.compile(
    r"(拒|答应|同意|决定|收下|推回|收束|落点|结束|算了|离去|离开|揭穿|识破|赢|输|放过|解决|成交)"
)
# Hiragana / katakana — source JP dialogue leaking into Chinese VO.
_JP_KANA_RE = re.compile(r"[\u3040-\u30ff]")
_VO_QUOTE_RE = re.compile(r"[「『]([^」』]{1,120})[」』]")
_VO_WHITESPACE_RE = re.compile(r"\s+")


def recap_target_sec(duration_sec: float) -> float:
    """Scale recap length to the story window, clamped to about 3–12 minutes."""
    _start, story_end = recap_story_window(duration_sec)
    raw = max(0.0, float(story_end or 0.0)) * RECAP_STORY_RATIO
    return round(min(MAX_RECAP_SEC, max(MIN_RECAP_SEC, raw or TARGET_RECAP_SEC)), 1)


def recap_duration_bounds(target_sec: float) -> tuple[float, float]:
    """Soft floor + hard ceiling. Floor is advisory; we never pad cuts just to hit it."""
    target = max(MIN_RECAP_SEC, float(target_sec or TARGET_RECAP_SEC))
    return (
        round(max(90.0, target * 0.5), 1),
        round(min(MAX_RECAP_SEC, max(target, target * 1.15)), 1),
    )


def format_recap_clock(sec: float) -> str:
    total = max(0.0, float(sec or 0.0))
    minutes = int(total // 60)
    seconds = int(round(total - minutes * 60.0))
    if seconds >= 60:
        minutes += 1
        seconds = 0
    return f"{minutes:02d}:{seconds:02d}"


def format_recap_clock_range(start: float, end: float) -> str:
    return f"{format_recap_clock(start)}–{format_recap_clock(end)}"


def group_recap_vo_units(
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group flat clips into narration units: one parent VO covering child shots.

    A unit starts at each clip that owns VO, or at the first empty clip after the
    previous unit. Following empty same-beat shots stay as children until the next
    VO-bearing clip (or beat change).
    """
    items = [dict(clip) for clip in clips or [] if isinstance(clip, Mapping)]
    by_id = _beats_by_id(beats)
    units: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        start = index
        head = items[start]
        vo = str(head.get("vo") or "").strip()
        beat_id = head.get("beat_id")
        end = start
        cursor = start + 1
        while cursor < len(items):
            nxt = items[cursor]
            nxt_vo = str(nxt.get("vo") or "").strip()
            if nxt_vo:
                break
            nxt_beat = nxt.get("beat_id")
            if beat_id is not None and nxt_beat is not None and nxt_beat != beat_id:
                break
            end = cursor
            cursor += 1
        indices = list(range(start, end + 1))
        shots: list[dict[str, Any]] = []
        picture = 0.0
        src_lo = float(items[start].get("src_in") or 0.0)
        src_hi = float(items[start].get("src_out") or src_lo)
        tl_lo = float(items[start].get("tl_in") or 0.0)
        tl_hi = float(items[end].get("tl_out") or tl_lo)
        for offset, clip_i in enumerate(indices):
            clip = items[clip_i]
            role = _clip_role(clip) or ("insert" if _looks_like_insert_cut(clip) else "")
            if _is_bridge_clip(clip):
                role = "bridge"
            if role == "vo_hold":
                # Narration placeholder with no picture shot — keep unit, hide from children.
                continue
            src_in = float(clip.get("src_in") or 0.0)
            src_out = float(clip.get("src_out") or src_in)
            tl_in = float(clip.get("tl_in") or 0.0)
            tl_out = float(clip.get("tl_out") or tl_in)
            span = max(0.0, tl_out - tl_in)
            if span <= 0.04 and clip.get("duration") is not None:
                span = max(0.0, float(clip.get("duration") or 0.0))
            picture += span
            src_lo = min(src_lo, src_in)
            src_hi = max(src_hi, src_out)
            shots.append(
                {
                    "offset": offset,
                    "clip_index": clip_i,
                    "name": str(clip.get("name") or f"{clip_i + 1:02d}"),
                    "role": role,
                    "src_in": round(src_in, 3),
                    "src_out": round(src_out, 3),
                    "tl_in": round(tl_in, 3),
                    "tl_out": round(tl_out, 3),
                    "picture_sec": round(span, 3),
                }
            )
        # Re-number shot offsets so UI delete/reorder match visible children.
        for shot_i, shot in enumerate(shots):
            shot["offset"] = shot_i
        try:
            beat_int = int(beat_id) if beat_id is not None else 0
        except (TypeError, ValueError):
            beat_int = 0
        beat = by_id.get(beat_int) or {}
        speak = vo_sec(vo) if vo else 0.0
        units.append(
            {
                "unit_index": len(units),
                "clip_indices": indices,
                "start_index": start,
                "end_index": end,
                "vo": vo,
                "beat_id": beat_int or None,
                "event": str(head.get("event") or beat.get("event") or "").strip(),
                "picture_sec": round(picture, 3),
                "speak_sec": round(speak, 3),
                "cover_sec": round(max(speak, 0.0), 3),
                "src_in": round(src_lo, 3),
                "src_out": round(src_hi, 3),
                "tl_in": round(tl_lo, 3),
                "tl_out": round(tl_hi, 3),
                "shots": shots,
                "shortfall_sec": round(max(0.0, speak - picture), 3),
            }
        )
        index = end + 1
    return units


def _write_recap_clips_payload(
    media: str,
    payload: Mapping[str, Any],
    clips: Sequence[Mapping[str, Any]],
    *,
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    info = {
        "fps": float(payload.get("fps") or 24.0),
        "width": int(payload.get("width") or 1920),
        "height": int(payload.get("height") or 1080),
    }
    laid = layout_clips_on_timeline(list(clips), fps=float(info["fps"]))
    dest = recap_cuts_path_for_video(media)
    cuts_path = write_recap_cuts_file(
        dest,
        title=str(payload.get("title") or ""),
        video_path=media,
        video_id=str(payload.get("video_id") or ""),
        info=info,
        laid_out=laid,
        beats_path=str(payload.get("beats_path") or ""),
        stage=str(payload.get("stage") or "captions"),
    )
    srt_path = ""
    if rewrite_srt:
        stem = Path(os.path.abspath(os.path.expanduser(media))).stem
        srt_dest = Path(os.path.abspath(os.path.expanduser(media))).parent / f"{stem}_recap.srt"
        srt_path = str(write_srt(laid, srt_dest))
    return {
        "ok": True,
        "cuts_path": str(cuts_path),
        "srt_path": srt_path,
        "clips": laid,
        "units": group_recap_vo_units(laid),
    }


def save_recap_vo_unit(
    video_path: str,
    clip_indices: Sequence[int],
    text: str,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Hand-edit one narration unit: VO on first shot, clear children, stamp cover time."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = sorted({int(i) for i in clip_indices})
    if not indices or indices[0] < 0 or indices[-1] >= len(clips):
        raise RuntimeError("无效的解说单元镜头范围。")
    for expected, got in enumerate(indices):
        if got != indices[0] + expected:
            raise RuntimeError("解说单元镜头必须连续。")
    body = str(text or "").strip()
    speak = _max_picture_for_vo(body) if body else 0.0
    first = indices[0]
    last = indices[-1]
    for pos in indices:
        row = dict(clips[pos])
        if pos == first:
            row["vo"] = body
            row["vo_draft"] = body
        else:
            row["vo"] = ""
            if "vo_draft" in row:
                row["vo_draft"] = ""
            row.pop("vo_tl_in", None)
            row.pop("vo_tl_out", None)
        clips[pos] = row
    head = clips[first]
    tl_in = float(head.get("tl_in") or 0.0)
    unit_out = float(clips[last].get("tl_out") or tl_in)
    if body and speak > 0:
        vo_end = min(unit_out, tl_in + max(speak, 0.5))
        if vo_end > tl_in + 0.04:
            head["vo_tl_in"] = round(tl_in, 3)
            head["vo_tl_out"] = round(vo_end, 3)
        else:
            head.pop("vo_tl_in", None)
            head.pop("vo_tl_out", None)
    else:
        head.pop("vo_tl_in", None)
        head.pop("vo_tl_out", None)
    clips[first] = head
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["start_index"] = first
    result["end_index"] = last
    result["vo"] = body
    result["speak_sec"] = round(vo_sec(body) if body else 0.0, 3)
    return result


def reorder_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    from_offset: int,
    to_offset: int,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Move one child shot inside its narration unit, then re-layout timeline."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if len(indices) < 2:
        raise RuntimeError("至少两个子镜头才能调序。")
    if from_offset < 0 or to_offset < 0 or from_offset >= len(indices) or to_offset >= len(indices):
        raise RuntimeError("子镜头位置无效。")
    if from_offset == to_offset:
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    block = [clips[i] for i in indices]
    item = block.pop(from_offset)
    block.insert(to_offset, item)
    # Keep unit VO on the chronologically first slot after reorder.
    voiced = [str(row.get("vo") or "").strip() for row in block]
    unit_vo = next((text for text in voiced if text), "")
    for offset, row in enumerate(block):
        next_row = dict(row)
        if offset == 0:
            next_row["vo"] = unit_vo
            next_row["vo_draft"] = unit_vo
        else:
            next_row["vo"] = ""
            if "vo_draft" in next_row:
                next_row["vo_draft"] = ""
            next_row.pop("vo_tl_in", None)
            next_row.pop("vo_tl_out", None)
        clips[indices[offset]] = next_row
    if unit_vo:
        head = clips[indices[0]]
        tl_in = float(head.get("tl_in") or 0.0)
        last = clips[indices[-1]]
        unit_out = float(last.get("tl_out") or tl_in)
        speak = _max_picture_for_vo(unit_vo)
        vo_end = min(unit_out, tl_in + max(speak, 0.5)) if speak > 0 else unit_out
        if vo_end > tl_in + 0.04:
            head["vo_tl_in"] = round(tl_in, 3)
            head["vo_tl_out"] = round(vo_end, 3)
        clips[indices[0]] = head
    return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)


def owned_chunk_indices_for_clips(
    chunks: Sequence[Mapping[str, Any]] | None,
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    overlap_ratio: float = 0.45,
) -> set[int]:
    """Chunks covered by the given clips (by chunk_index or time overlap)."""
    return set(
        classify_chunk_usage_for_clips(
            chunks,
            unit_clips=clips,
            all_clips=clips,
            overlap_ratio=overlap_ratio,
        )
    )


def classify_chunk_usage_for_clips(
    chunks: Sequence[Mapping[str, Any]] | None,
    *,
    unit_clips: Sequence[Mapping[str, Any]] | None = None,
    all_clips: Sequence[Mapping[str, Any]] | None = None,
    overlap_ratio: float = 0.45,
) -> dict[int, str]:
    """Map chunk index -> ``unit`` | ``used`` for picker coloring.

    - ``unit``: already in the current narration unit
    - ``used``: used by some other shot in the full cut list (not in the unit)
    """

    def _covered(shots: Sequence[Mapping[str, Any]] | None) -> set[int]:
        owned: set[int] = set()
        rows = [dict(row) for row in chunks or [] if isinstance(row, Mapping)]
        items = [dict(row) for row in shots or [] if isinstance(row, Mapping)]
        if not rows or not items:
            return owned
        for index, chunk in enumerate(rows):
            try:
                c0 = float(chunk.get("start") or chunk.get("src_in") or 0.0)
                c1 = float(chunk.get("end") or chunk.get("src_out") or c0)
            except (TypeError, ValueError):
                continue
            if c1 <= c0 + 0.04:
                continue
            span = max(0.001, c1 - c0)
            for shot in items:
                try:
                    if int(shot.get("chunk_index")) == index:
                        owned.add(index)
                        break
                except (TypeError, ValueError):
                    pass
                try:
                    s0 = float(shot.get("src_in") or 0.0)
                    s1 = float(shot.get("src_out") or s0)
                except (TypeError, ValueError):
                    continue
                overlap = max(0.0, min(c1, s1) - max(c0, s0))
                if overlap >= max(0.5, span * float(overlap_ratio)):
                    owned.add(index)
                    break
        return owned

    unit_set = _covered(unit_clips)
    all_set = _covered(all_clips if all_clips is not None else unit_clips)
    usage: dict[int, str] = {}
    for index in sorted(all_set | unit_set):
        if index in unit_set:
            usage[index] = "unit"
        else:
            usage[index] = "used"
    return usage


def add_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    *,
    src_in: float,
    src_out: float,
    after_offset: int | None = None,
    name: str = "",
    chunk_index: int | None = None,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Insert a child shot into a narration unit (no LLM)."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if not indices:
        raise RuntimeError("无效的解说单元。")
    start = float(src_in)
    end = float(src_out)
    if end <= start + 0.04:
        raise RuntimeError("原片入点/出点无效。")
    anchor = clips[indices[0]]
    # VO-only placeholder: replace with the first real shot, keep narration text.
    if len(indices) == 1 and _clip_role(anchor) == "vo_hold":
        hold_vo = str(anchor.get("vo") or "").strip()
        replacement = {
            "name": str(name or "").strip() or str(anchor.get("name") or f"{len(clips):02d}"),
            "beat_id": anchor.get("beat_id"),
            "src_in": round(start, 3),
            "src_out": round(end, 3),
            "duration": round(end - start, 3),
            "vo": hold_vo,
            "vo_draft": hold_vo,
            "role": "",
            "reason": str(anchor.get("reason") or ""),
            "event": str(anchor.get("event") or ""),
        }
        if chunk_index is not None:
            try:
                replacement["chunk_index"] = int(chunk_index)
            except (TypeError, ValueError):
                pass
        clips[indices[0]] = replacement
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    insert_at = indices[-1] + 1
    if after_offset is not None and 0 <= int(after_offset) < len(indices):
        insert_at = indices[int(after_offset)] + 1
    new_clip = {
        "name": str(name or "").strip() or f"{len(clips) + 1:02d}",
        "beat_id": anchor.get("beat_id"),
        "src_in": round(start, 3),
        "src_out": round(end, 3),
        "duration": round(end - start, 3),
        "vo": "",
        "role": str(anchor.get("role") or ""),
        "reason": str(anchor.get("reason") or ""),
        "event": str(anchor.get("event") or ""),
    }
    if chunk_index is not None:
        try:
            new_clip["chunk_index"] = int(chunk_index)
        except (TypeError, ValueError):
            pass
    clips.insert(insert_at, new_clip)
    return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)


def _unit_vo_text(block: Sequence[Mapping[str, Any]]) -> str:
    for row in block:
        text = str(row.get("vo") or "").strip()
        if text:
            return text
    return ""


def _stamp_unit_vo_on_block(block: list[dict[str, Any]], unit_vo: str) -> list[dict[str, Any]]:
    stamped: list[dict[str, Any]] = []
    for offset, row in enumerate(block):
        next_row = dict(row)
        if offset == 0:
            next_row["vo"] = unit_vo
            next_row["vo_draft"] = unit_vo
            if unit_vo:
                tl_in = float(next_row.get("tl_in") or 0.0)
                last = block[-1]
                unit_out = float(last.get("tl_out") or next_row.get("tl_out") or tl_in)
                speak = _max_picture_for_vo(unit_vo)
                vo_end = min(unit_out, tl_in + max(speak, 0.5)) if speak > 0 else unit_out
                if vo_end > tl_in + 0.04:
                    next_row["vo_tl_in"] = round(tl_in, 3)
                    next_row["vo_tl_out"] = round(vo_end, 3)
                else:
                    next_row.pop("vo_tl_in", None)
                    next_row.pop("vo_tl_out", None)
            else:
                next_row.pop("vo_tl_in", None)
                next_row.pop("vo_tl_out", None)
        else:
            next_row["vo"] = ""
            if "vo_draft" in next_row:
                next_row["vo_draft"] = ""
            next_row.pop("vo_tl_in", None)
            next_row.pop("vo_tl_out", None)
        stamped.append(next_row)
    return stamped


def delete_recap_unit_shot(
    video_path: str,
    clip_indices: Sequence[int],
    offset: int,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Remove one child shot. Last picture shot may leave a VO-only hold clip."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = [int(i) for i in clip_indices]
    if not indices:
        raise RuntimeError("无效的解说单元。")
    # Visible shots skip vo_hold; map UI offset → real clip index.
    picture_indices = [
        i for i in indices if _clip_role(clips[i]) != "vo_hold"
    ] if indices and max(indices) < len(clips) else []
    if offset < 0 or offset >= len(picture_indices):
        raise RuntimeError("子镜头位置无效。")
    remove_at = int(picture_indices[offset])
    block = [clips[i] for i in indices]
    unit_vo = _unit_vo_text(block)
    event = str(block[0].get("event") or "").strip()
    beat_id = block[0].get("beat_id")
    removed = dict(clips[remove_at])
    del clips[remove_at]

    remaining_picture = len(picture_indices) - 1
    if remaining_picture <= 0:
        if not unit_vo:
            # No VO and no shots left — drop the unit entirely.
            return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
        speak = max(0.5, float(_max_picture_for_vo(unit_vo) or 0.5))
        src_in = float(removed.get("src_in") or 0.0)
        hold = {
            "name": str(removed.get("name") or "vo"),
            "beat_id": beat_id,
            "src_in": round(src_in, 3),
            "src_out": round(src_in + speak, 3),
            "duration": round(speak, 3),
            "vo": unit_vo,
            "vo_draft": unit_vo,
            "role": "vo_hold",
            "event": event,
            "reason": str(removed.get("reason") or ""),
        }
        clips.insert(remove_at, hold)
        return _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)

    # Rebuild remaining unit block after the deletion (indices shift past remove_at).
    new_indices: list[int] = []
    for old in indices:
        if old == remove_at:
            continue
        new_indices.append(old - 1 if old > remove_at else old)
    remaining = [clips[i] for i in new_indices]
    stamped = _stamp_unit_vo_on_block(remaining, unit_vo)
    for idx, row in zip(new_indices, stamped):
        clips[idx] = row
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["deleted_offset"] = int(offset)
    result["vo_hold"] = False
    return result


def delete_recap_vo_unit(
    video_path: str,
    clip_indices: Sequence[int],
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Remove a whole narration unit (VO + all child shots)."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    indices = sorted({int(i) for i in clip_indices})
    if not indices or indices[0] < 0 or indices[-1] >= len(clips):
        raise RuntimeError("无效的解说单元镜头范围。")
    for expected, got in enumerate(indices):
        if got != indices[0] + expected:
            raise RuntimeError("解说单元镜头必须连续。")
    for index in reversed(indices):
        del clips[index]
    result = _write_recap_clips_payload(media, payload, clips, rewrite_srt=rewrite_srt)
    result["deleted_unit_clips"] = len(indices)
    return result


def recap_clip_review_rows(
    clips: Sequence[Mapping[str, Any]] | None,
    *,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Readonly review rows for the understanding-page QC table (not an NLE)."""
    by_id = _beats_by_id(beats)
    rows: list[dict[str, Any]] = []
    for index, clip in enumerate(clips or []):
        if not isinstance(clip, Mapping):
            continue
        tl_in = float(clip.get("tl_in") or 0.0)
        tl_out = float(clip.get("tl_out") or 0.0)
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or 0.0)
        picture = max(0.0, tl_out - tl_in)
        if picture <= 0.04 and clip.get("duration") is not None:
            picture = max(0.0, float(clip.get("duration") or 0.0))
        text = str(clip.get("vo") or "").strip()
        speak = vo_sec(text) if text else 0.0
        fill = (speak / picture) if picture > 0.08 else 0.0
        try:
            beat_id = int(clip.get("beat_id"))
        except (TypeError, ValueError):
            beat_id = 0
        beat = by_id.get(beat_id) or {}
        event = str(clip.get("event") or beat.get("event") or "").strip()
        flags: list[str] = []
        if _looks_like_insert_cut(clip):
            flags.append("insert")
        if _is_bridge_clip(clip):
            flags.append("bridge")
        if not text:
            if "bridge" not in flags:
                flags.append("empty_vo")
        elif _vo_underfills_picture(text, picture):
            flags.append("underfill")
        if is_weak_match_clip(clip):
            flags.append("weak_match")
        support = clip.get("evidence_support")
        if not isinstance(support, Mapping):
            support = {}
        evidence_flags: list[str] = []
        if support.get("asr"):
            evidence_flags.append("asr")
        if support.get("vlm"):
            evidence_flags.append("vlm")
        if support.get("character"):
            evidence_flags.append("character")
        if is_weak_match_clip(clip) and "vlm" not in evidence_flags and "asr" not in evidence_flags:
            evidence_flags.append("thin")
        rows.append(
            {
                "index": index,
                "name": str(clip.get("name") or f"{index + 1:02d}"),
                "tl_in": round(tl_in, 3),
                "tl_out": round(tl_out, 3),
                "src_in": round(src_in, 3),
                "src_out": round(src_out, 3),
                "beat_id": beat_id or None,
                "event": event,
                "vo": text,
                "vo_owns_shot": bool(text),
                "fill_ratio": round(fill, 3),
                "flags": flags,
                "evidence_flags": evidence_flags,
                "match_status": str(clip.get("match_status") or MATCH_STATUS_OK),
                "match_score": clip.get("match_score"),
                "picture_sec": round(picture, 3),
                "reason": str(clip.get("reason") or "").strip(),
                "evidence_required": list(
                    beat.get("evidence_required") or clip.get("evidence_required") or []
                ),
            }
        )
    return rows


def parse_recap_clock(text: str) -> float:
    body = str(text or "").strip().replace("，", ".").replace("：", ":")
    if not body:
        return 0.0
    if ":" in body:
        parts = [part.strip() for part in body.split(":")]
        if len(parts) == 2:
            return max(0.0, float(parts[0] or 0.0) * 60.0 + float(parts[1] or 0.0))
        if len(parts) == 3:
            return max(
                0.0,
                float(parts[0] or 0.0) * 3600.0
                + float(parts[1] or 0.0) * 60.0
                + float(parts[2] or 0.0),
            )
    return max(0.0, float(body))


def recap_speaker_stats(cues: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    from src.storage.dialogue_transcript_store import is_auto_speaker_label

    blank = 0
    auto = 0
    named = 0
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()
        if not label:
            blank += 1
        elif is_auto_speaker_label(label):
            auto += 1
        else:
            named += 1
    unnamed = blank + auto
    return {
        "blank": blank,
        "auto": auto,
        "named": named,
        "unnamed": unnamed,
        "needs_naming": unnamed > 0,
    }


def fill_recap_motion_for_beats(
    video_id: str,
    pack: Mapping[str, Any],
    beats: Sequence[Mapping[str, Any]] | None,
    *,
    config=None,
    should_stop_callback: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    chunk_completed_callback: Callable[..., None] | None = None,
) -> tuple[dict[str, Any], list[str], int]:
    """VLM every beat-window chunk that still lacks a motion caption.

    Climax windows use a four-frame grid in one call. Dialogue coverage alone
    never skips motion — empty caps make Match/VO picture-blind.
    """
    indices = recap_motion_gap_chunk_indices(pack, beats)
    if not indices:
        return dict(pack), [], 0
    dense = recap_motion_dense_chunk_indices(pack, beats, indices)
    from src.core.understanding.base import UnderstandingStoppedError
    from src.services.understanding_service import generate_evidence_for_video

    wanted = set()
    for raw in indices:
        try:
            wanted.add(int(raw))
        except (TypeError, ValueError):
            continue
    done = {"n": 0}

    def _on_chunk(chunk_index, _total, _payload) -> None:
        try:
            index = int(chunk_index)
        except (TypeError, ValueError):
            return
        if index not in wanted:
            return
        done["n"] += 1
        if on_progress:
            on_progress(done["n"], len(indices))
        if chunk_completed_callback:
            chunk_completed_callback(index, len(indices), _payload)

    if on_progress:
        on_progress(0, len(indices))
    try:
        generate_evidence_for_video(
            video_id,
            config=config,
            mode=UNDERSTANDING_MODE_MOTION,
            chunk_indices=indices,
            dense_chunk_indices=dense,
            should_stop_callback=should_stop_callback,
            chunk_completed_callback=_on_chunk,
        )
    except UnderstandingStoppedError:
        raise
    except Exception:
        return dict(pack), ["recap_warn_motion_gaps"], done["n"]
    refreshed = build_recap_pack(video_id, config=config)
    if pack.get("people"):
        refreshed["people"] = list(pack.get("people") or [])
    leftover = recap_motion_gap_chunk_indices(refreshed, beats)
    filled = max(0, len(indices) - len(leftover))
    return refreshed, [], filled


def resolve_plan_act_windows(
    pack: Mapping[str, Any],
    *,
    config=None,
    language: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[..., Any] | None = None,
) -> tuple[list[tuple[float, float]], list[str], dict[str, Any]]:
    """Understand timeline+ASR first, then cut acts; fall back to silence/time split."""
    warnings: list[str] = []
    focus = infer_recap_focus(pack)
    duration = float(pack.get("duration_sec") or 0.0)
    story_start, story_end = recap_story_window(duration)
    width = max(0.0, story_end - story_start)
    if width <= PLAN_ACT_TARGET_SEC * 1.25:
        return ([(story_start, story_end)] if width > 1.0 else []), warnings, focus

    if progress_callback is not None:
        try:
            progress_callback(10, {"stage": "plan_structure"})
        except TypeError:
            progress_callback(10, "plan_structure")

    brief = build_plan_structure_brief(pack)
    user = (
        "下面是整集正片时间轴：asr 带时码台词，chunks 是画面时间轴，silent_spans 是无对白但仍占时间的段落。\n"
        "先理解剧情阶段，再输出分幕 acts；silent_spans 必须划进某幕，禁止跳过。\n"
        "soft_prior 只是本地粗判，可参考可推翻；吃不准 soft_focus 用 generic。\n"
        f"正片窗口 story_t=[{story_start:.0f},{story_end:.0f}]，必须首尾盖住。\n\n"
        + json.dumps(brief, ensure_ascii=False)
    )
    try:
        text = call_remote_llm(
            system=default_recap_plan_structure_prompt(language),
            user=user,
            config=config,
            temperature=0.2,
            max_tokens=2048,
            should_stop_callback=should_stop_callback,
        )
        parsed = parse_plan_act_windows(text)
        focus = merge_recap_focus(focus, parse_soft_focus_payload(text))
        acts = normalize_plan_act_windows(
            parsed,
            story_start=story_start,
            story_end=story_end,
            goal_sec=PLAN_ACT_TARGET_SEC,
        )
        if acts and acts[0][0] <= story_start + 30.0 and acts[-1][1] >= story_end * 0.95:
            return acts, warnings, focus
        warnings.append("recap_warn_plan_structure")
    except UnderstandingStoppedError:
        raise
    except Exception:
        warnings.append("recap_warn_plan_structure")

    return split_story_into_plan_acts(pack), warnings, focus


def scrub_unevidenced_beats(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any] | None,
    *,
    pad_sec: float = 14.0,
) -> list[dict[str, Any]]:
    """Drop invented plot beats whose time window has no asr and no caps."""
    items = [dict(beat) for beat in beats or []]
    if not items or pack is None:
        return items
    kept: list[dict[str, Any]] = []
    for beat in items:
        span = _time_span(beat.get("t"))
        if not span:
            continue
        evidence = _evidence_for_source_span(
            pack,
            span[0],
            span[1],
            pad_sec=pad_sec,
            asr_limit=24,
            cap_limit=12,
        )
        has_asr = bool(evidence.get("asr"))
        has_caps = bool(evidence.get("caps"))
        if has_asr or has_caps:
            kept.append(beat)
            continue
        # Empty window = wrong t or pure hallucination. Keep only soft texture/bridge.
        try:
            importance = float(beat.get("importance") or 0.0)
        except (TypeError, ValueError):
            importance = 0.0
        if importance >= 0.45:
            continue
        if _is_texture_beat(beat) or _looks_like_scene_shift_text(beat.get("event")):
            # Still drop — no picture/dialogue to land on.
            continue
    if not kept:
        return items
    return kept


def finalize_recap_plan_beats(
    beats: Sequence[Mapping[str, Any]],
    pack: Mapping[str, Any],
    *,
    duration_sec: float | None = None,
) -> list[dict[str, Any]]:
    """Deterministic bookends/spine/lands after the one-shot act plan — zero extra LLM."""
    duration = float(duration_sec if duration_sec is not None else pack.get("duration_sec") or 0.0)
    items = drop_op_ed_beats([dict(beat) for beat in beats or []], duration)
    items = scrub_unevidenced_beats(items, pack)
    items = ensure_beats_cover_spine(items, build_asr_vlm_spine(pack))
    items = ensure_beats_land_dialogue_outcomes(items, pack)
    items = ensure_beats_cover_silent_spans(items, pack)
    if duration > 1.0 and not beats_cover_opening(items, duration):
        deadline = opening_deadline_sec(duration)
        spine = build_asr_vlm_spine(pack)
        head = next((seg for seg in spine if (_time_span(seg.get("t")) or (1e9, 1e9))[0] <= deadline), None)
        if head is None:
            cues = [
                row
                for row in (pack.get("ocr") or [])
                if isinstance(row, Mapping) and float(row.get("start") or 0.0) <= deadline
            ]
            if cues:
                lo = float(cues[0].get("start") or 0.0)
                hi = max(float(cues[-1].get("end") or lo), lo + 8.0)
                head = {"t": [lo, min(hi, deadline + 12.0)], "asr": cues[:8], "caps": [], "speakers": []}
        if head is not None:
            items = ensure_beats_cover_spine(items, [head], cover_ratio=0.99)
    if duration > 1.0 and not beats_cover_ending(items, duration):
        _story_start, story_end = recap_story_window(duration)
        spine = build_asr_vlm_spine(pack)
        tail = None
        for seg in reversed(spine):
            span = _time_span(seg.get("t"))
            if span and span[1] >= story_end * ENDING_COVER_RATIO:
                tail = seg
                break
        if tail is not None:
            items = ensure_beats_cover_spine(items, [tail], cover_ratio=0.99)
        items = ensure_beats_land_dialogue_outcomes(items, pack)
        items = ensure_beats_cover_silent_spans(items, pack)
    if len(items) > MAX_STORY_BEATS:
        items = trim_story_beats_to_limit(items, limit=MAX_STORY_BEATS)
    return items


def plan_story_beats_by_acts(
    pack: Mapping[str, Any],
    *,
    video_id: str,
    config=None,
    language: str | None = None,
    system_prompt: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[..., Any] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Plan beats act-by-act with dense local ASR so the model cannot invent mid-episode plot."""
    cfg = config if config is not None else load_config()
    acts, struct_warnings, focus = resolve_plan_act_windows(
        pack,
        config=cfg,
        language=language,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    warnings: list[str] = list(struct_warnings)
    pack = dict(pack)
    pack["recap_focus"] = normalize_recap_focus(focus)
    if not acts:
        return "", [], list(pack.get("people") or []), ["recap_warn_plan_acts_empty"]

    def _progress(pct: int, stage: str, extra: Mapping[str, Any] | None = None) -> None:
        if progress_callback is None:
            return
        payload = {"stage": stage}
        if extra:
            payload.update(dict(extra))
        try:
            progress_callback(int(pct), payload)
        except TypeError:
            progress_callback(int(pct), stage)

    people = normalize_story_people(pack.get("people"))
    already: list[dict[str, Any]] = []
    title = ""
    act_system = resolve_recap_prompt(system_prompt, default_recap_plan_act_prompt(language))
    for index, window in enumerate(acts):
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("stopped")
        pct = 12 + int(round(20.0 * float(index) / float(max(len(acts), 1))))
        _progress(min(32, pct), "planning", {"act": index + 1, "acts": len(acts)})
        act_pack = filter_pack_to_span(pack, window[0], window[1], pad_sec=4.0)
        if pack.get("recap_focus"):
            act_pack["recap_focus"] = pack.get("recap_focus")
        dense = compact_ocr_cues_in_span(
            video_id,
            window[0],
            window[1],
            config=cfg,
            limit=PLAN_ACT_ASR_LIMIT,
        )
        if dense:
            act_pack["ocr"] = dense
        if people and not act_pack.get("people"):
            act_pack["people"] = list(people)
        parsed = _try_story_plan_llm(
            system=act_system,
            user=recap_plan_act_user_prompt(
                act_pack,
                already=already,
                act_index=index,
                act_count=len(acts),
                window=window,
            ),
            config=cfg,
            should_stop_callback=should_stop_callback,
            temperature=0.25,
            max_tokens=4096,
        )
        if parsed is None:
            warnings.append("recap_warn_plan_act")
            continue
        act_title, act_beats, act_people = parsed
        if act_title and act_title.strip() and act_title.strip() != "解说剪辑":
            title = act_title.strip()
        act_beats = clamp_beats_to_act_window(act_beats, window)
        act_beats = drop_op_ed_beats(act_beats, float(pack.get("duration_sec") or 0.0))
        act_beats = ensure_beats_cover_spine(act_beats, build_asr_vlm_spine(act_pack))
        act_beats = ensure_beats_land_dialogue_outcomes(act_beats, act_pack)
        people = merge_story_people(people, act_people)
        already = merge_story_beats(already, act_beats, allowed_windows=[window])

    already = finalize_recap_plan_beats(already, pack)
    if not already:
        warnings.append("recap_warn_plan_acts_empty")
    return title or "解说剪辑", already, people, warnings


def list_speech_dialogue_cues(video_id: str, *, config=None) -> list[dict[str, Any]]:
    """Full ASR rows for the understanding table, including speaker labels."""
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import load_dialogue_transcript

    payload = load_dialogue_transcript(str(video_id or "").strip(), config=config) or {}
    default_source = str(payload.get("asr_source") or "").strip()
    cues: list[dict[str, Any]] = []
    for index, row in enumerate(payload.get("segments") or []):
        if not isinstance(row, Mapping):
            continue
        source = str(row.get("asr_source") or default_source or "").strip()
        if not source or is_hardsub_ocr_source(source):
            continue
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        try:
            seg_index = int(row.get("seg_index", index))
        except (TypeError, ValueError):
            seg_index = index
        start = float(row.get("start") or 0.0)
        end = float(row.get("end") or start)
        cues.append(
            {
                "seg_index": seg_index,
                "start": start,
                "end": end,
                "text": text,
                "asr_source": source,
                "speaker": str(row.get("speaker") or "").strip()[:40],
            }
        )
    return cues


def recap_dialogue_status(video_id: str, *, config=None) -> dict[str, Any]:
    vid = str(video_id or "").strip()
    if not vid:
        return {"ready": False, "count": 0, "source": ""}
    from src.services.asr_index_service import is_hardsub_ocr_source
    from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

    rows = list_dialogue_transcript_summaries(config=config, video_ids=[vid])
    if not rows:
        return {"ready": False, "count": 0, "source": ""}
    source = str(rows[0].get("asr_source") or "").strip()
    if not source or is_hardsub_ocr_source(source):
        return {"ready": False, "count": 0, "source": source}
    count = int(rows[0].get("segment_count") or 0)
    return {"ready": count > 0, "count": count, "source": source}


def people_from_dialogue_speakers(cues: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    """Seed the recap people table from ASR speakers (named + clustered 声线)."""
    from src.storage.dialogue_transcript_store import is_auto_speaker_label

    named: list[dict[str, Any]] = []
    auto: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in cues or []:
        label = str(row.get("speaker") or "").strip()[:40]
        if not label or label in seen:
            continue
        seen.add(label)
        entry = {
            "id": f"s{len(seen)}",
            "label": label,
            "look": "声纹聚类" if is_auto_speaker_label(label) else "对白说话人",
        }
        if is_auto_speaker_label(label):
            auto.append(entry)
        else:
            named.append(entry)
        if len(named) + len(auto) >= 16:
            break
    # Prefer real names first; keep 声线N so plan/VO can tell talkers apart.
    return [*named, *auto][:16]


def ensure_recap_dialogue_cues(cues: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    items = list(cues or [])
    if not items:
        raise RuntimeError(
            "没有语音对白。请先在理解页提取语音 ASR。"
        )
    return items


def build_recap_pack(video_id: str, *, config=None) -> dict[str, Any]:
    from src.services.indexing_service import load_video_chunks_by_id
    from src.services.understanding_service import (
        load_evidence_bundle,
        resolve_current_media_path,
        resolve_video_context,
    )

    cfg = config if config is not None else load_config()
    evidence = load_evidence_bundle(video_id, config=cfg, mode=UNDERSTANDING_MODE_MOTION) or {}
    video = dict(evidence.get("video") or {})
    duration = float(video.get("duration_sec") or 0.0)
    stored = str(video.get("video_path") or "")
    video_path = resolve_current_media_path(video_id, stored=stored, config=cfg)
    if not duration or not video_path:
        try:
            context = resolve_video_context(video_id, config=cfg, probe_duration=not duration)
        except Exception:
            context = {}
        if not video_path:
            video_path = str(context.get("video_path") or "")
        if not duration:
            duration = float(context.get("duration_sec") or 0.0)
    ocr = compact_ocr_cues(video_id, config=cfg, limit=RECAP_OCR_LIMIT)
    ensure_recap_dialogue_cues(ocr)
    index_rows = compact_index_chunks(load_video_chunks_by_id(video_id, cfg))
    motion_rows = compact_motion_chunks(evidence) if evidence else []
    if index_rows:
        chunks = overlay_motion_captions(index_rows, motion_rows)
    else:
        chunks = motion_rows
    if not chunks:
        raise RuntimeError("没有可用分段。请先索引该视频。")
    chunks = apply_recap_skip_marks(chunks, ocr, duration)
    return {
        "video_id": video_id,
        "video_path": video_path,
        "duration_sec": duration,
        "chunks": chunks,
        "ocr": ocr,
        "ocr_source": "asr",
        "people": people_from_dialogue_speakers(ocr),
    }


def recap_plan_user_prompt(pack: Mapping[str, Any]) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    _story_start, story_end = recap_story_window(duration)
    target = recap_target_sec(duration)
    seeded = list(pack.get("people") or [])
    name_line = (
        "people 已有稳定称呼（含用户命名与声线聚类）。event/口播主语优先跟 asr.speaker / people.label 走；"
        "声线N 可先当临时称呼；可用男主/女主/发色外号，但禁止用外号顶替已有真名/用户命名。\n"
        if seeded
        else "先列 people（稳定称呼，可用男主/女主/黄毛/蓝毛等）；无人名再用画面特征。\n"
    )
    return (
        f"原片时长 {duration:.0f} 秒。请规划有证据支撑的故事线大纲 beats（有 asr/cap 就写，条数不设上限），不要写 clips。\n"
        f"从 0 秒开始覆盖开场，正片在大约 {story_end:.0f} 秒结束（片尾曲之前）。\n"
        f"【证据优先】asr/cap 撑得住才写；台词密就写密，禁止为省条数砍收束。禁止稀薄提纲、禁止大段无节拍空档。\n"
        f"自检：只读全部 event 必须能听成有头有尾的故事（进入→展开→高潮→收束）。相邻纲要必须递进或转场。成片目标约 {target:.0f} 秒（软上限；禁止删进入/收束/因果来凑时长）。\n"
        "进入新活动/新空间前必须有进入拍（赶到现场、入座开始、走进房间等）；禁止直接蹦到场内「某人惊讶了」或场内结果（全勾完了/结果出来了）。\n"
        "相邻场面或活动性质变了时，中间必须有进入/离开过渡 beat；禁止上一段刚结束下一句就直接写下一段场内结果。\n"
        "每段新小剧场：进入 → 中间过程 → 落点都要有；对白已讲清的答应/拒绝/决定/胜负必须成落点，禁止讲完过程不写结果。\n"
        "禁止孤立反应句当大纲（XX惊讶了/愣住了）；先有触发事件，再写局面变化。\n"
        "高潮/对决/身份揭晓/胜负分晓 importance≥0.85，禁止跳过最精彩的冲突。\n"
        "短而关键的动作（失手、得手、致命一击等）必须各自成条且高权重，禁止因只有几秒就并进前后大段。\n"
        "对白骨架的前后因果不得跳空：后果与起因各自成 beat，禁止只留两端结果。\n"
        "相邻 beats 的 t 不要留下大段无节拍空档；中段推进过程要盖住，收束也要盖住。\n"
        "同场戏按剧情递进拆拍，不要把每一次表情/反应拆成大纲条目。\n"
        + name_line
        + "不要用同一个他指两个人。\n"
        "必须有冷开场或片头曲之后的第一场戏，不要因为去 OP 把开头剧情切掉。\n"
        "不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。asr 是叙事骨架。chunks 可能只有时间没有 cap；有 cap 才是看见的变化。skip=op_ed 不要用。\n"
        "asr[].speaker 非空=谁在说，绝对证据。不要把这句安到别人身上。空的且对白也无人名时才用画面特征称呼。\n"
        "对白只确认说过的话。人名只有自报或当面称呼才能用，且整集只绑同一个人；禁止从 people 表乱抓名字张冠李戴。\n"
        "event 写成故事线纲要句（谁做了什么、局面怎么变），且能被画面/对白核对；禁止空洞主题句；禁止「XX说/觉得/认为」；禁止单独「XX惊讶了」。\n"
        "每条 beat 必须带 evidence_required（1–4 个：人物/动作/反应/物品/对话/变化/场面）和 needed_visual，供选镜找证据。\n"
        "分清主语宾语：谁找到谁的名字必须写清；禁止并成「找到了两人名字」又自相矛盾。\n"
        "必须包含设定/空间、角色侧面。换场/换冲突必须有过渡 beat；同场也要递进，禁止高潮直接跳到下一场。\n"
        "t 填该 beat 在原片中大约落在哪一段。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "ed_before_sec": story_end,
                "people": seeded,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def recap_user_prompt(
    pack: Mapping[str, Any],
    beats: list[Mapping[str, Any]] | None = None,
    *,
    used_src: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    duration = float(pack.get("duration_sec") or 0.0)
    planned = list(beats or [])
    target = recap_target_sec(duration)
    used = list(used_src or [])
    used_line = (
        "【已用画面】下面 used_src 已占用，禁止再剪重叠超过约三成的同一段原片（连续复用更禁止）。\n"
        if used
        else "【已用画面】本段若多刀，每刀 src 不得互相大面积重叠；更禁止连着几刀同一画面。\n"
    )
    return (
        f"原片时长 {duration:.0f} 秒。成片目标约 {target:.0f} 秒（按原片比例，约 3–8 分钟，作软上限：不要为凑分钟注水）。本段 beats 全部都要剪进去。\n"
        f"本段 beats 配额合计 {sum(float(item.get('budget_sec') or 0.0) for item in planned):.0f} 秒：每条 beat 的进入/推进/收束画面都要有；低权重可短，不可省略进入与落点；不要漏拍、不要注水。\n"
        "先按 beats 找证据画面：id、event、vo=已写好的解说稿、evidence_required、importance、budget_sec=这拍成片配额上限、shots=建议刀数、needed_visual、t=原片范围。\n"
        "【硬约束】每条 clip 的 src_in/src_out 必须落在该 beat.t 内（允许前后各约 10 秒）；禁止跨到别的 beat 时间去「借」画面。\n"
        + used_line
        + "画面必须服务 beat.vo：优先选 cap 能证明这段旁白的 chunk；无 vo 时才退回按 event/evidence_required 选。"
        "无 cap 的 chunk 只能当时间兜底，reason 禁止瞎猜看见了什么；证据对不上就标弱证据，不要硬编。\n"
        "禁止改写 beat 事件或旁白去迁就画面。\n"
        "不要输出 vo 字段；正式旁白已在 beat.vo，铺字幕阶段只润色。\n"
        "同一 beat 的相邻镜头必须有新的视觉信息，不要用近似镜头重复同一事件，也不要把两刀粘成一条长镜头。\n"
        "shots>=2 时后几刀优先特写/反应，role=insert，不要为了赶时间并进主线。"
        "insert 必须贴着同一 beat 的主线动作与 beat.t：优先同 chunk/紧邻 chunk，紧跟主镜之后。"
        "禁止整段复用同一 src_in/src_out；禁止把别的 beat 已经用过的画面再剪一遍；允许动作后紧挨着的反应特写（可与主镜同 chunk，但 src 区间仍须错开）。"
        "禁止为了凑 insert 去选远晚于该 beat.t 的表情/特写。\n"
        "相邻 beats 换场/换人/换冲突时必须单独留 role=bridge 过渡镜（离开/赶到/进门/场面变化），禁止并进主线导致跳远；纯无信息走路才可并进。bridge 的 reason 只交代场面，不要编新剧情。\n"
        "每条 beat 的 clips：先保证进入→关键变化→落点都有画面；合计时长贴近 vo 口播时长，再控制不超过 budget_sec；禁止「证据够了就停」只留半截。每个 clip 给 duration。\n"
        "时间最早的 beat 是开场，必须剪进去。不要选 OP/片头曲、ED/片尾曲、演职员表、下一集预告。skip=op_ed 的 chunk 不要用。只输出这些 beats 的 clips。\n"
        "chunks 是视觉证据：i=chunk_index，t=[start,end]，cap=看得见的变化。"
        "有 cap 必须优先；无 cap 时只按 asr 时间与 chunk.t 选镜，禁止瞎猜画面内容。\n"
        "reason 用 people 里的稳定称呼（优先用户命名的 speaker label）；可用男主/女主/发色外号，有真名时不要用外号顶替。"
        "不要把两个人写成同一个他。每个 clip 必须带 beat_id 和 reason。\n"
        "asr[].speaker 非空=谁在说，当事实。\n\n"
        + json.dumps(
            {
                "duration_sec": round(duration, 2),
                "people": pack.get("people") or [],
                "beats": planned,
                "used_src": used,
                "chunks": pack.get("chunks") or [],
                "asr": pack.get("ocr") or [],
            },
            ensure_ascii=False,
        )
    )


def split_beats_for_match(
    beats: list[Mapping[str, Any]],
    *,
    per_wave: int = MATCH_BEATS_PER_WAVE,
    max_span_sec: float = 140.0,
    max_gap_sec: float = 48.0,
) -> list[list[dict[str, Any]]]:
    """Group beats for Match: small waves that stay near each other in source time.

    Count alone is not enough — packing 4 beats that span half an episode still
    dumps the whole middle of the film into one prompt and the model picks
    lookalike shots from the wrong act.
    """
    items = sorted(
        (dict(beat) for beat in beats),
        key=lambda item: (
            (_time_span(item.get("t")) or (0.0, 0.0))[0],
            int(item.get("id") or 0),
        ),
    )
    size = max(1, int(per_wave or MATCH_BEATS_PER_WAVE))
    span_cap = max(40.0, float(max_span_sec or 140.0))
    gap_cap = max(12.0, float(max_gap_sec or 48.0))
    if len(items) <= 1:
        return [items] if items else []

    waves: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    wave_lo: float | None = None
    wave_hi: float | None = None
    for beat in items:
        span = _time_span(beat.get("t"))
        if not current:
            current = [beat]
            if span:
                wave_lo, wave_hi = span[0], span[1]
            continue
        start_new = False
        if len(current) >= size:
            start_new = True
        elif span and wave_lo is not None and wave_hi is not None:
            if span[1] - wave_lo > span_cap:
                start_new = True
            elif span[0] - wave_hi > gap_cap:
                start_new = True
        if start_new:
            waves.append(current)
            current = [beat]
            wave_lo, wave_hi = (span[0], span[1]) if span else (None, None)
            continue
        current.append(beat)
        if span:
            wave_lo = span[0] if wave_lo is None else min(wave_lo, span[0])
            wave_hi = span[1] if wave_hi is None else max(wave_hi, span[1])
    if current:
        waves.append(current)
    return waves


def missing_match_beats(
    beats: list[Mapping[str, Any]],
    cuts: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    have_ids = {
        int(cut.get("beat_id"))
        for cut in cuts
        if cut.get("beat_id") is not None
    }
    missing: list[dict[str, Any]] = []
    for beat in beats:
        try:
            beat_id = int(beat.get("id"))
        except (TypeError, ValueError):
            beat_id = None
        if beat_id is not None and beat_id in have_ids:
            continue
        span = _time_span(beat.get("t"))
        covered = False
        if span:
            for cut in cuts:
                try:
                    clip_span = (float(cut.get("src_in")), float(cut.get("src_out")))
                except (TypeError, ValueError):
                    continue
                if _overlap_sec(clip_span, span) > 0.5:
                    covered = True
                    break
        if not covered:
            missing.append(dict(beat))
    return missing


def _coverage_pin_ids(beats: list[Mapping[str, Any]]) -> set[int]:
    by_time = sorted(
        beats,
        key=lambda item: ((_time_span(item.get("t")) or (0.0, 0.0))[0], int(item.get("id") or 0)),
    )
    pins: set[int] = set()
    if by_time:
        pins.add(int(by_time[0].get("id") or 0))
        pins.add(int(by_time[-1].get("id") or 0))
    for beat in beats:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        if float(beat.get("importance") or 0.0) >= 0.65:
            pins.add(beat_id)
    pins.update(_texture_pin_ids(beats))
    return {pin for pin in pins if pin}


def _is_texture_beat(beat: Mapping[str, Any]) -> bool:
    evidence = " ".join(str(tag) for tag in (beat.get("evidence_required") or []))
    body = f"{beat.get('event') or ''} {beat.get('needed_visual') or ''} {evidence}"
    return bool(_TEXTURE_BEAT_RE.search(body))


def _texture_pin_ids(beats: Sequence[Mapping[str, Any]], *, limit: int = 3) -> set[int]:
    """Keep a few setting / character / scene-change beats so allocate does not drop them all."""
    textured: list[tuple[float, int]] = []
    for beat in beats:
        if not _is_texture_beat(beat):
            continue
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id <= 0:
            continue
        start = (_time_span(beat.get("t")) or (0.0, 0.0))[0]
        textured.append((start, beat_id))
    if not textured:
        return set()
    textured.sort()
    if len(textured) <= limit:
        return {beat_id for _start, beat_id in textured}
    picks = {textured[0][1], textured[-1][1]}
    mid = textured[len(textured) // 2][1]
    picks.add(mid)
    return picks


def _ensure_pinned_rows(
    keep: list[tuple[float, float, dict[str, Any]]],
    scored: list[tuple[float, float, dict[str, Any]]],
    pin_ids: set[int],
) -> list[tuple[float, float, dict[str, Any]]]:
    rows = list(keep)
    have = {int(row[2].get("id") or 0) for row in rows}
    for row in scored:
        beat_id = int(row[2].get("id") or 0)
        if beat_id not in pin_ids or beat_id in have:
            continue
        if len(rows) >= MAX_PLAN_BEATS:
            drop_at = None
            for index in range(len(rows) - 1, -1, -1):
                other_id = int(rows[index][2].get("id") or 0)
                if other_id not in pin_ids:
                    drop_at = index
                    break
            if drop_at is None:
                continue
            dropped = rows.pop(drop_at)
            have.discard(int(dropped[2].get("id") or 0))
        rows.append(row)
        have.add(beat_id)
    return rows


def _normalize_vo_compare(text: str) -> str:
    return _VO_WHITESPACE_RE.sub("", str(text or "").strip().lower())


def _vo_overlaps_source_line(vo: str, source: str, *, min_chars: int = 6) -> bool:
    left = _normalize_vo_compare(vo)
    right = _normalize_vo_compare(source)
    if len(left) < min_chars or len(right) < min_chars:
        return False
    if left in right or right in left:
        return True
    return _text_similarity(left, right) >= 0.72


def scrub_verbatim_source_dialogue_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Drop Japanese kana / near-verbatim ASR pasted into VO."""
    out: list[dict[str, Any]] = []
    for clip in clips or []:
        row = dict(clip)
        vo = str(row.get("vo") or "").strip()
        if not vo:
            out.append(row)
            continue

        asr_texts: list[str] = []
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or src_in)
        except (TypeError, ValueError):
            src_in, src_out = 0.0, 0.0
        if pack is not None:
            evidence = _evidence_for_source_span(pack, src_in, src_out, asr_limit=12, cap_limit=1)
            asr_texts = [str(item.get("text") or "") for item in evidence.get("asr") or []]

        # Heavy Japanese → drop the whole line (source dialogue pasted as VO).
        kana_hits = _JP_KANA_RE.findall(vo)
        if len(kana_hits) >= 3 or (kana_hits and len(kana_hits) / max(len(vo), 1) >= 0.2):
            row["vo"] = ""
            out.append(row)
            continue

        def _keep_quote(match: re.Match[str]) -> str:
            quoted = str(match.group(1) or "").strip()
            if not quoted:
                return ""
            if _has_japanese_kana(quoted):
                return ""
            if any(_vo_overlaps_source_line(quoted, src) for src in asr_texts):
                return ""
            if len(quoted) > 6:
                return ""
            return match.group(0)

        cleaned = _VO_QUOTE_RE.sub(_keep_quote, vo)
        if _has_japanese_kana(cleaned):
            cleaned = _JP_KANA_RE.sub("", cleaned)
        # Strip leftover separators after kana/quote removal; keep sentence enders.
        cleaned = _VO_WHITESPACE_RE.sub(" ", cleaned).strip(" ，,.;；")
        if cleaned and any(_vo_overlaps_source_line(cleaned, src, min_chars=8) for src in asr_texts):
            cleaned = ""
        if len(re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)) < 2:
            cleaned = ""
        elif cleaned and cleaned[-1] not in "。！？!?…":
            cleaned = _punctuate_vo_sentence(cleaned)
        row["vo"] = cleaned
        out.append(row)
    return out


_SPEECH_ACT_RE = re.compile(
    r"(说|告诉|喊道|叫道|问道|答道|宣布|表示|低声|开口|下令|命令|提醒|警告|质问|反问|承认|否认|发誓)"
)


def _vo_source_span_for_scrub(
    clips: Sequence[Mapping[str, Any]],
    index: int,
) -> tuple[float, float]:
    """Widen to empty same-beat follow shots covered by spanning VO."""
    items = list(clips or [])
    clip = items[index]
    try:
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or src_in)
    except (TypeError, ValueError):
        return 0.0, 0.0
    beat_id = clip.get("beat_id")
    for nxt in items[index + 1 :]:
        if beat_id is None or nxt.get("beat_id") != beat_id:
            break
        if str(nxt.get("vo") or "").strip():
            break
        try:
            nxt_out = float(nxt.get("src_out") or 0.0)
        except (TypeError, ValueError):
            break
        src_out = max(src_out, nxt_out)
    return src_in, src_out


def _vo_evidence_window(
    clips: Sequence[Mapping[str, Any]],
    index: int,
    beats: Sequence[Mapping[str, Any]] | None = None,
    *,
    pad_sec: float = 8.0,
) -> tuple[float, float]:
    """Widen VO evidence to the beat time window so short cuts still see nearby dialogue."""
    src_in, src_out = _vo_source_span_for_scrub(clips, index)
    pad = max(0.0, float(pad_sec))
    lo, hi = src_in - pad, src_out + pad
    try:
        beat_id = int((clips[index] or {}).get("beat_id") or 0)
    except (TypeError, ValueError, IndexError):
        beat_id = 0
    beat = _beats_by_id(beats).get(beat_id) if beat_id else None
    span = _time_span((beat or {}).get("t")) if beat else None
    if span:
        lo = min(lo, span[0] - 2.0)
        hi = max(hi, span[1] + 2.0)
    if hi < lo:
        lo, hi = hi, lo
    return lo, hi


def scrub_unevidenced_vo(
    clips: Sequence[Mapping[str, Any]],
    *,
    pack: Mapping[str, Any] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Drop VO that invents speech/plot without asr/caps in the picture span."""
    if pack is None:
        # Without a pack we cannot verify evidence; leave VO untouched.
        return [dict(clip) for clip in clips or []]
    items = [dict(clip) for clip in clips or []]
    by_id = _beats_by_id(beats)
    out: list[dict[str, Any]] = []
    for index, row in enumerate(items):
        vo = str(row.get("vo") or "").strip()
        if not vo:
            out.append(row)
            continue
        src_in, src_out = _vo_evidence_window(items, index, beats)
        evidence = _evidence_for_source_span(
            pack, src_in, src_out, pad_sec=0.0, asr_limit=24, cap_limit=10
        )
        asr_rows = list(evidence.get("asr") or [])
        cap_rows = list(evidence.get("caps") or [])
        asr_blob = " ".join(str(item.get("text") or "") for item in asr_rows)
        cap_blob = " ".join(str(item.get("cap") or "") for item in cap_rows)
        has_asr = bool(asr_blob.strip())
        has_caps = bool(cap_blob.strip())
        weak = is_weak_match_clip(row)

        if not has_asr and not has_caps:
            row["vo"] = ""
            out.append(row)
            continue

        # Outline parroting with no dialogue: drop if VO ≈ event and barely matches caps.
        try:
            beat_id = int(row.get("beat_id") or 0)
        except (TypeError, ValueError):
            beat_id = 0
        event = str(row.get("event") or (by_id.get(beat_id) or {}).get("event") or "").strip()
        if (
            not has_asr
            and event
            and _text_similarity(_normalize_vo_compare(vo), _normalize_vo_compare(event)) >= 0.55
            and (
                not has_caps
                or _text_similarity(_normalize_vo_compare(vo), _normalize_vo_compare(cap_blob)) < 0.28
            )
        ):
            row["vo"] = ""
            out.append(row)
            continue

        parts = [item for item in re.split(r"(?<=[。！？!?；;])", vo) if str(item or "").strip()]
        if not parts:
            parts = [vo]
        kept: list[str] = []
        for part in parts:
            body = str(part or "").strip()
            if not body:
                continue
            quoted = bool(_VO_QUOTE_RE.search(body))
            speechy = bool(_SPEECH_ACT_RE.search(body)) or quoted
            # No dialogue at all → cannot report speech.
            if speechy and not has_asr:
                continue
            # Quoted invention: must touch source lines. Bare「XX说」narrative with asr is OK
            # (Chinese paraphrase of JP dialogue must not be nuked).
            if quoted and has_asr:
                if not _vo_overlaps_source_line(body, asr_blob, min_chars=4):
                    if _text_similarity(_normalize_vo_compare(body), _normalize_vo_compare(asr_blob)) < 0.22:
                        continue
            if weak and quoted:
                continue
            kept.append(body)
        cleaned = "".join(kept).strip(" ，,")
        if cleaned and cleaned[-1] not in "。！？!?…":
            cleaned = _punctuate_vo_sentence(cleaned)
        if len(re.sub(r"[\s\W_]+", "", cleaned, flags=re.UNICODE)) < 2:
            cleaned = ""
        row["vo"] = cleaned
        out.append(row)
    return out


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
        span = _time_span(item.get("t")) or (0.0, 0.0)
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
        payload = _loads_json_object(text)
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
        span = _time_span(beat.get("t")) or (0.0, 0.0)
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
        if importance < 0.22 and not _TEXTURE_BEAT_RE.search(event):
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


def draft_recap_vo_for_beats(
    pack: Mapping[str, Any],
    allocated: Sequence[Mapping[str, Any]],
    *,
    config=None,
    language: str | None = None,
    system_prompt: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Write beat.vo from beat-window evidence before Match. Failures leave vo empty."""
    out = [dict(beat) for beat in allocated or []]
    if not out:
        return out
    pending = [
        beat
        for beat in out
        if force or not str(beat.get("vo") or "").strip()
    ]
    if not pending:
        return out
    system = resolve_recap_prompt(
        system_prompt,
        default_recap_vo_draft_prompt(language or resolve_recap_caption_language(config)),
    )
    by_id: dict[int, dict[str, Any]] = {}
    for beat in out:
        try:
            beat_id = int(beat.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if beat_id > 0:
            by_id[beat_id] = beat
    waves = split_beats_for_match(
        pending,
        per_wave=VO_DRAFT_BEATS_PER_WAVE,
        max_span_sec=220.0,
        max_gap_sec=72.0,
    )
    prev = ""
    for wave_i, wave in enumerate(waves):
        if progress_callback:
            progress_callback(48 + min(10, wave_i), "vo_draft")
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("stopped")
        try:
            text = call_remote_llm(
                system=system,
                user=recap_vo_draft_user_prompt(pack, wave, prev_vo=prev),
                config=config,
                temperature=0.3,
                max_tokens=2048,
                should_stop_callback=should_stop_callback,
            )
            drafts = parse_vo_drafts(text, wave)
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            drafts = {}
        for beat in wave:
            try:
                beat_id = int(beat.get("id") or 0)
            except (TypeError, ValueError):
                continue
            body = str(drafts.get(beat_id) or "").strip()
            target = by_id.get(beat_id)
            if target is not None:
                target["vo"] = body
            if body:
                prev = body
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


def clamp_recap_vo_to_picture(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep match VO intact. Fitting length is the captions LLM pass."""
    return [dict(clip) for clip in clips or []]


def fit_recap_vo_picture(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep match VO intact. Fitting length is the captions LLM pass."""
    return [dict(clip) for clip in clips or []]


def parse_caption_cues(text: str, clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload = _loads_json_object(text)
    raw = payload.get("captions") if isinstance(payload, Mapping) else None
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("LLM 没有返回 captions。")
    return normalize_caption_cues(raw, clips)


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


def polish_recap_vo(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Final LLM pass: polish narration text only. Shots stay locked."""
    work = [dict(clip) for clip in clips]
    if not any(str(clip.get("vo") or "").strip() for clip in work):
        return work
    # Economy: VO-first draft already dense enough — skip another billable rewrite.
    if recap_vo_coverage_ratio(work) >= 0.82:
        if progress_callback:
            progress_callback(91, "polish_skip")
        return work
    if progress_callback:
        progress_callback(91, "polish")
    polish_system = resolve_recap_prompt(
        system_prompt,
        default_recap_polish_prompt(resolve_recap_caption_language(config)),
    )
    prev = ""
    offset = 0
    for wave in split_clips_for_captions(work):
        if not any(str(clip.get("vo") or "").strip() for clip in wave):
            offset += len(wave)
            continue
        try:
            text = call_remote_llm(
                system=polish_system,
                user=recap_vo_polish_user_prompt(wave, people=people, prev_caption=prev),
                config=config,
                temperature=0.2,
                max_tokens=2048,
                should_stop_callback=should_stop_callback,
            )
            caps = parse_vo_polish_cues(text, wave)
            stamped = apply_vo_polish_cues(wave, caps)
            for local_i, row in enumerate(stamped):
                work[offset + local_i] = row
            for clip in stamped:
                body = str(clip.get("vo") or "").strip()
                if body:
                    prev = body
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            pass
        offset += len(wave)
    work = scrub_unattested_people_names(work, people=people, pack=pack, beats=beats)
    work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
    work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
    return work


def scrub_adjacent_duplicate_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]


def scrub_restated_insert_vo(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """No-op."""
    return [dict(clip) for clip in clips or []]


def fit_recap_captions_to_tts(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    laid = [dict(clip) for clip in clips]
    # VO-first: land beat drafts before polish so a failed LLM wave cannot wipe narration.
    packed = pack_captions_for_tts(laid, use_draft=True)
    work = apply_caption_cues(laid, packed) if packed else laid
    if not laid:
        return work
    # Economy: draft already covers most of the cut — skip another full rewrite bill.
    if recap_vo_coverage_ratio(work) >= 0.82:
        if progress_callback:
            progress_callback(86, "captions_skip")
        work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
        work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
        return work
    if progress_callback:
        progress_callback(86, "captions")
    rewritten: list[dict[str, Any]] = []
    prev = ""
    offset = 0
    waves = split_clips_for_captions(laid)
    for wave in waves:
        try:
            text = call_remote_llm(
                system=resolve_recap_prompt(system_prompt, default_recap_caption_prompt(resolve_recap_caption_language(config))),
                user=recap_caption_user_prompt(
                    wave,
                    people=people,
                    prev_caption=prev,
                    beats=beats,
                    pack=pack,
                ),
                config=config,
                temperature=0.3,
                max_tokens=2048,
                should_stop_callback=should_stop_callback,
            )
            caps = parse_caption_cues(text, wave)
            for cap in caps:
                start = int(cap.get("from") or 1) + offset
                end = int(cap.get("to") or start) + offset
                cap["from"] = start
                cap["to"] = end
                prev = str(cap.get("text") or prev)
            rewritten.extend(caps)
        except UnderstandingStoppedError:
            raise
        except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
            # One bad wave must not wipe the whole caption pass.
            pass
        offset += len(wave)
    if rewritten:
        polished = apply_caption_cues(laid, rewritten)
        # Keep draft when polish emptied a previously voiced unit.
        for index, clip in enumerate(polished):
            if str(clip.get("vo") or "").strip():
                continue
            seed = str(
                work[index].get("vo")
                or laid[index].get("vo")
                or laid[index].get("vo_draft")
                or ""
            ).strip()
            if seed:
                clip["vo"] = seed
                clip.setdefault("vo_draft", seed)
        work = polished
    work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
    work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
    return work


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
        if _looks_like_insert_cut(clip) or _is_bridge_clip(clip):
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
        if picture < MIN_STANDALONE_CLIP_SEC and not _looks_like_insert_cut(items[index]):
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


def fill_recap_vo_gaps(
    clips: list[Mapping[str, Any]],
    *,
    config=None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> list[dict[str, Any]]:
    """Fill shots that still have no narration after the caption pass."""
    work = [dict(clip) for clip in clips]
    captions = pack_captions_for_tts(work)
    gap_indices = recap_gap_clip_indices(work, captions)
    if not gap_indices:
        return work
    if progress_callback:
        progress_callback(88, "gaps")
    try:
        text = call_remote_llm(
            system=default_recap_gap_prompt(resolve_recap_caption_language(config)),
            user=recap_gap_user_prompt(
                work,
                captions,
                gap_indices,
                people=people,
                beats=beats,
                pack=pack,
            ),
            config=config,
            temperature=0.3,
            max_tokens=2048,
            should_stop_callback=should_stop_callback,
        )
        fills = parse_gap_fills(text, work, allowed=set(gap_indices))
        if fills:
            work = apply_gap_fills(work, fills)
    except UnderstandingStoppedError:
        raise
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    work = scrub_verbatim_source_dialogue_vo(work, pack=pack)
    work = scrub_unevidenced_vo(work, pack=pack, beats=beats)
    return work


def parse_cut_list(text: str, pack: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    try:
        payload = _loads_cut_list_json(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "语言模型返回的剪辑表不是合法 JSON（常见于漏逗号或镜头太多被截断）。请再生成一次。"
        ) from exc
    if not isinstance(payload, dict):
        raise RuntimeError("LLM 输出不是 JSON 对象。")
    title = str(payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    return title, normalize_cut_list(payload, pack)


def _probe_media(video_path: str) -> dict[str, Any]:
    from src.media.probe import _probe_video_stream_with_opencv

    info = _probe_video_stream_with_opencv(video_path)
    if not info.get("fps"):
        info["fps"] = 24.0
    if not info.get("width"):
        info["width"] = 1920
    if not info.get("height"):
        info["height"] = 1080
    return info


def resolve_recap_prompt(text: str | None, default: str) -> str:
    body = str(text or "").strip()
    return body or default


def resolve_recap_caption_language(config=None) -> str:
    cfg = config if isinstance(config, Mapping) else load_config()
    understanding = cfg.get("understanding") if isinstance(cfg, Mapping) else None
    remote = understanding.get("remote_vlm") if isinstance(understanding, Mapping) else None
    if isinstance(remote, Mapping):
        return normalize_caption_language(remote.get("caption_language"))
    return CAPTION_LANGUAGE_ZH


def resolve_recap_system_prompt(text: str | None, language: str | None = None) -> str:
    return resolve_recap_prompt(text, default_recap_match_prompt(language))


def _try_story_plan_llm(
    *,
    system: str,
    user: str,
    config,
    should_stop_callback: Callable[[], bool] | None,
    temperature: float,
    max_tokens: int,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]] | None:
    try:
        text = call_remote_llm(
            system=system,
            user=user,
            config=config,
            temperature=temperature,
            max_tokens=max_tokens,
            should_stop_callback=should_stop_callback,
        )
        return parse_story_plan(text)
    except RuntimeError:
        return None


def normalize_recap_start_from(value: str | None) -> str:
    key = str(value or RECAP_START_PLAN).strip().lower()
    if key in {RECAP_START_MATCH, "matching", "match_only", "match-only", "2"}:
        return RECAP_START_MATCH
    if key in {RECAP_START_CAPTIONS, "caption", "gaps", "3"}:
        return RECAP_START_CAPTIONS
    if key in {RECAP_START_PLAN_ONLY, "plan-only", "planonly"}:
        return RECAP_START_PLAN_ONLY
    return RECAP_START_PLAN


def save_recap_clip_vo(
    video_path: str,
    clip_index: int,
    text: str,
    *,
    video_id: str = "",
    rewrite_srt: bool = True,
) -> dict[str, Any]:
    """Hand-edit one clip's narration and rewrite cuts (+ optional SRT). Not an NLE trim."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    try:
        index = int(clip_index)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无效的镜头序号。") from exc
    if index < 0 or index >= len(clips):
        raise RuntimeError("镜头序号超出范围。")
    body = str(text or "").strip()
    clip = clips[index]
    clip["vo"] = body
    clip["vo_draft"] = body
    tl_in = float(clip.get("tl_in") or 0.0)
    tl_out = float(clip.get("tl_out") or tl_in)
    if body:
        budget = _max_picture_for_vo(body)
        vo_end = min(tl_out, tl_in + max(budget, 0.5)) if budget > 0 else tl_out
        if vo_end > tl_in + 0.04:
            clip["vo_tl_in"] = round(tl_in, 3)
            clip["vo_tl_out"] = round(vo_end, 3)
        else:
            clip.pop("vo_tl_in", None)
            clip.pop("vo_tl_out", None)
    else:
        clip.pop("vo_tl_in", None)
        clip.pop("vo_tl_out", None)
    clips[index] = clip
    dest = recap_cuts_path_for_video(media)
    next_payload = dict(payload)
    next_payload["clips"] = _recap_clip_records(clips)
    next_payload["clip_count"] = len(clips)
    if clips:
        next_payload["duration_sec"] = float(clips[-1].get("tl_out") or next_payload.get("duration_sec") or 0.0)
    cuts_path = write_cuts_json(next_payload, dest)
    srt_path = ""
    if rewrite_srt:
        stem = Path(os.path.abspath(os.path.expanduser(media))).stem
        srt_dest = Path(os.path.abspath(os.path.expanduser(media))).parent / f"{stem}_recap.srt"
        srt_path = str(write_srt(clips, srt_dest))
    return {
        "ok": True,
        "cuts_path": str(cuts_path),
        "srt_path": srt_path,
        "clip_index": index,
        "vo": body,
        "clips": clips,
    }


def rewrite_recap_clip_caption(
    video_path: str,
    clip_index: int,
    *,
    video_id: str = "",
    config=None,
    system_prompt: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """LLM-rewrite narration for one locked shot; writes cuts + SRT. Does not rematch."""
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")
    payload = load_recap_cuts(media, video_id=video_id)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = [dict(clip) for clip in list(payload.get("clips") or [])]
    try:
        index = int(clip_index)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无效的镜头序号。") from exc
    if index < 0 or index >= len(clips):
        raise RuntimeError("镜头序号超出范围。")

    cfg = config if config is not None else load_config()
    vid = str(video_id or payload.get("video_id") or "").strip()
    beats_payload = load_recap_beats(media, video_id=vid) or {}
    beats = list(beats_payload.get("beats") or [])
    people = list(beats_payload.get("people") or [])
    pack: dict[str, Any] | None = None
    if vid:
        try:
            pack = build_recap_pack(vid, config=cfg)
        except Exception:
            pack = None
    prev = ""
    for cursor in range(index - 1, -1, -1):
        body = str(clips[cursor].get("vo") or "").strip()
        if body:
            prev = body
            break
    wave = [dict(clips[index])]
    text = call_remote_llm(
        system=resolve_recap_prompt(system_prompt, default_recap_caption_prompt(resolve_recap_caption_language(config))),
        user=recap_caption_user_prompt(
            wave,
            people=people,
            prev_caption=prev,
            beats=beats,
            pack=pack,
        ),
        config=cfg,
        temperature=0.3,
        max_tokens=1024,
        should_stop_callback=should_stop_callback,
    )
    caps = parse_caption_cues(text, wave)
    if not caps:
        raise RuntimeError("LLM 没有返回可用旁白。")
    new_vo = str(caps[0].get("text") or "").strip()
    if not new_vo:
        raise RuntimeError("LLM 返回的旁白为空。")
    saved = save_recap_clip_vo(
        media,
        index,
        new_vo,
        video_id=vid,
        rewrite_srt=True,
    )
    saved["rewritten"] = True
    return saved


def rematch_recap_user_prompt(
    pack: Mapping[str, Any],
    *,
    beat: Mapping[str, Any],
    prev_beat: Mapping[str, Any] | None = None,
    next_beat: Mapping[str, Any] | None = None,
    prev_vo: Sequence[str] | None = None,
    next_vo: Sequence[str] | None = None,
    old_cuts: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Match prompt for one beat with locked neighbor context (read-only)."""
    target_id = int(beat.get("id"))
    context_beats = [item for item in (prev_beat, beat, next_beat) if item]
    base = recap_user_prompt(pack, context_beats)
    old_rows = []
    for clip in old_cuts or []:
        old_rows.append(
            {
                "src_in": clip.get("src_in"),
                "src_out": clip.get("src_out"),
                "reason": str(clip.get("reason") or "")[:80],
                "role": str(clip.get("role") or ""),
                "vo": str(clip.get("vo") or "")[:120],
            }
        )
    extra = {
        "rematch": {
            "target_beat_id": target_id,
            "instruction": (
                f"这是定点重选镜：只输出 beat_id={target_id} 的 clips。"
                "前后拍已锁定，禁止输出其它 beat_id，禁止改写前后旁白。"
                "结合 asr 台词与 chunks.cap 画面证据重选；不要凭空编表情/动机。"
                "旧刀仅作参考，可以整段换掉，但事件必须仍是该 beat.event。"
            ),
            "locked_prev_vo": list(prev_vo or []),
            "locked_next_vo": list(next_vo or []),
            "old_cuts_for_target": old_rows,
        }
    }
    return base + "\n\n" + json.dumps(extra, ensure_ascii=False)


def caption_recap_clip_indices(
    clips: list[Mapping[str, Any]],
    indices: Sequence[int],
    *,
    config=None,
    system_prompt: str | None = None,
    people: Sequence[Mapping[str, Any]] | None = None,
    beats: Sequence[Mapping[str, Any]] | None = None,
    pack: Mapping[str, Any] | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
) -> list[dict[str, Any]]:
    """Caption selected clips in place without splitting underfilled shots."""
    work = [dict(clip) for clip in clips]
    ordered = sorted({int(index) for index in indices if 0 <= int(index) < len(work)})
    if not ordered:
        return work
    wave = [dict(work[index]) for index in ordered]
    prev = ""
    first = ordered[0]
    for cursor in range(first - 1, -1, -1):
        body = str(work[cursor].get("vo") or "").strip()
        if body:
            prev = body
            break
    text = call_remote_llm(
        system=resolve_recap_prompt(system_prompt, default_recap_caption_prompt(resolve_recap_caption_language(config))),
        user=recap_caption_user_prompt(
            wave,
            people=people,
            prev_caption=prev,
            beats=beats,
            pack=pack,
        ),
        config=config,
        temperature=0.3,
        max_tokens=2048,
        should_stop_callback=should_stop_callback,
    )
    caps = parse_caption_cues(text, wave)
    stamped = apply_caption_cues(wave, caps)
    for local_i, global_i in enumerate(ordered):
        row = dict(work[global_i])
        row["vo"] = str(stamped[local_i].get("vo") or "").strip()
        row["vo_draft"] = str(
            stamped[local_i].get("vo_draft")
            or stamped[local_i].get("vo")
            or row.get("vo_draft")
            or ""
        ).strip()
        if stamped[local_i].get("vo_tl_in") is not None:
            row["vo_tl_in"] = stamped[local_i].get("vo_tl_in")
        else:
            row.pop("vo_tl_in", None)
        if stamped[local_i].get("vo_tl_out") is not None:
            row["vo_tl_out"] = stamped[local_i].get("vo_tl_out")
        else:
            row.pop("vo_tl_out", None)
        work[global_i] = row
    return work


def rematch_recap_beat(
    video_id: str,
    beat_id: int,
    *,
    video_path: str = "",
    config=None,
    system_prompt: str | None = None,
    caption_prompt: str | None = None,
    fill_captions: bool = True,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Rematch shots for one beat, splice into saved cuts, optionally caption those shots."""
    cfg = config if config is not None else load_config()
    vid = str(video_id or "").strip()
    if not vid:
        raise RuntimeError("缺少 video_id。")
    try:
        target_beat_id = int(beat_id)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("无效的节拍 id。") from exc
    if target_beat_id <= 0:
        raise RuntimeError("无效的节拍 id。")

    def _progress(value: int, stage: str) -> None:
        if progress_callback:
            progress_callback(int(value), str(stage))

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("Recap stopped by user")

    pack = build_recap_pack(vid, config=cfg)
    from src.services.understanding_service import resolve_current_media_path

    media = resolve_current_media_path(
        vid,
        stored=str(video_path or pack.get("video_path") or ""),
        config=cfg,
    )
    pack["video_path"] = media
    if not media or not os.path.isfile(media):
        raise RuntimeError(f"找不到原片：{media or '(空路径)'}")

    beats_payload = load_recap_beats(media, video_id=vid)
    if not beats_payload:
        raise RuntimeError("没有已保存的剧情规划。")
    allocated = list(beats_payload.get("beats") or [])
    people = normalize_story_people(beats_payload)
    pack["people"] = people
    prev_beat, beat, next_beat = _neighbor_beats_for_rematch(allocated, target_beat_id)

    saved_cuts = load_recap_cuts(media, video_id=vid)
    if not saved_cuts:
        raise RuntimeError("还没有选镜表。")
    existing = restore_recap_vo_text(list(saved_cuts.get("clips") or []))
    title = str(saved_cuts.get("title") or beats_payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    prev_vo, next_vo, old_cuts = _locked_vo_context(existing, target_beat_id)
    other_before = [dict(clip) for clip in existing if _clip_beat_id(clip) != target_beat_id]

    _raise_if_stopped()
    _progress(20, "motion_gaps")
    # Include neighbor beat windows so ASR/caps around the cut are visible to the matcher.
    context_beats = [item for item in (prev_beat, beat, next_beat) if item]
    pack, _motion_warns, motion_filled = fill_recap_motion_for_beats(
        vid,
        pack,
        context_beats,
        config=cfg,
        should_stop_callback=should_stop_callback,
    )
    pack["video_path"] = media

    _raise_if_stopped()
    _progress(45, "matching")
    match_system = resolve_recap_system_prompt(system_prompt, resolve_recap_caption_language(cfg))
    wave_pack = pack_for_beats(pack, context_beats, pad_sec=36.0)
    match_text = call_remote_llm(
        system=match_system,
        user=rematch_recap_user_prompt(
            wave_pack,
            beat=beat,
            prev_beat=prev_beat,
            next_beat=next_beat,
            prev_vo=prev_vo,
            next_vo=next_vo,
            old_cuts=old_cuts,
        ),
        config=cfg,
        temperature=0.35,
        max_tokens=4096,
        should_stop_callback=should_stop_callback,
    )
    _wave_title, wave_cuts = parse_cut_list(match_text, pack)
    del _wave_title
    normalized = _filter_rematch_cuts_to_beat(
        stash_match_vo_as_draft(wave_cuts),
        beat,
        pack=pack,
    )
    if not normalized:
        raise RuntimeError("选镜没有返回可用镜头（或不在该拍时间窗内）。")
    # Light refine only: avoid coalesce sorting/dropping that can erase rematch shots.
    normalized = clamp_cuts_to_beat_window(normalized, pack, [beat])
    normalized = snap_cuts_to_capped_chunks(normalized, pack, [beat])
    normalized = clamp_insert_cuts_to_beat(normalized, pack, [beat])
    normalized = dedupe_overlapping_recap_cuts(normalized)
    normalized = _filter_rematch_cuts_to_beat(normalized, beat, pack=pack)
    if not normalized:
        raise RuntimeError("选镜结果无效。")
    normalized = annotate_recap_match_quality(
        normalized, [beat], pack, people, config=cfg
    )

    merged = _splice_recap_beat_cuts(existing, normalized, target_beat_id)
    other_after = [clip for clip in merged if _clip_beat_id(clip) != target_beat_id]
    if len(other_after) != len(other_before):
        raise RuntimeError(
            f"重选镜保护失败：其它拍镜头数从 {len(other_before)} 变成 {len(other_after)}，已中止写入。"
        )
    for left, right in zip(other_before, other_after):
        if round(float(left.get("src_in") or 0.0), 3) != round(float(right.get("src_in") or 0.0), 3):
            raise RuntimeError("重选镜保护失败：其它拍原片起点被改动，已中止写入。")
        if str(left.get("vo") or "") != str(right.get("vo") or ""):
            raise RuntimeError("重选镜保护失败：其它拍旁白被改动，已中止写入。")

    info = _probe_media(media)
    laid = layout_clips_on_timeline(
        merged,
        fps=float(info.get("fps") or saved_cuts.get("fps") or 24.0),
    )
    beat_indices = [
        index
        for index, clip in enumerate(laid)
        if _clip_beat_id(clip) == target_beat_id
    ]

    if fill_captions and beat_indices:
        _raise_if_stopped()
        _progress(75, "captions")
        laid = caption_recap_clip_indices(
            laid,
            beat_indices,
            config=cfg,
            system_prompt=caption_prompt,
            people=people,
            beats=allocated,
            pack=pack,
            should_stop_callback=should_stop_callback,
        )

    _progress(90, "writing")
    cuts_path = write_recap_cuts_file(
        recap_cuts_path_for_video(media),
        title=title,
        video_path=media,
        video_id=vid,
        info=info,
        laid_out=laid,
        beats_path=recap_beats_path_for_video(media),
        stage=RECAP_START_CAPTIONS if fill_captions else RECAP_START_MATCH,
    )
    stem = Path(media).stem
    srt_path = write_srt(laid, Path(media).parent / f"{stem}_recap.srt")
    return {
        "ok": True,
        "title": title,
        "video_id": vid,
        "beat_id": target_beat_id,
        "clip_count": len(laid),
        "beat_clip_count": len(beat_indices),
        "duration_sec": laid[-1]["tl_out"] if laid else 0,
        "cuts_path": str(cuts_path),
        "srt_path": str(srt_path),
        "motion_filled": int(motion_filled),
        "clips": laid,
    }


def rematch_weak_recap_beats(
    video_id: str,
    *,
    video_path: str = "",
    beat_ids: Sequence[int] | None = None,
    max_beats: int = MAX_WEAK_REMATCH_BEATS,
    config=None,
    system_prompt: str | None = None,
    caption_prompt: str | None = None,
    fill_captions: bool = True,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Rematch every weak-match beat (or an explicit beat id list), sequentially."""
    cfg = config if config is not None else load_config()
    vid = str(video_id or "").strip()
    if not vid:
        raise RuntimeError("缺少 video_id。")
    media = str(video_path or "").strip()
    if not media:
        raise RuntimeError("找不到原片路径。")

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("stopped")

    def _progress(value: int, stage: str) -> None:
        if progress_callback:
            progress_callback(int(value), str(stage))

    payload = load_recap_cuts(media, video_id=vid)
    if not payload:
        raise RuntimeError("还没有选镜表。")
    clips = list(payload.get("clips") or [])
    targets = [int(item) for item in (beat_ids or list_weak_match_beat_ids(clips)) if int(item) > 0]
    # De-dupe while preserving order.
    ordered: list[int] = []
    seen: set[int] = set()
    for beat_id in targets:
        if beat_id in seen:
            continue
        seen.add(beat_id)
        ordered.append(beat_id)
    limit = max(1, int(max_beats or MAX_WEAK_REMATCH_BEATS))
    skipped = max(0, len(ordered) - limit)
    ordered = ordered[:limit]
    if not ordered:
        raise RuntimeError("没有弱证据拍需要重选。")

    rematched: list[int] = []
    failed: list[dict[str, Any]] = []
    last: dict[str, Any] = {}
    total = len(ordered)
    for index, beat_id in enumerate(ordered):
        _raise_if_stopped()
        pct = 8 + int(round(84.0 * float(index) / float(max(total, 1))))
        _progress(min(90, pct), f"weak_rematch:{index + 1}/{total}:{beat_id}")
        try:
            last = rematch_recap_beat(
                vid,
                beat_id,
                video_path=media,
                config=cfg,
                system_prompt=system_prompt,
                caption_prompt=caption_prompt,
                fill_captions=fill_captions,
                should_stop_callback=should_stop_callback,
                progress_callback=None,
            )
            rematched.append(beat_id)
        except UnderstandingStoppedError:
            raise
        except Exception as exc:
            failed.append({"beat_id": beat_id, "error": str(exc)})
    _progress(100, "writing")
    refreshed = load_recap_cuts(media, video_id=vid) or last
    remaining = list_weak_match_beat_ids(list((refreshed or {}).get("clips") or []))
    return {
        "ok": True,
        "video_id": vid,
        "beat_ids": rematched,
        "failed": failed,
        "skipped": skipped,
        "requested": total,
        "remaining_weak": remaining,
        "clip_count": len(list((refreshed or {}).get("clips") or [])),
        "cuts_path": str((refreshed or {}).get("cuts_path") or last.get("cuts_path") or ""),
        "srt_path": str(last.get("srt_path") or ""),
        "duration_sec": float((refreshed or {}).get("duration_sec") or last.get("duration_sec") or 0.0),
    }


def save_recap_plan_edits(
    video_path: str,
    *,
    video_id: str,
    title: str,
    beats: Sequence[Mapping[str, Any]],
    people: Sequence[Mapping[str, Any]] | None = None,
    duration_sec: float = 0.0,
    chunks: Sequence[Mapping[str, Any]] | None = None,
    target_sec: float | None = None,
) -> Path:
    duration = float(duration_sec or 0.0)
    target = float(target_sec) if target_sec is not None else recap_target_sec(duration)
    allocated = allocate_beat_budgets(
        list(beats),
        chunks=list(chunks or []),
        target_sec=target,
        duration_sec=duration,
    )
    return write_recap_beats_file(
        recap_beats_path_for_video(video_path),
        title=str(title or "").strip() or "解说剪辑",
        video_id=str(video_id or "").strip(),
        allocated=allocated,
        people=normalize_story_people({"people": list(people or [])}),
    )


def generate_recap_timeline(
    video_id: str,
    dest_dir: str,
    *,
    config=None,
    system_prompt: str | None = None,
    plan_prompt: str | None = None,
    caption_prompt: str | None = None,
    polish_prompt: str | None = None,
    start_from: str | None = None,
    should_stop_callback: Callable[[], bool] | None = None,
    progress_callback: Callable[..., None] | None = None,
    chunk_completed_callback: Callable[..., None] | None = None,
) -> dict[str, Any]:
    cfg = config if config is not None else load_config()
    llm = get_remote_llm_settings(cfg)
    if not str(llm.get("model") or "").strip():
        raise RuntimeError("尚未配置语言模型。请先在模型服务 → LLM 里填写并保存。")
    pack = build_recap_pack(video_id, config=cfg)
    from src.services.understanding_service import resolve_current_media_path

    video_path = resolve_current_media_path(
        video_id,
        stored=str(pack.get("video_path") or ""),
        config=cfg,
    )
    pack["video_path"] = video_path
    if not video_path or not os.path.isfile(video_path):
        raise RuntimeError(f"找不到原片：{video_path or '(空路径)'}")

    def _progress(value: int, stage: str, extra: Mapping[str, Any] | None = None) -> None:
        if not progress_callback:
            return
        payload = dict(extra or {})
        try:
            progress_callback(int(value), str(stage), payload)
        except TypeError:
            progress_callback(int(value), str(stage))

    def _raise_if_stopped() -> None:
        if should_stop_callback and should_stop_callback():
            raise UnderstandingStoppedError("Recap stopped by user")

    _raise_if_stopped()
    stage = normalize_recap_start_from(start_from)
    caption_language = resolve_recap_caption_language(cfg)
    plan_system = resolve_recap_prompt(plan_prompt, default_recap_plan_prompt(caption_language))
    match_system = resolve_recap_system_prompt(system_prompt, caption_language)
    caption_raw = str(caption_prompt or "").strip()
    if caption_raw in {
        str(RECAP_GAP_SYSTEM).strip(),
        str(RECAP_GAP_SYSTEM_EN).strip(),
    }:
        caption_raw = ""
    caption_system = resolve_recap_prompt(caption_raw, default_recap_caption_prompt(caption_language))
    polish_system = resolve_recap_prompt(polish_prompt, default_recap_polish_prompt(caption_language))
    duration = float(pack.get("duration_sec") or 0.0)
    out_dir = Path(str(dest_dir or "").strip() or Path(video_path).resolve().parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    beats_path = out_dir / f"{stem}_recap_beats.json"
    cuts_path = out_dir / f"{stem}_recap_cuts.json"
    info: dict[str, Any] | None = None
    plan_title = "解说剪辑"
    allocated: list[dict[str, Any]] = []
    cuts: list[dict[str, Any]] = []
    title = plan_title
    people: list[dict[str, Any]] = []
    pack = dict(pack)
    warnings: list[str] = []
    motion_needed = 0
    motion_filled = 0
    motion_checked = False
    target_sec = recap_target_sec(duration)

    if stage == RECAP_START_CAPTIONS:
        saved_cuts = load_recap_cuts(video_path, video_id=video_id)
        if not saved_cuts:
            raise RuntimeError("没有已保存的选镜表。请先跑第二阶段，或从第一阶段开始。")
        title = str(saved_cuts.get("title") or "").strip() or plan_title
        saved_beats = load_recap_beats(video_path, video_id=video_id)
        if saved_beats:
            plan_title = str(saved_beats.get("title") or plan_title)
            beats_path = recap_beats_path_for_video(video_path)
            people = normalize_story_people(saved_beats)
            allocated = list(saved_beats.get("beats") or [])
        cuts = restore_recap_vo_text(list(saved_cuts.get("clips") or []))
        cuts = refine_recap_cuts(cuts, pack)
        pack["people"] = people
    else:
        if stage == RECAP_START_MATCH:
            saved = load_recap_beats(video_path, video_id=video_id)
            if not saved:
                raise RuntimeError("没有已保存的剧情规划。请先跑第一阶段，或从第一阶段开始。")
            plan_title = str(saved.get("title") or "").strip() or plan_title
            beats = list(saved.get("beats") or [])
            people = normalize_story_people(saved)
            pack["people"] = people
            allocated = allocate_beat_budgets(
                beats,
                chunks=list(pack.get("chunks") or []),
                target_sec=float(saved.get("target_sec") or target_sec),
                duration_sec=duration,
            )
            _raise_if_stopped()
            _progress(46, "vo_draft")
            allocated = draft_recap_vo_for_beats(
                pack,
                allocated,
                config=cfg,
                language=caption_language,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            beats_path = write_recap_beats_file(
                recap_beats_path_for_video(video_path),
                title=plan_title,
                video_id=video_id,
                allocated=allocated,
                people=people,
            )
        else:
            _progress(12, "planning")
            plan_title, beats, people, act_warns = plan_story_beats_by_acts(
                pack,
                video_id=video_id,
                config=cfg,
                language=caption_language,
                system_prompt=None,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            warnings.extend(act_warns)
            if not beats:
                # Fallback: single-shot plan if every act call failed.
                plan_text = call_remote_llm(
                    system=plan_system,
                    user=recap_plan_user_prompt(pack),
                    config=cfg,
                    temperature=0.25,
                    max_tokens=4096,
                    should_stop_callback=should_stop_callback,
                )
                plan_title, beats, people = parse_story_plan(plan_text)
            # One-shot act plan + free deterministic spine/land/bookends — no head/gap/tail LLM stack.
            beats = finalize_recap_plan_beats(beats, pack, duration_sec=duration)
            people = merge_story_people(pack.get("people"), people)
            pack["people"] = people
            allocated = allocate_beat_budgets(
                beats,
                chunks=list(pack.get("chunks") or []),
                target_sec=target_sec,
                duration_sec=duration,
            )
            _raise_if_stopped()
            _progress(48, "vo_draft")
            allocated = draft_recap_vo_for_beats(
                pack,
                allocated,
                config=cfg,
                language=caption_language,
                should_stop_callback=should_stop_callback,
                progress_callback=progress_callback,
            )
            beats_path = write_recap_beats_file(
                beats_path,
                title=plan_title,
                video_id=video_id,
                allocated=allocated,
                people=people,
            )
            if stage == RECAP_START_PLAN_ONLY:
                return {
                    "title": plan_title,
                    "video_id": video_id,
                    "stage": RECAP_START_PLAN,
                    "clip_count": 0,
                    "beat_count": len(allocated),
                    "duration_sec": round(sum(float(item.get("budget_sec") or 0.0) for item in allocated), 1),
                    "beats_path": str(beats_path),
                    "cuts_path": "",
                    "srt_path": "",
                    "warnings": list(warnings),
                    "motion_needed": 0,
                    "motion_filled": 0,
                    "motion_checked": False,
                }

        motion_checked = True
        gap_indices = recap_motion_gap_chunk_indices(pack, allocated)
        motion_needed = len(gap_indices)
        if gap_indices:
            _raise_if_stopped()
            _progress(44, "motion_gaps", {"done": 0, "total": motion_needed})

            def _on_motion_progress(done: int, total: int) -> None:
                pct = 44 + int(round(3.0 * float(done) / float(max(total, 1))))
                _progress(min(47, pct), "motion_gaps", {"done": int(done), "total": int(total)})

            pack, motion_warns, motion_filled = fill_recap_motion_for_beats(
                video_id,
                pack,
                allocated,
                config=cfg,
                should_stop_callback=should_stop_callback,
                on_progress=_on_motion_progress,
                chunk_completed_callback=chunk_completed_callback,
            )
            warnings.extend(motion_warns)
            pack["video_path"] = video_path
        else:
            _progress(46, "motion_gaps_skip")

        cuts = []
        match_title = plan_title
        waves = split_beats_for_match(allocated)
        for index, wave in enumerate(waves):
            _raise_if_stopped()
            _progress(48 + min(24, index * 14), "matching")
            wave_pack = pack_for_beats(pack, wave)
            used_src = collect_used_source_spans(cuts)
            match_text = call_remote_llm(
                system=match_system,
                user=recap_user_prompt(wave_pack, wave, used_src=used_src),
                config=cfg,
                temperature=0.25,
                max_tokens=4096,
                should_stop_callback=should_stop_callback,
            )
            wave_title, wave_cuts = parse_cut_list(match_text, pack)
            if wave_title and wave_title != "解说剪辑":
                match_title = wave_title
            cuts.extend(wave_cuts)
            cuts = drop_reused_source_cuts(cuts)
        leftover = missing_match_beats(allocated, cuts)
        if leftover:
            # No second match bill — first waves must cover; leftover stays for manual rematch.
            warnings.append("recap_warn_match_incomplete")
            _progress(82, "match_incomplete")
        cuts.sort(key=lambda item: (float(item.get("src_in") or 0.0), int(item.get("beat_id") or 0)))
        cuts = drop_reused_source_cuts(cuts)
        cuts = stash_match_vo_as_draft(cuts)
        cuts = stamp_beat_vo_onto_cuts(cuts, allocated)
        min_sec, _max_sec = recap_duration_bounds(target_sec)
        cuts = apply_recap_duration(cuts, pack, allocated, target_sec=target_sec, min_sec=min_sec)
        cuts = refine_recap_cuts(cuts, pack, allocated)
        cuts = annotate_recap_match_quality(cuts, allocated, pack, people, config=cfg)
        title = str(match_title or "").strip() or plan_title
        if title == "解说剪辑" and plan_title and plan_title != "解说剪辑":
            title = plan_title
        _raise_if_stopped()
        info = _probe_media(video_path)
        laid_match = layout_clips_on_timeline(cuts, fps=float(info.get("fps") or 24.0))
        cuts_path = write_recap_cuts_file(
            cuts_path,
            title=title,
            video_path=video_path,
            video_id=video_id,
            info=info,
            laid_out=laid_match,
            beats_path=beats_path,
            stage=RECAP_START_MATCH,
        )
        cuts = laid_match
        if stage == RECAP_START_MATCH:
            _progress(90, "writing")
            return {
                "title": title,
                "video_id": video_id,
                "stage": RECAP_START_MATCH,
                "clip_count": len(laid_match),
                "duration_sec": laid_match[-1]["tl_out"] if laid_match else 0,
                "beats_path": str(beats_path),
                "cuts_path": str(cuts_path),
                "srt_path": "",
                "warnings": list(warnings),
                "motion_needed": int(motion_needed),
                "motion_filled": int(motion_filled),
                "motion_checked": bool(motion_checked),
            }

    _raise_if_stopped()
    if info is None:
        info = _probe_media(video_path)
    if stage == RECAP_START_CAPTIONS:
        cuts = annotate_recap_match_quality(cuts, allocated, pack, people, config=cfg)
    laid_out = layout_clips_on_timeline(cuts, fps=float(info.get("fps") or 24.0))
    _progress(84, "captions")
    laid_out = fit_recap_captions_to_tts(
        laid_out,
        config=cfg,
        system_prompt=caption_system,
        people=people,
        beats=allocated,
        pack=pack,
        should_stop_callback=should_stop_callback,
        progress_callback=progress_callback,
    )
    _raise_if_stopped()
    # Economy: draft already covers the cut — skip gap/retry/polish LLM stack.
    if recap_vo_coverage_ratio(laid_out) < 0.82:
        laid_out = fill_recap_vo_gaps(
            laid_out,
            config=cfg,
            people=people,
            beats=allocated,
            pack=pack,
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
        )
        _raise_if_stopped()
        retry_indices = recap_gap_clip_indices(laid_out)
        if retry_indices:
            _progress(89, "captions")
            try:
                laid_out = caption_recap_clip_indices(
                    laid_out,
                    retry_indices,
                    config=cfg,
                    system_prompt=caption_system,
                    people=people,
                    beats=allocated,
                    pack=pack,
                    should_stop_callback=should_stop_callback,
                )
            except UnderstandingStoppedError:
                raise
            except (RuntimeError, json.JSONDecodeError, TypeError, ValueError):
                pass
        _raise_if_stopped()
        laid_out = polish_recap_vo(
            laid_out,
            config=cfg,
            system_prompt=polish_system,
            people=people,
            beats=allocated,
            pack=pack,
            should_stop_callback=should_stop_callback,
            progress_callback=progress_callback,
        )
    else:
        _progress(91, "polish_skip")
    _raise_if_stopped()
    _progress(92, "writing")
    cuts_path = write_recap_cuts_file(
        cuts_path,
        title=title,
        video_path=video_path,
        video_id=video_id,
        info=info,
        laid_out=laid_out,
        beats_path=beats_path,
        stage=RECAP_START_CAPTIONS,
    )
    srt_path = write_srt(laid_out, out_dir / f"{stem}_recap.srt")
    return {
        "title": title,
        "video_id": video_id,
        "stage": RECAP_START_CAPTIONS,
        "clip_count": len(laid_out),
        "duration_sec": laid_out[-1]["tl_out"] if laid_out else 0,
        "beats_path": str(beats_path),
        "cuts_path": str(cuts_path),
        "srt_path": str(srt_path),
        "warnings": list(warnings),
        "motion_needed": int(motion_needed),
        "motion_filled": int(motion_filled),
        "motion_checked": bool(motion_checked),
    }


def export_saved_recap_fcpxml(
    payload: Mapping[str, Any],
    dest_path: str | Path,
    *,
    video_path: str = "",
) -> Path:
    video = str(video_path or payload.get("video") or "").strip()
    video_id = str(payload.get("video_id") or "").strip()
    if video_id:
        from src.services.understanding_service import resolve_current_media_path

        video = resolve_current_media_path(video_id, stored=video)
    if not video or not os.path.isfile(video):
        raise RuntimeError(f"找不到原片：{video or '(空路径)'}")
    info = _probe_media(video)
    clips = stretch_recap_clips_for_vo(
        list(payload.get("clips") or []),
        media_duration=float(info.get("duration") or 0.0),
    )
    if not clips:
        raise RuntimeError("剪辑表没有镜头。")
    laid = layout_clips_on_timeline(clips, fps=float(info.get("fps") or payload.get("fps") or 24.0))
    return write_fcpxml(
        laid,
        video_path=video,
        info=info,
        dest_path=dest_path,
        project_name=str(payload.get("title") or "解说剪辑"),
    )
