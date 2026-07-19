"""Shared dialogue transcripts — OCR/ASR text, independent of CLIP profiles.

Vectors for semantic search stay in per-profile Lance ``dialogue_segments``.
This store keeps reusable raw material in SQLite: time + text + language.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from src.app.config import get_data_storage_paths
from src.app.logging_utils import get_logger
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("dialogue_transcript_store")

_SCHEMA_VERSION = 1
_IN_CHUNK = 400
_WRITE_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()


def get_dialogue_store_dir(*, config=None) -> str:
    data_dir = get_data_storage_paths(config=config)["data_dir"]
    return os.path.normpath(os.path.join(data_dir, "dialogue"))


def get_dialogue_transcripts_dir(*, config=None) -> str:
    """Legacy directory path (JSON era). Prefer ``get_dialogue_transcripts_db_path``."""
    return os.path.join(get_dialogue_store_dir(config=config), "transcripts")


def get_dialogue_transcripts_db_path(*, config=None) -> str:
    return os.path.join(get_dialogue_store_dir(config=config), "transcripts.db")


def transcript_path(video_id: str, *, config=None) -> str:
    """Compatibility shim: returns the shared SQLite DB path."""
    _ = video_id
    return get_dialogue_transcripts_db_path(config=config)


@contextmanager
def _db(*, config=None):
    """Short-lived connection so Windows can delete temp DBs in tests."""
    db_path = get_dialogue_transcripts_db_path(config=config)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
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
        CREATE TABLE IF NOT EXISTS meta (
          key TEXT PRIMARY KEY NOT NULL,
          value TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS transcripts (
          video_id TEXT PRIMARY KEY NOT NULL,
          library_path TEXT NOT NULL DEFAULT '',
          video_path TEXT NOT NULL DEFAULT '',
          asr_source TEXT NOT NULL DEFAULT '',
          segment_count INTEGER NOT NULL DEFAULT 0,
          updated_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS segments (
          video_id TEXT NOT NULL,
          seg_index INTEGER NOT NULL,
          start_sec REAL NOT NULL DEFAULT 0,
          end_sec REAL NOT NULL DEFAULT 0,
          text TEXT NOT NULL DEFAULT '',
          text_cf TEXT NOT NULL DEFAULT '',
          language TEXT NOT NULL DEFAULT '',
          asr_source TEXT NOT NULL DEFAULT '',
          PRIMARY KEY (video_id, seg_index),
          FOREIGN KEY (video_id) REFERENCES transcripts(video_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_segments_video_id ON segments(video_id);
        """
    )
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(_SCHEMA_VERSION),),
        )
        conn.commit()


def dialogue_db_cache_token(*, config=None) -> tuple[str, float, int]:
    """``(db_path, mtime, transcript_count)`` for lightweight cache invalidation."""
    db_path = os.path.normpath(get_dialogue_transcripts_db_path(config=config))
    try:
        mtime = float(os.path.getmtime(db_path)) if os.path.isfile(db_path) else 0.0
    except OSError:
        mtime = 0.0
    count = 0
    if mtime > 0:
        try:
            with _db(config=config) as conn:
                count = int(conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0])
        except sqlite3.Error:
            count = 0
    return db_path, mtime, count


def _normalize_segments(
    segments: list[dict[str, Any]] | None,
    *,
    asr_source: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        row_asr = str(item.get("asr_source", "") or asr_source or "").strip()
        rows.append(
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "text": text,
                "language": str(item.get("language", "") or "").strip(),
                "asr_source": row_asr,
            }
        )
    return rows


def save_dialogue_transcript(
    video_id: str,
    segments: list[dict[str, Any]],
    *,
    library_path: str = "",
    video_path: str = "",
    asr_source: str = "",
    config=None,
) -> dict[str, Any]:
    """Persist shared transcript for one video (overwrites previous)."""
    video_id = str(video_id or "").strip()
    if not video_id:
        return {"ok": False, "error": "missing video_id", "segment_count": 0}

    rows = _normalize_segments(segments, asr_source=asr_source)
    lib = canonicalize_library_path(library_path) if library_path else ""
    media = os.path.normpath(str(video_path or ""))
    source = str(asr_source or (rows[0].get("asr_source") if rows else "") or "").strip()
    updated_at = time.time()
    db_path = get_dialogue_transcripts_db_path(config=config)

    with _WRITE_LOCK:
        with _db(config=config) as conn:
            try:
                conn.execute("BEGIN")
                conn.execute(
                    """
                    INSERT INTO transcripts(
                      video_id, library_path, video_path, asr_source, segment_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(video_id) DO UPDATE SET
                      library_path=excluded.library_path,
                      video_path=excluded.video_path,
                      asr_source=excluded.asr_source,
                      segment_count=excluded.segment_count,
                      updated_at=excluded.updated_at
                    """,
                    (video_id, lib, media, source, len(rows), updated_at),
                )
                conn.execute("DELETE FROM segments WHERE video_id = ?", (video_id,))
                if rows:
                    conn.executemany(
                        """
                        INSERT INTO segments(
                          video_id, seg_index, start_sec, end_sec, text, text_cf, language, asr_source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            (
                                video_id,
                                index,
                                float(item["start"]),
                                float(item["end"]),
                                item["text"],
                                item["text"].casefold(),
                                item["language"],
                                item["asr_source"],
                            )
                            for index, item in enumerate(rows)
                        ],
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    return {"ok": True, "path": db_path, "segment_count": len(rows)}


def _payload_from_rows(
    meta: sqlite3.Row | None,
    segment_rows: list[sqlite3.Row],
) -> dict[str, Any] | None:
    if meta is None:
        return None
    segments = [
        {
            "start": float(row["start_sec"] or 0.0),
            "end": float(row["end_sec"] or 0.0),
            "text": str(row["text"] or ""),
            "language": str(row["language"] or ""),
            "asr_source": str(row["asr_source"] or ""),
        }
        for row in segment_rows
    ]
    return {
        "video_id": str(meta["video_id"] or ""),
        "library_path": str(meta["library_path"] or ""),
        "video_path": str(meta["video_path"] or ""),
        "asr_source": str(meta["asr_source"] or ""),
        "segment_count": int(meta["segment_count"] or len(segments) or 0),
        "segments": segments,
    }


def load_dialogue_transcript(video_id: str, *, config=None) -> dict[str, Any] | None:
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    try:
        with _db(config=config) as conn:
            meta = conn.execute(
                "SELECT * FROM transcripts WHERE video_id = ?",
                (video_id,),
            ).fetchone()
            if meta is None:
                return None
            segment_rows = conn.execute(
                """
                SELECT start_sec, end_sec, text, language, asr_source
                FROM segments
                WHERE video_id = ?
                ORDER BY seg_index
                """,
                (video_id,),
            ).fetchall()
            return _payload_from_rows(meta, list(segment_rows))
    except sqlite3.Error as exc:
        logger.warning("Unreadable dialogue transcript %s: %s", video_id, exc)
        return None


def delete_dialogue_transcript(video_id: str, *, config=None) -> bool:
    video_id = str(video_id or "").strip()
    if not video_id:
        return False
    with _WRITE_LOCK:
        with _db(config=config) as conn:
            cur = conn.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
            conn.commit()
            return cur.rowcount > 0


def has_any_dialogue_transcript(*, config=None) -> bool:
    try:
        with _db(config=config) as conn:
            row = conn.execute("SELECT 1 FROM transcripts LIMIT 1").fetchone()
            return row is not None
    except sqlite3.Error:
        return False


def _chunked(values: list[str], size: int = _IN_CHUNK) -> Iterator[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def list_dialogue_transcript_summaries(
    *,
    config=None,
    video_ids: list[str] | set[str] | None = None,
) -> list[dict[str, Any]]:
    """List transcript metadata without loading segment payloads."""
    want: list[str] | None = None
    if video_ids is not None:
        want = sorted({str(v).strip() for v in video_ids if str(v or "").strip()})
        if not want:
            return []

    records: list[dict[str, Any]] = []
    with _db(config=config) as conn:
        if want is None:
            source_rows = conn.execute(
                """
                SELECT video_id, library_path, video_path, asr_source, segment_count
                FROM transcripts
                ORDER BY video_id
                """
            ).fetchall()
        else:
            source_rows = []
            for chunk in _chunked(want):
                placeholders = ",".join("?" * len(chunk))
                source_rows.extend(
                    conn.execute(
                        f"""
                        SELECT video_id, library_path, video_path, asr_source, segment_count
                        FROM transcripts
                        WHERE video_id IN ({placeholders})
                        ORDER BY video_id
                        """,
                        chunk,
                    ).fetchall()
                )

        for row in source_rows:
            records.append(
                {
                    "video_id": str(row["video_id"] or ""),
                    "library_path": str(row["library_path"] or ""),
                    "video_path": str(row["video_path"] or ""),
                    "asr_source": str(row["asr_source"] or ""),
                    "segment_count": int(row["segment_count"] or 0),
                }
            )
    return records


def list_dialogue_transcript_records(
    *,
    config=None,
    video_ids: list[str] | set[str] | None = None,
    include_segments: bool = True,
) -> list[dict[str, Any]]:
    """List shared transcript payloads.

    Prefer ``list_dialogue_transcript_summaries`` for UI/stats. Full records with
    segments are only needed when callers must inspect cue text.
    """
    if not include_segments:
        return list_dialogue_transcript_summaries(config=config, video_ids=video_ids)

    summaries = list_dialogue_transcript_summaries(config=config, video_ids=video_ids)
    records: list[dict[str, Any]] = []
    for summary in summaries:
        payload = load_dialogue_transcript(str(summary.get("video_id") or ""), config=config)
        if payload:
            records.append(payload)
    return records


def iter_shared_transcript_segment_rows(
    *,
    config=None,
    video_id: str = "",
    video_ids: list[str] | set[str] | None = None,
    library_path: str = "",
):
    """Yield flat segment rows for one video, selected ids, or all videos."""
    want_video = str(video_id or "").strip()
    want_ids = None
    if video_ids is not None:
        want_ids = {str(v).strip() for v in video_ids if str(v or "").strip()}
        if not want_ids:
            return
    want_lib = canonicalize_library_path(library_path) if library_path else ""

    if want_video:
        targets = [want_video]
    elif want_ids is not None:
        targets = sorted(want_ids)
    else:
        targets = [
            str(item.get("video_id") or "").strip()
            for item in list_dialogue_transcript_summaries(config=config)
            if str(item.get("video_id") or "").strip()
        ]

    with _db(config=config) as conn:
        for vid in targets:
            if not vid:
                continue
            if want_ids is not None and vid not in want_ids:
                continue
            meta = conn.execute(
                "SELECT video_id, library_path, video_path, asr_source FROM transcripts WHERE video_id = ?",
                (vid,),
            ).fetchone()
            if meta is None:
                continue
            row_lib = canonicalize_library_path(str(meta["library_path"] or ""))
            if want_lib and row_lib != want_lib:
                continue
            media = str(meta["video_path"] or "")
            default_asr = str(meta["asr_source"] or "")
            segment_rows = conn.execute(
                """
                SELECT start_sec, end_sec, text, language, asr_source
                FROM segments
                WHERE video_id = ?
                ORDER BY start_sec, end_sec, seg_index
                """,
                (vid,),
            ).fetchall()
            for item in segment_rows:
                text = str(item["text"] or "").strip()
                if not text:
                    continue
                yield {
                    "video_id": vid,
                    "library_path": str(meta["library_path"] or ""),
                    "video_path": media,
                    "start": float(item["start_sec"] or 0.0),
                    "end": float(item["end_sec"] or 0.0),
                    "text": text,
                    "language": str(item["language"] or "").strip(),
                    "asr_source": str(item["asr_source"] or default_asr).strip(),
                }


def normalize_dialogue_query(query: str) -> str:
    """Casefold + trim; keep inner spaces for multi-token English queries."""
    return str(query or "").strip().casefold()


def _dialogue_query_tokens(needle: str) -> list[str]:
    text = normalize_dialogue_query(needle).replace("\u3000", " ")
    return [part for part in text.split() if part]


def _dialogue_query_compact(needle: str) -> str:
    """Single blob used for CJK / no-space fuzzy scoring."""
    tokens = _dialogue_query_tokens(needle)
    if len(tokens) > 1:
        return " ".join(tokens)
    if tokens:
        return tokens[0]
    return normalize_dialogue_query(needle).replace(" ", "")


def _char_ngrams(text: str, n: int = 2) -> list[str]:
    if not text:
        return []
    if len(text) < n:
        return [text]
    return [text[i : i + n] for i in range(len(text) - n + 1)]


def _ordered_char_coverage(needle: str, haystack: str) -> float:
    if not needle:
        return 0.0
    pos = 0
    matched = 0
    for ch in needle:
        found = haystack.find(ch, pos)
        if found < 0:
            continue
        matched += 1
        pos = found + 1
    return matched / float(len(needle))


def fuzzy_dialogue_match_score(text: str, query: str) -> float:
    """Score ``text`` against ``query`` in ``[0, 1]`` (1 = exact substring)."""
    needle = normalize_dialogue_query(query)
    if not needle:
        return 0.0
    hay = str(text or "").casefold()
    if not hay:
        return 0.0
    if needle in hay:
        return 1.0

    tokens = _dialogue_query_tokens(needle)
    if len(tokens) > 1:
        hits = sum(1 for token in tokens if token in hay)
        return hits / float(len(tokens))

    compact = _dialogue_query_compact(needle)
    if not compact:
        return 0.0
    if compact in hay:
        return 1.0
    if len(compact) < 2:
        return 1.0 if compact in hay else 0.0

    best = 0.0
    for index in range(len(compact)):
        deleted = compact[:index] + compact[index + 1 :]
        if len(deleted) >= 2 and deleted in hay:
            best = max(best, 0.9)

    grams = _char_ngrams(compact, 2)
    gram_hits = sum(1 for gram in grams if gram in hay)
    gram_ratio = gram_hits / float(len(grams)) if grams else 0.0
    best = max(best, gram_ratio)

    ordered = _ordered_char_coverage(compact, hay)
    # Allow roughly one wrong/missing character for short OCR typos.
    if len(compact) >= 3 and ordered + 1e-9 >= (len(compact) - 1) / float(len(compact)):
        best = max(best, max(0.7, ordered * 0.9))
    elif gram_ratio > 0:
        best = max(best, 0.45 * gram_ratio + 0.55 * ordered)
    return float(best)


def fuzzy_dialogue_accepts(score: float, query: str) -> bool:
    compact = _dialogue_query_compact(query)
    tokens = _dialogue_query_tokens(query)
    if len(tokens) > 1:
        return score >= 0.67
    n = len(compact)
    if n <= 2:
        return score >= 1.0
    if n <= 4:
        return score >= 0.5
    return score >= 0.6


def _fuzzy_probe_needles(query: str) -> list[str]:
    """Short pieces for SQL OR prefilter (refined by ``fuzzy_dialogue_match_score``)."""
    needle = normalize_dialogue_query(query)
    if not needle:
        return []
    tokens = _dialogue_query_tokens(needle)
    if len(tokens) > 1:
        return tokens[:16]

    compact = _dialogue_query_compact(needle)
    if not compact:
        return []
    if len(compact) <= 2:
        return [compact]

    probes: list[str] = []
    for gram in _char_ngrams(compact, 2):
        probes.append(gram)
    if len(compact) >= 3:
        for index in range(len(compact)):
            deleted = compact[:index] + compact[index + 1 :]
            if len(deleted) >= 2:
                probes.append(deleted)

    seen: set[str] = set()
    out: list[str] = []
    for piece in probes:
        if not piece or piece in seen:
            continue
        seen.add(piece)
        out.append(piece)
        if len(out) >= 28:
            break
    return out or [compact]


def iter_matching_transcript_segment_rows(
    query: str,
    *,
    config=None,
    video_id: str = "",
    video_ids: list[str] | set[str] | None = None,
    library_path: str = "",
    limit: int | None = None,
    match_mode: str = "exact",
):
    """Yield segment rows matching ``query``.

    ``match_mode``:
    - ``exact`` / ``segment`` / ``keyword``: contiguous casefolded substring (SQL INSTR)
    - ``fuzzy``: typo-tolerant fallback via n-grams / near-substring scoring
    """
    needle = normalize_dialogue_query(query)
    if not needle:
        return

    mode = str(match_mode or "exact").strip().lower()
    if mode in {"fuzzy", "tolerant", "approx"}:
        mode = "fuzzy"
    else:
        mode = "exact"

    want_video = str(video_id or "").strip()
    want_ids: list[str] | None = None
    if video_ids is not None:
        want_ids = sorted({str(v).strip() for v in video_ids if str(v or "").strip()})
        if not want_ids:
            return
    want_lib = canonicalize_library_path(library_path) if library_path else ""
    max_hits = int(limit) if limit is not None else None

    select_cols = """
        SELECT
          t.video_id AS video_id,
          t.library_path AS library_path,
          t.video_path AS video_path,
          s.start_sec AS start_sec,
          s.end_sec AS end_sec,
          s.text AS text,
          s.language AS language,
          COALESCE(NULLIF(s.asr_source, ''), t.asr_source) AS asr_source,
          s.text_cf AS text_cf
        FROM segments s
        JOIN transcripts t ON t.video_id = s.video_id
    """

    def _row_dict(row: sqlite3.Row, *, score: float) -> dict[str, Any]:
        return {
            "video_id": str(row["video_id"] or ""),
            "library_path": str(row["library_path"] or ""),
            "video_path": str(row["video_path"] or ""),
            "start": float(row["start_sec"] or 0.0),
            "end": float(row["end_sec"] or 0.0),
            "text": str(row["text"] or "").strip(),
            "language": str(row["language"] or "").strip(),
            "asr_source": str(row["asr_source"] or "").strip(),
            "score": float(score),
            "match_mode": mode,
        }

    with _db(config=config) as conn:
        if mode == "exact":
            yielded = 0
            base_select = select_cols + " WHERE instr(s.text_cf, ?) > 0"

            def _emit_exact(sql: str, params: list[Any]) -> Iterator[dict[str, Any]]:
                nonlocal yielded
                for row in conn.execute(sql, params):
                    if want_lib:
                        row_lib = canonicalize_library_path(str(row["library_path"] or ""))
                        if row_lib != want_lib:
                            continue
                    text = str(row["text"] or "").strip()
                    if not text:
                        continue
                    yield _row_dict(row, score=1.0)
                    yielded += 1
                    if max_hits is not None and yielded >= max_hits:
                        return

            order_limit = " ORDER BY t.video_id, s.start_sec, s.end_sec, s.seg_index"
            if max_hits is not None:
                order_limit += f" LIMIT {max(1, max_hits - yielded)}"

            if want_video:
                sql = base_select + " AND t.video_id = ?" + order_limit
                yield from _emit_exact(sql, [needle, want_video])
                return

            if want_ids is not None:
                for chunk in _chunked(want_ids):
                    if max_hits is not None and yielded >= max_hits:
                        return
                    placeholders = ",".join("?" * len(chunk))
                    sql = (
                        base_select
                        + f" AND t.video_id IN ({placeholders})"
                        + " ORDER BY t.video_id, s.start_sec, s.end_sec, s.seg_index"
                    )
                    params: list[Any] = [needle, *chunk]
                    if max_hits is not None:
                        sql += f" LIMIT {max(1, max_hits - yielded)}"
                    yield from _emit_exact(sql, params)
                return

            sql = base_select + order_limit
            yield from _emit_exact(sql, [needle])
            return

        # Fuzzy: broad SQL prefilter, then score / threshold / rank.
        probes = _fuzzy_probe_needles(needle)
        if not probes:
            return
        candidate_cap = 80
        if max_hits is not None:
            candidate_cap = max(80, min(2500, max_hits * 40))

        or_parts = [f"instr(s.text_cf, ?) > 0" for _ in probes]
        where_params: list[Any] = list(probes)
        compact = _dialogue_query_compact(needle)
        # First+last anchors keep single-char substitutions in the candidate set
        # without OR-ing common unigrams alone.
        if len(compact) >= 3 and " " not in compact:
            or_parts.append("(instr(s.text_cf, ?) > 0 AND instr(s.text_cf, ?) > 0)")
            where_params.extend([compact[0], compact[-1]])
        where_sql = "(" + " OR ".join(or_parts) + ")"
        scored: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, float, float, str]] = set()

        def _collect(sql: str, params: list[Any]) -> None:
            for row in conn.execute(sql, params):
                if want_lib:
                    row_lib = canonicalize_library_path(str(row["library_path"] or ""))
                    if row_lib != want_lib:
                        continue
                text = str(row["text"] or "").strip()
                if not text:
                    continue
                text_cf = str(row["text_cf"] or "").strip() or text.casefold()
                score = fuzzy_dialogue_match_score(text_cf, needle)
                if not fuzzy_dialogue_accepts(score, needle):
                    continue
                key = (
                    str(row["video_id"] or ""),
                    round(float(row["start_sec"] or 0.0), 3),
                    round(float(row["end_sec"] or 0.0), 3),
                    text,
                )
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                scored.append(_row_dict(row, score=score))

        order_sql = " ORDER BY t.video_id, s.start_sec, s.end_sec, s.seg_index"

        if want_video:
            params = [*where_params, want_video]
            sql = (
                select_cols
                + " WHERE "
                + where_sql
                + " AND t.video_id = ?"
                + order_sql
                + f" LIMIT {candidate_cap}"
            )
            _collect(sql, params)
        elif want_ids is not None:
            remaining = candidate_cap
            for chunk in _chunked(want_ids):
                if remaining <= 0:
                    break
                placeholders = ",".join("?" * len(chunk))
                params = [*where_params, *chunk]
                sql = (
                    select_cols
                    + " WHERE "
                    + where_sql
                    + f" AND t.video_id IN ({placeholders})"
                    + order_sql
                    + f" LIMIT {remaining}"
                )
                before = len(scored)
                _collect(sql, params)
                remaining = max(0, remaining - (len(scored) - before))
        else:
            params = list(where_params)
            sql = (
                select_cols
                + " WHERE "
                + where_sql
                + order_sql
                + f" LIMIT {candidate_cap}"
            )
            _collect(sql, params)

        scored.sort(
            key=lambda item: (
                -float(item.get("score") or 0.0),
                str(item.get("video_id") or ""),
                float(item.get("start") or 0.0),
            )
        )
        if max_hits is not None:
            scored = scored[: max(1, max_hits)]
        yield from scored


def list_shared_transcript_segments(
    video_id: str = "",
    *,
    config=None,
    video_ids: list[str] | set[str] | None = None,
    library_path: str = "",
) -> list[dict[str, Any]]:
    """Flat segment rows for one video, selected ids, or all videos."""
    rows = list(
        iter_shared_transcript_segment_rows(
            config=config,
            video_id=video_id,
            video_ids=video_ids,
            library_path=library_path,
        )
    )
    rows.sort(key=lambda item: (item["video_id"], item["start"], item["end"]))
    return rows


def import_transcripts_from_profile_lance(*, config=None) -> int:
    """Import text from any profile Lance dialogue table into the shared SQLite store.

    Skips videos that already have a shared transcript. Returns imported video count.
    """
    from src.storage.lance_store import (
        DIALOGUE_SEGMENTS_TABLE_NAME,
        _connect_lance,
        _list_table_names,
        get_lance_dir,
        list_dialogue_transcript_segments,
    )

    data_dir = get_data_storage_paths(config=config)["data_dir"]
    assets_root = os.path.join(data_dir, "model_assets")
    if not os.path.isdir(assets_root):
        return 0

    existing = {
        str(item.get("video_id") or "").strip()
        for item in list_dialogue_transcript_summaries(config=config)
        if str(item.get("video_id") or "").strip()
    }
    imported = 0
    for provider in os.listdir(assets_root):
        provider_dir = os.path.join(assets_root, provider)
        if not os.path.isdir(provider_dir):
            continue
        for variant in os.listdir(provider_dir):
            profile_base = os.path.join(provider_dir, variant)
            if not os.path.isdir(get_lance_dir(profile_base)):
                continue
            try:
                db = _connect_lance(profile_base)
                if DIALOGUE_SEGMENTS_TABLE_NAME not in _list_table_names(db):
                    continue
            except Exception:
                continue
            rows = list_dialogue_transcript_segments(
                profile_base_dir=profile_base,
                config=config,
            )
            by_video: dict[str, list[dict[str, Any]]] = {}
            meta: dict[str, dict[str, str]] = {}
            for row in rows:
                vid = str(row.get("video_id") or "").strip()
                if not vid or vid in existing:
                    continue
                by_video.setdefault(vid, []).append(row)
                meta[vid] = {
                    "library_path": str(row.get("library_path") or ""),
                    "video_path": str(row.get("video_path") or ""),
                    "asr_source": str(row.get("asr_source") or ""),
                }
            for vid, segs in by_video.items():
                info = meta.get(vid) or {}
                result = save_dialogue_transcript(
                    vid,
                    segs,
                    library_path=info.get("library_path", ""),
                    video_path=info.get("video_path", ""),
                    asr_source=info.get("asr_source", ""),
                    config=config,
                )
                if result.get("ok"):
                    existing.add(vid)
                    imported += 1
    if imported:
        logger.info("Imported %s dialogue transcripts into shared store", imported)
    return imported


def ensure_shared_transcripts(*, config=None) -> int:
    """Ensure shared SQLite store exists; import from legacy profile Lance if empty."""
    os.makedirs(get_dialogue_store_dir(config=config), exist_ok=True)
    with _db(config=config):
        pass
    if has_any_dialogue_transcript(config=config):
        return 0
    return import_transcripts_from_profile_lance(config=config)
