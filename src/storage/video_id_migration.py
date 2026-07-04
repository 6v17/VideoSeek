"""One-time migration: legacy video ids (10 MiB hash) -> current id format."""

from __future__ import annotations

import json
import os

from src.app.config import get_configured_data_root, get_data_storage_paths, load_config
from src.app.logging_utils import get_logger
from src.storage.asset_store import load_metadata, load_vector_payload, save_metadata
from src.utils import get_legacy_video_hash, get_video_hash

logger = get_logger("video_id_migration")

VIDEO_ID_FORMAT_VERSION = 2
VIDEO_ID_PENDING_CHECK_PASSED = "passed"


def _load_vectors_for_migration(vector_file):
    payload = load_vector_payload(vector_file)
    if isinstance(payload, dict):
        return payload.get("vector"), payload.get("timestamps")
    if isinstance(payload, (tuple, list)) and len(payload) >= 2:
        return payload[0], payload[1]
    return None, None


def _has_usable_vectors(vectors, timestamps):
    if vectors is None or timestamps is None:
        return False
    try:
        vector_count = len(vectors)
        timestamp_count = len(timestamps)
    except TypeError:
        return False
    return vector_count > 0 and vector_count == timestamp_count


def _migration_state_file(config):
    data_root = get_configured_data_root(config)
    return os.path.join(data_root, "data", "migration_state.json")


def _read_migration_state(config):
    state_file = _migration_state_file(config)
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_migration_state_patch(config, patch):
    state_file = _migration_state_file(config)
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    state = _read_migration_state(config)
    state.update(patch)
    with open(state_file, "w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)


def _iter_meta_file_entries(meta):
    entries = []
    for root_path, lib_data in (meta.get("libraries") or {}).items():
        if not os.path.exists(root_path):
            continue
        for rel_path, info in (lib_data.get("files") or {}).items():
            entries.append((root_path, rel_path, dict(info)))
    return entries


def _read_video_id_format(config):
    state = _read_migration_state(config or load_config())
    try:
        return int(state.get("video_id_format", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _vector_ids_on_disk(vector_dir):
    ids = set()
    if not vector_dir or not os.path.isdir(vector_dir):
        return ids
    for name in os.listdir(vector_dir):
        if name.lower().endswith("_vectors.npy"):
            video_id = name[: -len("_vectors.npy")]
            if video_id:
                ids.add(video_id)
    return ids


def _entry_has_legacy_video_ids(root_path, rel_path, info, vector_dir):
    """Check one meta entry; may read up to 20 MiB from the video file."""
    abs_path = os.path.join(root_path, rel_path)
    if not os.path.isfile(abs_path):
        return False
    try:
        new_vid = get_video_hash(abs_path)
        legacy_vid = get_legacy_video_hash(abs_path)
    except OSError:
        return False
    if legacy_vid == new_vid:
        return False

    saved_vid = str(info.get("vid", "") or "").strip()
    legacy_vectors = os.path.isfile(_legacy_vector_file(vector_dir, legacy_vid))
    new_vectors = os.path.isfile(_legacy_vector_file(vector_dir, new_vid))
    saved_vectors = os.path.isfile(_legacy_vector_file(vector_dir, saved_vid)) if saved_vid else False

    if saved_vid and saved_vid != new_vid and legacy_vectors:
        if not legacy_vid or saved_vid in {legacy_vid, new_vid}:
            return True
        if saved_vectors:
            return True

    if saved_vid == new_vid and legacy_vectors and not new_vectors:
        return True
    if saved_vid == new_vid and not saved_vectors and legacy_vectors:
        return True

    if legacy_vectors and not new_vectors:
        return True
    return False


def _trust_fast_video_id_check(config):
    state = _read_migration_state(config or load_config())
    return str(state.get("video_id_pending_check", "") or "").strip() == VIDEO_ID_PENDING_CHECK_PASSED


def _mark_video_id_pending_check_passed(config):
    _write_migration_state_patch(
        config or load_config(),
        {"video_id_pending_check": VIDEO_ID_PENDING_CHECK_PASSED},
    )


def _legacy_video_ids_pending_fast_for_root(meta, vector_dir, *, verify_saved_ids=False):
    """Disk/meta check; hashes only missing-vector entries, or saved ids when verify_saved_ids."""
    valid_ids = _collect_valid_video_ids(meta)
    disk_ids = _vector_ids_on_disk(vector_dir)
    for disk_id in disk_ids:
        if disk_id not in valid_ids and len(disk_id) > 10:
            return True

    for root_path, rel_path, info in _iter_meta_file_entries(meta):
        saved_vid = str(info.get("vid", "") or "").strip()
        abs_path = os.path.join(root_path, rel_path)
        if not saved_vid or not os.path.isfile(abs_path):
            continue
        saved_vectors = _legacy_vector_file(vector_dir, saved_vid)
        if os.path.isfile(saved_vectors):
            if not verify_saved_ids:
                continue
            try:
                new_vid = get_video_hash(abs_path)
            except OSError:
                continue
            if saved_vid != new_vid:
                return True
            continue
        if _entry_has_legacy_video_ids(root_path, rel_path, info, vector_dir):
            return True
    return False


def _legacy_video_ids_pending_fast(config, *, verify_saved_ids=False):
    for storage_root in iter_model_asset_storage_roots(config):
        meta_file = storage_root["meta_file"]
        if not os.path.isfile(meta_file):
            continue
        meta = load_metadata(meta_file)
        if _legacy_video_ids_pending_fast_for_root(
            meta,
            storage_root["vector_dir"],
            verify_saved_ids=verify_saved_ids,
        ):
            return True
    return False


def _legacy_video_ids_pending_full(config):
    for storage_root in iter_model_asset_storage_roots(config):
        meta_file = storage_root["meta_file"]
        if not os.path.isfile(meta_file):
            continue
        meta = load_metadata(meta_file)
        if _root_has_legacy_video_ids(_iter_meta_file_entries(meta), storage_root["vector_dir"]):
            return True
    return False


def legacy_video_ids_pending(config=None):
    """True while on-disk vectors still use pre-v2 ids that meta/hash no longer match."""
    runtime_config = config or load_config()
    trusted = _trust_fast_video_id_check(runtime_config)
    verify_saved_ids = not trusted
    if trusted or _read_video_id_format(runtime_config) >= VIDEO_ID_FORMAT_VERSION:
        if _legacy_video_ids_pending_fast(runtime_config, verify_saved_ids=verify_saved_ids):
            return True
        if trusted:
            return False
    return _legacy_video_ids_pending_full(runtime_config)


def video_id_migration_completed(config=None):
    runtime_config = config or load_config()
    if _read_video_id_format(runtime_config) < VIDEO_ID_FORMAT_VERSION:
        return False
    return not legacy_video_ids_pending(runtime_config)


def iter_model_asset_storage_roots(config=None):
    """Yield every on-disk model library tree (active + inactive profiles)."""
    cfg = dict(config or load_config())
    data_paths = get_data_storage_paths(config=cfg)
    data_dir = data_paths["data_dir"]
    seen = set()

    model_assets_root = os.path.join(data_dir, "model_assets")
    if os.path.isdir(model_assets_root):
        for provider_dir in sorted(os.listdir(model_assets_root)):
            provider_path = os.path.join(model_assets_root, provider_dir)
            if not os.path.isdir(provider_path):
                continue
            for variant in sorted(os.listdir(provider_path)):
                base_dir = os.path.join(provider_path, variant)
                if not os.path.isdir(base_dir):
                    continue
                meta_file = os.path.join(base_dir, "meta.json")
                if not os.path.isfile(meta_file):
                    continue
                key = os.path.normcase(os.path.normpath(base_dir))
                if key in seen:
                    continue
                seen.add(key)
                yield {
                    "label": f"{provider_dir}/{variant}",
                    "base_dir": base_dir,
                    "meta_file": meta_file,
                    "vector_dir": os.path.join(base_dir, "vector"),
                    "index_dir": os.path.join(base_dir, "index"),
                }

    legacy_meta = os.path.join(data_dir, "meta.json")
    legacy_vector = os.path.join(data_dir, "vector")
    legacy_index = os.path.join(data_dir, "index")
    if os.path.isfile(legacy_meta) and os.path.isdir(legacy_vector):
        key = os.path.normcase(os.path.normpath(data_dir))
        if key not in seen:
            seen.add(key)
            yield {
                "label": "legacy/data",
                "base_dir": data_dir,
                "meta_file": legacy_meta,
                "vector_dir": legacy_vector,
                "index_dir": legacy_index,
            }

    meta_file = str(cfg.get("meta_file", "") or "").strip()
    vector_dir = str(cfg.get("vector_dir", "") or "").strip()
    index_dir = str(cfg.get("index_dir", "") or "").strip()
    if meta_file and os.path.isfile(meta_file) and vector_dir and os.path.isdir(vector_dir):
        base_dir = os.path.dirname(meta_file)
        key = os.path.normcase(os.path.normpath(base_dir))
        if key not in seen:
            seen.add(key)
            yield {
                "label": "config",
                "base_dir": base_dir,
                "meta_file": meta_file,
                "vector_dir": vector_dir,
                "index_dir": index_dir if index_dir and os.path.isdir(index_dir) else os.path.join(base_dir, "index"),
            }


def _asset_paths(vector_dir, index_dir, video_id):
    return {
        "vectors": os.path.join(vector_dir, f"{video_id}_vectors.npy"),
        "index": os.path.join(index_dir, f"{video_id}_index.faiss"),
    }


def _rename_video_assets(vector_dir, index_dir, old_vid, new_vid):
    old_paths = _asset_paths(vector_dir, index_dir, old_vid)
    new_paths = _asset_paths(vector_dir, index_dir, new_vid)
    for key in ("vectors", "index"):
        src = old_paths[key]
        dst = new_paths[key]
        if not os.path.exists(src):
            continue
        if os.path.exists(dst):
            raise FileExistsError(f"Target asset already exists: {dst}")
        os.replace(src, dst)


def _legacy_vector_file(vector_dir, video_id):
    if not video_id:
        return ""
    return os.path.join(vector_dir, f"{video_id}_vectors.npy")


def _root_has_legacy_video_ids(entries, vector_dir):
    """True if on-disk vectors still use pre-v2 ids (including meta already updated)."""
    for root_path, rel_path, info in entries:
        if _entry_has_legacy_video_ids(root_path, rel_path, info, vector_dir):
            return True
    return False


def _collect_valid_video_ids(meta):
    valid = set()
    for lib_data in (meta.get("libraries") or {}).values():
        for info in (lib_data.get("files") or {}).values():
            vid = str(info.get("vid", "") or "").strip()
            if vid:
                valid.add(vid)
    return valid


def _gc_orphan_assets(vector_dir, index_dir, valid_ids):
    removed = 0
    for folder, suffix in ((vector_dir, "_vectors.npy"), (index_dir, "_index.faiss")):
        if not folder or not os.path.isdir(folder):
            continue
        for filename in os.listdir(folder):
            if not filename.endswith(suffix):
                continue
            video_id = filename[: -len(suffix)]
            if not video_id or video_id in valid_ids:
                continue
            if len(video_id) <= 10:
                continue
            path = os.path.join(folder, filename)
            try:
                os.remove(path)
                removed += 1
                logger.info("Removed orphan asset after video-id migration: %s", path)
            except OSError:
                logger.warning("Failed to remove orphan asset: %s", path)
    return removed


def migrate_model_storage_root(storage_root, *, progress_callback=None, progress_base=0, progress_span=100):
    meta_file = storage_root["meta_file"]
    vector_dir = storage_root["vector_dir"]
    index_dir = storage_root["index_dir"]
    label = storage_root.get("label", meta_file)

    if not os.path.isfile(meta_file):
        return {"label": label, "migrated": 0, "skipped": 0, "failed": 0, "orphans_removed": 0, "skipped_root": True}

    meta = load_metadata(meta_file)
    entries = _iter_meta_file_entries(meta)

    if not _root_has_legacy_video_ids(entries, vector_dir):
        return {
            "label": label,
            "migrated": 0,
            "skipped": len(entries),
            "failed": 0,
            "orphans_removed": 0,
            "skipped_root": True,
        }

    total = len(entries)
    migrated = skipped = failed = 0

    for index, (root_path, rel_path, info) in enumerate(entries, start=1):
        if callable(progress_callback) and total:
            percent = progress_base + int(progress_span * (index - 1) / total)
            progress_callback(percent, f"迁移视频 ID [{label}] {index}/{total}")

        abs_path = os.path.join(root_path, rel_path)
        saved_vid = str(info.get("vid", "") or "").strip()
        if not saved_vid or not os.path.isfile(abs_path):
            skipped += 1
            continue

        try:
            new_vid = get_video_hash(abs_path)
            legacy_vid = get_legacy_video_hash(abs_path)
        except OSError as exc:
            logger.warning("Cannot stat video during id migration: %s (%s)", abs_path, exc)
            failed += 1
            continue

        if legacy_vid == new_vid:
            skipped += 1
            continue

        old_vid = saved_vid
        if saved_vid == new_vid:
            legacy_vectors = _legacy_vector_file(vector_dir, legacy_vid)
            new_vectors = _legacy_vector_file(vector_dir, new_vid)
            if os.path.isfile(legacy_vectors) and not os.path.isfile(new_vectors):
                old_vid = legacy_vid
            else:
                skipped += 1
                continue
        elif saved_vid != new_vid:
            old_vid = saved_vid

        vector_file = _legacy_vector_file(vector_dir, old_vid)
        if not os.path.isfile(vector_file):
            skipped += 1
            continue

        if legacy_vid and old_vid not in {legacy_vid, new_vid}:
            logger.info(
                "Skipping video id migration for %s: stored vid does not match legacy hash",
                abs_path,
            )
            skipped += 1
            continue

        try:
            vectors, timestamps = _load_vectors_for_migration(vector_file)
        except Exception as exc:
            logger.warning("Unreadable vector payload, skip id migration: %s (%s)", vector_file, exc)
            failed += 1
            continue

        if not _has_usable_vectors(vectors, timestamps):
            failed += 1
            continue

        try:
            _rename_video_assets(vector_dir, index_dir, old_vid, new_vid)
        except Exception as exc:
            logger.warning("Failed to rename assets %s -> %s: %s", old_vid, new_vid, exc)
            failed += 1
            continue

        file_entry = (meta.get("libraries") or {}).get(root_path, {}).get("files", {}).get(rel_path)
        if isinstance(file_entry, dict):
            file_entry["vid"] = new_vid
        migrated += 1

    meta_dirty = migrated > 0
    if meta_dirty:
        save_metadata(meta, meta_file)

    valid_ids = _collect_valid_video_ids(meta)
    orphans_removed = _gc_orphan_assets(vector_dir, index_dir, valid_ids)

    if callable(progress_callback) and total:
        progress_callback(progress_base + progress_span, f"迁移视频 ID [{label}] 完成")

    return {
        "label": label,
        "migrated": migrated,
        "skipped": skipped,
        "failed": failed,
        "orphans_removed": orphans_removed,
        "meta_changed": meta_dirty,
    }


def migrate_legacy_video_ids(config=None, progress_callback=None):
    """Migrate all model libraries from legacy video ids to the current format."""
    runtime_config = dict(config or load_config())
    video_id_format = _read_video_id_format(runtime_config)
    trusted_fast = _trust_fast_video_id_check(runtime_config)
    if trusted_fast:
        logger.info("Checking legacy video ids (trusted fast path)")
        pending_before = _legacy_video_ids_pending_fast(runtime_config, verify_saved_ids=False)
    elif video_id_format >= VIDEO_ID_FORMAT_VERSION:
        logger.info("Checking legacy video ids (one-time verify, format_version=%s)", video_id_format)
        pending_before = legacy_video_ids_pending(runtime_config)
    else:
        logger.info("Checking legacy video ids (full scan, format_version=%s)", video_id_format)
        pending_before = legacy_video_ids_pending(runtime_config)
    if video_id_migration_completed(runtime_config) and not pending_before:
        if video_id_format >= VIDEO_ID_FORMAT_VERSION and not trusted_fast:
            _mark_video_id_pending_check_passed(runtime_config)
            logger.info("Marked legacy video-id fast check as passed after startup verification")
        logger.info("Video id migration skipped: already at format version %s", VIDEO_ID_FORMAT_VERSION)
        return {
            "migrated": False,
            "video_id_format": VIDEO_ID_FORMAT_VERSION,
            "pending_legacy": False,
        }

    if pending_before:
        logger.info("Video id migration required: legacy on-disk vector ids still pending")

    roots = list(iter_model_asset_storage_roots(runtime_config))
    if not roots:
        logger.warning("Video id migration found no model storage roots under data_dir")
        if not legacy_video_ids_pending(runtime_config):
            _write_migration_state_patch(
                runtime_config,
                {"video_id_format": VIDEO_ID_FORMAT_VERSION, "video_id_migration_stats": {"roots": 0}},
            )
        return {
            "migrated": False,
            "video_id_format": int(_read_migration_state(runtime_config).get("video_id_format", 0) or 0),
            "roots": 0,
            "pending_legacy": legacy_video_ids_pending(runtime_config),
        }

    per_root = []
    total_migrated = total_failed = total_orphans = 0
    span = max(1, 90 // len(roots))

    for root_index, storage_root in enumerate(roots):
        base = 5 + root_index * span
        stats = migrate_model_storage_root(
            storage_root,
            progress_callback=progress_callback,
            progress_base=base,
            progress_span=span,
        )
        per_root.append(stats)
        total_migrated += int(stats.get("migrated", 0) or 0)
        total_failed += int(stats.get("failed", 0) or 0)
        total_orphans += int(stats.get("orphans_removed", 0) or 0)

    pending_after = legacy_video_ids_pending(runtime_config)
    stats = {
        "roots": len(roots),
        "migrated": total_migrated,
        "failed": total_failed,
        "orphans_removed": total_orphans,
        "per_root": per_root,
        "pending_after": pending_after,
    }
    patch = {"video_id_migration_stats": stats}
    if not pending_after:
        patch["video_id_format"] = VIDEO_ID_FORMAT_VERSION
        patch["video_id_pending_check"] = VIDEO_ID_PENDING_CHECK_PASSED
    else:
        logger.warning(
            "Video id migration finished with pending legacy assets; will retry on next startup (migrated=%s failed=%s)",
            total_migrated,
            total_failed,
        )
    _write_migration_state_patch(runtime_config, patch)

    if callable(progress_callback):
        if pending_after:
            progress_callback(100, f"视频索引 ID 部分完成，已迁移 {total_migrated} 个（仍有待处理）")
        else:
            progress_callback(100, f"视频索引 ID 迁移完成（{total_migrated} 个）")

    logger.info(
        "Video id migration finished: roots=%s migrated=%s failed=%s orphans_removed=%s pending=%s",
        len(roots),
        total_migrated,
        total_failed,
        total_orphans,
        pending_after,
    )
    return {
        "migrated": total_migrated > 0 or total_orphans > 0,
        "video_id_format": VIDEO_ID_FORMAT_VERSION if not pending_after else int(
            _read_migration_state(runtime_config).get("video_id_format", 0) or 0
        ),
        "roots": len(roots),
        "migrated_video_ids": total_migrated,
        "failed_video_ids": total_failed,
        "orphans_removed": total_orphans,
        "per_root": per_root,
        "pending_legacy": pending_after,
    }
