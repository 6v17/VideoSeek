"""In-memory cache for search-result thumbnail images (QImage, not QPixmap)."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock


class ThumbPixmapCache:
    """LRU cache of worker-thread-safe thumbnail images.

    Stores ``QImage`` (or opaque stand-ins in tests). Callers on the GUI thread
    convert to ``QPixmap`` before painting.
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
            return image

    def put(self, key, image) -> None:
        if image is None:
            return
        with self._lock:
            self._entries[key] = image
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


_GLOBAL_CACHE = ThumbPixmapCache()


def get_thumb_cache() -> ThumbPixmapCache:
    return _GLOBAL_CACHE
