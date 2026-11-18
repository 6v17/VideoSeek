"""Gallery search state must ignore a worker that finishes after the user clears it."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")

from PySide6.QtCore import QCoreApplication, QObject

from ui.controllers.image_gallery_controller import ImageGalleryController


def _controller(test):
    parent = QObject()
    parent.texts = {
        "gallery_empty_query": "empty-query",
        "gallery_searching": "searching",
        "gallery_sync_busy": "sync-busy",
        "gallery_no_results": "none",
        "gallery_results_count": "{count}",
    }
    parent.gallery_page = MagicMock()
    parent.search_page = MagicMock()
    parent.search_page.gallery_results = MagicMock()
    parent.search_page.gallery_board = MagicMock()
    controller = ImageGalleryController(parent)
    test._controller = controller
    return controller, parent


class ImageGallerySearchLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QCoreApplication.instance() or QCoreApplication([])

    def tearDown(self):
        controller = getattr(self, "_controller", None)
        if controller is not None:
            controller._thumb_timer.stop()
            controller._stop_thumb_worker()

    def _arm_running_search(self, controller):
        search = MagicMock()
        search.isRunning.return_value = True
        thumb = MagicMock()
        thumb.isRunning.return_value = True
        controller._search_worker = search
        controller._thumb_worker = thumb
        controller._search_generation = 4
        controller._hit_rows = [{"path": "old.jpg", "score": 0.9}]
        controller._hit_scores = {"old.jpg": 0.9}
        controller._thumb_loaded = {0}
        controller._thumb_timer.start()
        return search, thumb

    def test_clear_results_drops_a_late_worker(self):
        controller, parent = _controller(self)
        search, thumb = self._arm_running_search(controller)

        controller.clear_results()

        self.assertEqual(controller._search_generation, 5)
        search.stop.assert_called_once()
        thumb.stop.assert_called_once()
        self.assertIsNone(controller._thumb_worker)
        self.assertFalse(controller._thumb_timer.isActive())
        self.assertEqual(controller._hit_rows, [])
        parent.search_page.gallery_results.clear.assert_called_once()

        controller._on_hits(4, [{"path": "old.jpg", "score": 0.9}])

        self.assertEqual(controller._hit_rows, [])
        parent.search_page.gallery_results.populate_local.assert_not_called()

    def test_empty_query_drops_a_late_worker(self):
        controller, parent = _controller(self)
        search, _thumb = self._arm_running_search(controller)

        controller.start_composed_search("  ", [], None, 0.2)

        self.assertEqual(controller._search_generation, 5)
        search.stop.assert_called_once()
        self.assertEqual(controller._hit_rows, [])
        parent.search_page.lbl_status.setText.assert_called_with("empty-query")

        controller._on_hits(4, [{"path": "old.jpg", "score": 0.9}])

        self.assertEqual(controller._hit_rows, [])
        parent.search_page.gallery_results.populate_local.assert_not_called()

    def test_new_search_invalidates_the_previous_generation(self):
        controller, parent = _controller(self)
        search, thumb = self._arm_running_search(controller)
        fresh = MagicMock()
        fresh.isRunning.return_value = False

        with patch(
            "ui.controllers.image_gallery_controller.ImageGallerySearchWorker",
            return_value=fresh,
        ):
            controller._query_text = "cat"
            controller._query_paths = []
            controller._launch_search(300, replacing=True)

        self.assertEqual(controller._search_generation, 5)
        search.stop.assert_called_once()
        thumb.stop.assert_called_once()
        self.assertFalse(controller._thumb_timer.isActive())
        fresh.start.assert_called_once()
        self.assertIs(controller._search_worker, fresh)
        parent.search_page.gallery_results = None

        controller._on_hits(4, [{"path": "old.jpg", "score": 0.9}])

        self.assertEqual(controller._hit_rows, [{"path": "old.jpg", "score": 0.9}])
        controller._on_hits(5, [{"path": "new.jpg", "score": 0.8}])
        self.assertEqual([row["path"] for row in controller._hit_rows], ["new.jpg"])


if __name__ == "__main__":
    unittest.main()
