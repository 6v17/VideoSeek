"""Merge short ASR snippets into sentence-sized dialogue rows."""

from __future__ import annotations

from typing import Any


def merge_adjacent_transcripts(
    rows: list[dict[str, Any]],
    *,
    max_gap_sec: float = 0.65,
    max_merged_duration_sec: float = 20.0,
    max_merged_chars: int = 80,
) -> list[dict[str, Any]]:
    """Join nearby ASR rows so dialogue search indexes phrases, not single chars.

    Rows are expected to have ``start`` / ``end`` / ``text`` (and optional metadata).
    Vectors are intentionally dropped — callers re-embed after merge.
    """
    if not rows:
        return []

    ordered = sorted(rows, key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)))
    merged: list[dict[str, Any]] = []
    current = _copy_row(ordered[0])

    for item in ordered[1:]:
        next_row = _copy_row(item)
        gap = float(next_row["start"]) - float(current["end"])
        duration = float(next_row["end"]) - float(current["start"])
        combined_text = _join_text(str(current.get("text", "") or ""), str(next_row.get("text", "") or ""))
        same_language = _same_language(current.get("language"), next_row.get("language"))
        same_speaker = _same_speaker(current.get("speaker"), next_row.get("speaker"))
        if (
            gap <= float(max_gap_sec)
            and duration <= float(max_merged_duration_sec)
            and len(combined_text) <= int(max_merged_chars)
            and same_language
            and same_speaker
        ):
            current["end"] = float(next_row["end"])
            current["text"] = combined_text
            if not current.get("language") and next_row.get("language"):
                current["language"] = next_row.get("language")
            if not current.get("asr_source") and next_row.get("asr_source"):
                current["asr_source"] = next_row.get("asr_source")
            if not current.get("speaker") and next_row.get("speaker"):
                current["speaker"] = next_row.get("speaker")
            continue
        merged.append(current)
        current = next_row

    merged.append(current)
    return merged


def _copy_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "start": float(row.get("start", 0.0) or 0.0),
        "end": float(row.get("end", 0.0) or 0.0),
        "text": str(row.get("text", "") or "").strip(),
        "language": str(row.get("language", "") or "").strip(),
        "asr_source": str(row.get("asr_source", "") or "").strip(),
        "speaker": str(row.get("speaker", "") or "").strip()[:40],
    }


def _same_speaker(left: Any, right: Any) -> bool:
    return str(left or "").strip() == str(right or "").strip()


def _join_text(left: str, right: str) -> str:
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    # CJK / no-space scripts: concatenate; otherwise keep a single space.
    if _needs_space(left, right):
        return f"{left} {right}"
    return f"{left}{right}"


def _needs_space(left: str, right: str) -> bool:
    if not left or not right:
        return False
    left_ch = left[-1]
    right_ch = right[0]
    if _is_cjk(left_ch) or _is_cjk(right_ch):
        return False
    if left_ch.isspace() or right_ch.isspace():
        return False
    return True


def _is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3040 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _same_language(left: Any, right: Any) -> bool:
    a = str(left or "").strip().lower()
    b = str(right or "").strip().lower()
    if not a or not b:
        return True
    return a == b
