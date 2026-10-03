import os
import sys
import unittest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.widgets.library_video_tree import LibraryGroupedVideoTree


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


if __name__ == "__main__":
    unittest.main()
