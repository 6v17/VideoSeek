"""Sampling FPS rule parsing and resolution."""

from __future__ import annotations


def _parse_duration_token(token):
    text = str(token or "").strip().lower()
    if not text:
        return None
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
    value = float(text)
    return max(0.0, value * multiplier)


def _has_explicit_duration_unit(token):
    text = str(token or "").strip().lower()
    if not text:
        return False
    if text == "0":
        return True
    return text.endswith("m")


def normalize_sampling_fps_rules_text(rules_text):
    text = str(rules_text or "")
    text = text.replace("\uFF1B", ";").replace("\uFF0C", ";").replace("\r", "\n")
    parts = []
    for chunk in text.replace("\n", ";").split(";"):
        item = chunk.strip()
        if item:
            parts.append(item)
    return "; ".join(parts)


def normalize_sampling_fps_mode(mode):
    normalized = str(mode or "").strip().lower()
    if normalized in {"dynamic", "rules", "mapping", "duration_map", "adaptive", "auto"}:
        return "dynamic"
    return "fixed"


def _parse_sampling_rule_item(item, index):
    if "=" not in item or "-" not in item:
        raise ValueError(f"Rule {index + 1} must use start-end=fps format")

    range_part, fps_part = item.split("=", 1)
    start_text, end_text = range_part.split("-", 1)
    start_text = start_text.strip()
    end_text = end_text.strip()
    if start_text and not _has_explicit_duration_unit(start_text):
        raise ValueError(f"Rule {index + 1} start duration must include a unit")
    if end_text and not _has_explicit_duration_unit(end_text):
        raise ValueError(f"Rule {index + 1} end duration must include a unit")
    min_duration = _parse_duration_token(start_text) if start_text.strip() else 0.0
    max_duration = _parse_duration_token(end_text) if end_text.strip() else None
    fps_value = float(fps_part.strip())
    if fps_value < 0.01:
        raise ValueError(f"Rule {index + 1} fps must be at least 0.01")
    if max_duration is not None and max_duration < min_duration:
        raise ValueError(f"Rule {index + 1} end duration must be greater than start duration")
    return {
        "min_duration": float(min_duration),
        "max_duration": None if max_duration is None else float(max_duration),
        "fps": float(fps_value),
        "index": index,
    }


def validate_sampling_fps_rules(rules_text):
    normalized_text = normalize_sampling_fps_rules_text(rules_text)
    if not normalized_text:
        return True, ""

    parsed_rules = []
    for index, chunk in enumerate(normalized_text.split(";")):
        item = chunk.strip()
        if not item:
            continue
        try:
            parsed_rules.append(_parse_sampling_rule_item(item, index))
        except (TypeError, ValueError):
            return False, f"Rule {index + 1}"

    sorted_rules = sorted(
        parsed_rules,
        key=lambda rule: (rule["min_duration"], float("inf") if rule["max_duration"] is None else rule["max_duration"]),
    )
    previous_rule = None
    for rule in sorted_rules:
        if previous_rule is None:
            previous_rule = rule
            continue
        previous_max = previous_rule["max_duration"]
        if previous_max is None or rule["min_duration"] < previous_max:
            return False, f"Rule {rule['index'] + 1}"
        previous_rule = rule
    return True, ""


def validate_sampling_fps_rules_full_coverage(rules_text):
    """
    Require dynamic rules to fully cover [0, +inf):
    - first range starts at 0
    - ranges are contiguous (no gaps)
    - final range has no upper bound
    """
    is_valid, invalid_ref = validate_sampling_fps_rules(rules_text)
    if not is_valid:
        return False, invalid_ref

    rules = parse_sampling_fps_rules(rules_text)
    if not rules:
        return True, ""

    ordered = sorted(
        rules,
        key=lambda rule: (rule["min_duration"], float("inf") if rule["max_duration"] is None else rule["max_duration"]),
    )
    first = ordered[0]
    if float(first["min_duration"]) != 0.0:
        return False, f"Rule {first['index'] + 1}"

    for current, nxt in zip(ordered, ordered[1:]):
        current_max = current["max_duration"]
        if current_max is None:
            return False, f"Rule {nxt['index'] + 1}"
        if float(nxt["min_duration"]) != float(current_max):
            return False, f"Rule {nxt['index'] + 1}"

    last = ordered[-1]
    if last["max_duration"] is not None:
        return False, f"Rule {last['index'] + 1}"
    return True, ""


def ensure_sampling_fps_rules_open_tail(rules_text, default_tail_fps=1):
    """
    Auto-append an open-ended tail rule when the final range has an upper bound.
    Example: "0-10m=2" -> "0-10m=2; 10m-=1"
    """
    normalized = normalize_sampling_fps_rules_text(rules_text)
    if not normalized:
        return normalized

    is_valid, _ = validate_sampling_fps_rules(normalized)
    if not is_valid:
        return normalized

    rules = parse_sampling_fps_rules(normalized)
    if not rules:
        return normalized

    ordered = sorted(
        rules,
        key=lambda rule: (rule["min_duration"], float("inf") if rule["max_duration"] is None else rule["max_duration"]),
    )
    last = ordered[-1]
    if last["max_duration"] is None:
        return normalized

    tail_start_minutes = float(last["max_duration"]) / 60.0
    if abs(tail_start_minutes - round(tail_start_minutes)) < 1e-9:
        tail_start_text = f"{int(round(tail_start_minutes))}m"
    else:
        tail_start_text = f"{tail_start_minutes:g}m"

    try:
        tail_fps = max(0.01, float(default_tail_fps))
    except (TypeError, ValueError):
        tail_fps = 1.0
    tail_rule = f"{tail_start_text}-={tail_fps:g}"
    return normalize_sampling_fps_rules_text(f"{normalized}; {tail_rule}")


def parse_sampling_fps_rules(rules_text):
    rules = []
    normalized_text = normalize_sampling_fps_rules_text(rules_text)
    for index, chunk in enumerate(normalized_text.split(";")):
        item = chunk.strip()
        if not item:
            continue
        try:
            rules.append(_parse_sampling_rule_item(item, index))
        except (TypeError, ValueError):
            continue
    return rules


def _match_sampling_rule(duration_sec, rules):
    matched_rule = None
    matched_width = None
    for rule in rules:
        min_duration = float(rule["min_duration"])
        max_duration = rule["max_duration"]
        if duration_sec < min_duration:
            continue
        if max_duration is not None and duration_sec >= float(max_duration):
            continue
        width = float("inf") if max_duration is None else float(max_duration) - min_duration
        if matched_rule is None or width < matched_width or (width == matched_width and rule["index"] > matched_rule["index"]):
            matched_rule = rule
            matched_width = width
    return matched_rule


def resolve_sampling_fps(duration_sec=None, config=None, requested_fps=None):
    from src.app.config import load_config

    config = dict(config or load_config())
    base_fps = float(requested_fps) if requested_fps is not None else float(config.get("fps", 1.0))
    base_fps = max(0.01, base_fps)
    if normalize_sampling_fps_mode(config.get("sampling_fps_mode", "fixed")) != "dynamic":
        return base_fps

    try:
        duration_value = float(duration_sec)
    except (TypeError, ValueError):
        return base_fps
    if duration_value <= 0:
        return base_fps
    rules = parse_sampling_fps_rules(config.get("sampling_fps_rules", ""))
    matched_rule = _match_sampling_rule(duration_value, rules)
    if matched_rule is not None:
        return float(matched_rule["fps"])
    return base_fps
