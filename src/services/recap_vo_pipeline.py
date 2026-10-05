"""VO draft / captions / polish / gap LLM stages.

Call LLM via the ``recap_service`` module object so tests can patch
``src.services.recap_service.call_remote_llm`` / ``build_recap_pack``.
``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.services.recap_caption_prompt import (
    parse_caption_cues,
    recap_caption_user_prompt,
    recap_gap_user_prompt,
)
from src.services.recap_captions import (
    apply_caption_cues,
    pack_captions_for_tts,
    recap_vo_coverage_ratio,
    split_clips_for_captions,
)
from src.services.recap_constants import VO_DRAFT_BEATS_PER_WAVE
from src.services.recap_io import load_recap_beats, load_recap_cuts
from src.services.recap_match_waves import split_beats_for_match
from src.services.recap_prompts import (
    default_recap_caption_prompt,
    default_recap_gap_prompt,
    default_recap_polish_prompt,
    default_recap_vo_draft_prompt,
)
from src.services.recap_runtime import (
    resolve_recap_caption_language,
    resolve_recap_prompt,
    save_recap_clip_vo,
)
from src.services.recap_vo_draft import parse_vo_drafts, recap_vo_draft_user_prompt
from src.services.recap_vo_post import (
    apply_gap_fills,
    apply_vo_polish_cues,
    parse_gap_fills,
    parse_vo_polish_cues,
    recap_gap_clip_indices,
    recap_vo_polish_user_prompt,
    scrub_unattested_people_names,
)
from src.services.recap_vo_scrub import scrub_unevidenced_vo, scrub_verbatim_source_dialogue_vo


def _rs():
    """Lazy: honor patches on ``src.services.recap_service``."""
    from src.services import recap_service as runner

    return runner

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
            text = _rs().call_remote_llm(
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
            text = _rs().call_remote_llm(
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
            text = _rs().call_remote_llm(
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
        text = _rs().call_remote_llm(
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
            pack = _rs().build_recap_pack(vid, config=cfg)
        except Exception:
            pack = None
    prev = ""
    for cursor in range(index - 1, -1, -1):
        body = str(clips[cursor].get("vo") or "").strip()
        if body:
            prev = body
            break
    wave = [dict(clips[index])]
    text = _rs().call_remote_llm(
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
    text = _rs().call_remote_llm(
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
