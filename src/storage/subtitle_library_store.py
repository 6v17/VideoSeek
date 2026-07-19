"""Global subtitle library registry — independent of CLIP model profiles.

Lives under ``{data_dir}/dialogue/library.db`` (same schema as profile library.db).
OCR cue text stays in ``transcripts.db``; this store only tracks which folders
belong to the shared subtitle library.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

from src.storage.dialogue_transcript_store import get_dialogue_store_dir
from src.storage.profile_library_store import (
    ensure_profile_library_db,
    get_library_db_path,
    load_profile_meta,
    save_profile_meta,
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
    db_path = get_subtitle_library_db_path(config=config)
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        try:
            row = conn.execute(
                "SELECT value FROM meta_kv WHERE key = ?",
                (_SEED_KEY,),
            ).fetchone()
            return bool(row and str(row[0] or "").strip() == "1")
        finally:
            conn.close()
    except Exception:
        return False


def mark_subtitle_registry_seeded(*, config=None) -> None:
    ensure_subtitle_library_db(config=config)
    db_path = get_subtitle_library_db_path(config=config)
    conn = sqlite3.connect(db_path, timeout=30.0)
    try:
        conn.execute(
            "INSERT INTO meta_kv(key, value) VALUES (?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_SEED_KEY,),
        )
        conn.commit()
    finally:
        conn.close()
