"""Act-structure / act-by-act plan LLM stages and deterministic plan finalize.

Call LLM / dense ASR via the `recap_service` module object so tests can patch
`call_remote_llm` and `compact_ocr_cues_in_span` on the runner.
`recap_service` re-exports these names.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.services.recap_constants import (
    ENDING_COVER_RATIO,
    MAX_STORY_BEATS,
    PLAN_ACT_ASR_LIMIT,
    PLAN_ACT_TARGET_SEC,
)
from src.services.recap_focus import (
    infer_recap_focus,
    merge_recap_focus,
    normalize_recap_focus,
)
from src.services.recap_match import (
    _evidence_for_source_span,
    _looks_like_scene_shift_text,
    recap_story_window,
    time_span,
)
from src.services.recap_match_waves import _is_texture_beat
from src.services.recap_plan_acts import (
    build_plan_structure_brief,
    clamp_beats_to_act_window,
    normalize_plan_act_windows,
    parse_plan_act_windows,
    parse_soft_focus_payload,
    recap_plan_act_user_prompt,
    split_story_into_plan_acts,
)
from src.services.recap_plan_cover import (
    ensure_beats_cover_silent_spans,
    ensure_beats_cover_spine,
    ensure_beats_land_dialogue_outcomes,
)
from src.services.recap_plan_gaps import (
    beats_cover_ending,
    beats_cover_opening,
    drop_op_ed_beats,
    opening_deadline_sec,
    trim_story_beats_to_limit,
)
from src.services.recap_plan_merge import filter_pack_to_span, merge_story_beats
from src.services.recap_plan_normalize import (
    merge_story_people,
    normalize_story_people,
    parse_story_plan,
)
from src.services.recap_prompts import (
    default_recap_plan_act_prompt,
    default_recap_plan_structure_prompt,
)
from src.services.recap_runtime import resolve_recap_prompt
from src.services.recap_spine import build_asr_vlm_spine


def _rs():
    from src.services import recap_service as runner

    return runner


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
        text = _rs().call_remote_llm(
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
        dense = _rs().compact_ocr_cues_in_span(
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
        text = _rs().call_remote_llm(
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
        span = time_span(beat.get("t"))
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
        head = next((seg for seg in spine if (time_span(seg.get("t")) or (1e9, 1e9))[0] <= deadline), None)
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
            span = time_span(seg.get("t"))
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
