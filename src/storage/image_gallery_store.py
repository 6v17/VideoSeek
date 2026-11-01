"""Image gallery catalog and Lance table.

Vectors live under the active model profile's ``image_gallery/`` directory,
separate from the video ``frames`` table.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading

import numpy as np

from src.core.vector_norm import normalize_vectors
from src.services.image_gallery_index import (
    CatalogRecord,
    rank_image_vectors,
)

TABLE_NAME = "images"
CATALOG_VERSION = 1

_LOCK = threading.RLock()


def image_id_for_path(path: str) -> str:
    return hashlib.sha256(str(path or "").encode("utf-8")).hexdigest()


def catalog_path(root: str) -> str:
    return os.path.join(os.path.normpath(root), "catalog.json")


def lance_dir(root: str) -> str:
    return os.path.join(os.path.normpath(root), "lance")


def empty_catalog() -> dict:
    return {"version": CATALOG_VERSION, "profile_id": "", "folders": [], "files": {}}


def load_catalog(root: str) -> dict:
    path = catalog_path(root)
    with _LOCK:
        if not os.path.isfile(path):
            return empty_catalog()
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return empty_catalog()
    if not isinstance(payload, dict):
        return empty_catalog()
    folders = payload.get("folders")
    files = payload.get("files")
    return {
        "version": CATALOG_VERSION,
        "profile_id": str(payload.get("profile_id") or ""),
        "folders": [str(item) for item in folders] if isinstance(folders, list) else [],
        "files": files if isinstance(files, dict) else {},
    }


def save_catalog(root: str, payload: dict) -> None:
    path = catalog_path(root)
    body = {
        "version": CATALOG_VERSION,
        "profile_id": str((payload or {}).get("profile_id") or ""),
        "folders": [str(item) for item in (payload or {}).get("folders") or []],
        "files": dict((payload or {}).get("files") or {}),
    }
    with _LOCK:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, path)


def records_from_catalog(payload: dict) -> dict[str, CatalogRecord]:
    records: dict[str, CatalogRecord] = {}
    files = (payload or {}).get("files") or {}
    if not isinstance(files, dict):
        return records
    for raw_path, raw in files.items():
        if not isinstance(raw, dict):
            continue
        path = str(raw_path or "").strip()
        if not path:
            continue
        records[path] = CatalogRecord(
            path=path,
            folder=str(raw.get("folder") or ""),
            mtime_ns=int(raw.get("mtime_ns") or 0),
            size=int(raw.get("size") or 0),
            profile_id=str(raw.get("profile_id") or ""),
            failed=bool(raw.get("failed")),
            pending=bool(raw.get("pending")),
        )
    return records


def write_record(payload: dict, record: CatalogRecord) -> None:
    files = payload.setdefault("files", {})
    files[record.path] = {
        "folder": record.folder,
        "mtime_ns": int(record.mtime_ns),
        "size": int(record.size),
        "profile_id": str(record.profile_id or ""),
        "failed": bool(record.failed),
        "pending": bool(record.pending),
    }


def drop_record(payload: dict, path: str) -> None:
    files = payload.get("files")
    if isinstance(files, dict):
        files.pop(path, None)


def _pa():
    import pyarrow as pa

    return pa


def _vector_field(dimension: int):
    pa = _pa()
    return pa.field("vector", pa.list_(pa.float32(), int(dimension)))


def images_table_schema(dimension: int):
    pa = _pa()
    return pa.schema(
        [
            pa.field("image_id", pa.string()),
            pa.field("image_path", pa.string()),
            pa.field("profile_id", pa.string()),
            _vector_field(dimension),
        ]
    )


def _connect(root: str):
    import lancedb

    directory = lance_dir(root)
    os.makedirs(directory, exist_ok=True)
    return lancedb.connect(directory)


def _table_names(db) -> list[str]:
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


def _open_table(root: str):
    db = _connect(root)
    if TABLE_NAME not in _table_names(db):
        return None
    return db.open_table(TABLE_NAME)


def vector_dimension(root: str) -> int:
    with _LOCK:
        table = _open_table(root)
        if table is None:
            return 0
        try:
            sample = table.search().select(["vector"]).limit(1).to_arrow()
        except Exception as exc:
            from src.app.logging_utils import note_swallowed

            note_swallowed(exc, "src/storage/image_gallery_store.py:vector_dimension")
            return 0
        if sample is None or sample.num_rows <= 0 or "vector" not in sample.column_names:
            return 0
        vector = sample["vector"][0].as_py()
        return len(vector or [])


def drop_vectors(root: str) -> None:
    with _LOCK:
        db = _connect(root)
        if TABLE_NAME not in _table_names(db):
            return
        db.drop_table(TABLE_NAME)


def _delete_ids(table, image_ids: list[str]) -> None:
    for start in range(0, len(image_ids), 200):
        chunk = [item for item in image_ids[start : start + 200] if item]
        if not chunk:
            continue
        quoted = ", ".join("'" + item.replace("'", "''") + "'" for item in chunk)
        table.delete(f"image_id IN ({quoted})")


def delete_image_paths(root: str, paths: list[str]) -> None:
    ids = [image_id_for_path(path) for path in paths if str(path or "").strip()]
    if not ids:
        return
    with _LOCK:
        table = _open_table(root)
        if table is None:
            return
        _delete_ids(table, ids)


def upsert_image_vectors(root: str, rows: list[dict]) -> None:
    """Insert normalized vectors. Raises ``ValueError('dimension_mismatch')`` instead of mixing dimensions."""
    if not rows:
        return
    vectors = [np.asarray(row["vector"], dtype=np.float32).reshape(-1) for row in rows]
    dimension = int(vectors[0].shape[0])
    if dimension <= 0 or any(int(vector.shape[0]) != dimension for vector in vectors):
        raise ValueError("image gallery vectors must share one dimension")
    normalized = normalize_vectors(np.vstack(vectors))
    payload = []
    for index, row in enumerate(rows):
        path = str(row.get("image_path") or "")
        payload.append(
            {
                "image_id": image_id_for_path(path),
                "image_path": path,
                "profile_id": str(row.get("profile_id") or ""),
                "vector": normalized[index].astype(np.float32).tolist(),
            }
        )
    with _LOCK:
        existing = vector_dimension(root)
        if existing > 0 and existing != dimension:
            raise ValueError("dimension_mismatch")
        db = _connect(root)
        ids = [item["image_id"] for item in payload]
        if TABLE_NAME in _table_names(db):
            _delete_ids(db.open_table(TABLE_NAME), ids)
            db.open_table(TABLE_NAME).add(payload)
            return
        db.create_table(TABLE_NAME, data=payload, schema=images_table_schema(dimension))


def search_image_vectors(root: str, query_vector, *, profile_id: str, top_k: int = 60) -> list[tuple[str, float]]:
    """Exact cosine over the Lance candidates for one profile. Empty when the table is missing."""
    limit = max(0, int(top_k))
    if limit <= 0:
        return []
    query = np.asarray(query_vector, dtype=np.float32).reshape(-1)
    if query.size == 0:
        return []
    active = str(profile_id or "")
    with _LOCK:
        table = _open_table(root)
        if table is None:
            return []
        stored = vector_dimension(root)
        if stored and int(query.shape[0]) != stored:
            raise ValueError("model_mismatch")
        query_list = normalize_vectors(query.reshape(1, -1))[0].tolist()
        columns = ["image_path", "profile_id", "vector", "_distance"]

        def _search(where: str = ""):
            builder = table.search(query_list).select(columns).limit(limit if not where else max(limit * 4, limit))
            if where:
                builder = builder.where(where)
            return builder.to_arrow()

        if active:
            safe = active.replace("'", "''")
            try:
                arrow = _search(f"profile_id = '{safe}'")
            except Exception:
                arrow = _search()
        else:
            arrow = _search()
    if arrow is None or arrow.num_rows <= 0:
        return []
    paths = arrow["image_path"].to_pylist() if "image_path" in arrow.column_names else []
    profiles = arrow["profile_id"].to_pylist() if "profile_id" in arrow.column_names else [""] * len(paths)
    if "vector" in arrow.column_names:
        vectors = arrow["vector"].to_pylist()
        items = []
        for index, path in enumerate(paths):
            if active and str(profiles[index] or "") != active:
                continue
            items.append((str(path or ""), np.asarray(vectors[index], dtype=np.float32)))
        return rank_image_vectors(query, items, limit)
    return []
