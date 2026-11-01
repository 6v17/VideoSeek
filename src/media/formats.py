"""Supported video containers and still-image suffixes (ingestion whitelists)."""

from __future__ import annotations

import os

# Keep in sync with product docs / user-facing "supported formats" copy.
# Export destinations stay narrower (mp4/mkv/mov) elsewhere.
VIDEO_EXTS = (
    ".mp4",
    ".m4v",
    ".mkv",
    ".avi",
    ".mov",
    ".flv",
    ".wmv",
    ".webm",
    ".mpg",
    ".mpeg",
    ".ts",
    ".m2ts",
    ".mts",
)

# MPEG transport / program streams often omit container duration; probe harder.
_TRANSPORT_LIKE_EXTS = frozenset({".ts", ".m2ts", ".mts", ".mpg", ".mpeg"})

# MPEG program streams: VLC :start-time often lands tens of seconds early.
_MPEG_PROGRAM_STREAM_EXTS = frozenset({".mpg", ".mpeg"})


def is_supported_video_path(path: str | os.PathLike[str]) -> bool:
    name = os.fspath(path).lower()
    return name.endswith(VIDEO_EXTS)


# Still images for the image gallery. HEIC is decoded by ``load_image_bgr`` when pillow-heif is present.
IMAGE_EXTS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".heic",
    ".heif",
    ".heics",
    ".heifs",
)


def is_supported_image_path(path: str | os.PathLike[str]) -> bool:
    name = os.fspath(path).lower()
    return name.endswith(IMAGE_EXTS)


def is_transport_like_video_path(path: str | os.PathLike[str]) -> bool:
    name = os.fspath(path).lower()
    return any(name.endswith(ext) for ext in _TRANSPORT_LIKE_EXTS)


def needs_seekable_preview_proxy(path: str | os.PathLike[str]) -> bool:
    """True when direct player seek on the source container is unreliable."""
    name = os.fspath(path).lower()
    return any(name.endswith(ext) for ext in _MPEG_PROGRAM_STREAM_EXTS)
