import os
import unittest

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


class ShotListDialogChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_footer_keeps_export_menu_without_preview_locate_buttons(self):
        from src.services.shot_list_service import ShotListItem, ShotListStore
        from ui.dialogs.shot_list_dialog import ShotListDialog

        store = ShotListStore()
        store.replace_items(
            [
                ShotListItem(
                    id="a",
                    video_path="D:/a.mp4",
                    start_sec=1.0,
                    end_sec=2.0,
                    score=0.9,
                    match_kind="clip",
                    source_query="q",
                )
            ]
        )
        dialog = ShotListDialog(store=store, language="zh", is_dark=True)
        self.addCleanup(dialog.deleteLater)

        self.assertTrue(hasattr(dialog, "btn_export"))
        self.assertIsNotNone(dialog.btn_export.menu())
        self.assertFalse(hasattr(dialog, "btn_preview"))
        self.assertFalse(hasattr(dialog, "btn_locate"))
        self.assertFalse(hasattr(dialog, "btn_export_manifest"))
        self.assertEqual(dialog._export_menu.actions()[0].text(), "导出清单")
        self.assertTrue(dialog.btn_export.isEnabled())


if __name__ == "__main__":
    unittest.main()
