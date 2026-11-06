"""Recap duration targets and clock helpers.

Clocks use MM:SS under one hour and H:MM:SS after that, same as search timecodes.

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
from src.utils import format_timecode_seconds

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
    return format_timecode_seconds(int(round(total)))

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
