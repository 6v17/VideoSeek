from __future__ import annotations

import os
import wave
from pathlib import Path

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


def resolve_sensevoice_model_variant(
    *,
    explicit_dir: str | None = None,
    base_dir: str | None = None,
    prefer_quantize: bool | None = None,
) -> tuple[str, bool] | None:
    """Resolve (model_dir, quantize) from env-style roots.

    Accepts either a direct package dir (contains model.onnx / model_quant.onnx)
    or a parent dir with fp32/ and int8/ children.
    """
    explicit = str(explicit_dir or os.environ.get("VIDEOSEEK_SENSEVOICE_MODEL_DIR", "") or "").strip()
    base = str(base_dir or os.environ.get("VIDEOSEEK_SENSEVOICE_BASE_DIR", "") or "").strip()

    def _match_dir(path: str) -> tuple[str, bool] | None:
        if os.path.isfile(os.path.join(path, "model.onnx")):
            return path, False
        if os.path.isfile(os.path.join(path, "model_quant.onnx")):
            return path, True
        return None

    if explicit:
        direct = _match_dir(explicit)
        if direct:
            return direct
        for quantize in (False, True) if prefer_quantize is None else (prefer_quantize,):
            sub_name = "int8" if quantize else "fp32"
            nested = _match_dir(os.path.join(explicit, sub_name))
            if nested:
                return nested

    search_bases = []
    if base:
        search_bases.append(base)
    if explicit and explicit not in search_bases:
        search_bases.append(explicit)

    for root in search_bases:
        order = [False, True] if prefer_quantize is None else [prefer_quantize]
        for quantize in order:
            sub_name = "int8" if quantize else "fp32"
            nested = _match_dir(os.path.join(root, sub_name))
            if nested:
                return nested
        direct = _match_dir(root)
        if direct:
            return direct
    return None


def resolve_existing_model_dir(path: str | None) -> str | None:
    resolved = resolve_sensevoice_model_variant(explicit_dir=path)
    return resolved[0] if resolved else None
