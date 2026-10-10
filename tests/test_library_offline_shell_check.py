import os
import sys
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.widgets.library_video_tree import LibraryGroupedVideoTree, expanded_library_list_height


class LibraryOfflineShellCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_expanded_empty_offline_shell_stays_checkable_for_remove(self):
        tree = LibraryGroupedVideoTree()
        missing = os.path.normpath("E:/gone-library")
        tree.refresh_from_entries(
            [],
            library_paths=[missing],
            expanded_lib_paths=[missing],
        )
        self.assertEqual(len(tree._blocks), 1)
        block = tree._blocks[0]
        self.assertEqual(block.entries, [])
        self.assertTrue(block.populated)
        self.assertIsNotNone(block.lib_cb)

        block.lib_cb.setCheckState(Qt.CheckState.Checked)

        self.assertEqual(block.lib_cb.checkState(), Qt.CheckState.Checked)
        self.assertTrue(block.default_on)
        self.assertEqual(
            [os.path.normpath(p) for p in tree.collect_checked_library_paths()],
            [missing],
        )

        block.lib_cb.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(block.lib_cb.checkState(), Qt.CheckState.Unchecked)
        self.assertFalse(block.default_on)
        self.assertEqual(tree.collect_checked_library_paths(), [])
        self.assertEqual(block.view.height(), 0)


class LibraryExpandHeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_short_list_uses_its_rows_and_long_list_stops_at_the_viewport(self):
        self.assertEqual(
            expanded_library_list_height(
                content_height=60,
                viewport_height=500,
                header_height=36,
            ),
            60,
        )
        self.assertEqual(
            expanded_library_list_height(
                content_height=3000,
                viewport_height=500,
                header_height=36,
                body_margin=4,
            ),
            460,
        )
        self.assertEqual(
            expanded_library_list_height(
                content_height=90,
                viewport_height=0,
                header_height=36,
            ),
            90,
        )

    def test_two_videos_expand_to_their_rows_not_a_fixed_stub(self):
        tree = LibraryGroupedVideoTree()
        lib = os.path.normpath("D:/videos")
        tree.refresh_from_entries(
            [
                {"library_path": lib, "video_id": "a", "video_rel_path": "a.mp4", "source_exists": True},
                {"library_path": lib, "video_id": "b", "video_rel_path": "b.mp4", "source_exists": True},
            ],
            library_paths=[lib],
            expanded_lib_paths=[lib],
        )
        view = tree._blocks[0].view
        self.assertEqual(view.model().rowCount(), 2)
        self.assertEqual(view.height(), 2 * view.verticalHeader().defaultSectionSize())
        self.assertNotEqual(view.height(), 280)


class LibraryEnglishColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_english_status_and_action_columns_fit_their_labels(self):
        from ui.widgets.library_video_tree import _ClickLabel

        tree = LibraryGroupedVideoTree()
        tree.set_action_texts(
            open_text="Open",
            header_video="Video",
            header_count="Count",
            header_status="Status",
            header_action="Action",
            status_template="{ready}/{total} extracted",
        )
        action_needed = tree._header_action_label.fontMetrics().horizontalAdvance("Action")
        status_needed = tree._header_status_label.fontMetrics().horizontalAdvance("999/999 extracted")
        self.assertGreaterEqual(tree._header_action_label.width(), action_needed)
        self.assertGreaterEqual(tree._header_status_label.width(), status_needed)

        title = _ClickLabel("进击的巨人第3季-很长的库名-不应该把功能列挤出窗口")
        self.assertLessEqual(title.minimumSizeHint().width(), 64)


class SubtitleAdvancedRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_sample_controls_stay_hidden_until_advanced_is_opened(self):
        from ui.widgets.components import LibraryPage

        page = LibraryPage()
        self.assertTrue(page.subtitle_sample_advanced_row.isHidden())
        self.assertFalse(page.btn_subtitle_sample_advanced.isChecked())
        self.assertIs(
            page.subtitle_video_tree.find_bar.parentWidget(),
            page.btn_subtitle_sample_advanced.parentWidget(),
        )

        page.btn_subtitle_sample_advanced.setChecked(True)

        self.assertFalse(page.subtitle_sample_advanced_row.isHidden())
        page.deleteLater()


class LibraryToolbarFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_narrow_toolbar_wraps_instead_of_growing_wider(self):
        from PySide6.QtWidgets import QPushButton, QWidget

        from ui.widgets.flow_layout import FlowLayout

        host = QWidget()
        layout = FlowLayout(host, spacing=8)
        for label in ("Remove selected videos", "Re-extract subtitles"):
            button = QPushButton(label)
            button.setMinimumWidth(180)
            layout.addWidget(button)
        self.assertLess(layout.minimumSize().width(), 300)
        self.assertGreater(layout.heightForWidth(300), layout.heightForWidth(800))


class SearchScopeExpandHeightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication(sys.argv)

    def test_two_videos_expand_to_their_rows_not_a_fixed_stub(self):
        from ui.widgets.video_scope_tree import VideoScopeTreeWidget

        tree = VideoScopeTreeWidget()
        lib = os.path.normpath("D:/videos")
        entries = [
            {
                "library_path": lib,
                "video_rel_path": "a.mp4",
                "source_exists": True,
                "asset_state": "ready",
            },
            {
                "library_path": lib,
                "video_rel_path": "b.mp4",
                "source_exists": True,
                "asset_state": "ready",
            },
        ]
        tree.refresh_from_entries(entries, expanded_lib_paths=[lib])
        view = tree._blocks[0].view
        self.assertEqual(view.model().rowCount(), 2)
        self.assertEqual(view.height(), 2 * view.verticalHeader().defaultSectionSize())
        self.assertNotEqual(view.height(), 280)

        tree.refresh_from_entries(entries, expanded_lib_paths=[])
        collapsed = tree._blocks[0]
        self.assertFalse(collapsed.expanded)
        self.assertEqual(collapsed.view.height(), 0)
        tree._set_block_expanded(collapsed, True)
        self.assertEqual(
            collapsed.view.height(),
            2 * collapsed.view.verticalHeader().defaultSectionSize(),
        )
        tree.deleteLater()


if __name__ == "__main__":
    unittest.main()
