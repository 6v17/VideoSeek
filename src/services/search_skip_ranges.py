"""Parse multi-range skip windows for search result filtering."""

from __future__ import annotations

import re

_MAX_RANGE_SEC = 24 * 3600.0
_HMS_COLON_RE = re.compile(
    r"^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$"
)
_COMPOUND_HMS_RE = re.compile(
    r"^(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m)?(?:(\d+(?:\.\d+)?)s)?$",
    re.IGNORECASE,
)


def normalize_search_skip_ranges_text(rules_text) -> str:
    text = str(rules_text or "")
    text = text.replace("\uFF1B", ";").replace("\uFF0C", ";").replace("\r", "\n")
    parts = []
    for chunk in text.replace("\n", ";").split(";"):
        item = chunk.strip()
        if item:
            parts.append(item)
    return "; ".join(parts)


def _parse_hms_colon(text: str):
    match = _HMS_COLON_RE.fullmatch(text)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    if minutes > 59 or seconds >= 60:
        raise ValueError("invalid hms time")
    return hours * 3600.0 + minutes * 60.0 + seconds


def _parse_compound_hms(text: str):
    if not any(ch in text for ch in "hmsHMS"):
        return None
    match = _COMPOUND_HMS_RE.fullmatch(text)
    if not match or not any(match.groups()):
        return None
    hours = float(match.group(1) or 0.0)
    minutes = float(match.group(2) or 0.0)
    seconds = float(match.group(3) or 0.0)
    return hours * 3600.0 + minutes * 60.0 + seconds


def _parse_duration_token(token):
    text = str(token or "").strip().lower()
    if not text:
        return None

    if ":" in text:
        seconds = _parse_hms_colon(text)
        if seconds is None:
            raise ValueError("invalid hms time")
    else:
        compound = _parse_compound_hms(text)
        if compound is not None:
            seconds = compound
        else:
            multiplier = 1.0
            if text.endswith("ms"):
                multiplier = 0.001
                text = text[:-2]
            elif text.endswith("s"):
                text = text[:-1]
            elif text.endswith("m"):
                multiplier = 60.0
                text = text[:-1]
            elif text.endswith("h"):
                multiplier = 3600.0
                text = text[:-1]
            if not text:
                return None
            value = float(text)
            if value < 0:
                raise ValueError("duration must be >= 0")
            seconds = value * multiplier

    if seconds < 0:
        raise ValueError("duration must be >= 0")
    if seconds > _MAX_RANGE_SEC:
        raise ValueError("duration too large")
    return float(seconds)


def _format_duration_token(seconds: float) -> str:
    value = max(0.0, float(seconds))
    whole = int(round(value))
    if abs(value - whole) > 1e-6:
        return f"{value:g}"
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    if minutes > 0:
        return f"{minutes}:{secs:02d}"
    return str(secs)


def parse_search_skip_range_item(item, index: int = 0) -> dict:
    raw = str(item or "").strip()
    if not raw:
        raise ValueError(f"Range {index + 1} is empty")
    lowered = raw.lower()
    if lowered.startswith("end-") or lowered == "end":
        amount_text = raw.split("-", 1)[1].strip() if "-" in raw else ""
        if not amount_text:
            raise ValueError(f"Range {index + 1} end-relative amount is required")
        amount = _parse_duration_token(amount_text)
        if amount is None or amount <= 0:
            raise ValueError(f"Range {index + 1} end-relative amount must be > 0")
        return {"kind": "from_end", "amount": float(amount), "index": index}

    if "-" not in raw:
        raise ValueError(f"Range {index + 1} must use start-end format")
    start_text, end_text = raw.split("-", 1)
    start_text = start_text.strip()
    end_text = end_text.strip()
    if start_text.lower() == "end":
        amount = _parse_duration_token(end_text)
        if amount is None or amount <= 0:
            raise ValueError(f"Range {index + 1} end-relative amount must be > 0")
        return {"kind": "from_end", "amount": float(amount), "index": index}

    start = _parse_duration_token(start_text)
    end = _parse_duration_token(end_text)
    if start is None or end is None:
        raise ValueError(f"Range {index + 1} start and end are required")
    if end <= start:
        raise ValueError(f"Range {index + 1} end must be greater than start")
    return {
        "kind": "absolute",
        "start": float(start),
        "end": float(end),
        "index": index,
    }


def validate_search_skip_ranges(rules_text) -> tuple[bool, str]:
    normalized = normalize_search_skip_ranges_text(rules_text)
    if not normalized:
        return True, ""
    for index, chunk in enumerate(normalized.split(";")):
        item = chunk.strip()
        if not item:
            continue
        try:
            parse_search_skip_range_item(item, index)
        except (TypeError, ValueError):
            return False, f"Range {index + 1}"
    return True, ""


def parse_search_skip_ranges(rules_text) -> list[dict]:
    normalized = normalize_search_skip_ranges_text(rules_text)
    if not normalized:
        return []
    rules = []
    for index, chunk in enumerate(normalized.split(";")):
        item = chunk.strip()
        if not item:
            continue
        rules.append(parse_search_skip_range_item(item, index))
    return rules


def format_search_skip_range_item(rule: dict) -> str:
    kind = str(rule.get("kind") or "")
    if kind == "from_end":
        return f"end-{_format_duration_token(rule.get('amount', 0))}"
    return (
        f"{_format_duration_token(rule.get('start', 0))}"
        f"-{_format_duration_token(rule.get('end', 0))}"
    )


def migrate_legacy_skip_edges_to_ranges(intro_sec=0, outro_sec=0) -> str:
    parts = []
    try:
        intro = max(0, int(float(intro_sec or 0)))
    except (TypeError, ValueError):
        intro = 0
    try:
        outro = max(0, int(float(outro_sec or 0)))
    except (TypeError, ValueError):
        outro = 0
    if intro > 0:
        parts.append(f"0-{_format_duration_token(intro)}")
    if outro > 0:
        parts.append(f"end-{_format_duration_token(outro)}")
    return "; ".join(parts)


def summarize_search_skip_ranges(rules_text, *, empty_text: str = "") -> str:
    normalized = normalize_search_skip_ranges_text(rules_text)
    if not normalized:
        return str(empty_text or "")
    parts = [chunk.strip() for chunk in normalized.split(";") if chunk.strip()]
    if not parts:
        return str(empty_text or "")
    return " | ".join(parts[:2]) + (" …" if len(parts) > 2 else "")


def resolve_skip_intervals(rules: list[dict], video_end: float | None) -> list[tuple[float, float]]:
    intervals: list[tuple[float, float]] = []
    end = None if video_end is None else max(0.0, float(video_end))
    for rule in rules or []:
        kind = str(rule.get("kind") or "")
        if kind == "from_end":
            if end is None:
                continue
            amount = max(0.0, float(rule.get("amount") or 0.0))
            if amount <= 0:
                continue
            start = max(0.0, end - amount)
            if start < end:
                intervals.append((start, end))
            continue
        start = max(0.0, float(rule.get("start") or 0.0))
        stop = max(0.0, float(rule.get("end") or 0.0))
        if end is not None:
            stop = min(stop, end)
        if stop > start:
            intervals.append((start, stop))
    if not intervals:
        return []
    intervals.sort(key=lambda item: item[0])
    merged: list[tuple[float, float]] = [intervals[0]]
    for start, stop in intervals[1:]:
        prev_start, prev_stop = merged[-1]
        if start <= prev_stop:
            merged[-1] = (prev_start, max(prev_stop, stop))
        else:
            merged.append((start, stop))
    return merged


def covered_skip_seconds(intervals: list[tuple[float, float]]) -> float:
    return sum(max(0.0, stop - start) for start, stop in intervals or [])


def probe_in_skip_intervals(probe: float, intervals: list[tuple[float, float]]) -> bool:
    value = max(0.0, float(probe))
    for start, stop in intervals or []:
        if start <= value <= stop:
            return True
    return False
