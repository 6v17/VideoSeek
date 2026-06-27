from __future__ import annotations

import threading
from typing import Callable, Sequence

import numpy as np
import onnxruntime as ort

from src.app.logging_utils import get_logger
from src.core.inference_providers import is_gpu_provider_active, resolve_ort_providers
from src.core.onnx_session import build_session_options

logger = get_logger("understanding.ort")

INFERENCE_LOCK = threading.RLock()


def resolve_provider_list(prefer_gpu: bool, provider_hints: Sequence[str] | None = None) -> list[str]:
    hints = [str(item or "").strip() for item in (provider_hints or []) if str(item or "").strip()]
    if prefer_gpu:
        if hints:
            providers = list(hints)
            if "CPUExecutionProvider" not in providers:
                providers.append("CPUExecutionProvider")
            return providers
        return resolve_ort_providers(prefer_gpu=True)
    return ["CPUExecutionProvider"]


def create_inference_session(
    model_path: str,
    *,
    prefer_gpu: bool = True,
    provider_hints: Sequence[str] | None = None,
) -> ort.InferenceSession:
    requested = resolve_provider_list(prefer_gpu, provider_hints)
    available = set(ort.get_available_providers())
    providers = [provider for provider in requested if provider in available]
    if not providers:
        providers = ["CPUExecutionProvider"]
    return ort.InferenceSession(
        model_path,
        sess_options=build_session_options(prefer_gpu and providers[0] != "CPUExecutionProvider"),
        providers=providers,
    )


def run_with_cpu_fallback(
    *,
    model_path: str,
    prefer_gpu: bool,
    provider_hints: Sequence[str] | None,
    run_fn: Callable[[ort.InferenceSession], np.ndarray | list[np.ndarray] | dict],
):
    session = create_inference_session(model_path, prefer_gpu=prefer_gpu, provider_hints=provider_hints)
    using_gpu = is_gpu_provider_active(list(session.get_providers()))
    try:
        with INFERENCE_LOCK:
            return run_fn(session), using_gpu
    except Exception as exc:
        if not using_gpu:
            raise
        logger.warning("Understanding GPU inference failed, retrying on CPU: %s", exc)
        cpu_session = create_inference_session(model_path, prefer_gpu=False, provider_hints=provider_hints)
        with INFERENCE_LOCK:
            return run_fn(cpu_session), False
