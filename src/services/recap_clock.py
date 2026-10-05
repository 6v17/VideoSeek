"""Recap duration targets and MM:SS clock helpers.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

from src.services.recap_constants import (
    MAX_RECAP_SEC,
    MIN_RECAP_SEC,
    RECAP_STORY_RATIO,
    TARGET_RECAP_SEC,
)
from src.services.recap_match import recap_story_window

def recap_target_sec(duration_sec: float) -> float:
    """Scale recap length to the story window, clamped to about 3–12 minutes."""
    _start, story_end = recap_story_window(duration_sec)
    raw = max(0.0, float(story_end or 0.0)) * RECAP_STORY_RATIO
    return round(min(MAX_RECAP_SEC, max(MIN_RECAP_SEC, raw or TARGET_RECAP_SEC)), 1)

def recap_duration_bounds(target_sec: float) -> tuple[float, float]:
    """Soft floor + hard ceiling. Floor is advisory; we never pad cuts just to hit it."""
    target = max(MIN_RECAP_SEC, float(target_sec or TARGET_RECAP_SEC))
    return (
        round(max(90.0, target * 0.5), 1),
        round(min(MAX_RECAP_SEC, max(target, target * 1.15)), 1),
    )

def format_recap_clock(sec: float) -> str:
    total = max(0.0, float(sec or 0.0))
    minutes = int(total // 60)
    seconds = int(round(total - minutes * 60.0))
    if seconds >= 60:
        minutes += 1
        seconds = 0
    return f"{minutes:02d}:{seconds:02d}"

def format_recap_clock_range(start: float, end: float) -> str:
    return f"{format_recap_clock(start)}–{format_recap_clock(end)}"

def parse_recap_clock(text: str) -> float:
    body = str(text or "").strip().replace("，", ".").replace("：", ":")
    if not body:
        return 0.0
    if ":" in body:
        parts = [part.strip() for part in body.split(":")]
        if len(parts) == 2:
            return max(0.0, float(parts[0] or 0.0) * 60.0 + float(parts[1] or 0.0))
        if len(parts) == 3:
            return max(
                0.0,
                float(parts[0] or 0.0) * 3600.0
                + float(parts[1] or 0.0) * 60.0
                + float(parts[2] or 0.0),
            )
    return max(0.0, float(body))
