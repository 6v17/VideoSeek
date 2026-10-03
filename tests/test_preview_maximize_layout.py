"""Preview maximize must give the vertical split back when it leaves fullscreen."""

import unittest

from PySide6.QtWidgets import QApplication

from ui.widgets.components import SearchPage


class _Splitter:
    def __init__(self, sizes):
        self._sizes = list(sizes)

    def sizes(self):
        return list(self._sizes)

    def setSizes(self, sizes):
        self._sizes = [int(value) for value in sizes]


class _Vis:
    def __init__(self):
        self.visible = True

    def setVisible(self, value):
        self.visible = bool(value)


class _Preview:
    def __init__(self, splitter):
        self.splitter = splitter
        self.maximized = False

    def set_maximized(self, value):
        self.maximized = bool(value)
        if self.maximized:
            # A taller minimum during fullscreen must not become the restored split.
            self.splitter.setSizes([900, 40])


class PreviewMaximizeLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_exit_restores_the_vertical_split_from_before_fullscreen(self):
        page = SearchPage.__new__(SearchPage)
        page._preview_layout_maximized = False
        page._workspace_sizes_before_preview_max = None
        page._workspace_splitter_save_timer = None
        splitter = _Splitter([430, 510])
        page.workspace_splitter = splitter
        page.search_panel = _Vis()
        page.results_slot = _Vis()
        page.preview_panel = _Preview(splitter)
        page.is_results_floating = lambda: False
        page._restore_workspace_splitter_sizes = lambda: splitter.setSizes([1, 1])
        page._lock_workspace_for_results_float = lambda: None

        page.set_preview_maximized(True)
        self.assertEqual(splitter.sizes(), [940, 0])
        self.assertFalse(page.search_panel.visible)

        page.set_preview_maximized(False)
        self.assertEqual(splitter.sizes(), [430, 510])
        self.assertTrue(page.search_panel.visible)
        self.assertTrue(page.results_slot.visible)
        self.assertFalse(page.preview_panel.maximized)
