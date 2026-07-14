"""Model directory resolution and model asset path helpers."""

from __future__ import annotations

import os

from src.app.logging_utils import get_logger
from src.infra.paths import get_default_model_dir

logger = get_logger("model_paths")


def resolve_model_dir_info():
    try:
        from src.app.config import load_config
        from src.storage.config_store import get_effective_model_dir

        config = load_config()
        configured_model_dir = str(get_effective_model_dir(config=config) or "").strip()
        if configured_model_dir:
            return os.path.normpath(configured_model_dir), "configured"
    except Exception:
        pass

    return os.path.normpath(get_default_model_dir()), "default"


def sync_model_dir_to_config():
    from src.app.config import load_config, save_config
    from src.storage.config_store import get_active_model_profile, get_effective_model_dir

    config = load_config()
    configured_model_dir = str(get_effective_model_dir(config=config) or "").strip()
    top_level_model_dir = str(config.get("model_dir", "") or "").strip()
    if configured_model_dir:
        normalized_dir = os.path.normpath(configured_model_dir)
        if not os.path.isdir(normalized_dir) and top_level_model_dir:
            top_level_normalized_dir = os.path.normpath(top_level_model_dir)
            if os.path.isdir(top_level_normalized_dir):
                # Compatibility self-heal: if runtime.model_dir is stale after a
                # manual move, prefer the valid top-level model_dir and sync it
                # back to the active profile to avoid fallback loading failures.
                normalized_dir = top_level_normalized_dir
        needs_save = False
        if str(config.get("model_dir", "") or "").strip() != normalized_dir:
            config["model_dir"] = normalized_dir
            needs_save = True
        profile = get_active_model_profile(config=config)
        if profile:
            models = config.setdefault("models", {})
            profiles = models.setdefault("profiles", [])
            active_id = str(models.get("active_profile", "") or "").strip()
            for idx, item in enumerate(profiles):
                if not isinstance(item, dict):
                    continue
                if str(item.get("id", "") or "").strip() != active_id:
                    continue
                runtime = dict(item.get("runtime", {}) or {})
                if str(runtime.get("model_dir", "") or "").strip() != normalized_dir:
                    runtime["model_dir"] = normalized_dir
                    item["runtime"] = runtime
                    profiles[idx] = item
                    needs_save = True
                break
        if needs_save:
            save_config(config)
        if os.path.isdir(normalized_dir):
            return normalized_dir
        logger.warning("Configured model_dir is missing on disk; resetting to default: %s", normalized_dir)
        config["model_dir"] = ""
        profile = get_active_model_profile(config=config)
        if profile:
            models = config.setdefault("models", {})
            profiles = models.setdefault("profiles", [])
            active_id = str(models.get("active_profile", "") or "").strip()
            for idx, item in enumerate(profiles):
                if not isinstance(item, dict):
                    continue
                if str(item.get("id", "") or "").strip() != active_id:
                    continue
                runtime = dict(item.get("runtime", {}) or {})
                runtime["model_dir"] = ""
                item["runtime"] = runtime
                profiles[idx] = item
                break
        save_config(config)

    resolved_dir, _ = resolve_model_dir_info()
    if not resolved_dir:
        return ""

    config["model_dir"] = resolved_dir
    save_config(config)
    return resolved_dir


def get_configured_model_dir():
    resolved_dir, _ = resolve_model_dir_info()
    return resolved_dir


def get_model_path(filename):
    """Resolve a model asset path with stale runtime.model_dir compatibility fallback."""
    from src.app.config import load_config
    from src.storage.config_store import (
        get_active_model_profile,
        get_active_model_resource_dir,
        iter_provider_resource_dir_candidates,
        resolve_provider_dir,
    )

    config = load_config()
    candidate_paths = []
    model_profile_dir = get_active_model_resource_dir(config=config)
    candidate_paths.append(os.path.join(model_profile_dir, filename))
    try:
        profile = get_active_model_profile(config=config)
        runtime = dict(profile.get("runtime") or {})
        model_variant = str(runtime.get("model_variant", "") or profile.get("model_variant", "") or "").strip() or "vit-base-patch32"
        provider = str(profile.get("provider", "") or "").strip()
        top_level_model_root = str(config.get("model_dir", "") or "").strip()
        if top_level_model_root and provider:
            seen = {os.path.normcase(os.path.normpath(model_profile_dir))}
            for provider_dir in iter_provider_resource_dir_candidates(provider):
                fallback_path = os.path.join(top_level_model_root, provider_dir, model_variant, filename)
                normalized = os.path.normcase(os.path.normpath(fallback_path))
                if normalized in seen:
                    continue
                seen.add(normalized)
                candidate_paths.append(fallback_path)
            # Primary canonical path when resource_dir resolution picked a legacy folder.
            canonical_path = os.path.join(
                top_level_model_root,
                resolve_provider_dir(provider),
                model_variant,
                filename,
            )
            normalized = os.path.normcase(os.path.normpath(canonical_path))
            if normalized not in seen:
                candidate_paths.append(canonical_path)
    except Exception:
        pass
    for candidate in candidate_paths:
        if os.path.exists(candidate):
            return candidate
    return candidate_paths[0]


def get_missing_model_files(model_filenames):
    missing = []
    resolved_paths = {}

    for filename in model_filenames:
        path = get_model_path(filename)
        resolved_paths[filename] = path
        if not os.path.exists(path):
            missing.append(filename)

    return missing, resolved_paths


def ensure_model_files(model_filenames):
    missing, resolved_paths = get_missing_model_files(model_filenames)

    if missing:
        missing_display = ", ".join(missing)
        raise FileNotFoundError(
            f"Missing model files: {missing_display}. "
            f"Place them under the active profile directory "
            f"(runtime.model_dir + <provider folder> + <model_variant>), or use in-app download."
        )

    return resolved_paths
