"""Build search execution plans from presets or compose inputs."""

from __future__ import annotations

from typing import Any

from src.app.config import load_config
from src.services.search_preset_model import get_preset
from src.services.search_preset_query import (
    _resolve_compose_ref_paths,
    encode_mixed_query_vector,
    resolve_preset_query_vector,
)
from src.services.search_preset_storage import resolve_preset_ref_paths
from src.storage.config_store import get_search_mode, get_search_top_k


def _resolve_preset_video_scope(preset: dict, config=None) -> list[str] | None:
    from src.services.search_scope import normalize_scope_path, resolve_active_search_video_scope

    raw_paths = preset.get("video_paths") or []
    if raw_paths:
        paths = [normalize_scope_path(path) for path in raw_paths if str(path or "").strip()]
        return paths or None
    return resolve_active_search_video_scope(config=config)


def build_compose_search_plan(
    *,
    query: str = "",
    source_image_paths=None,
    fusion=None,
    config=None,
) -> dict[str, Any]:
    cfg = config or load_config()
    query = str(query or "").strip()
    ref_paths = _resolve_compose_ref_paths(source_image_paths)
    if not query and not ref_paths:
        raise ValueError("Compose query must include text and/or reference images")
    query_vector = encode_mixed_query_vector(
        query=query,
        source_image_paths=ref_paths,
        fusion=fusion,
        config=cfg,
    )
    mode = get_search_mode(cfg)
    top_k = get_search_top_k(cfg)
    return {
        "query_vector": query_vector,
        "search_mode": mode,
        "top_k": int(top_k),
        "min_score": None,
        "is_text": bool(query) and not ref_paths,
        "has_image": bool(ref_paths),
        "query_data": query or (ref_paths[0] if ref_paths else ""),
        "pixel_query_data": ref_paths[0] if ref_paths else None,
    }


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
        "scope_video_paths": _resolve_preset_video_scope(preset, config=cfg),
        "is_text": bool(query) and not ref_paths,
        "has_image": bool(ref_paths),
        "query_data": query or (ref_paths[0] if ref_paths else ""),
        "pixel_query_data": ref_paths[0] if ref_paths else None,
    }
