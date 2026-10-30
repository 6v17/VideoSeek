"""Query vector construction and hit score filtering."""

from __future__ import annotations

from typing import List

import numpy as np

from src.core.clip_embedding import get_clip_embeddings_batch, get_text_embedding
from src.core.vector_norm import normalize_vectors as _normalize_vectors
from src.domain.search_hit import SearchHit


def build_query_vector(query_data, is_text=False):
    if is_text:
        query_vector = get_text_embedding(query_data)
    elif isinstance(query_data, str):
        from src.core.image_io import load_image_bgr

        image = load_image_bgr(query_data)
        if image is None:
            raise RuntimeError(
                "Could not load query image. Use JPG/PNG/WEBP, or install pillow-heif for iPhone HEIC photos."
            )
        query_vector = get_clip_embeddings_batch([image])
    else:
        query_vector = get_clip_embeddings_batch([query_data])

    return _normalize_vectors(query_vector.astype("float32"))


def _coalesce_query_vector(query_data, is_text=False, query_vector=None):
    if query_vector is not None:
        vector = np.asarray(query_vector, dtype=np.float32)
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        elif vector.ndim != 2 or vector.shape[0] != 1:
            raise RuntimeError("Invalid query vector. Please retry the search.")
        return _normalize_vectors(vector)
    return build_query_vector(query_data, is_text=is_text)


# UI hint only. A real match usually pulls its group ahead of the next one;
# a query with no answer keeps the top two almost tied. This is not a cutoff
# and is not calibrated — recheck on a few dozen labeled queries before
# treating the gap as "no result".
VISUAL_FLAT_TOP_GAP = 0.02


def visual_results_lack_standout(hits, *, gap: float = VISUAL_FLAT_TOP_GAP) -> bool:
    """True when the best two hits are too close to call one of them the match.

    Pass group representatives, not raw frames. Adjacent frames of a real hit
    score almost the same and would look like "no answer".
    """
    scores: list[float] = []
    for hit in hits or []:
        try:
            scores.append(float(getattr(hit, "score", 0.0) or 0.0))
        except (TypeError, ValueError):
            continue
    if len(scores) < 2:
        return False
    scores.sort(reverse=True)
    try:
        limit = float(gap)
    except (TypeError, ValueError):
        return False
    return (scores[0] - scores[1]) < limit


def filter_hits_by_min_score(hits, min_score, *, relative: bool = False) -> List[SearchHit]:
    """Drop weak hits.

    ``relative=False`` keeps ``score >= min_score`` (dialogue fuzzy match).
    ``relative=True`` keeps scores within ``min_score`` of this result list's best
    hit. CLIP cosine ranges overlap across queries, so one absolute floor cannot
    mean "relevant". ``0`` does not filter.
    """
    rows = list(hits or [])
    if min_score is None or not rows:
        return rows
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        return rows
    if threshold <= 0:
        return rows

    def _score(hit) -> float:
        return float(getattr(hit, "score", 0.0) or 0.0)

    if not relative:
        return [hit for hit in rows if _score(hit) >= threshold]
    floor = max(_score(hit) for hit in rows) - threshold
    return [hit for hit in rows if _score(hit) >= floor]


# Public names for cross-module callers (engineering.md rule 4).
coalesce_query_vector = _coalesce_query_vector
