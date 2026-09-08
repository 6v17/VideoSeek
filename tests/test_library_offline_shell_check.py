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


if __name__ == "__main__":
    unittest.main()
