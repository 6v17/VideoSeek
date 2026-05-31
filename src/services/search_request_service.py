"""Shared search request normalization for GUI, workers, and Agent API."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from src.app.config import DEFAULT_CONFIG, load_config


def default_agent_image_precision_mode(config=None) -> str:
    cfg = config or load_config()
    value = str(
        cfg.get("agent_api_default_image_precision", DEFAULT_CONFIG["agent_api_default_image_precision"])
    ).strip().lower()
    return value if value in {"fast", "precise"} else "fast"


def normalize_search_precision_mode(
    mode: Optional[str],
    *,
    is_text: bool,
    has_image: bool,
    config=None,
    use_agent_default: bool = False,
) -> str:
    """Resolve fast/precise for image-capable queries. Text-only is always fast."""
    if is_text and not has_image:
        return "fast"
    if mode is None and has_image and use_agent_default:
        mode = default_agent_image_precision_mode(config)
    normalized = str(mode or "fast").strip().lower()
    if normalized not in {"fast", "precise"}:
        normalized = "fast"
    return normalized


def validate_inline_image_query(query: str) -> None:
    path = str(query or "").strip()
    if not os.path.isfile(path):
        raise ValueError(f"image_path does not exist: {query}")


def resolve_search_query_inputs(
    *,
    preset_id: Optional[str] = None,
    query: Optional[str] = None,
    query_type: str = "text",
    config=None,
) -> Dict[str, Any]:
    """Resolve preset or inline query fields shared by GUI preset chip and Agent API."""
    cfg = config or load_config()
    preset_id = str(preset_id or "").strip()
    query = str(query or "").strip()
    if preset_id and query:
        raise ValueError("Provide either preset_id or query, not both.")
    if not preset_id and not query:
        raise ValueError("Provide preset_id or query.")

    if preset_id:
        from src.services.search_preset_service import build_preset_search_plan

        try:
            plan = build_preset_search_plan(preset_id, config=cfg)
        except KeyError as exc:
            raise ValueError(str(exc)) from exc
        preset = dict(plan.get("preset") or {})
        is_text = bool(plan.get("is_text"))
        return {
            "preset": preset,
            "preset_id": preset_id,
            "query_data": plan.get("query_data"),
            "query_label": str(preset.get("name") or preset_id),
            "query_type": "text" if is_text else "image_path",
            "is_text": is_text,
            "has_image": bool(plan.get("has_image")),
            "query_vector": plan.get("query_vector"),
            "pixel_query_data": plan.get("pixel_query_data"),
            "default_top_k": plan.get("top_k"),
            "default_min_score": plan.get("min_score"),
            "preset_scope_video_paths": plan.get("scope_video_paths"),
        }

    normalized_type = str(query_type or "text").strip().lower()
    if normalized_type not in {"text", "image_path"}:
        raise ValueError("query_type must be 'text' or 'image_path'")
    is_text = normalized_type == "text"
    if not is_text:
        validate_inline_image_query(query)
    return {
        "preset": None,
        "preset_id": None,
        "query_data": query,
        "query_label": query,
        "query_type": normalized_type,
        "is_text": is_text,
        "has_image": not is_text,
        "query_vector": None,
        "pixel_query_data": None,
        "default_top_k": None,
        "default_min_score": None,
        "preset_scope_video_paths": None,
    }
