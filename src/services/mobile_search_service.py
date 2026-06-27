"""Parse and validate LAN mobile search requests."""

from __future__ import annotations

from typing import Any

from src.app.config import load_config
from src.services.search_preset_service import _normalize_fusion
from src.storage.config_store import get_search_mode, get_search_precision_mode, get_search_scope_mode

_VALID_KINDS = frozenset({"image", "text", "compose"})
_MAX_COMPOSE_IMAGES = 12


def normalize_mobile_search_kind(raw: str) -> str:
    kind = str(raw or "image").strip().lower()
    if kind not in _VALID_KINDS:
        raise ValueError("search_kind must be one of: image, text, compose.")
    return kind


def normalize_mobile_image_paths(image_paths=None, *, image_path: str = "") -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw in list(image_paths or []):
        cleaned = str(raw or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        paths.append(cleaned)
    legacy = str(image_path or "").strip()
    if legacy and legacy not in seen:
        paths.insert(0, legacy)
    return paths


def parse_mobile_fusion(text_weight_raw: str, *, has_text: bool, has_image: bool) -> dict[str, float] | None:
    if not (has_text and has_image):
        return None
    raw = str(text_weight_raw or "").strip()
    if not raw:
        return _normalize_fusion(None)
    try:
        text_pct = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("text_weight must be an integer between 0 and 100.") from exc
    text_pct = max(0, min(100, text_pct))
    text_weight = text_pct / 100.0
    return _normalize_fusion(
        {
            "text_weight": text_weight,
            "image_weight": 1.0 - text_weight,
        }
    )


def build_mobile_search_payload(
    *,
    search_kind: str,
    query: str = "",
    image_paths=None,
    image_path: str = "",
    fusion: dict[str, float] | None = None,
    source: str = "",
) -> dict[str, Any]:
    kind = normalize_mobile_search_kind(search_kind)
    cleaned_query = str(query or "").strip()
    paths = normalize_mobile_image_paths(image_paths, image_path=image_path)
    has_text = bool(cleaned_query)
    has_image = bool(paths)

    if kind == "image":
        if not has_image:
            raise ValueError("Image search requires an uploaded image.")
        if len(paths) > 1:
            raise ValueError("Image search supports only one image.")
    elif kind == "text":
        if not has_text:
            raise ValueError("Text search requires a query.")
        if has_image:
            raise ValueError("Text search must not include an image.")
    else:
        if not has_text and not has_image:
            raise ValueError("Compose search requires text and/or images.")
        if len(paths) > _MAX_COMPOSE_IMAGES:
            raise ValueError(f"Compose search supports up to {_MAX_COMPOSE_IMAGES} images.")

    payload: dict[str, Any] = {
        "search_kind": kind,
        "query": cleaned_query,
        "image_paths": paths,
        "image_path": paths[0] if len(paths) == 1 else "",
        "fusion": fusion if kind == "compose" else None,
        "source": str(source or "").strip(),
    }
    return payload


def get_mobile_search_defaults(config=None) -> dict[str, Any]:
    cfg = config or load_config()
    mode = str(get_search_mode(cfg) or "frame").strip().lower()
    precision = str(get_search_precision_mode(cfg) or "fast").strip().lower()
    scope_mode = str(get_search_scope_mode(cfg) or "all").strip().lower()
    mode_label = "chunk" if mode == "chunk" else "frame"
    from src.app.i18n import get_texts

    language = str(cfg.get("language", "zh") or "zh")
    texts = get_texts(language)
    return {
        "ok": True,
        "language": language,
        "search_mode": mode_label,
        "search_precision_default": "precise" if precision == "precise" else "fast",
        "scope_mode": scope_mode,
        "max_compose_images": _MAX_COMPOSE_IMAGES,
        "labels": {
            "tab_image": texts.get("search_tab_image", "Image"),
            "tab_text": texts.get("search_tab_text", "Text"),
            "tab_compose": texts.get("search_tab_compose", "Compose"),
            "description_hint": texts.get("search_presets_field_description_hint", ""),
            "add_images": texts.get("search_presets_add_images", "Add images"),
            "remove_selected": texts.get("search_presets_remove_selected", "Delete selected"),
            "remove_selected_empty": texts.get("search_presets_remove_selected_empty", ""),
            "fusion_title": texts.get("search_presets_fusion_title", "Text / image balance"),
            "fusion_hint": texts.get("search_presets_fusion_hint", ""),
            "fusion_text": texts.get("search_presets_fusion_text", "Text"),
            "fusion_image": texts.get("search_presets_fusion_image", "Image"),
            "fusion_value": texts.get("search_presets_fusion_value", "Text {text}% · Image {image}%"),
            "image_drop_hint": texts.get("image_drop_hint", "Drop an image here"),
        },
    }
