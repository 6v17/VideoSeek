"""Merge OCR lines sampled inside speech segments into subtitle cues."""

from __future__ import annotations

from typing import Any


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def merge_ocr_observations(
    observations: list[dict[str, Any]],
    *,
    max_gap_sec: float = 1.25,
) -> list[dict[str, Any]]:
    """Collapse nearby OCR hits with the same text into subtitle cues.

    Each observation: ``{start, end, text, language?, asr_source?}``
    (field names kept compatible with shared transcript JSON / export).
    """
    rows = sorted(
        (
            {
                "start": float(item.get("start", 0.0) or 0.0),
                "end": float(item.get("end", item.get("start", 0.0)) or 0.0),
                "text": _normalize_text(str(item.get("text", "") or "")),
                "language": str(item.get("language", "") or "").strip(),
                "asr_source": str(item.get("asr_source", "") or "").strip(),
            }
            for item in observations or []
            if _normalize_text(str((item or {}).get("text", "") or ""))
        ),
        key=lambda row: (row["start"], row["end"], row["text"]),
    )
    if not rows:
        return []

    merged: list[dict[str, Any]] = []
    current = dict(rows[0])
    for item in rows[1:]:
        same = item["text"] == current["text"]
        gap = float(item["start"]) - float(current["end"])
        if same and gap <= float(max_gap_sec):
            current["end"] = max(float(current["end"]), float(item["end"]))
            continue
        merged.append(current)
        current = dict(item)
    merged.append(current)
    return merged
