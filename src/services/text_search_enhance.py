"""Text-search enhance: rule phrases + synonym expand + CLIP pick + RRF multi-route."""

from __future__ import annotations

import math
import re
from typing import Callable, List, Mapping, Sequence

import numpy as np

from src.domain.search_hit import SearchHit

MAX_TEXT_SEARCH_ROUTES = 4
MAX_EXTRA_ROUTES = 3
MAX_SYNONYMS_PER_TERM = 2
RRF_K = 60
MIN_PHRASE_CHARS = 1
MIN_LATIN_TOKEN_CHARS = 2
MAX_CJK_NGRAM = 4
DIVERSITY_COSINE_MAX = 0.92
MIN_ROUTE_COSINE = 0.18

_LATIN_STOP = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "into",
        "over",
        "under",
        "about",
        "than",
        "then",
        "so",
        "not",
        "no",
        "yes",
        "very",
        "just",
        "also",
        "can",
        "will",
        "would",
        "could",
        "should",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "who",
        "what",
        "where",
        "when",
        "how",
        "why",
        "which",
    }
)

_CJK_STOP = frozenset("的了吗呢啊吧嘛在是和与或及就都很也又被把给让向对从到着过上下中里外前后")

# Small visual-concept table (CN/EN). Keep tight to limit sense drift.
VISUAL_SYNONYM_MAP: dict[str, tuple[str, ...]] = {
    "狗": ("dog", "小狗"),
    "小狗": ("dog", "狗"),
    "犬": ("dog", "狗"),
    "dog": ("狗", "小狗"),
    "猫": ("cat", "小猫"),
    "小猫": ("cat", "猫"),
    "cat": ("猫", "小猫"),
    "车": ("car", "汽车"),
    "汽车": ("car", "车"),
    "轿车": ("car", "车"),
    "car": ("车", "汽车"),
    "女人": ("woman", "女性"),
    "女性": ("woman", "女人"),
    "女孩": ("girl", "女人"),
    "woman": ("女人", "女性"),
    "girl": ("女孩", "女人"),
    "男人": ("man", "男性"),
    "男性": ("man", "男人"),
    "男孩": ("boy", "男人"),
    "man": ("男人", "男性"),
    "boy": ("男孩", "男人"),
    "小孩": ("child", "儿童"),
    "儿童": ("child", "小孩"),
    "child": ("小孩", "儿童"),
    "警察": ("police", "警官"),
    "police": ("警察", "警官"),
    "医生": ("doctor", "大夫"),
    "doctor": ("医生", "大夫"),
    "学校": ("school", "校园"),
    "school": ("学校", "校园"),
    "办公室": ("office", "办公"),
    "office": ("办公室",),
    "街道": ("street", "马路"),
    "马路": ("street", "街道"),
    "street": ("街道", "马路"),
    "海边": ("beach", "海滩"),
    "海滩": ("beach", "海边"),
    "beach": ("海边", "海滩"),
    "山": ("mountain", "山脉"),
    "mountain": ("山", "山脉"),
    "雨": ("rain", "下雨"),
    "下雨": ("rain", "雨"),
    "rain": ("雨", "下雨"),
    "雪": ("snow", "下雪"),
    "下雪": ("snow", "雪"),
    "snow": ("雪", "下雪"),
    "夜": ("night", "夜晚"),
    "夜晚": ("night", "夜"),
    "night": ("夜", "夜晚"),
    "白天": ("day", "日间"),
    "day": ("白天",),
    "剑": ("sword", "刀剑"),
    "sword": ("剑",),
    "枪": ("gun", "枪支"),
    "gun": ("枪",),
    "飞机": ("plane", "airplane"),
    "plane": ("飞机", "airplane"),
    "airplane": ("飞机", "plane"),
    "船": ("boat", "ship"),
    "boat": ("船",),
    "ship": ("船",),
    "骑车": ("bike", "骑自行车"),
    "bike": ("骑车", "自行车"),
    "跑步": ("run", "奔跑"),
    "run": ("跑步", "奔跑"),
    "哭": ("cry", "哭泣"),
    "cry": ("哭", "哭泣"),
    "笑": ("smile", "微笑"),
    "smile": ("笑", "微笑"),
    "打架": ("fight", "打斗"),
    "fight": ("打架", "打斗"),
    "吃饭": ("eat", "用餐"),
    "eat": ("吃饭", "用餐"),
    "喝酒": ("drink", "饮酒"),
    "drink": ("喝酒", "饮酒"),
    "电话": ("phone", "手机"),
    "手机": ("phone", "电话"),
    "phone": ("电话", "手机"),
    "电脑": ("computer", "laptop"),
    "computer": ("电脑",),
    "laptop": ("电脑", "笔记本"),
}

_SPLIT_RE = re.compile(r"[\s,，。.!！？?；;：:、/\\|+\-_=()（）\[\]【】{}<>《》\"'‘’“”…]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_RE = re.compile(r"[A-Za-z0-9]+")


def normalize_text_search_query(text: str) -> str:
    return " ".join(str(text or "").strip().split())


def extract_text_search_phrases(query: str) -> list[str]:
    """Rule phrases: Latin tokens + CJK segments/n-grams. No jieba."""
    body = normalize_text_search_query(query)
    if not body:
        return []
    out: list[str] = []
    seen: set[str] = set()

    def _add(part: str) -> None:
        token = str(part or "").strip()
        if not token:
            return
        if _CJK_RE.fullmatch(token):
            if len(token) < MIN_PHRASE_CHARS:
                return
        elif len(token) < MIN_LATIN_TOKEN_CHARS:
            return
        key = token.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(token)

    for chunk in _SPLIT_RE.split(body):
        chunk = chunk.strip()
        if not chunk:
            continue
        for latin in _LATIN_RE.findall(chunk):
            if latin.casefold() in _LATIN_STOP:
                continue
            _add(latin)
        for cjk in _CJK_RE.findall(chunk):
            cleaned = "".join(ch for ch in cjk if ch not in _CJK_STOP)
            if cleaned:
                _add(cleaned)
            elif len(cjk) >= MIN_PHRASE_CHARS:
                _add(cjk)
            span = cleaned or cjk
            if len(span) >= 4:
                for n in (2, 3, min(MAX_CJK_NGRAM, len(span))):
                    if n > len(span):
                        continue
                    for index in range(0, len(span) - n + 1):
                        gram = span[index : index + n]
                        if any(ch in _CJK_STOP for ch in gram):
                            continue
                        _add(gram)
    return out


def expand_text_search_synonyms(
    phrases: Sequence[str],
    *,
    synonym_map: Mapping[str, Sequence[str]] | None = None,
    max_per_term: int = MAX_SYNONYMS_PER_TERM,
) -> list[str]:
    table = synonym_map if synonym_map is not None else VISUAL_SYNONYM_MAP
    out: list[str] = []
    seen: set[str] = set()

    def _add(part: str) -> None:
        token = str(part or "").strip()
        if not token:
            return
        if _CJK_RE.fullmatch(token):
            if len(token) < MIN_PHRASE_CHARS:
                return
        elif len(token) < MIN_LATIN_TOKEN_CHARS:
            return
        key = token.casefold()
        if key in seen:
            return
        seen.add(key)
        out.append(token)

    for phrase in phrases:
        _add(phrase)
        key = str(phrase or "").strip()
        alts = table.get(key) or table.get(key.casefold())
        if not alts:
            continue
        for alt in list(alts)[: max(0, int(max_per_term))]:
            _add(alt)
    return out


def _as_unit_vector(raw) -> np.ndarray | None:
    try:
        vec = np.asarray(raw, dtype=np.float32).reshape(-1)
    except (TypeError, ValueError):
        return None
    if vec.size == 0:
        return None
    norm = float(np.linalg.norm(vec))
    if not math.isfinite(norm) or norm <= 1e-8:
        return None
    return vec / norm


def _cosine(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.dot(left, right))


def select_text_search_routes(
    query: str,
    *,
    embed_fn: Callable[[str], object],
    max_extra: int = MAX_EXTRA_ROUTES,
    max_routes: int = MAX_TEXT_SEARCH_ROUTES,
) -> list[str]:
    """Full query first, then diverse CLIP-near phrases (including synonyms)."""
    body = normalize_text_search_query(query)
    if not body:
        return []
    routes = [body]
    phrases = expand_text_search_synonyms(extract_text_search_phrases(body))
    candidates = [p for p in phrases if p.casefold() != body.casefold()]
    if not candidates or max_extra <= 0 or max_routes <= 1:
        return routes[:max_routes]

    query_vec = _as_unit_vector(embed_fn(body))
    if query_vec is None:
        return routes[:max_routes]

    scored: list[tuple[float, str, np.ndarray]] = []
    for phrase in candidates:
        vec = _as_unit_vector(embed_fn(phrase))
        if vec is None or vec.shape != query_vec.shape:
            continue
        sim = _cosine(query_vec, vec)
        if sim < MIN_ROUTE_COSINE:
            continue
        scored.append((sim, phrase, vec))
    scored.sort(key=lambda item: (-item[0], len(item[1]), item[1]))

    picked_vecs = [query_vec]
    for sim, phrase, vec in scored:
        if len(routes) >= max_routes or len(routes) - 1 >= max_extra:
            break
        if any(_cosine(vec, other) >= DIVERSITY_COSINE_MAX for other in picked_vecs):
            continue
        routes.append(phrase)
        picked_vecs.append(vec)
    return routes


def default_text_embed_fn(text: str):
    from src.core.clip_embedding import get_text_embedding

    return get_text_embedding(text)


def search_hit_fusion_key(hit: SearchHit) -> tuple[str, str, float, float]:
    return (
        str(hit.video_id or ""),
        str(hit.video_path or ""),
        round(float(hit.start_sec or 0.0), 3),
        round(float(hit.end_sec or 0.0), 3),
    )


def rrf_fuse_search_hits(
    route_hit_lists: Sequence[Sequence[SearchHit]],
    top_k: int,
    *,
    rrf_k: int = RRF_K,
) -> list[SearchHit]:
    """Reciprocal rank fusion across multi-route ANN lists."""
    keep = max(1, int(top_k or 1))
    k = max(1, int(rrf_k or RRF_K))
    scores: dict[tuple[str, str, float, float], float] = {}
    best: dict[tuple[str, str, float, float], SearchHit] = {}
    for hits in route_hit_lists:
        for rank, hit in enumerate(hits or [], start=1):
            if not isinstance(hit, SearchHit):
                continue
            key = search_hit_fusion_key(hit)
            scores[key] = scores.get(key, 0.0) + 1.0 / float(k + rank)
            prev = best.get(key)
            if prev is None or float(hit.score or 0.0) > float(prev.score or 0.0):
                best[key] = hit
    ordered = sorted(scores.items(), key=lambda item: (-item[1], -float(best[item[0]].score or 0.0)))
    out: list[SearchHit] = []
    for key, fused in ordered[:keep]:
        hit = best[key]
        out.append(
            SearchHit(
                start_sec=hit.start_sec,
                end_sec=hit.end_sec,
                score=round(float(fused), 6),
                video_path=hit.video_path,
                match_kind=hit.match_kind,
                video_id=hit.video_id,
                matched_text=hit.matched_text,
            )
        )
    return out


def should_enhance_text_query(
    *,
    is_text: bool,
    query_data,
    query_vector=None,
    enabled: bool,
) -> bool:
    if not enabled or not is_text or query_vector is not None:
        return False
    if not isinstance(query_data, str):
        return False
    return bool(normalize_text_search_query(query_data))
