import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from src.app.search_results_paging import SEARCH_RESULTS_PAGE_SIZE


class _FakeWindow(QObject):
    def __init__(self):
        super().__init__()
        self.search_page = MagicMock()
        self.search_page.results_pager = None
        self.search_page.result_view = MagicMock()
        self.texts = {}


class SearchControllerPageSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_results_page_size_uses_fixed_page_constant(self):
        from ui.controllers.search_controller import SearchController

        parent = _FakeWindow()
        controller = SearchController(parent)
        controller._all_results = list(range(300))

        self.assertEqual(controller._results_page_size(), SEARCH_RESULTS_PAGE_SIZE)
        self.assertLess(controller._results_page_size(), len(controller._all_results))

    def test_furthest_global_index_adds_page_offset(self):
        from ui.controllers.search_controller import SearchController

        parent = _FakeWindow()
        controller = SearchController(parent)
        controller._current_page = 2
        with patch.object(controller, "_furthest_visible_index", return_value=5):
            with patch.object(controller, "_results_page_size", return_value=20):
                self.assertEqual(controller._furthest_global_index(), 45)


if __name__ == "__main__":
    unittest.main()
