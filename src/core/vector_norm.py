"""L2-normalize embedding rows. Numpy only, so Lance search does not import faiss."""

from __future__ import annotations

import numpy as np


def normalize_vectors(vectors):
    vectors = np.asarray(vectors, dtype="float32")
    if vectors.ndim == 1:
        vectors = vectors.reshape(1, -1)
    if vectors.size == 0:
        return vectors
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-10)
