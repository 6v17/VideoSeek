"""VLM tag search projection — SQLite index fed from evidence/tags JSON (authoritative)."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Mapping, Sequence

from src.app.logging_utils import get_logger
from src.services.understanding_tags import projectable_tags
from src.storage.dialogue_transcript_store import (
    _fuzzy_dialogue_rank,
    _fuzzy_probe_needles,
    fuzzy_dialogue_accepts,
    get_dialogue_store_dir,
    normalize_dialogue_query,
)

logger = get_logger("evidence_tags_store")

_SCHEMA_VERSION = 1
_SCHEMA_READY: set[str] = set()
_WRITE_LOCK = __import__("threading").RLock()
# Process-local suggest cache: invalidated on any projection write.
_SUGGEST_CACHE: dict[tuple[Any, ...], list[str]] = {}
_SUGGEST_CACHE_GEN = 0
_SUGGEST_CACHE_MAX = 96


def _invalidate_suggest_cache() -> None:
    global _SUGGEST_CACHE_GEN
    _SUGGEST_CACHE.clear()
    _SUGGEST_CACHE_GEN += 1


def get_evidence_tags_db_path(*, config=None) -> str:
    return os.path.join(get_dialogue_store_dir(config=config), "evidence_tags.db")


@contextmanager
def _db(*, config=None):
    db_path = get_evidence_tags_db_path(config=config)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
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
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY NOT NULL,
          value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS tag_rows (
          video_id TEXT NOT NULL,
          video_path TEXT NOT NULL DEFAULT '',
          library_path TEXT NOT NULL DEFAULT '',
          chunk_index INTEGER NOT NULL,
          start_sec REAL NOT NULL DEFAULT 0,
          end_sec REAL NOT NULL DEFAULT 0,
          tag TEXT NOT NULL,
          tag_cf TEXT NOT NULL,
          updated_at REAL NOT NULL DEFAULT 0,
          PRIMARY KEY (video_id, chunk_index, tag_cf)
        );

        CREATE INDEX IF NOT EXISTS idx_tag_rows_tag_cf ON tag_rows(tag_cf);
        CREATE INDEX IF NOT EXISTS idx_tag_rows_video ON tag_rows(video_id);
        """
    )
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
        ("schema_version", str(_SCHEMA_VERSION)),
    )
    conn.commit()


def _casefold_tag(tag: str) -> str:
    return str(tag or "").strip().casefold()


def _bundle_video_fields(bundle: Mapping[str, Any]) -> tuple[str, str]:
    video = bundle.get("video") if isinstance(bundle.get("video"), Mapping) else {}
    video_path = str((video or {}).get("video_path") or "").strip()
    library_path = str((video or {}).get("library_path") or "").strip()
    return video_path, library_path


def _iter_tag_rows_from_bundle(
    video_id: str,
    bundle: Mapping[str, Any],
    *,
    updated_at: float,
) -> list[tuple]:
    video_path, library_path = _bundle_video_fields(bundle)
    chunks = bundle.get("chunks") if isinstance(bundle.get("chunks"), list) else []
    rows: list[tuple] = []
    seen: set[tuple[int, str]] = set()
    for raw in chunks:
        if not isinstance(raw, Mapping):
            continue
        try:
            chunk_index = int(raw.get("chunk_index"))
        except (TypeError, ValueError):
            continue
        try:
            start_sec = float(raw.get("start_sec") or 0.0)
        except (TypeError, ValueError):
            start_sec = 0.0
        try:
            end_sec = float(raw.get("end_sec") or start_sec)
        except (TypeError, ValueError):
            end_sec = start_sec
        tags = raw.get("tags") if isinstance(raw.get("tags"), (list, tuple)) else []
        for tag in projectable_tags(tags):
            tag_cf = _casefold_tag(tag)
            if not tag or not tag_cf:
                continue
            key = (chunk_index, tag_cf)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                (
                    video_id,
                    video_path,
                    library_path,
                    chunk_index,
                    start_sec,
                    end_sec,
                    tag,
                    tag_cf,
                    updated_at,
                )
            )
    return rows


def replace_video_tags_from_bundle(
    video_id: str,
    bundle: Mapping[str, Any],
    *,
    config=None,
) -> int:
    """Replace all projected rows for one video from an evidence tags bundle."""
    vid = str(video_id or "").strip()
    if not vid or not isinstance(bundle, Mapping):
        return 0
    now = time.time()
    rows = _iter_tag_rows_from_bundle(vid, bundle, updated_at=now)
    with _WRITE_LOCK:
        with _db(config=config) as conn:
            conn.execute("DELETE FROM tag_rows WHERE video_id = ?", (vid,))
            if rows:
                conn.executemany(
                    """
                    INSERT INTO tag_rows(
                      video_id, video_path, library_path, chunk_index,
                      start_sec, end_sec, tag, tag_cf, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
            conn.commit()
    _invalidate_suggest_cache()
    return len(rows)


def delete_video_tags(video_id: str, *, config=None) -> int:
    vid = str(video_id or "").strip()
    if not vid:
        return 0
    with _WRITE_LOCK:
        with _db(config=config) as conn:
            cur = conn.execute("DELETE FROM tag_rows WHERE video_id = ?", (vid,))
            conn.commit()
            deleted = int(cur.rowcount or 0)
    if deleted:
        _invalidate_suggest_cache()
    return deleted


def clear_all_tag_rows(*, config=None) -> int:
    with _WRITE_LOCK:
        with _db(config=config) as conn:
            cur = conn.execute("DELETE FROM tag_rows")
            conn.commit()
            deleted = int(cur.rowcount or 0)
    if deleted:
        _invalidate_suggest_cache()
    return deleted


def list_tag_search_scope_entries(*, config=None) -> list[dict[str, Any]]:
    """Videos present in the tag projection DB — for the Tags-tab search scope picker."""
    db_path = get_evidence_tags_db_path(config=config)
    if not os.path.isfile(db_path):
        return []
    try:
        with _db(config=config) as conn:
            rows = list(
                conn.execute(
                    """
                    SELECT video_id,
                           MAX(video_path) AS video_path,
                           MAX(library_path) AS library_path
                    FROM tag_rows
                    GROUP BY video_id
                    ORDER BY library_path, video_path, video_id
                    """
                )
            )
    except Exception:
        logger.exception("Failed to list tag search scope entries")
        return []

    entries: list[dict[str, Any]] = []
    for row in rows:
        video_id = str(row["video_id"] or "").strip()
        if not video_id:
            continue
        video_path = str(row["video_path"] or "").strip()
        library_path = str(row["library_path"] or "").strip()
        rel = ""
        if library_path and video_path:
            try:
                candidate = os.path.relpath(video_path, library_path)
                if not str(candidate).startswith(".."):
                    rel = candidate
            except ValueError:
                rel = ""
        if not rel and video_path:
            rel = os.path.basename(video_path)
        source_exists = bool(video_path) and os.path.isfile(video_path)
        entries.append(
            {
                "video_id": video_id,
                "video_path": video_path,
                "library_path": library_path,
                "video_rel_path": rel,
                # Presence in the projection means searchable; file may be offline.
                "asset_state": "ready",
                "source_exists": source_exists,
            }
        )
    return entries


def get_tag_index_stats(*, config=None) -> dict[str, Any]:
    db_path = get_evidence_tags_db_path(config=config)
    if not os.path.isfile(db_path):
        return {
            "tag_index_ready": False,
            "tag_indexed_videos": 0,
            "tag_rows": 0,
            "db_path": db_path,
        }
    try:
        with _db(config=config) as conn:
            rows = int(conn.execute("SELECT COUNT(*) FROM tag_rows").fetchone()[0] or 0)
            videos = int(
                conn.execute("SELECT COUNT(DISTINCT video_id) FROM tag_rows").fetchone()[0] or 0
            )
    except Exception:
        logger.exception("Failed to read evidence tags stats")
        return {
            "tag_index_ready": False,
            "tag_indexed_videos": 0,
            "tag_rows": 0,
            "db_path": db_path,
        }
    return {
        "tag_index_ready": rows > 0,
        "tag_indexed_videos": videos,
        "tag_rows": rows,
        "db_path": db_path,
    }


def rebuild_all_from_json(*, config=None) -> dict[str, Any]:
    """Rebuild projection from any evidence JSON that carries chunk tags.

    Preference per video: ``tags/`` → ``summaries/`` → ``motion/`` → legacy ``videos/``.
    Motion/summary runs often store the same ``chunks[].tags`` used for search.
    """
    from src.services.understanding_paths import (
        get_evidence_motion_dir,
        get_evidence_summaries_dir,
        get_evidence_tags_dir,
        get_evidence_videos_dir,
    )

    cfg = config
    # Prefer dedicated tags store, then siblings that may still carry tags.
    store_dirs = [
        ("tags", get_evidence_tags_dir(config=cfg)),
        ("summaries", get_evidence_summaries_dir(config=cfg)),
        ("motion", get_evidence_motion_dir(config=cfg)),
        ("videos", get_evidence_videos_dir(config=cfg)),
    ]
    chosen: dict[str, tuple[str, str]] = {}  # video_id -> (store_kind, path)
    for store_kind, folder in store_dirs:
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not str(name).lower().endswith(".json"):
                continue
            vid = os.path.splitext(name)[0]
            if not vid or vid in chosen:
                continue
            chosen[vid] = (store_kind, os.path.join(folder, name))

    clear_all_tag_rows(config=cfg)
    projected = 0
    videos_ok = 0
    videos_skipped_no_tags = 0
    scanned_by_store: dict[str, int] = {}
    errors: list[str] = []
    for vid, (store_kind, path) in sorted(chosen.items()):
        scanned_by_store[store_kind] = scanned_by_store.get(store_kind, 0) + 1
        try:
            with open(path, "r", encoding="utf-8") as handle:
                bundle = json.load(handle)
            if not isinstance(bundle, Mapping):
                videos_skipped_no_tags += 1
                continue
            chunks = bundle.get("chunks") if isinstance(bundle.get("chunks"), list) else []
            if not any(isinstance(c, Mapping) and c.get("tags") for c in chunks):
                videos_skipped_no_tags += 1
                continue
            n = replace_video_tags_from_bundle(vid, bundle, config=cfg)
            projected += n
            if n:
                videos_ok += 1
            else:
                videos_skipped_no_tags += 1
        except Exception as exc:
            errors.append(f"{vid}: {exc}")
            logger.exception("Failed to project tags for %s from %s", vid, path)
    return {
        "ok": not errors,
        "videos_scanned": len(chosen),
        "videos_projected": videos_ok,
        "videos_skipped_no_tags": videos_skipped_no_tags,
        "tag_rows": projected,
        "scanned_by_store": scanned_by_store,
        "errors": errors,
    }


def suggest_tags(
    query: str,
    *,
    config=None,
    limit: int = 12,
    exclude_tags: Sequence[str] | None = None,
    required_tags: Sequence[str] | None = None,
) -> list[str]:
    """Return distinct full tags for the suggestion list.

    Empty query → popular tags by frequency (or co-occurring tags when
    ``required_tags`` is set).
    Non-empty → substring match on ``tag_cf``.

    When ``required_tags`` is set, only tags that co-occur on chunks matching
    *all* required needles (AND) are suggested — so multi-chip pick stays
    useful for the next AND term.

    Results are cached in-process until the next projection write.
    """
    needle = normalize_dialogue_query(query)
    keep = max(1, min(64, int(limit or 12)))
    exclude = {
        str(t).strip().casefold()
        for t in (exclude_tags or [])
        if str(t or "").strip()
    }
    anchors = _normalize_tag_needles("", required_tags)
    # Chips already selected should not reappear even if caller forgot exclude.
    for anchor in anchors:
        exclude.add(anchor)

    db_path = get_evidence_tags_db_path(config=config)
    cache_key = (
        _SUGGEST_CACHE_GEN,
        os.path.normpath(db_path),
        needle,
        tuple(anchors),
        tuple(sorted(exclude)),
        keep,
    )
    cached = _SUGGEST_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    fetch = keep + len(exclude) + 8
    with _db(config=config) as conn:
        if anchors:
            rows = _suggest_rows_cooccurring(conn, anchors, needle, fetch)
        elif needle:
            rows = list(
                conn.execute(
                    """
                    SELECT tag, COUNT(*) AS hit_count
                    FROM tag_rows
                    WHERE instr(tag_cf, ?) > 0
                    GROUP BY tag_cf
                    ORDER BY hit_count DESC, LENGTH(tag_cf) ASC, tag ASC
                    LIMIT ?
                    """,
                    (needle, fetch),
                )
            )
        else:
            rows = list(
                conn.execute(
                    """
                    SELECT tag, COUNT(*) AS hit_count
                    FROM tag_rows
                    GROUP BY tag_cf
                    ORDER BY hit_count DESC, LENGTH(tag_cf) ASC, tag ASC
                    LIMIT ?
                    """,
                    (fetch,),
                )
            )

    out: list[str] = []
    seen: set[str] = set()
    for row in rows:
        tag = str(row["tag"] or "").strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen or key in exclude:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= keep:
            break

    if len(_SUGGEST_CACHE) >= _SUGGEST_CACHE_MAX:
        # Drop an arbitrary old entry; gen bump clears everything on writes.
        _SUGGEST_CACHE.pop(next(iter(_SUGGEST_CACHE)), None)
    _SUGGEST_CACHE[cache_key] = list(out)
    return out


def _suggest_rows_cooccurring(
    conn: sqlite3.Connection,
    anchors: Sequence[str],
    needle: str,
    fetch: int,
) -> list[sqlite3.Row]:
    """Tags on chunks that already match every required anchor (AND)."""
    if not anchors:
        return []
    key_sql_parts: list[str] = []
    params: list[Any] = []
    for anchor in anchors:
        key_sql_parts.append(
            "SELECT video_id, chunk_index FROM tag_rows WHERE instr(tag_cf, ?) > 0"
        )
        params.append(anchor)
    matched_sql = " INTERSECT ".join(key_sql_parts)
    if needle:
        sql = f"""
            SELECT t.tag AS tag, COUNT(*) AS hit_count
            FROM tag_rows t
            INNER JOIN ({matched_sql}) m
              ON t.video_id = m.video_id AND t.chunk_index = m.chunk_index
            WHERE instr(t.tag_cf, ?) > 0
            GROUP BY t.tag_cf
            ORDER BY hit_count DESC, LENGTH(t.tag_cf) ASC, t.tag ASC
            LIMIT ?
        """
        params = list(params) + [needle, int(fetch)]
    else:
        sql = f"""
            SELECT t.tag AS tag, COUNT(*) AS hit_count
            FROM tag_rows t
            INNER JOIN ({matched_sql}) m
              ON t.video_id = m.video_id AND t.chunk_index = m.chunk_index
            GROUP BY t.tag_cf
            ORDER BY hit_count DESC, LENGTH(t.tag_cf) ASC, t.tag ASC
            LIMIT ?
        """
        params = list(params) + [int(fetch)]
    return list(conn.execute(sql, params))


def _normalize_tag_needles(
    query: str = "",
    required_tags: Sequence[str] | None = None,
) -> list[str]:
    needles: list[str] = []
    seen: set[str] = set()
    for raw in list(required_tags or []):
        needle = normalize_dialogue_query(raw)
        if needle and needle not in seen:
            seen.add(needle)
            needles.append(needle)
    for raw in (str(query or "").strip(),):
        if not raw:
            continue
        # UI / agent may pass joined chips as "a · b".
        parts = [p.strip() for p in raw.split(" · ")] if " · " in raw else [raw]
        for part in parts:
            needle = normalize_dialogue_query(part)
            if needle and needle not in seen:
                seen.add(needle)
                needles.append(needle)
    return needles


def search_tags(
    query: str = "",
    *,
    config=None,
    top_k: int = 50,
    match_mode: str = "exact",
    video_ids: list[str] | set[str] | None = None,
    required_tags: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """Return chunk-level hits: one row per (video_id, chunk_index).

    Multiple needles (``required_tags`` and/or ``query``) are AND-combined:
    a chunk must match every needle. ``matched_tags`` = tags that matched any
    needle; ``chunk_tags`` = full tag set for display + highlight.
    """
    needles = _normalize_tag_needles(query, required_tags)
    if not needles:
        return []
    mode = str(match_mode or "exact").strip().lower()
    if mode in {"fuzzy", "tolerant", "approx"}:
        mode = "fuzzy"
    else:
        mode = "exact"
    keep = max(1, min(200, int(top_k or 50)))
    want_ids: list[str] | None = None
    if video_ids is not None:
        want_ids = [str(v).strip() for v in video_ids if str(v or "").strip()]
        if not want_ids:
            return []

    with _db(config=config) as conn:
        if len(needles) == 1:
            needle = needles[0]
            if mode == "exact":
                rows = _fetch_tag_rows_exact(conn, needle, want_ids)
                hits = _aggregate_exact_hits(rows, needle, keep)
            else:
                rows = _fetch_tag_rows_fuzzy(conn, needle, want_ids)
                if not rows:
                    return []
                hits = _aggregate_fuzzy_hits(rows, needle, keep)
            return _attach_full_chunk_tags(conn, hits)

        surviving: set[tuple[str, int]] | None = None
        for needle in needles:
            if mode == "exact":
                keys = {
                    (str(row["video_id"] or ""), int(row["chunk_index"]))
                    for row in _fetch_tag_rows_exact(conn, needle, want_ids)
                }
            else:
                keys = set()
                for row in _fetch_tag_rows_fuzzy(conn, needle, want_ids):
                    tag_cf = str(row["tag_cf"] or "").strip() or str(row["tag"] or "").casefold()
                    _sub, scatter = _fuzzy_dialogue_rank(tag_cf, needle)
                    if fuzzy_dialogue_accepts(scatter, needle):
                        keys.add((str(row["video_id"] or ""), int(row["chunk_index"])))
            if surviving is None:
                surviving = keys
            else:
                surviving &= keys
            if not surviving:
                return []
        hits = _aggregate_and_hits(conn, surviving or set(), needles, mode, keep)
        return _attach_full_chunk_tags(conn, hits)


def _fetch_tag_rows_exact(
    conn: sqlite3.Connection,
    needle: str,
    want_ids: list[str] | None,
) -> list[sqlite3.Row]:
    sql = """
        SELECT video_id, video_path, library_path, chunk_index,
               start_sec, end_sec, tag, tag_cf
        FROM tag_rows
        WHERE instr(tag_cf, ?) > 0
    """
    params: list[Any] = [needle]
    if want_ids is not None:
        placeholders = ",".join("?" for _ in want_ids)
        sql += f" AND video_id IN ({placeholders})"
        params.extend(want_ids)
    return list(conn.execute(sql, params))


def _fetch_tag_rows_fuzzy(
    conn: sqlite3.Connection,
    needle: str,
    want_ids: list[str] | None,
) -> list[sqlite3.Row]:
    probes = _fuzzy_probe_needles(needle)
    if not probes:
        return []
    or_parts = ["instr(tag_cf, ?) > 0" for _ in probes]
    sql = f"""
        SELECT video_id, video_path, library_path, chunk_index,
               start_sec, end_sec, tag, tag_cf
        FROM tag_rows
        WHERE ({' OR '.join(or_parts)})
    """
    params: list[Any] = list(probes)
    if want_ids is not None:
        placeholders = ",".join("?" for _ in want_ids)
        sql += f" AND video_id IN ({placeholders})"
        params.extend(want_ids)
    return list(conn.execute(sql, params))


def _tag_matches_needle(tag_cf: str, needle: str, mode: str) -> bool:
    if not tag_cf or not needle:
        return False
    if mode == "exact":
        return needle in tag_cf
    _sub, scatter = _fuzzy_dialogue_rank(tag_cf, needle)
    return fuzzy_dialogue_accepts(scatter, needle)


def _aggregate_and_hits(
    conn: sqlite3.Connection,
    keys: set[tuple[str, int]],
    needles: Sequence[str],
    mode: str,
    keep: int,
) -> list[dict[str, Any]]:
    if not keys:
        return []
    clauses: list[str] = []
    params: list[Any] = []
    for vid, chunk_index in keys:
        clauses.append("(video_id = ? AND chunk_index = ?)")
        params.extend([vid, chunk_index])
    sql = f"""
        SELECT video_id, video_path, library_path, chunk_index,
               start_sec, end_sec, tag, tag_cf
        FROM tag_rows
        WHERE {' OR '.join(clauses)}
    """
    rows = list(conn.execute(sql, params))
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        vid = str(row["video_id"] or "")
        chunk_index = int(row["chunk_index"])
        key = (vid, chunk_index)
        if key not in keys:
            continue
        tag = str(row["tag"] or "").strip()
        tag_cf = str(row["tag_cf"] or "").strip() or tag.casefold()
        matched_any = any(_tag_matches_needle(tag_cf, needle, mode) for needle in needles)
        if not matched_any:
            continue
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "video_id": vid,
                "video_path": str(row["video_path"] or ""),
                "library_path": str(row["library_path"] or ""),
                "chunk_index": chunk_index,
                "start_sec": float(row["start_sec"] or 0.0),
                "end_sec": float(row["end_sec"] or 0.0),
                "matched_tags": [tag] if tag else [],
                "score": float(len(needles)),
            }
        elif tag and tag not in entry["matched_tags"]:
            entry["matched_tags"].append(tag)
    ordered = sorted(
        grouped.values(),
        key=lambda item: (
            -len(item["matched_tags"]),
            -float(item["score"]),
            str(item["video_path"]),
            int(item["chunk_index"]),
        ),
    )
    return ordered[:keep]


def _attach_full_chunk_tags(
    conn: sqlite3.Connection,
    hits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill ``chunk_tags`` with every projected tag for each hit chunk."""
    if not hits:
        return hits
    keys = [
        (str(item.get("video_id") or ""), int(item.get("chunk_index")))
        for item in hits
        if str(item.get("video_id") or "").strip()
    ]
    if not keys:
        for item in hits:
            item["chunk_tags"] = list(item.get("matched_tags") or [])
        return hits

    clauses: list[str] = []
    params: list[Any] = []
    for vid, chunk_index in keys:
        clauses.append("(video_id = ? AND chunk_index = ?)")
        params.extend([vid, chunk_index])
    sql = f"""
        SELECT video_id, chunk_index, tag
        FROM tag_rows
        WHERE {' OR '.join(clauses)}
        ORDER BY video_id, chunk_index, rowid
    """
    by_key: dict[tuple[str, int], list[str]] = {}
    for row in conn.execute(sql, params):
        key = (str(row["video_id"] or ""), int(row["chunk_index"]))
        tag = str(row["tag"] or "").strip()
        if not tag:
            continue
        bucket = by_key.setdefault(key, [])
        if tag not in bucket:
            bucket.append(tag)

    for item in hits:
        key = (str(item.get("video_id") or ""), int(item.get("chunk_index")))
        full = by_key.get(key) or list(item.get("matched_tags") or [])
        item["chunk_tags"] = full
    return hits


def _aggregate_exact_hits(rows: Sequence[sqlite3.Row], needle: str, keep: int) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        vid = str(row["video_id"] or "")
        chunk_index = int(row["chunk_index"])
        key = (vid, chunk_index)
        tag = str(row["tag"] or "").strip()
        tag_cf = str(row["tag_cf"] or "").strip() or tag.casefold()
        if needle not in tag_cf:
            continue
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "video_id": vid,
                "video_path": str(row["video_path"] or ""),
                "library_path": str(row["library_path"] or ""),
                "chunk_index": chunk_index,
                "start_sec": float(row["start_sec"] or 0.0),
                "end_sec": float(row["end_sec"] or 0.0),
                "matched_tags": [tag] if tag else [],
                "score": 1.0,
            }
        elif tag and tag not in entry["matched_tags"]:
            entry["matched_tags"].append(tag)
    ordered = sorted(
        grouped.values(),
        key=lambda item: (
            -len(item["matched_tags"]),
            str(item["video_path"]),
            int(item["chunk_index"]),
        ),
    )
    return ordered[:keep]


def _aggregate_fuzzy_hits(rows: Sequence[sqlite3.Row], needle: str, keep: int) -> list[dict[str, Any]]:
    # Best fuzzy rank per (video, chunk); collect accepting tags.
    best_rank: dict[tuple[str, int], tuple[int, float]] = {}
    grouped: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        vid = str(row["video_id"] or "")
        chunk_index = int(row["chunk_index"])
        key = (vid, chunk_index)
        tag = str(row["tag"] or "").strip()
        tag_cf = str(row["tag_cf"] or "").strip() or tag.casefold()
        subfield_len, scatter = _fuzzy_dialogue_rank(tag_cf, needle)
        if not fuzzy_dialogue_accepts(scatter, needle):
            continue
        prev = best_rank.get(key)
        if prev is None or (subfield_len, scatter) > prev:
            best_rank[key] = (subfield_len, scatter)
        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "video_id": vid,
                "video_path": str(row["video_path"] or ""),
                "library_path": str(row["library_path"] or ""),
                "chunk_index": chunk_index,
                "start_sec": float(row["start_sec"] or 0.0),
                "end_sec": float(row["end_sec"] or 0.0),
                "matched_tags": [tag] if tag else [],
                "score": float(scatter),
            }
        elif tag and tag not in entry["matched_tags"]:
            entry["matched_tags"].append(tag)
    for key, (sub_len, scatter) in best_rank.items():
        if key in grouped:
            # Prefer longer complete subfields, then scatter rate.
            grouped[key]["score"] = float(sub_len) + float(scatter)
    ordered = sorted(
        grouped.values(),
        key=lambda item: (
            -float(item["score"]),
            -len(item["matched_tags"]),
            str(item["video_path"]),
            int(item["chunk_index"]),
        ),
    )
    return ordered[:keep]
