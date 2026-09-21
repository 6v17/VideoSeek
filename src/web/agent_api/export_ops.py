"""Manifest/export batch helpers local to the Agent API."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from src.app.config import load_config
from src.services.clip_export_service import (
    MAX_BATCH_EXPORT_CLIPS,
    execute_batch_export_clips,
    output_path_allowed,
    resolve_batch_export_timeout_sec,
)
from src.services.manifest_export_service import (
    dedupe_manifest_items,
    execute_export_manifest,
    format_timecode as _format_timecode,
    manifest_items_from_sources,
)
from src.utils import normalize_export_encode_mode

from .schemas import (
    AgentBatchExportClipItem,
    AgentBatchExportClipsRequest,
    AgentBatchSearchExportOptions,
    AgentBatchSearchRequest,
)


def _sanitize_export_filename_stem(stem: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(stem or "").strip())
    cleaned = cleaned.strip(" .") or "clip"
    return cleaned[:80]


def _normalize_export_output_dir(output_dir: str) -> str:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(output_dir or "").strip())))
    if not normalized:
        raise ValueError("export.output_dir is required.")
    if not output_path_allowed(normalized, config=load_config()):
        raise ValueError("export.output_dir must not be inside an indexed library root.")
    os.makedirs(normalized, exist_ok=True)
    return normalized


def resolve_export_clip_output_path(
    *,
    output_path: Optional[str] = None,
    output_dir: Optional[str] = None,
    video_path: str = "",
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    client_request_id: Optional[str] = None,
) -> str:
    """Resolve single-clip destination: full ``output_path`` or auto name under ``output_dir``."""
    path = str(output_path or "").strip()
    directory = str(output_dir or "").strip()
    if path and directory:
        raise ValueError("Provide either output_path or output_dir, not both.")
    if path:
        return path
    if not directory:
        raise ValueError("Provide output_path or output_dir.")
    out_dir = _normalize_export_output_dir(directory)
    stem = _sanitize_export_filename_stem(
        client_request_id
        or os.path.splitext(os.path.basename(str(video_path or "").strip()))[0]
        or "clip"
    )
    try:
        start_tag = int(max(0.0, float(start_sec)))
        end_tag = int(max(0.0, float(end_sec)))
    except (TypeError, ValueError):
        start_tag, end_tag = 0, 0
    filename = f"{stem}_{start_tag}s_{end_tag}s.mp4"
    destination = os.path.join(out_dir, filename)
    if not output_path_allowed(destination, config=load_config()):
        raise ValueError(f"export output path is not allowed: {destination}")
    return destination


def build_batch_export_items_from_search_results(
    search_payload: Dict[str, Any],
    export_opts: AgentBatchSearchExportOptions,
    *,
    mode: str,
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
) -> List[AgentBatchExportClipItem]:
    output_dir = _normalize_export_output_dir(export_opts.output_dir)
    sources = [block for block in (search_payload.get("results") or []) if block.get("ok")]
    raw_items = manifest_items_from_sources(
        sources,
        keep_per_source=int(export_opts.keep_per_source),
        mode=mode,
        expand_frame_hits=expand_frame_hits,
        pad_before_sec=pad_before_sec,
        pad_after_sec=pad_after_sec,
    )
    if export_opts.dedupe:
        raw_items = dedupe_manifest_items(raw_items, mode=mode)
    if not raw_items:
        return []

    if len(raw_items) > MAX_BATCH_EXPORT_CLIPS:
        raise ValueError(f"Export item count exceeds limit ({MAX_BATCH_EXPORT_CLIPS}).")

    items: List[AgentBatchExportClipItem] = []
    used_names: set[str] = set()
    for row in raw_items:
        stem = _sanitize_export_filename_stem(
            row.get("client_request_id") or row.get("query") or row.get("id") or "clip"
        )
        try:
            rank = int(row.get("rank") or 1)
        except (TypeError, ValueError):
            rank = 1
        filename = f"{stem}_rank{rank:02d}.mp4"
        suffix = 1
        while filename.lower() in used_names:
            suffix += 1
            filename = f"{stem}_rank{rank:02d}_{suffix}.mp4"
        used_names.add(filename.lower())
        output_path = os.path.join(output_dir, filename)
        if not output_path_allowed(output_path):
            raise ValueError(f"export output path is not allowed: {output_path}")
        items.append(
            AgentBatchExportClipItem(
                video_path=str(row["video_path"]),
                start_sec=float(row["start_sec"]),
                end_sec=float(row["end_sec"]),
                output_path=output_path,
                client_request_id=row.get("client_request_id"),
                silent=export_opts.silent,
                encode_mode=export_opts.encode_mode,
            )
        )
    return items


def _attach_batch_search_export(
    search_payload: Dict[str, Any],
    body: AgentBatchSearchRequest,
    *,
    mode: str,
) -> Dict[str, Any]:
    export_opts = body.export
    if export_opts is None:
        return search_payload

    from src.utils import has_ffmpeg

    if not has_ffmpeg():
        raise RuntimeError("FFmpeg is not available. Install or configure FFmpeg in VideoSeek settings.")

    try:
        items = build_batch_export_items_from_search_results(
            search_payload,
            export_opts,
            mode=mode,
            expand_frame_hits=bool(body.expand_frame_hits),
            pad_before_sec=float(body.pad_before_sec),
            pad_after_sec=float(body.pad_after_sec),
        )
    except ValueError as exc:
        search_payload["export"] = {
            "ok": False,
            "results": [],
            "error": {"code": "invalid_request", "message": str(exc)},
            "meta": {"total": 0, "succeeded": 0, "failed": 0},
        }
        search_payload["ok"] = False
        return search_payload

    if not items:
        search_payload["export"] = {
            "ok": False,
            "results": [],
            "error": {"code": "invalid_request", "message": "No exportable hits from batch search."},
            "meta": {"total": 0, "succeeded": 0, "failed": 0},
        }
        search_payload["ok"] = False
        return search_payload

    export_payload = execute_batch_export_clips(
        AgentBatchExportClipsRequest(
            items=items,
            encode_mode=export_opts.encode_mode,
            silent=export_opts.silent,
            continue_on_error=export_opts.continue_on_error,
        )
    )
    search_payload["export"] = export_payload
    search_payload["ok"] = bool(search_payload.get("ok")) and bool(export_payload.get("ok"))
    search_payload.setdefault("meta", {})["export_output_dir"] = _normalize_export_output_dir(export_opts.output_dir)
    return search_payload


def _resolve_batch_search_export_timeout_sec(body: AgentBatchSearchRequest, config=None) -> float:
    from .search import _resolve_batch_queries, _resolve_batch_timeout_sec

    base = _resolve_batch_timeout_sec(body, config=config)
    if body.export is None:
        return base
    try:
        query_count = len(_resolve_batch_queries(body))
    except ValueError:
        query_count = len(body.queries or [])
    item_count = max(1, query_count * int(body.export.keep_per_source))
    encode_mode = normalize_export_encode_mode(body.export.encode_mode or "copy")
    export_sec = resolve_batch_export_timeout_sec(item_count, encode_mode)
    from .constants import _BATCH_TIMEOUT_MAX_SEC

    return min(_BATCH_TIMEOUT_MAX_SEC, base + export_sec)
