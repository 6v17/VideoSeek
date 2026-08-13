import threading

import numpy as np
import onnxruntime as ort

from src.app.logging_utils import get_logger
from src.core.onnx_session import (
    build_session_options,
    gpu_backend_label,
    providers_indicate_gpu,
    resolve_onnx_providers,
)

logger = get_logger("onnx_vision_engine")
INFERENCE_LOCK = threading.RLock()


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
        return None

    def visual_model_path(self):
        raise NotImplementedError

    def visual_input_name(self):
        return "input"

    def visual_session_providers(self):
        prefer_gpu = bool(getattr(self, "prefer_gpu", False)) and not self._visual_force_cpu
        config = None
        try:
            from src.app.config import load_config

            config = load_config()
        except Exception:
            config = None
        return resolve_onnx_providers(prefer_gpu=prefer_gpu, config=config)

    def preprocess_into(self, img_bgr, out_chw):
        raise NotImplementedError

    def extract_visual_features(self, outputs):
        return outputs[0]

    def imread_chinese(self, path):
        from src.core.image_io import load_image_bgr

        return load_image_bgr(path)

    def encode_images(self, frames):
        """Embed frames; CPU preprocess runs outside ``INFERENCE_LOCK``, ORT only under lock."""
        batches = self._preprocess_frames_to_batches(frames)
        if not batches:
            feature_dim = int(self._feature_dim or 0)
            return np.empty((0, feature_dim), dtype=np.float32)

        embeddings = []
        with INFERENCE_LOCK:
            self._ensure_feature_dim()
            for blob in batches:
                embeddings.append(self._run_visual_batch(blob))

        if not embeddings:
            feature_dim = int(self._feature_dim or 0)
            return np.empty((0, feature_dim), dtype=np.float32)
        return np.vstack(embeddings)

    def _preprocess_frames_to_batches(self, frames):
        """Load/preprocess frames into float32 NCHW batches without holding the inference lock."""
        batch_size = self.embedding_batch_size
        size = self.image_size
        batches = []
        work = np.empty((batch_size, 3, size, size), dtype=np.float32)
        filled = 0

        for frame in frames or []:
            image = self.imread_chinese(frame) if isinstance(frame, str) else frame
            if image is None:
                continue
            self.preprocess_into(image, work[filled])
            filled += 1
            if filled < batch_size:
                continue
            batches.append(np.ascontiguousarray(work[:filled]))
            filled = 0
            work = np.empty((batch_size, 3, size, size), dtype=np.float32)

        if filled:
            batches.append(np.ascontiguousarray(work[:filled]))
        return batches

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
        outputs = session.run(None, {self.visual_input_name(): input_blob})
        return self.extract_visual_features(outputs)

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
        active = list(self.visual_session.get_providers())
        self._set_active_vision_providers(active)
        self.using_gpu = providers_indicate_gpu([active])
        self.backend_label = gpu_backend_label([active]) if self.using_gpu else "CPU"
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
