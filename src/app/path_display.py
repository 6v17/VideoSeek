"""Human-readable labels for local paths and team play URLs."""

from __future__ import annotations

import os
from urllib.parse import unquote, urlparse


def _unquote_display(text: str) -> str:
    if "%" not in text:
        return text
    try:
        decoded = unquote(text)
    except Exception:
        return text
    return decoded or text


def video_display_name(path: str) -> str:
    """Basename for UI lists. Unquotes team play URL path segments (avoids %xx on Windows)."""
    text = str(path or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        parts = [part for part in urlparse(text).path.split("/") if part]
        if parts:
            name = _unquote_display(parts[-1]).strip()
            if name:
                return name
        return _unquote_display(text)
    # Normalize mixed separators so Windows basename works on POSIX-style paths.
    normalized = text.replace("/", os.sep).replace("\\", os.sep)
    return _unquote_display(os.path.basename(normalized) or text)


def readable_media_location(path: str) -> str:
    """Same location, with percent-encoded characters turned back into text."""
    text = str(path or "").strip()
    if not text:
        return ""
    if not text.lower().startswith(("http://", "https://")):
        return _unquote_display(text)
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(text)
    return urlunsplit((parts.scheme, parts.netloc, unquote(parts.path), parts.query, parts.fragment))
