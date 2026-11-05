"""NaFlex image prep for FG-CLIP2.

The vision graph consumes flattened 16×16 patches plus a position table that is
resized outside the graph. Frames keep their aspect ratio: the long side is
shrunk until the patch grid has at most 256 patches. Ranking uses cosine on
the L2-normalized ONNX outputs.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

PATCH_SIZE = 16
MAX_PATCHES = 256
POSITION_GRID = 16
TEXT_SEQ_LEN = 64
EMBEDDING_DIM = 768
PATCH_DIM = PATCH_SIZE * PATCH_SIZE * 3


def naflex_pixel_size(image_height: int, image_width: int) -> tuple[int, int]:
    """Return height, width snapped to the patch grid and capped at ``MAX_PATCHES``."""
    return get_image_size_for_max_num_patches(
        int(image_height),
        int(image_width),
        PATCH_SIZE,
        MAX_PATCHES,
    )


def get_image_size_for_max_num_patches(
    image_height: int,
    image_width: int,
    patch_size: int,
    max_num_patches: int,
    eps: float = 1e-5,
) -> tuple[int, int]:
    """Match SigLIP2 / FG-CLIP2: binary-search a scale, then snap to ``patch_size``."""

    def scaled(scale: float, size: int) -> int:
        snapped = math.ceil((size * scale) / patch_size) * patch_size
        return int(max(patch_size, snapped))

    scale_min, scale_max = eps / 10.0, 100.0
    while (scale_max - scale_min) >= eps:
        scale = (scale_min + scale_max) / 2.0
        target_h = scaled(scale, image_height)
        target_w = scaled(scale, image_width)
        num_patches = (target_h / patch_size) * (target_w / patch_size)
        if num_patches <= max_num_patches:
            scale_min = scale
        else:
            scale_max = scale

    return scaled(scale_min, image_height), scaled(scale_min, image_width)


def _resize_weights(n_in: int, n_out: int) -> np.ndarray:
    """Separable bilinear weights with antialias, align_corners=False.

    Matches ``torch.nn.functional.interpolate(..., mode='bilinear', antialias=True)``.
    """
    if n_out == n_in:
        return np.eye(n_in, dtype=np.float32)
    scale = float(n_in) / float(n_out)
    kernel = scale if n_out < n_in else 1.0
    rows = np.zeros((n_out, n_in), dtype=np.float32)
    for index in range(n_out):
        center = (index + 0.5) * scale - 0.5
        left = int(math.floor(center - kernel))
        right = int(math.ceil(center + kernel))
        total = 0.0
        taps: list[tuple[int, float]] = []
        for src in range(left, right + 1):
            if src < 0 or src >= n_in:
                continue
            dist = abs(center - src) / kernel
            if dist >= 1.0:
                continue
            weight = 1.0 - dist
            taps.append((src, weight))
            total += weight
        if total <= 0.0:
            nearest = min(max(int(round(center)), 0), n_in - 1)
            rows[index, nearest] = 1.0
            continue
        scale_tap = 1.0 / total
        for src, weight in taps:
            rows[index, src] = weight * scale_tap
    return rows


def resize_bilinear_aa(image_chw: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """Resize ``(C, H, W)`` float32 with antialiased bilinear interpolation."""
    channels, height, width = image_chw.shape
    out_h = int(out_h)
    out_w = int(out_w)
    if out_h == height and out_w == width:
        return np.ascontiguousarray(image_chw, dtype=np.float32)
    sample = np.ascontiguousarray(image_chw, dtype=np.float32)
    wy = _resize_weights(height, out_h)
    wx = _resize_weights(width, out_w)
    mid = np.matmul(wy, sample)
    return np.matmul(mid, wx.T)


def resize_positional_embeddings(
    table_hwd: np.ndarray,
    spatial_shapes: np.ndarray,
    max_length: int = MAX_PATCHES,
) -> np.ndarray:
    """Resize the ``(grid, grid, dim)`` position table per image and pad to ``max_length``.

    Padding repeats the first resized patch, matching the exported runtime.
    """
    table = np.asarray(table_hwd, dtype=np.float32)
    shapes = np.asarray(spatial_shapes, dtype=np.int64).reshape(-1, 2)
    batch = int(shapes.shape[0])
    dim = int(table.shape[-1])
    grid = table.transpose(2, 0, 1)  # (dim, grid, grid)
    out = np.empty((batch, int(max_length), dim), dtype=np.float32)
    for index in range(batch):
        height = int(shapes[index, 0])
        width = int(shapes[index, 1])
        if height <= 0 or width <= 0:
            raise ValueError(f"invalid spatial shape {(height, width)}")
        if height * width > int(max_length):
            raise ValueError(f"spatial shape {(height, width)} exceeds max_length={max_length}")
        resized = resize_bilinear_aa(grid, height, width)
        flat = resized.reshape(dim, height * width).T
        used = height * width
        out[index, :used] = flat
        if used < int(max_length):
            out[index, used:] = flat[0]
    return out


def patchify_bgr(image_bgr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """BGR uint8 frame -> padded patches, attention mask, and ``(grid_h, grid_w)``."""
    image = np.asarray(image_bgr)
    if image.size == 0 or image.ndim not in (2, 3):
        raise ValueError("image is empty")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        image = image[:, :, :3]
    elif image.shape[2] != 3:
        raise ValueError(f"unsupported channel count {image.shape[2]}")

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    src_h, src_w = int(rgb.shape[0]), int(rgb.shape[1])
    dst_h, dst_w = naflex_pixel_size(src_h, src_w)
    chw = np.transpose(rgb.astype(np.float32, copy=False), (2, 0, 1))
    if src_h != dst_h or src_w != dst_w:
        chw = resize_bilinear_aa(chw, dst_h, dst_w)
    chw *= 2.0 / 255.0
    chw -= 1.0
    chw = np.ascontiguousarray(chw)
    grid_h = dst_h // PATCH_SIZE
    grid_w = dst_w // PATCH_SIZE
    patched = chw.reshape(3, grid_h, PATCH_SIZE, grid_w, PATCH_SIZE)
    patched = patched.transpose(1, 3, 2, 4, 0)
    flat = patched.reshape(grid_h * grid_w, PATCH_DIM)

    pixels = np.zeros((MAX_PATCHES, PATCH_DIM), dtype=np.float32)
    mask = np.zeros((MAX_PATCHES,), dtype=np.int32)
    used = int(flat.shape[0])
    pixels[:used] = flat
    mask[:used] = 1
    spatial = np.asarray([grid_h, grid_w], dtype=np.int64)
    return pixels, mask, spatial
