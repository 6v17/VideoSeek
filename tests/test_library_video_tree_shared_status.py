"""Team-client shared libraries must not show local 'path missing' status."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.widgets.library_video_tree import LibraryGroupedVideoTree


class LibraryVideoTreeSharedStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_remote_shared_skips_local_path_missing(self):
        tree = LibraryGroupedVideoTree()
        tree.set_action_texts(
            offline_status_text="Path missing (check then Remove)",
            status_template="{ready}/{total} synced",
            shared_status_template="共享库 · {ready}/{total}",
        )
        missing_root = r"Z:\server-only\library-that-does-not-exist-here"
        self.assertFalse(os.path.isdir(missing_root))
        tree.refresh_from_entries(
            [
                {
                    "library_path": missing_root,
                    "video_path": os.path.join(missing_root, "a.mp4"),
                    "video_id": "vid-a",
                    "asset_state": "ready",
                    "status_tone": "ready",
                }
            ],
            library_paths=[missing_root],
        )
        self.app.processEvents()
        block = tree._blocks[0]
        self.assertEqual(block.status_label.toolTip(), "Path missing (check then Remove)")
        self.assertEqual(block.status_label.property("libSync"), "offline")

        tree.set_libraries_remote(True)
        self.app.processEvents()
        self.assertEqual(block.status_label.toolTip(), "共享库 · 1/1")
        self.assertEqual(block.status_label.property("libSync"), "shared")

    def test_team_shared_entry_flag_alone_is_enough(self):
        tree = LibraryGroupedVideoTree()
        tree.set_action_texts(
            offline_status_text="Path missing",
            shared_status_template="Shared · {ready}/{total}",
        )
        missing_root = r"Z:\server-only\another-missing-lib"
        tree.refresh_from_entries(
            [
                {
                    "library_path": missing_root,
                    "video_path": os.path.join(missing_root, "b.mp4"),
                    "video_id": "vid-b",
                    "asset_state": "ready",
                    "status_tone": "ready",
                    "team_shared": True,
                }
            ],
            library_paths=[missing_root],
        )
        self.app.processEvents()
        block = tree._blocks[0]
        self.assertEqual(block.status_label.toolTip(), "Shared · 1/1")
        self.assertEqual(block.status_label.property("libSync"), "shared")


if __name__ == "__main__":
    unittest.main()
