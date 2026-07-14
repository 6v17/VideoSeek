"""LanceDB vector storage for local search (frames/chunks tables, upsert, compact)."""

from __future__ import annotations

import json
import os
from typing import Callable

import numpy as np
import pyarrow as pa

from src.app.logging_utils import get_logger
from src.core.faiss_index import _normalize_vectors, load_vectors
from src.core.semantic_chunking import unpack_chunks
from src.storage.asset_store import load_metadata
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("lance_store")

LANCE_DIR_NAME = "lance"
FRAMES_TABLE_NAME = "frames"
CHUNKS_TABLE_NAME = "chunks"
LANCE_STORAGE_VERSION = 1
LANCE_ANN_MIN_ROWS = 2000
LANCE_ANN_ENABLED = False
_INDEX_BATCH_DEPTH: dict[str, int] = {}
_INDEX_BATCH_PROGRESS: dict[str, ProgressCallback | None] = {}
META_PERSIST_INTERVAL = 25

ProgressCallback = Callable[[int, str], None]

_FRAME_ROW_META_BYTES = 72
_CHUNK_ROW_META_BYTES = 64


def directory_size_bytes(path: str) -> int:
    normalized = os.path.normpath(str(path or ""))
    if not normalized or not os.path.exists(normalized):
        return 0
    if os.path.isfile(normalized):
        try:
            return os.path.getsize(normalized)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(normalized):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def format_byte_size(value) -> str:
    size = float(value or 0)
    if size <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} B"
    return f"{size:.1f} {units[unit_index]}"


def estimate_lance_video_payload_bytes(frame_count: int, chunk_count: int, *, dimension: int) -> int:
    dim = max(int(dimension or 0), 0)
    frames = max(int(frame_count or 0), 0)
    chunks = max(int(chunk_count or 0), 0)
    vector_bytes = (frames + chunks) * dim * 4
    meta_bytes = frames * _FRAME_ROW_META_BYTES + chunks * _CHUNK_ROW_META_BYTES
    return vector_bytes + meta_bytes


def allocate_lance_dir_bytes_by_weight(lance_dir_bytes: int, weights: dict[str, int]) -> dict[str, int]:
    total_weight = sum(max(int(value or 0), 0) for value in weights.values())
    if lance_dir_bytes <= 0 or total_weight <= 0:
        return {video_id: 0 for video_id in weights}
    allocated = {
        video_id: int(lance_dir_bytes * max(int(weight or 0), 0) / total_weight)
        for video_id, weight in weights.items()
    }
    remainder = int(lance_dir_bytes) - sum(allocated.values())
    if remainder > 0:
        target_video_id = max(weights, key=lambda video_id: max(int(weights.get(video_id, 0) or 0), 0))
        allocated[target_video_id] = allocated.get(target_video_id, 0) + remainder
    return allocated


def sum_legacy_vector_npy_bytes(vector_dir: str) -> int:
    folder = os.path.normpath(str(vector_dir or ""))
    if not folder or not os.path.isdir(folder):
        return 0
    total = 0
    for name in os.listdir(folder):
        if not name.lower().endswith("_vectors.npy"):
            continue
        file_path = os.path.join(folder, name)
        if not os.path.isfile(file_path):
            continue
        try:
            total += os.path.getsize(file_path)
        except OSError:
            continue
    return total


def get_lance_dir(profile_base_dir: str) -> str:
    return os.path.join(os.path.normpath(profile_base_dir), LANCE_DIR_NAME)


def get_lance_state_file(profile_base_dir: str) -> str:
    return os.path.join(get_lance_dir(profile_base_dir), "import_state.json")


def begin_lance_index_batch(profile_base_dir: str, progress_callback: ProgressCallback | None = None) -> None:
    key = os.path.normpath(str(profile_base_dir or ""))
    if not key:
        return
    _INDEX_BATCH_DEPTH[key] = int(_INDEX_BATCH_DEPTH.get(key, 0) or 0) + 1
    if progress_callback is not None:
        _INDEX_BATCH_PROGRESS[key] = progress_callback


def end_lance_index_batch(profile_base_dir: str) -> None:
    key = os.path.normpath(str(profile_base_dir or ""))
    if not key:
        return
    depth = int(_INDEX_BATCH_DEPTH.get(key, 0) or 0)
    if depth <= 1:
        _INDEX_BATCH_DEPTH.pop(key, None)
        progress_callback = _INDEX_BATCH_PROGRESS.pop(key, None)
        refresh_import_state(key)
        _invalidate_lance_search_caches(key)
        drop_lance_vector_indexes(key)
        if LANCE_ANN_ENABLED:
            ensure_lance_vector_indexes(key, progress_callback=progress_callback)
        return
    _INDEX_BATCH_DEPTH[key] = depth - 1


def lance_index_batch_active(profile_base_dir: str) -> bool:
    key = os.path.normpath(str(profile_base_dir or ""))
    return int(_INDEX_BATCH_DEPTH.get(key, 0) or 0) > 0


def _count_profile_ready_videos(profile_base_dir: str) -> int:
    meta_file = os.path.join(os.path.normpath(profile_base_dir), "meta.json")
    if not os.path.isfile(meta_file):
        return 0
    meta = load_metadata(meta_file)
    count = 0
    for lib_data in (meta.get("libraries") or {}).values():
        for info in (lib_data.get("files") or {}).values():
            if str(info.get("asset_state", "")).strip().lower() != "ready":
                continue
            if str(info.get("vid", "") or "").strip():
                count += 1
    return count


def _finalize_lance_maintenance(profile_base_dir: str) -> None:
    refresh_import_state(profile_base_dir)
    _invalidate_lance_search_caches(profile_base_dir)


def _lance_vector_index_status(table) -> tuple[bool, int]:
    try:
        indices = table.list_indices()
    except Exception:
        return False, 0
    for index in indices or []:
        columns = list(getattr(index, "columns", None) or [])
        if "vector" not in columns:
            continue
        unindexed = int(getattr(index, "num_unindexed_rows", 0) or 0)
        return True, unindexed
    return False, 0


def ensure_lance_vector_indexes(
    profile_base_dir: str,
    *,
    progress_callback: ProgressCallback | None = None,
    min_rows: int = LANCE_ANN_MIN_ROWS,
) -> dict:
    """Optional IVF_PQ index for speed; disabled by default because it reduces recall accuracy."""
    if not LANCE_ANN_ENABLED:
        return {"built": [], "skipped": ["disabled"]}

    from lancedb.index import IvfPq

    profile_base_dir = os.path.normpath(profile_base_dir)
    if not os.path.isdir(get_lance_dir(profile_base_dir)):
        return {"built": [], "skipped": []}

    db = _connect_lance(profile_base_dir)
    built: list[str] = []
    skipped: list[str] = []
    for table_name in (FRAMES_TABLE_NAME, CHUNKS_TABLE_NAME):
        if table_name not in _list_table_names(db):
            skipped.append(table_name)
            continue
        table = db.open_table(table_name)
        row_count = int(table.count_rows())
        if row_count < max(int(min_rows or 0), 1):
            skipped.append(table_name)
            continue
        has_index, unindexed_rows = _lance_vector_index_status(table)
        if has_index and unindexed_rows <= 0:
            skipped.append(table_name)
            continue
        if progress_callback:
            progress_callback(
                96,
                f"index_progress|lance_index|0|0|{row_count}|{row_count}|{table_name}",
            )
        num_partitions = max(16, min(256, int(row_count**0.5)))
        try:
            table.create_index(
                "vector",
                config=IvfPq(
                    distance_type="cosine",
                    num_partitions=num_partitions,
                    num_sub_vectors=16,
                ),
                replace=not has_index,
            )
            built.append(table_name)
        except Exception as exc:
            logger.warning("Failed to build Lance ANN index for %s: %s", table_name, exc)
            skipped.append(table_name)
    return {"built": built, "skipped": skipped}


def drop_lance_vector_indexes(profile_base_dir: str) -> dict:
    """Remove IVF/PQ ANN indexes so Lance falls back to exact vector search."""
    profile_base_dir = os.path.normpath(profile_base_dir)
    if not os.path.isdir(get_lance_dir(profile_base_dir)):
        return {"dropped": []}

    db = _connect_lance(profile_base_dir)
    dropped: list[str] = []
    for table_name in (FRAMES_TABLE_NAME, CHUNKS_TABLE_NAME):
        if table_name not in _list_table_names(db):
            continue
        table = db.open_table(table_name)
        try:
            indices = table.list_indices()
        except Exception as exc:
            logger.debug("Failed to list Lance indices for %s: %s", table_name, exc)
            continue
        for index in indices or []:
            columns = list(getattr(index, "columns", None) or [])
            if "vector" not in columns:
                continue
            index_name = str(getattr(index, "name", "") or "vector_idx")
            try:
                table.drop_index(index_name)
                dropped.append(f"{table_name}:{index_name}")
            except Exception as exc:
                logger.warning("Failed to drop Lance index %s on %s: %s", index_name, table_name, exc)
    if dropped:
        refresh_import_state(profile_base_dir)
        _invalidate_lance_search_caches(profile_base_dir)
    return {"dropped": dropped}


def compact_lance_storage(profile_base_dir: str) -> None:
    profile_base_dir = os.path.normpath(profile_base_dir)
    if not os.path.isdir(get_lance_dir(profile_base_dir)):
        return
    try:
        db = _connect_lance(profile_base_dir)
        for table_name in (FRAMES_TABLE_NAME, CHUNKS_TABLE_NAME):
            if table_name not in _list_table_names(db):
                continue
            db.open_table(table_name).optimize()
        refresh_import_state(profile_base_dir)
        _invalidate_lance_search_caches(profile_base_dir)
    except Exception as exc:
        logger.warning("Failed to compact Lance storage for %s: %s", profile_base_dir, exc)


def collect_meta_video_ids(meta) -> set[str]:
    valid_ids = set()
    for lib_data in (meta.get("libraries") or {}).values():
        for info in (lib_data.get("files") or {}).values():
            video_id = str(info.get("vid", "") or "").strip()
            if video_id:
                valid_ids.add(video_id)
    return valid_ids


def garbage_collect_orphan_lance_videos(meta, config=None) -> list[str]:
    from src.storage.config_store import get_local_model_asset_dirs
    from src.storage.lance_search_index import get_lance_indexed_video_ids, lance_search_is_ready

    model_dirs = get_local_model_asset_dirs(config=config)
    profile_base_dir = os.path.normpath(model_dirs["base_dir"])
    if not lance_search_is_ready(profile_base_dir):
        return []

    valid_ids = collect_meta_video_ids(meta)
    orphan_ids = sorted(get_lance_indexed_video_ids(profile_base_dir) - valid_ids)
    if not orphan_ids:
        return []

    for video_id in orphan_ids:
        delete_profile_video_vectors(video_id, config=config)
    compact_lance_storage(profile_base_dir)
    return orphan_ids


def read_lance_profile_summary(profile_base_dir: str, *, include_dir_size: bool = True) -> dict:
    """Read-only Lance table stats for diagnostics UI (does not rewrite import_state)."""
    from src.storage.lance_search_index import get_lance_indexed_video_ids, lance_search_is_ready

    profile_base_dir = os.path.normpath(profile_base_dir)
    summary = {
        "ready": False,
        "frame_rows": 0,
        "chunk_rows": 0,
        "indexed_video_count": 0,
        "dimension": 0,
        "lance_dir_bytes": 0,
    }
    if not os.path.isdir(get_lance_dir(profile_base_dir)):
        return summary
    try:
        if include_dir_size:
            summary["lance_dir_bytes"] = directory_size_bytes(get_lance_dir(profile_base_dir))
        summary["ready"] = lance_search_is_ready(profile_base_dir)
        summary["indexed_video_count"] = len(get_lance_indexed_video_ids(profile_base_dir))
        db = _connect_lance(profile_base_dir)
        if FRAMES_TABLE_NAME in _list_table_names(db):
            table = db.open_table(FRAMES_TABLE_NAME)
            summary["frame_rows"] = int(table.count_rows())
            if summary["frame_rows"] > 0:
                sample = table.search().select(["vector"]).limit(1).to_arrow()
                vector_value = sample["vector"][0].as_py()
                summary["dimension"] = len(vector_value or [])
        if CHUNKS_TABLE_NAME in _list_table_names(db):
            summary["chunk_rows"] = int(db.open_table(CHUNKS_TABLE_NAME).count_rows())
    except Exception as exc:
        logger.debug("Failed to read Lance profile summary for %s: %s", profile_base_dir, exc)
    return summary


def _vector_field_name(dimension: int) -> pa.Field:
    return pa.field("vector", pa.list_(pa.float32(), dimension))


def frames_table_schema(dimension: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("video_id", pa.string()),
            pa.field("library_path", pa.string()),
            pa.field("video_path", pa.string()),
            pa.field("frame_index", pa.int32()),
            pa.field("timestamp", pa.float32()),
            _vector_field_name(dimension),
        ]
    )


def chunks_table_schema(dimension: int) -> pa.Schema:
    return pa.schema(
        [
            pa.field("video_id", pa.string()),
            pa.field("library_path", pa.string()),
            pa.field("video_path", pa.string()),
            pa.field("start", pa.float32()),
            pa.field("end", pa.float32()),
            _vector_field_name(dimension),
        ]
    )


def _read_import_state(profile_base_dir: str) -> dict:
    state_file = get_lance_state_file(profile_base_dir)
    if not os.path.isfile(state_file):
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unreadable Lance import state %s: %s", state_file, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_import_state(profile_base_dir: str, payload: dict) -> None:
    lance_dir = get_lance_dir(profile_base_dir)
    os.makedirs(lance_dir, exist_ok=True)
    state_file = get_lance_state_file(profile_base_dir)
    temp_path = f"{state_file}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, state_file)


def _merge_import_state_videos(previous: dict, payload: dict) -> dict:
    merged = dict(payload)
    if isinstance(previous.get("videos"), dict):
        merged["videos"] = previous["videos"]
    return merged


def get_stored_chunk_config(profile_base_dir: str, video_id: str):
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    state = _read_import_state(profile_base_dir)
    videos = state.get("videos")
    if not isinstance(videos, dict):
        return None
    entry = videos.get(video_id)
    if not isinstance(entry, dict):
        return None
    return entry.get("chunk_config")


def set_stored_chunk_config(profile_base_dir: str, video_id: str, chunk_config: dict) -> None:
    video_id = str(video_id or "").strip()
    if not video_id or not isinstance(chunk_config, dict):
        return
    state = _read_import_state(profile_base_dir)
    videos = dict(state.get("videos") or {})
    entry = dict(videos.get(video_id) or {})
    entry["chunk_config"] = dict(chunk_config)
    videos[video_id] = entry
    state["videos"] = videos
    _write_import_state(profile_base_dir, state)


def _connect_lance(profile_base_dir: str):
    import lancedb

    lance_dir = get_lance_dir(profile_base_dir)
    os.makedirs(lance_dir, exist_ok=True)
    return lancedb.connect(lance_dir)


def _video_id_from_vector_file(file_name: str) -> str:
    suffix = "_vectors.npy"
    lower = file_name.lower()
    if not lower.endswith(suffix):
        return ""
    return file_name[: -len(suffix)]


def build_video_lookup(meta: dict) -> dict[str, dict[str, str]]:
    """Map video_id -> {library_path, video_path} from profile meta.json."""
    lookup: dict[str, dict[str, str]] = {}
    libraries = (meta or {}).get("libraries") or {}
    if not isinstance(libraries, dict):
        return lookup

    for root_path, lib_data in libraries.items():
        if not isinstance(lib_data, dict):
            continue
        library_path = canonicalize_library_path(root_path)
        files = lib_data.get("files") or {}
        if not isinstance(files, dict):
            continue
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            video_id = str(info.get("vid", "") or "").strip()
            if not video_id:
                continue
            abs_path = os.path.normpath(os.path.join(root_path, rel_path))
            lookup[video_id] = {
                "library_path": library_path,
                "video_path": abs_path,
            }
    return lookup


def _infer_vector_dimension(vectors) -> int:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim == 1:
        return int(array.shape[0])
    if array.ndim >= 2:
        return int(array.shape[1])
    return 0


def _vectors_to_fixed_list(vectors, dimension: int) -> list[list[float]]:
    array = _normalize_vectors(vectors)
    if array.size == 0:
        return []
    if array.shape[1] != dimension:
        raise ValueError(f"Expected vector dimension {dimension}, got {array.shape[1]}")
    return array.tolist()


def _build_frame_rows(
    video_id: str,
    vectors,
    timestamps,
    *,
    library_path: str,
    video_path: str,
    dimension: int,
) -> list[dict]:
    vector_rows = _vectors_to_fixed_list(vectors, dimension)
    timestamp_values = np.asarray(timestamps, dtype=np.float32).reshape(-1)
    if len(vector_rows) != len(timestamp_values):
        raise ValueError(
            f"Mismatched vector/timestamp counts for {video_id}: "
            f"{len(vector_rows)} vs {len(timestamp_values)}"
        )
    return [
        {
            "video_id": video_id,
            "library_path": library_path,
            "video_path": video_path,
            "frame_index": int(frame_index),
            "timestamp": float(timestamp_values[frame_index]),
            "vector": vector_rows[frame_index],
        }
        for frame_index in range(len(vector_rows))
    ]


def _build_chunk_rows(
    video_id: str,
    chunks,
    *,
    library_path: str,
    video_path: str,
    dimension: int,
) -> list[dict]:
    rows = []
    for chunk in chunks or []:
        embedding = np.asarray(chunk.get("embedding"), dtype=np.float32).reshape(-1)
        if embedding.size == 0:
            continue
        if embedding.shape[0] != dimension:
            raise ValueError(
                f"Chunk dimension mismatch for {video_id}: expected {dimension}, got {embedding.shape[0]}"
            )
        norm = float(np.linalg.norm(embedding))
        if norm > 0:
            embedding = embedding / norm
        rows.append(
            {
                "video_id": video_id,
                "library_path": library_path,
                "video_path": video_path,
                "start": float(chunk.get("start", 0.0)),
                "end": float(chunk.get("end", 0.0)),
                "vector": embedding.astype(np.float32).tolist(),
            }
        )
    return rows


def _list_table_names(db) -> list[str]:
    list_tables = getattr(db, "list_tables", None)
    if callable(list_tables):
        result = list_tables()
        tables = getattr(result, "tables", None)
        if isinstance(tables, list):
            return [str(name) for name in tables]
        if isinstance(result, list):
            return [str(name) for name in result]
    table_names = getattr(db, "table_names", None)
    if callable(table_names):
        return [str(name) for name in table_names()]
    return []


def _append_rows_to_table(db, table_name: str, schema: pa.Schema, rows: list[dict]):
    if not rows:
        return
    if table_name not in _list_table_names(db):
        db.create_table(table_name, data=rows, schema=schema)
        return
    db.open_table(table_name).add(rows)


def _delete_video_rows(db, table_name: str, video_id: str) -> None:
    if table_name not in _list_table_names(db):
        return
    table = db.open_table(table_name)
    safe_id = video_id.replace("'", "''")
    table.delete(f"video_id = '{safe_id}'")


def import_video_npy_to_lance(
    db,
    *,
    video_id: str,
    vector_file: str,
    video_lookup: dict[str, dict[str, str]],
    profile_base_dir: str = "",
    dimension: int | None = None,
    replace_existing: bool = True,
) -> dict:
    """Import one ``*_vectors.npy`` file into Lance tables."""
    stats = {
        "video_id": video_id,
        "vector_file": vector_file,
        "frame_rows": 0,
        "chunk_rows": 0,
        "skipped": False,
        "error": "",
    }
    if not video_id or not os.path.isfile(vector_file):
        stats["skipped"] = True
        return stats

    try:
        data = load_vectors(vector_file)
    except Exception as exc:
        stats["error"] = str(exc)
        return stats

    if not isinstance(data, dict):
        stats["error"] = "invalid payload"
        return stats

    vectors = data.get("vector")
    timestamps = data.get("timestamps")
    if vectors is None or timestamps is None:
        stats["error"] = "missing vector/timestamps"
        return stats

    resolved_dimension = int(dimension or _infer_vector_dimension(vectors))
    if resolved_dimension <= 0:
        stats["error"] = "invalid vector dimension"
        return stats

    location = video_lookup.get(video_id) or {}
    library_path = str(location.get("library_path", "") or "")
    video_path = str(location.get("video_path", "") or "")

    try:
        frame_rows = _build_frame_rows(
            video_id,
            vectors,
            timestamps,
            library_path=library_path,
            video_path=video_path,
            dimension=resolved_dimension,
        )
        chunk_rows = _build_chunk_rows(
            video_id,
            unpack_chunks(data.get("chunks")),
            library_path=library_path,
            video_path=video_path,
            dimension=resolved_dimension,
        )
    except ValueError as exc:
        stats["error"] = str(exc)
        return stats

    if replace_existing:
        _delete_video_rows(db, FRAMES_TABLE_NAME, video_id)
        _delete_video_rows(db, CHUNKS_TABLE_NAME, video_id)

    if frame_rows:
        _append_rows_to_table(db, FRAMES_TABLE_NAME, frames_table_schema(resolved_dimension), frame_rows)
        stats["frame_rows"] = len(frame_rows)
    if chunk_rows:
        _append_rows_to_table(db, CHUNKS_TABLE_NAME, chunks_table_schema(resolved_dimension), chunk_rows)
        stats["chunk_rows"] = len(chunk_rows)
    chunk_config = data.get("chunk_config")
    if isinstance(chunk_config, dict) and profile_base_dir:
        set_stored_chunk_config(profile_base_dir, video_id, chunk_config)
    return stats


def import_npy_to_lance(
    profile_base_dir: str,
    *,
    replace_existing: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """Import all per-video ``*_vectors.npy`` under one model profile into LanceDB."""
    profile_base_dir = os.path.normpath(profile_base_dir)
    meta_file = os.path.join(profile_base_dir, "meta.json")
    vector_dir = os.path.join(profile_base_dir, "vector")

    summary = {
        "profile_base_dir": profile_base_dir,
        "videos_total": 0,
        "videos_imported": 0,
        "videos_skipped": 0,
        "videos_failed": 0,
        "frame_rows": 0,
        "chunk_rows": 0,
        "dimension": 0,
        "errors": [],
    }

    if not os.path.isdir(vector_dir):
        summary["errors"].append(f"vector dir not found: {vector_dir}")
        return summary

    meta = load_metadata(meta_file) if os.path.isfile(meta_file) else {}
    video_lookup = build_video_lookup(meta)
    npy_files = sorted(
        name
        for name in os.listdir(vector_dir)
        if name.lower().endswith("_vectors.npy")
    )
    summary["videos_total"] = len(npy_files)
    if not npy_files:
        return summary

    db = _connect_lance(profile_base_dir)
    if replace_existing:
        for table_name in _list_table_names(db):
            db.drop_table(table_name)

    locked_dimension = 0
    for index, file_name in enumerate(npy_files, start=1):
        video_id = _video_id_from_vector_file(file_name)
        vector_file = os.path.join(vector_dir, file_name)
        if progress_callback:
            progress_callback(
                int(index * 100 / max(len(npy_files), 1)),
                f"{index}/{len(npy_files)} {file_name}",
            )

        per_video = import_video_npy_to_lance(
            db,
            video_id=video_id,
            vector_file=vector_file,
            video_lookup=video_lookup,
            profile_base_dir=profile_base_dir,
            dimension=locked_dimension or None,
            replace_existing=not replace_existing,
        )
        if per_video.get("error"):
            summary["videos_failed"] += 1
            summary["errors"].append(f"{file_name}: {per_video['error']}")
            continue
        if per_video.get("skipped"):
            summary["videos_skipped"] += 1
            continue

        summary["videos_imported"] += 1
        summary["frame_rows"] += int(per_video.get("frame_rows", 0))
        summary["chunk_rows"] += int(per_video.get("chunk_rows", 0))
        if not locked_dimension:
            try:
                data = load_vectors(vector_file)
                locked_dimension = _infer_vector_dimension(data.get("vector"))
                summary["dimension"] = locked_dimension
            except Exception:
                pass

    _write_import_state(
        profile_base_dir,
        _merge_import_state_videos(
            _read_import_state(profile_base_dir),
            {
                "storage_version": LANCE_STORAGE_VERSION,
                "profile_base_dir": profile_base_dir,
                "videos_total": summary["videos_total"],
                "videos_imported": summary["videos_imported"],
                "videos_failed": summary["videos_failed"],
                "frame_rows": summary["frame_rows"],
                "chunk_rows": summary["chunk_rows"],
                "dimension": summary["dimension"],
            },
        ),
    )
    return summary


def refresh_import_state(profile_base_dir: str) -> dict:
    profile_base_dir = os.path.normpath(profile_base_dir)
    db = _connect_lance(profile_base_dir)
    frame_rows = 0
    chunk_rows = 0
    dimension = 0
    if FRAMES_TABLE_NAME in _list_table_names(db):
        table = db.open_table(FRAMES_TABLE_NAME)
        frame_rows = int(table.count_rows())
        if frame_rows > 0:
            sample = table.search().select(["vector"]).limit(1).to_arrow()
            vector_value = sample["vector"][0].as_py()
            dimension = len(vector_value or [])
    if CHUNKS_TABLE_NAME in _list_table_names(db):
        chunk_rows = int(db.open_table(CHUNKS_TABLE_NAME).count_rows())
    vector_dir = os.path.join(profile_base_dir, "vector")
    videos_total = _count_profile_ready_videos(profile_base_dir)
    if os.path.isdir(vector_dir):
        npy_total = sum(1 for name in os.listdir(vector_dir) if name.lower().endswith("_vectors.npy"))
        videos_total = max(videos_total, npy_total)
    payload = _merge_import_state_videos(
        _read_import_state(profile_base_dir),
        {
            "storage_version": LANCE_STORAGE_VERSION,
            "profile_base_dir": profile_base_dir,
            "videos_total": videos_total,
            "videos_imported": videos_total,
            "videos_failed": 0,
            "frame_rows": frame_rows,
            "chunk_rows": chunk_rows,
            "dimension": dimension,
        },
    )
    _write_import_state(profile_base_dir, payload)
    return payload


def upsert_profile_video_vectors(
    video_id: str,
    config=None,
    *,
    library_path: str = "",
    video_path: str = "",
) -> dict:
    """Import one video from legacy ``*_vectors.npy`` into Lance.

    Hot-path indexing must use ``upsert_profile_video_vectors_from_arrays``.
    This helper remains for migration tooling and tests only.
    """
    logger.warning(
        "upsert_profile_video_vectors reads legacy npy for %s; prefer array upsert or startup migration",
        video_id,
    )
    from src.storage.config_store import get_local_model_asset_dirs

    video_id = str(video_id or "").strip()
    if not video_id:
        return {"error": "missing video_id"}

    model_dirs = get_local_model_asset_dirs(config=config)
    profile_base_dir = model_dirs["base_dir"]
    vector_file = os.path.join(model_dirs["vector_dir"], f"{video_id}_vectors.npy")
    if not os.path.isfile(vector_file):
        return {"error": f"vector file not found: {vector_file}"}

    meta = load_metadata(model_dirs["meta_file"]) if os.path.isfile(model_dirs["meta_file"]) else {}
    video_lookup = build_video_lookup(meta)
    if library_path and video_path:
        video_lookup[video_id] = {
            "library_path": canonicalize_library_path(library_path),
            "video_path": os.path.normpath(video_path),
        }

    db = _connect_lance(profile_base_dir)
    result = import_video_npy_to_lance(
        db,
        video_id=video_id,
        vector_file=vector_file,
        video_lookup=video_lookup,
        profile_base_dir=profile_base_dir,
        replace_existing=True,
    )
    refresh_import_state(profile_base_dir)
    _invalidate_lance_search_caches(profile_base_dir)
    return result


def delete_profile_video_vectors(video_id: str, config=None) -> None:
    from src.storage.config_store import get_local_model_asset_dirs

    video_id = str(video_id or "").strip()
    if not video_id:
        return
    model_dirs = get_local_model_asset_dirs(config=config)
    profile_base_dir = model_dirs["base_dir"]
    if not os.path.isdir(get_lance_dir(profile_base_dir)):
        return
    db = _connect_lance(profile_base_dir)
    _delete_video_rows(db, FRAMES_TABLE_NAME, video_id)
    _delete_video_rows(db, CHUNKS_TABLE_NAME, video_id)
    refresh_import_state(profile_base_dir)
    _invalidate_lance_search_caches(profile_base_dir)


def resolve_vector_search_backend(config=None) -> str:
    return "lance"


def should_use_lance_search(config=None, *, profile_base_dir: str = "") -> bool:
    from src.storage.config_store import get_local_model_asset_dirs
    from src.storage.lance_search_index import lance_search_is_ready

    base_dir = profile_base_dir or get_local_model_asset_dirs(config=config)["base_dir"]
    return lance_search_is_ready(base_dir)


def should_use_lance_storage(config=None, *, profile_base_dir: str = "") -> bool:
    """Vectors are always persisted to Lance."""
    return True


def _invalidate_lance_search_caches(profile_base_dir: str = "") -> None:
    try:
        from src.services.search_assets import invalidate_search_asset_caches
        from src.storage.lance_search_index import invalidate_lance_runtime_caches

        invalidate_lance_runtime_caches(profile_base_dir)
        invalidate_search_asset_caches()
    except Exception:
        pass


def video_has_lance_vectors(video_id: str, config=None) -> bool:
    from src.storage.config_store import get_local_model_asset_dirs
    from src.storage.lance_search_index import lance_video_has_vectors

    video_id = str(video_id or "").strip()
    if not video_id:
        return False
    model_dirs = get_local_model_asset_dirs(config=config)
    return lance_video_has_vectors(model_dirs["base_dir"], video_id)


def upsert_profile_video_vectors_from_arrays(
    video_id: str,
    vectors,
    timestamps,
    config=None,
    *,
    library_path: str = "",
    video_path: str = "",
    chunks=None,
    chunk_config=None,
) -> dict:
    from src.storage.config_store import get_local_model_asset_dirs

    video_id = str(video_id or "").strip()
    if not video_id:
        return {"error": "missing video_id"}

    model_dirs = get_local_model_asset_dirs(config=config)
    profile_base_dir = model_dirs["base_dir"]
    resolved_dimension = _infer_vector_dimension(vectors)
    if resolved_dimension <= 0:
        return {"error": "invalid vector dimension"}

    location = {
        "library_path": canonicalize_library_path(library_path) if library_path else "",
        "video_path": os.path.normpath(video_path) if video_path else "",
    }
    if chunks is None:
        from src.storage.lance_search_index import load_lance_video_chunks

        chunks = load_lance_video_chunks(profile_base_dir, video_id)
    try:
        frame_rows = _build_frame_rows(
            video_id,
            vectors,
            timestamps,
            library_path=location["library_path"],
            video_path=location["video_path"],
            dimension=resolved_dimension,
        )
        chunk_rows = _build_chunk_rows(
            video_id,
            chunks or [],
            library_path=location["library_path"],
            video_path=location["video_path"],
            dimension=resolved_dimension,
        )
    except ValueError as exc:
        return {"error": str(exc)}

    db = _connect_lance(profile_base_dir)
    _delete_video_rows(db, FRAMES_TABLE_NAME, video_id)
    _delete_video_rows(db, CHUNKS_TABLE_NAME, video_id)
    if frame_rows:
        _append_rows_to_table(db, FRAMES_TABLE_NAME, frames_table_schema(resolved_dimension), frame_rows)
    if chunk_rows:
        _append_rows_to_table(db, CHUNKS_TABLE_NAME, chunks_table_schema(resolved_dimension), chunk_rows)

    if isinstance(chunk_config, dict):
        set_stored_chunk_config(profile_base_dir, video_id, chunk_config)
    if not lance_index_batch_active(profile_base_dir):
        _finalize_lance_maintenance(profile_base_dir)
    return {
        "video_id": video_id,
        "frame_rows": len(frame_rows),
        "chunk_rows": len(chunk_rows),
        "error": "",
    }


def import_all_model_profiles_to_lance(
    config=None,
    *,
    replace_existing: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    from src.storage.video_id_migration import iter_model_asset_storage_roots

    summaries = []
    roots = list(iter_model_asset_storage_roots(config=config))
    for index, root in enumerate(roots, start=1):
        label = str(root.get("label", "") or root.get("base_dir", ""))
        if progress_callback:
            progress_callback(int((index - 1) * 100 / max(len(roots), 1)), f"profile {label}")
        summary = import_npy_to_lance(
            root["base_dir"],
            replace_existing=replace_existing,
            progress_callback=progress_callback,
        )
        summary["label"] = label
        summaries.append(summary)
    return summaries
