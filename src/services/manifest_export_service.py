"""Shared search-result / shot-list JSON manifest export."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence

from src.app.config import load_config
from src.storage.config_store import get_search_mode

API_VERSION = "1"
DEFAULT_FRAME_PAD_BEFORE_SEC = 3.0
DEFAULT_FRAME_PAD_AFTER_SEC = 3.0


def format_timecode(seconds: float) -> str:
    """HH:MM:SS for Agent API / manifest payloads."""
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = int(total % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def normalize_manifest_mode(mode: Optional[str], config=None) -> str:
    cfg = config or load_config()
    normalized = str(mode or get_search_mode(cfg)).strip().lower()
    if normalized not in {"frame", "chunk"}:
        normalized = get_search_mode(cfg)
    return normalized


def _interval_overlap_ratio(start_a, end_a, start_b, end_b) -> float:
    left = max(float(start_a), float(start_b))
    right = min(float(end_a), float(end_b))
    overlap = max(0.0, right - left)
    shorter = max(1e-6, min(float(end_a) - float(start_a), float(end_b) - float(start_b)))
    return overlap / shorter


def _should_deduplicate(item_a: Dict[str, Any], item_b: Dict[str, Any], *, mode: str) -> bool:
    from src.services.search_scope import normalize_scope_path

    def _norm(path: str) -> str:
        return normalize_scope_path(path)

    if _norm(item_a.get("video_path", "")) != _norm(item_b.get("video_path", "")):
        return False
    if _interval_overlap_ratio(item_a["start_sec"], item_a["end_sec"], item_b["start_sec"], item_b["end_sec"]) > 0.5:
        return True
    if mode == "frame" and abs(float(item_a["start_sec"]) - float(item_b["start_sec"])) <= 2.0:
        return True
    return False


def _manifest_item_rank(item: Dict[str, Any]) -> int:
    try:
        return int(item.get("rank") or 9999)
    except (TypeError, ValueError):
        return 9999


def dedupe_manifest_items(items: List[Dict[str, Any]], *, mode: str) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=_manifest_item_rank)
    kept: List[Dict[str, Any]] = []
    for candidate in ordered:
        if any(_should_deduplicate(candidate, existing, mode=mode) for existing in kept):
            continue
        kept.append(candidate)
    return kept


def manifest_items_from_sources(
    sources: List[Dict[str, Any]],
    *,
    keep_per_source: int,
    mode: Optional[str],
    expand_frame_hits: bool,
    pad_before_sec: float,
    pad_after_sec: float,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for block in sources:
        if not block.get("ok", True) and block.get("error"):
            continue
        block_mode = str(block.get("mode") or mode or "chunk")
        query = str(block.get("query") or "")
        client_request_id = block.get("client_request_id")
        hits = sorted(block.get("hits") or [], key=lambda row: row.get("rank", 999))
        for hit in hits[:keep_per_source]:
            stem = str(client_request_id or query or "item")
            item_id = f"{stem}-rank-{hit.get('rank', 1)}"
            items.append(
                {
                    "id": item_id,
                    "query": query,
                    "client_request_id": client_request_id,
                    "video_path": hit["video_path"],
                    "start_sec": float(hit["start_sec"]),
                    "end_sec": float(hit["end_sec"]),
                    "score": hit.get("score"),
                    "rank": hit.get("rank"),
                    "duration_sec": hit.get("duration_sec", max(0.0, float(hit["end_sec"]) - float(hit["start_sec"]))),
                    "start_timecode": hit.get("start_timecode") or format_timecode(hit["start_sec"]),
                    "end_timecode": hit.get("end_timecode") or format_timecode(hit["end_sec"]),
                    "clip_window": hit.get("clip_window"),
                    "video_duration_sec": hit.get("video_duration_sec"),
                    "notes": f"source_query={query}" if query else "",
                }
            )
    return items


def _coerce_manifest_item(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return {
        "id": getattr(item, "id", None),
        "query": getattr(item, "query", None),
        "client_request_id": getattr(item, "client_request_id", None),
        "video_path": getattr(item, "video_path"),
        "start_sec": float(getattr(item, "start_sec")),
        "end_sec": float(getattr(item, "end_sec")),
        "score": getattr(item, "score", None),
        "rank": getattr(item, "rank", None),
        "notes": getattr(item, "notes", None),
    }


def execute_export_manifest(
    body=None,
    *,
    project: str = "rough-cut",
    items: Optional[Sequence[Any]] = None,
    sources: Optional[List[Dict[str, Any]]] = None,
    keep_per_source: int = 2,
    dedupe: bool = True,
    write_path: Optional[str] = None,
    expand_frame_hits: bool = True,
    pad_before_sec: float = DEFAULT_FRAME_PAD_BEFORE_SEC,
    pad_after_sec: float = DEFAULT_FRAME_PAD_AFTER_SEC,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a JSON cut list. Accepts kwargs or a duck-typed AgentManifestRequest body."""
    if body is not None:
        project = str(getattr(body, "project", None) or project)
        items = getattr(body, "items", None) if items is None else items
        sources = getattr(body, "sources", None) if sources is None else sources
        keep_per_source = int(getattr(body, "keep_per_source", keep_per_source))
        dedupe = bool(getattr(body, "dedupe", dedupe))
        write_path = getattr(body, "write_path", write_path)
        expand_frame_hits = bool(getattr(body, "expand_frame_hits", expand_frame_hits))
        pad_before_sec = float(getattr(body, "pad_before_sec", pad_before_sec))
        pad_after_sec = float(getattr(body, "pad_after_sec", pad_after_sec))
        mode = getattr(body, "mode", mode)

    resolved_mode = normalize_manifest_mode(mode) if mode else "chunk"
    if items:
        raw_items = [_coerce_manifest_item(item) for item in items]
    elif sources:
        raw_items = manifest_items_from_sources(
            sources,
            keep_per_source=int(keep_per_source),
            mode=mode,
            expand_frame_hits=bool(expand_frame_hits),
            pad_before_sec=float(pad_before_sec),
            pad_after_sec=float(pad_after_sec),
        )
    else:
        raise ValueError("Provide items or sources.")

    if not raw_items:
        raise ValueError("Manifest has no clip items.")

    deduped = dedupe_manifest_items(raw_items, mode=resolved_mode) if dedupe else list(raw_items)
    manifest = {"version": 1, "project": project, "items": deduped}
    written_path = None
    if write_path:
        target = os.path.normpath(os.path.abspath(os.path.expanduser(str(write_path).strip())))
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
        written_path = target

    return {
        "api_version": API_VERSION,
        "ok": True,
        "manifest": manifest,
        "meta": {
            "item_count": len(deduped),
            "dedupe": bool(dedupe),
            "write_path": written_path,
        },
    }
