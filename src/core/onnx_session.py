import os
from typing import Sequence

import onnxruntime as ort

_INFERENCE_EP_VALUES = frozenset({"auto", "cuda", "dml", "cpu"})
_GPU_PROVIDER_MARKERS = (
    "CUDAExecutionProvider",
    "DmlExecutionProvider",
    "TensorrtExecutionProvider",
)


def build_session_options(prefer_gpu, disable_optimizations=False):
    """ONNX Runtime session tuning.

    DirectML keeps sequential execution and mem_pattern off for stability. Graph optimizations are
    enabled by default unless ``disable_optimizations`` is set.

    When ``prefer_gpu`` is true, ``intra_op_num_threads`` is capped so ORT's CPU-side work does not
    starve FFmpeg frame decoding. Override with env ``VIDEOSEEK_ORT_INTRA_OP_THREADS`` (integer 1–32).
    """
    session_options = ort.SessionOptions()
    if not disable_optimizations:
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    if prefer_gpu:
        session_options.enable_mem_pattern = False
        session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        session_options.inter_op_num_threads = 1
        raw_threads = os.environ.get("VIDEOSEEK_ORT_INTRA_OP_THREADS", "").strip()
        if raw_threads:
            try:
                intra = int(raw_threads)
                intra = max(1, min(32, intra))
            except ValueError:
                cores = os.cpu_count() or 4
                intra = max(1, min(4, cores // 4))
        else:
            cores = os.cpu_count() or 4
            intra = max(1, min(4, cores // 4))
        session_options.intra_op_num_threads = intra
    if disable_optimizations:
        session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    return session_options


def resolve_embedding_batch_size(config=None):
    runtime_config = dict(config or {})
    try:
        batch_size = int(runtime_config.get("embedding_batch_size", 16))
    except (TypeError, ValueError):
        return 16
    return max(1, batch_size)


def normalize_inference_ep(value) -> str:
    text = str(value or "").strip().lower()
    if text in {"directml", "dx"}:
        return "dml"
    if text in _INFERENCE_EP_VALUES:
        return text
    return "auto"


def resolve_inference_ep(config=None) -> str:
    """Return ``auto|cuda|dml|cpu``. Env ``VIDEOSEEK_INFERENCE_EP`` overrides config."""
    raw_env = os.environ.get("VIDEOSEEK_INFERENCE_EP", "").strip()
    if raw_env:
        return normalize_inference_ep(raw_env)
    try:
        from src.app.config import DEFAULT_CONFIG

        default = DEFAULT_CONFIG.get("inference_ep", "auto")
    except Exception:
        default = "auto"
    return normalize_inference_ep((config or {}).get("inference_ep", default))


def get_available_onnx_provider_names() -> list[str]:
    try:
        providers = ort.get_available_providers()
    except Exception:
        return []
    return [str(provider) for provider in providers]


def is_cuda_execution_provider_available() -> bool:
    return "CUDAExecutionProvider" in get_available_onnx_provider_names()


def is_dml_execution_provider_available() -> bool:
    return "DmlExecutionProvider" in get_available_onnx_provider_names()


def resolve_onnx_providers(*, prefer_gpu: bool = True, config=None) -> list[str]:
    """Build ORT provider list for CLIP/SigLIP vision (and CLIP text) sessions.

    ``prefer_gpu=False`` or ``inference_ep=cpu`` → CPU only.
    ``auto``: CUDA before DML when present in this ORT build; else DML; else CPU.
    Missing EPs are filtered out so stock ``onnxruntime-directml`` keeps today's path.
    """
    if not prefer_gpu:
        return ["CPUExecutionProvider"]
    ep = resolve_inference_ep(config)
    if ep == "cpu":
        return ["CPUExecutionProvider"]
    available = set(get_available_onnx_provider_names())
    if ep == "cuda":
        ordered = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    elif ep == "dml":
        ordered = ["DmlExecutionProvider", "CPUExecutionProvider"]
    else:
        ordered = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    filtered = [name for name in ordered if name in available or name == "CPUExecutionProvider"]
    if "CPUExecutionProvider" not in filtered:
        filtered.append("CPUExecutionProvider")
    # Forced cuda without CUDA EP → DML if present, else CPU.
    if ep == "cuda" and "CUDAExecutionProvider" not in filtered:
        if "DmlExecutionProvider" in available:
            return ["DmlExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]
    if ep == "dml" and "DmlExecutionProvider" not in filtered:
        return ["CPUExecutionProvider"]
    return filtered


def providers_indicate_gpu(provider_lists: Sequence[Sequence[str]] | None) -> bool:
    """True when every listed session has at least one GPU EP active."""
    lists = list(provider_lists or [])
    if not lists:
        return False
    for providers in lists:
        names = [str(item) for item in (providers or [])]
        if not any(marker in names for marker in _GPU_PROVIDER_MARKERS):
            return False
    return True


def gpu_backend_label(provider_lists: Sequence[Sequence[str]] | None) -> str:
    if not providers_indicate_gpu(provider_lists):
        return "CPU"
    flat = []
    for providers in provider_lists or []:
        flat.extend(str(item) for item in (providers or []))
    if "CUDAExecutionProvider" in flat:
        return "CUDA"
    if "DmlExecutionProvider" in flat:
        return "DirectML"
    if "TensorrtExecutionProvider" in flat:
        return "TensorRT"
    return "GPU"
