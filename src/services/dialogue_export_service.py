"""Export shared dialogue transcripts to SRT / TXT / JSON."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from src.storage.dialogue_transcript_store import (
    ensure_shared_transcripts,
    list_dialogue_transcript_records,
    load_dialogue_transcript,
)

ExportFormat = Literal["srt", "txt", "json"]

_SAFE_NAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _safe_basename(value: str, fallback: str = "dialogue") -> str:
    name = os.path.splitext(os.path.basename(str(value or "").strip()))[0]
    name = _SAFE_NAME_RE.sub("_", name).strip(" .")
    return name or fallback


def _format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds or 0.0) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def render_dialogue_srt(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    index = 1
    for item in segments or []:
        text = str((item or {}).get("text", "") or "").strip()
        if not text:
            continue
        speaker = str((item or {}).get("speaker") or "").strip()
        if speaker:
            text = f"{speaker}：{text}"
        start = float((item or {}).get("start", 0.0) or 0.0)
        end = float((item or {}).get("end", start) or start)
        if end < start:
            end = start
        blocks.append(
            f"{index}\n{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}\n{text}\n"
        )
        index += 1
    return "\n".join(blocks).rstrip() + ("\n" if blocks else "")


def render_dialogue_txt(segments: list[dict[str, Any]], *, include_timestamps: bool = True) -> str:
    lines: list[str] = []
    for item in segments or []:
        text = str((item or {}).get("text", "") or "").strip()
        if not text:
            continue
        if include_timestamps:
            start = float((item or {}).get("start", 0.0) or 0.0)
            end = float((item or {}).get("end", start) or start)
            speaker = str((item or {}).get("speaker") or "").strip()
            line = f"{speaker}：{text}" if speaker else text
            lines.append(f"[{start:08.3f} --> {end:08.3f}] {line}")
        else:
            speaker = str((item or {}).get("speaker") or "").strip()
            lines.append(f"{speaker}：{text}" if speaker else text)
    return "\n".join(lines) + ("\n" if lines else "")


def render_dialogue_json(record: dict[str, Any]) -> str:
    payload = {
        "video_id": str(record.get("video_id", "") or ""),
        "video_path": str(record.get("video_path", "") or ""),
        "library_path": str(record.get("library_path", "") or ""),
        "asr_source": str(record.get("asr_source", "") or ""),
        "segment_count": int(record.get("segment_count") or len(record.get("segments") or []) or 0),
        "segments": list(record.get("segments") or []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _resolve_records(video_ids: list[str] | None, *, config=None) -> list[dict[str, Any]]:
    ensure_shared_transcripts(config=config)
    want = {str(item or "").strip() for item in (video_ids or []) if str(item or "").strip()}
    if want:
        records: list[dict[str, Any]] = []
        for video_id in sorted(want):
            payload = load_dialogue_transcript(video_id, config=config)
            if payload:
                records.append(payload)
        return records
    return list_dialogue_transcript_records(config=config)


def export_dialogue_transcripts(
    output_dir: str,
    *,
    format: ExportFormat = "srt",
    video_ids: list[str] | None = None,
    config=None,
) -> dict[str, Any]:
    """Export shared transcripts into ``output_dir`` (one file per video)."""
    fmt = str(format or "srt").strip().lower()
    if fmt not in {"srt", "txt", "json"}:
        return {"ok": False, "error": f"unsupported format: {format}", "exported": 0, "files": []}

    out_dir = os.path.normpath(str(output_dir or "").strip())
    if not out_dir:
        return {"ok": False, "error": "missing output_dir", "exported": 0, "files": []}
    os.makedirs(out_dir, exist_ok=True)

    records = _resolve_records(video_ids, config=config)
    if not records:
        return {"ok": False, "error": "no shared dialogue transcripts", "exported": 0, "files": []}

    files: list[str] = []
    errors: list[str] = []
    used_names: set[str] = set()
    for record in records:
        video_id = str(record.get("video_id") or "").strip() or "unknown"
        stem = _safe_basename(str(record.get("video_path") or ""), fallback=video_id)
        if stem in used_names:
            stem = f"{stem}_{_safe_basename(video_id)}"
        used_names.add(stem)
        path = os.path.join(out_dir, f"{stem}.{fmt}")
        try:
            if fmt == "srt":
                content = render_dialogue_srt(list(record.get("segments") or []))
            elif fmt == "txt":
                content = render_dialogue_txt(list(record.get("segments") or []))
            else:
                content = render_dialogue_json(record)
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
            files.append(path)
        except OSError as exc:
            errors.append(f"{video_id}: {exc}")

    return {
        "ok": bool(files) and not errors,
        "exported": len(files),
        "files": files,
        "errors": errors,
        "format": fmt,
        "output_dir": out_dir,
        "error": "; ".join(errors) if errors and not files else "",
    }


def export_dialogue_json_to_path(video_id: str, dest_path: str, *, config=None) -> dict[str, Any]:
    vid = str(video_id or "").strip()
    path = os.path.normpath(str(dest_path or "").strip())
    if not vid:
        return {"ok": False, "error": "missing video_id", "path": ""}
    if not path:
        return {"ok": False, "error": "missing dest_path", "path": ""}
    record = load_dialogue_transcript(vid, config=config)
    if not record:
        return {"ok": False, "error": "no shared dialogue transcript", "path": ""}
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_dialogue_json(record))
    return {"ok": True, "path": path, "segment_count": int(record.get("segment_count") or 0)}
