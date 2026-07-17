"""Shared dialogue transcripts — raw ASR text, independent of CLIP profiles.

Vectors for semantic search stay in per-profile Lance ``dialogue_segments``.
This store only keeps the reusable raw material: time + text + language.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from src.app.config import get_data_storage_paths
from src.app.logging_utils import get_logger
from src.storage.video_identity import canonicalize_library_path

logger = get_logger("dialogue_transcript_store")

_SAFE_VIDEO_ID_RE = re.compile(r"[^A-Za-z0-9._-]+")


def get_dialogue_store_dir(*, config=None) -> str:
    data_dir = get_data_storage_paths(config=config)["data_dir"]
    return os.path.normpath(os.path.join(data_dir, "dialogue"))


def get_dialogue_transcripts_dir(*, config=None) -> str:
    return os.path.join(get_dialogue_store_dir(config=config), "transcripts")


def _safe_video_filename(video_id: str) -> str:
    cleaned = _SAFE_VIDEO_ID_RE.sub("_", str(video_id or "").strip())
    return cleaned or "unknown"


def transcript_path(video_id: str, *, config=None) -> str:
    return os.path.join(
        get_dialogue_transcripts_dir(config=config),
        f"{_safe_video_filename(video_id)}.json",
    )


def save_dialogue_transcript(
    video_id: str,
    segments: list[dict[str, Any]],
    *,
    library_path: str = "",
    video_path: str = "",
    asr_source: str = "",
    config=None,
) -> dict[str, Any]:
    """Persist shared ASR transcript for one video (overwrites previous)."""
    video_id = str(video_id or "").strip()
    if not video_id:
        return {"ok": False, "error": "missing video_id", "segment_count": 0}

    rows: list[dict[str, Any]] = []
    for item in segments or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", 0.0) or 0.0),
                "text": text,
                "language": str(item.get("language", "") or "").strip(),
                "asr_source": str(item.get("asr_source", "") or asr_source or "").strip(),
            }
        )

    payload = {
        "video_id": video_id,
        "library_path": canonicalize_library_path(library_path) if library_path else "",
        "video_path": os.path.normpath(str(video_path or "")),
        "asr_source": str(asr_source or (rows[0].get("asr_source") if rows else "") or "").strip(),
        "segment_count": len(rows),
        "segments": rows,
    }
    out_dir = get_dialogue_transcripts_dir(config=config)
    os.makedirs(out_dir, exist_ok=True)
    path = transcript_path(video_id, config=config)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)
    return {"ok": True, "path": path, "segment_count": len(rows)}


def load_dialogue_transcript(video_id: str, *, config=None) -> dict[str, Any] | None:
    video_id = str(video_id or "").strip()
    if not video_id:
        return None
    path = transcript_path(video_id, config=config)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Unreadable dialogue transcript %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    segments = payload.get("segments")
    if not isinstance(segments, list):
        return None
    return payload


def delete_dialogue_transcript(video_id: str, *, config=None) -> bool:
    path = transcript_path(video_id, config=config)
    if not os.path.isfile(path):
        return False
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def list_dialogue_transcript_records(*, config=None) -> list[dict[str, Any]]:
    """List all shared transcript payloads (lightweight metadata + segments)."""
    root = get_dialogue_transcripts_dir(config=config)
    if not os.path.isdir(root):
        return []
    records: list[dict[str, Any]] = []
    for name in sorted(os.listdir(root)):
        if not name.lower().endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        video_id = str(payload.get("video_id", "") or "").strip()
        if not video_id:
            video_id = os.path.splitext(name)[0]
        segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
        records.append(
            {
                "video_id": video_id,
                "library_path": str(payload.get("library_path", "") or ""),
                "video_path": str(payload.get("video_path", "") or ""),
                "asr_source": str(payload.get("asr_source", "") or ""),
                "segment_count": int(payload.get("segment_count") or len(segments) or 0),
                "segments": segments,
            }
        )
    return records


def list_shared_transcript_segments(
    video_id: str = "",
    *,
    config=None,
) -> list[dict[str, Any]]:
    """Flat segment rows for one video, or all videos when ``video_id`` is empty."""
    want = str(video_id or "").strip()
    rows: list[dict[str, Any]] = []
    if want:
        payload = load_dialogue_transcript(want, config=config)
        records = [payload] if payload else []
    else:
        records = list_dialogue_transcript_records(config=config)

    for payload in records:
        if not payload:
            continue
        vid = str(payload.get("video_id", "") or "").strip()
        lib = str(payload.get("library_path", "") or "")
        media = str(payload.get("video_path", "") or "")
        default_asr = str(payload.get("asr_source", "") or "")
        for item in payload.get("segments") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            rows.append(
                {
                    "video_id": vid,
                    "library_path": lib,
                    "video_path": media,
                    "start": float(item.get("start", 0.0) or 0.0),
                    "end": float(item.get("end", 0.0) or 0.0),
                    "text": text,
                    "language": str(item.get("language", "") or "").strip(),
                    "asr_source": str(item.get("asr_source", "") or default_asr).strip(),
                }
            )
    rows.sort(key=lambda item: (item["video_id"], item["start"], item["end"]))
    return rows


def import_transcripts_from_profile_lance(*, config=None) -> int:
    """One-time style import: copy text from any profile Lance dialogue table into shared JSON.

    Skips videos that already have a shared transcript. Returns imported video count.
    """
    from src.storage.lance_store import (
        DIALOGUE_SEGMENTS_TABLE_NAME,
        _connect_lance,
        _list_table_names,
        get_lance_dir,
        list_dialogue_transcript_segments,
    )

    data_dir = get_data_storage_paths(config=config)["data_dir"]
    assets_root = os.path.join(data_dir, "model_assets")
    if not os.path.isdir(assets_root):
        return 0

    existing = {
        str(item.get("video_id") or "").strip()
        for item in list_dialogue_transcript_records(config=config)
    }
    imported = 0
    for provider in os.listdir(assets_root):
        provider_dir = os.path.join(assets_root, provider)
        if not os.path.isdir(provider_dir):
            continue
        for variant in os.listdir(provider_dir):
            profile_base = os.path.join(provider_dir, variant)
            if not os.path.isdir(get_lance_dir(profile_base)):
                continue
            try:
                db = _connect_lance(profile_base)
                if DIALOGUE_SEGMENTS_TABLE_NAME not in _list_table_names(db):
                    continue
            except Exception:
                continue
            rows = list_dialogue_transcript_segments(
                profile_base_dir=profile_base,
                config=config,
            )
            by_video: dict[str, list[dict[str, Any]]] = {}
            meta: dict[str, dict[str, str]] = {}
            for row in rows:
                vid = str(row.get("video_id") or "").strip()
                if not vid or vid in existing:
                    continue
                by_video.setdefault(vid, []).append(row)
                meta[vid] = {
                    "library_path": str(row.get("library_path") or ""),
                    "video_path": str(row.get("video_path") or ""),
                    "asr_source": str(row.get("asr_source") or ""),
                }
            for vid, segs in by_video.items():
                info = meta.get(vid) or {}
                result = save_dialogue_transcript(
                    vid,
                    segs,
                    library_path=info.get("library_path", ""),
                    video_path=info.get("video_path", ""),
                    asr_source=info.get("asr_source", ""),
                    config=config,
                )
                if result.get("ok"):
                    existing.add(vid)
                    imported += 1
    if imported:
        logger.info("Imported %s dialogue transcripts into shared store", imported)
    return imported


def ensure_shared_transcripts(*, config=None) -> int:
    """Ensure shared store exists; import from legacy profile Lance if empty-ish."""
    os.makedirs(get_dialogue_transcripts_dir(config=config), exist_ok=True)
    records = list_dialogue_transcript_records(config=config)
    if records:
        return 0
    return import_transcripts_from_profile_lance(config=config)
