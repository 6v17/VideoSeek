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

    def test_qimage_put_and_get_do_not_share_the_instance(self):
        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication

        _app = QApplication.instance() or QApplication([])
        cache = ThumbPixmapCache(max_entries=2)
        key = cache.make_key("a.mp4", 1.0, 8, 8)
        image = QImage(8, 8, QImage.Format_RGB888)
        image.fill(1)

        cache.put(key, image)
        got = cache.get(key)

        self.assertIsInstance(got, QImage)
        self.assertIsNot(got, image)
        image.fill(2)
        self.assertNotEqual(got.pixel(0, 0), image.pixel(0, 0))

    def test_search_controller_converts_qimage_on_ui_thread(self):
        from PySide6.QtCore import QObject
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtWidgets import QApplication
        from unittest.mock import MagicMock

        from ui.controllers.search_controller import SearchController

        app = QApplication.instance() or QApplication([])
        _ = app
        parent = QObject()
        parent.search_page = MagicMock()
        parent.search_page.result_view = MagicMock()
        controller = SearchController(parent)
        controller._is_shutdown = False
        image = QImage(8, 8, QImage.Format_RGB888)
        image.fill(0)

        controller._on_thumb_ready(0, image)

        args = parent.search_page.result_view.set_thumbnail.call_args
        self.assertEqual(args.args[0], 0)
        self.assertIsInstance(args.args[1], QPixmap)
        self.assertFalse(args.args[1].isNull())

        controller._on_thumb_ready(1, None)
        self.assertIsNone(parent.search_page.result_view.set_thumbnail.call_args.args[1])


class TableVisibilityTests(unittest.TestCase):
    def test_empty_table_returns_empty_range(self):
        from PySide6.QtWidgets import QApplication, QTableWidget

        _app = QApplication.instance() or QApplication([])
        table = QTableWidget()
        self.assertEqual(list(visible_table_row_range(table)), [])


if __name__ == "__main__":
    unittest.main()
