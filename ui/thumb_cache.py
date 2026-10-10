"""In-memory cache for search-result thumbnail images (QImage, not QPixmap)."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock


def _detached_qimage(image):
    """Return a QImage the caller can use without sharing implicit data.

    Non-image stand-ins used by tests are returned unchanged.
    """
    try:
        from PySide6.QtGui import QImage
    except Exception:
        return image
    if not isinstance(image, QImage):
        return image
    detached = image.copy()
    if detached.isNull():
        return image
    return detached


class ThumbPixmapCache:
    """LRU cache of worker-thread-safe thumbnail images.

    Stores a detached ``QImage`` (or opaque stand-ins in tests). ``get`` returns
    another detach so the GUI thread and a loader never share one QImage.
    Callers on the GUI thread convert to ``QPixmap`` before painting.
    """

    def __init__(self, max_entries: int = 256):
        self._max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[tuple, object] = OrderedDict()
        self._lock = Lock()

    @staticmethod
    def make_key(video_path: str, thumb_time: float, width: int, height: int) -> tuple:
        return (
            str(video_path or "").strip(),
            round(float(thumb_time), 2),
            int(width),
            int(height),
        )

    def get(self, key):
        with self._lock:
            image = self._entries.get(key)
            if image is not None:
                self._entries.move_to_end(key)
        if image is None:
            return None
        return _detached_qimage(image)

    def put(self, key, image) -> None:
        if image is None:
            return
        stored = _detached_qimage(image)
        with self._lock:
            self._entries[key] = stored
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


_GLOBAL_CACHE = ThumbPixmapCache()


def get_thumb_cache() -> ThumbPixmapCache:
    return _GLOBAL_CACHE
