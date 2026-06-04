"""CUDA EP IO binding for visual ONNX sessions (VIP / experiment path only)."""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import onnxruntime as ort

from src.app.logging_utils import get_logger

logger = get_logger("ort_cuda_io_binding")

_CUDA_IO_BINDING_ENV = "VIDEOSEEK_CUDA_IO_BINDING"


def is_cuda_io_binding_enabled() -> bool:
    override = os.environ.get(_CUDA_IO_BINDING_ENV, "").strip().lower()
    if override in {"0", "false", "no", "off"}:
        return False
    if override in {"1", "true", "yes", "on"}:
        return True
    try:
        from src.core.inference_providers import is_cuda_inference_mode

        return is_cuda_inference_mode()
    except Exception:
        return False


def session_supports_cuda_io_binding(session) -> bool:
    if session is None:
        return False
    try:
        providers = list(session.get_providers() or [])
    except Exception:
        return False
    return "CUDAExecutionProvider" in providers


def _output_names(session) -> list[str]:
    try:
        return [meta.name for meta in session.get_outputs()]
    except Exception:
        return []


def _output_metas(session):
    try:
        return list(session.get_outputs() or [])
    except Exception:
        return []


def _numpy_type_from_ort_type(type_name) -> type:
    raw = str(type_name or "").strip().lower()
    if "float16" in raw:
        return np.float16
    if "double" in raw or "float64" in raw:
        return np.float64
    if "int64" in raw:
        return np.int64
    if "int32" in raw:
        return np.int32
    return np.float32


def _resolve_output_shape(output_meta, batch_size: int) -> tuple[int, ...]:
    batch = max(1, int(batch_size))
    raw_shape = list(getattr(output_meta, "shape", None) or [])
    if not raw_shape:
        return (batch,)

    resolved: list[int] = []
    for index, dim in enumerate(raw_shape):
        if index == 0:
            resolved.append(batch)
            continue
        if dim is None or isinstance(dim, str):
            raise RuntimeError(
                f"Unsupported symbolic output dimension for {getattr(output_meta, 'name', '?')}: {dim!r}"
            )
        value = int(dim)
        if value <= 0:
            raise RuntimeError(
                f"Unsupported dynamic output dimension for {getattr(output_meta, 'name', '?')}: {value}"
            )
        resolved.append(value)
    return tuple(resolved)


class CudaVisualIoBindingRunner:
    """Reusable ``InferenceSession.io_binding()`` runner for batched visual models."""

    def __init__(self, session, *, input_name: str, device_id: int = 0):
        self.session = session
        self.input_name = str(input_name or "input")
        self.device_id = int(device_id)
        self.output_metas = _output_metas(session)
        self.output_names = [meta.name for meta in self.output_metas]
        if not self.output_names:
            raise RuntimeError("Visual ONNX session exposes no output bindings")

    def _bind_outputs(self, io_binding, batch_size: int, *, device: str = "cpu", output_ptrs: dict | None = None) -> None:
        output_ptrs = output_ptrs or {}
        bind_device = str(device or "cpu").strip().lower()
        for meta in self.output_metas:
            shape = _resolve_output_shape(meta, batch_size)
            element_type = _numpy_type_from_ort_type(getattr(meta, "type", None))
            ptr = output_ptrs.get(meta.name)
            if bind_device == "cuda" and ptr is not None:
                io_binding.bind_output(
                    meta.name,
                    "cuda",
                    self.device_id,
                    element_type,
                    shape,
                    int(ptr),
                )
            else:
                io_binding.bind_output(
                    meta.name,
                    "cpu",
                    self.device_id,
                    element_type,
                    shape,
                )

    def run(self, input_blob: np.ndarray) -> list[np.ndarray]:
        if input_blob.dtype != np.float32:
            input_blob = np.ascontiguousarray(input_blob.astype(np.float32, copy=False))
        elif not input_blob.flags["C_CONTIGUOUS"]:
            input_blob = np.ascontiguousarray(input_blob)

        batch_size = max(1, int(input_blob.shape[0]))
        io_binding = self.session.io_binding()
        io_binding.bind_cpu_input(self.input_name, input_blob)
        # Bind outputs per run with the active batch size. Pre-binding once in
        # __init__ pins batch=1; skipping output binding makes ORT reject the run.
        self._bind_outputs(io_binding, batch_size)
        self.session.run_with_iobinding(io_binding)
        outputs = io_binding.copy_outputs_to_cpu()
        if not isinstance(outputs, list):
            return [outputs]
        return list(outputs)

    def run_gpu_io(self, data_ptr: int, input_shape: tuple[int, ...], *, output_gpu=None):
        """Run with CUDA input + CUDA output; return primary output as CuPy (no ORT D2H)."""
        if not input_shape or int(input_shape[0]) <= 0:
            return None
        import cupy as cp

        batch_size = max(1, int(input_shape[0]))
        primary_meta = self.output_metas[0]
        out_shape = _resolve_output_shape(primary_meta, batch_size)
        if output_gpu is None:
            output_gpu = cp.empty(out_shape, dtype=cp.float32)
        else:
            output_gpu = cp.asarray(output_gpu)
            if tuple(int(x) for x in output_gpu.shape) != tuple(int(x) for x in out_shape):
                output_gpu = cp.empty(out_shape, dtype=cp.float32)

        io_binding = self.session.io_binding()
        io_binding.bind_input(
            self.input_name,
            "cuda",
            self.device_id,
            np.float32,
            tuple(int(dim) for dim in input_shape),
            int(data_ptr),
        )
        output_ptrs = {primary_meta.name: int(output_gpu.data.ptr)}
        self._bind_outputs(io_binding, batch_size, device="cuda", output_ptrs=output_ptrs)
        self.session.run_with_iobinding(io_binding)
        cp.cuda.get_current_stream().synchronize()
        return output_gpu

    def run_gpu_input(self, data_ptr: int, shape: tuple[int, ...]) -> list[np.ndarray]:
        """Run inference with a preprocessed input tensor already on CUDA device memory."""
        if not shape or int(shape[0]) <= 0:
            return []
        batch_size = max(1, int(shape[0]))
        io_binding = self.session.io_binding()
        io_binding.bind_input(
            self.input_name,
            "cuda",
            self.device_id,
            np.float32,
            tuple(int(dim) for dim in shape),
            int(data_ptr),
        )
        self._bind_outputs(io_binding, batch_size)
        self.session.run_with_iobinding(io_binding)
        outputs = io_binding.copy_outputs_to_cpu()
        if not isinstance(outputs, list):
            return [outputs]
        return list(outputs)


def create_cuda_visual_io_binding_runner(session, *, input_name: str) -> CudaVisualIoBindingRunner | None:
    if not is_cuda_io_binding_enabled():
        return None
    if not session_supports_cuda_io_binding(session):
        return None
    if not hasattr(session, "io_binding"):
        return None
    try:
        return CudaVisualIoBindingRunner(session, input_name=input_name)
    except Exception as exc:
        logger.warning("Failed to initialize CUDA IO binding: %s", exc)
        return None


def log_cuda_io_binding_active(*, model_path: str, input_name: str, output_names: list[str], gpu_output: bool = False) -> None:
    logger.info(
        "Visual inference using CUDA IO binding: model=%s input=%s outputs=%s gpu_output=%s",
        os.path.basename(str(model_path or "")) or "-",
        input_name,
        ",".join(output_names) if output_names else "-",
        bool(gpu_output),
    )
