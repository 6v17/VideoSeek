"""Shared constants for search preset records."""

from __future__ import annotations

PRESET_SCHEMA_VERSION = 3
PRESET_TYPE_MIXED = "mixed"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
DEFAULT_FUSION = {"text_weight": 0.5, "image_weight": 0.5}

BUILTIN_SEARCH_PRESETS: tuple[dict[str, str], ...] = (
    {"id": "builtin_smile", "name": "开心", "query": "a person with a big smile"},
    {"id": "builtin_angry", "name": "愤怒", "query": "a person with an angry face"},
    {
        "id": "builtin_crying",
        "name": "哭泣",
        "query": "a person with a sad, crying expression, tears on cheeks",
    },
    {"id": "builtin_battle", "name": "战斗", "query": "a person fighting in a battle"},
    {"id": "builtin_landscape", "name": "风景", "query": "beautiful landscape"},
)
BUILTIN_SEARCH_PRESET_IDS = frozenset(spec["id"] for spec in BUILTIN_SEARCH_PRESETS)
