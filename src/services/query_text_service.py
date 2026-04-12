import re
import unicodedata


GENERIC_QUERIES = {
    "人",
    "男人",
    "女人",
    "一个人",
    "一个男的",
    "一个女的",
    "有人",
    "人物",
    "车",
    "汽车",
    "一辆车",
    "猫",
    "狗",
    "动物",
    "风景",
    "房子",
    "建筑",
    "画面",
    "镜头",
}

STOP_PHRASES = {
    "我想找",
    "帮我找",
    "给我找",
    "我想搜",
    "帮我搜",
    "给我搜",
    "有没有",
    "视频里",
    "画面里",
}

VISUAL_HINT_PREFIXES = (
    "画面中",
    "镜头里",
    "视频里",
)


def normalize_query_text(text):
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = re.sub(r"[\t\r\n]+", " ", normalized)
    normalized = re.sub(r"[，,。.!！？?、;；:：]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _is_too_short(text):
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if len(compact) <= 1:
        return True
    if len(compact) <= 2 and compact.isascii():
        return True
    return False


def _is_generic(text):
    lowered = text.lower()
    if lowered in GENERIC_QUERIES:
        return True
    if len(text) <= 4 and any(token in text for token in ("人", "车", "猫", "狗", "房", "景")):
        return True
    return False


def _strip_stop_phrases(text):
    cleaned = text
    for phrase in STOP_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or text


def expand_text_queries(text):
    normalized = normalize_query_text(text)
    if not normalized:
        return []

    stripped = _strip_stop_phrases(normalized)
    candidates = [normalized]
    if stripped != normalized:
        candidates.append(stripped)

    if len(stripped) >= 3:
        for prefix in VISUAL_HINT_PREFIXES:
            candidates.append(f"{prefix}{stripped}")

    deduped = []
    seen = set()
    for item in candidates:
        item = normalize_query_text(item)
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:4]


def prepare_text_query(text):
    normalized = normalize_query_text(text)
    result = {
        "original": str(text or ""),
        "normalized": normalized,
        "changed": normalized != str(text or "").strip(),
        "too_short": False,
        "generic": False,
        "expanded_queries": [],
    }
    if _is_too_short(normalized):
        result["too_short"] = True
        return result
    if _is_generic(normalized):
        result["generic"] = True
    result["expanded_queries"] = expand_text_queries(normalized)
    return result
