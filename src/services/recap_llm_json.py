"""Salvage LLM JSON for recap plan / cut-list payloads.

``recap_service`` re-exports these names.
"""

from __future__ import annotations

import json
import re
from typing import Any

def _extract_json(text: str) -> str:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.startswith("json"):
            body = body[4:]
        body = body.strip()
    start = body.find("{")
    end = body.rfind("}")
    if start >= 0 and end > start:
        return body[start : end + 1]
    return body

def _repair_llm_json(text: str) -> str:
    """Fix the usual LLM JSON slips: trailing commas, missing commas, smart quotes."""
    body = str(text or "").replace("\u201c", '"').replace("\u201d", '"')
    body = body.replace("\u2018", "'").replace("\u2019", "'")
    body = re.sub(r",\s*([}\]])", r"\1", body)
    body = re.sub(r"([}\]])\s*([{\[])", r"\1,\2", body)
    body = re.sub(
        r'("(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?|true|false|null)\s*\n\s*"',
        r'\1,\n"',
        body,
        flags=re.IGNORECASE,
    )
    return body

def _extract_balanced_object(text: str, start: int) -> str:
    if start < 0 or start >= len(text) or text[start] != "{":
        return ""
    depth = 0
    in_str = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""

def _salvage_cut_list_payload(text: str) -> dict[str, Any]:
    title = "解说剪辑"
    match = re.search(r'"title"\s*:\s*"((?:\\.|[^"\\])*)"', text)
    if match:
        try:
            title = json.loads(f'"{match.group(1)}"')
        except json.JSONDecodeError:
            title = match.group(1)
    clips: list[Any] = []
    cursor = 0
    while cursor < len(text):
        start = text.find("{", cursor)
        if start < 0:
            break
        blob = _extract_balanced_object(text, start)
        if not blob:
            cursor = start + 1
            continue
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError:
            try:
                parsed = json.loads(_repair_llm_json(blob))
            except json.JSONDecodeError:
                cursor = start + 1
                continue
        if isinstance(parsed, dict) and "clips" not in parsed and ("src_in" in parsed or "vo" in parsed):
            clips.append(parsed)
            cursor = start + len(blob)
            continue
        cursor = start + 1
    if not clips:
        raise json.JSONDecodeError("No clip objects", text, 0)
    return {"title": str(title or "解说剪辑").strip() or "解说剪辑", "clips": clips}

def _loads_json_object(text: str) -> dict[str, Any]:
    raw = _extract_json(text)
    for candidate in (raw, _repair_llm_json(raw)):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise json.JSONDecodeError("No JSON object", str(text or ""), 0)

def _loads_cut_list_json(text: str) -> dict[str, Any]:
    try:
        return _loads_json_object(text)
    except json.JSONDecodeError:
        pass
    body = str(text or "").strip()
    start = body.find("{")
    salvage_src = body[start:] if start >= 0 else _extract_json(text)
    return _salvage_cut_list_payload(salvage_src)
