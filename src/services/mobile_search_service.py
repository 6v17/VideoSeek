"""Parse and validate LAN mobile search requests."""

from __future__ import annotations

from typing import Any

from src.app.config import load_config
from src.services.search_preset_service import _normalize_fusion
from src.storage.config_store import (
    get_dialogue_search_scope_mode,
    get_image_search_mode,
    get_search_mode,
    get_search_scope_mode,
)

_VALID_KINDS = frozenset({"image", "text", "compose", "dialogue"})
_VALID_IMAGE_SEARCH_MODES = frozenset({"chunk", "frame", "video_discovery", "precise"})
_VALID_TEXT_SEARCH_MODES = frozenset({"frame", "chunk"})
_VALID_DIALOGUE_SEARCH_MODES = frozenset({"exact", "fuzzy"})
_MAX_COMPOSE_IMAGES = 12


def normalize_mobile_search_kind(raw: str) -> str:
    kind = str(raw or "image").strip().lower()
    if kind not in _VALID_KINDS:
        raise ValueError("search_kind must be one of: image, text, compose, dialogue.")
    return kind


def normalize_mobile_image_search_mode(raw: str, *, default: str = "frame") -> str:
    mode = str(raw or "").strip().lower()
    if not mode:
        mode = str(default or "frame").strip().lower()
    if mode not in _VALID_IMAGE_SEARCH_MODES:
        raise ValueError("image_search_mode must be one of: chunk, frame, video_discovery, precise.")
    return mode


def normalize_mobile_text_search_mode(raw: str, *, default: str = "frame") -> str:
    mode = str(raw or "").strip().lower()
    if not mode:
        mode = str(default or "frame").strip().lower()
    if mode == "chunk":
        return "chunk"
    if mode in _VALID_TEXT_SEARCH_MODES:
        return mode
    raise ValueError("search_mode must be one of: frame, chunk.")


def normalize_mobile_dialogue_search_mode(raw: str, *, default: str = "exact") -> str:
    mode = str(raw or "").strip().lower()
    if not mode:
        mode = str(default or "exact").strip().lower()
    if mode in {"fuzzy", "tolerant", "approx"}:
        return "fuzzy"
    if mode in _VALID_DIALOGUE_SEARCH_MODES:
        return mode
    raise ValueError("dialogue_search_mode must be one of: exact, fuzzy.")


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
    image_search_mode: str = "",
    search_mode: str = "",
    dialogue_search_mode: str = "",
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
    elif kind == "dialogue":
        if not has_text:
            raise ValueError("Subtitle search requires a query.")
        if has_image:
            raise ValueError("Subtitle search must not include an image.")
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
    if kind == "image" and str(image_search_mode or "").strip():
        payload["image_search_mode"] = normalize_mobile_image_search_mode(image_search_mode)
    # Text + compose share frame/chunk granularity.
    if kind in {"text", "compose"} and str(search_mode or "").strip():
        payload["search_mode"] = normalize_mobile_text_search_mode(search_mode)
    if kind == "dialogue":
        # Prefer dedicated field; allow legacy search_mode=exact|fuzzy from older clients.
        raw_dialogue_mode = str(dialogue_search_mode or search_mode or "").strip()
        if raw_dialogue_mode:
            payload["dialogue_search_mode"] = normalize_mobile_dialogue_search_mode(raw_dialogue_mode)
    return payload


def get_mobile_search_defaults(config=None) -> dict[str, Any]:
    cfg = config or load_config()
    text_mode = str(get_search_mode(cfg) or "frame").strip().lower()
    if text_mode not in _VALID_TEXT_SEARCH_MODES:
        text_mode = "frame"
    image_mode = str(get_image_search_mode(cfg) or "frame").strip().lower()
    if image_mode not in _VALID_IMAGE_SEARCH_MODES:
        image_mode = "frame"
    precision = "precise" if image_mode == "precise" else "fast"
    scope_mode = str(get_search_scope_mode(cfg) or "all").strip().lower()
    dialogue_scope_mode = str(get_dialogue_search_scope_mode(cfg) or "all").strip().lower()
    from src.app.i18n import get_texts

    language = str(cfg.get("language", "zh") or "zh")
    texts = get_texts(language)
    return {
        "ok": True,
        "language": language,
        "search_mode": text_mode,
        "image_search_mode": image_mode,
        "dialogue_search_mode": "exact",
        "search_precision_default": precision,
        "scope_mode": scope_mode,
        "dialogue_scope_mode": dialogue_scope_mode,
        "max_compose_images": _MAX_COMPOSE_IMAGES,
        "image_search_modes": [
            {
                "id": "chunk",
                "label": texts.get("search_image_mode_chunk", "Chunk"),
            },
            {
                "id": "frame",
                "label": texts.get("search_image_mode_frame", "Frame"),
            },
            {
                "id": "video_discovery",
                "label": texts.get("search_image_mode_video_discovery", "Best per video"),
            },
            {
                "id": "precise",
                "label": texts.get("search_image_mode_precise", "Deep search"),
            },
        ],
        "text_search_modes": [
            {
                "id": "frame",
                "label": texts.get("setting_search_mode_frame", "Frame"),
            },
            {
                "id": "chunk",
                "label": texts.get("setting_search_mode_chunk", "Chunk"),
            },
        ],
        "dialogue_search_modes": [
            {
                "id": "exact",
                "label": texts.get("search_dialogue_match_exact", "Exact"),
            },
            {
                "id": "fuzzy",
                "label": texts.get("search_dialogue_match_fuzzy", "Fuzzy"),
            },
        ],
        "labels": {
            "tab_image": texts.get("search_tab_image", "Image"),
            "tab_text": texts.get("search_tab_text", "Text"),
            "tab_compose": texts.get("search_tab_compose", "Compose"),
            "tab_dialogue": texts.get("search_tab_dialogue", "Subtitles"),
            "description_hint": texts.get("search_presets_field_description_hint", ""),
            "dialogue_hint": texts.get(
                "search_dialogue_match_exact_hint",
                texts.get("search_empty_dialogue", "Enter subtitle keywords"),
            ),
            "add_images": texts.get("search_presets_add_images", "Add images"),
            "remove_selected": texts.get("search_presets_remove_selected", "Delete selected"),
            "remove_selected_empty": texts.get("search_presets_remove_selected_empty", ""),
            "fusion_title": texts.get("search_presets_fusion_title", "Text / image balance"),
            "fusion_hint": texts.get("search_presets_fusion_hint", ""),
            "fusion_text": texts.get("search_presets_fusion_text", "Text"),
            "fusion_image": texts.get("search_presets_fusion_image", "Image"),
            "fusion_value": texts.get("search_presets_fusion_value", "Text {text}% · Image {image}%"),
            "image_drop_hint": texts.get("image_drop_hint", "Drop an image here"),
            "image_mode_label": texts.get("search_image_mode_label", "Image mode"),
            "text_mode_label": texts.get("setting_search_mode", "Search mode"),
            "dialogue_mode_label": texts.get("search_dialogue_match_label", "Match mode"),
            "scope_all": texts.get("search_scope_all_short", texts.get("search_scope_all", "All")),
            "scope_selected": texts.get("search_scope_selected_short", "Selected"),
        },
    }
