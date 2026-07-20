"""In-memory flat search index backed by LanceDB tables (FAISS-compatible surface)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from src.app.logging_utils import get_logger
from src.core.faiss_index import _normalize_vectors
from src.storage.lance_store import (
    CHUNKS_TABLE_NAME,
    FRAMES_TABLE_NAME,
    _connect_lance,
    _list_table_names,
    get_lance_dir,
    get_lance_state_file,
)
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("lance_search_index")

_READY_CACHE: dict[str, tuple[float, bool]] = {}
_INDEXED_VIDEO_IDS_CACHE: dict[str, tuple[float, frozenset[str]]] = {}
_VIDEO_ROW_COUNTS_CACHE: dict[str, tuple[float, dict[str, dict[str, int]]]] = {}
_LANCE_ROW_SCAN_LIMIT = 2_000_000


def _lance_state_mtime(profile_base_dir: str) -> float:
    """Cache token for Lance readiness; prefers profile ``library.db`` over legacy JSON."""
    from src.storage.profile_library_store import get_library_db_path, library_db_cache_token

    _path, mtime, revision = library_db_cache_token(profile_base_dir)
    if mtime > 0:
        return float(mtime) + (float(revision) * 1e-9)
    try:
        return os.path.getmtime(get_lance_state_file(profile_base_dir))
    except OSError:
        pass
    try:
        return os.path.getmtime(get_library_db_path(profile_base_dir))
    except OSError:
        return 0.0


def invalidate_lance_runtime_caches(profile_base_dir: str = "") -> None:
    if profile_base_dir:
        key = os.path.normpath(profile_base_dir)
        _READY_CACHE.pop(key, None)
        _INDEXED_VIDEO_IDS_CACHE.pop(key, None)
        _VIDEO_ROW_COUNTS_CACHE.pop(key, None)
        return
    _READY_CACHE.clear()
    _INDEXED_VIDEO_IDS_CACHE.clear()
    _VIDEO_ROW_COUNTS_CACHE.clear()


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _build_scope_where(*, library_path: str = "", video_id: str = "") -> str:
    predicates = []
    normalized_video = str(video_id or "").strip()
    if normalized_video:
        predicates.append(f"video_id = {_sql_literal(normalized_video)}")
    normalized_library = canonicalize_library_path(library_path) if library_path else ""
    if normalized_library:
        predicates.append(f"library_path = {_sql_literal(normalized_library)}")
    return " AND ".join(predicates)


def _vectors_from_arrow_column(column, num_rows: int) -> np.ndarray:
    import pyarrow as pa

    values = column.combine_chunks()
    if pa.types.is_fixed_size_list(values.type):
        flat = values.values.to_numpy(zero_copy_only=False)
        dimension = int(values.type.list_size)
        if dimension <= 0 or num_rows <= 0:
            return np.empty((0, 0), dtype=np.float32)
        return np.asarray(flat, dtype=np.float32).reshape(num_rows, dimension)
    if pa.types.is_list(values.type):
        return np.asarray(values.to_pylist(), dtype=np.float32)
    return np.asarray(values.to_pylist(), dtype=np.float32)


def _load_columns_arrow(
    table,
    columns: Sequence[str],
    *,
    library_path: str = "",
    video_id: str = "",
    limit: int = _LANCE_ROW_SCAN_LIMIT,
):
    where = _build_scope_where(library_path=library_path, video_id=video_id)
    builder = table.search().select(list(columns))
    if where:
        builder = builder.where(where)
    return builder.limit(int(limit)).to_arrow()


def _load_table_arrow(table, *, library_path: str = "", video_id: str = "", columns: Sequence[str] | None = None):
    where = _build_scope_where(library_path=library_path, video_id=video_id)
    if where or columns:
        builder = table.search()
        if where:
            builder = builder.where(where)
        if columns:
            builder = builder.select(list(columns))
        return builder.limit(_LANCE_ROW_SCAN_LIMIT).to_arrow()
    return table.search().limit(_LANCE_ROW_SCAN_LIMIT).to_arrow()


def _lance_distance_to_score(distance: float) -> float:
    # Cosine distance on normalized vectors equals 1 - inner product.
    return 1.0 - float(distance)


@dataclass(frozen=True)
class LanceSearchRow:
    score: float
    video_path: str
    video_id: str = ""
    timestamp: float | None = None
    start: float | None = None
    end: float | None = None
    vector: np.ndarray | None = None


class LanceTableSearchIndex:
    """Query Lance tables directly instead of materializing all vectors in RAM."""

    def __init__(self, table, *, where: str = "", is_chunk: bool = False):
        self._table = table
        self._where = str(where or "").strip()
        self._is_chunk = bool(is_chunk)
        self._ntotal = self._count_rows()
        self._d = self._read_dimension()
        self._last_rows: list[LanceSearchRow] = []

    def _count_rows(self) -> int:
        try:
            if self._where:
                return int(self._table.count_rows(filter=self._where))
            return int(self._table.count_rows())
        except Exception as exc:
            logger.debug("Lance row count failed: %s", exc)
            return 0

    def _read_dimension(self) -> int:
        try:
            arrow = self._table.search().select(["vector"]).limit(1).to_arrow()
            if arrow.num_rows <= 0:
                return 0
            vector_value = arrow["vector"][0].as_py()
            return len(vector_value or [])
        except Exception as exc:
            logger.debug("Lance dimension probe failed: %s", exc)
            return 0

    @property
    def ntotal(self) -> int:
        return int(self._ntotal)

    @property
    def d(self) -> int:
        return int(self._d)

    @property
    def last_rows(self) -> list[LanceSearchRow]:
        return list(self._last_rows)

    def _build_vector_search(self, query_vector):
        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim == 2:
            if query.shape[0] != 1:
                raise RuntimeError("LanceTableSearchIndex expects a single query row")
            query = query[0]
        builder = self._table.search(np.asarray(query, dtype=np.float32).tolist()).metric("cosine")
        if self._where:
            builder = builder.where(self._where)
        # IVF_PQ indexes trade recall for speed; prefer exact Lance vector search for CLIP ranking.
        if hasattr(builder, "bypass_vector_index"):
            builder = builder.bypass_vector_index()
        return builder

    def search_rows(self, query_vector, top_k: int) -> list[LanceSearchRow]:
        actual_k = min(max(int(top_k), 0), self._ntotal)
        if actual_k <= 0:
            self._last_rows = []
            return []

        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)
        if query.shape[0] != 1:
            raise RuntimeError("LanceTableSearchIndex expects a single query row")
        query_dim = int(query.shape[1])
        if self._d > 0 and query_dim != self._d:
            raise RuntimeError(
                f"Search index dimension mismatch (query={query_dim}, index={self._d}). "
                "Current model uses a different embedding space. Please rebuild the index for the active model."
            )

        try:
            arrow = self._build_vector_search(query).limit(actual_k).to_arrow()
        except Exception as exc:
            logger.error("Lance vector search failed: %s", exc)
            self._last_rows = []
            return []

        rows: list[LanceSearchRow] = []
        if arrow.num_rows <= 0:
            self._last_rows = rows
            return rows

        timestamps = arrow["timestamp"].to_pylist() if "timestamp" in arrow.column_names else [None] * arrow.num_rows
        starts = arrow["start"].to_pylist() if "start" in arrow.column_names else [None] * arrow.num_rows
        ends = arrow["end"].to_pylist() if "end" in arrow.column_names else [None] * arrow.num_rows
        paths = arrow["video_path"].to_pylist()
        video_ids = (
            arrow["video_id"].to_pylist()
            if "video_id" in arrow.column_names
            else [""] * arrow.num_rows
        )
        distances = arrow["_distance"].to_pylist()
        vectors = arrow["vector"].to_pylist()
        for index in range(arrow.num_rows):
            vector = np.asarray(vectors[index], dtype=np.float32).reshape(-1)
            rows.append(
                LanceSearchRow(
                    score=_lance_distance_to_score(float(distances[index])),
                    video_path=str(paths[index] or ""),
                    video_id=str(video_ids[index] or ""),
                    timestamp=float(timestamps[index]) if timestamps[index] is not None else None,
                    start=float(starts[index]) if starts[index] is not None else None,
                    end=float(ends[index]) if ends[index] is not None else None,
                    vector=vector,
                )
            )
        self._last_rows = rows
        return rows

    def search(self, query_vector, top_k: int):
        rows = self.search_rows(query_vector, top_k)
        empty = np.empty((1, 0), dtype=np.float32)
        empty_ids = np.full((1, 0), -1, dtype=np.int64)
        if not rows:
            return empty, empty_ids
        scores = np.asarray([row.score for row in rows], dtype=np.float32).reshape(1, -1)
        indices = np.arange(len(rows), dtype=np.int64).reshape(1, -1)
        return scores, indices

    def reconstruct(self, index_value: int):
        idx = int(index_value)
        if idx < 0 or idx >= len(self._last_rows):
            raise IndexError(index_value)
        vector = self._last_rows[idx].vector
        if vector is None:
            raise IndexError(index_value)
        return np.asarray(vector, dtype=np.float32)

    def fetch_neighbor_rows(
        self,
        *,
        video_path: str,
        center_sec: float,
        window_sec: float,
        limit: int = 512,
    ) -> list[LanceSearchRow]:
        normalized_path = str(video_path or "").strip()
        if not normalized_path:
            return []
        center = float(center_sec)
        window = max(0.0, float(window_sec))
        lo = center - window
        hi = center + window
        predicates = [
            f"video_path = {_sql_literal(normalized_path)}",
            f"timestamp >= {lo}",
            f"timestamp <= {hi}",
        ]
        if self._where:
            predicates.insert(0, f"({self._where})")
        where = " AND ".join(predicates)
        try:
            arrow = (
                self._table.search()
                .where(where)
                .select(["timestamp", "video_path", "vector"])
                .limit(max(int(limit), 1))
                .to_arrow()
            )
        except Exception as exc:
            logger.debug("Lance neighbor fetch failed for %s: %s", normalized_path, exc)
            return []
        rows: list[LanceSearchRow] = []
        if arrow.num_rows <= 0:
            return rows
        timestamps = arrow["timestamp"].to_pylist()
        paths = arrow["video_path"].to_pylist()
        vectors = arrow["vector"].to_pylist()
        for index in range(arrow.num_rows):
            rows.append(
                LanceSearchRow(
                    score=0.0,
                    video_path=str(paths[index] or ""),
                    timestamp=float(timestamps[index]),
                    vector=np.asarray(vectors[index], dtype=np.float32).reshape(-1),
                )
            )
        return rows


class InMemoryFlatSearchIndex:
    """Minimal IndexFlatIP-compatible index for normalized vectors."""

    def __init__(self, vectors: np.ndarray):
        matrix = _normalize_vectors(np.asarray(vectors, dtype=np.float32))
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.size == 0:
            matrix = np.empty((0, 0), dtype=np.float32)
        self._vectors = matrix
        self.d = int(matrix.shape[1]) if matrix.ndim == 2 and matrix.shape[0] > 0 else 0
        self.ntotal = int(matrix.shape[0]) if matrix.ndim == 2 else 0

    @property
    def vectors(self) -> np.ndarray:
        return self._vectors

    def search(self, query_vector, top_k: int):
        actual_k = min(int(top_k), self.ntotal)
        empty = np.empty((1, 0), dtype=np.float32)
        if actual_k <= 0:
            return empty, np.full((1, 0), -1, dtype=np.int64)

        query = np.asarray(query_vector, dtype=np.float32)
        if query.ndim == 1:
            query = query.reshape(1, -1)
        if query.shape[0] != 1:
            raise RuntimeError("InMemoryFlatSearchIndex expects a single query row")
        if self.d > 0 and query.shape[1] != self.d:
            raise RuntimeError(
                f"Search index dimension mismatch (query={query.shape[1]}, index={self.d})"
            )

        query_row = query[0]
        scores = self._vectors @ query_row
        if actual_k >= len(scores):
            order = np.argsort(-scores, kind="stable")
        else:
            partition = np.argpartition(-scores, actual_k - 1)[:actual_k]
            order = partition[np.argsort(-scores[partition], kind="stable")]
        selected = order[:actual_k]
        distances = scores[selected].astype(np.float32).reshape(1, -1)
        indices = selected.astype(np.int64).reshape(1, -1)
        return distances, indices

    def reconstruct(self, index_value: int):
        idx = int(index_value)
        if idx < 0 or idx >= self.ntotal:
            raise IndexError(index_value)
        return np.asarray(self._vectors[idx], dtype=np.float32)


def lance_search_is_ready(profile_base_dir: str) -> bool:
    profile_base_dir = os.path.normpath(profile_base_dir)
    state_mtime = _lance_state_mtime(profile_base_dir)
    cached = _READY_CACHE.get(profile_base_dir)
    if cached is not None and cached[0] == state_mtime:
        return cached[1]

    result = False
    lance_dir = get_lance_dir(profile_base_dir)
    if os.path.isdir(lance_dir):
        try:
            db = _connect_lance(profile_base_dir)
            if FRAMES_TABLE_NAME in _list_table_names(db):
                result = db.open_table(FRAMES_TABLE_NAME).count_rows() > 0
        except Exception as exc:
            logger.debug("Lance search readiness check failed for %s: %s", profile_base_dir, exc)
    _READY_CACHE[profile_base_dir] = (state_mtime, result)
    return result


def get_lance_indexed_video_ids(profile_base_dir: str) -> frozenset[str]:
    profile_base_dir = os.path.normpath(profile_base_dir)
    if not lance_search_is_ready(profile_base_dir):
        return frozenset()
    state_mtime = _lance_state_mtime(profile_base_dir)
    cached = _INDEXED_VIDEO_IDS_CACHE.get(profile_base_dir)
    if cached is not None and cached[0] == state_mtime:
        return cached[1]

    db = _connect_lance(profile_base_dir)
    if FRAMES_TABLE_NAME not in _list_table_names(db):
        return frozenset()
    table = db.open_table(FRAMES_TABLE_NAME)
    try:
        arrow = _load_columns_arrow(table, ["video_id"])
    except Exception as exc:
        logger.debug("Failed to list Lance video ids for %s: %s", profile_base_dir, exc)
        return frozenset()
    if arrow.num_rows <= 0:
        ids = frozenset()
    else:
        ids = frozenset(str(value) for value in arrow["video_id"].to_pylist() if value)
    _INDEXED_VIDEO_IDS_CACHE[profile_base_dir] = (state_mtime, ids)
    return ids


def lance_video_has_vectors(profile_base_dir: str, video_id: str) -> bool:
    video_id = str(video_id or "").strip()
    if not video_id or not lance_search_is_ready(profile_base_dir):
        return False
    try:
        db = _connect_lance(profile_base_dir)
        if FRAMES_TABLE_NAME not in _list_table_names(db):
            return False
        table = db.open_table(FRAMES_TABLE_NAME)
        where = _build_scope_where(video_id=video_id)
        if where:
            return int(table.count_rows(filter=where)) > 0
        return int(table.count_rows()) > 0
    except Exception as exc:
        logger.debug("Failed to probe Lance vectors for %s: %s", video_id, exc)
        return False


def get_lance_video_library_path(profile_base_dir: str, video_id: str) -> str:
    """Return one stored ``library_path`` for ``video_id``, or empty string."""
    video_id = str(video_id or "").strip()
    if not video_id or not lance_search_is_ready(profile_base_dir):
        return ""
    try:
        db = _connect_lance(profile_base_dir)
        if FRAMES_TABLE_NAME not in _list_table_names(db):
            return ""
        table = db.open_table(FRAMES_TABLE_NAME)
        where = _build_scope_where(video_id=video_id)
        builder = table.search().select(["library_path"])
        if where:
            builder = builder.where(where)
        arrow = builder.limit(1).to_arrow()
        if arrow.num_rows <= 0 or "library_path" not in arrow.column_names:
            return ""
        return canonicalize_library_path(str(arrow["library_path"][0].as_py() or ""))
    except Exception as exc:
        logger.debug("Failed to read Lance library_path for %s: %s", video_id, exc)
        return ""


def _count_video_ids_in_table(table, *, column: str = "video_id") -> dict[str, int]:
    from collections import Counter

    try:
        arrow = _load_columns_arrow(table, [column])
    except Exception as exc:
        logger.debug("Failed to count Lance %s values: %s", column, exc)
        return {}
    if arrow.num_rows <= 0 or column not in arrow.column_names:
        return {}
    return {
        str(value): int(count)
        for value, count in Counter(
            str(value) for value in arrow[column].to_pylist() if value
        ).items()
    }


def get_lance_video_row_counts(profile_base_dir: str) -> dict[str, dict[str, int]]:
    """Batch-read per-video frame/chunk row counts from Lance tables."""
    profile_base_dir = os.path.normpath(profile_base_dir)
    if not lance_search_is_ready(profile_base_dir):
        return {}
    state_mtime = _lance_state_mtime(profile_base_dir)
    cached = _VIDEO_ROW_COUNTS_CACHE.get(profile_base_dir)
    if cached is not None and cached[0] == state_mtime:
        return cached[1]

    counts: dict[str, dict[str, int]] = {}
    try:
        db = _connect_lance(profile_base_dir)
        table_names = _list_table_names(db)
        if FRAMES_TABLE_NAME in table_names:
            for video_id, frame_count in _count_video_ids_in_table(db.open_table(FRAMES_TABLE_NAME)).items():
                counts.setdefault(video_id, {"frame_count": 0, "chunk_count": 0})["frame_count"] = frame_count
        if CHUNKS_TABLE_NAME in table_names:
            for video_id, chunk_count in _count_video_ids_in_table(db.open_table(CHUNKS_TABLE_NAME)).items():
                counts.setdefault(video_id, {"frame_count": 0, "chunk_count": 0})["chunk_count"] = chunk_count
    except Exception as exc:
        logger.debug("Failed to read Lance per-video row counts for %s: %s", profile_base_dir, exc)
        counts = {}

    _VIDEO_ROW_COUNTS_CACHE[profile_base_dir] = (state_mtime, counts)
    return counts


def _lance_cache_key(profile_base_dir: str, *, library_path: str = "", table_name: str = FRAMES_TABLE_NAME) -> tuple | None:
    lance_dir = get_lance_dir(profile_base_dir)
    state_file = get_lance_state_file(profile_base_dir)
    try:
        return (
            os.path.abspath(lance_dir),
            os.path.getmtime(state_file),
            table_name,
            os.path.normcase(library_path or ""),
        )
    except OSError:
        return None


def _table_to_arrays(table, *, library_path: str = "", video_id: str = ""):
    normalized_library = canonicalize_library_path(library_path) if library_path else ""
    normalized_video = str(video_id or "").strip()
    arrow = _load_table_arrow(
        table,
        library_path=normalized_library,
        video_id=normalized_video,
    )
    if "frame_index" in arrow.column_names:
        import pyarrow.compute as pc

        indices = pc.sort_indices(arrow, sort_keys=[("frame_index", "ascending")])
        arrow = arrow.take(indices)
    if arrow.num_rows <= 0:
        return None, None, None

    timestamps = np.asarray(arrow["timestamp"].to_numpy(zero_copy_only=False), dtype=np.float32).reshape(-1)
    video_paths = [str(value) for value in arrow["video_path"].to_pylist()]
    vectors = _vectors_from_arrow_column(arrow["vector"], arrow.num_rows)
    if vectors.ndim != 2 or len(video_paths) != vectors.shape[0] or len(timestamps) != vectors.shape[0]:
        raise RuntimeError("Invalid Lance frame table shape")
    return vectors, timestamps, video_paths


def _chunk_table_to_arrays(table, *, library_path: str = "", video_id: str = ""):
    normalized_library = canonicalize_library_path(library_path) if library_path else ""
    normalized_video = str(video_id or "").strip()
    arrow = _load_table_arrow(
        table,
        library_path=normalized_library,
        video_id=normalized_video,
    )
    if arrow.num_rows <= 0:
        return None, None, None

    starts = np.asarray(arrow["start"].to_numpy(zero_copy_only=False), dtype=np.float32).reshape(-1)
    ends = np.asarray(arrow["end"].to_numpy(zero_copy_only=False), dtype=np.float32).reshape(-1)
    video_paths = [str(value) for value in arrow["video_path"].to_pylist()]
    vectors = _vectors_from_arrow_column(arrow["vector"], arrow.num_rows)
    ranges = np.stack([starts, ends], axis=1).astype(np.float32)
    if vectors.ndim != 2 or len(video_paths) != vectors.shape[0] or len(ranges) != vectors.shape[0]:
        raise RuntimeError("Invalid Lance chunk table shape")
    return vectors, ranges, video_paths


def _open_lance_table(profile_base_dir: str, table_name: str):
    db = _connect_lance(profile_base_dir)
    if table_name not in _list_table_names(db):
        return None
    return db.open_table(table_name)


def _should_materialize_in_memory(*, library_path: str = "", video_id: str = "") -> bool:
    return bool(str(video_id or "").strip())


def load_lance_frame_search_assets(profile_base_dir: str, *, library_path: str = "", video_id: str = ""):
    if not lance_search_is_ready(profile_base_dir):
        return None, None, None
    table = _open_lance_table(profile_base_dir, FRAMES_TABLE_NAME)
    if table is None:
        return None, None, None

    if not _should_materialize_in_memory(library_path=library_path, video_id=video_id):
        where = _build_scope_where(library_path=library_path, video_id=video_id)
        return LanceTableSearchIndex(table, where=where, is_chunk=False), None, None

    normalized_library = canonicalize_library_path(library_path) if library_path else ""
    try:
        vectors, timestamps, video_paths = _table_to_arrays(
            table,
            library_path=normalized_library,
            video_id=str(video_id or "").strip(),
        )
    except Exception as exc:
        logger.error("Failed to load Lance frame search assets: %s", exc)
        return None, None, None
    if vectors is None:
        return None, None, None
    return InMemoryFlatSearchIndex(vectors), timestamps, video_paths


def load_lance_chunk_search_assets(profile_base_dir: str, *, library_path: str = ""):
    if not lance_search_is_ready(profile_base_dir):
        return None, None, None
    table = _open_lance_table(profile_base_dir, CHUNKS_TABLE_NAME)
    if table is None:
        return None, None, None

    if not _should_materialize_in_memory(library_path=library_path):
        where = _build_scope_where(library_path=library_path)
        return LanceTableSearchIndex(table, where=where, is_chunk=True), None, None

    normalized_library = canonicalize_library_path(library_path) if library_path else ""
    try:
        vectors, ranges, video_paths = _chunk_table_to_arrays(table, library_path=normalized_library)
    except Exception as exc:
        logger.error("Failed to load Lance chunk search assets: %s", exc)
        return None, None, None
    if vectors is None:
        return None, None, None
    return InMemoryFlatSearchIndex(vectors), ranges, video_paths


def lance_cache_key_for_profile(profile_base_dir: str, *, library_path: str = "", table_name: str = FRAMES_TABLE_NAME):
    return _lance_cache_key(profile_base_dir, library_path=library_path, table_name=table_name)


def load_lance_video_frame_arrays(profile_base_dir: str, video_id: str):
    if not lance_search_is_ready(profile_base_dir):
        return None, None
    db = _connect_lance(profile_base_dir)
    if FRAMES_TABLE_NAME not in _list_table_names(db):
        return None, None
    table = db.open_table(FRAMES_TABLE_NAME)
    try:
        vectors, timestamps, _paths = _table_to_arrays(
            table,
            video_id=str(video_id or "").strip(),
        )
    except Exception as exc:
        logger.error("Failed to load Lance frame vectors for %s: %s", video_id, exc)
        return None, None
    if vectors is None:
        return None, None
    return vectors, timestamps


def load_lance_video_chunks(profile_base_dir: str, video_id: str):
    if not lance_search_is_ready(profile_base_dir):
        return []
    db = _connect_lance(profile_base_dir)
    if CHUNKS_TABLE_NAME not in _list_table_names(db):
        return []
    table = db.open_table(CHUNKS_TABLE_NAME)
    try:
        vectors, ranges, _paths = _chunk_table_to_arrays(
            table,
            video_id=str(video_id or "").strip(),
        )
    except Exception as exc:
        logger.error("Failed to load Lance chunks for %s: %s", video_id, exc)
        return []
    if vectors is None:
        return []
    chunks = []
    for index in range(len(vectors)):
        chunks.append(
            {
                "start": float(ranges[index][0]),
                "end": float(ranges[index][1]),
                "embedding": vectors[index],
            }
        )
    return chunks
