"""Shared mixed search presets with per-model-profile query vector caches."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any

import faiss
import numpy as np

from src.app.config import get_configured_data_root, load_config
from src.app.logging_utils import get_logger
from src.core.faiss_index import atomic_save_numpy
from src.storage.config_store import (
    get_active_embedding_spec,
    get_active_model_profile,
    get_search_mode,
    get_search_top_k,
)

logger = get_logger("search_preset_service")

PRESET_SCHEMA_VERSION = 3
PRESET_TYPE_MIXED = "mixed"
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_DEFAULT_FUSION = {"text_weight": 0.5, "image_weight": 0.5}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_active_profile_id(config=None) -> str:
    profile = get_active_model_profile(config=config or load_config())
    profile_id = str(profile.get("id", "") or "").strip()
    if not profile_id:
        raise RuntimeError("Missing active model profile")
    return profile_id


def get_search_presets_base_dir(config=None) -> str:
    cfg = config or load_config()
    return os.path.join(get_configured_data_root(cfg), "data", "search_presets")


def get_search_preset_root(config=None) -> str:
    """Shared preset storage root (presets.json + refs/)."""
    return get_search_presets_base_dir(config)


def get_presets_file(config=None) -> str:
    return os.path.join(get_search_preset_root(config), "presets.json")


def get_preset_refs_dir(config=None) -> str:
    return os.path.join(get_search_preset_root(config), "refs")


def get_preset_query_cache_root(config=None) -> str:
    return os.path.join(get_search_presets_base_dir(config), "query_cache")


def get_preset_query_cache_dir(config=None) -> str:
    profile_id = get_active_profile_id(config)
    return os.path.join(get_preset_query_cache_root(config), profile_id)


def _query_cache_path(preset_id: str, config=None, *, profile_id: str | None = None) -> str:
    preset_id = str(preset_id or "").strip()
    cache_dir = (
        os.path.join(get_preset_query_cache_root(config), profile_id)
        if profile_id
        else get_preset_query_cache_dir(config)
    )
    return os.path.join(cache_dir, f"{preset_id}.npy")


def _resolve_ref_rel_path(ref_file: str, config=None) -> str:
    ref_file = str(ref_file or "").strip()
    if not ref_file:
        return ""
    if os.path.isabs(ref_file):
        return ref_file
    return os.path.join(get_search_preset_root(config), ref_file.replace("/", os.sep))


def resolve_preset_ref_paths(preset: dict, config=None) -> list[str]:
    paths = []
    for ref_file in list((preset or {}).get("ref_files") or []):
        resolved = _resolve_ref_rel_path(ref_file, config=config)
        if resolved and os.path.isfile(resolved):
            paths.append(resolved)
    if paths:
        return paths
    legacy = _resolve_ref_rel_path((preset or {}).get("ref_file", ""), config=config)
    if legacy and os.path.isfile(legacy):
        return [legacy]
    return []


def get_preset_ref_path(preset: dict, config=None) -> str:
    paths = resolve_preset_ref_paths(preset, config=config)
    return paths[0] if paths else ""


def _atomic_write_json(path: str, payload: dict) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _empty_document() -> dict:
    return {
        "version": PRESET_SCHEMA_VERSION,
        "presets": [],
    }


def _read_presets_payload(path: str) -> dict:
    if not os.path.isfile(path):
        return _empty_document()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        logger.warning("Failed to read search presets file %s: %s", path, exc)
        return _empty_document()
    if not isinstance(payload, dict):
        return _empty_document()
    presets = payload.get("presets")
    if not isinstance(presets, list):
        presets = []
    return {
        "version": int(payload.get("version", PRESET_SCHEMA_VERSION) or PRESET_SCHEMA_VERSION),
        "presets": [item for item in presets if isinstance(item, dict)],
    }


def load_presets_document(config=None) -> dict:
    cfg = config or load_config()
    return _read_presets_payload(get_presets_file(cfg))


def save_presets_document(document: dict, config=None) -> None:
    payload = dict(document or {})
    payload["version"] = PRESET_SCHEMA_VERSION
    presets = payload.get("presets")
    if not isinstance(presets, list):
        presets = []
    payload["presets"] = presets
    payload.pop("model_profile_id", None)
    _atomic_write_json(get_presets_file(config), payload)


def _normalize_fusion(raw) -> dict:
    fusion = dict(_DEFAULT_FUSION)
    if isinstance(raw, dict):
        for key in ("text_weight", "image_weight"):
            try:
                fusion[key] = float(raw.get(key, fusion[key]))
            except (TypeError, ValueError):
                pass
    total = float(fusion["text_weight"]) + float(fusion["image_weight"])
    if total <= 0:
        return dict(_DEFAULT_FUSION)
    return {
        "text_weight": float(fusion["text_weight"]) / total,
        "image_weight": float(fusion["image_weight"]) / total,
    }


def _collect_ref_files(raw: dict) -> list[str]:
    ref_files = []
    for ref_file in list((raw or {}).get("ref_files") or []):
        normalized = str(ref_file or "").strip()
        if normalized:
            ref_files.append(normalized)
    if ref_files:
        return ref_files
    legacy = str((raw or {}).get("ref_file", "") or "").strip()
    if legacy:
        return [legacy]
    return []


def preset_has_content(preset: dict) -> bool:
    query = str((preset or {}).get("query", "") or "").strip()
    ref_files = _collect_ref_files(preset)
    return bool(query or ref_files)


def normalize_preset_record(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    preset_id = str(raw.get("id", "") or "").strip()
    name = str(raw.get("name", "") or "").strip()
    if not preset_id or not name:
        return None
    library_paths = [
        str(path or "").strip()
        for path in (raw.get("library_paths") or [])
        if str(path or "").strip()
    ]
    video_paths = [
        str(path or "").strip()
        for path in (raw.get("video_paths") or [])
        if str(path or "").strip()
    ]
    ui = raw.get("ui") if isinstance(raw.get("ui"), dict) else {}
    top_k = raw.get("top_k")
    min_score = raw.get("min_score")
    try:
        top_k_value = int(top_k) if top_k is not None else None
    except (TypeError, ValueError):
        top_k_value = None
    try:
        min_score_value = float(min_score) if min_score is not None else None
    except (TypeError, ValueError):
        min_score_value = None
    mode = str(raw.get("mode", "") or "").strip().lower() or None
    if mode not in {None, "frame", "chunk"}:
        mode = None
    preset = {
        "id": preset_id,
        "type": PRESET_TYPE_MIXED,
        "name": name,
        "query": str(raw.get("query", "") or "").strip(),
        "ref_files": _collect_ref_files(raw),
        "fusion": _normalize_fusion(raw.get("fusion")),
        "library_paths": library_paths,
        "video_paths": video_paths,
        "mode": mode,
        "top_k": top_k_value,
        "min_score": min_score_value,
        "ui": dict(ui),
        "created_at": str(raw.get("created_at", "") or "").strip(),
        "updated_at": str(raw.get("updated_at", "") or "").strip(),
    }
    if not preset_has_content(preset):
        return None
    return preset


def list_presets(config=None) -> list[dict]:
    document = load_presets_document(config=config)
    presets = []
    for item in document.get("presets", []):
        normalized = normalize_preset_record(item)
        if normalized:
            presets.append(normalized)
    return presets


def get_preset(preset_id: str, config=None) -> dict | None:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return None
    for preset in list_presets(config=config):
        if str(preset.get("id", "") or "").strip() == preset_id:
            return dict(preset)
    return None


def _sanitize_preset_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "").strip())
    if not cleaned:
        raise ValueError("Preset name is required")
    if len(cleaned) > 64:
        cleaned = cleaned[:64].strip()
    return cleaned


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
    fusion = _normalize_fusion(preset.get("fusion"))
    parts.append(f"fusion:{fusion['text_weight']:.4f}:{fusion['image_weight']:.4f}")
    return "|".join(parts) if parts else "empty"


def invalidate_preset_query_cache(preset_id: str, config=None) -> None:
    cache_path = _query_cache_path(preset_id, config=config)
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
    query_vector = np.asarray(vector, dtype=np.float32)
    if query_vector.ndim == 1:
        query_vector = query_vector.reshape(1, -1)
    elif query_vector.ndim != 2 or query_vector.shape[0] != 1:
        raise RuntimeError("Preset query vector must be shape (1, dim)")
    faiss.normalize_L2(query_vector)
    return query_vector


def _load_cached_query_vector(preset: dict, config=None) -> np.ndarray | None:
    cache_path = _query_cache_path(preset.get("id", ""), config=config)
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
    cache_path = _query_cache_path(preset.get("id", ""), config=config)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
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


def _encode_preset_query_vector(preset: dict, config=None) -> np.ndarray:
    from src.services.search_service import build_query_vector

    normalized = normalize_preset_record(preset)
    if not normalized:
        raise RuntimeError("Invalid preset record")
    query = str(normalized.get("query", "") or "").strip()
    ref_paths = resolve_preset_ref_paths(normalized, config=config)
    branches = []
    if query:
        branches.append(("text", _normalize_query_vector(build_query_vector(query, is_text=True))))
    if ref_paths:
        branches.append(("image", _encode_image_branch(ref_paths)))
    if not branches:
        raise RuntimeError("Preset must include query text and/or reference images")
    if len(branches) == 1:
        return branches[0][1]
    fusion = _normalize_fusion(normalized.get("fusion"))
    text_vector = next((vector for kind, vector in branches if kind == "text"), None)
    image_vector = next((vector for kind, vector in branches if kind == "image"), None)
    if text_vector is None or image_vector is None:
        return branches[0][1]
    merged = (
        fusion["text_weight"] * text_vector.reshape(1, -1)
        + fusion["image_weight"] * image_vector.reshape(1, -1)
    ).astype(np.float32)
    return _normalize_query_vector(merged)


def resolve_preset_query_vector(preset: dict, config=None, *, force_refresh: bool = False) -> np.ndarray:
    normalized = normalize_preset_record(preset)
    if not normalized:
        raise RuntimeError("Invalid preset record")
    if not force_refresh:
        cached = _load_cached_query_vector(normalized, config=config)
        if cached is not None:
            return cached
    vector = _encode_preset_query_vector(normalized, config=config)
    _save_cached_query_vector(normalized, vector, config=config)
    return vector


def _copy_reference_image(source_path: str, preset_id: str, index: int, config=None) -> str:
    source_path = str(source_path or "").strip()
    if not source_path or not os.path.isfile(source_path):
        raise ValueError("Reference image is unreadable")
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in _IMAGE_EXTENSIONS:
        ext = ".jpg"
    refs_dir = get_preset_refs_dir(config)
    os.makedirs(refs_dir, exist_ok=True)
    dest_path = os.path.join(refs_dir, f"{preset_id}_{index}{ext}")
    shutil.copy2(source_path, dest_path)
    return f"refs/{preset_id}_{index}{ext}"


def _copy_reference_images(source_paths, preset_id: str, config=None) -> list[str]:
    ref_files = []
    for index, source_path in enumerate(list(source_paths or [])):
        path = str(source_path or "").strip()
        if not path:
            continue
        ref_files.append(_copy_reference_image(path, preset_id, index, config=config))
    return ref_files


def _same_reference_paths(left, right) -> bool:
    left_norm = [os.path.normcase(os.path.normpath(str(path or "").strip())) for path in left if str(path or "").strip()]
    right_norm = [os.path.normcase(os.path.normpath(str(path or "").strip())) for path in right if str(path or "").strip()]
    return left_norm == right_norm


def _remove_preset_reference_files(preset: dict, config=None) -> None:
    for ref_path in resolve_preset_ref_paths(preset, config=config):
        if os.path.isfile(ref_path):
            try:
                os.remove(ref_path)
            except OSError:
                logger.warning("Failed to remove preset reference image %s", ref_path)


def _remove_preset_assets(preset: dict, config=None) -> None:
    preset_id = str(preset.get("id", "") or "").strip()
    if preset_id:
        invalidate_all_preset_query_caches(preset_id, config=config)
    _remove_preset_reference_files(preset, config=config)


def _validate_mixed_content(query: str, source_image_paths) -> None:
    query = str(query or "").strip()
    image_paths = [str(path or "").strip() for path in (source_image_paths or []) if str(path or "").strip()]
    if not query and not image_paths:
        raise ValueError("Preset requires query text and/or at least one reference image")


def create_preset(
    *,
    name: str,
    query: str = "",
    source_image_paths=None,
    library_paths=None,
    video_paths=None,
    mode: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    fusion: dict | None = None,
    ui: dict | None = None,
    config=None,
) -> dict:
    query = str(query or "").strip()
    image_paths = [str(path or "").strip() for path in (source_image_paths or []) if str(path or "").strip()]
    _validate_mixed_content(query, image_paths)
    preset_id = uuid.uuid4().hex[:12]
    now = _now_iso()
    ref_files = _copy_reference_images(image_paths, preset_id, config=config)
    preset = normalize_preset_record(
        {
            "id": preset_id,
            "type": PRESET_TYPE_MIXED,
            "name": _sanitize_preset_name(name),
            "query": query,
            "ref_files": ref_files,
            "fusion": _normalize_fusion(fusion),
            "library_paths": list(library_paths or []),
            "video_paths": list(video_paths or []),
            "mode": mode,
            "top_k": top_k,
            "min_score": min_score,
            "ui": dict(ui or {}),
            "created_at": now,
            "updated_at": now,
        }
    )
    if not preset:
        raise RuntimeError("Failed to normalize preset record")
    document = load_presets_document(config=config)
    document.setdefault("presets", []).append(preset)
    save_presets_document(document, config=config)
    resolve_preset_query_vector(preset, config=config, force_refresh=True)
    return dict(preset)


def update_preset(
    preset_id: str,
    *,
    name: str | None = None,
    query: str | None = None,
    source_image_paths=None,
    replace_reference_images: bool = False,
    library_paths=None,
    video_paths=None,
    mode: str | None = None,
    top_k: int | None = None,
    min_score: float | None = None,
    fusion: dict | None = None,
    ui: dict | None = None,
    config=None,
) -> dict:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        raise ValueError("Preset id is required")
    document = load_presets_document(config=config)
    presets = document.get("presets", [])
    updated = None
    for index, item in enumerate(presets):
        if str(item.get("id", "") or "").strip() != preset_id:
            continue
        current = normalize_preset_record(item) or {}
        if name is not None:
            current["name"] = _sanitize_preset_name(name)
        if query is not None:
            current["query"] = str(query or "").strip()
        if fusion is not None:
            current["fusion"] = _normalize_fusion(fusion)
        if source_image_paths is not None:
            new_paths = [str(path or "").strip() for path in source_image_paths if str(path or "").strip()]
            if replace_reference_images:
                existing_paths = resolve_preset_ref_paths(current, config=config)
                if _same_reference_paths(existing_paths, new_paths):
                    pass
                else:
                    _remove_preset_reference_files(current, config=config)
                    current["ref_files"] = _copy_reference_images(new_paths, preset_id, config=config)
            elif new_paths:
                start_index = len(current.get("ref_files") or [])
                appended = []
                for offset, path in enumerate(new_paths):
                    appended.append(_copy_reference_image(path, preset_id, start_index + offset, config=config))
                current["ref_files"] = list(current.get("ref_files") or []) + appended
        if library_paths is not None:
            current["library_paths"] = [str(path or "").strip() for path in library_paths if str(path or "").strip()]
        if video_paths is not None:
            current["video_paths"] = [str(path or "").strip() for path in video_paths if str(path or "").strip()]
        if mode is not None:
            current["mode"] = str(mode or "").strip().lower() or None
        if top_k is not None:
            current["top_k"] = int(top_k)
        if min_score is not None:
            current["min_score"] = float(min_score)
        if ui is not None:
            current["ui"] = dict(ui)
        if not preset_has_content(current):
            raise ValueError("Preset requires query text and/or at least one reference image")
        current["updated_at"] = _now_iso()
        updated = normalize_preset_record(current)
        if not updated:
            raise RuntimeError("Failed to normalize updated preset")
        presets[index] = updated
        break
    if updated is None:
        raise KeyError(preset_id)
    save_presets_document(document, config=config)
    invalidate_all_preset_query_caches(preset_id, config=config)
    resolve_preset_query_vector(updated, config=config, force_refresh=True)
    return dict(updated)


def delete_preset(preset_id: str, config=None) -> bool:
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        return False
    document = load_presets_document(config=config)
    presets = document.get("presets", [])
    kept = []
    removed = None
    for item in presets:
        if str(item.get("id", "") or "").strip() == preset_id:
            removed = normalize_preset_record(item)
            continue
        kept.append(item)
    if removed is None:
        return False
    _remove_preset_assets(removed, config=config)
    document["presets"] = kept
    save_presets_document(document, config=config)
    return True


def describe_preset_content(preset: dict, config=None) -> str:
    preset = dict(preset or {})
    parts = []
    query = str(preset.get("query", "") or "").strip()
    if query:
        parts.append(query)
    ref_count = len(resolve_preset_ref_paths(preset, config=config))
    if ref_count:
        parts.append(f"[{ref_count} image(s)]")
    if query and ref_count:
        fusion = _normalize_fusion(preset.get("fusion"))
        text_pct = int(round(float(fusion["text_weight"]) * 100))
        image_pct = 100 - text_pct
        parts.append(f"({text_pct}:{image_pct})")
    return " + ".join(parts) if parts else ""


def build_preset_search_plan(preset_id: str, config=None) -> dict[str, Any]:
    preset = get_preset(preset_id, config=config)
    if preset is None:
        raise KeyError(f"Preset not found: {preset_id}")
    cfg = config or load_config()
    query_vector = resolve_preset_query_vector(preset, config=cfg)
    mode = get_search_mode(cfg)
    top_k = preset.get("top_k")
    if top_k is None:
        top_k = get_search_top_k(cfg)
    query = str(preset.get("query", "") or "").strip()
    ref_paths = resolve_preset_ref_paths(preset, config=cfg)
    return {
        "preset": preset,
        "query_vector": query_vector,
        "search_mode": mode,
        "top_k": int(top_k),
        "min_score": preset.get("min_score"),
        "scope_library_paths": None,
        "scope_video_paths": None,
        "is_text": bool(query) and not ref_paths,
        "query_data": query or (ref_paths[0] if ref_paths else ""),
    }
