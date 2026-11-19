"""Search browse layout keeps the query bar and results on the page."""

import unittest

from PySide6.QtWidgets import QApplication, QHBoxLayout, QSizePolicy, QWidget

from ui.widgets.components import NavigationSidebar, SearchPage


class _Vis:
    def __init__(self):
        self.visible = True

    def setVisible(self, value):
        self.visible = bool(value)

    def hide(self):
        self.visible = False

    def show(self):
        self.visible = True

    def isVisible(self):
        return self.visible


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

    def test_app_fill_hides_shell_chrome_then_restores(self):
        from ui.windows.gui_preview import PreviewGuiMixin

        class _Host(PreviewGuiMixin):
            def __init__(self):
                self._sidebar_hidden = False
                self.sidebar_hidden_calls = []
                self.search_page = type(
                    "P",
                    (),
                    {
                        "search_panel": _Vis(),
                        "preview_detail": _Vis(),
                        "header": _Vis(),
                    },
                )()
                self.runtime_banner = _Vis()
                self.btn_sidebar_restore = _Vis()

            def _set_sidebar_hidden(self, hidden):
                self._sidebar_hidden = bool(hidden)
                self.sidebar_hidden_calls.append(bool(hidden))

        host = _Host()
        host._apply_search_preview_app_fill(True)
        self.assertFalse(host.search_page.search_panel.visible)
        self.assertFalse(host.search_page.header.visible)
        self.assertFalse(host.runtime_banner.visible)
        self.assertFalse(host.btn_sidebar_restore.visible)
        self.assertTrue(host.search_page.preview_detail.visible)
        self.assertEqual(host.sidebar_hidden_calls, [True])
        host._apply_search_preview_app_fill(False)
        self.assertTrue(host.search_page.search_panel.visible)
        self.assertTrue(host.search_page.header.visible)
        self.assertTrue(host.search_page.preview_detail.visible)
        self.assertEqual(host.sidebar_hidden_calls, [True, False])

    def test_layout_transition_hides_video_until_chrome_settles(self):
        from ui.windows.gui_preview import PreviewGuiMixin

        class _Video:
            def __init__(self):
                self.visible = True

            def hide(self):
                self.visible = False

            def show(self):
                self.visible = True

        class _Dialog:
            def __init__(self):
                self.video_host = _Video()
                self.player = None

            def isVisible(self):
                return True

        class _Host(PreviewGuiMixin):
            def __init__(self):
                self.updates = True
                self.rebind_calls = 0
                self.search_page = None
                self.preview_controller = None

            def setUpdatesEnabled(self, enabled):
                self.updates = bool(enabled)

            def _rebind_preview_output(self, dialog):
                self.rebind_calls += 1
                self.rebind_dialog = dialog

        host = _Host()
        dialog = _Dialog()
        host._begin_preview_layout_transition(dialog)
        self.assertTrue(host._preview_layout_frozen)
        self.assertFalse(dialog.video_host.visible)
        self.assertFalse(host.updates)
        PreviewGuiMixin._rebind_preview_output(host, dialog)
        self.assertEqual(host.rebind_calls, 0)
        host._end_preview_layout_transition(dialog)
        self.assertFalse(host._preview_layout_frozen)
        self.assertTrue(dialog.video_host.visible)
        self.assertTrue(host.updates)
        self.assertEqual(host.rebind_calls, 1)

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

    def test_yielded_preview_column_stays_collapsed(self):
        page = SearchPage()
        page.resize(1500, 800)
        page.show()
        self._app.processEvents()
        page.yield_preview_column(True)
        self._app.processEvents()
        page.adopt_preview_width()
        self._app.processEvents()
        self.assertEqual(page.compare_splitter.sizes()[1], 0)
        page.hide()

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

    def test_ready_status_stays_a_chip(self):
        page = SearchPage()
        page.lbl_status.setText("就绪")
        page.resize(1400, 700)
        page.show()
        self._app.processEvents()
        self.assertEqual(
            page.lbl_status.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Maximum,
        )
        self.assertLess(page.lbl_status.width(), 160)
        self.assertGreater(page.results_actions.x(), page.lbl_status.x() + page.lbl_status.width())
        page.hide()
