import unittest

from PySide6.QtCore import Qt

from ui.widgets.library_video_tree import LibraryVideoTableModel, _STATUS_FIX, _STATUS_READY


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

    def test_fix_status_uses_amber_foreground(self):
        model = LibraryVideoTableModel()
        model.set_rows(
            [
                {
                    "video_id": "ok",
                    "video_rel_path": "a.mp4",
                    "status_text": "就绪",
                    "status_tone": "ready",
                },
                {
                    "video_id": "bad",
                    "video_rel_path": "b.mp4",
                    "status_text": "向量/索引缺失",
                    "status_tone": "fix",
                },
            ],
            preserve_checked=False,
        )
        ready_color = model.data(model.index(0, 1), Qt.ItemDataRole.ForegroundRole)
        fix_color = model.data(model.index(1, 1), Qt.ItemDataRole.ForegroundRole)
        self.assertEqual(ready_color, _STATUS_READY)
        self.assertEqual(fix_color, _STATUS_FIX)


if __name__ == "__main__":
    unittest.main()
