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
    matched_by: str  # "keyword" | "vector"


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


def get_dialogue_index_stats(*, config=None, profile_base_dir: str = "") -> dict[str, Any]:
    """Health/status snapshot for optional dialogue index.

    Shared transcripts (raw ASR) make keyword search ready. Per-profile Lance
    vectors make semantic search ready for the active CLIP model.
    """
    from src.storage.dialogue_transcript_store import (
        ensure_shared_transcripts,
        list_dialogue_transcript_records,
    )

    ensure_shared_transcripts(config=config)
    records = list_dialogue_transcript_records(config=config)
    transcript_ids = [
        str(item.get("video_id") or "").strip()
        for item in records
        if str(item.get("video_id") or "").strip()
    ]
    transcript_rows = sum(int(item.get("segment_count") or 0) for item in records)

    if profile_base_dir:
        base = os.path.normpath(profile_base_dir)
    else:
        base = get_local_model_asset_dirs(config=config)["base_dir"]
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
    return {
        "dialogue_index_ready": ready,
        "dialogue_indexed_videos": len(transcript_ids) or len(vector_ready_ids),
        "dialogue_rows": int(transcript_rows) or int(vector_rows),
        "dialogue_ready_video_ids": transcript_ids or vector_ready_ids,
        "dialogue_transcript_videos": len(transcript_ids),
        "dialogue_vector_rows": int(vector_rows),
    }


def keyword_search_dialogue(
    query: str,
    *,
    config=None,
    profile_base_dir: str = "",
    library_path: str = "",
    video_id: str = "",
    top_k: int = 20,
    require_active_embedding_spec: bool = False,
) -> list[DialogueSearchHit]:
    """Substring match on shared ASR transcripts (not bound to CLIP)."""
    from src.storage.dialogue_transcript_store import (
        ensure_shared_transcripts,
        list_shared_transcript_segments,
    )

    text = str(query or "").strip()
    if not text:
        return []

    ensure_shared_transcripts(config=config)
    want_video = str(video_id or "").strip()
    want_lib = canonicalize_library_path(library_path) if library_path else ""
    segments = list_shared_transcript_segments(want_video, config=config)

    # Legacy fallback: profile Lance text if shared store still empty.
    if not segments and not require_active_embedding_spec:
        if profile_base_dir:
            base = os.path.normpath(profile_base_dir)
        else:
            base = get_local_model_asset_dirs(config=config)["base_dir"]
        if os.path.isdir(get_lance_dir(base)):
            db = _connect_lance(base)
            if DIALOGUE_SEGMENTS_TABLE_NAME in _list_table_names(db):
                table = db.open_table(DIALOGUE_SEGMENTS_TABLE_NAME)
                where = _scope_where(library_path=library_path, video_id=video_id)
                builder = table.search().select(
                    ["video_id", "video_path", "library_path", "start", "end", "text", "language"]
                )
                if where:
                    builder = builder.where(where)
                try:
                    arrow = builder.limit(50_000).to_arrow()
                    for index in range(arrow.num_rows):
                        segments.append(
                            {
                                "video_id": str(arrow["video_id"][index].as_py() or ""),
                                "video_path": str(arrow["video_path"][index].as_py() or ""),
                                "library_path": str(arrow["library_path"][index].as_py() or ""),
                                "start": float(arrow["start"][index].as_py() or 0.0),
                                "end": float(arrow["end"][index].as_py() or 0.0),
                                "text": str(arrow["text"][index].as_py() or ""),
                                "language": str(arrow["language"][index].as_py() or ""),
                            }
                        )
                except Exception as exc:
                    logger.error("Dialogue keyword legacy scan failed: %s", exc)

    needle = text.casefold()
    hits: list[DialogueSearchHit] = []
    seen: set[tuple[str, float, float, str]] = set()
    for item in segments:
        row_text = str(item.get("text", "") or "")
        if needle not in row_text.casefold():
            continue
        video_key = str(item.get("video_id", "") or "")
        if want_video and video_key != want_video:
            continue
        row_lib = canonicalize_library_path(str(item.get("library_path", "") or ""))
        if want_lib and row_lib != want_lib:
            continue
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", 0.0) or 0.0)
        dedupe_key = (video_key, round(start_sec, 3), round(end_sec, 3), row_text)
        if dedupe_key in seen:
            continue
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
                score=1.0,
                matched_by="keyword",
            )
        )
        if len(hits) >= max(int(top_k), 1):
            break
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
    top_k: int = 20,
    query_vector=None,
    match_mode: str = "auto",
) -> dict[str, Any]:
    """Search dialogue rows.

    ``match_mode``:
    - ``segment`` / ``keyword``: substring match on ASR text only
    - ``semantic`` / ``vector``: CLIP text vector only
    - ``auto``: keyword first, then vector fallback (legacy / Agent default)
    """
    mode = str(match_mode or "auto").strip().lower()
    if mode in {"segment", "keyword", "literal"}:
        mode = "segment"
    elif mode in {"semantic", "vector"}:
        mode = "semantic"
    else:
        mode = "auto"

    def _keyword() -> list[DialogueSearchHit]:
        return keyword_search_dialogue(
            query,
            config=config,
            profile_base_dir=profile_base_dir,
            library_path=library_path,
            video_id=video_id,
            top_k=top_k,
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

    if mode == "segment":
        hits = _keyword()
        if not hits:
            return {"matched_by": "keyword", "hits": [], "message": "no dialogue matches"}
        return {"matched_by": "keyword", "hits": hits, "message": ""}

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
