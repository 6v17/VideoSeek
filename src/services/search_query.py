"""Query vector construction and hit score filtering."""

from __future__ import annotations

from typing import List

import faiss
import numpy as np

from src.core.clip_embedding import get_clip_embeddings_batch, get_text_embedding
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

    query_vector = query_vector.astype("float32")
    faiss.normalize_L2(query_vector)
    return query_vector


def _coalesce_query_vector(query_data, is_text=False, query_vector=None):
    if query_vector is not None:
        vector = np.asarray(query_vector, dtype=np.float32)
        if vector.ndim == 1:
            vector = vector.reshape(1, -1)
        elif vector.ndim != 2 or vector.shape[0] != 1:
            raise RuntimeError("Invalid query vector. Please retry the search.")
        faiss.normalize_L2(vector)
        return vector
    return build_query_vector(query_data, is_text=is_text)


def filter_hits_by_min_score(hits, min_score) -> List[SearchHit]:
    if min_score is None:
        return list(hits or [])
    try:
        threshold = float(min_score)
    except (TypeError, ValueError):
        return list(hits or [])
    return [hit for hit in (hits or []) if float(getattr(hit, "score", 0.0) or 0.0) >= threshold]
