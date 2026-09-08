"""Human-readable labels for local paths and team play URLs."""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse


def video_display_name(path: str) -> str:
    """Basename for UI lists. Unquotes team play URL path segments (avoids %xx on Windows)."""
    text = str(path or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        parts = [part for part in urlparse(text).path.split("/") if part]
        if parts:
            name = unquote(parts[-1]).strip()
            if name:
                return name
        return text
    # Normalize mixed separators so Windows basename works on POSIX-style paths.
    normalized = text.replace("/", os.sep).replace("\\", os.sep)
    return os.path.basename(normalized) or text
