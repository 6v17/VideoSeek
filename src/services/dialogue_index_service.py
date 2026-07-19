"""Compatibility facade: dialogue indexing now builds the shared subtitle library via OCR.

Prefer ``src.services.subtitle_index_service`` for new code. This module keeps existing
UI/worker imports working while ASR is retired.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Literal

ProgressCallback = Callable[[float, str], None]
StopCallback = Callable[[], bool]
DialogueIndexMode = Literal["auto", "asr", "reembed", "ocr", "reuse"]


def list_dialogue_index_targets(*, config=None) -> list[dict[str, str]]:
    """Library videos on disk (candidates for subtitle indexing).

    Does not require visual/CLIP sync. Ensures file records exist via
    ``register_library_videos`` so a folder only needs to be added first.
    """
    from src.services.library_service import register_library_videos
    from src.storage.asset_store import load_model_metadata
    from src.utils import canonicalize_library_path

    cfg = config
    register_library_videos(config=cfg)
    meta = load_model_metadata(config=cfg)
    targets: list[dict[str, str]] = []
    libraries = (meta or {}).get("libraries") or {}
    if not isinstance(libraries, dict):
        return []
    for root_path, lib_data in libraries.items():
        if not isinstance(lib_data, dict):
            continue
        files = lib_data.get("files") or {}
        if not isinstance(files, dict):
            continue
        library_path = canonicalize_library_path(root_path)
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            video_id = str(info.get("vid", "") or "").strip()
            if not video_id:
                continue
            video_path = os.path.normpath(os.path.join(root_path, str(rel_path or "")))
            if not video_path or not os.path.isfile(video_path):
                continue
            targets.append(
                {
                    "video_id": video_id,
                    "video_path": video_path,
                    "library_path": library_path,
                }
            )
    return targets


def list_shared_dialogue_library(*, config=None) -> list[dict[str, Any]]:
    from src.services.subtitle_index_service import list_subtitle_library

    return list_subtitle_library(config=config)


def list_dialogue_reembed_targets(*, config=None) -> list[dict[str, str]]:
    """Videos that already have shared subtitle/transcript JSON."""
    from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

    by_id = {item["video_id"]: item for item in list_dialogue_index_targets(config=config)}
    targets: list[dict[str, str]] = []
    for record in list_dialogue_transcript_summaries(config=config):
        video_id = str(record.get("video_id") or "").strip()
        if not video_id:
            continue
        base = by_id.get(video_id) or {}
        targets.append(
            {
                "video_id": video_id,
                "video_path": str(base.get("video_path") or record.get("video_path") or ""),
                "library_path": str(base.get("library_path") or record.get("library_path") or ""),
            }
        )
    return targets


def ensure_dialogue_asr_ready(*, config=None) -> tuple[bool, str]:
    """Shim name kept for UI: now checks RapidOCR readiness."""
    from src.services.subtitle_index_service import ensure_subtitle_ocr_ready

    return ensure_subtitle_ocr_ready(config=config)


def index_video_dialogue(
    video_id: str,
    video_path: str,
    *,
    library_path: str = "",
    config=None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
    language: str = "auto",
    keep_wav: bool = False,
    mode: DialogueIndexMode = "auto",
) -> dict[str, Any]:
    """Build shared subtitle cues (VAD + RapidOCR). ``language`` ignored."""
    del language
    from src.services.subtitle_index_service import index_video_subtitles

    mode_value = str(mode or "auto").strip().lower()
    if mode_value in {"asr", "ocr"}:
        subtitle_mode = "ocr"
    elif mode_value == "reembed":
        subtitle_mode = "reuse"
    else:
        subtitle_mode = "auto"
    return index_video_subtitles(
        video_id,
        video_path,
        library_path=library_path,
        config=config,
        progress_callback=progress_callback,
        stop_callback=stop_callback,
        keep_wav=keep_wav,
        mode=subtitle_mode,
    )
