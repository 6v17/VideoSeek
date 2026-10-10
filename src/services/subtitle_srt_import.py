"""Import SRT cues onto videos already registered in the subtitle library.

Matching does not require a visual sync. A file is used when its name (without
extension) lines up with exactly one registered video, or with the video that
sits in the same folder when several share that name. A trailing language tag
such as ``.zh`` or ``.zh-Hans`` is ignored when the plain name does not match.
"""

from __future__ import annotations

import os
import re
from html import unescape
from typing import Any

from src.storage.dialogue_transcript_store import (
    list_dialogue_transcript_summaries,
    save_dialogue_transcript,
)

SRT_SOURCE_ID = "srt"

_ARROW_RE = re.compile(
    r"(?P<start>\d+:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*(?P<end>\d+:\d{2}:\d{2}[,.]\d{1,3})"
)
_TS_RE = re.compile(r"(?P<h>\d+):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{1,3})")
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_ASS_RE = re.compile(r"\{[^}]*\}")
_LANG_TAIL_RE = re.compile(
    r"[._-]([a-z]{2,3}(?:[-_](?:[a-z]{2}|[a-z]{4}|\d{3}))?)$",
    re.IGNORECASE,
)


def parse_srt_text(text: str) -> list[dict[str, Any]]:
    """Return cue dicts ``{start, end, text}``. Malformed blocks are skipped."""
    body = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if body.startswith("\ufeff"):
        body = body.lstrip("\ufeff")
    if not body:
        return []
    cues: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", body):
        lines = [line.strip() for line in block.split("\n")]
        lines = [line for line in lines if line]
        if not lines:
            continue
        stamp_at = 0
        if lines[0].isdigit() and len(lines) > 1:
            stamp_at = 1
        match = _ARROW_RE.search(lines[stamp_at])
        if match is None:
            continue
        start = _timestamp_seconds(match.group("start"))
        end = _timestamp_seconds(match.group("end"))
        if start is None or end is None:
            continue
        if end < start:
            end = start
        text_lines = [_clean_cue_line(line) for line in lines[stamp_at + 1 :]]
        cue_text = " ".join(line for line in text_lines if line).strip()
        if not cue_text:
            continue
        cues.append({"start": start, "end": end, "text": cue_text})
    return cues


def plan_subtitle_srt_import(srt_paths, *, config=None) -> dict[str, Any]:
    """Match SRT files to registered subtitle-library videos. Does not write."""
    from src.services.subtitle_library_service import list_subtitle_library_video_entries

    entries = [
        item
        for item in list_subtitle_library_video_entries(config=config, register=True)
        if item.get("source_exists") and str(item.get("video_id") or "").strip()
    ]
    by_stem: dict[str, list[dict]] = {}
    for item in entries:
        stem = _stem(str(item.get("video_path") or ""))
        if stem:
            by_stem.setdefault(stem, []).append(item)

    existing_ids = {
        str(row.get("video_id") or "").strip()
        for row in list_dialogue_transcript_summaries(config=config)
        if str(row.get("video_id") or "").strip()
    }

    raw_matches: list[dict[str, Any]] = []
    unmatched: list[str] = []
    skipped: list[dict[str, str]] = []
    seen_paths: set[str] = set()

    for raw_path in srt_paths or []:
        path = os.path.normpath(str(raw_path or "").strip())
        if not path:
            continue
        key = os.path.normcase(path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        if not path.lower().endswith(".srt") or not os.path.isfile(path):
            skipped.append({"srt_path": path, "reason": "unreadable"})
            continue
        try:
            cues = parse_srt_text(_read_srt_text(path))
        except OSError:
            skipped.append({"srt_path": path, "reason": "unreadable"})
            continue
        if not cues:
            skipped.append({"srt_path": path, "reason": "empty"})
            continue
        chosen, how = _resolve_video(path, by_stem)
        if chosen is None:
            if how == "ambiguous":
                skipped.append({"srt_path": path, "reason": "ambiguous"})
            else:
                unmatched.append(path)
            continue
        raw_matches.append(
            {
                "video_id": str(chosen.get("video_id") or ""),
                "video_path": str(chosen.get("video_path") or ""),
                "library_path": str(chosen.get("library_path") or ""),
                "srt_path": path,
                "segments": cues,
                "segment_count": len(cues),
                "exact": how == "exact",
            }
        )

    matches: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in raw_matches:
        grouped.setdefault(item["video_id"], []).append(item)
    for video_id, group in grouped.items():
        group.sort(key=_match_rank)
        winner = group[0]
        winner["replaces"] = video_id in existing_ids
        matches.append(winner)
        for extra in group[1:]:
            skipped.append({"srt_path": extra["srt_path"], "reason": "duplicate"})

    matches.sort(key=lambda item: os.path.normcase(item["srt_path"]))
    return {
        "matches": matches,
        "unmatched": unmatched,
        "skipped": skipped,
    }


def apply_subtitle_srt_import(matches, *, config=None) -> dict[str, Any]:
    """Write planned matches into the shared subtitle store."""
    imported = 0
    segments = 0
    errors: list[str] = []
    for item in matches or []:
        video_id = str(item.get("video_id") or "").strip()
        if not video_id:
            continue
        try:
            saved = save_dialogue_transcript(
                video_id,
                list(item.get("segments") or []),
                library_path=str(item.get("library_path") or ""),
                video_path=str(item.get("video_path") or ""),
                asr_source=SRT_SOURCE_ID,
                config=config,
            )
        except OSError as exc:
            errors.append(f"{os.path.basename(str(item.get('srt_path') or video_id))}: {exc}")
            continue
        if not saved.get("ok"):
            errors.append(
                f"{os.path.basename(str(item.get('srt_path') or video_id))}: {saved.get('error') or 'save failed'}"
            )
            continue
        imported += 1
        segments += int(saved.get("segment_count") or 0)
    return {
        "ok": imported > 0 and not errors,
        "imported": imported,
        "segments": segments,
        "errors": errors,
    }


def _timestamp_seconds(token: str) -> float | None:
    match = _TS_RE.fullmatch(str(token or "").strip())
    if match is None:
        return None
    millis = match.group("ms").ljust(3, "0")[:3]
    return (
        int(match.group("h")) * 3600
        + int(match.group("m")) * 60
        + int(match.group("s"))
        + int(millis) / 1000.0
    )


def _clean_cue_line(line: str) -> str:
    text = _ASS_RE.sub("", line)
    text = _TAG_RE.sub("", text)
    return unescape(text).strip()


def _read_srt_text(path: str) -> str:
    with open(path, "rb") as handle:
        raw = handle.read()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeError:
        return raw.decode("gb18030")


def _stem(path: str) -> str:
    return os.path.splitext(os.path.basename(str(path or "")))[0].casefold()


def _match_stems(path: str) -> list[str]:
    stem = _stem(path)
    if not stem:
        return []
    keys = [stem]
    stripped = _LANG_TAIL_RE.sub("", stem).strip(" ._")
    if stripped and stripped != stem:
        keys.append(stripped)
    return keys


def _resolve_video(srt_path: str, by_stem: dict[str, list[dict]]) -> tuple[dict | None, str]:
    for index, key in enumerate(_match_stems(srt_path)):
        candidates = by_stem.get(key) or []
        if not candidates:
            continue
        chosen = _pick_candidate(srt_path, candidates)
        if chosen is None:
            return None, "ambiguous"
        return chosen, "exact" if index == 0 else "lang"
    return None, "unmatched"


def _pick_candidate(srt_path: str, candidates: list[dict]) -> dict | None:
    srt_dir = os.path.normcase(os.path.dirname(os.path.normpath(srt_path)))
    beside = [
        item
        for item in candidates
        if os.path.normcase(os.path.dirname(str(item.get("video_path") or ""))) == srt_dir
    ]
    pool = beside or candidates
    if len(pool) == 1:
        return pool[0]
    return None


def _match_rank(item: dict[str, Any]) -> tuple:
    srt_dir = os.path.normcase(os.path.dirname(item["srt_path"]))
    video_dir = os.path.normcase(os.path.dirname(item["video_path"]))
    beside = 0 if srt_dir == video_dir else 1
    exact = 0 if item.get("exact") else 1
    return (beside, exact, os.path.normcase(item["srt_path"]))
