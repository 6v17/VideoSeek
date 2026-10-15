"""Search browse layout keeps the query bar and results on the page."""

import unittest

from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

from ui.widgets.components import NavigationSidebar, SearchPage


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

    def test_short_docked_column_keeps_transport_above_detail(self):
        page = SearchPage()
        panel = page.preview_panel
        panel.set_docked(True)
        panel.detail_name.setText("遭到流放的转生重骑士凭借游戏知识大开无双 - 09.mp4")
        panel.detail_body.setText("命中 00:01:12\n相关度 0.86\n类型 对白\n" * 4)
        page.resize(1400, 560)
        page.show()
        self._app.processEvents()
        panel._apply_docked_geometry()
        self._app.processEvents()
        host = panel.preview_host.geometry()
        chrome = panel.expanded_chrome.geometry()
        detail = panel.detail_wrap.geometry()
        self.assertGreaterEqual(chrome.height(), 80)
        self.assertLessEqual(host.y() + host.height(), chrome.y())
        self.assertLessEqual(chrome.y() + chrome.height(), detail.y())
        clear = panel.expanded_chrome.clear_segment_button
        slider = panel.expanded_chrome.slider

        def deepest(widget):
            current = page
            local = widget.mapTo(page, widget.rect().center())
            while True:
                child = current.childAt(local)
                if child is None:
                    return current
                local = child.mapFrom(current, local)
                current = child

        self.assertIs(deepest(clear), clear)
        self.assertIs(deepest(slider), slider)
        page.hide()

    def test_hiding_sidebar_gives_its_width_to_content(self):
        root = QWidget()
        layout = QHBoxLayout(root)
        sidebar = NavigationSidebar()
        content = QWidget()
        layout.addWidget(sidebar)
        layout.addWidget(content, 1)
        root.resize(1600, 700)
        root.show()
        self._app.processEvents()
        before = content.width()
        sidebar.hide()
        self._app.processEvents()
        self.assertGreater(content.width(), before + 200)
        root.hide()

    def test_extra_width_restores_squeezed_preview(self):
        page = SearchPage()
        page.resize(1500, 800)
        page.show()
        self._app.processEvents()
        page._apply_viewport_budget()
        page.compare_splitter.setSizes([1400, 360])
        page.resize(1900, 800)
        self._app.processEvents()
        page.adopt_preview_width()
        self._app.processEvents()
        self.assertGreaterEqual(page.compare_splitter.sizes()[1], 470)
        page.hide()
