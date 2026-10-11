import unittest

from src.storage.config_store import next_result_window
from src.app.search_results_paging import (
    visible_end_index,
    SEARCH_RESULTS_PAGE_SIZE,
    search_results_page_count,
    slice_search_results_page,
)


class SearchResultsPagingTests(unittest.TestCase):
    def test_page_count(self):
        self.assertEqual(search_results_page_count(0), 0)
        self.assertEqual(search_results_page_count(1), 1)
        self.assertEqual(search_results_page_count(20), 1)
        self.assertEqual(search_results_page_count(21), 2)
        self.assertEqual(search_results_page_count(100), 5)

    def test_slice_page(self):
        items = list(range(45))
        self.assertEqual(slice_search_results_page(items, 0), items[:SEARCH_RESULTS_PAGE_SIZE])
        self.assertEqual(slice_search_results_page(items, 1), items[SEARCH_RESULTS_PAGE_SIZE : SEARCH_RESULTS_PAGE_SIZE * 2])
        self.assertEqual(slice_search_results_page(items, 2), items[40:45])
        self.assertEqual(slice_search_results_page(items, 99), [])
        self.assertEqual(search_results_page_count(100, 100), 1)


class VisibleEndIndexTests(unittest.TestCase):
    def test_scroll_at_top_is_the_first_screen_not_the_end(self):
        # A rebuilding scrollbar can report a tiny range while value is still 0.
        self.assertLess(visible_end_index(300, 0, 8, 800, 200, cols=4), 40)
        self.assertEqual(visible_end_index(300, 0, 0, 800, 200, cols=4), 15)

    def test_scrolled_list_reports_the_viewport_end(self):
        index = visible_end_index(300, 4000, 8000, 800, 200, cols=1)
        self.assertGreater(index, 100)
        self.assertLess(index, 299)


class SearchWindowGrowthTests(unittest.TestCase):
    def test_grows_by_100_once_the_user_is_100_short_of_the_cap(self):
        self.assertIsNone(next_result_window(300, 198))
        self.assertEqual(next_result_window(300, 199), 400)
        self.assertEqual(next_result_window(400, 299), 500)
        self.assertIsNone(next_result_window(400, 298))

    def test_threshold_cutoff_stops_growth(self):
        self.assertIsNone(next_result_window(300, 299, exhausted=True))
        self.assertIsNone(next_result_window(0, 10))


class SearchResultsPagerLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_english_previous_label_is_not_clipped(self):
        from ui.widgets.search_results_pager import SearchResultsPager

        pager = SearchResultsPager()
        pager.set_texts(
            {
                "search_results_prev_page": "Previous",
                "search_results_next_page": "Next",
                "search_results_page_info": "{page}/{pages} · {total}",
            }
        )
        needed = pager.btn_prev.fontMetrics().horizontalAdvance("Previous") + 16
        self.assertGreaterEqual(pager.btn_prev.width(), needed)
        self.assertEqual(pager.btn_prev.width(), pager.btn_next.width())

    def test_pager_hides_when_one_page_holds_every_result(self):
        from ui.widgets.search_results_pager import SearchResultsPager

        pager = SearchResultsPager()
        pager.configure(total_count=48, current_page=0, page_size=48)
        self.assertFalse(pager.isVisible())
        pager.configure(total_count=48, current_page=0, page_size=20)
        self.assertTrue(pager.isVisible())


if __name__ == "__main__":
    unittest.main()
