"""Per-profile lock for CLIP frame geometry (stretch vs center-crop).

Existing libraries keep stretch forever so multi-TB syncs never need a rebuild.
Empty profiles lock to center-crop on first use.
"""

from __future__ import annotations

import logging
import os

from src.core.vision_preprocess import (
    PREPROCESS_CENTER_CROP,
    PREPROCESS_STRETCH,
    normalize_embedding_preprocess,
)

logger = logging.getLogger(__name__)

_META_KEY = "embedding_preprocess"


def profile_has_visual_assets(profile_base_dir: str) -> bool:
    """True when this profile already has ready videos or Lance frame rows."""
    profile_base_dir = os.path.normpath(str(profile_base_dir or ""))
    if not profile_base_dir:
        return False
    try:
        from src.storage.lance_search_index import lance_search_is_ready

        if lance_search_is_ready(profile_base_dir):
            return True
    except Exception:
        pass
    try:
        from src.storage.lance_store import _count_profile_ready_videos

        if int(_count_profile_ready_videos(profile_base_dir) or 0) > 0:
            return True
    except Exception:
        pass
    return False


def get_locked_embedding_preprocess(profile_base_dir: str) -> str:
    from src.storage.profile_library_store import get_profile_meta_flag

    return normalize_embedding_preprocess(
        get_profile_meta_flag(profile_base_dir, _META_KEY)
    )


def set_locked_embedding_preprocess(profile_base_dir: str, mode: str) -> str:
    from src.storage.profile_library_store import set_profile_meta_flag

    normalized = normalize_embedding_preprocess(mode)
    if not normalized:
        raise ValueError(f"invalid embedding_preprocess: {mode!r}")
    set_profile_meta_flag(profile_base_dir, _META_KEY, normalized)
    return normalized


def resolve_embedding_preprocess(config=None) -> str:
    """Return the locked mode for the active profile, locking once if unset.

    - Already locked → return as-is (never auto-migrate stretch → crop).
    - Unset + existing vectors/ready assets → lock ``stretch``.
    - Unset + empty profile → lock ``center_crop``.
    """
    from src.storage.config_store import get_local_model_asset_dirs, load_config

    cfg = config if config is not None else load_config()
    base_dir = get_local_model_asset_dirs(config=cfg)["base_dir"]
    locked = get_locked_embedding_preprocess(base_dir)
    if locked:
        return locked
    mode = (
        PREPROCESS_STRETCH
        if profile_has_visual_assets(base_dir)
        else PREPROCESS_CENTER_CROP
    )
    set_locked_embedding_preprocess(base_dir, mode)
    logger.info(
        "Locked embedding_preprocess=%s for profile %s",
        mode,
        base_dir,
    )
    return mode
