"""Search browse layout keeps the query bar and results on the page."""

import unittest

from PySide6.QtWidgets import QApplication

from ui.widgets.components import SearchPage


class _Vis:
    def __init__(self):
        self.visible = True

    def setVisible(self, value):
        self.visible = bool(value)


class SearchBrowseLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_preview_maximize_does_not_hide_browse_layout(self):
        page = SearchPage.__new__(SearchPage)
        page._preview_layout_maximized = False
        page.search_panel = _Vis()
        page.results_slot = _Vis()

        page.set_preview_maximized(True)

        self.assertTrue(page.search_panel.visible)
        self.assertTrue(page.results_slot.visible)
        self.assertFalse(page.is_preview_maximized())
