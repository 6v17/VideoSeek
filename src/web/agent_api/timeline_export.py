"""Agent API multi-clip timeline export (Jianying / FCPXML / FCP7 XML)."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Sequence, Tuple

from src.services.shot_list_service import ShotListItem

from .constants import API_VERSION, MAX_BATCH_QUERIES
from .schemas import AgentTimelineClipItem, AgentTimelineExportRequest

_TIMELINE_FORMATS = frozenset({"jianying", "fcpxml", "fcp7_xml"})
_MAX_TIMELINE_CLIPS = MAX_BATCH_QUERIES  # 64, aligned with batch export


def _normalize_format(value: str) -> str:
    key = str(value or "").strip().lower()
    aliases = {
        "jianying": "jianying",
        "capcut": "jianying",
        "剪映": "jianying",
        "fcpxml": "fcpxml",
        "resolve": "fcpxml",
        "davinci": "fcpxml",
        "fcp7": "fcp7_xml",
        "fcp7_xml": "fcp7_xml",
        "premiere": "fcp7_xml",
        "pr": "fcp7_xml",
        "xml": "fcp7_xml",
    }
    resolved = aliases.get(key, key)
    if resolved not in _TIMELINE_FORMATS:
        raise ValueError(
            f"format must be one of: jianying, fcpxml, fcp7_xml (got {value!r})"
        )
    return resolved


def _resolve_item_span(item: AgentTimelineClipItem) -> Tuple[float, float, str]:
    """Return (start_sec, end_sec, match_kind)."""
    has_range = item.start_sec is not None and item.end_sec is not None
    has_point = item.time_sec is not None
    if has_range:
        start = float(item.start_sec)
        end = float(item.end_sec)
        if end < start:
            start, end = end, start
        return start, end, "segment"
    if has_point:
        anchor = max(0.0, float(item.time_sec))
        return anchor, anchor, "frame"
    raise ValueError(
        "each item needs time_sec or both start_sec and end_sec "
        f"(video_path={item.video_path!r})"
    )


def normalize_timeline_items(
    items: Sequence[AgentTimelineClipItem],
) -> Tuple[List[ShotListItem], List[Dict[str, str]]]:
    """Convert request items to ShotListItem; missing/remote paths go to skipped."""
    if not items:
        raise ValueError("items must not be empty.")
    if len(items) > _MAX_TIMELINE_CLIPS:
        raise ValueError(f"Timeline size exceeds limit ({_MAX_TIMELINE_CLIPS}).")

    shots: List[ShotListItem] = []
    skipped: List[Dict[str, str]] = []
    for item in items:
        path = str(item.video_path or "").strip()
        lower = path.lower()
        if lower.startswith(("http://", "https://")):
            skipped.append({"path": path, "reason": "remote"})
            continue
        try:
            start_sec, end_sec, match_kind = _resolve_item_span(item)
        except ValueError as exc:
            skipped.append({"path": path or "(empty)", "reason": str(exc)})
            continue
        if not path:
            skipped.append({"path": "(empty)", "reason": "missing"})
            continue
        abs_path = os.path.normpath(os.path.abspath(os.path.expanduser(path)))
        if not os.path.isfile(abs_path):
            skipped.append({"path": abs_path, "reason": "missing"})
            continue
        item_id = str(item.client_request_id or "").strip() or str(uuid.uuid4())
        shots.append(
            ShotListItem(
                id=item_id,
                video_path=abs_path,
                start_sec=float(start_sec),
                end_sec=float(end_sec),
                score=None,
                match_kind=match_kind,
                source_query="",
                added_at="",
            )
        )
    return shots, skipped


def _sanitize_export_stem(stem: str) -> str:
    import re

    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(stem or "").strip())
    cleaned = cleaned.strip(" .") or "VideoSeek"
    return cleaned[:80]


def _resolve_xml_write_path(
    *,
    write_path: str | None,
    output_dir: str | None,
    format_key: str,
    project: str,
) -> str:
    from src.services.agent_clip_service import _output_path_allowed

    explicit = str(write_path or "").strip()
    if explicit:
        return _ensure_write_path(explicit, format_key=format_key)

    directory = str(output_dir or "").strip()
    if not directory:
        raise ValueError(
            "fcpxml / fcp7_xml require write_path or output_dir "
            "(e.g. output_dir=\"D:/Exports\")."
        )
    root = os.path.normpath(os.path.abspath(os.path.expanduser(directory)))
    if not root:
        raise ValueError("output_dir is empty.")
    if not _output_path_allowed(root):
        raise ValueError("output_dir must not be inside an indexed library root.")
    os.makedirs(root, exist_ok=True)
    ext = ".fcpxml" if format_key == "fcpxml" else ".xml"
    stem = _sanitize_export_stem(project)
    candidate = os.path.join(root, f"{stem}{ext}")
    if not os.path.exists(candidate):
        return candidate
    # Avoid overwrite when the same project name is reused.
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(root, f"{stem}_{stamp}{ext}")


def _ensure_write_path(write_path: str, *, format_key: str) -> str:
    from src.services.agent_clip_service import _output_path_allowed

    target = os.path.normpath(os.path.abspath(os.path.expanduser(str(write_path or "").strip())))
    if not target:
        raise ValueError("write_path is required for fcpxml / fcp7_xml.")
    lower = target.lower()
    if format_key == "fcpxml":
        if not lower.endswith(".fcpxml"):
            target = f"{target}.fcpxml"
    else:
        if not lower.endswith(".xml"):
            target = f"{target}.xml"
    parent = os.path.dirname(target)
    if parent and not _output_path_allowed(parent):
        raise ValueError("write_path must not be inside an indexed library root.")
    if parent:
        os.makedirs(parent, exist_ok=True)
    return target


def execute_agent_timeline_export(body: AgentTimelineExportRequest) -> Dict[str, Any]:
    started = time.perf_counter()
    format_key = _normalize_format(body.format)
    shots, skipped = normalize_timeline_items(body.items or [])
    if not shots:
        raise ValueError(
            "No local clips to export "
            f"(skipped={len(skipped)}; provide existing video_path + time_sec or start/end)."
        )

    project = str(body.project or "VideoSeek").strip() or "VideoSeek"
    payload: Dict[str, Any]

    if format_key == "jianying":
        from src.services.jianying_draft_service import (
            JianyingDraftError,
            export_shot_list_to_jianying_draft,
            is_jianying_draft_support_available,
        )

        if not is_jianying_draft_support_available():
            raise RuntimeError(
                "pyJianYingDraft is not installed. "
                "Install with: pip install pyJianYingDraft"
            )
        try:
            result = export_shot_list_to_jianying_draft(
                shots,
                drafts_dir=body.drafts_dir,
                draft_name=body.draft_name,
            )
        except JianyingDraftError as exc:
            detail = str(getattr(exc, "detail", "") or "").strip()
            message = str(exc)
            if detail:
                message = f"{message}: {detail}"
            raise RuntimeError(message) from exc
        jy_skipped = list(result.get("skipped") or [])
        skipped.extend(jy_skipped)
        payload = {
            "api_version": API_VERSION,
            "ok": True,
            "format": format_key,
            "draft_name": result.get("draft_name"),
            "draft_path": result.get("draft_path"),
            "drafts_dir": result.get("drafts_dir"),
            "export_path": result.get("draft_path"),
            "clip_count": int(result.get("exported_count") or 0),
            "skipped": skipped,
            "skipped_missing": sum(1 for row in skipped if row.get("reason") == "missing"),
            "client_request_id": body.client_request_id,
            "meta": {
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "project": project,
            },
        }
        return payload

    from src.services.fcpxml_export_service import export_shot_list_nle_xml

    write_path = _resolve_xml_write_path(
        write_path=body.write_path,
        output_dir=body.output_dir,
        format_key=format_key,
        project=project,
    )
    # Force extension by rewriting path before call; export_shot_list_nle_xml
    # also branches on suffix.
    result = export_shot_list_nle_xml(
        shots,
        write_path=write_path,
        project_name=project,
        event_name="VideoSeek Agent Timeline",
    )
    out_path = result.get("write_path") or write_path
    payload = {
        "api_version": API_VERSION,
        "ok": True,
        "format": str(result.get("format") or format_key),
        "write_path": out_path,
        "export_path": out_path,
        "clip_count": int(result.get("clip_count") or result.get("exported_count") or 0),
        "skipped": skipped,
        "skipped_missing": int(result.get("skipped_missing") or 0)
        + sum(1 for row in skipped if row.get("reason") == "missing"),
        "skipped_remote": int(result.get("skipped_remote") or 0),
        "client_request_id": body.client_request_id,
        "meta": {
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "project": project,
            "fcpxml_version": result.get("fcpxml_version"),
        },
    }
    return payload
