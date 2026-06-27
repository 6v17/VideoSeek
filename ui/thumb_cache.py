"""In-memory cache for search-result thumbnail pixmaps."""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock


class ThumbPixmapCache:
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
            pixmap = self._entries.get(key)
            if pixmap is not None:
                self._entries.move_to_end(key)
            return pixmap

    def put(self, key, pixmap) -> None:
        if pixmap is None:
            return
        with self._lock:
            self._entries[key] = pixmap
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


_GLOBAL_CACHE = ThumbPixmapCache()


def get_thumb_cache() -> ThumbPixmapCache:
    return _GLOBAL_CACHE
