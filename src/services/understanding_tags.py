"""Parse and normalize free-form VLM tag outputs for evidence chunks."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Mapping

# Short labels only — never truncate prose into fake tags (motion mode used to).
_TAG_MAX_CHARS = 16
_TAG_MAX_COUNT = 24
_SENTENCE_PUNCT_RE = re.compile(r"[。！？!?\n；;]")
_SLASH_SPLIT_RE = re.compile(r"[/／|]+")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_QUOTED_STRING_RE = re.compile(r'"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\'')
_TAGS_ARRAY_RE = re.compile(
    r'(?:["\']?tags["\']?|["\']?labels["\']?|["\']?keywords["\']?|标签)\s*[:=]\s*\[(.*?)\]',
    re.IGNORECASE | re.DOTALL,
)
_JSON_DEBRIS_RE = re.compile(
    r'^(?:\{+\s*)?(?:["\']?tags["\']?\s*[:=]\s*\[?)|(?:\]+\s*\}+)$',
    re.IGNORECASE,
)


def _looks_like_prose(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if _SENTENCE_PUNCT_RE.search(value):
        return True
    # Motion captions are multi-clause; bare length catches truncated prose.
    if len(value) > 64 and ("，" in value or "," in value or " " in value):
        return True
    return False


def expand_raw_tag_pieces(value: Any) -> List[str]:
    """Split slash-joined VLM tags (prompt leakage: 人物/动作/场景) into atoms."""
    text = str(value or "").strip()
    if not text:
        return []
    if _looks_like_prose(text):
        return []
    if _SLASH_SPLIT_RE.search(text):
        parts = [p.strip() for p in _SLASH_SPLIT_RE.split(text) if p.strip()]
        if len(parts) >= 2:
            return parts
    return [text]


def normalize_tag_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    # Strip leftovers from failed JSON comma-splitting.
    text = text.strip(" \t\r\n\"'`")
    text = _JSON_DEBRIS_RE.sub("", text).strip(" \t\r\n\"'`[]{},:")
    if text.startswith("#"):
        text = text.lstrip("#").strip()
    text = " ".join(text.split())
    if not text or text.lower() in {"tags", "labels", "keywords"}:
        return ""
    if _looks_like_prose(text):
        return ""
    if len(text) > _TAG_MAX_CHARS:
        # Reject — truncating captions created the "description as tag" bug.
        return ""
    return text


def _dedupe_tags(tags: Iterable[str], *, limit: int = _TAG_MAX_COUNT) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in tags:
        for piece in expand_raw_tag_pieces(raw):
            tag = normalize_tag_text(piece)
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            out.append(tag)
            if len(out) >= max(1, int(limit)):
                return out
    return out


def projectable_tags(tags: Iterable[Any], *, limit: int = _TAG_MAX_COUNT) -> List[str]:
    """Normalize a chunk's tags for SQLite projection (filters prose / splits /)."""
    return _dedupe_tags(tags, limit=limit)


def _tags_from_json_payload(payload: Any) -> List[str] | None:
    if isinstance(payload, list):
        return [str(item) for item in payload]
    if isinstance(payload, dict):
        for key in ("tags", "labels", "keywords", "标签"):
            value = payload.get(key)
            if isinstance(value, list):
                return [str(item) for item in value]
            if isinstance(value, str) and value.strip():
                return re.split(r"[,，、/;；|\n]+", value)
    return None


def _normalize_jsonish(text: str) -> str:
    """Make common VLM JSON mistakes parseable."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    # Smart / fullwidth quotes → ASCII.
    cleaned = (
        cleaned.replace("“", '"')
        .replace("”", '"')
        .replace("‘", "'")
        .replace("’", "'")
        .replace("＂", '"')
        .replace("＇", "'")
    )
    # Fullwidth / Chinese commas between JSON values.
    cleaned = cleaned.replace("，", ",")
    # Trailing commas before ] or }.
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    return cleaned


def _extract_quoted_strings(text: str) -> List[str]:
    out: List[str] = []
    for match in _QUOTED_STRING_RE.finditer(text):
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        try:
            value = json.loads(f'"{raw}"')
        except Exception:
            value = raw.replace(r"\"", '"').replace(r"\'", "'")
        value = str(value or "").strip()
        if value and value.lower() not in {"tags", "labels", "keywords"}:
            out.append(value)
    return out


def _try_recover_tags_from_jsonish(text: str) -> List[str] | None:
    """Recover tags when json.loads fails on near-JSON model output."""
    cleaned = _normalize_jsonish(text)
    array_match = _TAGS_ARRAY_RE.search(cleaned)
    if array_match:
        quoted = _extract_quoted_strings(array_match.group(1))
        if quoted:
            return quoted
        parts = re.split(r"[,，、/;；|\n]+", array_match.group(1))
        recovered = [part for part in parts if normalize_tag_text(part) or expand_raw_tag_pieces(part)]
        if recovered:
            return recovered
    # Whole payload is a quoted-string list / object debris.
    if "{" in cleaned or "[" in cleaned:
        quoted = _extract_quoted_strings(cleaned)
        # Drop the key name if present as first quoted token.
        if quoted and quoted[0].lower() in {"tags", "labels", "keywords"}:
            quoted = quoted[1:]
        if quoted:
            return quoted
    return None


def _try_parse_json_tags(text: str) -> List[str] | None:
    candidates = [text, _normalize_jsonish(text)]
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
        candidates.insert(1, _normalize_jsonish(fenced.group(1)))
    # Common case: prose then a JSON object/array.
    for source in list(candidates):
        for opener, closer in (("{", "}"), ("[", "]")):
            start = source.find(opener)
            end = source.rfind(closer)
            if start >= 0 and end > start:
                candidates.append(source[start : end + 1])
    seen: set[str] = set()
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        tags = _tags_from_json_payload(parsed)
        if tags is not None:
            return tags
    return _try_recover_tags_from_jsonish(text)


def parse_vlm_tag_list(raw_text: str, *, max_tags: int = _TAG_MAX_COUNT) -> List[str]:
    """Extract tags from VLM output (JSON preferred; comma/line split fallback).

    Motion replies are prose + optional JSON. Never turn the prose body into tags:
    if JSON is missing and the text looks like sentences, return [].
    """
    text = str(raw_text or "").strip()
    if not text:
        return []
    from_json = _try_parse_json_tags(text)
    if from_json is not None:
        return _dedupe_tags(from_json, limit=max_tags)
    # Avoid naive comma-splitting of JSON-looking debris.
    if text[:1] in {"{", "["} or '"tags"' in text.lower() or "'tags'" in text.lower():
        recovered = _try_recover_tags_from_jsonish(text)
        if recovered:
            return _dedupe_tags(recovered, limit=max_tags)
    # Do not ingest motion/description prose as tags.
    if _looks_like_prose(text):
        return []
    parts = re.split(r"[,，、/;；|\n]+", text)
    return _dedupe_tags(parts, limit=max_tags)


def format_tags_for_display(tags: Iterable[str], *, separator: str = " · ") -> str:
    return str(separator).join(_dedupe_tags(tags))


def format_motion_cap_text(visible: str = "", change: str = "", *, joiner: str = "；") -> str:
    """Compose backward-compatible one-line cap from structured motion fields."""
    parts = [str(visible or "").strip(), str(change or "").strip()]
    body = str(joiner).join(part for part in parts if part)
    return body


def _clamp_inferred_weight(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        weight = float(value)
    except (TypeError, ValueError):
        return None
    if weight != weight:  # NaN
        return None
    return round(min(1.0, max(0.0, weight)), 3)


def _motion_fields_from_mapping(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    visible = str(payload.get("visible") or payload.get("subject") or "").strip()
    change = str(payload.get("change") or payload.get("delta") or "").strip()
    inferred = str(payload.get("inferred") or payload.get("soft") or "").strip()
    tags = _tags_from_json_payload(payload)
    if tags is None:
        tags = []
    weight = _clamp_inferred_weight(payload.get("inferred_weight"))
    if not inferred:
        weight = 0.0 if weight is None else weight
    # Accept if any structured field is present (including tags-only legacy JSON).
    if not (visible or change or inferred or tags or "inferred_weight" in payload or "visible" in payload or "change" in payload):
        return None
    if inferred and weight is None:
        weight = 0.35
    if not inferred:
        weight = 0.0
    return {
        "visible": visible[:120],
        "change": change[:120],
        "tags": _dedupe_tags(tags, limit=8),
        "inferred": inferred[:80],
        "inferred_weight": float(weight or 0.0),
    }


def parse_motion_vlm_payload(raw_text: str) -> dict[str, Any]:
    """Parse motion VLM output into visible/change/tags/inferred(+weight).

    Legacy prose + trailing ``{"tags":[...]}`` still works: prose becomes visible
    (or visible+change if two sentences), tags from JSON.
    """
    text = str(raw_text or "").strip()
    empty = {
        "visible": "",
        "change": "",
        "tags": [],
        "inferred": "",
        "inferred_weight": 0.0,
    }
    if not text:
        return empty

    candidates: list[str] = []
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text)
    # Trailing object after prose.
    brace = text.find("{")
    if brace > 0:
        candidates.append(text[brace:].strip())
    candidates.append(_normalize_jsonish(text))

    for candidate in candidates:
        body = str(candidate or "").strip()
        if not body:
            continue
        try:
            parsed = json.loads(body if body[:1] in {"{", "["} else body)
        except Exception:
            try:
                parsed = json.loads(_normalize_jsonish(body))
            except Exception:
                continue
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            parsed = parsed[0]
        fields = _motion_fields_from_mapping(parsed if isinstance(parsed, dict) else None)
        if fields is None:
            continue
        # Pure tags JSON (old motion): leave visible empty unless prose prefix exists.
        if not fields["visible"] and not fields["change"] and brace > 0:
            prose = text[:brace].strip()
            prose = re.sub(r"\s+", " ", prose).strip()
            if prose and not prose.startswith("{"):
                # Keep one short visible line; do not invent a change from leftover tags JSON.
                line = prose.split("\n", 1)[0].strip()
                fields["visible"] = line[:120]
        return fields

    # No JSON object: do not invent structure from long prose beyond a short visible line.
    tags = parse_vlm_tag_list(text)
    if _looks_like_prose(text):
        line = text.split("\n", 1)[0].strip()
        json_at = line.find("{")
        if json_at > 0:
            line = line[:json_at].strip()
        return {
            "visible": line[:120],
            "change": "",
            "tags": tags,
            "inferred": "",
            "inferred_weight": 0.0,
        }
    return {**empty, "tags": tags}
