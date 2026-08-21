"""Supported library video container suffixes (ingestion whitelist)."""

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


def is_supported_video_path(path: str | os.PathLike[str]) -> bool:
    name = os.fspath(path).lower()
    return name.endswith(VIDEO_EXTS)


def is_transport_like_video_path(path: str | os.PathLike[str]) -> bool:
    name = os.fspath(path).lower()
    return any(name.endswith(ext) for ext in _TRANSPORT_LIKE_EXTS)
