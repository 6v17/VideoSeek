import unittest

from PySide6.QtCore import Qt

from ui.widgets.library_video_tree import LibraryVideoTableModel


class LibraryVideoTableModelTests(unittest.TestCase):
    def test_virtual_model_check_all_without_per_row_widgets(self):
        model = LibraryVideoTableModel()
        rows = [
            {
                "video_id": f"v{i}",
                "video_path": f"/x/{i}.mp4",
                "video_rel_path": f"{i}.mp4",
                "status_text": "ready",
            }
            for i in range(5000)
        ]
        model.set_rows(rows, default_on=False, preserve_checked=False)
        self.assertEqual(model.rowCount(), 5000)
        model.set_all_checked(True)
        n, tot = model.check_stats()
        self.assertEqual(n, 5000)
        self.assertEqual(tot, 5000)
        self.assertEqual(len(model.checked_video_ids()), 5000)
        model.setData(model.index(0, 0), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)
        n, tot = model.check_stats()
        self.assertEqual(n, 4999)


if __name__ == "__main__":
    unittest.main()
