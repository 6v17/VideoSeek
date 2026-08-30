"""Speech ASR → shared dialogue transcript store."""

from __future__ import annotations

import os
import tempfile
import time
from collections.abc import Callable, Sequence
from typing import Any, Mapping

import numpy as np

from src.app.logging_utils import get_logger
from src.core.asr.audio_extract import DEFAULT_SAMPLE_RATE, encode_asr_upload_bytes, extract_audio_mono_f32
from src.core.asr.audio_io import write_wav_mono_f32
from src.core.asr.dialogue_segments import merge_adjacent_transcripts
from src.core.asr.transcribe_remote import (
    format_asr_error,
    is_empty_asr_result,
    is_transient_asr_error,
    parse_transcription_payload,
    transcribe_wav_bytes,
    uses_dashscope_chat_asr,
    uses_dashscope_native_audio_asr,
)
from src.core.understanding.base import UnderstandingStoppedError
from src.services.asr_settings import ASR_SOURCE_ID, get_remote_asr_settings
from src.storage.config_store import get_local_model_asset_dirs
from src.storage.dialogue_transcript_store import load_dialogue_transcript, save_dialogue_transcript
from src.storage.lance_store import DIALOGUE_INDEX_STATE_FAILED, DIALOGUE_INDEX_STATE_READY, set_dialogue_index_state
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("asr_index")

ProgressCallback = Callable[[float, str], None]
StopCallback = Callable[[], bool]

MAX_ASR_WINDOW_SEC = 20.0
MAX_ASR_GAP_SEC = 0.8
MIN_CLIP_SEC = 0.12
MIN_SPLIT_SEC = 8.0
PAD_SEC = 0.12
WINDOW_PAUSE_SEC = 0.35


def is_hardsub_ocr_source(source: str) -> bool:
    text = str(source or "").strip().lower()
    return "ocr" in text or text in {"subtitle", "subtitles"}


def pack_speech_windows(
    spans: Sequence[tuple[float, float] | Mapping[str, Any]] | None,
    *,
    duration_sec: float = 0.0,
    max_window_sec: float = MAX_ASR_WINDOW_SEC,
    max_gap_sec: float = MAX_ASR_GAP_SEC,
) -> list[tuple[float, float]]:
    """Merge nearby VAD spans into upload windows (OpenAI 25 MB / ~25 s audio)."""
    limit = max(4.0, float(max_window_sec or MAX_ASR_WINDOW_SEC))
    gap = max(0.0, float(max_gap_sec or 0.0))
    duration = max(0.0, float(duration_sec or 0.0))
    cleaned: list[tuple[float, float]] = []
    for item in spans or []:
        if isinstance(item, Mapping):
            start = float(item.get("start_sec", item.get("start", 0.0)) or 0.0)
            end = float(item.get("end_sec", item.get("end", start)) or start)
        else:
            start, end = float(item[0]), float(item[1])
        start = max(0.0, start)
        end = max(start, end)
        if duration > 0:
            end = min(end, duration)
        if end - start < MIN_CLIP_SEC:
            continue
        cleaned.append((start, end))
    if not cleaned:
        if duration < MIN_CLIP_SEC:
            return []
        windows: list[tuple[float, float]] = []
        cursor = 0.0
        while cursor < duration - 1e-6:
            windows.append((cursor, min(duration, cursor + limit)))
            cursor += limit
        return windows
    cleaned.sort()
    packed: list[tuple[float, float]] = []
    cur_start, cur_end = cleaned[0]
    for start, end in cleaned[1:]:
        if start - cur_end <= gap and (end - cur_start) <= limit:
            cur_end = max(cur_end, end)
            continue
        packed.extend(_split_oversize(cur_start, cur_end, limit))
        cur_start, cur_end = start, end
    packed.extend(_split_oversize(cur_start, cur_end, limit))
    return packed


def transcribe_video_asr(
    video_id: str,
    *,
    video_path: str = "",
    library_path: str = "",
    force: bool = False,
    language: str = "",
    config=None,
    progress_callback: ProgressCallback | None = None,
    stop_callback: StopCallback | None = None,
) -> dict[str, Any]:
    """Extract speech for one video and overwrite its shared dialogue transcript."""
    vid = str(video_id or "").strip()
    if not vid:
        return {"ok": False, "error": "missing video_id", "segment_count": 0}

    existing = load_dialogue_transcript(vid, config=config)
    if existing and not force:
        source = str(existing.get("asr_source") or "")
        count = int(existing.get("segment_count") or len(existing.get("segments") or []) or 0)
        if count > 0 and is_hardsub_ocr_source(source):
            return {
                "ok": True,
                "skipped": True,
                "reason": "ocr_exists",
                "video_id": vid,
                "segment_count": count,
                "asr_source": source,
            }

    media = os.path.normpath(str(video_path or (existing or {}).get("video_path") or ""))
    if not media or not os.path.isfile(media):
        return {"ok": False, "error": f"video not found: {media!r}", "segment_count": 0}

    settings = get_remote_asr_settings(config)
    if not str(settings.get("model") or "").strip():
        return {"ok": False, "error": "remote ASR model is not configured", "segment_count": 0}

    lib = canonicalize_library_path(library_path or (existing or {}).get("library_path") or "")
    profile_base_dir = get_local_model_asset_dirs(config=config)["base_dir"]

    def _progress(value: float, stage: str) -> None:
        if progress_callback:
            progress_callback(max(0.0, min(1.0, float(value))), stage)

    def _stopped() -> bool:
        return bool(stop_callback and stop_callback())

    try:
        if _stopped():
            raise UnderstandingStoppedError("ASR stopped by user")
        _progress(0.02, "extract_audio")
        waveform = extract_audio_mono_f32(media, progress_callback=None)
        duration = float(waveform.shape[0]) / float(DEFAULT_SAMPLE_RATE) if waveform.size else 0.0
        if duration < MIN_CLIP_SEC:
            return _save_empty(vid, lib, media, config=config, profile_base_dir=profile_base_dir)

        if _stopped():
            raise UnderstandingStoppedError("ASR stopped by user")
        _progress(0.18, "vad")
        spans, vad_ok = _speech_spans(waveform)
        if vad_ok and not spans:
            return _save_empty(vid, lib, media, config=config, profile_base_dir=profile_base_dir)
        windows = pack_speech_windows(spans, duration_sec=duration)
        if not windows:
            return _save_empty(vid, lib, media, config=config, profile_base_dir=profile_base_dir)

        rows: list[dict[str, Any]] = []
        total = max(1, len(windows))
        with tempfile.TemporaryDirectory(prefix="videoseek-asr-") as tmp:
            for index, (start, end) in enumerate(windows):
                if _stopped():
                    raise UnderstandingStoppedError("ASR stopped by user")
                _progress(0.22 + 0.72 * (index / total), f"asr_window:{index + 1}:{total}")
                rows.extend(
                    _transcribe_span(
                        waveform,
                        start,
                        end,
                        settings=settings,
                        language=language,
                        tmp_dir=tmp,
                        clip_index=index,
                        stop_callback=_stopped,
                    )
                )
                _progress(0.22 + 0.72 * ((index + 1) / total), f"asr_window:{index + 1}:{total}")
                if index + 1 < total:
                    time.sleep(WINDOW_PAUSE_SEC)

        merged = merge_adjacent_transcripts(rows)
        saved = save_dialogue_transcript(
            vid,
            merged,
            library_path=lib,
            video_path=media,
            asr_source=ASR_SOURCE_ID,
            config=config,
        )
        _mark_state(
            profile_base_dir,
            vid,
            DIALOGUE_INDEX_STATE_READY,
            extras={
                "dialogue_segment_rows": int(saved.get("segment_count") or len(merged)),
                "dialogue_asr_source": ASR_SOURCE_ID,
                "dialogue_error": "",
            },
        )
        _progress(1.0, "asr_done")
        return {
            "ok": True,
            "video_id": vid,
            "segment_count": int(saved.get("segment_count") or len(merged)),
            "window_count": len(windows),
            "asr_source": ASR_SOURCE_ID,
            "skipped": False,
        }
    except UnderstandingStoppedError:
        raise
    except Exception as exc:
        logger.exception("ASR transcribe failed for %s", vid)
        wrapped = format_asr_error(exc)
        _mark_state(
            profile_base_dir,
            vid,
            DIALOGUE_INDEX_STATE_FAILED,
            extras={"dialogue_error": wrapped[:300], "dialogue_asr_source": ASR_SOURCE_ID},
        )
        return {"ok": False, "error": wrapped, "segment_count": 0, "video_id": vid}


def _transcribe_span(
    waveform: np.ndarray,
    start_sec: float,
    end_sec: float,
    *,
    settings: Mapping[str, Any],
    language: str,
    tmp_dir: str,
    clip_index: int,
    stop_callback: Callable[[], bool],
    depth: int = 0,
) -> list[dict[str, Any]]:
    if stop_callback():
        raise UnderstandingStoppedError("ASR stopped by user")
    clip, offset = _slice_waveform(waveform, start_sec, end_sec)
    if clip.size < int(MIN_CLIP_SEC * DEFAULT_SAMPLE_RATE):
        return []
    wav_path = os.path.join(tmp_dir, f"clip_{clip_index:04d}_{depth}.wav")
    write_wav_mono_f32(wav_path, clip, sample_rate=DEFAULT_SAMPLE_RATE)
    if uses_dashscope_chat_asr(settings) or uses_dashscope_native_audio_asr(settings):
        with open(wav_path, "rb") as handle:
            payload_bytes = handle.read()
        filename = os.path.basename(wav_path) or "clip.wav"
        content_type = "audio/wav"
    else:
        payload_bytes, filename, content_type = encode_asr_upload_bytes(wav_path)
    try:
        payload = transcribe_wav_bytes(
            payload_bytes,
            settings=settings,
            filename=filename,
            content_type=content_type,
            language=language,
        )
        return parse_transcription_payload(
            payload,
            offset_sec=offset,
            duration_sec=float(clip.shape[0]) / float(DEFAULT_SAMPLE_RATE),
            asr_source=ASR_SOURCE_ID,
        )
    except Exception as exc:
        duration = max(0.0, float(end_sec) - float(start_sec))
        if is_empty_asr_result(exc):
            logger.info("ASR window %.1f-%.1fs has no words, skipping", start_sec, end_sec)
            return []
        if is_transient_asr_error(exc) and duration > MIN_SPLIT_SEC and depth < 2:
            logger.warning("ASR window %.1f-%.1fs reset, splitting: %s", start_sec, end_sec, exc)
            mid = (float(start_sec) + float(end_sec)) / 2.0
            left = _transcribe_span(
                waveform,
                start_sec,
                mid,
                settings=settings,
                language=language,
                tmp_dir=tmp_dir,
                clip_index=clip_index,
                stop_callback=stop_callback,
                depth=depth + 1,
            )
            right = _transcribe_span(
                waveform,
                mid,
                end_sec,
                settings=settings,
                language=language,
                tmp_dir=tmp_dir,
                clip_index=clip_index,
                stop_callback=stop_callback,
                depth=depth + 1,
            )
            return left + right
        raise RuntimeError(format_asr_error(exc)) from exc


def _speech_spans(waveform: np.ndarray) -> tuple[list[tuple[float, float]], bool]:
    try:
        from src.core.asr.vad_segment import segment_speech

        segments = segment_speech(waveform)
    except Exception as exc:
        logger.warning("VAD failed, falling back to fixed ASR windows: %s", exc)
        return [], False
    return [(float(item.start_sec), float(item.end_sec)) for item in segments], True


def _slice_waveform(waveform: np.ndarray, start_sec: float, end_sec: float) -> tuple[np.ndarray, float]:
    sr = float(DEFAULT_SAMPLE_RATE)
    padded_start = max(0.0, float(start_sec) - PAD_SEC)
    padded_end = min(float(waveform.shape[0]) / sr, float(end_sec) + PAD_SEC)
    i0 = int(padded_start * sr)
    i1 = min(int(waveform.shape[0]), max(i0 + 1, int(round(padded_end * sr))))
    return np.ascontiguousarray(waveform[i0:i1], dtype=np.float32), i0 / sr


def _split_oversize(start: float, end: float, limit: float) -> list[tuple[float, float]]:
    if end - start <= limit + 1e-6:
        return [(start, end)]
    out: list[tuple[float, float]] = []
    cursor = start
    while cursor < end - 1e-6:
        out.append((cursor, min(end, cursor + limit)))
        cursor += limit
    return out


def _save_empty(video_id: str, library_path: str, video_path: str, *, config, profile_base_dir: str) -> dict[str, Any]:
    save_dialogue_transcript(
        video_id,
        [],
        library_path=library_path,
        video_path=video_path,
        asr_source=ASR_SOURCE_ID,
        config=config,
    )
    _mark_state(
        profile_base_dir,
        video_id,
        DIALOGUE_INDEX_STATE_READY,
        extras={"dialogue_segment_rows": 0, "dialogue_asr_source": ASR_SOURCE_ID, "dialogue_error": ""},
    )
    return {"ok": True, "video_id": video_id, "segment_count": 0, "asr_source": ASR_SOURCE_ID, "skipped": False}


def _mark_state(profile_base_dir: str, video_id: str, state: str, *, extras: Mapping[str, Any]) -> None:
    try:
        set_dialogue_index_state(profile_base_dir, video_id, state, extras=dict(extras))
    except Exception as exc:
        logger.warning("ASR dialogue state update failed for %s: %s", video_id, exc)
