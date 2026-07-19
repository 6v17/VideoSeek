"""Build shared subtitle library via VAD + frame OCR (RapidOCR ONNX).

Pipeline: FFmpeg PCM pipe → Silero VAD → sample frames inside speech segments
→ decode thread + bounded queue → RapidOCR on main thread (CLIP-style overlap)
→ shared transcript JSON.
Keyword search reads the shared store; CLIP semantic search is deferred.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from typing import Any, Literal

import numpy as np

from src.app.logging_utils import get_logger
from src.core.asr.vad_segment import segment_media_speech
from src.core.subtitle_ocr.frame_sample import sample_times_in_segment
from src.core.subtitle_ocr.merge_cues import merge_ocr_observations
from src.core.subtitle_ocr.ocr_pipeline import collect_ocr_observations
from src.core.subtitle_ocr.rapidocr_engine import (
    OCR_COMPONENT_ID,
    is_rapidocr_available,
    ocr_frame_to_line,
    resolve_rapidocr_model_dir,
)
from src.media.probe import get_video_duration_seconds
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.dialogue_transcript_store import (
    ensure_shared_transcripts,
    list_shared_transcript_segments,
    save_dialogue_transcript,
)
from src.storage.lance_store import (
    DIALOGUE_INDEX_STATE_FAILED,
    DIALOGUE_INDEX_STATE_READY,
    set_dialogue_index_state,
)
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("subtitle_index")

ProgressCallback = Callable[[float, str], None]
StopCallback = Callable[[], bool]
SubtitleIndexMode = Literal["auto", "ocr", "reuse"]

OCR_SOURCE_ID = OCR_COMPONENT_ID

# Absolute safety valve only (≈2h speech @ 0.8s). Normal budget comes from VAD speech seconds.
_SUBTITLE_FRAME_BUDGET_SAFETY_MAX = 9000


def _stopped(stop_callback: StopCallback | None) -> bool:
    return bool(stop_callback and stop_callback())


def _speech_duration_sec(segments: Sequence[Any]) -> float:
    total = 0.0
    for seg in segments or []:
        start = float(getattr(seg, "start_sec", 0.0) or (seg.get("start_sec") if isinstance(seg, dict) else 0.0) or 0.0)
        end = float(getattr(seg, "end_sec", start) or (seg.get("end_sec") if isinstance(seg, dict) else start) or start)
        total += max(0.0, end - start)
    return total


def resolve_subtitle_frame_budget(
    speech_sec: float,
    *,
    sample_interval_sec: float,
    segment_count: int = 0,
    max_total_frames: int = 0,
) -> int:
    """Budget OCR frames from VAD speech duration and sample interval.

    ``max_total_frames <= 0``: fully dynamic (only a large safety ceiling).
    ``max_total_frames > 0``: optional hard ceiling on top of the dynamic estimate.
    """
    interval = max(0.1, float(sample_interval_sec))
    speech = max(0.0, float(speech_sec))
    # Expected samples ≈ speech/interval, plus a little headroom for segment edges.
    expected = int(math.ceil(speech / interval)) + max(0, int(segment_count))
    expected = int(math.ceil(expected * 1.05)) + 8
    floor = 40
    ceiling = _SUBTITLE_FRAME_BUDGET_SAFETY_MAX
    if int(max_total_frames) > 0:
        ceiling = min(ceiling, int(max_total_frames))
    return max(floor, min(expected, ceiling))


def ensure_subtitle_ocr_ready(*, config=None) -> tuple[bool, str]:
    if not is_rapidocr_available():
        return False, "rapidocr-onnxruntime is not installed (pip install rapidocr-onnxruntime)"
    if not resolve_rapidocr_model_dir(config=config):
        return (
            False,
            f"RapidOCR model not imported: {OCR_COMPONENT_ID}. "
            "Import the understanding zip (Understanding / Settings → Import Model).",
        )
    return True, ""


def list_subtitle_index_targets(*, config=None) -> list[dict[str, str]]:
    """Library videos on disk (no visual sync required; add-library is enough)."""
    from src.services.dialogue_index_service import list_dialogue_index_targets

    return list_dialogue_index_targets(config=config)


def list_subtitle_library(*, config=None) -> list[dict[str, Any]]:
    from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

    ensure_shared_transcripts(config=config)
    by_id = {item["video_id"]: item for item in list_subtitle_index_targets(config=config)}
    rows: list[dict[str, Any]] = []
    for record in list_dialogue_transcript_summaries(config=config):
        video_id = str(record.get("video_id") or "").strip()
        if not video_id:
            continue
        base = by_id.get(video_id) or {}
        rows.append(
            {
                "video_id": video_id,
                "video_path": str(base.get("video_path") or record.get("video_path") or ""),
                "library_path": str(base.get("library_path") or record.get("library_path") or ""),
                "segment_count": int(record.get("segment_count") or 0),
                "asr_source": str(record.get("asr_source") or ""),
                "has_transcript": True,
                "has_current_vectors": False,
            }
        )
    rows.sort(key=lambda item: item["video_id"])
    return rows


def index_video_subtitles(
    video_id: str,
    video_path: str,
    *,
    library_path: str = "",
    config=None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
    keep_wav: bool = False,
    mode: SubtitleIndexMode = "auto",
    sample_interval_sec: float = 1.2,
    max_frames_per_segment: int = 0,
    max_total_frames: int = 0,
) -> dict[str, Any]:
    """Extract hard-subtitle cues: VAD speech segments → sparse frames → RapidOCR.

    Default sample interval is 1.2s. Per-segment frame cap is off by default
    (``max_frames_per_segment<=0``). Whole-video OCR budget is derived from
    VAD speech duration / interval; ``max_total_frames>0`` only sets an optional ceiling.
    ``keep_wav`` is accepted for API compatibility (default uses PCM pipe).
    """
    del keep_wav
    video_id = str(video_id or "").strip()
    media_path = os.path.normpath(os.path.abspath(str(video_path or "").strip())) if video_path else ""
    if not video_id:
        return {"ok": False, "error": "missing video_id", "segment_rows": 0}

    try:
        sample_interval_sec = float(sample_interval_sec)
    except (TypeError, ValueError):
        sample_interval_sec = 1.2
    sample_interval_sec = max(0.1, min(6.0, sample_interval_sec))

    mode_value = str(mode or "auto").strip().lower()
    if mode_value not in {"auto", "ocr", "reuse"}:
        mode_value = "auto"

    model_dirs = get_local_model_asset_dirs(config=config)
    profile_base_dir = model_dirs["base_dir"]
    lib_path = canonicalize_library_path(library_path) if library_path else ""

    existing = [] if mode_value == "ocr" else list_shared_transcript_segments(video_id, config=config)
    if mode_value == "auto" and existing:
        mode_value = "reuse"
    if mode_value == "reuse":
        if not existing:
            return {"ok": False, "error": "no shared subtitles to reuse", "segment_rows": 0, "mode": "reuse"}
        try:
            set_dialogue_index_state(
                profile_base_dir,
                video_id,
                DIALOGUE_INDEX_STATE_READY,
                extras={
                    "dialogue_segment_rows": len(existing),
                    "dialogue_asr_source": str((existing[0] or {}).get("asr_source") or OCR_SOURCE_ID),
                    "dialogue_error": "",
                },
            )
        except Exception as state_exc:
            logger.warning(
                "Subtitle reuse state update failed for %s: %s",
                video_id,
                state_exc,
            )
        if progress_callback:
            progress_callback(1.0, "subtitle_reuse")
        return {
            "ok": True,
            "video_id": video_id,
            "segment_rows": len(existing),
            "mode": "reuse",
            "reused_transcripts": True,
            "asr_source": str((existing[0] or {}).get("asr_source") or OCR_SOURCE_ID),
        }

    if not media_path or not os.path.isfile(media_path):
        return {"ok": False, "error": f"video not found: {video_path!r}", "segment_rows": 0}
    ready, ready_error = ensure_subtitle_ocr_ready(config=config)
    if not ready:
        return {"ok": False, "error": ready_error, "segment_rows": 0, "mode": "ocr"}

    try:
        if progress_callback:
            progress_callback(0.04, "subtitle_extract_audio")
        if _stopped(stop_callback):
            return {"ok": False, "error": "stopped", "segment_rows": 0}

        def _vad_progress(ratio: float, stage: str) -> None:
            if not progress_callback:
                return
            stage_name = "subtitle_extract_audio" if "extract" in str(stage) else "subtitle_vad"
            progress_callback(0.04 + 0.14 * max(0.0, min(1.0, float(ratio))), stage_name)

        speech = segment_media_speech(media_path, progress_callback=_vad_progress)
        segments = list(speech or [])

        duration = float(get_video_duration_seconds(media_path) or 0.0)
        if not segments:
            save_dialogue_transcript(
                video_id,
                [],
                library_path=lib_path,
                video_path=media_path,
                asr_source=OCR_SOURCE_ID,
                config=config,
            )
            try:
                set_dialogue_index_state(
                    profile_base_dir,
                    video_id,
                    DIALOGUE_INDEX_STATE_READY,
                    extras={
                        "dialogue_segment_rows": 0,
                        "dialogue_asr_source": OCR_SOURCE_ID,
                        "dialogue_error": "",
                    },
                )
            except Exception as state_exc:
                logger.warning(
                    "Empty-subtitle state update failed for %s: %s",
                    video_id,
                    state_exc,
                )
            if progress_callback:
                progress_callback(1.0, "subtitle_done")
            return {
                "ok": True,
                "video_id": video_id,
                "segment_rows": 0,
                "mode": "ocr",
                "speech_segments": 0,
                "sample_frames": 0,
            }

        times: list[float] = []
        for seg in segments:
            start = float(getattr(seg, "start_sec", 0.0) or 0.0)
            end = float(getattr(seg, "end_sec", start) or start)
            times.extend(
                sample_times_in_segment(
                    start,
                    end,
                    interval_sec=sample_interval_sec,
                    max_frames=max_frames_per_segment,
                )
            )
        deduped: list[float] = []
        min_spacing = max(0.05, min(0.35, float(sample_interval_sec) * 0.4))
        for t in sorted(times):
            if not deduped or abs(t - deduped[-1]) >= min_spacing:
                deduped.append(t)
        times = deduped

        speech_sec = _speech_duration_sec(segments)
        frame_cap = resolve_subtitle_frame_budget(
            speech_sec,
            sample_interval_sec=sample_interval_sec,
            segment_count=len(segments),
            max_total_frames=max_total_frames,
        )
        if len(times) > frame_cap:
            logger.info(
                "Subtitle OCR frame budget trim: speech=%.1fs interval=%.2fs times=%d -> cap=%d",
                speech_sec,
                sample_interval_sec,
                len(times),
                frame_cap,
            )
            idxs = np.linspace(0, len(times) - 1, num=frame_cap, dtype=int)
            times = [times[int(i)] for i in idxs]
        else:
            logger.info(
                "Subtitle OCR frame budget: speech=%.1fs interval=%.2fs times=%d cap=%d",
                speech_sec,
                sample_interval_sec,
                len(times),
                frame_cap,
            )

        if _stopped(stop_callback):
            return {"ok": False, "error": "stopped", "segment_rows": 0}
        if progress_callback:
            progress_callback(0.20, f"subtitle_ocr|0|{max(1, len(times))}")

        def _ocr_roi(roi):
            return ocr_frame_to_line(roi, config=config)

        try:
            observations = collect_ocr_observations(
                media_path,
                times,
                ocr_fn=_ocr_roi,
                duration=duration,
                asr_source=OCR_SOURCE_ID,
                stop_callback=stop_callback,
                progress_callback=progress_callback,
                progress_base=0.20,
                progress_span=0.70,
                queue_size=12,
            )
        except InterruptedError:
            return {"ok": False, "error": "stopped", "segment_rows": 0}

        if progress_callback:
            progress_callback(0.92, "subtitle_merge")
        cues = merge_ocr_observations(observations)
        save = save_dialogue_transcript(
            video_id,
            cues,
            library_path=lib_path,
            video_path=media_path,
            asr_source=OCR_SOURCE_ID,
            config=config,
        )
        if not save.get("ok"):
            set_dialogue_index_state(
                profile_base_dir,
                video_id,
                DIALOGUE_INDEX_STATE_FAILED,
                extras={"dialogue_error": str(save.get("error") or "save failed")},
            )
            return {"ok": False, "error": save.get("error") or "save failed", "segment_rows": 0, "mode": "ocr"}

        try:
            set_dialogue_index_state(
                profile_base_dir,
                video_id,
                DIALOGUE_INDEX_STATE_READY,
                extras={
                    "dialogue_segment_rows": int(save.get("segment_count") or len(cues)),
                    "dialogue_asr_source": OCR_SOURCE_ID,
                    "dialogue_error": "",
                },
            )
        except Exception as state_exc:
            logger.warning(
                "Subtitle transcript saved but dialogue index state update failed for %s: %s",
                video_id,
                state_exc,
            )
        if progress_callback:
            progress_callback(1.0, "subtitle_done")
        return {
            "ok": True,
            "video_id": video_id,
            "segment_rows": int(save.get("segment_count") or len(cues)),
            "speech_segments": len(segments),
            "sample_frames": len(times),
            "mode": "ocr",
            "reused_transcripts": False,
            "asr_source": OCR_SOURCE_ID,
        }
    except Exception as exc:
        logger.exception("Subtitle index failed for %s: %s", video_id, exc)
        try:
            set_dialogue_index_state(
                profile_base_dir,
                video_id,
                DIALOGUE_INDEX_STATE_FAILED,
                extras={"dialogue_error": str(exc)},
            )
        except Exception:
            pass
        return {"ok": False, "error": str(exc), "segment_rows": 0, "mode": "ocr"}
