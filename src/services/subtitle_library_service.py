"""Global subtitle library registry — folder membership shared across CLIP models."""

from __future__ import annotations

import os

from src.app.config import load_config
from src.app.logging_utils import get_logger
from src.services.library_service import _iter_library_video_paths, _normalize_library_map, _paths_overlap
from src.storage.dialogue_transcript_store import (
    delete_dialogue_transcript,
    list_transcript_library_paths,
)
from src.storage.subtitle_library_store import (
    is_subtitle_registry_seeded,
    load_subtitle_library_meta,
    mark_subtitle_registry_seeded,
    save_subtitle_library_meta,
)
from src.utils import canonicalize_library_path, canonicalize_library_rel_path

logger = get_logger("subtitle_library_service")


def ensure_subtitle_library_seeded(*, config=None) -> dict:
    """One-time seed of global subtitle libs from transcripts + active CLIP libs."""
    cfg = config or load_config()
    if is_subtitle_registry_seeded(config=cfg):
        return {"seeded": False, "added": 0, "reason": "already"}

    meta = load_subtitle_library_meta(config=cfg)
    libraries = _normalize_library_map(meta.get("libraries", {}))
    meta["libraries"] = libraries

    candidates: list[str] = []
    seen: set[str] = set()
    for path in list_transcript_library_paths(config=cfg):
        key = canonicalize_library_path(path)
        if key and key not in seen:
            seen.add(key)
            candidates.append(key)

    try:
        from src.services.library_service import list_libraries

        for path in list_libraries().keys():
            key = canonicalize_library_path(path)
            if key and key not in seen:
                seen.add(key)
                candidates.append(key)
    except Exception:
        logger.warning("Subtitle library seed: failed to read CLIP libraries", exc_info=True)

    added = 0
    for path in candidates:
        if path in libraries:
            continue
        libraries[path] = {"files": {}, "last_scan": "", "index_state": "pending"}
        added += 1

    if added:
        meta["libraries"] = libraries
        save_subtitle_library_meta(meta, config=cfg)
        try:
            register_subtitle_library_videos(config=cfg)
        except Exception:
            logger.warning("Subtitle library seed: register videos failed", exc_info=True)

    mark_subtitle_registry_seeded(config=cfg)
    return {"seeded": True, "added": added, "reason": ""}


def list_subtitle_libraries(*, config=None, seed: bool = True) -> dict:
    cfg = config or load_config()
    if seed:
        ensure_subtitle_library_seeded(config=cfg)
    meta = load_subtitle_library_meta(config=cfg)
    return _normalize_library_map(meta.get("libraries", {}))


def add_subtitle_library(path, *, config=None) -> dict:
    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    meta = load_subtitle_library_meta(config=cfg)
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    normalized_path = canonicalize_library_path(path)

    if normalized_path in meta["libraries"]:
        return {"added": False, "reason": "exists", "path": normalized_path}

    for existing_path in meta["libraries"].keys():
        if _paths_overlap(existing_path, normalized_path):
            return {
                "added": False,
                "reason": "overlap",
                "path": normalized_path,
                "conflict_path": existing_path,
            }

    meta["libraries"][normalized_path] = {"files": {}, "last_scan": "", "index_state": "pending"}
    save_subtitle_library_meta(meta, config=cfg)
    return {"added": True, "reason": "", "path": normalized_path}


def register_subtitle_library_videos(*, config=None, library_path: str | None = None) -> dict:
    """Discover videos under global subtitle libraries and assign video_id."""
    from src.utils import get_video_hash

    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    meta = load_subtitle_library_meta(config=cfg)
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    target = canonicalize_library_path(library_path) if library_path else ""

    registered = 0
    updated = 0
    changed = False

    for root_path, lib_data in list(meta.get("libraries", {}).items()):
        if not isinstance(lib_data, dict):
            continue
        root_key = canonicalize_library_path(root_path)
        if target and root_key != target:
            continue
        if not os.path.isdir(root_path):
            continue

        lib_files = lib_data.setdefault("files", {})
        if not isinstance(lib_files, dict):
            lib_files = {}
            lib_data["files"] = lib_files

        for abs_path in _iter_library_video_paths(root_path):
            if not os.path.isfile(abs_path):
                continue
            rel_path = canonicalize_library_rel_path(os.path.relpath(abs_path, root_path))
            try:
                video_mod_time = os.path.getmtime(abs_path)
            except OSError:
                continue

            previous = dict(lib_files.get(rel_path, {}) or {})
            video_id = str(previous.get("vid", "") or "").strip()
            if not video_id:
                try:
                    video_id = get_video_hash(abs_path)
                except OSError:
                    continue
                registered += 1

            next_info = dict(previous)
            next_info["vid"] = video_id
            next_info["mod_time"] = video_mod_time
            # Subtitle registry does not track CLIP asset_state.
            next_info.pop("asset_state", None)
            next_info.pop("sync_failure_reason", None)

            if next_info != previous:
                lib_files[rel_path] = next_info
                updated += 1
                changed = True

        lib_data["files"] = lib_files

    if changed:
        save_subtitle_library_meta(meta, config=cfg)
    return {"registered": registered, "updated": updated, "changed": changed}


def list_subtitle_library_video_entries(*, config=None, register: bool = True) -> list[dict]:
    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    if register:
        register_subtitle_library_videos(config=cfg)
    meta = load_subtitle_library_meta(config=cfg)
    libraries = _normalize_library_map(meta.get("libraries", {}))
    entries: list[dict] = []
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
            video_path = os.path.normpath(os.path.join(root_path, str(rel_path or "")))
            source_exists = os.path.isfile(video_path)
            entries.append(
                {
                    "library_path": library_path,
                    "video_path": video_path,
                    "video_rel_path": str(rel_path or "").replace("\\", "/"),
                    "video_id": video_id,
                    "asset_state": "",
                    "source_exists": source_exists,
                    "sync_failure_reason": "",
                }
            )
    entries.sort(key=lambda item: (item["library_path"].lower(), item["video_rel_path"].lower()))
    return entries


def list_subtitle_search_scope_entries(*, config=None) -> list[dict]:
    """Entries for the search-scope picker when the subtitle/dialogue tab is active.

    ``asset_state`` is ``ready`` when shared OCR text exists for the video.
    """
    from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    transcript_ids = {
        str(row.get("video_id") or "").strip()
        for row in list_dialogue_transcript_summaries(config=cfg)
        if str(row.get("video_id") or "").strip()
    }
    entries: list[dict] = []
    for item in list_subtitle_library_video_entries(config=cfg, register=False):
        video_id = str(item.get("video_id") or "").strip()
        if not video_id:
            continue
        has_transcript = video_id in transcript_ids
        source_exists = bool(item.get("source_exists", True))
        entries.append(
            {
                "library_path": item.get("library_path") or "",
                "video_path": item.get("video_path") or "",
                "video_rel_path": item.get("video_rel_path") or "",
                "video_id": video_id,
                "asset_state": "ready" if has_transcript and source_exists else "missing_asset",
                "source_exists": source_exists,
                "has_transcript": has_transcript,
            }
        )
    entries.sort(
        key=lambda row: (
            str(row.get("library_path") or "").lower(),
            str(row.get("video_rel_path") or "").lower(),
        )
    )
    return entries


def list_subtitle_search_scope_library_options(*, config=None) -> list[dict]:
    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    by_lib: dict[str, dict] = {}
    for item in list_subtitle_search_scope_entries(config=cfg):
        lib = str(item.get("library_path") or "").strip()
        if not lib:
            continue
        bucket = by_lib.setdefault(
            lib,
            {
                "path": lib,
                "display_name": os.path.basename(lib.rstrip("\\/")) or lib,
                "ready_count": 0,
                "total_count": 0,
            },
        )
        bucket["total_count"] += 1
        if str(item.get("asset_state") or "").strip().lower() == "ready":
            bucket["ready_count"] += 1
    return [by_lib[key] for key in sorted(by_lib.keys(), key=lambda p: p.lower())]


def _clear_dialogue_side_effects(video_ids: list[str], *, config=None) -> None:
    """Clear per-profile dialogue state + legacy Lance dialogue rows for video_ids."""
    from src.storage.lance_store import delete_profile_dialogue_segments
    from src.storage.video_id_migration import iter_model_asset_storage_roots

    ids = sorted({str(v or "").strip() for v in video_ids if str(v or "").strip()})
    if not ids:
        return
    cfg = config or load_config()
    for root in iter_model_asset_storage_roots(cfg):
        base_dir = str(root.get("base_dir") or "").strip()
        if not base_dir:
            continue
        for video_id in ids:
            try:
                delete_profile_dialogue_segments(video_id, profile_base_dir=base_dir)
            except Exception:
                logger.warning(
                    "Failed clearing dialogue side-effects for %s in %s",
                    video_id,
                    base_dir,
                    exc_info=True,
                )


def clear_subtitle_transcripts(video_ids, *, config=None) -> dict:
    """Delete shared OCR transcripts for the given videos; keep library membership.

    Also clears per-profile dialogue_index_state and any legacy Lance dialogue rows.
    """
    cfg = config or load_config()
    ids = sorted({str(v or "").strip() for v in (video_ids or []) if str(v or "").strip()})
    cleared: list[str] = []
    missing: list[str] = []
    for video_id in ids:
        try:
            deleted = delete_dialogue_transcript(video_id, config=cfg)
        except Exception:
            logger.warning("Failed deleting transcript %s", video_id, exc_info=True)
            deleted = False
        if deleted:
            cleared.append(video_id)
        else:
            missing.append(video_id)
    # Always reset side state for requested ids (even if transcript already gone).
    _clear_dialogue_side_effects(ids, config=cfg)
    return {
        "cleared": cleared,
        "missing": missing,
        "cleared_count": len(cleared),
        "requested_count": len(ids),
    }


def prune_missing_subtitle_sources(*, config=None, clear_orphan_transcripts: bool = False) -> dict:
    """Drop registry file rows whose source media is gone.

    Safety rules (aligned with visual-library cleanup):
    - If the whole library root is offline/missing, skip it. Removable/network
      drives must not wipe OCR just because they were briefly unplugged.
    - By default do **not** delete transcripts. Re-scanning the same files later
      keeps the same video_id and can reuse existing OCR. Explicit remove-library
      / clear-selected still delete transcripts on purpose.
    """
    from src.services.library_service import count_video_id_refs

    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    meta = load_subtitle_library_meta(config=cfg)
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))

    removed_files = 0
    orphan_ids: list[str] = []
    skipped_offline_roots = 0
    changed = False

    for root_path, lib_data in list(meta.get("libraries", {}).items()):
        if not isinstance(lib_data, dict):
            continue
        # Same offline-root guard as visual cleanup_missing_library_files.
        if not os.path.exists(root_path):
            skipped_offline_roots += 1
            logger.info(
                "Skipping subtitle prune for offline library root: %s",
                root_path,
            )
            continue
        files = lib_data.get("files")
        if not isinstance(files, dict):
            continue
        keep: dict = {}
        for rel_path, info in files.items():
            if not isinstance(info, dict):
                continue
            abs_path = os.path.normpath(os.path.join(root_path, str(rel_path or "")))
            if os.path.isfile(abs_path):
                keep[rel_path] = info
                continue
            removed_files += 1
            changed = True
            video_id = str(info.get("vid") or "").strip()
            if video_id:
                orphan_ids.append(video_id)
        if keep != files:
            lib_data["files"] = keep

    if changed:
        save_subtitle_library_meta(meta, config=cfg)
        logger.warning(
            "Subtitle prune removed %d missing file row(s); clear_orphan_transcripts=%s",
            removed_files,
            bool(clear_orphan_transcripts),
        )

    cleared_transcripts = 0
    if clear_orphan_transcripts and orphan_ids:
        exclusive = sorted(
            {
                video_id
                for video_id in orphan_ids
                if count_video_id_refs(meta, video_id) == 0
            }
        )
        if exclusive:
            result = clear_subtitle_transcripts(exclusive, config=cfg)
            cleared_transcripts = int(result.get("cleared_count") or 0)

    return {
        "removed_files": removed_files,
        "orphan_video_ids": sorted(set(orphan_ids)),
        "cleared_transcripts": cleared_transcripts,
        "skipped_offline_roots": skipped_offline_roots,
        "changed": changed or cleared_transcripts > 0,
    }


def remove_subtitle_library(path, *, config=None, progress_callback=None) -> bool:
    """Remove a global subtitle library and its OCR transcripts. Does not touch Lance visual vectors."""
    cfg = config or load_config()
    ensure_subtitle_library_seeded(config=cfg)
    meta = load_subtitle_library_meta(config=cfg)
    meta["libraries"] = _normalize_library_map(meta.get("libraries", {}))
    normalized_path = canonicalize_library_path(path)
    library = meta["libraries"].get(normalized_path)
    if library is None:
        return False

    def _progress(percent: int, text: str = "") -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(int(percent), str(text or ""))
        except Exception:
            pass

    from src.services.library_service import count_video_id_refs

    removable_video_ids = sorted(
        {
            str(info.get("vid") or "").strip()
            for info in library.get("files", {}).values()
            if isinstance(info, dict)
            and str(info.get("vid") or "").strip()
            and count_video_id_refs(
                meta,
                str(info.get("vid") or "").strip(),
                exclude_library_path=normalized_path,
            )
            == 0
        }
    )

    _progress(2, "remove_library|meta")
    del meta["libraries"][normalized_path]
    save_subtitle_library_meta(meta, config=cfg)

    if removable_video_ids:
        total = len(removable_video_ids)
        _progress(20, "remove_library|transcripts")
        for index, video_id in enumerate(removable_video_ids):
            _progress(
                int(20 + (index / max(total, 1)) * 60),
                f"remove_library|{index + 1}|{total}|{video_id}",
            )
            try:
                delete_dialogue_transcript(str(video_id or ""), config=cfg)
            except Exception:
                pass
        _progress(85, "remove_library|side_state")
        _clear_dialogue_side_effects(removable_video_ids, config=cfg)

    _progress(100, "remove_library|done")
    return True
