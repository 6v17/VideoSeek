"""Per-CLIP-profile library registry in SQLite.

Replaces ``meta.json`` (libraries/files) and the per-video map inside
``lance/import_state.json`` with ``{profile_base_dir}/library.db``.

``load_model_metadata`` / ``save_model_metadata`` keep the same nested dict shape.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any

from src.app.logging_utils import get_logger
logger = get_logger("profile_library_store")

LIBRARY_DB_NAME = "library.db"
_SCHEMA_VERSION = 1
_WRITE_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()

_TOP_LEVEL_META_KEYS = (
    "schema_version",
    "search_index_schema_version",
    "global_index_state",
    "global_indexes",
)


def get_library_db_path(profile_base_dir: str) -> str:
    return os.path.join(os.path.normpath(str(profile_base_dir or "")), LIBRARY_DB_NAME)


def library_db_cache_token(profile_base_dir: str) -> tuple[str, float, int]:
    db_path = os.path.normpath(get_library_db_path(profile_base_dir))
    try:
        mtime = float(os.path.getmtime(db_path)) if os.path.isfile(db_path) else 0.0
    except OSError:
        mtime = 0.0
    revision = 0
    if mtime > 0:
        try:
            with _db(profile_base_dir) as conn:
                row = conn.execute(
                    "SELECT value FROM meta_kv WHERE key = 'revision'"
                ).fetchone()
                revision = int(row["value"]) if row else 0
        except (sqlite3.Error, TypeError, ValueError):
            revision = 0
    return db_path, mtime, revision


@contextmanager
def _db(profile_base_dir: str):
    profile_base_dir = os.path.normpath(str(profile_base_dir or "").strip())
    if not profile_base_dir:
        raise ValueError("missing profile_base_dir")
    db_path = get_library_db_path(profile_base_dir)
    os.makedirs(profile_base_dir, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        norm = os.path.normpath(db_path)
        if norm not in _SCHEMA_READY:
            _ensure_schema(conn)
            _SCHEMA_READY.add(norm)
        yield conn
    finally:
        conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta_kv (
          key TEXT PRIMARY KEY NOT NULL,
          value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS libraries (
          library_path TEXT PRIMARY KEY NOT NULL,
          last_scan TEXT NOT NULL DEFAULT '',
          index_state TEXT NOT NULL DEFAULT 'pending',
          search_index_schema_version INTEGER NOT NULL DEFAULT 0,
          discover_cache_json TEXT NOT NULL DEFAULT '',
          extras_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS videos (
          library_path TEXT NOT NULL,
          video_rel_path TEXT NOT NULL,
          video_id TEXT NOT NULL DEFAULT '',
          mod_time REAL NOT NULL DEFAULT 0,
          asset_state TEXT NOT NULL DEFAULT '',
          sync_failure_reason TEXT NOT NULL DEFAULT '',
          extras_json TEXT NOT NULL DEFAULT '{}',
          PRIMARY KEY (library_path, video_rel_path),
          FOREIGN KEY (library_path) REFERENCES libraries(library_path) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_videos_video_id ON videos(video_id);

        CREATE TABLE IF NOT EXISTS video_index_state (
          video_id TEXT PRIMARY KEY NOT NULL,
          chunk_config_json TEXT NOT NULL DEFAULT '',
          dialogue_index_state TEXT NOT NULL DEFAULT 'missing',
          dialogue_segment_rows INTEGER NOT NULL DEFAULT 0,
          dialogue_asr_source TEXT NOT NULL DEFAULT '',
          dialogue_error TEXT NOT NULL DEFAULT '',
          extras_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS lance_stats (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          storage_version INTEGER NOT NULL DEFAULT 1,
          profile_base_dir TEXT NOT NULL DEFAULT '',
          videos_total INTEGER NOT NULL DEFAULT 0,
          videos_imported INTEGER NOT NULL DEFAULT 0,
          videos_failed INTEGER NOT NULL DEFAULT 0,
          frame_rows INTEGER NOT NULL DEFAULT 0,
          chunk_rows INTEGER NOT NULL DEFAULT 0,
          dialogue_rows INTEGER NOT NULL DEFAULT 0,
          dimension INTEGER NOT NULL DEFAULT 0,
          updated_at REAL NOT NULL DEFAULT 0
        );
        """
    )
    row = conn.execute("SELECT value FROM meta_kv WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta_kv(key, value) VALUES ('schema_version', ?)",
            (str(_SCHEMA_VERSION),),
        )
        conn.execute("INSERT INTO meta_kv(key, value) VALUES ('revision', '0')")
        conn.commit()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: str, default: Any):
    text = str(raw or "").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return default


def _bump_revision(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO meta_kv(key, value) VALUES ('revision', '1')
        ON CONFLICT(key) DO UPDATE SET
          value = CAST(CAST(COALESCE(meta_kv.value, '0') AS INTEGER) + 1 AS TEXT)
        """
    )


def _profile_has_rows(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM libraries LIMIT 1").fetchone()
    if row is not None:
        return True
    row = conn.execute("SELECT 1 FROM meta_kv WHERE key = 'migrated_from_json'").fetchone()
    return row is not None


def _migrate_from_json_files(profile_base_dir: str, conn: sqlite3.Connection) -> None:
    """One-time import from meta.json + lance/import_state.json for this profile."""
    profile_base_dir = os.path.normpath(profile_base_dir)
    meta_file = os.path.join(profile_base_dir, "meta.json")
    state_file = os.path.join(profile_base_dir, "lance", "import_state.json")

    meta: dict[str, Any] = {"libraries": {}}
    if os.path.isfile(meta_file):
        try:
            with open(meta_file, "r", encoding="utf-8-sig") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                meta = loaded
                if "libraries" not in meta or not isinstance(meta.get("libraries"), dict):
                    meta["libraries"] = {}
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Library DB migrate: bad meta.json %s: %s", meta_file, exc)

    _replace_meta_from_dict(conn, meta)

    if os.path.isfile(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Library DB migrate: bad import_state %s: %s", state_file, exc)
            state = {}
        if isinstance(state, dict):
            _replace_import_state_from_dict(conn, state, profile_base_dir=profile_base_dir)

    conn.execute(
        "INSERT INTO meta_kv(key, value) VALUES ('migrated_from_json', '1') "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    )
    _bump_revision(conn)
    conn.commit()
    logger.info("Migrated profile library JSON into %s", get_library_db_path(profile_base_dir))


def ensure_profile_library_db(profile_base_dir: str, *, migrate: bool = True) -> str:
    """Ensure ``library.db`` exists.

    ``migrate=False`` only creates schema (safe for hot paths like dialogue state
    writes). Full JSON import runs when ``migrate=True`` (metadata load).
    """
    profile_base_dir = os.path.normpath(str(profile_base_dir or ""))
    if not profile_base_dir:
        raise ValueError("missing profile_base_dir")
    meta_file = os.path.join(profile_base_dir, "meta.json")
    state_file = os.path.join(profile_base_dir, "lance", "import_state.json")
    with _WRITE_LOCK:
        with _db(profile_base_dir) as conn:
            if (
                migrate
                and not _profile_has_rows(conn)
                and (os.path.isfile(meta_file) or os.path.isfile(state_file))
            ):
                _migrate_from_json_files(profile_base_dir, conn)
    return get_library_db_path(profile_base_dir)


def _replace_meta_from_dict(conn: sqlite3.Connection, meta: dict[str, Any]) -> None:
    for key in _TOP_LEVEL_META_KEYS:
        if key not in meta:
            continue
        value = meta.get(key)
        if isinstance(value, (dict, list)):
            raw = _json_dumps(value)
        else:
            raw = "" if value is None else str(value)
        conn.execute(
            "INSERT INTO meta_kv(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"top:{key}", raw),
        )

    conn.execute("DELETE FROM videos")
    conn.execute("DELETE FROM libraries")

    libraries = meta.get("libraries") if isinstance(meta.get("libraries"), dict) else {}
    for root_path, lib_data in libraries.items():
        if not isinstance(lib_data, dict):
            continue
        # Preserve path casing for media joins; comparisons use canonicalize elsewhere.
        library_path = os.path.normpath(os.path.abspath(str(root_path or "")))
        if not library_path:
            continue
        known = {
            "files",
            "last_scan",
            "index_state",
            "search_index_schema_version",
            "discover_cache",
        }
        extras = {k: v for k, v in lib_data.items() if k not in known}
        discover = lib_data.get("discover_cache")
        discover_json = _json_dumps(discover) if isinstance(discover, dict) else ""
        try:
            schema_ver = int(lib_data.get("search_index_schema_version") or 0)
        except (TypeError, ValueError):
            schema_ver = 0
        conn.execute(
            """
            INSERT INTO libraries(
              library_path, last_scan, index_state, search_index_schema_version,
              discover_cache_json, extras_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                library_path,
                str(lib_data.get("last_scan", "") or ""),
                str(lib_data.get("index_state", "") or "pending"),
                schema_ver,
                discover_json,
                _json_dumps(extras) if extras else "{}",
            ),
        )
        files = lib_data.get("files") if isinstance(lib_data.get("files"), dict) else {}
        video_rows = []
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            rel = str(rel_path or "").replace("\\", "/")
            if not rel:
                continue
            known_file = {"vid", "mod_time", "asset_state", "sync_failure_reason"}
            file_extras = {k: v for k, v in info.items() if k not in known_file}
            try:
                mod_time = float(info.get("mod_time", 0.0) or 0.0)
            except (TypeError, ValueError):
                mod_time = 0.0
            video_rows.append(
                (
                    library_path,
                    rel,
                    str(info.get("vid", "") or "").strip(),
                    mod_time,
                    str(info.get("asset_state", "") or "").strip(),
                    str(info.get("sync_failure_reason", "") or "").strip(),
                    _json_dumps(file_extras) if file_extras else "{}",
                )
            )
        if video_rows:
            conn.executemany(
                """
                INSERT INTO videos(
                  library_path, video_rel_path, video_id, mod_time,
                  asset_state, sync_failure_reason, extras_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                video_rows,
            )


def _replace_import_state_from_dict(
    conn: sqlite3.Connection,
    state: dict[str, Any],
    *,
    profile_base_dir: str = "",
) -> None:
    videos = state.get("videos") if isinstance(state.get("videos"), dict) else {}
    conn.execute("DELETE FROM video_index_state")
    rows = []
    for video_id, entry in videos.items():
        vid = str(video_id or "").strip()
        if not vid or not isinstance(entry, dict):
            continue
        chunk = entry.get("chunk_config")
        chunk_json = _json_dumps(chunk) if isinstance(chunk, dict) else ""
        known = {
            "chunk_config",
            "dialogue_index_state",
            "dialogue_segment_rows",
            "dialogue_asr_source",
            "dialogue_error",
        }
        extras = {k: v for k, v in entry.items() if k not in known}
        try:
            seg_rows = int(entry.get("dialogue_segment_rows") or 0)
        except (TypeError, ValueError):
            seg_rows = 0
        rows.append(
            (
                vid,
                chunk_json,
                str(entry.get("dialogue_index_state", "") or "missing").strip().lower() or "missing",
                seg_rows,
                str(entry.get("dialogue_asr_source", "") or ""),
                str(entry.get("dialogue_error", "") or ""),
                _json_dumps(extras) if extras else "{}",
            )
        )
    if rows:
        conn.executemany(
            """
            INSERT INTO video_index_state(
              video_id, chunk_config_json, dialogue_index_state, dialogue_segment_rows,
              dialogue_asr_source, dialogue_error, extras_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _int(key: str, default: int = 0) -> int:
        try:
            return int(state.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    conn.execute(
        """
        INSERT INTO lance_stats(
          id, storage_version, profile_base_dir, videos_total, videos_imported,
          videos_failed, frame_rows, chunk_rows, dialogue_rows, dimension, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          storage_version=excluded.storage_version,
          profile_base_dir=excluded.profile_base_dir,
          videos_total=excluded.videos_total,
          videos_imported=excluded.videos_imported,
          videos_failed=excluded.videos_failed,
          frame_rows=excluded.frame_rows,
          chunk_rows=excluded.chunk_rows,
          dialogue_rows=excluded.dialogue_rows,
          dimension=excluded.dimension,
          updated_at=excluded.updated_at
        """,
        (
            _int("storage_version", 1),
            str(state.get("profile_base_dir") or profile_base_dir or ""),
            _int("videos_total"),
            _int("videos_imported"),
            _int("videos_failed"),
            _int("frame_rows"),
            _int("chunk_rows"),
            _int("dialogue_rows"),
            _int("dimension"),
            time.time(),
        ),
    )


def load_profile_meta(profile_base_dir: str) -> dict[str, Any]:
    profile_base_dir = os.path.normpath(str(profile_base_dir or ""))
    ensure_profile_library_db(profile_base_dir)
    with _db(profile_base_dir) as conn:
        meta: dict[str, Any] = {"libraries": {}}
        for key in _TOP_LEVEL_META_KEYS:
            row = conn.execute(
                "SELECT value FROM meta_kv WHERE key = ?",
                (f"top:{key}",),
            ).fetchone()
            if row is None:
                continue
            raw = str(row["value"] or "")
            if key in {"global_indexes"}:
                meta[key] = _json_loads(raw, {})
            elif key in {"schema_version", "search_index_schema_version"}:
                try:
                    meta[key] = int(raw)
                except (TypeError, ValueError):
                    meta[key] = raw
            else:
                meta[key] = raw

        lib_rows = conn.execute(
            """
            SELECT library_path, last_scan, index_state, search_index_schema_version,
                   discover_cache_json, extras_json
            FROM libraries
            ORDER BY library_path
            """
        ).fetchall()
        libraries: dict[str, Any] = {}
        for lib in lib_rows:
            library_path = str(lib["library_path"] or "")
            entry: dict[str, Any] = {
                "files": {},
                "last_scan": str(lib["last_scan"] or ""),
                "index_state": str(lib["index_state"] or "pending"),
            }
            schema_ver = int(lib["search_index_schema_version"] or 0)
            if schema_ver:
                entry["search_index_schema_version"] = schema_ver
            discover = _json_loads(str(lib["discover_cache_json"] or ""), None)
            if isinstance(discover, dict):
                entry["discover_cache"] = discover
            extras = _json_loads(str(lib["extras_json"] or ""), {})
            if isinstance(extras, dict):
                entry.update(extras)

            file_rows = conn.execute(
                """
                SELECT video_rel_path, video_id, mod_time, asset_state,
                       sync_failure_reason, extras_json
                FROM videos
                WHERE library_path = ?
                ORDER BY video_rel_path
                """,
                (library_path,),
            ).fetchall()
            files: dict[str, Any] = {}
            for fr in file_rows:
                rel = str(fr["video_rel_path"] or "")
                info: dict[str, Any] = {
                    "vid": str(fr["video_id"] or ""),
                    "mod_time": float(fr["mod_time"] or 0.0),
                    "asset_state": str(fr["asset_state"] or ""),
                }
                reason = str(fr["sync_failure_reason"] or "").strip()
                if reason:
                    info["sync_failure_reason"] = reason
                file_extras = _json_loads(str(fr["extras_json"] or ""), {})
                if isinstance(file_extras, dict):
                    info.update(file_extras)
                files[rel] = info
            entry["files"] = files
            libraries[library_path] = entry
        meta["libraries"] = libraries
        return meta


def save_profile_meta(profile_base_dir: str, meta: dict[str, Any]) -> None:
    profile_base_dir = os.path.normpath(str(profile_base_dir or ""))
    if not isinstance(meta, dict):
        raise TypeError("meta must be a dict")
    ensure_profile_library_db(profile_base_dir)
    with _WRITE_LOCK:
        with _db(profile_base_dir) as conn:
            try:
                conn.execute("BEGIN")
                _replace_meta_from_dict(conn, meta)
                _bump_revision(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise


def load_import_state_dict(profile_base_dir: str) -> dict[str, Any]:
    profile_base_dir = os.path.normpath(str(profile_base_dir or ""))
    ensure_profile_library_db(profile_base_dir)
    with _db(profile_base_dir) as conn:
        stats = conn.execute("SELECT * FROM lance_stats WHERE id = 1").fetchone()
        payload: dict[str, Any] = {
            "storage_version": int(stats["storage_version"]) if stats else 1,
            "profile_base_dir": str(stats["profile_base_dir"] or profile_base_dir) if stats else profile_base_dir,
            "videos_total": int(stats["videos_total"] or 0) if stats else 0,
            "videos_imported": int(stats["videos_imported"] or 0) if stats else 0,
            "videos_failed": int(stats["videos_failed"] or 0) if stats else 0,
            "frame_rows": int(stats["frame_rows"] or 0) if stats else 0,
            "chunk_rows": int(stats["chunk_rows"] or 0) if stats else 0,
            "dialogue_rows": int(stats["dialogue_rows"] or 0) if stats else 0,
            "dimension": int(stats["dimension"] or 0) if stats else 0,
            "videos": {},
        }
        videos: dict[str, Any] = {}
        for row in conn.execute("SELECT * FROM video_index_state").fetchall():
            vid = str(row["video_id"] or "").strip()
            if not vid:
                continue
            entry: dict[str, Any] = {
                "dialogue_index_state": str(row["dialogue_index_state"] or "missing"),
            }
            chunk = _json_loads(str(row["chunk_config_json"] or ""), None)
            if isinstance(chunk, dict):
                entry["chunk_config"] = chunk
            seg_rows = int(row["dialogue_segment_rows"] or 0)
            if seg_rows:
                entry["dialogue_segment_rows"] = seg_rows
            asr = str(row["dialogue_asr_source"] or "")
            if asr:
                entry["dialogue_asr_source"] = asr
            err = str(row["dialogue_error"] or "")
            if err:
                entry["dialogue_error"] = err
            extras = _json_loads(str(row["extras_json"] or ""), {})
            if isinstance(extras, dict):
                entry.update(extras)
            videos[vid] = entry
        payload["videos"] = videos
        return payload


def save_import_state_dict(profile_base_dir: str, state: dict[str, Any]) -> None:
    profile_base_dir = os.path.normpath(str(profile_base_dir or ""))
    if not isinstance(state, dict):
        return
    ensure_profile_library_db(profile_base_dir)
    with _WRITE_LOCK:
        with _db(profile_base_dir) as conn:
            try:
                conn.execute("BEGIN")
                _replace_import_state_from_dict(conn, state, profile_base_dir=profile_base_dir)
                _bump_revision(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise


def get_stored_chunk_config(profile_base_dir: str, video_id: str):
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    ensure_profile_library_db(profile_base_dir, migrate=False)
    with _db(profile_base_dir) as conn:
        row = conn.execute(
            "SELECT chunk_config_json FROM video_index_state WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    if row is None:
        return None
    chunk = _json_loads(str(row["chunk_config_json"] or ""), None)
    return chunk if isinstance(chunk, dict) else None


def set_stored_chunk_config(profile_base_dir: str, video_id: str, chunk_config: dict) -> None:
    video_id = str(video_id or "").strip()
    if not video_id or not isinstance(chunk_config, dict):
        return
    ensure_profile_library_db(profile_base_dir, migrate=False)
    with _WRITE_LOCK:
        with _db(profile_base_dir) as conn:
            conn.execute(
                """
                INSERT INTO video_index_state(video_id, chunk_config_json)
                VALUES (?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                  chunk_config_json = excluded.chunk_config_json
                """,
                (video_id, _json_dumps(chunk_config)),
            )
            _bump_revision(conn)
            conn.commit()


def get_dialogue_index_state(profile_base_dir: str, video_id: str) -> str:
    video_id = str(video_id or "").strip()
    if not video_id:
        return "missing"
    ensure_profile_library_db(profile_base_dir, migrate=False)
    with _db(profile_base_dir) as conn:
        row = conn.execute(
            "SELECT dialogue_index_state FROM video_index_state WHERE video_id = ?",
            (video_id,),
        ).fetchone()
    if row is None:
        return "missing"
    value = str(row["dialogue_index_state"] or "").strip().lower()
    return value if value in {"ready", "missing", "failed"} else "missing"


def set_dialogue_index_state(
    profile_base_dir: str,
    video_id: str,
    dialogue_index_state: str,
    *,
    extras: dict | None = None,
) -> None:
    video_id = str(video_id or "").strip()
    state_value = str(dialogue_index_state or "").strip().lower()
    if not video_id or state_value not in {"ready", "missing", "failed"}:
        return
    # Hot path: never block OCR/index workers on legacy JSON migration.
    ensure_profile_library_db(profile_base_dir, migrate=False)

    with _WRITE_LOCK:
        with _db(profile_base_dir) as conn:
            existing = conn.execute(
                "SELECT * FROM video_index_state WHERE video_id = ?",
                (video_id,),
            ).fetchone()
            seg_rows = int(existing["dialogue_segment_rows"] or 0) if existing else 0
            asr_source = str(existing["dialogue_asr_source"] or "") if existing else ""
            error = str(existing["dialogue_error"] or "") if existing else ""
            merged_extras = (
                _json_loads(str(existing["extras_json"] or ""), {}) if existing else {}
            )
            if not isinstance(merged_extras, dict):
                merged_extras = {}
            if extras:
                if "dialogue_segment_rows" in extras:
                    try:
                        seg_rows = int(extras.get("dialogue_segment_rows") or 0)
                    except (TypeError, ValueError):
                        seg_rows = 0
                if "dialogue_asr_source" in extras:
                    asr_source = str(extras.get("dialogue_asr_source", "") or "")
                if "dialogue_error" in extras:
                    error = str(extras.get("dialogue_error", "") or "")
                known = {"dialogue_segment_rows", "dialogue_asr_source", "dialogue_error"}
                merged_extras.update({k: v for k, v in extras.items() if k not in known})
            conn.execute(
                """
                INSERT INTO video_index_state(
                  video_id, chunk_config_json, dialogue_index_state, dialogue_segment_rows,
                  dialogue_asr_source, dialogue_error, extras_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                  dialogue_index_state = excluded.dialogue_index_state,
                  dialogue_segment_rows = excluded.dialogue_segment_rows,
                  dialogue_asr_source = excluded.dialogue_asr_source,
                  dialogue_error = excluded.dialogue_error,
                  extras_json = excluded.extras_json
                """,
                (
                    video_id,
                    str(existing["chunk_config_json"] or "") if existing else "",
                    state_value,
                    seg_rows,
                    asr_source,
                    error,
                    _json_dumps(merged_extras) if merged_extras else "{}",
                ),
            )
            _bump_revision(conn)
            conn.commit()
