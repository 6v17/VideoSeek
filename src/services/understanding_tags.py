"""Parse and normalize free-form VLM tag outputs for evidence chunks."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, List

_TAG_MAX_CHARS = 48
_TAG_MAX_COUNT = 24
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
    if len(text) > _TAG_MAX_CHARS:
        text = text[:_TAG_MAX_CHARS].rstrip()
    return text


def _dedupe_tags(tags: Iterable[str], *, limit: int = _TAG_MAX_COUNT) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = normalize_tag_text(raw)
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= max(1, int(limit)):
            break
    return out


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
        recovered = [part for part in parts if normalize_tag_text(part)]
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
    """Extract tags from VLM output (JSON preferred; comma/line split fallback)."""
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
    parts = re.split(r"[,，、/;；|\n]+", text)
    return _dedupe_tags(parts, limit=max_tags)


def format_tags_for_display(tags: Iterable[str], *, separator: str = " · ") -> str:
    return str(separator).join(_dedupe_tags(tags))
