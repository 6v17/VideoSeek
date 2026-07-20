"""Pure helpers for selecting which library files to process during index sync."""

from __future__ import annotations

import os
from collections.abc import Iterable

from src.app.logging_utils import get_logger
from src.storage.video_identity import canonicalize_library_rel_path

logger = get_logger("library_scan_selection")


def _abs_path_from_library_rel(root_path: str, rel_path: str) -> str:
    rel = canonicalize_library_rel_path(rel_path)
    if not rel:
        return ""
    return os.path.normpath(os.path.join(root_path, rel.replace("/", os.sep)))


def plan_library_scan_paths(
    root_path: str,
    lib_files: dict | None,
    valid_files: Iterable[str],
    selected_video_ids: set[str] | None = None,
) -> list[str]:
    """Return absolute paths to process.

    When ``selected_video_ids`` is None, all ``valid_files`` are kept.
    Otherwise resolve by ``vid`` first (meta/SQLite keys), then overlay discover
    paths — so Windows ``\\`` vs stored ``/`` cannot silently drop the whole set.
    """
    files = list(valid_files or [])
    if selected_video_ids is None:
        return files
    wanted = {str(v).strip() for v in selected_video_ids if str(v or "").strip()}
    if not wanted:
        return []

    records = lib_files if isinstance(lib_files, dict) else {}
    by_rel = {
        canonicalize_library_rel_path(key): value
        for key, value in records.items()
        if canonicalize_library_rel_path(key)
    }

    # Primary: selected ids → path from stable meta relative keys.
    planned_by_vid: dict[str, str] = {}
    for rel, info in by_rel.items():
        if not isinstance(info, dict):
            continue
        video_id = str(info.get("vid", "") or "").strip()
        if not video_id or video_id not in wanted:
            continue
        abs_path = _abs_path_from_library_rel(root_path, rel)
        if abs_path and os.path.isfile(abs_path):
            planned_by_vid[video_id] = abs_path

    meta_hits = len(planned_by_vid)

    # Overlay discover paths when rel keys also match (handles in-library moves).
    discover_hits = 0
    for abs_path in files:
        if not abs_path or not os.path.isfile(abs_path):
            continue
        try:
            rel_path = canonicalize_library_rel_path(os.path.relpath(abs_path, root_path))
        except ValueError:
            continue
        info = by_rel.get(rel_path)
        if not isinstance(info, dict):
            continue
        video_id = str(info.get("vid", "") or "").strip()
        if video_id and video_id in wanted:
            planned_by_vid[video_id] = abs_path
            discover_hits += 1

    planned = [planned_by_vid[vid] for vid in sorted(planned_by_vid)]
    unmatched = sorted(wanted - set(planned_by_vid))

    if not planned and wanted:
        logger.error(
            "Selected sync matched 0/%s video_ids (discovered=%s meta_files=%s root=%s). "
            "Refusing to treat this as a successful empty sync.",
            len(wanted),
            len(files),
            len(by_rel),
            root_path,
        )
    elif unmatched:
        logger.warning(
            "Selected sync unmatched %s/%s video_ids (matched=%s meta_first=%s discover_overlay=%s root=%s)",
            len(unmatched),
            len(wanted),
            len(planned),
            meta_hits,
            discover_hits,
            root_path,
        )
    elif meta_hits == 0 and discover_hits > 0:
        logger.warning(
            "Selected sync recovered %s paths only via discover overlay (meta key join missed; root=%s)",
            discover_hits,
            root_path,
        )

    return planned
