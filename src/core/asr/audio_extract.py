"""Extract 16 kHz mono PCM from video/audio via FFmpeg."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from typing import Any

import numpy as np

from src.infra.ffmpeg_paths import get_ffmpeg_path, has_ffmpeg
from src.infra.paths import ensure_folder_exists

DEFAULT_SAMPLE_RATE = 16000
ProgressCallback = Callable[[float, str], None]


def _hidden_startupinfo() -> Any:
    if sys.platform != "win32" or not hasattr(subprocess, "STARTUPINFO"):
        return None
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return startupinfo


def _run_ffmpeg(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        cmd,
        capture_output=True,
        startupinfo=_hidden_startupinfo(),
    )


def extract_audio_mono_f32(
    media_path: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    progress_callback: ProgressCallback | None = None,
) -> np.ndarray:
    """Decode media audio to float32 mono via FFmpeg stdout pipe (no temp WAV)."""
    source = os.path.normpath(os.path.abspath(str(media_path or "").strip()))
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"Media file not found: {media_path!r}")
    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available")

    sr = int(sample_rate)
    if sr <= 0:
        raise ValueError("sample_rate must be positive")

    if progress_callback:
        progress_callback(0.0, "extract_audio")

    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "s16le",
        "pipe:1",
    ]
    result = _run_ffmpeg(cmd)
    if result.returncode != 0:
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg audio extract failed: {detail or result.returncode}")
    raw = result.stdout or b""
    if len(raw) < 2:
        raise RuntimeError("FFmpeg audio extract returned empty PCM")

    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) * np.float32(1.0 / 32768.0)
    if progress_callback:
        progress_callback(1.0, "extract_audio")
    return np.ascontiguousarray(samples, dtype=np.float32)


def extract_audio_wav(
    media_path: str,
    output_path: str | None = None,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Extract mono PCM WAV at ``sample_rate`` (default 16 kHz).

    Returns the absolute path of the written WAV file.
    When ``output_path`` is omitted, a NamedTemporaryFile is created (caller deletes it).
    """
    source = os.path.normpath(os.path.abspath(str(media_path or "").strip()))
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"Media file not found: {media_path!r}")
    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available")

    sr = int(sample_rate)
    if sr <= 0:
        raise ValueError("sample_rate must be positive")

    if output_path:
        dest = os.path.normpath(os.path.abspath(str(output_path)))
        ensure_folder_exists(dest)
    else:
        handle = tempfile.NamedTemporaryFile(prefix="videoseek_asr_", suffix=".wav", delete=False)
        dest = handle.name
        handle.close()

    if progress_callback:
        progress_callback(0.0, "extract_audio")

    ffmpeg = get_ffmpeg_path()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        source,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-c:a",
        "pcm_s16le",
        dest,
    ]
    result = _run_ffmpeg(cmd)
    if result.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) <= 0:
        if os.path.isfile(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
        detail = (result.stderr or b"").decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"FFmpeg audio extract failed: {detail or result.returncode}")

    if progress_callback:
        progress_callback(1.0, "extract_audio")
    return dest


def encode_asr_upload_bytes(
    wav_path: str,
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
) -> tuple[bytes, str, str]:
    """Prefer a compact MP3 upload; fall back to the WAV file."""
    source = str(wav_path or "").strip()
    if not source or not os.path.isfile(source):
        raise FileNotFoundError(f"wav path is required: {wav_path!r}")
    wav_bytes = _read_bytes(source)
    wav_name = os.path.basename(source) or "clip.wav"
    if not has_ffmpeg():
        return wav_bytes, wav_name, "audio/wav"
    mp3_path = os.path.splitext(source)[0] + ".mp3"
    ffmpeg = get_ffmpeg_path()
    result = _run_ffmpeg(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            source,
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(int(sample_rate)),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            mp3_path,
        ]
    )
    if result.returncode == 0 and os.path.isfile(mp3_path) and os.path.getsize(mp3_path) > 0:
        try:
            payload = _read_bytes(mp3_path)
        finally:
            try:
                os.remove(mp3_path)
            except OSError:
                pass
        if payload:
            return payload, os.path.basename(mp3_path) or "clip.mp3", "audio/mpeg"
    if os.path.isfile(mp3_path):
        try:
            os.remove(mp3_path)
        except OSError:
            pass
    return wav_bytes, wav_name, "audio/wav"


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()
