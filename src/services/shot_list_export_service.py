"""Export helpers for the desktop shot list (manifest + batch clips + FCPXML)."""

from __future__ import annotations

import os
import re
from types import SimpleNamespace
from typing import Any, Dict, List, Sequence

from src.services.shot_list_service import ShotListItem

_MAX_BATCH_EXPORT_CLIPS = 64  # keep aligned with agent_clip_service._MAX_BATCH_EXPORT_CLIPS


def _sanitize_export_filename_stem(stem: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(stem or "").strip())
    cleaned = cleaned.strip(" .") or "clip"
    return cleaned[:80]


def _normalize_export_output_dir(output_dir: str) -> str:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(output_dir or "").strip())))
    if not normalized:
        raise ValueError("output_dir is required.")
    from src.services.agent_clip_service import _output_path_allowed

    if not _output_path_allowed(normalized):
        raise ValueError("output_dir must not be inside an indexed library root.")
    os.makedirs(normalized, exist_ok=True)
    return normalized


def build_manifest_items_from_shot_list(items: Sequence[ShotListItem]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rank, item in enumerate(items, start=1):
        rows.append(
            {
                "id": item.id,
                "query": item.source_query or None,
                "client_request_id": item.id,
                "video_path": str(item.video_path),
                "start_sec": float(item.start_sec),
                "end_sec": float(item.end_sec),
                "score": float(item.score) if item.score is not None else None,
                "rank": rank,
                "notes": f"shot_list_rank={rank}",
            }
        )
    return rows


def export_shot_list_manifest(
    items: Sequence[ShotListItem],
    *,
    write_path: str,
    project: str = "VideoSeek",
) -> Dict[str, Any]:
    from src.web.agent_api import AgentManifestRequest, execute_export_manifest

    manifest_items = build_manifest_items_from_shot_list(items)
    if not manifest_items:
        raise ValueError("Shot list is empty.")
    body = AgentManifestRequest(
        project=str(project or "VideoSeek"),
        items=manifest_items,
        dedupe=False,
        write_path=str(write_path),
    )
    return execute_export_manifest(body)


def export_shot_list_fcpxml(
    items: Sequence[ShotListItem],
    *,
    write_path: str,
    project: str = "VideoSeek",
) -> Dict[str, Any]:
    from src.services.fcpxml_export_service import export_shot_list_fcpxml as _export

    if not items:
        raise ValueError("Shot list is empty.")
    return _export(
        items,
        write_path=write_path,
        project_name=str(project or "VideoSeek"),
        event_name="VideoSeek Shot List",
    )


def build_shot_list_batch_export_items(
    items: Sequence[ShotListItem],
    output_dir: str,
) -> List[SimpleNamespace]:
    normalized_dir = _normalize_export_output_dir(output_dir)
    if len(items) > _MAX_BATCH_EXPORT_CLIPS:
        raise ValueError(f"Shot list exceeds batch export limit ({_MAX_BATCH_EXPORT_CLIPS}).")

    batch_items: List[SimpleNamespace] = []
    used_names: set[str] = set()
    for index, item in enumerate(items, start=1):
        base_name = os.path.splitext(os.path.basename(item.video_path))[0] or "clip"
        stem = _sanitize_export_filename_stem(f"{index:02d}_{base_name}_{int(float(item.start_sec))}")
        filename = f"{stem}.mp4"
        suffix = 1
        while filename.lower() in used_names:
            suffix += 1
            filename = f"{stem}_{suffix}.mp4"
        used_names.add(filename.lower())
        output_path = os.path.join(normalized_dir, filename)
        batch_items.append(
            SimpleNamespace(
                video_path=str(item.video_path),
                start_sec=float(item.start_sec),
                end_sec=float(item.end_sec),
                output_path=output_path,
                client_request_id=item.id,
                silent=None,
                encode_mode=None,
            )
        )
    return batch_items


def export_shot_list_clips(
    items: Sequence[ShotListItem],
    *,
    output_dir: str,
    encode_mode: str = "copy",
    continue_on_error: bool = True,
    silent: bool | None = None,
) -> Dict[str, Any]:
    from src.services.agent_clip_service import execute_agent_batch_export_clips

    batch_items = build_shot_list_batch_export_items(items, output_dir)
    if not batch_items:
        raise ValueError("Shot list is empty.")
    body = SimpleNamespace(
        items=batch_items,
        encode_mode=encode_mode,
        silent=silent,
        continue_on_error=bool(continue_on_error),
    )
    return execute_agent_batch_export_clips(body)
