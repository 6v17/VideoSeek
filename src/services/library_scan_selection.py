"""Pure helpers for selecting which library files to process during index sync."""

from __future__ import annotations

import os
from collections.abc import Iterable


def plan_library_scan_paths(
    root_path: str,
    lib_files: dict | None,
    valid_files: Iterable[str],
    selected_video_ids: set[str] | None = None,
) -> list[str]:
    """Return absolute paths to process.

    When ``selected_video_ids`` is None, all ``valid_files`` are kept.
    Otherwise only files whose meta ``vid`` is in the set are kept.
    """
    files = list(valid_files or [])
    if selected_video_ids is None:
        return files
    wanted = {str(v).strip() for v in selected_video_ids if str(v or "").strip()}
    if not wanted:
        return []
    records = lib_files if isinstance(lib_files, dict) else {}
    planned: list[str] = []
    for abs_path in files:
        rel_path = os.path.relpath(abs_path, root_path)
        info = records.get(rel_path)
        if not isinstance(info, dict):
            continue
        video_id = str(info.get("vid", "") or "").strip()
        if video_id and video_id in wanted:
            planned.append(abs_path)
    return planned
