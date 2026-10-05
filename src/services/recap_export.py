"""Export a saved recap cut list to FCPXML.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from src.media.fcpxml import layout_clips_on_timeline, write_fcpxml
from src.services.recap_runtime import _probe_media
from src.services.recap_vo_budget import stretch_recap_clips_for_vo

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
