"""Mixed preset query vector encoding and per-profile cache."""

from __future__ import annotations

import hashlib
import os

import numpy as np

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.storage.config_store import get_active_embedding_spec

from src.services.search_preset_constants import PRESET_TYPE_MIXED
from src.services.search_preset_model import normalize_fusion, normalize_preset_record
from src.services.search_preset_storage import (
    _now_iso,
    get_preset_query_cache_root,
    query_cache_path,
    resolve_preset_ref_paths,
)

logger = get_logger("search_preset_query")


def _hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _preset_source_fingerprint(preset: dict, config=None) -> str:
    parts = []
    query = str(preset.get("query", "") or "").strip()
    if query:
        parts.append("text:" + hashlib.sha256(query.encode("utf-8")).hexdigest())
    for ref_path in resolve_preset_ref_paths(preset, config=config):
        stat = os.stat(ref_path)
        parts.append(f"img:{stat.st_size}:{stat.st_mtime_ns}:{_hash_file(ref_path)}")
    fusion = normalize_fusion(preset.get("fusion"))
    parts.append(f"fusion:{fusion['text_weight']:.4f}:{fusion['image_weight']:.4f}")
    return "|".join(parts) if parts else "empty"


def invalidate_preset_query_cache(preset_id: str, config=None) -> None:
    cache_path = query_cache_path(preset_id, config=config)
    if cache_path and os.path.isfile(cache_path):
        try:
            os.remove(cache_path)
        except OSError:
            logger.warning("Failed to remove preset query cache %s", cache_path)


def invalidate_all_preset_query_caches(preset_id: str, config=None) -> None:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return
    cache_root = get_preset_query_cache_root(config)
    if not os.path.isdir(cache_root):
        return
    for name in os.listdir(cache_root):
        cache_path = os.path.join(cache_root, name, f"{preset_id}.npy")
        if os.path.isfile(cache_path):
            try:
                os.remove(cache_path)
            except OSError:
                logger.warning("Failed to remove preset query cache %s", cache_path)


def _normalize_query_vector(vector) -> np.ndarray:
    import faiss

    query_vector = np.asarray(vector, dtype=np.float32)
    if query_vector.ndim == 1:
        query_vector = query_vector.reshape(1, -1)
    elif query_vector.ndim != 2 or query_vector.shape[0] != 1:
        raise RuntimeError("Preset query vector must be shape (1, dim)")
    faiss.normalize_L2(query_vector)
    return query_vector


def _load_cached_query_vector(preset: dict, config=None) -> np.ndarray | None:
    cache_path = query_cache_path(preset.get("id", ""), config=config)
    if not cache_path or not os.path.isfile(cache_path):
        return None
    try:
        payload = np.load(cache_path, allow_pickle=True).item()
    except Exception as exc:
        logger.warning("Failed to load preset query cache %s: %s", cache_path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    vector = payload.get("vector")
    if vector is None:
        return None
    expected_spec = get_active_embedding_spec(config=config)
    cached_spec = payload.get("embedding_spec")
    if not isinstance(cached_spec, dict):
        return None
    for key in ("model_id", "provider", "embedding_space", "dimension", "metric"):
        if str(cached_spec.get(key, "") or "") != str(expected_spec.get(key, "") or ""):
            return None
    if str(payload.get("source_fingerprint", "") or "") != _preset_source_fingerprint(preset, config=config):
        return None
    return _normalize_query_vector(vector)


def _save_cached_query_vector(preset: dict, vector: np.ndarray, config=None) -> None:
    cache_path = query_cache_path(preset.get("id", ""), config=config)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    from src.core.faiss_index import atomic_save_numpy

    payload = {
        "vector": _normalize_query_vector(vector),
        "embedding_spec": get_active_embedding_spec(config=config or load_config()),
        "source_fingerprint": _preset_source_fingerprint(preset, config=config),
        "source_type": PRESET_TYPE_MIXED,
        "cached_at": _now_iso(),
    }
    atomic_save_numpy(cache_path, payload)


def _encode_image_branch(ref_paths: list[str]) -> np.ndarray:
    from src.services.search_service import build_query_vector

    vectors = []
    for ref_path in ref_paths:
        vectors.append(build_query_vector(ref_path, is_text=False))
    if not vectors:
        raise RuntimeError("Preset reference images are missing")
    if len(vectors) == 1:
        return _normalize_query_vector(vectors[0])
    stacked = np.vstack([np.asarray(item, dtype=np.float32).reshape(1, -1) for item in vectors])
    mean_vector = stacked.mean(axis=0, keepdims=True).astype(np.float32)
    return _normalize_query_vector(mean_vector)


def _resolve_compose_ref_paths(source_image_paths) -> list[str]:
    paths = []
    for path in source_image_paths or []:
        cleaned = str(path or "").strip()
        if cleaned and os.path.isfile(cleaned):
            paths.append(cleaned)
    return paths


def encode_mixed_query_vector(
    *,
    query: str = "",
    source_image_paths=None,
    fusion=None,
    config=None,
) -> np.ndarray:
    from src.services.search_service import build_query_vector

    query = str(query or "").strip()
    ref_paths = _resolve_compose_ref_paths(source_image_paths)
    branches = []
    if query:
        branches.append(("text", _normalize_query_vector(build_query_vector(query, is_text=True))))
    if ref_paths:
        branches.append(("image", _encode_image_branch(ref_paths)))
    if not branches:
        raise RuntimeError("Compose query must include text and/or reference images")
    if len(branches) == 1:
        return branches[0][1]
    fusion = normalize_fusion(fusion)
    text_vector = next((vector for kind, vector in branches if kind == "text"), None)
    image_vector = next((vector for kind, vector in branches if kind == "image"), None)
    if text_vector is None or image_vector is None:
        return branches[0][1]
    merged = (
        fusion["text_weight"] * text_vector.reshape(1, -1)
        + fusion["image_weight"] * image_vector.reshape(1, -1)
    ).astype(np.float32)
    return _normalize_query_vector(merged)


def encode_preset_query_vector(preset: dict, config=None) -> np.ndarray:
    normalized = normalize_preset_record(preset)
    if not normalized:
        raise RuntimeError("Invalid preset record")
    return encode_mixed_query_vector(
        query=str(normalized.get("query", "") or "").strip(),
        source_image_paths=resolve_preset_ref_paths(normalized, config=config),
        fusion=normalized.get("fusion"),
        config=config,
    )


def resolve_preset_query_vector(preset: dict, config=None, *, force_refresh: bool = False) -> np.ndarray:
    normalized = normalize_preset_record(preset)
    if not normalized:
        raise RuntimeError("Invalid preset record")
    if not force_refresh:
        cached = _load_cached_query_vector(normalized, config=config)
        if cached is not None:
            return cached
    vector = encode_preset_query_vector(normalized, config=config)
    _save_cached_query_vector(normalized, vector, config=config)
    return vector
