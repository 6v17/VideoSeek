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
    """Subtitle-library videos on disk (candidates for OCR indexing).

    Uses the global subtitle registry (``dialogue/library.db``), not the CLIP
    visual library. Does not require visual sync — add-library on the subtitle
    tab is enough.
    """
    from src.services.subtitle_library_service import list_subtitle_library_video_entries

    targets: list[dict[str, str]] = []
    for item in list_subtitle_library_video_entries(config=config, register=True):
        if not item.get("source_exists"):
            continue
        video_id = str(item.get("video_id") or "").strip()
        video_path = str(item.get("video_path") or "").strip()
        if not video_id or not video_path:
            continue
        targets.append(
            {
                "video_id": video_id,
                "video_path": video_path,
                "library_path": str(item.get("library_path") or ""),
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
    sample_interval_sec: float | None = None,
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
    kwargs = {
        "library_path": library_path,
        "config": config,
        "progress_callback": progress_callback,
        "stop_callback": stop_callback,
        "keep_wav": keep_wav,
        "mode": subtitle_mode,
    }
    if sample_interval_sec is not None:
        kwargs["sample_interval_sec"] = float(sample_interval_sec)
    return index_video_subtitles(video_id, video_path, **kwargs)
