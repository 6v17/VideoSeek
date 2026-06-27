"""ORT execution provider selection (CUDA-first on experiment branch; DML via explicit opt-in)."""
from __future__ import annotations

import os
import site

from src.app.logging_utils import get_logger

logger = get_logger("inference_providers")

_INFERENCE_EP_ENV = "VIDEOSEEK_INFERENCE_EP"
_DEFAULT_INFERENCE_EP = "cuda"
_NVIDIA_DLL_SUBDIRS = (
    "cublas",
    "cudnn",
    "cuda_runtime",
    "cufft",
    "curand",
    "nvjitlink",
    "cuda_nvrtc",
)
_CUDA_DLL_PATHS_PREPARED = False
_AVAILABLE_ORT_PROVIDERS: list[str] | None = None
_CUDA_DEFAULTS_LOGGED = False


def get_inference_ep_mode() -> str:
    return os.environ.get(_INFERENCE_EP_ENV, _DEFAULT_INFERENCE_EP).strip().lower()


def _get_available_ort_providers() -> list[str]:
    global _AVAILABLE_ORT_PROVIDERS
    if _AVAILABLE_ORT_PROVIDERS is None:
        import onnxruntime as ort

        _AVAILABLE_ORT_PROVIDERS = list(ort.get_available_providers())
    return list(_AVAILABLE_ORT_PROVIDERS)


def is_cuda_inference_mode() -> bool:
    mode = get_inference_ep_mode()
    if mode in {"dml", "directml", "cpu"}:
        return False
    available = _get_available_ort_providers()
    if "CUDAExecutionProvider" not in available:
        if mode == "cuda":
            logger.warning(
                "CUDA inference mode is configured but CUDAExecutionProvider is unavailable; "
                "GPU decode/indexing will fall back to DirectML or CPU where possible."
            )
        return False
    return True


def apply_cuda_experiment_defaults() -> None:
    """Prepare CUDA-first runtime defaults before ORT sessions or GPU decode initialize."""
    global _CUDA_DEFAULTS_LOGGED
    ensure_cuda_runtime_dll_paths()
    if not os.environ.get(_INFERENCE_EP_ENV, "").strip():
        os.environ[_INFERENCE_EP_ENV] = _DEFAULT_INFERENCE_EP
    if _CUDA_DEFAULTS_LOGGED:
        return
    _CUDA_DEFAULTS_LOGGED = True
    if not is_cuda_inference_mode():
        logger.info(
            "Inference defaults: mode=%s (CUDAExecutionProvider unavailable in this build)",
            get_inference_ep_mode(),
        )
        return
    zero_copy = False
    full_gpu = False
    try:
        from src.core.extract_frames import cuda_zero_copy_indexing_enabled
        from src.core.gpu_vector_ops import full_gpu_indexing_enabled

        zero_copy = cuda_zero_copy_indexing_enabled()
        full_gpu = full_gpu_indexing_enabled()
    except Exception as exc:
        logger.info("CUDA pipeline capability probe skipped during startup: %s", exc)
    logger.info(
        "Inference defaults: mode=cuda zero_copy=%s full_gpu_index=%s providers=%s",
        zero_copy,
        full_gpu,
        _get_available_ort_providers(),
    )


def _candidate_site_roots() -> list[str]:
    roots: list[str] = []
    for entry in site.getsitepackages():
        if entry:
            roots.append(entry)
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(user_site)
    conda_prefix = str(os.environ.get("CONDA_PREFIX", "") or "").strip()
    if conda_prefix:
        roots.append(os.path.join(conda_prefix, "Lib", "site-packages"))
    deduped: list[str] = []
    seen: set[str] = set()
    for root in roots:
        normalized = os.path.normcase(os.path.normpath(root))
        if normalized in seen or not os.path.isdir(root):
            continue
        seen.add(normalized)
        deduped.append(root)
    return deduped


def ensure_cuda_runtime_dll_paths() -> list[str]:
    """Register pip-installed NVIDIA CUDA/cuDNN DLL directories on Windows."""
    global _CUDA_DLL_PATHS_PREPARED
    if _CUDA_DLL_PATHS_PREPARED:
        return []

    added: list[str] = []
    for site_root in _candidate_site_roots():
        nvidia_root = os.path.join(site_root, "nvidia")
        if not os.path.isdir(nvidia_root):
            continue
        for subdir in _NVIDIA_DLL_SUBDIRS:
            bin_dir = os.path.join(nvidia_root, subdir, "bin")
            if not os.path.isdir(bin_dir):
                continue
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(bin_dir)
                except OSError:
                    pass
            path_value = os.environ.get("PATH", "")
            if os.path.normcase(bin_dir) not in os.path.normcase(path_value):
                os.environ["PATH"] = bin_dir + os.pathsep + path_value
            added.append(bin_dir)

    _CUDA_DLL_PATHS_PREPARED = True
    return added


def preferred_gpu_provider_name() -> str:
    return "CUDAExecutionProvider" if is_cuda_inference_mode() else "DmlExecutionProvider"


def resolve_ort_providers(*, prefer_gpu: bool) -> list[str]:
    if not prefer_gpu:
        return ["CPUExecutionProvider"]
    if is_cuda_inference_mode():
        ensure_cuda_runtime_dll_paths()
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    available = _get_available_ort_providers()
    if "DmlExecutionProvider" in available:
        return ["DmlExecutionProvider", "CPUExecutionProvider"]
    if "CUDAExecutionProvider" in available:
        ensure_cuda_runtime_dll_paths()
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def is_gpu_provider_active(providers: list[str]) -> bool:
    return preferred_gpu_provider_name() in list(providers or [])


def gpu_runtime_fallback_hint() -> str:
    if is_cuda_inference_mode():
        return (
            "Verify that onnxruntime-gpu[cuda,cudnn] is installed and that CUDA 12 / cuDNN 9 "
            "runtime DLLs are available."
        )
    return (
        "Verify that onnxruntime-directml is installed and that DirectML / DirectX 12 is available."
    )
