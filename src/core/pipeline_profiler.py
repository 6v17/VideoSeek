"""CUDA/VIP pipeline stage timing (off by default for stable DirectML builds)."""
from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Any

_LOCK = threading.Lock()
_ACTIVE = False
_DECODE_SEC = 0.0
_PREPROCESS_SEC = 0.0
_ORT_SEC = 0.0
_FRAMES_DECODED = 0
_FRAMES_ENCODED = 0

_PROFILE_ENV = "VIDEOSEEK_PIPELINE_PROFILE"


def is_pipeline_profiling_enabled() -> bool:
    override = os.environ.get(_PROFILE_ENV, "").strip().lower()
    if override in {"0", "false", "no", "off"}:
        return False
    if override in {"1", "true", "yes", "on"}:
        return True
    try:
        from src.core.inference_providers import is_cuda_inference_mode

        return is_cuda_inference_mode()
    except Exception:
        return False


def _reset_counters() -> None:
    global _DECODE_SEC, _PREPROCESS_SEC, _ORT_SEC, _FRAMES_DECODED, _FRAMES_ENCODED
    _DECODE_SEC = 0.0
    _PREPROCESS_SEC = 0.0
    _ORT_SEC = 0.0
    _FRAMES_DECODED = 0
    _FRAMES_ENCODED = 0


@contextmanager
def pipeline_profile_run():
    """Reset and collect stage timings for one indexing run."""
    global _ACTIVE
    if not is_pipeline_profiling_enabled():
        yield
        return

    with _LOCK:
        _reset_counters()
        _ACTIVE = True
    try:
        yield
    finally:
        with _LOCK:
            _ACTIVE = False


def record_decode(seconds: float, *, frames: int = 1) -> None:
    global _DECODE_SEC, _FRAMES_DECODED
    if not _ACTIVE:
        return
    delta = max(0.0, float(seconds))
    count = max(0, int(frames))
    with _LOCK:
        _DECODE_SEC += delta
        _FRAMES_DECODED += count


def record_preprocess(seconds: float, *, frames: int = 1) -> None:
    global _PREPROCESS_SEC, _FRAMES_ENCODED
    if not _ACTIVE:
        return
    delta = max(0.0, float(seconds))
    count = max(0, int(frames))
    with _LOCK:
        _PREPROCESS_SEC += delta
        _FRAMES_ENCODED += count


def record_ort(seconds: float) -> None:
    global _ORT_SEC
    if not _ACTIVE:
        return
    with _LOCK:
        _ORT_SEC += max(0.0, float(seconds))


def snapshot() -> dict[str, Any] | None:
    if not is_pipeline_profiling_enabled():
        return None
    with _LOCK:
        return {
            "t_decode": _DECODE_SEC,
            "t_preprocess": _PREPROCESS_SEC,
            "t_ort": _ORT_SEC,
            "frames_decoded": _FRAMES_DECODED,
            "frames_encoded": _FRAMES_ENCODED,
        }


def _format_seconds(value: float) -> str:
    return f"{float(value):.3f}s"


def log_pipeline_summary(
    logger,
    *,
    log_tag: str,
    wall_pipe_sec: float,
    decode_backend: str | None = None,
) -> None:
    stats = snapshot()
    if not stats:
        return

    t_decode = float(stats["t_decode"])
    t_preprocess = float(stats["t_preprocess"])
    t_ort = float(stats["t_ort"])
    t_compute = t_preprocess + t_ort
    wall_pipe = max(0.0, float(wall_pipe_sec))
    overlap_sec = max(0.0, t_decode + t_compute - wall_pipe)
    idle_sec = max(0.0, wall_pipe - max(t_decode, t_compute))

    frames_decoded = int(stats["frames_decoded"])
    frames_encoded = int(stats["frames_encoded"])
    backend = str(decode_backend or "").strip() or "-"

    logger.info(
        "Pipeline profile %s: wall_pipe=%s decode=%s preprocess=%s ort=%s "
        "compute=%s overlap_est=%s idle_est=%s frames=%d/%d backend=%s",
        log_tag,
        _format_seconds(wall_pipe),
        _format_seconds(t_decode),
        _format_seconds(t_preprocess),
        _format_seconds(t_ort),
        _format_seconds(t_compute),
        _format_seconds(overlap_sec),
        _format_seconds(idle_sec),
        frames_decoded,
        frames_encoded,
        backend,
    )


def reset_for_tests() -> None:
    """Test helper: clear counters and deactivate profiling scope."""
    global _ACTIVE
    with _LOCK:
        _ACTIVE = False
        _reset_counters()
