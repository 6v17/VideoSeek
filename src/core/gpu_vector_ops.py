"""GPU vector utilities for full-GPU CUDA indexing (CuPy)."""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

_FULL_GPU_ENV = "VIDEOSEEK_FULL_GPU_INDEX"


def is_cupy_array(value: Any) -> bool:
    try:
        import cupy as cp
    except Exception:
        return False
    return isinstance(value, cp.ndarray)


def full_gpu_indexing_enabled(config=None) -> bool:
    """True when embeddings should stay on GPU until final host save (Lance D2H)."""
    import os

    force = os.environ.get(_FULL_GPU_ENV, "").strip().lower()
    if force in {"0", "false", "no", "off"}:
        return False
    if force in {"1", "true", "yes", "on"}:
        try:
            from src.core.extract_frames import cuda_zero_copy_indexing_enabled, cupy_available

            return cuda_zero_copy_indexing_enabled(config=config) and cupy_available()
        except Exception:
            return False
    try:
        from src.core.extract_frames import cuda_zero_copy_indexing_enabled

        return cuda_zero_copy_indexing_enabled(config=config)
    except Exception:
        return False


def l2_normalize_gpu(batch_gpu, *, eps: float = 1e-10):
    """In-place L2 row normalization on a 2-D CuPy array."""
    import cupy as cp

    arr = batch_gpu if isinstance(batch_gpu, cp.ndarray) else cp.asarray(batch_gpu)
    if arr.size == 0:
        return arr
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    norms = cp.linalg.norm(arr, axis=1, keepdims=True)
    arr /= cp.maximum(norms, float(eps))
    return arr


def vstack_gpu(parts: Sequence[Any]):
    import cupy as cp

    arrays = [part for part in parts if part is not None and getattr(part, "size", 0)]
    if not arrays:
        return cp.empty((0, 0), dtype=cp.float32)
    return cp.vstack([cp.asarray(part) for part in arrays])


def gpu_to_numpy(batch_gpu) -> np.ndarray:
    import cupy as cp

    if isinstance(batch_gpu, cp.ndarray):
        return cp.asnumpy(batch_gpu).astype(np.float32, copy=False)
    return np.asarray(batch_gpu, dtype=np.float32)
