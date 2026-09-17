"""Shared vision preprocessing helpers for CLIP-family ONNX engines."""

from __future__ import annotations

import cv2
import numpy as np

# Locked per embedding profile (see ``embedding_preprocess`` service).
PREPROCESS_STRETCH = "stretch"
PREPROCESS_CENTER_CROP = "center_crop"
VALID_EMBEDDING_PREPROCESS = frozenset({PREPROCESS_STRETCH, PREPROCESS_CENTER_CROP})

# Legacy issued packs stretched frames to square (scale only).
CLIP_STRETCH_VF = "scale={size}:{size}:flags=bicubic"

# Prefer for new empty profiles: keep aspect, then center-crop to square.
CLIP_SQUARE_VF = (
    "scale={size}:{size}:force_original_aspect_ratio=increase:flags=bicubic,"
    "crop={size}:{size}"
)


def normalize_embedding_preprocess(value) -> str:
    """Return stretch / center_crop, or empty string if unrecognized."""
    raw = str(value or "").strip().lower().replace("-", "_")
    if raw in {PREPROCESS_STRETCH, "legacy_stretch", "scale"}:
        return PREPROCESS_STRETCH
    if raw in {PREPROCESS_CENTER_CROP, "crop", "center_crop_2026_09"}:
        return PREPROCESS_CENTER_CROP
    return ""


def clip_frame_vf(*, fps: float, size: int = 224, preprocess: str = PREPROCESS_CENTER_CROP) -> str:
    """Build the fps + square geometry filter chain for FFmpeg."""
    mode = normalize_embedding_preprocess(preprocess) or PREPROCESS_CENTER_CROP
    size = int(size)
    if mode == PREPROCESS_STRETCH:
        geom = CLIP_STRETCH_VF.format(size=size)
    else:
        geom = CLIP_SQUARE_VF.format(size=size)
    return f"fps={float(fps):.6f},{geom}"


def resize_stretch_rgb(img_rgb: np.ndarray, size: int) -> np.ndarray:
    """Stretch (distort) to size x size — matches legacy FFmpeg scale=W:H."""
    if img_rgb is None or getattr(img_rgb, "size", 0) == 0:
        raise ValueError("image is empty")
    size = int(size)
    if size <= 0:
        raise ValueError("size must be positive")
    h, w = int(img_rgb.shape[0]), int(img_rgb.shape[1])
    if h == size and w == size:
        return img_rgb
    return cv2.resize(img_rgb, (size, size), interpolation=cv2.INTER_CUBIC)


def resize_center_crop_rgb(img_rgb: np.ndarray, size: int) -> np.ndarray:
    """Resize so the short side equals size, then center-crop to size x size."""
    if img_rgb is None or getattr(img_rgb, "size", 0) == 0:
        raise ValueError("image is empty")
    size = int(size)
    if size <= 0:
        raise ValueError("size must be positive")
    h, w = int(img_rgb.shape[0]), int(img_rgb.shape[1])
    if h == size and w == size:
        return img_rgb
    scale = float(size) / float(min(h, w))
    new_w = max(size, int(round(w * scale)))
    new_h = max(size, int(round(h * scale)))
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    resized = cv2.resize(img_rgb, (new_w, new_h), interpolation=interp)
    y0 = max(0, (int(resized.shape[0]) - size) // 2)
    x0 = max(0, (int(resized.shape[1]) - size) // 2)
    cropped = resized[y0 : y0 + size, x0 : x0 + size]
    if cropped.shape[0] != size or cropped.shape[1] != size:
        cropped = cv2.resize(cropped, (size, size), interpolation=cv2.INTER_LINEAR)
    return cropped


def resize_for_clip_rgb(
    img_rgb: np.ndarray,
    size: int,
    preprocess: str = PREPROCESS_CENTER_CROP,
) -> np.ndarray:
    """Apply the profile-locked CLIP geometry to an RGB image."""
    mode = normalize_embedding_preprocess(preprocess) or PREPROCESS_CENTER_CROP
    if mode == PREPROCESS_STRETCH:
        return resize_stretch_rgb(img_rgb, size)
    return resize_center_crop_rgb(img_rgb, size)
