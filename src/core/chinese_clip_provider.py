import json
import os

import cv2
import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.core.onnx_session import build_session_options, resolve_embedding_batch_size
from src.core.onnx_vision_engine import INFERENCE_LOCK, OnnxVisionBatchMixin
from src.storage.config_store import get_effective_prefer_gpu


class ChineseCLIPOnnxEngine(OnnxVisionBatchMixin):
    """Chinese CLIP ONNX inference (512-d projected features)."""

    def __init__(self, model_dir, prefer_gpu=None, image_size=224):
        self.model_dir = os.path.normpath(os.path.abspath(os.fspath(model_dir)))
        self.image_size = int(image_size)
        self._load_preprocessor_stats()
        self.tokenizer = self._build_tokenizer(self.model_dir)

        runtime_config = load_config()
        configured_prefer_gpu = (
            get_effective_prefer_gpu(config=runtime_config) if prefer_gpu is None else bool(prefer_gpu)
        )
        effective_prefer_gpu = configured_prefer_gpu

        self._image_path = os.path.join(self.model_dir, "chinese_clip_image.onnx")
        self._text_path = os.path.join(self.model_dir, "chinese_clip_text.onnx")
        for file_path in (self._image_path, self._text_path):
            if not os.path.isfile(file_path):
                raise RuntimeError(f"Missing Chinese CLIP model file: {file_path}")

        vision_providers = ["CPUExecutionProvider"]
        if effective_prefer_gpu:
            vision_providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        text_providers = ["CPUExecutionProvider"]

        self.visual_session = ort.InferenceSession(
            self._image_path,
            sess_options=build_session_options(effective_prefer_gpu),
            providers=vision_providers,
        )
        self.text_session = ort.InferenceSession(
            self._text_path,
            sess_options=build_session_options(False),
            providers=text_providers,
        )
        self.active_providers = {
            "visual": list(self.visual_session.get_providers()),
            "text": list(self.text_session.get_providers()),
        }
        self.using_gpu = "DmlExecutionProvider" in self.active_providers["visual"]
        self.prefer_gpu = configured_prefer_gpu
        self.provider_id = "chinese_clip_onnx"
        self.init_vision_batch_state(
            visual_session=self.visual_session,
            embedding_batch_size=resolve_embedding_batch_size(runtime_config),
            image_size=self.image_size,
            using_gpu=self.using_gpu,
            backend_label="GPU" if self.using_gpu else "CPU",
            active_providers=self.active_providers,
        )
        self.runtime_warning = ""
        self.runtime_issue = ""
        self.runtime_diagnostics = {}
        self._text_max_length = 512

    def visual_model_path(self):
        return self._image_path

    def visual_input_name(self):
        return "pixel_values"

    def preprocess_into(self, img_bgr, out_chw):
        img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        h, w = int(img.shape[0]), int(img.shape[1])
        size = self.image_size
        if h != size or w != size:
            interp = cv2.INTER_AREA if (h > size or w > size) else cv2.INTER_LINEAR
            img = cv2.resize(img, (size, size), interpolation=interp)
        tensor = img.astype(np.float32, copy=False)
        tensor *= 1.0 / 255.0
        tensor -= self.mean
        tensor /= self.std
        out_chw[:] = np.transpose(tensor, (2, 0, 1))

    def extract_visual_features(self, outputs):
        for tensor in outputs:
            if getattr(tensor, "ndim", 0) == 2:
                return tensor.astype(np.float32)
        first = outputs[0].astype(np.float32)
        if first.ndim == 2:
            return first
        raise RuntimeError(f"Unsupported Chinese CLIP image output shape: {tuple(first.shape)}")

    def _load_preprocessor_stats(self):
        config_path = os.path.join(self.model_dir, "preprocessor_config.json")
        mean = [0.48145466, 0.4578275, 0.40821073]
        std = [0.26862954, 0.26130258, 0.27577711]
        if os.path.isfile(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
                if isinstance(payload.get("image_mean"), list) and len(payload["image_mean"]) == 3:
                    mean = [float(v) for v in payload["image_mean"]]
                if isinstance(payload.get("image_std"), list) and len(payload["image_std"]) == 3:
                    std = [float(v) for v in payload["image_std"]]
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        self.mean = np.array(mean, dtype=np.float32).reshape(1, 1, 3)
        self.std = np.array(std, dtype=np.float32).reshape(1, 1, 3)

    @staticmethod
    def _build_tokenizer(model_dir):
        vocab_path = os.path.join(model_dir, "vocab.txt")
        if not os.path.isfile(vocab_path):
            raise RuntimeError(f"Missing Chinese CLIP vocab file: {vocab_path}")
        try:
            from tokenizers import BertWordPieceTokenizer
        except Exception as exc:
            raise RuntimeError(
                "Chinese CLIP requires the `tokenizers` package for Bert WordPiece vocab loading."
            ) from exc

        tokenizer = BertWordPieceTokenizer(str(vocab_path), lowercase=False)
        tokenizer.enable_truncation(max_length=512)
        return tokenizer

    def encode_text(self, text):
        with INFERENCE_LOCK:
            return self._encode_text_locked(text)

    def _encode_text_locked(self, text):
        encoded = self.tokenizer.encode(str(text or ""))
        input_ids = np.asarray([encoded.ids], dtype=np.int64)
        attention_mask = np.asarray([encoded.attention_mask], dtype=np.int64)
        outputs = self.text_session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )
        features = self.extract_visual_features(outputs).astype(np.float32)
        features /= np.linalg.norm(features, axis=-1, keepdims=True) + 1e-10
        self._feature_dim = int(features.shape[1])
        return features


def build_chinese_clip_profile_manifest(variant="vit-base-patch16"):
    variant_text = str(variant or "").strip() or "vit-base-patch16"
    return {
        "id": f"chinese_clip_{variant_text.replace('-', '_')}",
        "provider": "chinese_clip_onnx",
        "variant": variant_text,
        "display_name": f"Chinese CLIP {variant_text}",
        "prefer_gpu": True,
        "required_files": [
            "chinese_clip_image.onnx",
            "chinese_clip_text.onnx",
            "vocab.txt",
            "preprocessor_config.json",
            "config.json",
        ],
        "files": {
            "image_model": "chinese_clip_image.onnx",
            "text_model": "chinese_clip_text.onnx",
            "tokenizer_vocab": "vocab.txt",
            "preprocessor_config": "preprocessor_config.json",
            "model_config": "config.json",
        },
    }
