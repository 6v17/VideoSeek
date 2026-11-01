"""Pure image-gallery diff and cosine ranking. No CLIP and no Lance."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.core.vector_norm import normalize_vectors


@dataclass(frozen=True)
class ScannedImage:
    path: str
    folder: str
    mtime_ns: int
    size: int


@dataclass(frozen=True)
class CatalogRecord:
    path: str
    folder: str
    mtime_ns: int
    size: int
    profile_id: str
    failed: bool = False
    pending: bool = False


@dataclass(frozen=True)
class ImageSyncDiff:
    to_embed: tuple[ScannedImage, ...]
    to_delete: tuple[str, ...]
    to_relink: tuple[ScannedImage, ...]
    unchanged: tuple[str, ...]


@dataclass(frozen=True)
class ImageSyncPlan:
    to_embed: tuple[ScannedImage, ...]
    to_delete: tuple[str, ...]
    to_relink: tuple[ScannedImage, ...]
    rebuild: bool


def _needs_embed(record: CatalogRecord | None, stat: ScannedImage, active_profile_id: str) -> bool:
    if record is None or record.pending:
        return True
    if str(record.profile_id or "") != active_profile_id:
        return True
    if int(record.mtime_ns) != int(stat.mtime_ns) or int(record.size) != int(stat.size):
        return True
    return False


def gallery_is_stale(records: dict[str, CatalogRecord], active_profile_id: str) -> bool:
    return index_profile_mismatch(records, active_profile_id)


def index_profile_mismatch(records: dict[str, CatalogRecord], active_profile_id: str) -> bool:
    """True when a successful vector was built with a different model profile."""
    active = str(active_profile_id or "")
    for record in records.values():
        if record.failed or record.pending:
            continue
        if str(record.profile_id or "") != active:
            return True
    return False


def diff_image_catalog(
    records: dict[str, CatalogRecord],
    scanned: dict[str, ScannedImage],
    *,
    active_profile_id: str,
    online_folders: set[str],
) -> ImageSyncDiff:
    """Decide which files to embed, drop, or leave.

    A missing file is deleted only when its folder is online. An offline folder
    keeps its catalog rows so a disconnected drive is not wiped.
    Failed decodes are not retried until mtime, size, or profile changes.
    """
    active = str(active_profile_id or "")
    online = set(online_folders)
    to_embed: list[ScannedImage] = []
    to_relink: list[ScannedImage] = []
    unchanged: list[str] = []
    for path in sorted(scanned):
        stat = scanned[path]
        record = records.get(path)
        if _needs_embed(record, stat, active):
            to_embed.append(stat)
            continue
        if record is not None and record.folder != stat.folder:
            to_relink.append(stat)
            continue
        unchanged.append(path)
    to_delete = tuple(
        sorted(
            path
            for path, record in records.items()
            if path not in scanned and record.folder in online
        )
    )
    return ImageSyncDiff(
        to_embed=tuple(to_embed),
        to_delete=to_delete,
        to_relink=tuple(to_relink),
        unchanged=tuple(unchanged),
    )


def plan_image_sync(
    records: dict[str, CatalogRecord],
    scanned: dict[str, ScannedImage],
    *,
    active_profile_id: str,
    online_folders: set[str],
) -> ImageSyncPlan:
    """Expand a profile mismatch into a full rebuild of every scanned file."""
    diff = diff_image_catalog(
        records,
        scanned,
        active_profile_id=active_profile_id,
        online_folders=online_folders,
    )
    if not index_profile_mismatch(records, active_profile_id):
        return ImageSyncPlan(
            to_embed=diff.to_embed,
            to_delete=diff.to_delete,
            to_relink=diff.to_relink,
            rebuild=False,
        )
    # Dropping the table invalidates offline rows too. Forget them so the next
    # time the folder is online they embed as new files instead of looping rebuilds.
    offline_paths = tuple(
        sorted(path for path, record in records.items() if path not in scanned and record.folder not in online_folders)
    )
    to_delete = tuple(sorted(set(diff.to_delete) | set(offline_paths)))
    to_embed = tuple(sorted(scanned.values(), key=lambda item: item.path))
    return ImageSyncPlan(
        to_embed=to_embed,
        to_delete=to_delete,
        to_relink=(),
        rebuild=True,
    )


def rank_image_vectors(query_vector, items: list[tuple[str, np.ndarray]], top_k: int) -> list[tuple[str, float]]:
    """Return ``(key, cosine)`` pairs, highest cosine first."""
    limit = int(top_k)
    if limit <= 0 or not items:
        return []
    query = normalize_vectors(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))[0]
    scored: list[tuple[str, float]] = []
    for key, vector in items:
        if vector is None:
            continue
        array = np.asarray(vector, dtype=np.float32).reshape(-1)
        if array.size == 0 or array.shape[0] != query.shape[0]:
            continue
        vector_row = normalize_vectors(array.reshape(1, -1))[0]
        scored.append((str(key), float(np.dot(query, vector_row))))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:limit]
