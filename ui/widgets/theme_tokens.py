"""Load Figma-exported theme tokens from resources/tokens_*.json."""

from __future__ import annotations

import json
import os
from pathlib import Path


def _figma_key_to_token(key: str) -> str:
    return str(key or "").strip().replace("-", "_").upper()


def load_figma_color_tokens(path: Path | str | None) -> dict[str, str]:
    """Parse `resources/tokens_dark.json` / `tokens_light.json` shape from Figma."""
    if not path:
        return {}
    token_path = Path(path)
    if not token_path.is_file():
        return {}
    try:
        payload = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    colors = (
        payload.get("videoseek", {})
        .get("theme", {})
        .get("color", {})
    )
    if not isinstance(colors, dict):
        return {}

    return {
        _figma_key_to_token(key): str(value).strip()
        for key, value in colors.items()
        if str(value or "").strip()
    }


def merge_theme_colors(base: dict[str, str], figma_override: dict[str, str]) -> dict[str, str]:
    """Figma tokens override defaults; unspecified keys keep built-in fallbacks."""
    merged = dict(base)
    for key, value in figma_override.items():
        merged[key] = value
    return merged


def theme_colors_path(is_dark: bool) -> Path:
    from src.infra.paths import get_resource_path

    name = "tokens_dark.json" if is_dark else "tokens_light.json"
    return Path(get_resource_path(os.path.join("resources", name)))


def load_merged_theme_colors(is_dark: bool, base: dict[str, str]) -> dict[str, str]:
    figma = load_figma_color_tokens(theme_colors_path(is_dark))
    return merge_theme_colors(base, figma)
