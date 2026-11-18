"""Gallery search state: a cleared search stays clear, and a later window only appends."""

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

    def test_next_window_appends_new_paths_only(self):
        controller, parent = _controller(self)
        board = _ResultBoard()
        parent.search_page.gallery_results = board
        controller._scroll_hooked = True
        controller._search_generation = 3
        controller._window_limit = 300
        controller._window_exhausted = False
        controller._hit_rows = [{"path": "a.jpg", "score": 0.9}]
        controller._search_worker = MagicMock(replacing=False, window_limit=600)

        with patch.object(controller, "_maybe_grow_window"), patch.object(controller, "_schedule_thumbs"):
            controller._on_hits(
                3,
                [
                    {"path": "a.jpg", "score": 0.9},
                    {"path": "b.jpg", "score": 0.4},
                    {"path": "", "score": 0.1},
                ],
            )

        self.assertEqual([row["path"] for row in controller._hit_rows], ["a.jpg", "b.jpg"])
        self.assertEqual(board.populated, [])
        self.assertEqual(board.appended, [(["b.jpg"], 1)])
        self.assertEqual(controller._hit_scores["b.jpg"], 0.4)
        self.assertEqual(controller._window_limit, 600)
        self.assertFalse(controller._window_exhausted)
        parent.search_page.lbl_status.setText.assert_called_with("2")

    def test_short_reply_with_nothing_new_stops_growth(self):
        controller, parent = _controller(self)
        parent.texts["search_window_end_hint"] = "end"
        controller._search_generation = 3
        controller._window_exhausted = False
        controller._hit_rows = [{"path": "a.jpg", "score": 0.9}]
        controller._search_worker = MagicMock(replacing=False, window_limit=600)

        with patch.object(controller, "_maybe_grow_window"), patch.object(controller, "_schedule_thumbs"):
            controller._on_hits(3, [{"path": "a.jpg", "score": 0.9}])

        self.assertEqual([row["path"] for row in controller._hit_rows], ["a.jpg"])
        self.assertTrue(controller._window_exhausted)
        parent.search_page.lbl_status.setText.assert_called_with("1 · end")

    def test_ceiling_reply_shows_the_cap_and_does_not_fetch_again(self):
        controller, parent = _controller(self)
        parent.texts["search_window_cap_hint"] = "cap"
        parent.search_page.gallery_results = None
        controller._search_generation = 2
        controller._window_exhausted = False
        controller._hit_rows = [{"path": "0.jpg", "score": 0.5}]
        controller._search_worker = MagicMock(replacing=False, window_limit=10000, isRunning=lambda: False)
        rows = [{"path": f"{index}.jpg", "score": 0.5} for index in range(10000)]

        with patch.object(controller, "_schedule_thumbs"):
            controller._on_hits(2, rows)

        self.assertEqual(len(controller._hit_rows), 10000)
        self.assertTrue(controller._window_capped)
        self.assertTrue(controller._window_exhausted)
        parent.search_page.lbl_status.setText.assert_called_with("10000 · cap")
        launched = controller._search_worker
        controller._maybe_grow_window()
        self.assertIs(controller._search_worker, launched)

    def test_reaching_the_loaded_rows_fetches_the_next_window(self):
        controller, _parent = _controller(self)
        controller._query_text = "cat"
        controller._window_limit = 300
        controller._window_exhausted = False
        controller._hit_rows = [{"path": f"{index}.jpg", "score": 0.5} for index in range(300)]
        controller._search_worker = MagicMock(isRunning=lambda: False)
        fresh = MagicMock()
        fresh.isRunning.return_value = False

        with patch(
            "ui.controllers.image_gallery_controller.ImageGallerySearchWorker",
            return_value=fresh,
        ) as created:
            with patch.object(controller, "_furthest_visible_index", return_value=10):
                controller._maybe_grow_window()
            created.assert_not_called()
            with patch.object(controller, "_furthest_visible_index", return_value=299):
                controller._maybe_grow_window()

        self.assertEqual(created.call_args.kwargs["top_k"], 600)
        self.assertFalse(fresh.replacing)
        self.assertEqual(fresh.window_limit, 600)
        fresh.start.assert_called_once()
        self.assertEqual(len(controller._hit_rows), 300)

    def test_old_thumbnail_and_failure_leave_the_new_search(self):
        controller, parent = _controller(self)
        parent.show_error_dialog = MagicMock()
        board = _ResultBoard()
        parent.search_page.gallery_results = board
        controller._search_generation = 5
        controller._hit_rows = [{"path": "new.jpg", "score": 0.8}]
        controller._search_worker = MagicMock(replacing=False)

        controller._on_thumb(4, 0, MagicMock())
        controller._on_search_finished(4, False, "boom")

        self.assertEqual(board.thumbs, [])
        self.assertEqual(controller._hit_rows, [{"path": "new.jpg", "score": 0.8}])
        self.assertFalse(controller._prefetch_hold)
        parent.show_error_dialog.assert_not_called()

        controller._on_search_finished(5, False, "boom")

        self.assertTrue(controller._prefetch_hold)
        self.assertEqual(controller._hit_rows, [{"path": "new.jpg", "score": 0.8}])
        parent.show_error_dialog.assert_not_called()


class _ResultBoard:
    def __init__(self):
        self.populated = []
        self.appended = []
        self.thumbs = []

    def set_busy(self, _busy: bool) -> None:
        return None

    def set_empty_message(self, _message: str) -> None:
        return None

    def populate_local(self, packed, *_args) -> None:
        self.populated.append([hit.video_path for hit in packed])

    def append_local(self, packed, *_args, rank_offset: int = 0) -> None:
        self.appended.append(([hit.video_path for hit in packed], rank_offset))

    def set_thumbnail(self, index: int, _image) -> None:
        self.thumbs.append(index)


if __name__ == "__main__":
    unittest.main()
