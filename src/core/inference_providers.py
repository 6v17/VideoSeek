"""ORT execution provider selection (DirectML default; CUDA via env on experiment branch)."""
from __future__ import annotations

import os
import site

_INFERENCE_EP_ENV = "VIDEOSEEK_INFERENCE_EP"
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


def get_inference_ep_mode() -> str:
    return os.environ.get(_INFERENCE_EP_ENV, "dml").strip().lower()


def is_cuda_inference_mode() -> bool:
    return get_inference_ep_mode() == "cuda"


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
    return ["DmlExecutionProvider", "CPUExecutionProvider"]


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
