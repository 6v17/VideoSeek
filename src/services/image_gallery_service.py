"""Scan local image folders, embed them with the active model, and search by text."""

from __future__ import annotations

import os
import sys

import cv2
import numpy as np

from src.app.logging_utils import get_logger
from src.core.image_io import existing_file_path, extended_length_path, from_extended_length_path, load_image_bgr
from src.media.formats import is_supported_image_path
from src.services.image_gallery_index import (
    CatalogRecord,
    ScannedImage,
    gallery_is_stale,
    plan_image_sync,
)
from src.storage.image_gallery_store import (
    delete_image_paths,
    drop_record,
    drop_vectors,
    empty_catalog,
    load_catalog,
    records_from_catalog,
    save_catalog,
    search_image_vectors,
    upsert_image_vectors,
    write_record,
)
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("image_gallery")

IMAGE_GALLERY_TOP_K = 60
_EMBED_BATCH = 4
_ENCODE_LONG_SIDE = 1024


class ImageGalleryStopped(Exception):
    def __init__(self, summary: dict):
        super().__init__("stopped")
        self.summary = summary


class ImageGalleryScanStopped(Exception):
    """The walk was cancelled. ``online`` lists only folders that were fully listed."""

    def __init__(self, scanned: dict[str, ScannedImage], online: set[str]):
        super().__init__("stopped")
        self.scanned = scanned
        self.online = set(online)


class _ScanHalted(Exception):
    pass


# Child names skipped so a drive root can finish. The folder the user added is
# still walked; only these names are not entered. Junctions are skipped separately.
_SKIP_DIR_NAMES = frozenset(
    {
        "__macosx",
        "__pycache__",
        ".git",
        ".thumbnails",
        "@eadir",
        "$recycle.bin",
        "$winreagent",
        "system volume information",
        "windows",
        "program files",
        "program files (x86)",
        "programdata",
        "appdata",
        "node_modules",
        "documents and settings",
        "config.msi",
        "msocache",
    }
)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_SCAN_FILE_STRIDE = 64
_SCAN_DIR_STRIDE = 40


def gallery_root(config=None) -> str:
    from src.storage.config_store import get_local_model_asset_dirs

    base_dir = get_local_model_asset_dirs(config=config)["base_dir"]
    return os.path.join(base_dir, "image_gallery")


def active_profile_id(config=None) -> str:
    from src.storage.config_store import get_active_model_profile

    profile = get_active_model_profile(config=config)
    profile_id = str(profile.get("id") or "").strip()
    if profile_id:
        return profile_id
    provider = str(profile.get("provider") or "").strip()
    if provider:
        return provider
    raise RuntimeError("missing active model profile")


def _resolve_root(root: str | None, config=None) -> str:
    if str(root or "").strip():
        return os.path.normpath(str(root))
    return gallery_root(config=config)


def _is_under(path: str, folder: str) -> bool:
    if path == folder:
        return True
    prefix = folder if folder.endswith(os.sep) else folder + os.sep
    return path.startswith(prefix)


def owning_folder(path: str, folders: list[str]) -> str:
    matches = [folder for folder in folders if folder and _is_under(path, folder)]
    if not matches:
        return ""
    return max(matches, key=len)


def _skip_dir_name(name: str) -> bool:
    return str(name or "").strip().lower() in _SKIP_DIR_NAMES


def _is_reparse_point(entry: os.DirEntry) -> bool:
    """True for symlinks and Windows junctions. Following those loops a drive scan."""
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return True
    try:
        stat_result = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = int(getattr(stat_result, "st_file_attributes", 0) or 0)
    return bool(attributes & _FILE_ATTRIBUTE_REPARSE_POINT)


def _remember_image(scanned: dict[str, ScannedImage], entry: os.DirEntry, folder: str, canonical_folders: list[str]) -> None:
    if not is_supported_image_path(entry.name):
        return
    full = canonicalize_library_path(from_extended_length_path(entry.path))
    try:
        stat_result = entry.stat(follow_symlinks=False)
    except OSError as exc:
        logger.warning("Image scan skipped %s: %s", full, exc)
        return
    owner = owning_folder(full, canonical_folders) or folder
    scanned[full] = ScannedImage(
        path=full,
        folder=owner,
        mtime_ns=int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000))),
        size=int(stat_result.st_size),
    )


def _scan_one_folder(
    folder: str,
    scanned: dict[str, ScannedImage],
    canonical_folders: list[str],
    *,
    should_stop,
    note_file,
    note_dir,
) -> bool:
    """List ``folder`` recursively. Returns False when the root itself cannot be opened."""
    root_path = extended_length_path(folder)
    stack = [root_path]
    root_pending = True
    while stack:
        if should_stop():
            raise _ScanHalted()
        current = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError as exc:
            logger.warning("Image scan skipped %s: %s", from_extended_length_path(current), exc)
            if root_pending and current == root_path:
                return False
            continue
        root_pending = False
        children: list[str] = []
        with iterator:
            for entry in iterator:
                if should_stop():
                    raise _ScanHalted()
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if _skip_dir_name(entry.name) or _is_reparse_point(entry):
                        continue
                    children.append(entry.path)
                    continue
                try:
                    is_file = entry.is_file(follow_symlinks=False)
                except OSError:
                    continue
                if not is_file:
                    continue
                before = len(scanned)
                _remember_image(scanned, entry, folder, canonical_folders)
                if len(scanned) != before:
                    note_file()
        note_dir()
        stack.extend(children)
    return True


def scan_image_folders(
    folders: list[str],
    *,
    progress_callback=None,
    should_stop=None,
) -> tuple[dict[str, ScannedImage], set[str]]:
    """Walk each registered folder, including nested directories and a drive root.

    ``online`` contains folders whose root was listed. A cancelled walk raises
    ``ImageGalleryScanStopped`` and leaves the interrupted folder out of ``online``.
    """
    canonical_folders = []
    seen = set()
    for raw in folders:
        folder = canonicalize_library_path(raw)
        if not folder or folder in seen:
            continue
        seen.add(folder)
        canonical_folders.append(folder)
    online: set[str] = set()
    scanned: dict[str, ScannedImage] = {}
    found = 0
    directories = 0
    emitted = -1
    stop = should_stop or (lambda: False)

    def _emit(force: bool = False) -> None:
        nonlocal emitted
        if progress_callback is None:
            return
        if not force and found == emitted:
            return
        emitted = found
        progress_callback(found)

    def _note_file() -> None:
        nonlocal found
        found += 1
        if found == 1 or found % _SCAN_FILE_STRIDE == 0:
            _emit()

    def _note_dir() -> None:
        nonlocal directories
        directories += 1
        if directories % _SCAN_DIR_STRIDE == 0:
            _emit(force=True)

    for folder in canonical_folders:
        probe = extended_length_path(folder)
        if not os.path.isdir(probe) and not os.path.isdir(folder):
            continue
        try:
            listed = _scan_one_folder(
                folder,
                scanned,
                canonical_folders,
                should_stop=stop,
                note_file=_note_file,
                note_dir=_note_dir,
            )
        except _ScanHalted:
            raise ImageGalleryScanStopped(scanned, online) from None
        if listed:
            online.add(folder)
    _emit(force=True)
    return scanned, online


def gallery_status(root: str | None = None, *, config=None, profile_id: str | None = None) -> dict:
    resolved = _resolve_root(root, config=config)
    active = str(profile_id if profile_id is not None else active_profile_id(config=config))
    catalog = load_catalog(resolved)
    records = records_from_catalog(catalog)
    folders = []
    for folder in catalog.get("folders") or []:
        online = os.path.isdir(folder)
        folder_records = [record for record in records.values() if record.folder == folder]
        folders.append(
            {
                "path": folder,
                "online": online,
                "indexed": sum(1 for record in folder_records if _record_is_indexed(record, active)),
                "failed": sum(1 for record in folder_records if record.failed),
            }
        )
    indexed = sum(1 for record in records.values() if _record_is_indexed(record, active))
    failed = sum(1 for record in records.values() if record.failed)
    files = []
    for record in records.values():
        folder = str(record.folder or "")
        if not folder:
            continue
        record_failed = bool(record.failed)
        record_pending = bool(record.pending)
        files.append(
            {
                "path": record.path,
                "folder": folder,
                "failed": record_failed,
                "pending": record_pending,
                "stale": (not record_failed) and (not record_pending) and str(record.profile_id or "") != active,
            }
        )
    return {
        "root": resolved,
        "profile_id": active,
        "folders": folders,
        "files": files,
        "indexed": indexed,
        "failed": failed,
        "stale": gallery_is_stale(records, active),
    }


def add_image_folder(path: str, root: str | None = None, *, config=None) -> str:
    folder = canonicalize_library_path(path)
    if not folder or not os.path.isdir(folder):
        raise ValueError("invalid_folder")
    resolved = _resolve_root(root, config=config)
    catalog = load_catalog(resolved)
    folders = list(catalog.get("folders") or [])
    if folder in folders:
        raise ValueError("folder_exists")
    folders.append(folder)
    catalog["folders"] = folders
    save_catalog(resolved, catalog)
    return folder


def remove_image_folder(path: str, root: str | None = None, *, config=None) -> list[str]:
    folder = canonicalize_library_path(path)
    resolved = _resolve_root(root, config=config)
    catalog = load_catalog(resolved)
    folders = [item for item in (catalog.get("folders") or []) if item != folder]
    records = records_from_catalog(catalog)
    removed = [
        record.path
        for record in records.values()
        if record.folder == folder or (record.folder not in folders and _is_under(record.path, folder))
    ]
    # Files still covered by a remaining nested folder stay, but their owner may change on the next sync.
    kept_removed = []
    for record_path in removed:
        if owning_folder(record_path, folders):
            continue
        kept_removed.append(record_path)
        drop_record(catalog, record_path)
    catalog["folders"] = folders
    save_catalog(resolved, catalog)
    delete_image_paths(resolved, kept_removed)
    return kept_removed


def _record_is_indexed(record: CatalogRecord, active: str) -> bool:
    return (not record.failed) and (not record.pending) and str(record.profile_id or "") == str(active or "")


def _same_file_stat(record: CatalogRecord, stat: ScannedImage) -> bool:
    return int(record.mtime_ns) == int(stat.mtime_ns) and int(record.size) == int(stat.size)


def _merge_scanned_catalog(
    catalog: dict,
    records: dict[str, CatalogRecord],
    scanned: dict[str, ScannedImage],
    online: set[str],
) -> tuple[int, list[str]]:
    """List newly seen files as pending. Drop rows only for folders that were fully listed."""
    added = 0
    for stat in scanned.values():
        record = records.get(stat.path)
        if record is not None and _same_file_stat(record, stat):
            if record.folder != stat.folder:
                write_record(
                    catalog,
                    CatalogRecord(
                        path=stat.path,
                        folder=stat.folder,
                        mtime_ns=stat.mtime_ns,
                        size=stat.size,
                        profile_id=record.profile_id,
                        failed=record.failed,
                        pending=record.pending,
                    ),
                )
            continue
        write_record(
            catalog,
            CatalogRecord(
                path=stat.path,
                folder=stat.folder,
                mtime_ns=stat.mtime_ns,
                size=stat.size,
                profile_id="",
                failed=False,
                pending=True,
            ),
        )
        added += 1
    deleted: list[str] = []
    for path, record in records.items():
        if path in scanned or record.folder not in online:
            continue
        drop_record(catalog, path)
        deleted.append(path)
    return added, deleted


def discover_image_gallery(
    root: str | None = None,
    *,
    config=None,
    progress_callback=None,
    should_stop=None,
    folders=None,
) -> dict:
    """List images under registered folders without embedding them."""
    resolved = _resolve_root(root, config=config)
    stop = should_stop or (lambda: False)
    catalog = load_catalog(resolved)
    if not catalog.get("folders") and not os.path.isfile(os.path.join(resolved, "catalog.json")):
        catalog = empty_catalog()
    records = records_from_catalog(catalog)
    stopped = False
    catalog_folders = list(catalog.get("folders") or [])
    if folders is not None:
        wanted = {canonicalize_library_path(path) for path in folders if str(path or "").strip()}
        catalog_folders = [path for path in catalog_folders if canonicalize_library_path(path) in wanted]

    def _scan_progress(found: int) -> None:
        if progress_callback is not None:
            progress_callback("scan", int(found), 0)

    try:
        scanned, online = scan_image_folders(
            catalog_folders,
            progress_callback=_scan_progress,
            should_stop=stop,
        )
    except ImageGalleryScanStopped as exc:
        scanned, online = exc.scanned, exc.online
        stopped = True
    added, deleted = _merge_scanned_catalog(catalog, records, scanned, online)
    save_catalog(resolved, catalog)
    if deleted:
        delete_image_paths(resolved, deleted)
    return {
        "mode": "discover",
        "found": len(scanned),
        "added": added,
        "deleted": len(deleted),
        "embedded": 0,
        "failed": 0,
        "unchanged": 0,
        "stopped": stopped,
        "rebuild": False,
    }


def _limit_long_side(image: np.ndarray, limit: int = _ENCODE_LONG_SIDE) -> np.ndarray:
    height, width = int(image.shape[0]), int(image.shape[1])
    long_side = max(height, width)
    if long_side <= limit:
        return image
    scale = float(limit) / float(long_side)
    return cv2.resize(
        image,
        (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
        interpolation=cv2.INTER_AREA,
    )


def _encode_rows(encode_images, images: list[np.ndarray]) -> np.ndarray:
    vectors = np.asarray(encode_images(images), dtype=np.float32)
    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    return vectors


def sync_image_gallery(
    root: str | None = None,
    *,
    config=None,
    profile_id: str | None = None,
    encode_images=None,
    load_image=None,
    progress_callback=None,
    should_stop=None,
) -> dict:
    """Embed new and changed images. Decode failures are recorded and skipped."""
    resolved = _resolve_root(root, config=config)
    active = str(profile_id if profile_id is not None else active_profile_id(config=config))
    if encode_images is None:
        from src.core.clip_embedding import get_clip_embeddings_batch

        encode_images = get_clip_embeddings_batch
    if load_image is None:
        load_image = load_image_bgr
    stop = should_stop or (lambda: False)
    catalog = load_catalog(resolved)
    if not catalog.get("folders") and not os.path.isfile(os.path.join(resolved, "catalog.json")):
        catalog = empty_catalog()

    def _scan_progress(found: int) -> None:
        if progress_callback is not None:
            progress_callback("scan", int(found), 0)

    try:
        scanned, online = scan_image_folders(
            list(catalog.get("folders") or []),
            progress_callback=_scan_progress,
            should_stop=stop,
        )
    except ImageGalleryScanStopped:
        summary = {
            "mode": "sync",
            "embedded": 0,
            "deleted": 0,
            "failed": 0,
            "unchanged": 0,
            "stopped": True,
            "rebuild": False,
        }
        raise ImageGalleryStopped(summary) from None
    records = records_from_catalog(catalog)
    plan = plan_image_sync(
        records,
        scanned,
        active_profile_id=active,
        online_folders=online,
    )
    summary = {
        "embedded": 0,
        "deleted": 0,
        "failed": 0,
        "unchanged": 0,
        "stopped": False,
        "rebuild": bool(plan.rebuild),
    }
    deleted_paths = set(plan.to_delete)
    failed_paths: set[str] = set()
    if plan.rebuild:
        drop_vectors(resolved)
    for path in plan.to_delete:
        drop_record(catalog, path)
    if plan.to_delete:
        delete_image_paths(resolved, list(plan.to_delete))
        summary["deleted"] = len(plan.to_delete)
    for stat in plan.to_relink:
        previous = records.get(stat.path)
        write_record(
            catalog,
            CatalogRecord(
                path=stat.path,
                folder=stat.folder,
                mtime_ns=stat.mtime_ns,
                size=stat.size,
                profile_id=previous.profile_id if previous is not None else active,
                failed=bool(previous.failed) if previous is not None else False,
            ),
        )
    save_catalog(resolved, catalog)

    total = len(plan.to_embed)
    done = 0
    for stat in plan.to_embed:
        write_record(
            catalog,
            CatalogRecord(
                path=stat.path,
                folder=stat.folder,
                mtime_ns=stat.mtime_ns,
                size=stat.size,
                profile_id="",
                failed=False,
                pending=True,
            ),
        )
    save_catalog(resolved, catalog)
    if progress_callback is not None:
        progress_callback("listed", 0, total)

    queue = list(plan.to_embed)
    index = 0
    dimension_checked = plan.rebuild
    while index < len(queue):
        if stop():
            summary["stopped"] = True
            _fill_unchanged(summary, scanned)
            save_catalog(resolved, catalog)
            raise ImageGalleryStopped(summary)
        batch = queue[index : index + _EMBED_BATCH]
        index += len(batch)
        images = []
        stats = []
        for stat in batch:
            done += 1
            if progress_callback is not None:
                progress_callback("embed", done, max(total, len(queue)))
            try:
                image = load_image(stat.path)
            except Exception as exc:
                logger.warning("Image gallery failed to read %s: %s", stat.path, exc)
                image = None
            if image is None:
                summary["failed"] += 1
                failed_paths.add(stat.path)
                write_record(
                    catalog,
                    CatalogRecord(
                        path=stat.path,
                        folder=stat.folder,
                        mtime_ns=stat.mtime_ns,
                        size=stat.size,
                        profile_id=active,
                        failed=True,
                    ),
                )
                continue
            images.append(_limit_long_side(image))
            stats.append(stat)
        if not stats:
            save_catalog(resolved, catalog)
            continue
        embedded = _embed_available(encode_images, images, stats, summary, failed_paths, catalog, active)
        if not embedded:
            save_catalog(resolved, catalog)
            continue
        rows = [
            {"image_path": stat.path, "profile_id": active, "vector": vector}
            for stat, vector in embedded
        ]
        if not dimension_checked:
            dimension_checked = True
            new_dim = int(np.asarray(rows[0]["vector"]).reshape(-1).shape[0])
            existing_dim = 0 if plan.rebuild else _stored_dimension(resolved)
            if existing_dim not in (0, new_dim):
                drop_vectors(resolved)
                _requeue_unembedded(
                    queue,
                    scanned,
                    skip=deleted_paths | failed_paths | {stat.path for stat, _vector in embedded},
                )
                total = len(queue)
        upsert_image_vectors(resolved, rows)
        for stat, _vector in embedded:
            write_record(
                catalog,
                CatalogRecord(
                    path=stat.path,
                    folder=stat.folder,
                    mtime_ns=stat.mtime_ns,
                    size=stat.size,
                    profile_id=active,
                    failed=False,
                ),
            )
        summary["embedded"] += len(embedded)
        save_catalog(resolved, catalog)
    catalog["profile_id"] = active
    _fill_unchanged(summary, scanned)
    save_catalog(resolved, catalog)
    if progress_callback is not None:
        progress_callback("done", summary["embedded"] + summary["failed"], summary["embedded"] + summary["failed"])
    return summary


def _fill_unchanged(summary: dict, scanned: dict) -> None:
    summary["unchanged"] = max(0, len(scanned) - int(summary["embedded"]) - int(summary["failed"]))


def _stored_dimension(root: str) -> int:
    from src.storage.image_gallery_store import vector_dimension

    return int(vector_dimension(root) or 0)


def _requeue_unembedded(queue: list, scanned: dict[str, ScannedImage], *, skip: set[str]) -> None:
    queued = {stat.path for stat in queue}
    for path in sorted(scanned):
        if path in skip or path in queued:
            continue
        queue.append(scanned[path])


def _embed_available(encode_images, images, stats, summary: dict, failed_paths: set[str], catalog: dict, active: str):
    try:
        vectors = _encode_rows(encode_images, images)
    except Exception as exc:
        logger.warning("Image gallery batch embed failed, retrying one by one: %s", exc)
        vectors = None
    pairs = []
    if vectors is not None and int(vectors.shape[0]) == len(stats):
        return list(zip(stats, vectors))
    if vectors is not None and int(vectors.shape[0]) != len(stats):
        logger.error(
            "Image gallery embed count mismatch: images=%s vectors=%s",
            len(stats),
            int(vectors.shape[0]),
        )
    for stat, image in zip(stats, images):
        try:
            single = _encode_rows(encode_images, [image])
        except Exception as exc:
            logger.warning("Image gallery embed failed for %s: %s", stat.path, exc)
            single = None
        if single is None or int(single.shape[0]) != 1:
            summary["failed"] += 1
            failed_paths.add(stat.path)
            write_record(
                catalog,
                CatalogRecord(
                    path=stat.path,
                    folder=stat.folder,
                    mtime_ns=stat.mtime_ns,
                    size=stat.size,
                    profile_id=active,
                    failed=True,
                ),
            )
            continue
        pairs.append((stat, single[0]))
    return pairs


def search_image_gallery_by_vector(
    vector,
    root: str | None = None,
    *,
    config=None,
    profile_id: str | None = None,
    top_k: int = IMAGE_GALLERY_TOP_K,
    min_score: float = 0.0,
) -> list[dict]:
    """Rank gallery stills by a query vector. Text, image, and fused queries all enter here."""
    resolved = _resolve_root(root, config=config)
    active = str(profile_id if profile_id is not None else active_profile_id(config=config))
    floor = float(min_score or 0.0)
    try:
        ranked = search_image_vectors(resolved, vector, profile_id=active, top_k=int(top_k))
    except ValueError as exc:
        if str(exc) == "model_mismatch":
            raise ValueError("model_mismatch") from exc
        raise
    return [
        {"path": path, "score": float(score)}
        for path, score in ranked
        if float(score) >= floor
    ]


def search_image_gallery(
    text: str,
    root: str | None = None,
    *,
    config=None,
    profile_id: str | None = None,
    embed_text=None,
    top_k: int = IMAGE_GALLERY_TOP_K,
    min_score: float = 0.0,
) -> list[dict]:
    query = str(text or "").strip()
    if not query:
        return []
    resolved = _resolve_root(root, config=config)
    active = str(profile_id if profile_id is not None else active_profile_id(config=config))
    if embed_text is None:
        from src.core.clip_embedding import get_text_embedding

        embed_text = get_text_embedding
    vector = np.asarray(embed_text(query), dtype=np.float32).reshape(-1)
    return search_image_gallery_by_vector(
        vector,
        resolved,
        config=config,
        profile_id=active,
        top_k=top_k,
        min_score=min_score,
    )


def open_original_image(path: str) -> bool:
    target = existing_file_path(path)
    if not target:
        return False
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
        return True
    import subprocess

    if sys.platform == "darwin":
        subprocess.run(["open", target], check=False)
    else:
        subprocess.run(["xdg-open", target], check=False)
    return True


# Re-export for callers that only need the stale check next to status.
__all__ = [
    "IMAGE_GALLERY_TOP_K",
    "ImageGalleryStopped",
    "active_profile_id",
    "add_image_folder",
    "gallery_root",
    "gallery_status",
    "open_original_image",
    "remove_image_folder",
    "scan_image_folders",
    "search_image_gallery",
    "search_image_gallery_by_vector",
    "sync_image_gallery",
]
