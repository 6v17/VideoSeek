import unittest

from src.app.search_results_paging import (
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


if __name__ == "__main__":
    unittest.main()
