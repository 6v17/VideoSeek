"""Global subtitle library registry — independent of CLIP model profiles.

Lives under ``{data_dir}/dialogue/library.db`` (same schema as profile library.db).
OCR cue text stays in ``transcripts.db``; this store only tracks which folders
belong to the shared subtitle library.
"""

from __future__ import annotations

import os
from typing import Any

from src.storage.dialogue_transcript_store import get_dialogue_store_dir
from src.storage.profile_library_store import (
    ensure_profile_library_db,
    get_library_db_path,
    get_profile_meta_flag,
    load_profile_meta,
    save_profile_meta,
    set_profile_meta_flag,
)

_SEED_KEY = "subtitle_registry_seeded"


def get_subtitle_library_base_dir(*, config=None) -> str:
    return get_dialogue_store_dir(config=config)


def get_subtitle_library_db_path(*, config=None) -> str:
    return get_library_db_path(get_subtitle_library_base_dir(config=config))


def ensure_subtitle_library_db(*, config=None) -> str:
    base = get_subtitle_library_base_dir(config=config)
    os.makedirs(base, exist_ok=True)
    # No legacy meta.json under dialogue/; skip JSON import.
    return ensure_profile_library_db(base, migrate=False)


def load_subtitle_library_meta(*, config=None) -> dict[str, Any]:
    ensure_subtitle_library_db(config=config)
    return load_profile_meta(get_subtitle_library_base_dir(config=config))


def save_subtitle_library_meta(meta: dict[str, Any], *, config=None) -> None:
    ensure_subtitle_library_db(config=config)
    save_profile_meta(get_subtitle_library_base_dir(config=config), meta)


def is_subtitle_registry_seeded(*, config=None) -> bool:
    ensure_subtitle_library_db(config=config)
    try:
        return get_profile_meta_flag(get_subtitle_library_base_dir(config=config), _SEED_KEY) == "1"
    except Exception as _swallowed:
        from src.app.logging_utils import note_swallowed

        note_swallowed(_swallowed, "src/storage/subtitle_library_store.py:is_subtitle_registry_seeded")
        return False


def mark_subtitle_registry_seeded(*, config=None) -> None:
    ensure_subtitle_library_db(config=config)
    set_profile_meta_flag(get_subtitle_library_base_dir(config=config), _SEED_KEY, "1")
