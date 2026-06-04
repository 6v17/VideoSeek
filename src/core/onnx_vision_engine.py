import threading
import time

import numpy as np
import onnxruntime as ort

from src.app.logging_utils import get_logger
from src.core.inference_providers import is_gpu_provider_active, resolve_ort_providers
from src.core.onnx_session import build_session_options
from src.core.ort_cuda_io_binding import (
    create_cuda_visual_io_binding_runner,
    is_cuda_io_binding_enabled,
    log_cuda_io_binding_active,
    session_supports_cuda_io_binding,
)

logger = get_logger("onnx_vision_engine")
INFERENCE_LOCK = threading.RLock()


def _record_preprocess(seconds: float) -> None:
    try:
        from src.core.pipeline_profiler import record_preprocess

        record_preprocess(seconds)
    except Exception:
        return


def _record_ort(seconds: float) -> None:
    try:
        from src.core.pipeline_profiler import record_ort

        record_ort(seconds)
    except Exception:
        return


def truncate_log_text(text, limit=240):
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def format_exception_detail(exc):
    if exc is None:
        return ""
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


class OnnxVisionBatchMixin:
    """Shared batched visual embedding with GPU batch-split and CPU fallback."""

    def init_vision_batch_state(
        self,
        *,
        visual_session,
        embedding_batch_size=16,
        image_size=224,
        using_gpu=False,
        backend_label="CPU",
        active_providers=None,
    ):
        self.visual_session = visual_session
        self.embedding_batch_size = max(1, int(embedding_batch_size or 16))
        self.image_size = int(image_size or 224)
        self.using_gpu = bool(using_gpu)
        self.backend_label = str(backend_label or "CPU")
        self.active_providers = dict(active_providers or {})
        self._feature_dim = None
        self._cpu_visual_session = None
        self._visual_force_cpu = False
        self._cuda_io_binding_runner = None
        self._cuda_io_binding_disabled = False
        self._cuda_io_binding_logged = False
        self.runtime_warning = getattr(self, "runtime_warning", "") or ""

    def _vision_provider_key(self):
        providers = getattr(self, "active_providers", None)
        if isinstance(providers, dict):
            if "visual" in providers:
                return "visual"
            if "vision" in providers:
                return "vision"
        return "visual"

    def _set_active_vision_providers(self, providers):
        if not isinstance(getattr(self, "active_providers", None), dict):
            self.active_providers = {}
        key = self._vision_provider_key()
        self.active_providers[key] = list(providers)

    def _on_visual_session_recreated(self):
        self._reset_cuda_io_binding_runner()

    def visual_model_path(self):
        raise NotImplementedError

    def visual_input_name(self):
        return "input"

    def visual_session_providers(self):
        prefer_gpu = bool(getattr(self, "prefer_gpu", False)) and not self._visual_force_cpu
        return resolve_ort_providers(prefer_gpu=prefer_gpu)

    def preprocess_into(self, img_bgr, out_chw):
        raise NotImplementedError

    def extract_visual_features(self, outputs):
        return outputs[0]

    def _visual_batch_output_count(self, features) -> int:
        try:
            from src.core.gpu_vector_ops import is_cupy_array

            if is_cupy_array(features):
                if features.ndim <= 1:
                    return 1
                return int(features.shape[0])
        except Exception:
            pass
        array = np.asarray(features)
        if array.ndim <= 1:
            return 1
        return int(array.shape[0])

    def _validate_visual_batch_output(self, input_blob, features) -> None:
        expected = int(input_blob.shape[0]) if getattr(input_blob, "ndim", 0) > 0 else 0
        actual = self._visual_batch_output_count(features)
        if expected > 0 and actual != expected:
            raise RuntimeError(
                f"Visual batch size mismatch: input={expected} output={actual}"
            )

    def imread_chinese(self, path):
        from src.core.image_io import load_image_bgr

        return load_image_bgr(path)

    def encode_images(self, frames):
        with INFERENCE_LOCK:
            return self._encode_images_locked(frames)

    def encode_preprocessed_batch_gpu(self, gpu_batch):
        with INFERENCE_LOCK:
            return self._encode_preprocessed_batch_gpu_locked(gpu_batch)

    def _encode_preprocessed_batch_gpu_locked(self, gpu_batch):
        self._ensure_feature_dim()
        if gpu_batch is None:
            feature_dim = int(self._feature_dim or 0)
            return self._empty_embedding_batch(feature_dim)

        try:
            import cupy as cp
        except Exception as exc:
            raise RuntimeError("CuPy is required for GPU batch encoding") from exc

        if isinstance(gpu_batch, cp.ndarray) and int(getattr(gpu_batch, "size", 0) or 0) == 0:
            feature_dim = int(self._feature_dim or 0)
            return self._empty_embedding_batch(feature_dim)

        from src.core.gpu_clip_preprocess import as_cuda_input_binding
        from src.core.gpu_vector_ops import full_gpu_indexing_enabled, l2_normalize_gpu

        data_ptr, shape = as_cuda_input_binding(gpu_batch)
        if not shape or int(shape[0]) <= 0:
            feature_dim = int(self._feature_dim or 0)
            return self._empty_embedding_batch(feature_dim)

        ort_t0 = time.perf_counter()
        use_full_gpu = full_gpu_indexing_enabled()
        if use_full_gpu:
            feat = self._run_visual_batch_once_gpu_full(gpu_batch, data_ptr, shape)
            l2_normalize_gpu(feat)
        else:
            feat = self._run_visual_batch_once_gpu(gpu_batch, data_ptr, shape).astype(np.float32)
            feat /= np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10
        _record_ort(time.perf_counter() - ort_t0)
        if isinstance(feat, cp.ndarray):
            self._feature_dim = int(feat.shape[1]) if feat.ndim > 1 else int(feat.shape[0])
        else:
            self._feature_dim = int(feat.shape[1]) if feat.ndim > 1 else int(feat.shape[0])
        return feat

    def _empty_embedding_batch(self, feature_dim: int):
        from src.core.gpu_vector_ops import full_gpu_indexing_enabled

        if full_gpu_indexing_enabled():
            import cupy as cp

            dim = max(0, int(feature_dim or 0))
            return cp.empty((0, dim), dtype=cp.float32)
        return np.empty((0, max(0, int(feature_dim or 0))), dtype=np.float32)

    def _encode_images_locked(self, frames):
        self._ensure_feature_dim()

        embeddings = []
        batch_size = self.embedding_batch_size
        size = self.image_size
        work = np.empty((batch_size, 3, size, size), dtype=np.float32)
        filled = 0

        def flush():
            nonlocal filled
            if filled == 0:
                return
            ort_t0 = time.perf_counter()
            embeddings.append(self._run_visual_batch(work[:filled]))
            _record_ort(time.perf_counter() - ort_t0)
            filled = 0

        for frame in frames:
            image = self.imread_chinese(frame) if isinstance(frame, str) else frame
            if image is None:
                continue
            pre_t0 = time.perf_counter()
            self.preprocess_into(image, work[filled])
            _record_preprocess(time.perf_counter() - pre_t0)
            filled += 1
            if filled < batch_size:
                continue
            flush()

        if filled:
            embeddings.append(self._run_visual_batch(work[:filled]))

        if not embeddings:
            feature_dim = int(self._feature_dim or 0)
            return np.empty((0, feature_dim), dtype=np.float32)
        return np.vstack(embeddings)

    def _ensure_feature_dim(self):
        if self._feature_dim is not None:
            return
        dummy = np.zeros((1, 3, self.image_size, self.image_size), dtype=np.float32)
        features = self._run_visual_batch_once(dummy)
        if features.ndim > 1:
            self._feature_dim = int(features.shape[1])
        else:
            self._feature_dim = int(features.shape[0])

    def _run_visual_batch(self, input_blob):
        if isinstance(input_blob, list):
            if not input_blob:
                feature_dim = self._feature_dim or 0
                return np.empty((0, feature_dim), dtype=np.float32)
            input_blob = np.stack(input_blob, axis=0)

        if input_blob is None or getattr(input_blob, "size", 0) == 0 or input_blob.shape[0] == 0:
            feature_dim = self._feature_dim or 0
            return np.empty((0, feature_dim), dtype=np.float32)

        if input_blob.dtype != np.float32:
            input_blob = np.ascontiguousarray(input_blob.astype(np.float32, copy=False))
        elif not input_blob.flags["C_CONTIGUOUS"]:
            input_blob = np.ascontiguousarray(input_blob)

        feat = self._run_visual_batch_with_recovery(input_blob).astype(np.float32)
        feat /= np.linalg.norm(feat, axis=-1, keepdims=True) + 1e-10
        self._feature_dim = int(feat.shape[1]) if feat.ndim > 1 else int(feat.shape[0])
        return feat

    def _run_visual_batch_with_recovery(self, input_blob):
        try:
            return self._run_visual_batch_once(input_blob)
        except Exception as exc:
            batch_size = int(input_blob.shape[0]) if getattr(input_blob, "ndim", 0) > 0 else 0
            logger.warning(
                "Visual batch inference failed: backend=%s forced_cpu=%s batch_size=%s detail=%s",
                self.backend_label,
                self._visual_force_cpu,
                batch_size,
                truncate_log_text(exc),
            )
            if batch_size > 1:
                midpoint = max(1, batch_size // 2)
                left = self._run_visual_batch_with_recovery(input_blob[:midpoint])
                right = self._run_visual_batch_with_recovery(input_blob[midpoint:])
                if left.size == 0:
                    return right
                if right.size == 0:
                    return left
                return np.vstack([left, right])
            return self._handle_single_frame_visual_failure(input_blob, exc)

    def _run_visual_batch_once(self, input_blob):
        session = self._get_visual_session_for_run()
        if self._can_use_cuda_io_binding(session):
            try:
                runner = self._get_cuda_io_binding_runner(session)
                outputs = runner.run(input_blob)
                features = self.extract_visual_features(outputs)
                self._validate_visual_batch_output(input_blob, features)
                return features
            except Exception as exc:
                self._disable_cuda_io_binding(
                    "CUDA IO binding failed; falling back to session.run",
                    exc,
                )
        outputs = session.run(None, {self.visual_input_name(): input_blob})
        features = self.extract_visual_features(outputs)
        self._validate_visual_batch_output(input_blob, features)
        return features

    def _run_visual_batch_once_gpu(self, gpu_batch, data_ptr: int, shape: tuple[int, ...]):
        session = self._get_visual_session_for_run()
        batch_size = int(shape[0]) if shape else 0
        dummy = np.zeros((max(1, batch_size), 3, self.image_size, self.image_size), dtype=np.float32)
        if self._can_use_cuda_io_binding(session):
            try:
                runner = self._get_cuda_io_binding_runner(session)
                outputs = runner.run_gpu_input(data_ptr, shape)
                features = self.extract_visual_features(outputs)
                self._validate_visual_batch_output(dummy[:batch_size], features)
                return features
            except Exception as exc:
                self._disable_cuda_io_binding(
                    "CUDA GPU-input IO binding failed; falling back to CPU copy",
                    exc,
                )

        import cupy as cp

        input_blob = cp.asnumpy(gpu_batch if isinstance(gpu_batch, cp.ndarray) else cp.asarray(gpu_batch))
        input_blob = np.ascontiguousarray(input_blob, dtype=np.float32)
        outputs = session.run(None, {self.visual_input_name(): input_blob})
        features = self.extract_visual_features(outputs)
        self._validate_visual_batch_output(input_blob, features)
        return features

    def _run_visual_batch_once_gpu_full(self, gpu_batch, data_ptr: int, shape: tuple[int, ...]):
        session = self._get_visual_session_for_run()
        batch_size = int(shape[0]) if shape else 0
        dummy = np.zeros((max(1, batch_size), 3, self.image_size, self.image_size), dtype=np.float32)
        if self._can_use_cuda_io_binding(session):
            try:
                runner = self._get_cuda_io_binding_runner(session)
                features = runner.run_gpu_io(data_ptr, shape)
                self._validate_visual_batch_output(dummy[:batch_size], features)
                return features
            except Exception as exc:
                self._disable_cuda_io_binding(
                    "CUDA full-GPU IO binding failed; falling back to CPU output copy",
                    exc,
                )
        return self._run_visual_batch_once_gpu(gpu_batch, data_ptr, shape)

    def _reset_cuda_io_binding_runner(self) -> None:
        self._cuda_io_binding_runner = None

    def _disable_cuda_io_binding(self, message: str, exc: Exception | None = None) -> None:
        self._cuda_io_binding_disabled = True
        self._reset_cuda_io_binding_runner()
        if exc is not None:
            logger.warning("%s: %s", message, truncate_log_text(exc))
        else:
            logger.warning(message)

    def _can_use_cuda_io_binding(self, session) -> bool:
        if self._cuda_io_binding_disabled or self._visual_force_cpu or not self.using_gpu:
            return False
        if not is_cuda_io_binding_enabled():
            return False
        return session_supports_cuda_io_binding(session)

    def _get_cuda_io_binding_runner(self, session):
        runner = getattr(self, "_cuda_io_binding_runner", None)
        if runner is not None and runner.session is session:
            return runner
        runner = create_cuda_visual_io_binding_runner(session, input_name=self.visual_input_name())
        if runner is None:
            raise RuntimeError("CUDA IO binding is not available for the active visual session")
        self._cuda_io_binding_runner = runner
        if not getattr(self, "_cuda_io_binding_logged", False):
            from src.core.gpu_vector_ops import full_gpu_indexing_enabled

            log_cuda_io_binding_active(
                model_path=self.visual_model_path(),
                input_name=self.visual_input_name(),
                output_names=runner.output_names,
                gpu_output=full_gpu_indexing_enabled(),
            )
            self._cuda_io_binding_logged = True
        return runner

    def _get_visual_session_for_run(self):
        if self._visual_force_cpu:
            session = self._get_cpu_visual_session()
            if session is None:
                raise RuntimeError("CPU fallback visual session is not initialized.")
            return session

        session = getattr(self, "visual_session", None)
        if session is None:
            self._reinitialize_visual_session()
            session = self.visual_session
        if session is None:
            raise RuntimeError(
                "Visual ONNX session is not initialized for "
                f"{self.__class__.__name__} ({self.visual_model_path()})"
            )
        return session

    def _reinitialize_visual_session(self):
        model_path = self.visual_model_path()
        prefer_gpu = bool(getattr(self, "prefer_gpu", False)) and not self._visual_force_cpu
        logger.warning(
            "Recreating missing visual ONNX session: engine=%s model=%s prefer_gpu=%s",
            self.__class__.__name__,
            model_path,
            prefer_gpu,
        )
        self.visual_session = ort.InferenceSession(
            model_path,
            sess_options=build_session_options(prefer_gpu),
            providers=self.visual_session_providers(),
        )
        self._set_active_vision_providers(self.visual_session.get_providers())
        self.using_gpu = is_gpu_provider_active(self.visual_session.get_providers())
        self.backend_label = "GPU" if self.using_gpu else "CPU"
        self._on_visual_session_recreated()

    def _get_cpu_visual_session(self):
        if self._cpu_visual_session is None:
            self._cpu_visual_session = self._create_cpu_visual_session()
        return self._cpu_visual_session

    def _create_cpu_visual_session(self):
        logger.warning("Creating CPU fallback visual session after GPU visual inference failure")
        return ort.InferenceSession(
            self.visual_model_path(),
            sess_options=build_session_options(False),
            providers=["CPUExecutionProvider"],
        )

    def _handle_single_frame_visual_failure(self, input_blob, original_exc):
        if not self.using_gpu and not self._visual_force_cpu:
            raise RuntimeError(
                f"Visual inference failed on CPU for batch size 1: {format_exception_detail(original_exc)}"
            ) from original_exc

        try:
            cpu_feat = self.extract_visual_features(
                self._get_cpu_visual_session().run(None, {self.visual_input_name(): input_blob})
            )
        except Exception as cpu_exc:
            raise RuntimeError(
                "Visual inference failed after batch reduction and CPU fallback. "
                f"GPU error: {format_exception_detail(original_exc)}. "
                f"CPU fallback error: {format_exception_detail(cpu_exc)}"
            ) from cpu_exc

        self._visual_force_cpu = True
        self.using_gpu = False
        self.backend_label = "CPU"
        self._reset_cuda_io_binding_runner()
        self._set_active_vision_providers(["CPUExecutionProvider"])
        fallback_warning = (
            "GPU visual inference became unstable during indexing and fell back to CPU for the remaining frames."
        )
        if fallback_warning not in self.runtime_warning:
            self.runtime_warning = f"{self.runtime_warning} {fallback_warning}".strip()
        logger.warning(
            "GPU visual inference fell back to CPU for remaining frames after batch reduction failure: %s",
            truncate_log_text(original_exc),
        )
        return cpu_feat
