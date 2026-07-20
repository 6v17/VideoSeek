from __future__ import annotations

import re
from typing import Any

EMOJI_DICT = {
    "<|nospeech|><|Event_UNK|>": "❓",
    "<|zh|>": "",
    "<|en|>": "",
    "<|yue|>": "",
    "<|ja|>": "",
    "<|ko|>": "",
    "<|nospeech|>": "",
    "<|HAPPY|>": "😊",
    "<|SAD|>": "😔",
    "<|ANGRY|>": "😡",
    "<|NEUTRAL|>": "",
    "<|BGM|>": "🎼",
    "<|Speech|>": "",
    "<|Applause|>": "👏",
    "<|Laughter|>": "😀",
    "<|FEARFUL|>": "😰",
    "<|DISGUSTED|>": "🤢",
    "<|SURPRISED|>": "😮",
    "<|Cry|>": "😭",
    "<|EMO_UNKNOWN|>": "",
    "<|Sneeze|>": "🤧",
    "<|Breath|>": "",
    "<|Cough|>": "😷",
    "<|Sing|>": "",
    "<|Speech_Noise|>": "",
    "<|withitn|>": "",
    "<|woitn|>": "",
    "<|GBG|>": "",
    "<|Event_UNK|>": "",
}

EMO_DICT = {
    "<|HAPPY|>": "😊",
    "<|SAD|>": "😔",
    "<|ANGRY|>": "😡",
    "<|NEUTRAL|>": "",
    "<|FEARFUL|>": "😰",
    "<|DISGUSTED|>": "🤢",
    "<|SURPRISED|>": "😮",
}

EVENT_DICT = {
    "<|BGM|>": "🎼",
    "<|Speech|>": "",
    "<|Applause|>": "👏",
    "<|Laughter|>": "😀",
    "<|Cry|>": "😭",
    "<|Sneeze|>": "🤧",
    "<|Breath|>": "",
    "<|Cough|>": "🤧",
}

LANG_DICT = {
    "<|zh|>": "zh",
    "<|en|>": "en",
    "<|yue|>": "yue",
    "<|ja|>": "ja",
    "<|ko|>": "ko",
    "<|nospeech|>": "nospeech",
}

TAG_PATTERN = re.compile(r"<\|[^|]+\|>")
EMO_SET = {"😊", "😔", "😡", "😰", "🤢", "😮"}
EVENT_SET = {"🎼", "👏", "😀", "😭", "🤧", "😷"}


def _format_segment(raw: str) -> str:
    counts = {token: raw.count(token) for token in EMOJI_DICT}
    text = raw
    for token in EMOJI_DICT:
        text = text.replace(token, "")

    emotion = "<|NEUTRAL|>"
    for candidate in EMO_DICT:
        if counts.get(candidate, 0) > counts.get(emotion, 0):
            emotion = candidate
    for candidate in EVENT_DICT:
        if counts.get(candidate, 0) > 0:
            text = EVENT_DICT[candidate] + text
    text = text + EMO_DICT[emotion]

    for emoji in EMO_SET.union(EVENT_SET):
        text = text.replace(" " + emoji, emoji)
        text = text.replace(emoji + " ", emoji)
    return text.strip()


def rich_transcription_postprocess(raw: str) -> str:
    text = str(raw or "")
    text = text.replace("<|nospeech|><|Event_UNK|>", "❓")
    for lang_token in LANG_DICT:
        text = text.replace(lang_token, "<|lang|>")
    parts = [_format_segment(part).strip(" ") for part in text.split("<|lang|>")]
    if not parts:
        return ""

    merged = " " + parts[0]
    current_event = _leading_event(merged)
    for part in parts[1:]:
        if not part:
            continue
        if _leading_event(part) == current_event and _leading_event(part) is not None:
            part = part[1:]
        current_event = _leading_event(part)
        if _trailing_emoji(part) is not None and _trailing_emoji(part) == _trailing_emoji(merged):
            merged = merged[:-1]
        merged += part.strip().lstrip()
    return merged.replace("The.", " ").strip()


def _leading_event(text: str) -> str | None:
    return text[0] if text and text[0] in EVENT_SET else None


def _trailing_emoji(text: str) -> str | None:
    return text[-1] if text and text[-1] in EMO_SET.union(EVENT_SET) else None


def extract_language(raw: str) -> str:
    for token, language in LANG_DICT.items():
        if token in raw:
            return language
    return ""


def extract_tags(raw: str) -> list[str]:
    tags: list[str] = []
    for token in TAG_PATTERN.findall(str(raw or "")):
        normalized = token.strip("<|>").strip()
        if normalized in {"withitn", "woitn", "EMO_UNKNOWN"}:
            continue
        if normalized in LANG_DICT.values():
            continue
        if normalized and normalized not in tags:
            tags.append(normalized)
    return tags


def normalize_transcript(raw: str, *, use_itn: bool = True) -> dict[str, Any]:
    raw_text = str(raw or "").strip()
    language = extract_language(raw_text)
    tags = extract_tags(raw_text)
    text = rich_transcription_postprocess(raw_text)
    if not use_itn:
        text = TAG_PATTERN.sub("", raw_text).strip()
    return {
        "raw": raw_text,
        "text": text.strip(),
        "language": language,
        "tags": tags,
    }


def is_meaningful_transcript(payload: dict[str, Any]) -> bool:
    text = str(payload.get("text", "") or "").strip()
    language = str(payload.get("language", "") or "").strip().lower()
    if language == "nospeech":
        return False
    if not text:
        return False
    if text in {"❓"}:
        return False
    return bool(re.search(r"[\w\u4e00-\u9fff]", text))
