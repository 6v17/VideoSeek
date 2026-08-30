from __future__ import annotations

import wave

import numpy as np


def load_wav_mono(path: str, *, target_sr: int = 16000) -> np.ndarray:
    """Load a PCM WAV file as float32 mono in [-1, 1]."""
    wav_path = str(path or "").strip()
    if not wav_path:
        raise ValueError("wav path is required")

    with wave.open(wav_path, "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        raw = handle.readframes(frame_count)

    if sample_width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if sample_rate != target_sr:
        samples = _resample_linear(samples, sample_rate, target_sr)

    return np.ascontiguousarray(samples, dtype=np.float32)


def load_wav_mono_from_bytes(raw: bytes, *, sample_rate: int, channels: int = 1, sample_width: int = 2, target_sr: int = 16000) -> np.ndarray:
    if sample_width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    if sample_rate != target_sr:
        samples = _resample_linear(samples, sample_rate, target_sr)

    return np.ascontiguousarray(samples, dtype=np.float32)


def _resample_linear(samples: np.ndarray, source_sr: int, target_sr: int) -> np.ndarray:
    if source_sr == target_sr or samples.size == 0:
        return samples
    duration = samples.shape[0] / float(source_sr)
    target_length = max(1, int(round(duration * target_sr)))
    source_positions = np.linspace(0.0, samples.shape[0] - 1, num=target_length, dtype=np.float64)
    return np.interp(source_positions, np.arange(samples.shape[0], dtype=np.float64), samples).astype(np.float32)


def write_wav_mono_f32(path: str, samples: np.ndarray, *, sample_rate: int = 16000) -> str:
    """Write float32 mono [-1, 1] as 16-bit PCM WAV."""
    dest = str(path or "").strip()
    if not dest:
        raise ValueError("wav path is required")
    waveform = np.asarray(samples, dtype=np.float32).reshape(-1)
    clipped = np.clip(waveform, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(dest, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())
    return dest

