"""Build shared subtitle library via timeline/VAD probe + frame OCR (RapidOCR ONNX).

Pipeline strategies:
- ``timeline``: sample across the full video (better for BGM-heavy PVs)
- ``vad``: Silero VAD speech segments only (faster for dialogue-heavy media)

Both paths share: decode + blank/unchanged subtitle-band gates → RapidOCR on
changed plates → shared transcript JSON.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Sequence
from typing import Any, Literal

import numpy as np

from src.app.logging_utils import get_logger
from src.core.asr.vad_segment import segment_media_speech
from src.core.subtitle_ocr.frame_sample import (
    sample_times_across_timeline,
    sample_times_in_segment,
)
from src.core.subtitle_ocr.merge_cues import merge_ocr_observations
from src.core.subtitle_ocr.ocr_pipeline import collect_ocr_observations
from src.core.subtitle_ocr.rapidocr_engine import (
    OCR_COMPONENT_ID,
    is_rapidocr_available,
    ocr_frame_to_line,
    ocr_frames_to_lines,
    resolve_rapidocr_model_dir,
    resolve_subtitle_ocr_batch_size,
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
SubtitleSampleStrategy = Literal["timeline", "vad"]

OCR_SOURCE_ID = OCR_COMPONENT_ID
SUBTITLE_SAMPLE_STRATEGY_TIMELINE = "timeline"
SUBTITLE_SAMPLE_STRATEGY_VAD = "vad"
DEFAULT_SUBTITLE_SAMPLE_STRATEGY = SUBTITLE_SAMPLE_STRATEGY_TIMELINE

# Absolute safety valve for probe timestamps (decode cost). OCR is gated separately.
_SUBTITLE_FRAME_BUDGET_SAFETY_MAX = 9000


def _stopped(stop_callback: StopCallback | None) -> bool:
    return bool(stop_callback and stop_callback())


def normalize_subtitle_sample_strategy(value: str | None) -> SubtitleSampleStrategy:
    text = str(value or "").strip().lower()
    if text in {"vad", "speech", "fast"}:
        return SUBTITLE_SAMPLE_STRATEGY_VAD
    if text in {"timeline", "full", "probe", "pv"}:
        return SUBTITLE_SAMPLE_STRATEGY_TIMELINE
    return DEFAULT_SUBTITLE_SAMPLE_STRATEGY


def resolve_subtitle_sample_strategy(*, config=None, explicit: str | None = None) -> SubtitleSampleStrategy:
    if explicit is not None and str(explicit).strip():
        return normalize_subtitle_sample_strategy(explicit)
    try:
        from src.app.config import DEFAULT_CONFIG, load_config

        cfg = dict(config or load_config())
        return normalize_subtitle_sample_strategy(
            cfg.get(
                "subtitle_sample_strategy",
                DEFAULT_CONFIG.get("subtitle_sample_strategy", DEFAULT_SUBTITLE_SAMPLE_STRATEGY),
            )
        )
    except Exception:
        return DEFAULT_SUBTITLE_SAMPLE_STRATEGY


def _speech_duration_sec(segments: Sequence[Any]) -> float:
    total = 0.0
    for seg in segments or []:
        start = float(getattr(seg, "start_sec", 0.0) or (seg.get("start_sec") if isinstance(seg, dict) else 0.0) or 0.0)
        end = float(getattr(seg, "end_sec", start) or (seg.get("end_sec") if isinstance(seg, dict) else start) or start)
        total += max(0.0, end - start)
    return total


def resolve_subtitle_frame_budget(
    span_sec: float,
    *,
    sample_interval_sec: float,
    max_total_frames: int = 0,
    segment_count: int = 0,
) -> int:
    """Budget probe timestamps from a time span (full duration or VAD speech).

    ``segment_count`` adds a little headroom for VAD segment edges.
    ``max_total_frames <= 0``: fully dynamic (only a large safety ceiling).
    ``max_total_frames > 0``: optional hard ceiling on top of the dynamic estimate.
    """
    interval = max(0.1, float(sample_interval_sec))
    span = max(0.0, float(span_sec))
    expected = int(math.ceil(span / interval)) + max(0, int(segment_count))
    expected = int(math.ceil(expected * 1.05)) + 8
    floor = 40
    ceiling = _SUBTITLE_FRAME_BUDGET_SAFETY_MAX
    if int(max_total_frames) > 0:
        ceiling = min(ceiling, int(max_total_frames))
    return max(floor, min(expected, ceiling))


def ensure_subtitle_ocr_ready(*, config=None, import_engine: bool = True) -> tuple[bool, str]:
    """Check RapidOCR models/config. ``import_engine=False`` skips importing ORT on the UI thread."""
    if import_engine and not is_rapidocr_available():
        return False, "rapidocr-onnxruntime is not installed (pip install rapidocr-onnxruntime)"
    if not resolve_rapidocr_model_dir(config=config):
        return (
            False,
            f"RapidOCR model not imported: {OCR_COMPONENT_ID}. "
            "Import the understanding zip (Understanding / Settings → Import Model).",
        )
    try:
        from src.core.subtitle_ocr.rapidocr_engine import resolve_rapidocr_config_path

        resolve_rapidocr_config_path()
    except Exception as exc:
        return False, str(exc).strip() or "RapidOCR config.yaml is missing"
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


def _build_probe_times_timeline(
    *,
    duration: float,
    sample_interval_sec: float,
    max_total_frames: int,
) -> tuple[list[float], int]:
    frame_cap = resolve_subtitle_frame_budget(
        duration,
        sample_interval_sec=sample_interval_sec,
        max_total_frames=max_total_frames,
    )
    times = sample_times_across_timeline(
        duration,
        interval_sec=sample_interval_sec,
        max_frames=frame_cap,
    )
    logger.info(
        "Subtitle OCR probe plan (timeline): duration=%.1fs interval=%.2fs times=%d cap=%d",
        duration,
        sample_interval_sec,
        len(times),
        frame_cap,
    )
    return times, frame_cap


def _build_probe_times_vad(
    *,
    media_path: str,
    duration: float,
    sample_interval_sec: float,
    max_frames_per_segment: int,
    max_total_frames: int,
    progress_callback: ProgressCallback | None,
    stop_callback: StopCallback | None,
) -> tuple[list[float], int, int]:
    def _vad_progress(ratio: float, stage: str) -> None:
        if not progress_callback:
            return
        stage_name = "subtitle_extract_audio" if "extract" in str(stage) else "subtitle_vad"
        progress_callback(0.04 + 0.14 * max(0.0, min(1.0, float(ratio))), stage_name)

    if progress_callback:
        progress_callback(0.04, "subtitle_extract_audio")
    if _stopped(stop_callback):
        raise InterruptedError("stopped")

    segments = list(segment_media_speech(media_path, progress_callback=_vad_progress) or [])
    if not segments:
        logger.info("Subtitle OCR VAD found no speech segments for %s", media_path)
        return [], 0, 0

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
            "Subtitle OCR frame budget trim (vad): speech=%.1fs interval=%.2fs times=%d -> cap=%d",
            speech_sec,
            sample_interval_sec,
            len(times),
            frame_cap,
        )
        idxs = np.linspace(0, len(times) - 1, num=frame_cap, dtype=int)
        times = [times[int(i)] for i in idxs]
    else:
        logger.info(
            "Subtitle OCR probe plan (vad): speech=%.1fs duration=%.1fs interval=%.2fs times=%d cap=%d",
            speech_sec,
            duration,
            sample_interval_sec,
            len(times),
            frame_cap,
        )
    return times, frame_cap, len(segments)


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
    sample_strategy: str | None = None,
    ocr_batch_size: int | None = None,
    max_frames_per_segment: int = 0,
    max_total_frames: int = 0,
) -> dict[str, Any]:
    """Extract hard-subtitle cues with change-gated RapidOCR.

    ``sample_strategy``:
    - ``timeline``: probe the full video (default; better for BGM/PV);
      OCR both a top title band (~0–20%) and bottom dialogue band (~60–100%)
    - ``vad``: only sample inside Silero speech segments (faster for dialogue);
      bottom band only

    Blank / unchanged subtitle bands are skipped so OCR cost tracks subtitle
    changes. ``max_total_frames>0`` only caps probe count.
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
    strategy = resolve_subtitle_sample_strategy(config=config, explicit=sample_strategy)
    if ocr_batch_size is None:
        batch_size = resolve_subtitle_ocr_batch_size(config=config)
    else:
        try:
            batch_size = max(1, min(6, int(ocr_batch_size)))
        except (TypeError, ValueError):
            batch_size = 1

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
        if _stopped(stop_callback):
            return {"ok": False, "error": "stopped", "segment_rows": 0}

        duration = float(get_video_duration_seconds(media_path) or 0.0)
        if duration <= 1e-3:
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
                "sample_strategy": strategy,
                "sample_frames": 0,
                "speech_segments": 0,
                "probed": 0,
                "ocr_calls": 0,
                "blank_skips": 0,
                "unchanged_skips": 0,
            }

        speech_segments = 0
        if strategy == SUBTITLE_SAMPLE_STRATEGY_VAD:
            times, _frame_cap, speech_segments = _build_probe_times_vad(
                media_path=media_path,
                duration=duration,
                sample_interval_sec=sample_interval_sec,
                max_frames_per_segment=max_frames_per_segment,
                max_total_frames=max_total_frames,
                progress_callback=progress_callback,
                stop_callback=stop_callback,
            )
            if not times:
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
                    "sample_strategy": strategy,
                    "sample_frames": 0,
                    "speech_segments": 0,
                    "probed": 0,
                    "ocr_calls": 0,
                    "blank_skips": 0,
                    "unchanged_skips": 0,
                }
        else:
            if progress_callback:
                progress_callback(0.06, "subtitle_probe")
            times, _frame_cap = _build_probe_times_timeline(
                duration=duration,
                sample_interval_sec=sample_interval_sec,
                max_total_frames=max_total_frames,
            )

        if _stopped(stop_callback):
            return {"ok": False, "error": "stopped", "segment_rows": 0}
        if progress_callback:
            progress_callback(0.20, f"subtitle_ocr|0|{max(1, len(times))}")

        def _ocr_roi(roi):
            return ocr_frame_to_line(roi, config=config)

        def _ocr_rois(rois):
            return ocr_frames_to_lines(rois, config=config)

        probe_stats: dict[str, int] = {}
        try:
            observations = collect_ocr_observations(
                media_path,
                times,
                ocr_fn=_ocr_roi,
                ocr_batch_fn=_ocr_rois,
                batch_size=batch_size,
                duration=duration,
                asr_source=OCR_SOURCE_ID,
                stop_callback=stop_callback,
                progress_callback=progress_callback,
                progress_base=0.20,
                progress_span=0.70,
                queue_size=max(12, batch_size * 3),
                stats_out=probe_stats,
                # Top titles/names: timeline/PV only. VAD stays bottom dialogue band.
                include_top_band=(strategy == SUBTITLE_SAMPLE_STRATEGY_TIMELINE),
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
            "sample_strategy": strategy,
            "sample_frames": len(times),
            "speech_segments": speech_segments,
            "probed": int(probe_stats.get("probed", 0) or 0),
            "ocr_calls": int(probe_stats.get("ocr_calls", 0) or 0),
            "blank_skips": int(probe_stats.get("blank_skips", 0) or 0),
            "unchanged_skips": int(probe_stats.get("unchanged_skips", 0) or 0),
            "mode": "ocr",
            "reused_transcripts": False,
            "asr_source": OCR_SOURCE_ID,
        }
    except InterruptedError:
        return {"ok": False, "error": "stopped", "segment_rows": 0}
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
