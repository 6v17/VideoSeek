"""Recap job runner: motion evidence + dialogue cues → LLM cut list + SRT.

Stage modules live beside this file (``recap_*``). This module re-exports their
public surfaces and owns ``generate_recap_timeline`` orchestration.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.media.fcpxml import (
    layout_clips_on_timeline,
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
    default_recap_caption_prompt as default_recap_caption_prompt,
    default_recap_gap_prompt as default_recap_gap_prompt,
    default_recap_match_prompt as default_recap_match_prompt,
    default_recap_plan_act_prompt as default_recap_plan_act_prompt,
    default_recap_plan_gap_prompt as default_recap_plan_gap_prompt,
    default_recap_plan_head_prompt as default_recap_plan_head_prompt,
    default_recap_plan_prompt as default_recap_plan_prompt,
    default_recap_plan_structure_prompt as default_recap_plan_structure_prompt,
    default_recap_plan_tail_prompt as default_recap_plan_tail_prompt,
    default_recap_polish_prompt as default_recap_polish_prompt,
    default_recap_vo_draft_prompt as default_recap_vo_draft_prompt,
)
from src.services.recap_constants import (  # facade: knobs live in recap_constants
    BASE_CHARS_PER_SEC as BASE_CHARS_PER_SEC,
    BEAT_SRC_PAD_SEC as BEAT_SRC_PAD_SEC,
    CAPTION_CLIPS_PER_WAVE as CAPTION_CLIPS_PER_WAVE,
    CHARS_PER_SEC as CHARS_PER_SEC,
    DIALOGUE_OUTCOME_RE as DIALOGUE_OUTCOME_RE,
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
    TEXTURE_BEAT_RE as TEXTURE_BEAT_RE,
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
    looks_like_insert_cut as looks_like_insert_cut,
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
    is_bridge_clip as is_bridge_clip,
    _is_bridge_clip as _is_bridge_clip,
    _looks_like_scene_shift_text as _looks_like_scene_shift_text,
    overlap_sec as overlap_sec,
    _people_labels as _people_labels,
    _text_similarity as _text_similarity,
    time_span as time_span,
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
    recap_clip_records as recap_clip_records,
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

from src.services.recap_rematch import (  # facade: rematch splice + jobs
    filter_rematch_cuts_to_beat as filter_rematch_cuts_to_beat,
    locked_vo_context as locked_vo_context,
    neighbor_beats_for_rematch as neighbor_beats_for_rematch,
    rematch_recap_beat as rematch_recap_beat,
    rematch_weak_recap_beats as rematch_weak_recap_beats,
    splice_recap_beat_cuts as splice_recap_beat_cuts,
)

from src.services.recap_motion import (  # facade: motion chunks / VLM gaps / fill
    _asr_covers_span as _asr_covers_span,
    _beat_evidence_tags as _beat_evidence_tags,
    _beat_needs_visual_motion as _beat_needs_visual_motion,
    _caption_one_liner as _caption_one_liner,
    _chunk_motion_beats as _chunk_motion_beats,
    _cue_span as _cue_span,
    apply_recap_skip_marks as apply_recap_skip_marks,
    compact_index_chunks as compact_index_chunks,
    compact_motion_chunks as compact_motion_chunks,
    fill_recap_motion_for_beats as fill_recap_motion_for_beats,
    overlay_motion_captions as overlay_motion_captions,
    recap_motion_dense_chunk_indices as recap_motion_dense_chunk_indices,
    recap_motion_gap_chunk_indices as recap_motion_gap_chunk_indices,
)

from src.services.recap_spine import (  # facade: OCR cues / ASR-VLM spine
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
    extract_json as extract_json,
    _extract_json as _extract_json,
    loads_cut_list_json as loads_cut_list_json,
    loads_json_object as loads_json_object,
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

from src.services.recap_match_waves import (  # facade: match waves / pins / prompts
    _coverage_pin_ids as _coverage_pin_ids,
    _ensure_pinned_rows as _ensure_pinned_rows,
    _is_texture_beat as _is_texture_beat,
    _texture_pin_ids as _texture_pin_ids,
    missing_match_beats as missing_match_beats,
    recap_plan_user_prompt as recap_plan_user_prompt,
    recap_user_prompt as recap_user_prompt,
    rematch_recap_user_prompt as rematch_recap_user_prompt,
    split_beats_for_match as split_beats_for_match,
)

from src.services.recap_vo_scrub import (  # facade: VO evidence scrub
    _SPEECH_ACT_RE as _SPEECH_ACT_RE,
    _VO_QUOTE_RE as _VO_QUOTE_RE,
    _VO_WHITESPACE_RE as _VO_WHITESPACE_RE,
    _normalize_vo_compare as _normalize_vo_compare,
    _vo_evidence_window as _vo_evidence_window,
    _vo_overlaps_source_line as _vo_overlaps_source_line,
    _vo_source_span_for_scrub as _vo_source_span_for_scrub,
    scrub_unevidenced_vo as scrub_unevidenced_vo,
    scrub_verbatim_source_dialogue_vo as scrub_verbatim_source_dialogue_vo,
)

from src.services.recap_plan_normalize import (  # facade: parse / allocate beats
    _fit_budgets_to_target as _fit_budgets_to_target,
    allocate_beat_budgets as allocate_beat_budgets,
    merge_story_people as merge_story_people,
    normalize_story_beats as normalize_story_beats,
    normalize_story_people as normalize_story_people,
    parse_story_beats as parse_story_beats,
    parse_story_plan as parse_story_plan,
)

from src.services.recap_vo_units import (  # facade: narration units / review
    _stamp_unit_vo_on_block as _stamp_unit_vo_on_block,
    _unit_vo_text as _unit_vo_text,
    classify_chunk_usage_for_clips as classify_chunk_usage_for_clips,
    group_recap_vo_units as group_recap_vo_units,
    owned_chunk_indices_for_clips as owned_chunk_indices_for_clips,
    recap_clip_review_rows as recap_clip_review_rows,
)

from src.services.recap_vo_edit import (  # facade: unit hand-edits
    _write_recap_clips_payload as _write_recap_clips_payload,
    add_recap_unit_shot as add_recap_unit_shot,
    delete_recap_unit_shot as delete_recap_unit_shot,
    delete_recap_vo_unit as delete_recap_vo_unit,
    reorder_recap_unit_shot as reorder_recap_unit_shot,
    save_recap_vo_unit as save_recap_vo_unit,
)


from src.services.recap_vo_draft import (  # facade: VO draft prompt / stamp
    _VO_LAND_HINT_RE as _VO_LAND_HINT_RE,
    _format_asr_speaker_line as _format_asr_speaker_line,
    beat_vo_drops_dialogue_land as beat_vo_drops_dialogue_land,
    parse_vo_drafts as parse_vo_drafts,
    recap_vo_draft_user_prompt as recap_vo_draft_user_prompt,
    stamp_beat_vo_onto_cuts as stamp_beat_vo_onto_cuts,
)

from src.services.recap_clock import (  # facade: duration / clock
    format_recap_clock as format_recap_clock,
    format_recap_clock_range as format_recap_clock_range,
    parse_recap_clock as parse_recap_clock,
    recap_duration_bounds as recap_duration_bounds,
    recap_target_sec as recap_target_sec,
)

from src.services.recap_caption_prompt import (  # facade: caption/gap prompts
    _caption_clip_rows as _caption_clip_rows,
    _caption_visual_role as _caption_visual_role,
    parse_caption_cues as parse_caption_cues,
    recap_caption_user_prompt as recap_caption_user_prompt,
    recap_gap_user_prompt as recap_gap_user_prompt,
)

from src.services.recap_vo_post import (  # facade: polish/gap helpers + no-ops
    _fallback_role_for_unattested_name as _fallback_role_for_unattested_name,
    apply_gap_fills as apply_gap_fills,
    apply_vo_polish_cues as apply_vo_polish_cues,
    attested_people_labels_for_span as attested_people_labels_for_span,
    clamp_recap_vo_to_picture as clamp_recap_vo_to_picture,
    clear_redundant_insert_vo as clear_redundant_insert_vo,
    finalize_recap_vo_density as finalize_recap_vo_density,
    fit_recap_vo_picture as fit_recap_vo_picture,
    merge_same_beat_mainline_vo as merge_same_beat_mainline_vo,
    parse_gap_fills as parse_gap_fills,
    parse_vo_polish_cues as parse_vo_polish_cues,
    recap_gap_clip_indices as recap_gap_clip_indices,
    recap_vo_polish_user_prompt as recap_vo_polish_user_prompt,
    scrub_adjacent_duplicate_vo as scrub_adjacent_duplicate_vo,
    scrub_generic_role_labels_vo as scrub_generic_role_labels_vo,
    scrub_intra_line_duplicate_vo as scrub_intra_line_duplicate_vo,
    scrub_restated_insert_vo as scrub_restated_insert_vo,
    scrub_unattested_people_names as scrub_unattested_people_names,
)



from src.services.recap_runtime import (  # facade: parse/resolve/save + export
    export_saved_recap_fcpxml as export_saved_recap_fcpxml,
    probe_recap_media as probe_recap_media,
    normalize_recap_start_from as normalize_recap_start_from,
    parse_cut_list as parse_cut_list,
    resolve_recap_caption_language as resolve_recap_caption_language,
    resolve_recap_prompt as resolve_recap_prompt,
    resolve_recap_system_prompt as resolve_recap_system_prompt,
    save_recap_clip_vo as save_recap_clip_vo,
    save_recap_plan_edits as save_recap_plan_edits,
)


from src.services.recap_pack import (  # facade: evidence pack + dialogue
    build_recap_pack as build_recap_pack,
    ensure_recap_dialogue_cues as ensure_recap_dialogue_cues,
    list_speech_dialogue_cues as list_speech_dialogue_cues,
    people_from_dialogue_speakers as people_from_dialogue_speakers,
    recap_dialogue_status as recap_dialogue_status,
    recap_speaker_stats as recap_speaker_stats,
)

from src.services.recap_vo_pipeline import (  # facade: VO LLM stages
    caption_recap_clip_indices as caption_recap_clip_indices,
    draft_recap_vo_for_beats as draft_recap_vo_for_beats,
    fill_recap_vo_gaps as fill_recap_vo_gaps,
    fit_recap_captions_to_tts as fit_recap_captions_to_tts,
    polish_recap_vo as polish_recap_vo,
    rewrite_recap_clip_caption as rewrite_recap_clip_caption,
)


from src.services.recap_plan_pipeline import (  # facade: act plan LLM + finalize
    _try_story_plan_llm as _try_story_plan_llm,
    finalize_recap_plan_beats as finalize_recap_plan_beats,
    plan_story_beats_by_acts as plan_story_beats_by_acts,
    resolve_plan_act_windows as resolve_plan_act_windows,
    scrub_unevidenced_beats as scrub_unevidenced_beats,
)

_DIALOGUE_OUTCOME_RE = DIALOGUE_OUTCOME_RE
_TEXTURE_BEAT_RE = TEXTURE_BEAT_RE


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
        info = probe_recap_media(video_path)
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
        info = probe_recap_media(video_path)
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


