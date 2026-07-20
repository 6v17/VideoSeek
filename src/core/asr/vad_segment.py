"""Silero VAD (ONNX) speech segmentation — no PyTorch dependency."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import onnxruntime as ort

from src.core.asr.audio_io import load_wav_mono
from src.core.onnx_session import build_session_options

DEFAULT_SAMPLE_RATE = 16000
WINDOW_SAMPLES = 512
CONTEXT_SAMPLES = 64
STATE_SHAPE = (2, 1, 128)
# Skip ORT when window energy is clearly silence (still advances context).
DEFAULT_SILENCE_RMS = 5e-4
DEFAULT_PROGRESS_EVERY = 64

ProgressCallback = Callable[[float, str], None]

_ENGINE_LOCK = threading.RLock()
_ENGINE_CACHE: dict[str, "SileroVadOnnxEngine"] = {}


@dataclass(frozen=True)
class SpeechSegment:
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return max(0.0, float(self.end_sec) - float(self.start_sec))

    def as_dict(self) -> dict[str, float]:
        return {"start_sec": float(self.start_sec), "end_sec": float(self.end_sec)}


BUNDLED_SILERO_VAD_RELPATH = os.path.join("resources", "asr", "silero_vad.onnx")


def resolve_silero_vad_model_path(
    *,
    explicit_path: str | None = None,
    model_dir: str | None = None,
) -> str | None:
    """Resolve bundled ``silero_vad.onnx`` (shipped under resources/asr/).

    ``model_dir`` is accepted for API compatibility but ignored — VAD is not a
    user-imported model. Optional override: ``explicit_path`` / ``VIDEOSEEK_SILERO_VAD_PATH``.
    """
    del model_dir  # bundled asset; not installed under model_dir
    candidates: list[str] = []

    explicit = str(explicit_path or os.environ.get("VIDEOSEEK_SILERO_VAD_PATH", "") or "").strip()
    if explicit:
        candidates.append(explicit)

    try:
        from src.infra.paths import get_resource_path

        candidates.append(get_resource_path(BUNDLED_SILERO_VAD_RELPATH))
    except Exception:
        pass

    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normpath(os.path.abspath(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(normalized) and os.path.getsize(normalized) > 0:
            return normalized
    return None


class SileroVadOnnxEngine:
    def __init__(self, model_path: str, *, intra_op_num_threads: int = 2) -> None:
        path = os.path.normpath(os.path.abspath(str(model_path)))
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Silero VAD model not found: {path}")
        self.model_path = path
        options = build_session_options(prefer_gpu=False)
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = max(1, int(intra_op_num_threads))
        # Per-engine lock: avoid locking every window with a process-global RLock.
        self._run_lock = threading.RLock()
        self._session = ort.InferenceSession(
            path,
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._sr = np.array(DEFAULT_SAMPLE_RATE, dtype=np.int64)
        self._x = np.empty((1, CONTEXT_SAMPLES + WINDOW_SAMPLES), dtype=np.float32)
        self._reset_stream_state()

    def _reset_stream_state(self) -> None:
        self._state = np.zeros(STATE_SHAPE, dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)

    def reset_states(self) -> None:
        self._reset_stream_state()

    def __call__(self, chunk: np.ndarray, sample_rate: int = DEFAULT_SAMPLE_RATE) -> float:
        if int(sample_rate) != DEFAULT_SAMPLE_RATE:
            raise ValueError(f"Silero VAD ONNX expects {DEFAULT_SAMPLE_RATE} Hz, got {sample_rate}")
        window = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if window.shape[0] != WINDOW_SAMPLES:
            raise ValueError(f"chunk must have {WINDOW_SAMPLES} samples, got {window.shape[0]}")
        probs = self.infer_probs(window, silence_rms=0.0)
        return float(probs[0]) if probs else 0.0

    def infer_probs(
        self,
        waveform: np.ndarray,
        *,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        silence_rms: float = DEFAULT_SILENCE_RMS,
        progress_callback: ProgressCallback | None = None,
        progress_every: int = DEFAULT_PROGRESS_EVERY,
    ) -> list[float]:
        """Run Silero over a mono waveform; return one probability per 512-sample window.

        Clear-silence windows skip ORT (probability 0) and only advance audio context,
        which is the main speedup on sparse-dialogue media.
        """
        if int(sample_rate) != DEFAULT_SAMPLE_RATE:
            raise ValueError(f"Silero VAD ONNX expects {DEFAULT_SAMPLE_RATE} Hz, got {sample_rate}")

        audio = np.ascontiguousarray(np.asarray(waveform, dtype=np.float32).reshape(-1))
        if audio.size == 0:
            return []

        remainder = int(audio.shape[0] % WINDOW_SAMPLES)
        if remainder:
            audio = np.pad(audio, (0, WINDOW_SAMPLES - remainder))

        num_windows = int(audio.shape[0] // WINDOW_SAMPLES)
        probs = [0.0] * num_windows
        silence_power = float(max(0.0, silence_rms)) ** 2
        report_every = max(1, int(progress_every))

        with self._run_lock:
            self.reset_states()
            state = self._state
            context = self._context
            session = self._session
            x = self._x
            sr = self._sr
            silent_streak = 0

            for index in range(num_windows):
                start = index * WINDOW_SAMPLES
                window = audio[start : start + WINDOW_SAMPLES]
                if silence_power > 0.0:
                    power = float(np.dot(window, window) / float(WINDOW_SAMPLES))
                    if power < silence_power:
                        probs[index] = 0.0
                        context = window[-CONTEXT_SAMPLES:].reshape(1, -1)
                        silent_streak += 1
                        # Soft-reset recurrent state after sustained silence.
                        if silent_streak >= 16 and silent_streak % 16 == 0:
                            state = np.zeros(STATE_SHAPE, dtype=np.float32)
                        if progress_callback and (index % report_every == 0 or index + 1 == num_windows):
                            progress_callback((index + 1) / float(num_windows), "vad_infer")
                        continue

                silent_streak = 0
                x[:, :CONTEXT_SAMPLES] = context
                x[:, CONTEXT_SAMPLES:] = window.reshape(1, -1)
                outputs = session.run(
                    None,
                    {
                        "input": x,
                        "state": state,
                        "sr": sr,
                    },
                )
                probs[index] = float(np.asarray(outputs[0]).reshape(-1)[0])
                state = np.asarray(outputs[1], dtype=np.float32)
                context = x[:, -CONTEXT_SAMPLES:].copy()

                if progress_callback and (index % report_every == 0 or index + 1 == num_windows):
                    progress_callback((index + 1) / float(num_windows), "vad_infer")

            self._state = state
            self._context = context
        return probs


def get_silero_vad_engine(
    model_path: str | None = None,
    *,
    model_dir: str | None = None,
) -> SileroVadOnnxEngine:
    resolved = str(model_path or "").strip() or resolve_silero_vad_model_path(model_dir=model_dir)
    if not resolved:
        raise FileNotFoundError(
            "Bundled silero_vad.onnx not found under resources/asr/. "
            "Set VIDEOSEEK_SILERO_VAD_PATH only for local overrides."
        )
    cache_key = os.path.normpath(os.path.abspath(resolved))
    with _ENGINE_LOCK:
        cached = _ENGINE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        engine = SileroVadOnnxEngine(cache_key)
        _ENGINE_CACHE[cache_key] = engine
        return engine


def clear_silero_vad_engine_cache() -> None:
    with _ENGINE_LOCK:
        _ENGINE_CACHE.clear()


def _collect_speech_probs(
    waveform: np.ndarray,
    model: SileroVadOnnxEngine,
    *,
    sample_rate: int,
    progress_callback: ProgressCallback | None = None,
    silence_rms: float = DEFAULT_SILENCE_RMS,
) -> list[float]:
    return model.infer_probs(
        waveform,
        sample_rate=sample_rate,
        silence_rms=silence_rms,
        progress_callback=progress_callback,
    )


def _timestamps_from_probs(
    speech_probs: Sequence[float],
    *,
    audio_length_samples: int,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    threshold: float = 0.5,
    neg_threshold: float | None = None,
    min_speech_duration_ms: int = 250,
    max_speech_duration_s: float = 30.0,
    min_silence_duration_ms: int = 100,
    speech_pad_ms: int = 30,
    min_silence_at_max_speech_ms: int = 98,
) -> list[dict[str, int]]:
    """Port of silero-vad ``get_speech_timestamps`` (sample indices)."""
    if audio_length_samples <= 0 or not speech_probs:
        return []

    window_size_samples = WINDOW_SAMPLES
    min_speech_samples = sample_rate * min_speech_duration_ms / 1000.0
    speech_pad_samples = sample_rate * speech_pad_ms / 1000.0
    max_speech_samples = sample_rate * float(max_speech_duration_s) - window_size_samples - 2 * speech_pad_samples
    min_silence_samples = sample_rate * min_silence_duration_ms / 1000.0
    min_silence_samples_at_max_speech = sample_rate * min_silence_at_max_speech_ms / 1000.0
    if neg_threshold is None:
        neg_threshold = max(float(threshold) - 0.15, 0.01)

    triggered = False
    speeches: list[dict[str, int]] = []
    current_speech: dict[str, int] = {}
    temp_end = 0
    prev_end = 0
    next_start = 0
    possible_ends: list[tuple[int, float]] = []

    for index, speech_prob in enumerate(speech_probs):
        cur_sample = window_size_samples * index

        if speech_prob >= threshold and temp_end:
            sil_dur = cur_sample - temp_end
            if sil_dur > min_silence_samples_at_max_speech:
                possible_ends.append((temp_end, sil_dur))
            temp_end = 0
            if next_start < prev_end:
                next_start = cur_sample

        if speech_prob >= threshold and not triggered:
            triggered = True
            current_speech["start"] = cur_sample
            continue

        if triggered and (cur_sample - current_speech["start"] > max_speech_samples):
            if possible_ends:
                prev_end, dur = max(possible_ends, key=lambda item: item[1])
                current_speech["end"] = int(prev_end)
                speeches.append(current_speech)
                current_speech = {}
                next_start = int(prev_end + dur)
                if next_start < prev_end + cur_sample:
                    current_speech["start"] = next_start
                else:
                    triggered = False
                    prev_end = next_start = temp_end = 0
                    possible_ends = []
            else:
                current_speech["end"] = cur_sample
                speeches.append(current_speech)
                current_speech = {}
                prev_end = next_start = temp_end = 0
                triggered = False
                possible_ends = []
            continue

        if speech_prob < neg_threshold and triggered:
            if not temp_end:
                temp_end = cur_sample
            sil_dur_now = cur_sample - temp_end
            if sil_dur_now < min_silence_samples:
                continue
            current_speech["end"] = int(temp_end)
            if (current_speech["end"] - current_speech["start"]) > min_speech_samples:
                speeches.append(current_speech)
            current_speech = {}
            prev_end = next_start = temp_end = 0
            triggered = False
            possible_ends = []
            continue

    if current_speech and (audio_length_samples - current_speech["start"]) > min_speech_samples:
        current_speech["end"] = audio_length_samples
        speeches.append(current_speech)

    for index, speech in enumerate(speeches):
        if index == 0:
            speech["start"] = int(max(0, speech["start"] - speech_pad_samples))
        if index != len(speeches) - 1:
            silence_duration = speeches[index + 1]["start"] - speech["end"]
            if silence_duration < 2 * speech_pad_samples:
                speech["end"] += int(silence_duration // 2)
                speeches[index + 1]["start"] = int(max(0, speeches[index + 1]["start"] - silence_duration // 2))
            else:
                speech["end"] = int(min(audio_length_samples, speech["end"] + speech_pad_samples))
                speeches[index + 1]["start"] = int(max(0, speeches[index + 1]["start"] - speech_pad_samples))
        else:
            speech["end"] = int(min(audio_length_samples, speech["end"] + speech_pad_samples))

    return speeches


def _split_oversized_segments(
    segments: Sequence[SpeechSegment],
    *,
    max_segment_duration_s: float,
) -> list[SpeechSegment]:
    limit = float(max_segment_duration_s)
    if limit <= 0:
        return list(segments)
    result: list[SpeechSegment] = []
    for segment in segments:
        start = float(segment.start_sec)
        end = float(segment.end_sec)
        if end - start <= limit + 1e-6:
            result.append(SpeechSegment(start_sec=start, end_sec=end))
            continue
        cursor = start
        while cursor < end - 1e-6:
            piece_end = min(end, cursor + limit)
            if piece_end - cursor >= 0.05:
                result.append(SpeechSegment(start_sec=cursor, end_sec=piece_end))
            cursor = piece_end
    return result


def segment_speech(
    audio: str | np.ndarray,
    *,
    model: SileroVadOnnxEngine | None = None,
    model_path: str | None = None,
    model_dir: str | None = None,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    threshold: float = 0.5,
    min_speech_duration_ms: int = 250,
    max_speech_duration_s: float = 30.0,
    min_silence_duration_ms: int = 100,
    speech_pad_ms: int = 30,
    silence_rms: float = DEFAULT_SILENCE_RMS,
    progress_callback: ProgressCallback | None = None,
) -> list[SpeechSegment]:
    """Return speech segments in seconds for a WAV path or mono float32 waveform."""
    if isinstance(audio, str):
        waveform = load_wav_mono(audio, target_sr=sample_rate)
    else:
        waveform = np.asarray(audio, dtype=np.float32).reshape(-1)

    engine = model or get_silero_vad_engine(model_path, model_dir=model_dir)
    if progress_callback:
        progress_callback(0.0, "vad_start")

    probs = _collect_speech_probs(
        waveform,
        engine,
        sample_rate=sample_rate,
        progress_callback=progress_callback,
        silence_rms=silence_rms,
    )
    sample_segments = _timestamps_from_probs(
        probs,
        audio_length_samples=int(waveform.shape[0]),
        sample_rate=sample_rate,
        threshold=threshold,
        min_speech_duration_ms=min_speech_duration_ms,
        max_speech_duration_s=max_speech_duration_s,
        min_silence_duration_ms=min_silence_duration_ms,
        speech_pad_ms=speech_pad_ms,
    )
    segments = [
        SpeechSegment(
            start_sec=item["start"] / float(sample_rate),
            end_sec=item["end"] / float(sample_rate),
        )
        for item in sample_segments
    ]
    segments = _split_oversized_segments(segments, max_segment_duration_s=max_speech_duration_s)
    if progress_callback:
        progress_callback(1.0, "vad_done")
    return segments


def segment_media_speech(
    media_path: str,
    *,
    wav_output_path: str | None = None,
    keep_wav: bool = False,
    model_path: str | None = None,
    model_dir: str | None = None,
    progress_callback: ProgressCallback | None = None,
    **vad_kwargs: Any,
) -> list[SpeechSegment]:
    """Extract audio from media then run VAD.

    Default path pipes PCM from FFmpeg (no temp WAV). Pass ``wav_output_path`` /
    ``keep_wav`` only when a WAV file is explicitly required.
    """
    from src.core.asr.audio_extract import extract_audio_mono_f32, extract_audio_wav

    if wav_output_path or keep_wav:
        wav_path = extract_audio_wav(
            media_path,
            wav_output_path,
            progress_callback=progress_callback,
        )
        try:
            return segment_speech(
                wav_path,
                model_path=model_path,
                model_dir=model_dir,
                progress_callback=progress_callback,
                **vad_kwargs,
            )
        finally:
            if not keep_wav and not wav_output_path and os.path.isfile(wav_path):
                try:
                    os.remove(wav_path)
                except OSError:
                    pass

    waveform = extract_audio_mono_f32(media_path, progress_callback=progress_callback)
    return segment_speech(
        waveform,
        model_path=model_path,
        model_dir=model_dir,
        progress_callback=progress_callback,
        **vad_kwargs,
    )
