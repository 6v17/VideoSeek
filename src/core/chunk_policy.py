"""Named chunk segmentation presets mapped to app config fields."""

from __future__ import annotations

from typing import Any, Mapping

CHUNK_POLICY_BALANCED = "balanced"
CHUNK_POLICY_SENSITIVE = "sensitive"
CHUNK_POLICY_STABLE = "stable"
CHUNK_POLICY_CUSTOM = "custom"

SUPPORTED_CHUNK_POLICIES = {
    CHUNK_POLICY_BALANCED,
    CHUNK_POLICY_SENSITIVE,
    CHUNK_POLICY_STABLE,
    CHUNK_POLICY_CUSTOM,
}

DEFAULT_CHUNK_POLICY = CHUNK_POLICY_BALANCED

# Fields owned by a chunk policy preset (expanded into config.json on save).
CHUNK_POLICY_CONFIG_KEYS = (
    "similarity_threshold",
    "min_chunk_duration",
    "min_chunk_size",
)

CHUNK_POLICY_PRESETS: dict[str, dict[str, Any]] = {
    CHUNK_POLICY_BALANCED: {
        "similarity_threshold": 0.85,
        "min_chunk_duration": 0.0,
        "min_chunk_size": 2,
    },
    CHUNK_POLICY_SENSITIVE: {
        "similarity_threshold": 0.88,
        "min_chunk_duration": 0.0,
        "min_chunk_size": 2,
    },
    CHUNK_POLICY_STABLE: {
        "similarity_threshold": 0.80,
        "min_chunk_duration": 0.0,
        "min_chunk_size": 2,
    },
}


def normalize_chunk_policy_id(policy_id: str | None) -> str:
    value = str(policy_id or DEFAULT_CHUNK_POLICY).strip().lower()
    return value if value in SUPPORTED_CHUNK_POLICIES else DEFAULT_CHUNK_POLICY


def list_selectable_chunk_policies() -> list[str]:
    return [CHUNK_POLICY_BALANCED, CHUNK_POLICY_SENSITIVE, CHUNK_POLICY_STABLE, CHUNK_POLICY_CUSTOM]


def resolve_chunk_policy_values(policy_id: str | None) -> dict[str, Any] | None:
    normalized = normalize_chunk_policy_id(policy_id)
    if normalized == CHUNK_POLICY_CUSTOM:
        return None
    preset = CHUNK_POLICY_PRESETS.get(normalized)
    return dict(preset) if preset else None


def chunk_policy_values_from_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    from src.app.config import DEFAULT_CONFIG

    cfg = config or {}
    values: dict[str, Any] = {}
    for key in CHUNK_POLICY_CONFIG_KEYS:
        values[key] = cfg.get(key, DEFAULT_CONFIG.get(key))
    return values


def detect_chunk_policy(config: Mapping[str, Any] | None) -> str:
    current = chunk_policy_values_from_config(config)
    for policy_id in (CHUNK_POLICY_BALANCED, CHUNK_POLICY_SENSITIVE, CHUNK_POLICY_STABLE):
        preset = CHUNK_POLICY_PRESETS[policy_id]
        if _values_match_preset(current, preset):
            return policy_id
    return CHUNK_POLICY_CUSTOM


def apply_chunk_policy(config: dict[str, Any], policy_id: str | None) -> dict[str, Any]:
    normalized = normalize_chunk_policy_id(policy_id)
    updated = dict(config)
    preset_values = resolve_chunk_policy_values(normalized)
    if preset_values:
        updated.update(preset_values)
    updated["chunk_policy"] = normalized
    return updated


def _values_match_preset(current: Mapping[str, Any], preset: Mapping[str, Any]) -> bool:
    for key in CHUNK_POLICY_CONFIG_KEYS:
        left = current.get(key)
        right = preset.get(key)
        if isinstance(right, float):
            try:
                if abs(float(left) - float(right)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
            continue
        if str(left) != str(right):
            return False
    return True
