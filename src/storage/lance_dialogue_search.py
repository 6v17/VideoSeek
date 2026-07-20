"""Vector / keyword search over Lance ``dialogue_segments``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from src.app.logging_utils import get_logger
from src.core.faiss_index import _normalize_vectors
from src.storage.config_store import get_active_embedding_spec, get_local_model_asset_dirs
from src.storage.lance_store import (
    DIALOGUE_INDEX_STATE_READY,
    DIALOGUE_SEGMENTS_TABLE_NAME,
    _connect_lance,
    _list_table_names,
    _read_import_state,
    get_lance_dir,
    serialize_embedding_spec,
)
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("lance_dialogue_search")

# CLIP text↔text is a weak proxy for dialogue semantics. Nearest-neighbor search
# always returns top_k rows even when unrelated; drop low-confidence vector hits.
DIALOGUE_VECTOR_MIN_SCORE = 0.72


@dataclass(frozen=True)
class DialogueSearchHit:
    video_id: str
    video_path: str
    library_path: str
    start_sec: float
    end_sec: float
    text: str
    language: str
    score: float
    matched_by: str  # "keyword" | "keyword_fuzzy" | "vector"


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _scope_where(
    *,
    library_path: str = "",
    video_id: str = "",
    embedding_spec_json: str = "",
) -> str:
    predicates: list[str] = []
    vid = str(video_id or "").strip()
    if vid:
        predicates.append(f"video_id = {_sql_literal(vid)}")
    lib = canonicalize_library_path(library_path) if library_path else ""
    if lib:
        predicates.append(f"library_path = {_sql_literal(lib)}")
    spec = str(embedding_spec_json or "").strip()
    if spec:
        predicates.append(f"embedding_spec = {_sql_literal(spec)}")
    return " AND ".join(predicates)


def dialogue_table_row_count(profile_base_dir: str) -> int:
    base = os.path.normpath(profile_base_dir)
    if not os.path.isdir(get_lance_dir(base)):
        return 0
    db = _connect_lance(base)
    if DIALOGUE_SEGMENTS_TABLE_NAME not in _list_table_names(db):
        return 0
    return int(db.open_table(DIALOGUE_SEGMENTS_TABLE_NAME).count_rows())


_DIALOGUE_STATS_CACHE: dict[str, tuple[tuple[float, int], dict[str, Any]]] = {}


def _dialogue_transcripts_cache_key(config=None) -> tuple[str, float, int]:
    from src.storage.dialogue_transcript_store import dialogue_db_cache_token

    return dialogue_db_cache_token(config=config)


def get_dialogue_index_stats(*, config=None, profile_base_dir: str = "") -> dict[str, Any]:
    """Health/status snapshot for optional dialogue index.

    Shared transcripts (raw ASR) make keyword search ready. Per-profile Lance
    vectors make semantic search ready for the active CLIP model.
    """
    from src.storage.dialogue_transcript_store import (
        ensure_shared_transcripts,
        list_dialogue_transcript_summaries,
    )

    cache_key = _dialogue_transcripts_cache_key(config=config)
    root, mtime, file_count = cache_key
    if profile_base_dir:
        base = os.path.normpath(profile_base_dir)
    else:
        base = get_local_model_asset_dirs(config=config)["base_dir"]
    cache_token = (mtime, file_count)
    cached = _DIALOGUE_STATS_CACHE.get(root)
    if cached is not None and cached[0] == cache_token and cached[1].get("_profile_base") == base:
        return {k: v for k, v in cached[1].items() if not str(k).startswith("_")}

    ensure_shared_transcripts(config=config)
    # Re-key after possible one-time import.
    cache_key = _dialogue_transcripts_cache_key(config=config)
    root, mtime, file_count = cache_key
    cache_token = (mtime, file_count)

    records = list_dialogue_transcript_summaries(config=config)
    transcript_ids = [
        str(item.get("video_id") or "").strip()
        for item in records
        if str(item.get("video_id") or "").strip()
    ]
    transcript_rows = sum(int(item.get("segment_count") or 0) for item in records)

    vector_rows = dialogue_table_row_count(base)
    state = _read_import_state(base)
    videos = state.get("videos") if isinstance(state.get("videos"), dict) else {}
    vector_ready_ids = [
        str(video_id)
        for video_id, entry in videos.items()
        if isinstance(entry, dict)
        and str(entry.get("dialogue_index_state", "") or "").strip().lower() == DIALOGUE_INDEX_STATE_READY
    ]
    ready = bool(transcript_ids) or vector_rows > 0
    payload = {
        "dialogue_index_ready": ready,
        "dialogue_indexed_videos": len(transcript_ids) or len(vector_ready_ids),
        "dialogue_rows": int(transcript_rows) or int(vector_rows),
        "dialogue_ready_video_ids": transcript_ids or vector_ready_ids,
        "dialogue_transcript_videos": len(transcript_ids),
        "dialogue_vector_rows": int(vector_rows),
        "_profile_base": base,
    }
    _DIALOGUE_STATS_CACHE[root] = (cache_token, payload)
    return {k: v for k, v in payload.items() if not str(k).startswith("_")}


def keyword_search_dialogue(
    query: str,
    *,
    config=None,
    profile_base_dir: str = "",
    library_path: str = "",
    video_id: str = "",
    video_ids: list[str] | set[str] | None = None,
    top_k: int = 20,
    require_active_embedding_spec: bool = False,
    match_mode: str = "exact",
) -> list[DialogueSearchHit]:
    """Match shared OCR/ASR transcripts (not bound to CLIP).

    ``match_mode`` ``exact`` uses SQLite INSTR substring match; ``fuzzy`` allows
    short OCR typos via n-gram / near-substring scoring.
    Pass ``video_ids`` (or ``video_id`` / ``library_path``) to avoid scanning the
    whole shared store when the UI search scope is narrowed.
    """
    from src.storage.dialogue_transcript_store import (
        ensure_shared_transcripts,
        fuzzy_dialogue_accepts,
        fuzzy_dialogue_match_score,
        has_any_dialogue_transcript,
        iter_matching_transcript_segment_rows,
        normalize_dialogue_query,
    )

    text = str(query or "").strip()
    if not text:
        return []

    mode = str(match_mode or "exact").strip().lower()
    if mode in {"fuzzy", "tolerant", "approx"}:
        mode = "fuzzy"
    elif mode in {"segment", "keyword", "literal", "exact"}:
        mode = "exact"
    else:
        mode = "exact"

    ensure_shared_transcripts(config=config)
    want_video = str(video_id or "").strip()
    want_lib = canonicalize_library_path(library_path) if library_path else ""
    want_ids = None
    if video_ids is not None:
        want_ids = {str(v).strip() for v in video_ids if str(v or "").strip()}
        if not want_ids:
            return []

    needle = normalize_dialogue_query(text)
    hits: list[DialogueSearchHit] = []
    seen: set[tuple[str, float, float, str]] = set()
    limit = max(int(top_k), 1)
    matched_by = "keyword_fuzzy" if mode == "fuzzy" else "keyword"

    def _consume(item: dict[str, Any]) -> bool:
        row_text = str(item.get("text", "") or "")
        if not row_text:
            return False
        row_cf = row_text.casefold()
        score = item.get("score")
        if score is None:
            if mode == "exact":
                if needle not in row_cf:
                    return False
                score = 1.0
            else:
                score = fuzzy_dialogue_match_score(row_cf, needle)
                if not fuzzy_dialogue_accepts(float(score), needle):
                    return False
        else:
            score = float(score)
            if mode == "exact" and needle not in row_cf:
                return False
            if mode == "fuzzy" and not fuzzy_dialogue_accepts(score, needle):
                return False
        video_key = str(item.get("video_id", "") or "")
        if want_video and video_key != want_video:
            return False
        if want_ids is not None and video_key not in want_ids:
            return False
        row_lib = canonicalize_library_path(str(item.get("library_path", "") or ""))
        if want_lib and row_lib != want_lib:
            return False
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", 0.0) or 0.0)
        dedupe_key = (video_key, round(start_sec, 3), round(end_sec, 3), row_text)
        if dedupe_key in seen:
            return False
        seen.add(dedupe_key)
        hits.append(
            DialogueSearchHit(
                video_id=video_key,
                video_path=str(item.get("video_path", "") or ""),
                library_path=str(item.get("library_path", "") or ""),
                start_sec=start_sec,
                end_sec=end_sec,
                text=row_text,
                language=str(item.get("language", "") or ""),
                score=float(score),
                matched_by=matched_by if score < 1.0 else "keyword",
            )
        )
        return len(hits) >= limit

    for item in iter_matching_transcript_segment_rows(
        text,
        config=config,
        video_id=want_video,
        video_ids=want_ids,
        library_path=want_lib,
        limit=limit,
        match_mode=mode,
    ):
        if _consume(item):
            return hits

    # Legacy fallback: profile Lance text if shared store still empty.
    if hits or has_any_dialogue_transcript(config=config) or require_active_embedding_spec:
        return hits

    if profile_base_dir:
        base = os.path.normpath(profile_base_dir)
    else:
        base = get_local_model_asset_dirs(config=config)["base_dir"]
    if not os.path.isdir(get_lance_dir(base)):
        return hits
    db = _connect_lance(base)
    if DIALOGUE_SEGMENTS_TABLE_NAME not in _list_table_names(db):
        return hits
    table = db.open_table(DIALOGUE_SEGMENTS_TABLE_NAME)
    where = _scope_where(library_path=library_path, video_id=video_id)
    builder = table.search().select(
        ["video_id", "video_path", "library_path", "start", "end", "text", "language"]
    )
    if where:
        builder = builder.where(where)
    try:
        arrow = builder.limit(50_000).to_arrow()
        legacy_rows: list[dict[str, Any]] = []
        for index in range(arrow.num_rows):
            item = {
                "video_id": str(arrow["video_id"][index].as_py() or ""),
                "video_path": str(arrow["video_path"][index].as_py() or ""),
                "library_path": str(arrow["library_path"][index].as_py() or ""),
                "start": float(arrow["start"][index].as_py() or 0.0),
                "end": float(arrow["end"][index].as_py() or 0.0),
                "text": str(arrow["text"][index].as_py() or ""),
                "language": str(arrow["language"][index].as_py() or ""),
            }
            if want_ids is not None and item["video_id"] not in want_ids:
                continue
            if mode == "fuzzy":
                item["score"] = fuzzy_dialogue_match_score(item["text"], needle)
            legacy_rows.append(item)
        if mode == "fuzzy":
            legacy_rows.sort(key=lambda row: -float(row.get("score") or 0.0))
        for item in legacy_rows:
            if _consume(item):
                break
    except Exception as exc:
        logger.error("Dialogue keyword legacy scan failed: %s", exc)
    return hits


def vector_search_dialogue(
    query_vector,
    *,
    config=None,
    profile_base_dir: str = "",
    library_path: str = "",
    video_id: str = "",
    top_k: int = 20,
    require_active_embedding_spec: bool = True,
    min_score: float | None = DIALOGUE_VECTOR_MIN_SCORE,
) -> list[DialogueSearchHit]:
    if profile_base_dir:
        base = os.path.normpath(profile_base_dir)
    else:
        base = get_local_model_asset_dirs(config=config)["base_dir"]
    if not os.path.isdir(get_lance_dir(base)):
        return []

    query = _normalize_vectors(query_vector)
    if query.size == 0:
        return []
    query_row = query.reshape(1, -1)[0]

    spec_json = ""
    if require_active_embedding_spec:
        spec_json = serialize_embedding_spec(get_active_embedding_spec(config=config))

    db = _connect_lance(base)
    if DIALOGUE_SEGMENTS_TABLE_NAME not in _list_table_names(db):
        return []
    table = db.open_table(DIALOGUE_SEGMENTS_TABLE_NAME)
    where = _scope_where(
        library_path=library_path,
        video_id=video_id,
        embedding_spec_json=spec_json,
    )
    builder = table.search(query_row.tolist()).metric("cosine")
    if where:
        builder = builder.where(where)
    if hasattr(builder, "bypass_vector_index"):
        builder = builder.bypass_vector_index()
    builder = builder.select(
        [
            "video_id",
            "video_path",
            "library_path",
            "start",
            "end",
            "text",
            "language",
            "_distance",
        ]
    )
    try:
        arrow = builder.limit(max(int(top_k), 1)).to_arrow()
    except Exception as exc:
        logger.error("Dialogue vector search failed: %s", exc)
        return []

    score_floor = None if min_score is None else float(min_score)
    hits: list[DialogueSearchHit] = []
    for index in range(arrow.num_rows):
        distance = float(arrow["_distance"][index].as_py() or 0.0)
        score = max(0.0, 1.0 - distance)
        if score_floor is not None and score < score_floor:
            continue
        hits.append(
            DialogueSearchHit(
                video_id=str(arrow["video_id"][index].as_py() or ""),
                video_path=str(arrow["video_path"][index].as_py() or ""),
                library_path=str(arrow["library_path"][index].as_py() or ""),
                start_sec=float(arrow["start"][index].as_py() or 0.0),
                end_sec=float(arrow["end"][index].as_py() or 0.0),
                text=str(arrow["text"][index].as_py() or ""),
                language=str(arrow["language"][index].as_py() or ""),
                score=score,
                matched_by="vector",
            )
        )
    return hits


def search_dialogue(
    query: str,
    *,
    config=None,
    profile_base_dir: str = "",
    library_path: str = "",
    video_id: str = "",
    video_ids: list[str] | set[str] | None = None,
    top_k: int = 20,
    query_vector=None,
    match_mode: str = "auto",
) -> dict[str, Any]:
    """Search dialogue rows.

    ``match_mode``:
    - ``exact`` / ``segment`` / ``keyword``: contiguous substring on OCR/ASR text
    - ``fuzzy``: typo-tolerant keyword match on OCR/ASR text
    - ``semantic`` / ``vector``: CLIP text vector only
    - ``auto``: exact keyword first, then vector fallback (legacy / Agent default)
    """
    mode = str(match_mode or "auto").strip().lower()
    keyword_mode = "exact"
    if mode in {"fuzzy", "tolerant", "approx"}:
        mode = "fuzzy"
        keyword_mode = "fuzzy"
    elif mode in {"segment", "keyword", "literal", "exact"}:
        mode = "exact"
        keyword_mode = "exact"
    elif mode in {"semantic", "vector"}:
        mode = "semantic"
    else:
        mode = "auto"
        keyword_mode = "exact"

    def _keyword() -> list[DialogueSearchHit]:
        return keyword_search_dialogue(
            query,
            config=config,
            profile_base_dir=profile_base_dir,
            library_path=library_path,
            video_id=video_id,
            video_ids=video_ids,
            top_k=top_k,
            match_mode=keyword_mode,
        )

    def _vector() -> list[DialogueSearchHit]:
        vector = query_vector
        if vector is None:
            from src.core.clip_embedding import get_text_embedding

            text = str(query or "").strip()
            if not text:
                return []
            vector = get_text_embedding(text)
        return vector_search_dialogue(
            vector,
            config=config,
            profile_base_dir=profile_base_dir,
            library_path=library_path,
            video_id=video_id,
            top_k=top_k,
        )

    if mode in {"exact", "fuzzy"}:
        hits = _keyword()
        matched = "keyword_fuzzy" if mode == "fuzzy" else "keyword"
        if hits and mode == "fuzzy":
            # Prefer reporting fuzzy only when at least one non-exact hit exists.
            if any(str(item.matched_by) == "keyword_fuzzy" for item in hits):
                matched = "keyword_fuzzy"
            else:
                matched = "keyword"
        if not hits:
            return {"matched_by": matched, "hits": [], "message": "no dialogue matches"}
        return {"matched_by": matched, "hits": hits, "message": ""}

    if mode == "semantic":
        text = str(query or "").strip()
        if not text:
            return {"matched_by": "", "hits": [], "message": "empty query"}
        hits = _vector()
        if not hits:
            return {"matched_by": "vector", "hits": [], "message": "no dialogue matches"}
        return {"matched_by": "vector", "hits": hits, "message": ""}

    keyword_hits = _keyword()
    if keyword_hits:
        return {"matched_by": "keyword", "hits": keyword_hits, "message": ""}

    text = str(query or "").strip()
    if not text:
        return {"matched_by": "", "hits": [], "message": "empty query"}
    hits = _vector()
    if not hits:
        return {
            "matched_by": "",
            "hits": [],
            "message": "no dialogue matches",
        }
    return {"matched_by": "vector", "hits": hits, "message": ""}
