
"""Rematch splice helpers and one-beat / weak-batch rematch jobs.

Uses lazy `recap_service` lookups so tests can patch `call_remote_llm`,
`build_recap_pack`, `fill_recap_motion_for_beats`, `load_recap_cuts`,
`rematch_recap_beat`, and `probe_recap_media`.
`recap_service` re-exports the public names.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.app.config import load_config
from src.core.understanding.base import UnderstandingStoppedError
from src.media.fcpxml import layout_clips_on_timeline, write_srt
from src.services.recap_constants import (
    BEAT_SRC_PAD_SEC,
    MAX_CLIP_SEC,
    MAX_WEAK_REMATCH_BEATS,
    MIN_FLASH_CLIP_SEC,
    RECAP_START_CAPTIONS,
    RECAP_START_MATCH,
)
from src.services.recap_cut_build import stash_match_vo_as_draft
from src.services.recap_cut_fit import (
    _snap_src_into_beat_window,
    clamp_cuts_to_beat_window,
    snap_cuts_to_capped_chunks,
)
from src.services.recap_cut_pad import _source_hits_op_ed, clamp_insert_cuts_to_beat
from src.services.recap_cuts import _clip_beat_id, dedupe_overlapping_recap_cuts
from src.services.recap_io import (
    load_recap_beats,
    load_recap_cuts,
    recap_beats_path_for_video,
    recap_cuts_path_for_video,
    write_recap_cuts_file,
)
from src.services.recap_match import (
    annotate_recap_match_quality,
    list_weak_match_beat_ids,
    overlap_sec,
    time_span,
)
from src.services.recap_match_waves import rematch_recap_user_prompt
from src.services.recap_plan_merge import pack_for_beats
from src.services.recap_plan_normalize import normalize_story_people
from src.services.recap_runtime import (
    parse_cut_list,
    resolve_recap_caption_language,
    resolve_recap_system_prompt,
)
from src.services.recap_vo_budget import restore_recap_vo_text
from src.services.recap_vo_pipeline import caption_recap_clip_indices

def _splice_recap_beat_cuts(
    existing: Sequence[Mapping[str, Any]],
    new_cuts: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> list[dict[str, Any]]:
    """Replace every clip for ``beat_id`` with ``new_cuts``, keeping other beats intact.

    Removes *all* clips of the target beat (even if non-contiguous), then inserts the
    new block at the first removed position so neighbors stay in narrative order.
    """
    target = int(beat_id)
    kept: list[dict[str, Any]] = []
    insert_at: int | None = None
    for clip in existing or []:
        row = dict(clip)
        if _clip_beat_id(row) == target:
            if insert_at is None:
                insert_at = len(kept)
            continue
        kept.append(row)
    mid: list[dict[str, Any]] = []
    for clip in new_cuts or []:
        row = dict(clip)
        row["beat_id"] = target
        mid.append(row)
    if not mid:
        return kept
    if insert_at is None:
        # No prior clips for this beat — place by ascending beat id among neighbors.
        insert_at = len(kept)
        for index, clip in enumerate(kept):
            bid = _clip_beat_id(clip)
            if bid is not None and bid > target:
                insert_at = index
                break
    return kept[:insert_at] + mid + kept[insert_at:]

def _neighbor_beats_for_rematch(
    allocated: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any] | None]:
    ordered = [dict(item) for item in allocated or []]
    target_index = None
    for index, item in enumerate(ordered):
        try:
            if int(item.get("id")) == int(beat_id):
                target_index = index
                break
        except (TypeError, ValueError):
            continue
    if target_index is None:
        raise RuntimeError(f"规划里没有拍 #{beat_id}。")
    prev_beat = ordered[target_index - 1] if target_index > 0 else None
    next_beat = ordered[target_index + 1] if target_index + 1 < len(ordered) else None
    return prev_beat, ordered[target_index], next_beat

def _locked_vo_context(
    clips: Sequence[Mapping[str, Any]],
    beat_id: int,
) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    """Return (prev VO lines, next VO lines, old cuts for this beat)."""
    target = int(beat_id)
    prev: list[str] = []
    nxt: list[str] = []
    old: list[dict[str, Any]] = []
    phase = "before"
    for clip in clips or []:
        row = dict(clip)
        bid = _clip_beat_id(row)
        vo = str(row.get("vo") or "").strip()
        if bid == target:
            phase = "after"
            old.append(row)
            continue
        if phase == "before":
            if vo:
                prev.append(vo)
        else:
            if vo:
                nxt.append(vo)
    return prev[-3:], nxt[:3], old

def _filter_rematch_cuts_to_beat(
    cuts: Sequence[Mapping[str, Any]],
    beat: Mapping[str, Any],
    *,
    pack: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Keep only target-beat clips that still touch the beat time window."""
    target = int(beat.get("id"))
    span = time_span(beat.get("t"))
    out: list[dict[str, Any]] = []
    for clip in cuts or []:
        row = dict(clip)
        bid = _clip_beat_id(row)
        if bid not in (None, 0, target):
            continue
        row["beat_id"] = target
        try:
            src_in = float(row.get("src_in") or 0.0)
            src_out = float(row.get("src_out") or 0.0)
        except (TypeError, ValueError):
            continue
        if src_out <= src_in + 0.4:
            continue
        pad = float(BEAT_SRC_PAD_SEC)
        if span and overlap_sec((src_in, src_out), (span[0] - pad, span[1] + pad)) <= 0.05:
            # Far outside beat window — try snap, else drop.
            placed = None
            if pack is not None:
                placed = _snap_src_into_beat_window(
                    pack,
                    span,
                    want_sec=max(MIN_FLASH_CLIP_SEC, min(src_out - src_in, MAX_CLIP_SEC)),
                    pad_sec=pad,
                )
            if placed is None:
                continue
            row["src_in"], row["src_out"] = placed
            row["duration"] = round(placed[1] - placed[0], 3)
            src_in, src_out = placed
        if pack is not None and _source_hits_op_ed(pack, src_in, src_out):
            continue
        out.append(row)
    return out

filter_rematch_cuts_to_beat = _filter_rematch_cuts_to_beat
locked_vo_context = _locked_vo_context
neighbor_beats_for_rematch = _neighbor_beats_for_rematch
splice_recap_beat_cuts = _splice_recap_beat_cuts

def _rs():
    from src.services import recap_service as runner

    return runner

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

    pack = _rs().build_recap_pack(vid, config=cfg)
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
    prev_beat, beat, next_beat = neighbor_beats_for_rematch(allocated, target_beat_id)

    saved_cuts = load_recap_cuts(media, video_id=vid)
    if not saved_cuts:
        raise RuntimeError("还没有选镜表。")
    existing = restore_recap_vo_text(list(saved_cuts.get("clips") or []))
    title = str(saved_cuts.get("title") or beats_payload.get("title") or "解说剪辑").strip() or "解说剪辑"
    prev_vo, next_vo, old_cuts = locked_vo_context(existing, target_beat_id)
    other_before = [dict(clip) for clip in existing if _clip_beat_id(clip) != target_beat_id]

    _raise_if_stopped()
    _progress(20, "motion_gaps")
    # Include neighbor beat windows so ASR/caps around the cut are visible to the matcher.
    context_beats = [item for item in (prev_beat, beat, next_beat) if item]
    pack, _motion_warns, motion_filled = _rs().fill_recap_motion_for_beats(
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
    match_text = _rs().call_remote_llm(
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
    normalized = filter_rematch_cuts_to_beat(
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
    normalized = filter_rematch_cuts_to_beat(normalized, beat, pack=pack)
    if not normalized:
        raise RuntimeError("选镜结果无效。")
    normalized = annotate_recap_match_quality(
        normalized, [beat], pack, people, config=cfg
    )

    merged = splice_recap_beat_cuts(existing, normalized, target_beat_id)
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

    info = _rs().probe_recap_media(media)
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

    # Via runner so tests can patch ``recap_service.load_recap_cuts``.
    payload = _rs().load_recap_cuts(media, video_id=vid)
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
            last = _rs().rematch_recap_beat(
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
    refreshed = _rs().load_recap_cuts(media, video_id=vid) or last
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
