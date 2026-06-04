"""GPU CLIP preprocessing (CuPy) for NVDEC zero-copy indexing."""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

from src.app.logging_utils import get_logger

logger = get_logger("gpu_clip_preprocess")

_DEFAULT_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_DEFAULT_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

_CUPY_MODULE = None
_CUPY_NDI = None


def _get_cupy():
    global _CUPY_MODULE
    if _CUPY_MODULE is None:
        import cupy as cp

        _CUPY_MODULE = cp
    return _CUPY_MODULE


def _get_cupy_ndi():
    global _CUPY_NDI
    if _CUPY_NDI is None:
        import cupyx.scipy.ndimage as ndi

        _CUPY_NDI = ndi
    return _CUPY_NDI


def cupy_available(*, force_refresh: bool = False) -> bool:
    if force_refresh:
        global _CUPY_MODULE, _CUPY_NDI
        _CUPY_MODULE = None
        _CUPY_NDI = None
    try:
        _get_cupy()
        return True
    except Exception:
        return False


def resolve_clip_mean_std(mean=None, std=None):
    mean_arr = np.asarray(mean if mean is not None else _DEFAULT_MEAN, dtype=np.float32).reshape(1, 1, 3)
    std_arr = np.asarray(std if std is not None else _DEFAULT_STD, dtype=np.float32).reshape(1, 1, 3)
    return mean_arr, std_arr


def _ensure_cupy_cuda_context(device_id: int = 0) -> None:
    """Initialize CuPy on the target device before PyNvVideoCodec opens its CUDA context."""
    cp = _get_cupy()
    device = cp.cuda.Device(int(device_id))
    device.use()
    # Touch the default memory pool so CuPy attaches to the primary context early.
    scratch = cp.empty(1, dtype=cp.uint8)
    del scratch
    device.synchronize()


def gpu_frame_to_cupy(frame: Any, *, copy: bool = False):
    """Convert a PyNvVideoCodec GPU frame (DLPack / CAI) to CuPy HWC uint8 RGB."""
    cp = _get_cupy()
    if isinstance(frame, cp.ndarray):
        return frame.copy() if copy else frame
    try:
        arr = cp.from_dlpack(frame)
    except Exception:
        arr = None
    if arr is None:
        try:
            arr = cp.asarray(frame)
        except Exception as exc:
            raise RuntimeError(f"Unsupported GPU frame type: {type(frame)!r}") from exc
    if copy:
        arr = cp.ascontiguousarray(arr.copy())
    return arr


def retain_nvdec_gpu_frame(frame: Any):
    """Copy a decoder-owned GPU frame into CuPy-owned device memory.

    PyNvVideoCodec external buffers become invalid once the decoder stops or reuses
    the pool; consumers must retain a copy before the decode stream advances/closes.
    """
    cp = _get_cupy()
    arr = gpu_frame_to_cupy(frame, copy=True)
    cp.cuda.get_current_stream().synchronize()
    return arr


def resize_rgb_gpu(gpu_rgb, image_size: int):
    """Resize HWC RGB on GPU to ``image_size`` x ``image_size``."""
    cp = _get_cupy()
    ndi = _get_cupy_ndi()
    arr = gpu_frame_to_cupy(gpu_rgb)
    if arr.ndim != 3 or int(arr.shape[-1]) != 3:
        raise RuntimeError(f"Expected HWC RGB frame, got shape {tuple(arr.shape)}")
    height, width = int(arr.shape[0]), int(arr.shape[1])
    size = int(image_size)
    if height == size and width == size:
        return arr
    factors = (size / float(height), size / float(width), 1.0)
    resized = ndi.zoom(arr.astype(cp.float32), factors, order=1)
    return cp.clip(resized, 0, 255).astype(cp.uint8)


def preprocess_batch_gpu(
    frames: Sequence[Any],
    *,
    image_size: int = 224,
    mean=None,
    std=None,
) -> Any:
    """Return contiguous GPU NCHW float32 batch shaped (N, 3, image_size, image_size)."""
    if not frames:
        cp = _get_cupy()
        return cp.empty((0, 3, int(image_size), int(image_size)), dtype=cp.float32)

    cp = _get_cupy()
    mean_np, std_np = resolve_clip_mean_std(mean=mean, std=std)
    mean_gpu = cp.asarray(mean_np)
    std_gpu = cp.asarray(std_np)

    resized = [resize_rgb_gpu(frame, image_size) for frame in frames]
    batch_hwc = cp.stack(resized, axis=0).astype(cp.float32)
    batch_hwc *= 1.0 / 255.0
    batch_hwc -= mean_gpu
    batch_hwc /= std_gpu
    batch_nchw = cp.transpose(batch_hwc, (0, 3, 1, 2))
    return cp.ascontiguousarray(batch_nchw, dtype=cp.float32)


def as_cuda_input_binding(batch_gpu) -> tuple[int, tuple[int, ...]]:
    """Return ``(device_ptr, shape)`` for ORT CUDA input binding."""
    cp = _get_cupy()
    arr = batch_gpu if isinstance(batch_gpu, cp.ndarray) else gpu_frame_to_cupy(batch_gpu)
    if not arr.flags["C_CONTIGUOUS"]:
        arr = cp.ascontiguousarray(arr)
    shape = tuple(int(dim) for dim in arr.shape)
    return int(arr.data.ptr), shape


def load_mean_std_from_engine(engine) -> tuple[np.ndarray, np.ndarray]:
    mean = getattr(engine, "mean", None)
    std = getattr(engine, "std", None)
    return resolve_clip_mean_std(mean=mean, std=std)
