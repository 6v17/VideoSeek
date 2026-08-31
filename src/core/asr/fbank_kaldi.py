"""Kaldi-style 80-dim log-mel fbank (numpy). Used by CAM++ ONNX.

Matches ``torchaudio.compliance.kaldi.fbank`` defaults used by FunASR / 3D-Speaker:
16 kHz, 25 ms window, 10 ms hop, povey window, 80 bins, utterance CMN.
No PyTorch.
"""

from __future__ import annotations

import math

import numpy as np

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_NUM_MEL_BINS = 80
DEFAULT_FRAME_LENGTH_MS = 25.0
DEFAULT_FRAME_SHIFT_MS = 10.0
DEFAULT_LOW_FREQ = 20.0
DEFAULT_PREEMPHASIS = 0.97
_MEL_CACHE: dict[tuple[int, int, int, float, float], np.ndarray] = {}


def _next_power_of_two(value: int) -> int:
    n = max(1, int(value))
    return 1 << (n - 1).bit_length()


def _hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return 1127.0 * np.log(1.0 + np.asarray(hz) / 700.0)


def _mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (np.exp(np.asarray(mel) / 1127.0) - 1.0)


def _povey_window(size: int) -> np.ndarray:
    if size <= 1:
        return np.ones(max(1, size), dtype=np.float64)
    n = np.arange(size, dtype=np.float64)
    hann = 0.5 - 0.5 * np.cos(2.0 * math.pi * n / (size - 1))
    return np.power(np.maximum(hann, 0.0), 0.85)


def _mel_filterbank(
    *,
    num_bins: int,
    padded_window: int,
    sample_rate: int,
    low_freq: float,
    high_freq: float,
) -> np.ndarray:
    key = (int(num_bins), int(padded_window), int(sample_rate), float(low_freq), float(high_freq))
    cached = _MEL_CACHE.get(key)
    if cached is not None:
        return cached
    nyquist = 0.5 * float(sample_rate)
    high = float(high_freq)
    if high <= 0.0:
        high += nyquist
    num_fft_bins = padded_window // 2
    fft_bin_width = float(sample_rate) / float(padded_window)
    mel_low = float(_hz_to_mel(low_freq))
    mel_high = float(_hz_to_mel(high))
    mel_points = np.linspace(mel_low, mel_high, int(num_bins) + 2)
    bin_hz = np.asarray(_mel_to_hz(mel_points), dtype=np.float64)
    bins = np.floor(bin_hz / fft_bin_width).astype(np.int32)
    banks = np.zeros((int(num_bins), num_fft_bins), dtype=np.float64)
    for index in range(int(num_bins)):
        left = int(bins[index])
        center = int(bins[index + 1])
        right = int(bins[index + 2])
        for fft_bin in range(left, center):
            if 0 <= fft_bin < num_fft_bins and center != left:
                banks[index, fft_bin] = (fft_bin - left) / float(center - left)
        for fft_bin in range(center, right):
            if 0 <= fft_bin < num_fft_bins and right != center:
                banks[index, fft_bin] = (right - fft_bin) / float(right - center)
    _MEL_CACHE[key] = banks
    return banks


def compute_fbank(
    waveform: np.ndarray,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    num_mel_bins: int = DEFAULT_NUM_MEL_BINS,
    frame_length_ms: float = DEFAULT_FRAME_LENGTH_MS,
    frame_shift_ms: float = DEFAULT_FRAME_SHIFT_MS,
    dither: float = 0.0,
    apply_cmn: bool = True,
) -> np.ndarray:
    """Return float32 log-mel features of shape ``(frames, num_mel_bins)``."""
    samples = np.asarray(waveform, dtype=np.float64).reshape(-1)
    if samples.size == 0:
        return np.zeros((0, int(num_mel_bins)), dtype=np.float32)
    sr = int(sample_rate)
    window_size = int(round(sr * float(frame_length_ms) * 0.001))
    window_shift = int(round(sr * float(frame_shift_ms) * 0.001))
    if window_size <= 1 or window_shift <= 0:
        raise ValueError("invalid fbank window")
    if samples.size < window_size:
        samples = np.pad(samples, (0, window_size - samples.size))

    pcm = samples * 32768.0
    if dither > 0.0:
        pcm = pcm + float(dither) * np.random.standard_normal(pcm.shape)
    pcm = pcm - pcm.mean()
    emphasized = np.empty_like(pcm)
    emphasized[0] = pcm[0]
    emphasized[1:] = pcm[1:] - float(DEFAULT_PREEMPHASIS) * pcm[:-1]

    num_frames = 1 + (emphasized.size - window_size) // window_shift
    if num_frames <= 0:
        return np.zeros((0, int(num_mel_bins)), dtype=np.float32)

    padded_window = _next_power_of_two(window_size)
    window = _povey_window(window_size)
    banks = _mel_filterbank(
        num_bins=int(num_mel_bins),
        padded_window=padded_window,
        sample_rate=sr,
        low_freq=DEFAULT_LOW_FREQ,
        high_freq=0.0,
    )
    frames = np.lib.stride_tricks.as_strided(
        emphasized,
        shape=(num_frames, window_size),
        strides=(emphasized.strides[0] * window_shift, emphasized.strides[0]),
    ).copy()
    frames *= window
    if padded_window > window_size:
        padded = np.zeros((num_frames, padded_window), dtype=np.float64)
        padded[:, :window_size] = frames
        frames = padded
    spectrum = np.fft.rfft(frames, n=padded_window, axis=1)
    power = np.square(spectrum.real) + np.square(spectrum.imag)
    power = power[:, : banks.shape[1]]
    mel = np.maximum(power @ banks.T, 1.0e-10)
    feat = np.log(mel).astype(np.float32)
    if apply_cmn and feat.shape[0] > 0:
        feat = feat - feat.mean(axis=0, keepdims=True)
    return feat
