import unittest

from ui.thumb_cache import ThumbPixmapCache
from ui.views.table_visibility import visible_table_row_range


class ThumbCacheTests(unittest.TestCase):
    def test_cache_evicts_oldest_entry(self):
        cache = ThumbPixmapCache(max_entries=2)
        key_a = cache.make_key("a.mp4", 1.0, 100, 60)
        key_b = cache.make_key("b.mp4", 2.0, 100, 60)
        key_c = cache.make_key("c.mp4", 3.0, 100, 60)
        cache.put(key_a, "pixmap-a")
        cache.put(key_b, "pixmap-b")
        cache.put(key_c, "pixmap-c")
        self.assertIsNone(cache.get(key_a))
        self.assertEqual(cache.get(key_b), "pixmap-b")
        self.assertEqual(cache.get(key_c), "pixmap-c")


class TableVisibilityTests(unittest.TestCase):
    def test_empty_table_returns_empty_range(self):
        from PySide6.QtWidgets import QApplication, QTableWidget

        app = QApplication.instance() or QApplication([])
        table = QTableWidget()
        self.assertEqual(list(visible_table_row_range(table)), [])


if __name__ == "__main__":
    unittest.main()
