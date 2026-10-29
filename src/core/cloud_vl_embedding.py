"""Optional DashScope Qwen3-VL-Embedding client.

Frames and queries are encoded by the cloud API. Vectors stay local and never
share an index with Chinese-CLIP. The packed ONNX export is not used.
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

import cv2
import numpy as np

CLOUD_VL_PROVIDER_ID = "qwen3_vl_embedding_cloud"
CLOUD_VL_PROFILE_ID = "qwen3_vl_embedding_cloud"
CLOUD_VL_MODEL = "qwen3-vl-embedding"
CLOUD_VL_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
    "multimodal-embedding/multimodal-embedding"
)
CLOUD_VL_DIMENSIONS = (256, 512, 768, 1024, 1536, 2048, 2560)
CLOUD_VL_DEFAULT_DIMENSION = 2048
_IMAGE_LONG_SIDE = 1280
_API_IMAGE_BATCH = 4
_MAX_ATTEMPTS = 3

DEFAULT_CLOUD_VL_EMBEDDING = {
    "enabled": False,
    "api_key": "",
    "base_url": CLOUD_VL_ENDPOINT,
    "model": CLOUD_VL_MODEL,
    "dimension": CLOUD_VL_DEFAULT_DIMENSION,
}


def normalize_cloud_vl_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(raw or {})
    try:
        dimension = int(source.get("dimension", CLOUD_VL_DEFAULT_DIMENSION))
    except (TypeError, ValueError):
        dimension = CLOUD_VL_DEFAULT_DIMENSION
    if dimension not in CLOUD_VL_DIMENSIONS:
        dimension = CLOUD_VL_DEFAULT_DIMENSION
    model = str(source.get("model") or CLOUD_VL_MODEL).strip() or CLOUD_VL_MODEL
    base_url = str(source.get("base_url") or CLOUD_VL_ENDPOINT).strip() or CLOUD_VL_ENDPOINT
    return {
        "enabled": bool(source.get("enabled", False)),
        "api_key": str(source.get("api_key") or "").strip(),
        "base_url": base_url,
        "model": model,
        "dimension": dimension,
        "previous_profile_id": str(source.get("previous_profile_id") or "").strip(),
    }


def resolve_cloud_vl_api_key(config: Mapping[str, Any] | None, settings: Mapping[str, Any] | None = None) -> str:
    payload = normalize_cloud_vl_settings(settings if settings is not None else (config or {}).get("cloud_vl_embedding"))
    if payload["api_key"]:
        return payload["api_key"]
    understanding = (config or {}).get("understanding")
    remote = understanding.get("remote_vlm") if isinstance(understanding, dict) else None
    if not isinstance(remote, dict):
        return ""
    from src.services.understanding_resource_service import get_remote_vlm_api_key_for_preset

    return get_remote_vlm_api_key_for_preset(remote, "dashscope")


def cloud_vl_variant(dimension: int) -> str:
    return f"qwen3-vl-embedding-{int(dimension)}"


def _l2_normalize(rows: np.ndarray) -> np.ndarray:
    array = np.asarray(rows, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    return array / np.clip(norms, 1e-12, None)


def _load_bgr(frame) -> np.ndarray:
    if isinstance(frame, str):
        raw = np.fromfile(frame, dtype=np.uint8)
        image = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Cloud embedding could not read image: {frame}")
        return image
    image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] != 3:
        raise RuntimeError("Cloud embedding expects a BGR image.")
    return image


def _jpeg_data_uri(image_bgr: np.ndarray) -> str:
    frame = image_bgr
    height, width = int(frame.shape[0]), int(frame.shape[1])
    long_side = max(height, width)
    if long_side > _IMAGE_LONG_SIDE:
        scale = float(_IMAGE_LONG_SIDE) / float(long_side)
        frame = cv2.resize(
            frame,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        raise RuntimeError("Cloud embedding failed to encode a JPEG frame.")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def _error_message(body: bytes, status: int) -> str:
    text = body.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text) if text else {}
    except json.JSONDecodeError:
        payload = {}
    if isinstance(payload, dict):
        message = str(payload.get("message") or payload.get("error") or "").strip()
        code = str(payload.get("code") or "").strip()
        if message:
            return f"Cloud embedding API {status} {code}: {message}".strip()
    snippet = text[:240] if text else "empty response"
    return f"Cloud embedding API {status}: {snippet}"


def embed_contents(settings: Mapping[str, Any], api_key: str, contents: list[dict]) -> np.ndarray:
    """Call DashScope once. ``contents`` items are independent text or image inputs."""
    payload = normalize_cloud_vl_settings(settings)
    key = str(api_key or "").strip()
    if not key:
        raise RuntimeError(
            "Cloud embedding API key is missing. Add a DashScope key in Settings, "
            "or save the Qwen vision DashScope key."
        )
    if not contents:
        return np.empty((0, int(payload["dimension"])), dtype=np.float32)
    body = json.dumps(
        {
            "model": payload["model"],
            "input": {"contents": contents},
            "parameters": {"dimension": int(payload["dimension"])},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        payload["base_url"],
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
            break
        except urllib.error.HTTPError as exc:
            detail = _error_message(exc.read(), int(exc.code))
            last_error = RuntimeError(detail)
            if exc.code not in {429, 500, 502, 503} or attempt + 1 >= _MAX_ATTEMPTS:
                raise last_error from exc
            time.sleep(1.5 * (attempt + 1))
        except urllib.error.URLError as exc:
            last_error = RuntimeError(f"Cloud embedding request failed: {exc.reason}")
            if attempt + 1 >= _MAX_ATTEMPTS:
                raise last_error from exc
            time.sleep(1.5 * (attempt + 1))
    else:
        raise last_error or RuntimeError("Cloud embedding request failed.")

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Cloud embedding API returned invalid JSON.") from exc
    rows = ((parsed.get("output") or {}).get("embeddings") if isinstance(parsed, dict) else None)
    if not isinstance(rows, list) or len(rows) != len(contents):
        raise RuntimeError(
            f"Cloud embedding API returned {0 if not isinstance(rows, list) else len(rows)} "
            f"vectors for {len(contents)} inputs."
        )
    ordered = sorted(rows, key=lambda item: int(item.get("index", 0)))
    vectors = []
    expected = int(payload["dimension"])
    for item in ordered:
        values = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(values, list) or len(values) != expected:
            raise RuntimeError(
                f"Cloud embedding dimension is {0 if not isinstance(values, list) else len(values)}, "
                f"profile expects {expected}."
            )
        vectors.append(values)
    return _l2_normalize(np.asarray(vectors, dtype=np.float32))


class CloudVlEmbeddingEngine:
    """Text and frame embeddings from DashScope qwen3-vl-embedding."""

    remote = True
    visual_session = None
    prefer_gpu = False
    using_gpu = False
    backend_label = "Cloud"
    runtime_warning = ""
    runtime_issue = ""
    runtime_diagnostics: dict = {}
    provider_id = CLOUD_VL_PROVIDER_ID

    def __init__(self):
        from src.app.config import load_config

        config = load_config()
        self._config = config
        self._settings = normalize_cloud_vl_settings(config.get("cloud_vl_embedding"))
        self._api_key = resolve_cloud_vl_api_key(config, self._settings)
        self.embedding_batch_size = _API_IMAGE_BATCH
        if not self._api_key:
            self.runtime_warning = "Cloud embedding API key is missing."

    def encode_text(self, text):
        query = str(text or "").strip()
        if not query:
            raise RuntimeError("Cloud embedding query is empty.")
        return embed_contents(self._settings, self._api_key, [{"text": query}])

    def encode_images(self, frames):
        images = [_jpeg_data_uri(_load_bgr(frame)) for frame in frames or []]
        if not images:
            return np.empty((0, int(self._settings["dimension"])), dtype=np.float32)
        parts = []
        for start in range(0, len(images), _API_IMAGE_BATCH):
            batch = images[start : start + _API_IMAGE_BATCH]
            parts.append(embed_contents(self._settings, self._api_key, [{"image": uri} for uri in batch]))
        return np.vstack(parts)
