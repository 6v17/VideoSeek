"""Working copy of dialogue cues for the understanding page.

The subtitle library stays untouched. If that library already has cues for the
video, the first visit copies them here. OCR, ASR, edits, and deletes on the
understanding page write only this copy. The library changes when the user
exports SRT and imports it there.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Mapping

_SAFE_ID_RE = re.compile(r"[^\w.\-]+", flags=re.UNICODE)


def working_copy_path(video_id: str, *, config=None) -> str:
    from src.storage.dialogue_transcript_store import get_dialogue_store_dir

    vid = str(video_id or "").strip()
    name = _SAFE_ID_RE.sub("_", vid).strip("._") or "video"
    folder = os.path.join(get_dialogue_store_dir(config=config), "understanding")
    return os.path.normpath(os.path.join(folder, f"{name}.json"))


def load_working_copy(video_id: str, *, config=None) -> dict[str, Any] | None:
    path = working_copy_path(video_id, config=config)
    if not os.path.isfile(path):
        return None
    try:
        payload = json.loads(open(path, encoding="utf-8").read())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("video_id") or "").strip() != str(video_id or "").strip():
        return None
    cues = payload.get("cues")
    if not isinstance(cues, list):
        return None
    payload["cues"] = [row for row in (_normalize_cue(item, index, "") for index, item in enumerate(cues)) if row]
    return payload


def save_working_copy(
    video_id: str,
    cues: list[Mapping[str, Any]] | None,
    *,
    origin: str,
    video_path: str = "",
    library_path: str = "",
    asr_source: str = "",
    config=None,
) -> dict[str, Any]:
    vid = str(video_id or "").strip()
    source = str(asr_source or "").strip()
    rows = [
        row
        for index, item in enumerate(list(cues or []))
        if (row := _normalize_cue(item, index, source))
    ]
    if not source and rows:
        source = str(rows[0].get("asr_source") or "").strip()
    payload = {
        "video_id": vid,
        "origin": str(origin or "").strip() or "local",
        "asr_source": source,
        "video_path": str(video_path or "").strip(),
        "library_path": str(library_path or "").strip(),
        "cues": rows,
    }
    path = working_copy_path(vid, config=config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, path)
    return payload


def ensure_working_copy(
    video_id: str,
    *,
    video_path: str = "",
    library_path: str = "",
    config=None,
) -> dict[str, Any]:
    """Return the page copy. Copy library cues once when this page has none yet."""
    vid = str(video_id or "").strip()
    existing = load_working_copy(vid, config=config) if vid else None
    if existing is not None:
        return {**existing, "present": True}
    if not vid:
        return {"present": False, "cues": [], "origin": "", "video_id": ""}
    from src.storage.dialogue_transcript_store import load_dialogue_transcript

    record = load_dialogue_transcript(vid, config=config) or {}
    segments = list(record.get("segments") or [])
    if not segments:
        return {"present": False, "cues": [], "origin": "", "video_id": vid}
    saved = save_working_copy(
        vid,
        segments,
        origin="library",
        video_path=str(record.get("video_path") or video_path or ""),
        library_path=str(record.get("library_path") or library_path or ""),
        asr_source=str(record.get("asr_source") or ""),
        config=config,
    )
    return {**saved, "present": True}


def _seg_index(value, fallback: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def update_working_cue(
    video_id: str,
    seg_index: int,
    *,
    start: float,
    end: float,
    text: str,
    speaker: str = "",
    config=None,
) -> bool:
    payload = load_working_copy(video_id, config=config)
    if payload is None:
        return False
    target = _seg_index(seg_index)
    if target < 0:
        return False
    found = False
    updated: list[dict[str, Any]] = []
    for row in payload.get("cues") or []:
        item = dict(row)
        if _seg_index(item.get("seg_index")) == target:
            item["start"] = float(start)
            item["end"] = float(end)
            item["text"] = str(text or "")
            item["speaker"] = str(speaker or "")
            found = True
        updated.append(item)
    if not found:
        return False
    save_working_copy(
        video_id,
        updated,
        origin=str(payload.get("origin") or "local"),
        video_path=str(payload.get("video_path") or ""),
        library_path=str(payload.get("library_path") or ""),
        asr_source=str(payload.get("asr_source") or ""),
        config=config,
    )
    return True


def delete_working_cue(video_id: str, seg_index: int, *, config=None) -> bool:
    payload = load_working_copy(video_id, config=config)
    if payload is None:
        return False
    target = _seg_index(seg_index)
    if target < 0:
        return False
    cues = list(payload.get("cues") or [])
    kept = [row for row in cues if _seg_index(row.get("seg_index")) != target]
    if len(kept) == len(cues):
        return False
    save_working_copy(
        video_id,
        kept,
        origin=str(payload.get("origin") or "local"),
        video_path=str(payload.get("video_path") or ""),
        library_path=str(payload.get("library_path") or ""),
        asr_source=str(payload.get("asr_source") or ""),
        config=config,
    )
    return True


def update_working_speaker(
    video_id: str,
    seg_index: int,
    speaker: str,
    *,
    config=None,
) -> bool:
    payload = load_working_copy(video_id, config=config)
    if payload is None:
        return False
    target = _seg_index(seg_index)
    if target < 0:
        return False
    from src.storage.dialogue_transcript_store import normalize_dialogue_speaker

    label = normalize_dialogue_speaker(speaker)
    found = False
    updated: list[dict[str, Any]] = []
    for row in payload.get("cues") or []:
        item = dict(row)
        if _seg_index(item.get("seg_index")) == target:
            item["speaker"] = label
            found = True
        updated.append(item)
    if not found:
        return False
    save_working_copy(
        video_id,
        updated,
        origin=str(payload.get("origin") or "local"),
        video_path=str(payload.get("video_path") or ""),
        library_path=str(payload.get("library_path") or ""),
        asr_source=str(payload.get("asr_source") or ""),
        config=config,
    )
    return True


def apply_speaker_assignments(
    video_id: str,
    assignments: Mapping[int, str],
    *,
    config=None,
) -> int:
    payload = load_working_copy(video_id, config=config)
    if payload is None or not assignments:
        return 0
    from src.storage.dialogue_transcript_store import normalize_dialogue_speaker

    wanted = {int(key): normalize_dialogue_speaker(value) for key, value in assignments.items()}
    changed = 0
    updated: list[dict[str, Any]] = []
    for row in payload.get("cues") or []:
        item = dict(row)
        label = wanted.get(_seg_index(item.get("seg_index")))
        if label is not None and label != str(item.get("speaker") or ""):
            item["speaker"] = label
            changed += 1
        updated.append(item)
    if changed:
        save_working_copy(
            video_id,
            updated,
            origin=str(payload.get("origin") or "local"),
            video_path=str(payload.get("video_path") or ""),
            library_path=str(payload.get("library_path") or ""),
            asr_source=str(payload.get("asr_source") or ""),
            config=config,
        )
    return changed


def rename_working_speakers(
    video_id: str,
    old_speaker: str,
    new_speaker: str,
    *,
    config=None,
) -> int:
    from src.storage.dialogue_transcript_store import normalize_dialogue_speaker

    source = normalize_dialogue_speaker(old_speaker)
    target = normalize_dialogue_speaker(new_speaker)
    payload = load_working_copy(video_id, config=config)
    if payload is None or not source or source == target:
        return 0
    changed = 0
    updated: list[dict[str, Any]] = []
    for row in payload.get("cues") or []:
        item = dict(row)
        if str(item.get("speaker") or "") == source:
            item["speaker"] = target
            changed += 1
        updated.append(item)
    if changed:
        save_working_copy(
            video_id,
            updated,
            origin=str(payload.get("origin") or "local"),
            video_path=str(payload.get("video_path") or ""),
            library_path=str(payload.get("library_path") or ""),
            asr_source=str(payload.get("asr_source") or ""),
            config=config,
        )
    return changed


def clear_working_speakers(video_id: str, *, config=None) -> int:
    payload = load_working_copy(video_id, config=config)
    if payload is None:
        return 0
    changed = 0
    updated: list[dict[str, Any]] = []
    for row in payload.get("cues") or []:
        item = dict(row)
        if str(item.get("speaker") or "").strip():
            item["speaker"] = ""
            changed += 1
        updated.append(item)
    if changed:
        save_working_copy(
            video_id,
            updated,
            origin=str(payload.get("origin") or "local"),
            video_path=str(payload.get("video_path") or ""),
            library_path=str(payload.get("library_path") or ""),
            asr_source=str(payload.get("asr_source") or ""),
            config=config,
        )
    return changed


def list_understanding_dialogue_cues(
    video_id: str,
    *,
    video_path: str = "",
    library_path: str = "",
    config=None,
) -> list[dict[str, Any]]:
    payload = ensure_working_copy(
        video_id,
        video_path=video_path,
        library_path=library_path,
        config=config,
    )
    return list(payload.get("cues") or [])


def _normalize_cue(item: Mapping[str, Any] | None, index: int, default_source: str) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    try:
        start = float(item.get("start") or 0.0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(item.get("end") or start)
    except (TypeError, ValueError):
        end = start
    if end < start:
        end = start
    try:
        seg_index = int(item.get("seg_index", index))
    except (TypeError, ValueError):
        seg_index = index
    from src.storage.dialogue_transcript_store import normalize_dialogue_speaker

    return {
        "seg_index": seg_index,
        "start": start,
        "end": end,
        "text": text,
        "language": str(item.get("language") or "").strip(),
        "asr_source": str(item.get("asr_source") or default_source or "").strip(),
        "speaker": normalize_dialogue_speaker(item.get("speaker")),
    }
