"""Clipboard → local image file helpers for image search paste (Ctrl+V)."""

from __future__ import annotations

import os
import time

from src.infra.paths import get_app_data_dir
from src.services.search_preset_constants import IMAGE_EXTENSIONS


def clipboard_query_cache_dir() -> str:
    path = os.path.join(get_app_data_dir(), "cache", "clipboard_query")
    os.makedirs(path, exist_ok=True)
    return path


def is_image_file_path(path: str) -> bool:
    text = str(path or "").strip()
    if not text or not os.path.isfile(text):
        return False
    return os.path.splitext(text)[1].lower() in IMAGE_EXTENSIONS


def save_qimage_for_query(image, *, suffix: str = ".png") -> str:
    """Persist a Qt QImage to the clipboard-query cache; return absolute path."""
    if image is None or image.isNull():
        return ""
    folder = clipboard_query_cache_dir()
    ext = str(suffix or ".png").strip().lower() or ".png"
    if not ext.startswith("."):
        ext = f".{ext}"
    path = os.path.join(folder, f"paste_{int(time.time() * 1000)}{ext}")
    fmt = "PNG" if ext == ".png" else "JPEG" if ext in {".jpg", ".jpeg"} else "PNG"
    if not image.save(path, fmt):
        return ""
    return path


def resolve_clipboard_image_path(clipboard) -> str:
    """
    Return a local image path from the clipboard, or "".

    Prefers raster clipboard images (screenshots / WeChat copy), then local file URLs.
    """
    if clipboard is None:
        return ""
    mime = clipboard.mimeData()
    if mime is None:
        return ""

    if mime.hasImage():
        image = clipboard.image()
        if image is None or image.isNull():
            pixmap = clipboard.pixmap()
            if pixmap is not None and not pixmap.isNull():
                image = pixmap.toImage()
        path = save_qimage_for_query(image)
        if path:
            return path

    if mime.hasUrls():
        for url in mime.urls() or []:
            local = str(url.toLocalFile() or "").strip()
            if is_image_file_path(local):
                return local
    return ""
