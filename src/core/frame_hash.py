from __future__ import annotations

import cv2
import numpy as np


def compute_dhash(image_bgr: np.ndarray, hash_size: int = 8) -> int:
    if image_bgr is None or getattr(image_bgr, "size", 0) <= 0:
        return 0
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    diff = resized[:, 1:] > resized[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return int(value)


def dhash_similarity(left: int, right: int, hash_size: int = 8) -> float:
    if left <= 0 or right <= 0:
        return 0.0
    max_bits = hash_size * hash_size
    distance = int(left ^ right).bit_count()
    return max(0.0, 1.0 - (float(distance) / float(max_bits)))
