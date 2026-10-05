
"""Recap runtime helpers: parse/resolve/save, media probe, FCPXML export.

`recap_service` re-exports these names.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.app.config import load_config
from src.media.fcpxml import layout_clips_on_timeline, write_cuts_json, write_fcpxml, write_srt
from src.services.recap_clock import recap_target_sec
from src.services.recap_constants import (
    RECAP_START_CAPTIONS,
    RECAP_START_MATCH,
    RECAP_START_PLAN,
    RECAP_START_PLAN_ONLY,
)
from src.services.recap_cut_build import normalize_cut_list
from src.services.recap_io import (
    load_recap_cuts,
    recap_beats_path_for_video,
    recap_clip_records,
    recap_cuts_path_for_video,
    write_recap_beats_file,
)
from src.services.recap_llm_json import loads_cut_list_json
from src.services.recap_plan_normalize import allocate_beat_budgets, normalize_story_people
from src.services.recap_prompts import default_recap_match_prompt
from src.services.recap_vo_budget import _max_picture_for_vo, stretch_recap_clips_for_vo
from src.services.understanding_resource_service import (
    CAPTION_LANGUAGE_ZH,
    normalize_caption_language,
)

def parse_cut_list(text: str, pack: Mapping[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    try:
        payload = loads_cut_list_json(text)
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
    next_payload["clips"] = recap_clip_records(clips)
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

probe_recap_media = _probe_media

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
    info = probe_recap_media(video)
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
