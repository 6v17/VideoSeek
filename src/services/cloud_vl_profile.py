"""Keep the optional cloud embedding profile in the model switcher."""

from __future__ import annotations

from typing import Any

from src.core.cloud_vl_embedding import (
    CLOUD_VL_PROFILE_ID,
    CLOUD_VL_PROVIDER_ID,
    cloud_vl_variant,
    normalize_cloud_vl_settings,
)


def build_cloud_vl_profile(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = normalize_cloud_vl_settings(settings)
    dimension = int(payload["dimension"])
    variant = cloud_vl_variant(dimension)
    return {
        "id": CLOUD_VL_PROFILE_ID,
        "provider": CLOUD_VL_PROVIDER_ID,
        "display_name": "Qwen3-VL Embedding（云）",
        "enabled": True,
        "runtime": {
            "prefer_gpu": False,
            "model_dir": "",
            "model_variant": variant,
            "embedding_dimension": dimension,
            "embedding_space": f"{CLOUD_VL_PROVIDER_ID}_{dimension}",
            "metric": "ip",
        },
        "capabilities": {
            "text_query": True,
            "image_query": True,
            "video_embedding": True,
            "cross_modal_search": True,
            "embedding_dimension": dimension,
        },
        "files": {},
        "embedding_dimension": dimension,
    }


def sync_cloud_vl_profile(config: dict) -> dict:
    """Enable the cloud profile as the active model, or restore the previous local model."""
    settings = normalize_cloud_vl_settings(config.get("cloud_vl_embedding"))
    config["cloud_vl_embedding"] = settings
    models = config.get("models")
    if not isinstance(models, dict):
        return config
    profiles = models.get("profiles")
    if not isinstance(profiles, list):
        profiles = []
        models["profiles"] = profiles

    def _is_cloud(item: Any) -> bool:
        return isinstance(item, dict) and str(item.get("id") or "").strip() == CLOUD_VL_PROFILE_ID

    def _profile_id(item: Any) -> str:
        return str(item.get("id") or "").strip() if isinstance(item, dict) else ""

    current = str(models.get("active_profile") or "").strip()
    if not settings["enabled"]:
        kept = [item for item in profiles if not _is_cloud(item)]
        models["profiles"] = kept
        if current == CLOUD_VL_PROFILE_ID:
            restore = str(settings.get("previous_profile_id") or "").strip()
            kept_ids = {_profile_id(item) for item in kept}
            if restore not in kept_ids:
                restore = next((_profile_id(item) for item in kept if _profile_id(item)), "")
            models["active_profile"] = restore
        return config

    if current and current != CLOUD_VL_PROFILE_ID:
        settings["previous_profile_id"] = current
        config["cloud_vl_embedding"] = settings
    profile = build_cloud_vl_profile(settings)
    replaced = False
    refreshed = []
    for item in profiles:
        if _is_cloud(item):
            if not replaced:
                refreshed.append(profile)
                replaced = True
            continue
        refreshed.append(item)
    if not replaced:
        refreshed.append(profile)
    models["profiles"] = refreshed
    models["active_profile"] = CLOUD_VL_PROFILE_ID
    return config
