"""Local FG-CLIP2 ONNX provider.

Vision inputs are NaFlex patches, not a 224 square tensor. Batch size follows
``embedding_batch_size``. Scores are cosine similarity of L2-normalized vectors.
"""

from __future__ import annotations

import os

import numpy as np
import onnxruntime as ort

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.core.fgclip2_preprocess import (
    EMBEDDING_DIM,
    MAX_PATCHES,
    POSITION_GRID,
    TEXT_SEQ_LEN,
    patchify_bgr,
    resize_positional_embeddings,
)
from src.core.onnx_session import (
    build_session_options,
    gpu_backend_label,
    providers_indicate_gpu,
    resolve_embedding_batch_size,
    resolve_onnx_providers,
)
from src.core.onnx_vision_engine import INFERENCE_LOCK, OnnxVisionBatchMixin
from src.storage.config_store import get_effective_prefer_gpu

logger = get_logger("fgclip2_provider")

# Square CLIP engines use image_size as the NCHW side. FG-CLIP2 never builds that tensor.
PATCH_SIZE_SENTINEL = 16

FGCLIP2_REQUIRED_FILES = [
    "fgclip2_vision_fp16.onnx",
    "fgclip2_text_fp16.onnx",
    "position_embedding_weight.npz",
    "tokenizer.json",
]

_ORT_NUMPY = {
    "tensor(float16)": np.float16,
    "tensor(float)": np.float32,
    "tensor(double)": np.float64,
    "tensor(int32)": np.int32,
    "tensor(int64)": np.int64,
}


def configure_fgclip2_tokenizer(tokenizer, seq_len: int = TEXT_SEQ_LEN):
    """Pad and truncate to the exported text graph length. The tokenizer adds ``<eos>``."""
    tokenizer.enable_truncation(max_length=int(seq_len))
    tokenizer.enable_padding(length=int(seq_len), pad_id=0, pad_token="<pad>")
    return tokenizer


def build_fgclip2_profile_manifest(variant="base", *, embedding_dimension=EMBEDDING_DIM):
    """Return a model_manifest payload for an FG-CLIP2 package."""
    variant_text = str(variant or "").strip() or "base"
    profile_id = "fgclip2_base" if variant_text == "base" else f"fgclip2_{variant_text.replace('-', '_')}"
    display = "FG-CLIP2 base" if variant_text == "base" else f"FG-CLIP2 {variant_text}"
    return {
        "id": profile_id,
        "provider": "fgclip2_onnx",
        "variant": variant_text,
        "display_name": display,
        "prefer_gpu": True,
        "embedding_dimension": int(embedding_dimension),
        "required_files": list(FGCLIP2_REQUIRED_FILES),
        "files": {
            "vision_model": "fgclip2_vision_fp16.onnx",
            "text_model": "fgclip2_text_fp16.onnx",
            "position_embedding": "position_embedding_weight.npz",
            "tokenizer_json": "tokenizer.json",
        },
    }


def _cast_feed(array: np.ndarray, node) -> np.ndarray:
    dtype = _ORT_NUMPY.get(str(getattr(node, "type", "") or ""))
    if dtype is None or array.dtype == dtype:
        return np.ascontiguousarray(array)
    return np.ascontiguousarray(array.astype(dtype, copy=False))


def _embedding_matrix(outputs) -> np.ndarray:
    feat = np.asarray(outputs[0])
    if feat.ndim == 3 and feat.shape[1] == 1:
        feat = feat[:, 0, :]
    if feat.ndim == 1:
        feat = feat.reshape(1, -1)
    elif feat.ndim > 2:
        feat = feat.reshape(feat.shape[0], -1)
    return feat.astype(np.float32, copy=False)


class Fgclip2OnnxEngine(OnnxVisionBatchMixin):
    """FG-CLIP2 vision + text ONNX sessions."""

    def __init__(self, model_dir, prefer_gpu=None):
        self.model_dir = os.path.normpath(os.path.abspath(os.fspath(model_dir)))
        self.provider_id = "fgclip2_onnx"
        self.runtime_issue = ""
        self.runtime_diagnostics = {}
        self.runtime_warning = ""
        runtime_config = load_config()
        configured_prefer_gpu = (
            get_effective_prefer_gpu(config=runtime_config) if prefer_gpu is None else bool(prefer_gpu)
        )
        self.prefer_gpu = configured_prefer_gpu

        self._vision_path = os.path.join(self.model_dir, "fgclip2_vision_fp16.onnx")
        self._text_path = os.path.join(self.model_dir, "fgclip2_text_fp16.onnx")
        self._position_path = os.path.join(self.model_dir, "position_embedding_weight.npz")
        for file_path in (self._vision_path, self._text_path, self._position_path):
            if not os.path.isfile(file_path):
                raise RuntimeError(f"Missing FG-CLIP2 model file: {file_path}")

        self.tokenizer = self._build_tokenizer(self.model_dir)
        self._position_table = self._load_position_table(self._position_path)

        providers = resolve_onnx_providers(prefer_gpu=configured_prefer_gpu, config=runtime_config)
        self.vision_session = ort.InferenceSession(
            self._vision_path,
            sess_options=build_session_options(configured_prefer_gpu),
            providers=providers,
        )
        self.text_session = ort.InferenceSession(
            self._text_path,
            sess_options=build_session_options(configured_prefer_gpu),
            providers=providers,
        )
        self.active_providers = {
            "visual": list(self.vision_session.get_providers()),
            "text": list(self.text_session.get_providers()),
        }
        self.using_gpu = providers_indicate_gpu([self.active_providers["visual"]])
        backend = gpu_backend_label([self.active_providers["visual"]]) if self.using_gpu else "CPU"
        self.init_vision_batch_state(
            visual_session=self.vision_session,
            embedding_batch_size=resolve_embedding_batch_size(runtime_config),
            image_size=PATCH_SIZE_SENTINEL,
            using_gpu=self.using_gpu,
            backend_label=backend,
            active_providers=self.active_providers,
        )
        self._vision_inputs = list(self.vision_session.get_inputs())
        self._text_inputs = list(self.text_session.get_inputs())

    def visual_model_path(self):
        return self._vision_path

    def _on_visual_session_recreated(self):
        self.vision_session = self.visual_session
        self._vision_inputs = list(self.visual_session.get_inputs())

    @staticmethod
    def _load_position_table(path):
        asset = np.load(path)
        weight = np.asarray(asset["weight"], dtype=np.float32)
        grid = int(asset["position_embedding_size"]) if "position_embedding_size" in asset.files else POSITION_GRID
        if weight.ndim == 2:
            weight = weight.reshape(grid, grid, -1)
        if weight.shape[0] != grid or weight.shape[1] != grid:
            raise RuntimeError(
                f"FG-CLIP2 position table shape {tuple(weight.shape)} does not match grid {grid}"
            )
        return weight

    @staticmethod
    def _build_tokenizer(model_dir):
        tokenizer_path = os.path.join(model_dir, "tokenizer.json")
        if not os.path.isfile(tokenizer_path):
            raise RuntimeError(f"Missing FG-CLIP2 tokenizer file: {tokenizer_path}")
        try:
            from tokenizers import Tokenizer
        except Exception as exc:
            raise RuntimeError("FG-CLIP2 requires the `tokenizers` package.") from exc
        return configure_fgclip2_tokenizer(Tokenizer.from_file(tokenizer_path))

    def encode_text(self, text):
        with INFERENCE_LOCK:
            return self._encode_text_locked(text)

    def _encode_text_locked(self, text):
        encoded = self.tokenizer.encode(str(text or ""))
        ids = np.asarray([encoded.ids], dtype=np.int64)
        if ids.shape[1] != TEXT_SEQ_LEN:
            raise RuntimeError(f"FG-CLIP2 text length must be {TEXT_SEQ_LEN}, got {ids.shape[1]}")
        feed = {}
        for node in self._text_inputs:
            if node.name == "input_ids":
                feed[node.name] = _cast_feed(ids, node)
        if not feed and len(self._text_inputs) == 1:
            node = self._text_inputs[0]
            feed[node.name] = _cast_feed(ids, node)
        if not feed:
            raise RuntimeError("FG-CLIP2 text encoder inputs could not be prepared.")
        features = _embedding_matrix(self.text_session.run(None, feed))
        features /= np.linalg.norm(features, axis=-1, keepdims=True) + 1e-10
        self._feature_dim = int(features.shape[1])
        return features

    def encode_images(self, frames):
        prepared = []
        for frame in frames or []:
            image = self.imread_chinese(frame) if isinstance(frame, str) else frame
            if image is None:
                continue
            try:
                prepared.append(patchify_bgr(image))
            except ValueError as exc:
                logger.info("Skipping FG-CLIP2 frame: %s", exc)
                continue
        if not prepared:
            feature_dim = int(self._feature_dim or EMBEDDING_DIM)
            return np.empty((0, feature_dim), dtype=np.float32)

        batch_size = max(1, int(self.embedding_batch_size or 1))
        batches = []
        for start in range(0, len(prepared), batch_size):
            chunk = prepared[start : start + batch_size]
            pixels = np.stack([item[0] for item in chunk], axis=0)
            mask = np.stack([item[1] for item in chunk], axis=0)
            spatial = np.stack([item[2] for item in chunk], axis=0)
            pos = resize_positional_embeddings(self._position_table, spatial, max_length=MAX_PATCHES)
            batches.append((pixels, pos, mask))

        embeddings = []
        with INFERENCE_LOCK:
            for pixels, pos, mask in batches:
                embeddings.append(self._run_vision_batch(pixels, pos, mask))
        features = np.vstack(embeddings).astype(np.float32, copy=False)
        features /= np.linalg.norm(features, axis=-1, keepdims=True) + 1e-10
        self._feature_dim = int(features.shape[1])
        return features

    def _vision_feed(self, session_inputs, pixels, pos, mask):
        by_name = {node.name: node for node in session_inputs}
        feed = {}
        if "pixel_values" in by_name:
            feed["pixel_values"] = _cast_feed(pixels, by_name["pixel_values"])
        if "pos_emb" in by_name:
            feed["pos_emb"] = _cast_feed(pos, by_name["pos_emb"])
        mask_name = "pixel_attention_mask" if "pixel_attention_mask" in by_name else ""
        if not mask_name:
            for name in by_name:
                if "mask" in name:
                    mask_name = name
                    break
        if mask_name:
            feed[mask_name] = _cast_feed(mask, by_name[mask_name])
        missing = [node.name for node in session_inputs if node.name not in feed]
        if missing:
            raise RuntimeError(f"FG-CLIP2 vision inputs missing: {', '.join(missing)}")
        return feed

    def _run_vision_batch(self, pixels, pos, mask):
        try:
            session = self._get_visual_session_for_run()
            outputs = session.run(None, self._vision_feed(self._vision_inputs, pixels, pos, mask))
            return _embedding_matrix(outputs)
        except Exception as exc:
            batch = int(pixels.shape[0])
            if batch > 1:
                mid = max(1, batch // 2)
                left = self._run_vision_batch(pixels[:mid], pos[:mid], mask[:mid])
                right = self._run_vision_batch(pixels[mid:], pos[mid:], mask[mid:])
                return np.vstack([left, right])
            return self._vision_single_fallback(pixels, pos, mask, exc)

    def _vision_single_fallback(self, pixels, pos, mask, original_exc):
        if not self.using_gpu and not self._visual_force_cpu:
            raise RuntimeError(f"FG-CLIP2 visual inference failed: {original_exc}") from original_exc
        cpu_session = self._get_cpu_visual_session()
        try:
            outputs = cpu_session.run(
                None,
                self._vision_feed(list(cpu_session.get_inputs()), pixels, pos, mask),
            )
        except Exception as cpu_exc:
            raise RuntimeError(
                f"FG-CLIP2 visual inference failed on GPU ({original_exc}) and CPU ({cpu_exc})"
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
        logger.warning("FG-CLIP2 visual inference fell back to CPU: %s", original_exc)
        return _embedding_matrix(outputs)
