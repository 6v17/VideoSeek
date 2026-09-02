"""JianYing (剪映) draft discovery and shot-list export helpers."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Sequence

from src.services.shot_list_service import ShotListItem


_VIDEOSEEK_TRACK_NAME = "VideoSeek"
_VIDEOSEEK_TEXT_TRACK_NAME = "VideoSeek旁白"
_DEFAULT_COLLECT_DRAFT_PREFIX = "VideoSeek导入"
_RECAP_DRAFT_PREFIX = "VideoSeek解说"
_CLONE_DRAFT_PREFIX = "VideoSeek克隆"
_CLONE_TRACK_NAMES = {
    1: "VideoSeek V1",
    2: "VideoSeek V2",
    3: "VideoSeek V3",
}


class JianyingDraftError(RuntimeError):
    """User-facing Jianying draft failure with a short summary."""

    def __init__(self, summary: str, *, detail: str = ""):
        self.summary = str(summary or "").strip() or "Jianying draft error"
        self.detail = str(detail or "").strip()
        super().__init__(self.summary)


class JianyingDraftEncryptedError(JianyingDraftError):
    """New Jianying builds store encrypted draft_content.json."""


@dataclass(frozen=True)
class JianyingDraftInfo:
    name: str
    path: str
    readable: bool = True


def is_jianying_draft_support_available() -> bool:
    try:
        import pyJianYingDraft  # noqa: F401

        return True
    except ImportError:
        return False


def discover_jianying_drafts_dirs() -> List[str]:
    """Best-effort Windows draft roots used by Jianying Pro / CapCut CN."""
    found: List[str] = []
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if not local:
        return found
    candidates = [
        os.path.join(local, "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        os.path.join(local, "CapCut", "User Data", "Projects", "com.lveditor.draft"),
        os.path.join(local, "JianyingPro Drafts"),
    ]
    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normcase(os.path.abspath(path))
        if normalized in seen or not os.path.isdir(path):
            continue
        seen.add(normalized)
        found.append(os.path.abspath(path))
    return found


def resolve_jianying_drafts_dir(config=None) -> str:
    from src.app.config import DEFAULT_CONFIG, load_config

    cfg = config if config is not None else load_config()
    configured = str(cfg.get("jianying_drafts_dir", DEFAULT_CONFIG.get("jianying_drafts_dir", "")) or "").strip()
    if configured and os.path.isdir(configured):
        return os.path.abspath(configured)
    discovered = discover_jianying_drafts_dirs()
    return discovered[0] if discovered else ""


def is_plain_json_draft_content(draft_path: str) -> bool:
    content_path = os.path.join(os.fspath(draft_path), "draft_content.json")
    if not os.path.isfile(content_path):
        return False
    try:
        with open(content_path, "rb") as handle:
            raw = handle.read()
        json.loads(raw.decode("utf-8"))
        return True
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def list_jianying_drafts(drafts_dir: str | None = None, *, config=None) -> List[JianyingDraftInfo]:
    root = str(drafts_dir or resolve_jianying_drafts_dir(config=config) or "").strip()
    if not root or not os.path.isdir(root):
        return []
    items: List[JianyingDraftInfo] = []
    try:
        names = sorted(os.listdir(root), key=lambda name: name.lower())
    except OSError:
        return []
    for name in names:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        content = os.path.join(path, "draft_content.json")
        meta = os.path.join(path, "draft_meta_info.json")
        if not (os.path.isfile(content) or os.path.isfile(meta)):
            continue
        items.append(
            JianyingDraftInfo(
                name=name,
                path=path,
                readable=is_plain_json_draft_content(path),
            )
        )
    return items


def allocate_unique_draft_name(root: str, prefix: str) -> str:
    stamp = datetime.now().strftime("%m%d-%H%M")
    base = str(prefix or "").strip() or _DEFAULT_COLLECT_DRAFT_PREFIX
    candidate = f"{base}-{stamp}"
    index = 1
    while os.path.isdir(os.path.join(root, candidate)):
        index += 1
        candidate = f"{base}-{stamp}-{index}"
    return candidate


def _safe_draft_slug(text: str, *, fallback: str = "解说", max_len: int = 36) -> str:
    body = re.sub(r'[<>:"/\\|?*]', "_", str(text or "").strip())
    body = re.sub(r"\s+", " ", body).strip(" .")
    if not body:
        body = fallback
    return body[:max_len].rstrip(" .") or fallback


def recap_export_clip_spans(clips: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One timeline: picture duration is the source span we will place."""
    items: list[dict[str, Any]] = []
    for clip in clips:
        src_in = float(clip.get("src_in") or 0.0)
        src_out = float(clip.get("src_out") or 0.0)
        duration = src_out - src_in
        if duration <= 0.05:
            continue
        items.append(
            {
                "src_in": src_in,
                "duration": duration,
                "vo": str(clip.get("vo") or "").strip(),
            }
        )
    return items


def merge_recap_captions(spans: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Lock captions to the picture timeline: same start, same duration.

    Empty follow shots keep the current line on screen. The next spoken line
    starts when its shot starts. Do not use a second TTS clock.
    """
    from src.services.recap_service import _vo_covers, _vo_needs_more_picture

    captions: list[dict[str, Any]] = []
    cursor = 0.0
    for item in spans:
        duration = float(item.get("duration") or 0.0)
        if duration <= 0:
            continue
        vo = str(item.get("vo") or "").strip()
        if vo:
            if captions and _vo_covers(captions[-1]["text"], vo):
                captions[-1]["duration"] += duration
            elif captions and _vo_covers(vo, captions[-1]["text"]):
                captions[-1]["text"] = vo
                captions[-1]["duration"] += duration
            else:
                captions.append({"start": cursor, "duration": duration, "text": vo})
        elif captions and _vo_needs_more_picture(captions[-1]["text"], captions[-1]["duration"]):
            captions[-1]["duration"] += duration
        cursor += duration
    return captions


def _draft_canvas(*, width: int = 1920, height: int = 1080, fps: float = 30) -> tuple[int, int, int]:
    canvas_w = max(320, int(width or 1920))
    canvas_h = max(240, int(height or 1080))
    fps_i = int(round(float(fps or 30)))
    if fps_i < 12:
        fps_i = 30
    if fps_i > 120:
        fps_i = 60
    return canvas_w, canvas_h, fps_i


def _normalize_clip_span(
    *,
    start_sec: float,
    end_sec: float,
    match_kind: str = "frame",
    media_path: str = "",
) -> tuple[float, float]:
    """Return (source_start, duration) with frame hits expanded like FCPXML (±3s)."""
    from src.services.fcpxml_export_service import _clip_span_seconds, _probe_media

    media_duration = None
    fps = 30.0
    path = str(media_path or "").strip()
    if path and os.path.isfile(path):
        info = _probe_media(path)
        if info.get("duration") is not None:
            media_duration = float(info["duration"])
        if info.get("fps"):
            fps = float(info["fps"])
    item = SimpleNamespace(
        start_sec=float(start_sec),
        end_sec=float(end_sec if end_sec is not None else start_sec),
        match_kind=str(match_kind or "frame"),
    )
    return _clip_span_seconds(item, fps, media_duration)


def _make_video_segment(draft_mod, media: str, *, timeline_start_us: int, clip_start: float, duration: float):
    """Build a 1x VideoSegment placed at ``timeline_start_us`` on the timeline."""
    return draft_mod.VideoSegment(
        media,
        draft_mod.trange(int(timeline_start_us), draft_mod.tim(f"{duration:.3f}s")),
        source_timerange=draft_mod.trange(
            draft_mod.tim(f"{clip_start:.3f}s"),
            draft_mod.tim(f"{duration:.3f}s"),
        ),
        speed=1.0,
    )


def _add_segment_to_imported_video_track(script, draft_mod, track, segment) -> None:
    """Append a VideoSegment onto an imported (template-mode) video track.

    ``ScriptFile.add_segment`` only accepts editable tracks in ``script.tracks``.
    After ``load_template``, saved tracks become imported — appending there must
    update the imported track in place, otherwise a new parallel track is created.
    """
    from pyJianYingDraft.template_mode import ImportedMediaSegment

    # Mirror the material bookkeeping that ScriptFile.add_segment would do.
    if segment.animations_instance is not None and segment.animations_instance not in script.materials:
        script.materials.animations.append(segment.animations_instance)
    if segment.fade is not None and segment.fade not in script.materials:
        script.materials.audio_fades.append(segment.fade)
    for effect in segment.effects:
        if effect not in script.materials:
            script.materials.video_effects.append(effect)
    for filter_ in segment.filters:
        if filter_ not in script.materials:
            script.materials.filters.append(filter_)
    for mix_mode in segment.mix_modes:
        script.materials.mix_modes.append(mix_mode)
    if segment.mask is not None:
        script.materials.masks.append(segment.mask.export_json())
    if segment.transition is not None and segment.transition not in script.materials:
        script.materials.transitions.append(segment.transition)
    if segment.background_filling is not None:
        script.materials.canvases.append(segment.background_filling)
    if segment.chroma is not None and segment.chroma not in script.materials:
        script.materials.chromas.append(segment.chroma)
    script.materials.speeds.append(segment.speed)
    script.add_material(segment.material_instance)

    track.segments.append(ImportedMediaSegment(segment.export_json()))
    script.duration = max(int(getattr(script, "duration", 0) or 0), int(segment.end))


def _consolidate_imported_videoseek_tracks(script, draft_mod):
    """Merge duplicate VideoSeek imported tracks onto one timeline (legacy bugfix)."""
    TrackType = draft_mod.TrackType
    matches = [
        track
        for track in list(getattr(script, "imported_tracks", []) or [])
        if getattr(track, "track_type", None) == TrackType.video
        and str(getattr(track, "name", "") or "") == _VIDEOSEEK_TRACK_NAME
    ]
    if not matches:
        return None
    primary = matches[0]
    collected = []
    for track in matches:
        collected.extend(list(getattr(track, "segments", []) or []))
        if track is not primary:
            script.imported_tracks.remove(track)
    cursor = 0
    for seg in collected:
        duration = int(getattr(seg.target_timerange, "duration", 0) or 0)
        seg.target_timerange.start = int(cursor)
        cursor += max(0, duration)
    primary.segments = collected
    script.duration = max(int(getattr(script, "duration", 0) or 0), int(cursor))
    return primary


def _resolve_videoseek_write_target(script, draft_mod) -> tuple[str, object, int]:
    """Return ``(mode, track_handle, end_time_us)``.

    mode is ``\"editable\"`` (TrackRef for add_segment) or ``\"imported\"`` (ImportedMediaTrack).
    """
    TrackType = draft_mod.TrackType
    TrackSpec = draft_mod.TrackSpec

    for track in (getattr(script, "tracks", {}) or {}).values():
        if getattr(track, "track_type", None) == TrackType.video and str(getattr(track, "name", "") or "") == _VIDEOSEEK_TRACK_NAME:
            ref = script._track_to_ref(track)
            return "editable", ref, int(getattr(track, "end_time", 0) or 0)

    imported = _consolidate_imported_videoseek_tracks(script, draft_mod)
    if imported is not None:
        return "imported", imported, int(getattr(imported, "end_time", 0) or 0)

    ref = script.append_track(TrackSpec(TrackType.video, name=_VIDEOSEEK_TRACK_NAME))
    return "editable", ref, 0


def _append_clip_onto_script(
    script,
    draft_mod,
    *,
    video_path: str,
    start_sec: float,
    end_sec: float,
    match_kind: str = "frame",
) -> None:
    media = os.path.abspath(os.path.expanduser(str(video_path or "").strip()))
    if not media or not os.path.isfile(media):
        raise JianyingDraftError("找不到视频文件", detail=media or "(empty)")

    clip_start, duration = _normalize_clip_span(
        start_sec=start_sec,
        end_sec=end_sec,
        match_kind=match_kind,
        media_path=media,
    )
    if duration <= 0:
        raise JianyingDraftError("片段时长无效", detail=media)

    mode, track_handle, track_end_us = _resolve_videoseek_write_target(script, draft_mod)
    segment = _make_video_segment(
        draft_mod,
        media,
        timeline_start_us=track_end_us,
        clip_start=clip_start,
        duration=duration,
    )
    if mode == "editable":
        script.add_segment(segment, track_handle)
    else:
        _add_segment_to_imported_video_track(script, draft_mod, track_handle, segment)


def append_clip_to_jianying_draft(
    *,
    drafts_dir: str,
    draft_name: str,
    video_path: str,
    start_sec: float,
    end_sec: float,
    match_kind: str = "frame",
) -> str:
    """Append a local video range onto a dedicated VideoSeek track.

    Frame-level hits are expanded to about 6 seconds (anchor±3s) so they are
    editable in Jianying instead of flashing past. Speed is forced to 1.0.

    Returns the draft display name on success.
    """
    if not is_jianying_draft_support_available():
        raise JianyingDraftError(
            "未安装 pyJianYingDraft",
            detail="请在 VideoSeek 环境执行：pip install pyJianYingDraft",
        )

    import pyJianYingDraft as draft
    from pyJianYingDraft.exceptions import DraftContentLoadFailed

    root = os.path.abspath(str(drafts_dir or "").strip())
    name = str(draft_name or "").strip()
    if not root or not os.path.isdir(root):
        raise JianyingDraftError("找不到剪映草稿目录", detail=root or "(empty)")
    if not name:
        raise JianyingDraftError("未选择草稿")

    draft_path = os.path.join(root, name)
    if not os.path.isdir(draft_path):
        raise JianyingDraftError("找不到所选草稿", detail=name)
    if not is_plain_json_draft_content(draft_path):
        raise JianyingDraftEncryptedError(
            "该草稿已被剪映加密，无法直接追加",
            detail=(
                "新版剪映的 draft_content.json 不是明文 JSON。\n"
                "请从 VideoSeek 素材篮重新导出一份新草稿后再在剪映中打开。"
            ),
        )

    folder = draft.DraftFolder(root)
    try:
        script = folder.load_template(name)
    except DraftContentLoadFailed as exc:
        raise JianyingDraftEncryptedError(
            "该草稿已被剪映加密，无法直接追加",
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise JianyingDraftError("加载剪映草稿失败", detail=str(exc)) from exc

    try:
        _append_clip_onto_script(
            script,
            draft,
            video_path=video_path,
            start_sec=start_sec,
            end_sec=end_sec,
            match_kind=match_kind,
        )
        script.save()
    except JianyingDraftError:
        raise
    except Exception as exc:
        raise JianyingDraftError("写入剪映草稿失败", detail=str(exc)) from exc
    return name


def export_shot_list_to_jianying_draft(
    items: Sequence[ShotListItem],
    *,
    drafts_dir: str | None = None,
    draft_name: str | None = None,
    config=None,
) -> Dict[str, Any]:
    """Create a plaintext VideoSeek draft and lay all local clips on one timeline track."""
    if not items:
        raise JianyingDraftError("素材篮为空")
    if not is_jianying_draft_support_available():
        raise JianyingDraftError(
            "未安装 pyJianYingDraft",
            detail="请在 VideoSeek 环境执行：pip install pyJianYingDraft",
        )

    import pyJianYingDraft as draft

    root = str(drafts_dir or resolve_jianying_drafts_dir(config=config) or "").strip()
    if not root or not os.path.isdir(root):
        raise JianyingDraftError(
            "找不到剪映草稿目录",
            detail="请选择剪映工程里的草稿根目录（含各草稿子文件夹的那一层）。",
        )
    root = os.path.abspath(root)

    name = str(draft_name or "").strip()
    if not name:
        name = allocate_unique_draft_name(root, _DEFAULT_COLLECT_DRAFT_PREFIX)

    folder = draft.DraftFolder(root)
    try:
        # Build the whole timeline in one ScriptFile session. Reloading between
        # clips turns saved tracks into imported_tracks and used to spawn a new
        # parallel VideoSeek track for every clip.
        script = folder.create_draft(name, 1920, 1080, fps=30, allow_replace=False)
        script.append_track(draft.TrackSpec(draft.TrackType.video, name=_VIDEOSEEK_TRACK_NAME))
    except FileExistsError as exc:
        raise JianyingDraftError("同名草稿已存在", detail=name) from exc
    except Exception as exc:
        raise JianyingDraftError("创建剪映草稿失败", detail=str(exc)) from exc

    exported = 0
    skipped: List[Dict[str, str]] = []
    for item in items:
        path = str(getattr(item, "video_path", "") or "").strip()
        lower = path.lower()
        if lower.startswith(("http://", "https://")):
            skipped.append({"path": path, "reason": "remote"})
            continue
        if not path or not os.path.isfile(path):
            skipped.append({"path": path or "(empty)", "reason": "missing"})
            continue
        try:
            _append_clip_onto_script(
                script,
                draft,
                video_path=path,
                start_sec=float(item.start_sec),
                end_sec=float(item.end_sec if item.end_sec is not None else item.start_sec),
                match_kind=str(getattr(item, "match_kind", "frame") or "frame"),
            )
            exported += 1
        except JianyingDraftError as exc:
            skipped.append({"path": path, "reason": exc.summary})
        except Exception as exc:
            skipped.append({"path": path, "reason": str(exc)})

    if exported <= 0:
        # Remove the empty draft folder we just created.
        draft_path = os.path.join(root, name)
        try:
            import shutil

            if os.path.isdir(draft_path):
                shutil.rmtree(draft_path)
        except OSError:
            pass
        detail = skipped[0]["reason"] if skipped else "no clips"
        raise JianyingDraftError("没有可写入剪映的本地片段", detail=detail)

    try:
        script.save()
    except Exception as exc:
        raise JianyingDraftError("写入剪映草稿失败", detail=str(exc)) from exc

    return {
        "draft_name": name,
        "drafts_dir": root,
        "draft_path": os.path.join(root, name),
        "exported_count": exported,
        "skipped_count": len(skipped),
        "skipped": skipped,
    }


def export_recap_to_jianying_draft(
    clips: Sequence[Mapping[str, Any]],
    *,
    video_path: str,
    drafts_dir: str | None = None,
    draft_name: str | None = None,
    title: str = "",
    fps: float = 30,
    width: int = 1920,
    height: int = 1080,
    config=None,
) -> Dict[str, Any]:
    """Create a plaintext recap draft: video clips + bottom VO captions."""
    if not is_jianying_draft_support_available():
        raise JianyingDraftError(
            "未安装 pyJianYingDraft",
            detail="请在 VideoSeek 环境执行：pip install pyJianYingDraft",
        )

    media = os.path.abspath(os.path.expanduser(str(video_path or "").strip()))
    if not media or not os.path.isfile(media):
        raise JianyingDraftError("找不到视频文件", detail=media or "(empty)")

    from src.services.recap_service import stretch_recap_clips_for_vo, _probe_media as probe_recap_media

    media_duration = 0.0
    try:
        media_duration = float(probe_recap_media(media).get("duration") or 0.0)
    except Exception:
        media_duration = 0.0
    prepared = stretch_recap_clips_for_vo(clips, media_duration=media_duration)
    spans = recap_export_clip_spans(prepared)
    if not spans:
        raise JianyingDraftError("没有可写入剪映的镜头")

    root = str(drafts_dir or resolve_jianying_drafts_dir(config=config) or "").strip()
    if not root or not os.path.isdir(root):
        raise JianyingDraftError(
            "找不到剪映草稿目录",
            detail="请选择剪映工程里的草稿根目录（含各草稿子文件夹的那一层）。",
        )
    root = os.path.abspath(root)

    name = str(draft_name or "").strip()
    if not name:
        slug = _safe_draft_slug(title)
        name = allocate_unique_draft_name(root, f"{_RECAP_DRAFT_PREFIX}-{slug}")

    import pyJianYingDraft as draft

    canvas_w, canvas_h, fps_i = _draft_canvas(width=width, height=height, fps=fps)
    folder = draft.DraftFolder(root)
    try:
        script = folder.create_draft(name, canvas_w, canvas_h, fps=fps_i, allow_replace=False)
        script.append_track(draft.TrackSpec(draft.TrackType.video, name=_VIDEOSEEK_TRACK_NAME))
        captions = merge_recap_captions(spans)
        text_ref = None
        if captions:
            text_ref = script.append_track(
                draft.TrackSpec(draft.TrackType.text, name=_VIDEOSEEK_TEXT_TRACK_NAME)
            )
    except FileExistsError as exc:
        raise JianyingDraftError("同名草稿已存在", detail=name) from exc
    except Exception as exc:
        raise JianyingDraftError("创建剪映草稿失败", detail=str(exc)) from exc

    try:
        for item in spans:
            start = float(item["src_in"])
            duration = float(item["duration"])
            _append_clip_onto_script(
                script,
                draft,
                video_path=media,
                start_sec=start,
                end_sec=start + duration,
                match_kind="clip",
            )
        if text_ref is not None:
            last_end_us = 0
            for cap in captions:
                start_us = max(int(round(float(cap["start"]) * 1_000_000)), last_end_us)
                end_us = int(round((float(cap["start"]) + float(cap["duration"])) * 1_000_000))
                if end_us <= start_us:
                    continue
                text_seg = draft.TextSegment(
                    str(cap["text"]),
                    draft.trange(start_us, end_us - start_us),
                    style=draft.TextStyle(
                        size=7.0,
                        align=1,
                        auto_wrapping=True,
                        max_line_width=0.86,
                    ),
                    clip_settings=draft.ClipSettings(transform_y=-0.8),
                    border=draft.TextBorder(width=40.0),
                )
                script.add_segment(text_seg, text_ref)
                last_end_us = end_us
        script.save()
    except JianyingDraftError:
        raise
    except Exception as exc:
        raise JianyingDraftError("写入剪映草稿失败", detail=str(exc)) from exc

    return {
        "draft_name": name,
        "drafts_dir": root,
        "draft_path": os.path.join(root, name),
        "exported_count": len(spans),
        "caption_count": len(captions),
    }


def _place_clip_onto_track(
    script,
    draft_mod,
    track_ref,
    *,
    video_path: str,
    timeline_start_sec: float,
    source_start_sec: float,
    duration_sec: float,
) -> None:
    """Place a source range onto ``track_ref`` at the query timeline offset."""
    media = os.path.abspath(os.path.expanduser(str(video_path or "").strip()))
    if not media or not os.path.isfile(media):
        raise JianyingDraftError("找不到视频文件", detail=media or "(empty)")
    duration = max(float(duration_sec or 0.0), 0.05)
    start_us = max(int(round(float(timeline_start_sec or 0.0) * 1_000_000)), 0)
    clip_start = max(float(source_start_sec or 0.0), 0.0)
    segment = _make_video_segment(
        draft_mod,
        media,
        timeline_start_us=start_us,
        clip_start=clip_start,
        duration=duration,
    )
    script.add_segment(segment, track_ref)


def _remove_draft_folder(root: str, name: str) -> None:
    import shutil

    draft_path = os.path.join(root, name)
    try:
        if os.path.isdir(draft_path):
            shutil.rmtree(draft_path)
    except OSError:
        pass


def export_clone_match_to_jianying_draft(
    segments: Sequence[Mapping[str, Any]],
    *,
    drafts_dir: str | None = None,
    draft_name: str | None = None,
    title: str = "",
    timeline_fps: float = 24.0,
    export_mode: str | None = None,
    query_path: str = "",
    config=None,
) -> Dict[str, Any]:
    """Create a plaintext clone-match draft: query-aligned V1/V2/V3 video tracks."""
    if not is_jianying_draft_support_available():
        raise JianyingDraftError(
            "未安装 pyJianYingDraft",
            detail="请在 VideoSeek 环境执行：pip install pyJianYingDraft",
        )
    rows = [dict(item or {}) for item in (segments or [])]
    if not rows:
        raise JianyingDraftError("没有可写入剪映的匹配片段")

    from src.services.nle_timeline_export import _prepare_clone_timeline_clips

    by_track, media_cache, _max_end = _prepare_clone_timeline_clips(
        rows,
        timeline_fps=max(float(timeline_fps or 24.0), 1.0),
        export_mode=export_mode,
    )
    if not by_track:
        raise JianyingDraftError("没有可写入剪映的匹配片段")

    root = str(drafts_dir or resolve_jianying_drafts_dir(config=config) or "").strip()
    if not root or not os.path.isdir(root):
        raise JianyingDraftError(
            "找不到剪映草稿目录",
            detail="请选择剪映工程里的草稿根目录（含各草稿子文件夹的那一层）。",
        )
    root = os.path.abspath(root)

    name = str(draft_name or "").strip()
    if not name:
        slug_src = title or os.path.splitext(os.path.basename(str(query_path or "").strip()))[0]
        slug = _safe_draft_slug(slug_src, fallback="匹配")
        name = allocate_unique_draft_name(root, f"{_CLONE_DRAFT_PREFIX}-{slug}")

    width, height, fps = 1920, 1080, 24
    if media_cache:
        first = next(iter(media_cache.values()))
        width = int(first.get("width") or 1920)
        height = int(first.get("height") or 1080)
        probed_fps = float(first.get("fps") or 0.0)
        if probed_fps >= 12:
            fps = probed_fps
    canvas_w, canvas_h, fps_i = _draft_canvas(width=width, height=height, fps=fps)

    import pyJianYingDraft as draft
    from pyJianYingDraft.exceptions import SegmentOverlap

    folder = draft.DraftFolder(root)
    try:
        script = folder.create_draft(name, canvas_w, canvas_h, fps=fps_i, allow_replace=False)
        track_refs: dict[int, Any] = {}
        for track_id in sorted(by_track):
            label = _CLONE_TRACK_NAMES.get(int(track_id), f"VideoSeek V{int(track_id)}")
            track_refs[int(track_id)] = script.append_track(
                draft.TrackSpec(draft.TrackType.video, name=label)
            )
    except FileExistsError as exc:
        raise JianyingDraftError("同名草稿已存在", detail=name) from exc
    except Exception as exc:
        raise JianyingDraftError("创建剪映草稿失败", detail=str(exc)) from exc

    exported = 0
    skipped: List[Dict[str, str]] = []
    try:
        for track_id, clips in sorted(by_track.items()):
            ref = track_refs.get(int(track_id))
            if ref is None:
                continue
            ordered = sorted(clips, key=lambda item: float(item.get("query_start") or 0.0))
            for clip in ordered:
                path = str(clip.get("path") or "").strip()
                if not path or not os.path.isfile(path):
                    skipped.append({"path": path or "(empty)", "reason": "missing"})
                    continue
                try:
                    _place_clip_onto_track(
                        script,
                        draft,
                        ref,
                        video_path=path,
                        timeline_start_sec=float(clip.get("query_start") or 0.0),
                        source_start_sec=float(clip.get("source_start") or 0.0),
                        duration_sec=float(clip.get("duration_sec") or 0.0),
                    )
                    exported += 1
                except SegmentOverlap:
                    skipped.append({"path": path, "reason": "overlap"})
                except JianyingDraftError as exc:
                    skipped.append({"path": path, "reason": exc.summary})
                except Exception as exc:
                    skipped.append({"path": path, "reason": str(exc)})
        if exported <= 0:
            _remove_draft_folder(root, name)
            detail = skipped[0]["reason"] if skipped else "no clips"
            raise JianyingDraftError("没有可写入剪映的本地片段", detail=detail)
        script.save()
    except JianyingDraftError:
        raise
    except Exception as exc:
        _remove_draft_folder(root, name)
        raise JianyingDraftError("写入剪映草稿失败", detail=str(exc)) from exc

    return {
        "draft_name": name,
        "drafts_dir": root,
        "draft_path": os.path.join(root, name),
        "exported_count": exported,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "track_count": len(track_refs),
    }


def create_jianying_draft(
    *,
    drafts_dir: str,
    draft_name: str,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
) -> str:
    if not is_jianying_draft_support_available():
        raise JianyingDraftError(
            "未安装 pyJianYingDraft",
            detail="请在 VideoSeek 环境执行：pip install pyJianYingDraft",
        )

    import pyJianYingDraft as draft

    root = os.path.abspath(str(drafts_dir or "").strip())
    name = str(draft_name or "").strip()
    if not root or not os.path.isdir(root):
        raise JianyingDraftError("找不到剪映草稿目录", detail=root or "(empty)")
    if not name:
        raise JianyingDraftError("草稿名称不能为空")

    folder = draft.DraftFolder(root)
    try:
        script = folder.create_draft(name, int(width), int(height), fps=int(fps), allow_replace=False)
        script.append_track(draft.TrackSpec(draft.TrackType.video, name=_VIDEOSEEK_TRACK_NAME))
        script.save()
    except FileExistsError as exc:
        raise JianyingDraftError("同名草稿已存在", detail=name) from exc
    except Exception as exc:
        raise JianyingDraftError("创建剪映草稿失败", detail=str(exc)) from exc
    return name


def create_videoseek_collect_draft(*, drafts_dir: str, prefix: str = _DEFAULT_COLLECT_DRAFT_PREFIX) -> str:
    """Create a fresh plaintext draft dedicated to VideoSeek appends."""
    root = os.path.abspath(str(drafts_dir or "").strip())
    candidate = allocate_unique_draft_name(root, prefix)
    return create_jianying_draft(drafts_dir=root, draft_name=candidate)


def filter_draft_names(drafts: Sequence[JianyingDraftInfo], query: str = "") -> List[JianyingDraftInfo]:
    needle = str(query or "").strip().lower()
    if not needle:
        return list(drafts)
    return [item for item in drafts if needle in item.name.lower()]
