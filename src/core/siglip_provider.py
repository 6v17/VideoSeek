import os

import cv2
import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.core.inference_providers import is_gpu_provider_active, resolve_ort_providers
from src.core.onnx_session import build_session_options, resolve_embedding_batch_size
from src.core.onnx_vision_engine import INFERENCE_LOCK, OnnxVisionBatchMixin
from src.storage.config_store import get_effective_prefer_gpu


class SigLIP2OnnxEngine(OnnxVisionBatchMixin):
    """Local SigLIP2 ONNX inference provider."""

    def __init__(self, model_dir, prefer_gpu=None, image_size=224):
        self.model_dir = os.path.normpath(os.path.abspath(os.fspath(model_dir)))
        self.image_size = int(image_size)
        self.tokenizer = self._build_tokenizer(self.model_dir)
        runtime_config = load_config()
        configured_prefer_gpu = (
            get_effective_prefer_gpu(config=runtime_config) if prefer_gpu is None else bool(prefer_gpu)
        )
        effective_prefer_gpu = configured_prefer_gpu

        self._vision_path = os.path.join(self.model_dir, "vision_model.onnx")
        self._text_path = os.path.join(self.model_dir, "text_model.onnx")
        for file_path in [self._vision_path, self._text_path]:
            if not os.path.isfile(file_path):
                raise RuntimeError(f"Missing SigLIP model file: {file_path}")

        vision_providers = resolve_ort_providers(prefer_gpu=effective_prefer_gpu)

        # Keep text on CPU by default for compatibility; make this configurable later if needed.
        text_providers = ["CPUExecutionProvider"]

        self.vision_session = ort.InferenceSession(
            self._vision_path,
            sess_options=build_session_options(effective_prefer_gpu),
            providers=vision_providers,
        )
        self.text_session = ort.InferenceSession(
            self._text_path,
            sess_options=build_session_options(False),
            providers=text_providers,
        )
        self.active_providers = {
            "visual": list(self.vision_session.get_providers()),
            "text": list(self.text_session.get_providers()),
        }
        self.using_gpu = is_gpu_provider_active(self.active_providers["visual"])
        self.prefer_gpu = configured_prefer_gpu
        self.provider_id = "siglip2_onnx"
        self.init_vision_batch_state(
            visual_session=self.vision_session,
            embedding_batch_size=resolve_embedding_batch_size(runtime_config),
            image_size=self.image_size,
            using_gpu=self.using_gpu,
            backend_label="GPU" if self.using_gpu else "CPU",
            active_providers=self.active_providers,
        )
        self.runtime_issue = ""
        self.runtime_diagnostics = {}
        self._tokenizer_backend = "unknown"
        self._vision_input_name = self.vision_session.get_inputs()[0].name

    def visual_model_path(self):
        return self._vision_path

    def visual_input_name(self):
        return self._vision_input_name

    def _on_visual_session_recreated(self):
        self._vision_input_name = self.visual_session.get_inputs()[0].name

    def preprocess_into(self, img_bgr, out_chw):
        """Normalize one BGR frame into CHW float32 ``out_chw`` shaped (3, image_size, image_size)."""
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = int(img.shape[0]), int(img.shape[1])
        size = self.image_size
        if h != size or w != size:
            interp = cv2.INTER_AREA if (h > size or w > size) else cv2.INTER_LINEAR
            img = cv2.resize(img, (size, size), interpolation=interp)
        tensor = img.astype(np.float32, copy=False)
        tensor *= 2.0 / 255.0
        tensor -= 1.0
        out_chw[:] = np.transpose(tensor, (2, 0, 1))

    def extract_visual_features(self, outputs):
        for tensor in outputs:
            if getattr(tensor, "ndim", 0) == 2:
                return tensor.astype(np.float32)
        first = outputs[0].astype(np.float32)
        if first.ndim == 3:
            return np.mean(first, axis=1)
        if first.ndim == 2:
            return first
        raise RuntimeError(f"Unsupported SigLIP output shape: {tuple(first.shape)}")

    @staticmethod
    def _build_tokenizer(model_dir):
        tokenizer_json_path = os.path.join(model_dir, "tokenizer.json")
        if not os.path.isfile(tokenizer_json_path):
            raise RuntimeError(f"Missing SigLIP tokenizer file: {tokenizer_json_path}")
        try:
            from tokenizers import Tokenizer
        except Exception as exc:
            raise RuntimeError("SigLIP requires the `tokenizers` package for tokenizer.json loading.") from exc

        tokenizer = Tokenizer.from_file(tokenizer_json_path)
        tokenizer.enable_truncation(max_length=64)
        tokenizer.enable_padding(length=64, pad_id=0, pad_token="[PAD]")
        return {
            "backend": "tokenizers",
            "instance": tokenizer,
        }

    def encode_text(self, text):
        with INFERENCE_LOCK:
            return self._encode_text_locked(text)

    def _encode_text_locked(self, text):
        encoded = self._encode_text_inputs(str(text or ""))
        feed = {}
        text_inputs = self.text_session.get_inputs()
        for node in text_inputs:
            if node.name in encoded:
                feed[node.name] = encoded[node.name].astype(np.int64)
        if not feed and text_inputs:
            first_name = text_inputs[0].name
            if "input_ids" in encoded:
                feed[first_name] = encoded["input_ids"].astype(np.int64)
        if not feed:
            raise RuntimeError("SigLIP text encoder inputs could not be prepared for ONNX session.")
        outputs = self.text_session.run(None, feed)
        features = self.extract_visual_features(outputs).astype(np.float32)
        features /= np.linalg.norm(features, axis=-1, keepdims=True) + 1e-10
        self._feature_dim = int(features.shape[1])
        return features

    def _encode_text_inputs(self, text):
        tokenizer_wrapper = self.tokenizer
        backend = str(tokenizer_wrapper.get("backend", "") or "")
        tokenizer_instance = tokenizer_wrapper.get("instance")

        if backend != "tokenizers" or tokenizer_instance is None:
            raise RuntimeError("SigLIP tokenizer backend is invalid; expected tokenizers runtime.")
        self._tokenizer_backend = "tokenizers"
        encoded = tokenizer_instance.encode(text)
        input_ids = np.asarray([encoded.ids], dtype=np.int64)
        attention_mask = np.asarray([encoded.attention_mask], dtype=np.int64)
        return {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }


def build_siglip_profile_manifest(variant="base-patch16-224"):
    """Return a model_manifest payload for SigLIP package parsing."""
    variant_text = str(variant or "").strip() or "base-patch16-224"
    return {
        "id": f"siglip2_{variant_text.replace('-', '_')}",
        "provider": "siglip2_onnx",
        "variant": variant_text,
        "display_name": f"SigLIP2 {variant_text}",
        "prefer_gpu": True,
        "required_files": [
            "vision_model.onnx",
            "text_model.onnx",
            "tokenizer.json",
            "tokenizer_config.json",
        ],
        "files": {
            "vision_model": "vision_model.onnx",
            "text_model": "text_model.onnx",
            "tokenizer_json": "tokenizer.json",
            "tokenizer_config": "tokenizer_config.json",
        },
    }
