import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("VIDEOSEEK_TEST_MODE", "1")


class ResourceTableDialogChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            cls._app = QApplication([])

    def test_utility_actions_collapse_into_export_menu(self):
        from ui.dialogs.resource_table import ResourceTableDialog

        dialog = ResourceTableDialog(
            language="zh",
            title="t",
            headers=["#", "Path"],
            rows=[[1, "D:/a.mp4"]],
            row_payloads=[{"path": "D:/a.mp4"}],
            extra_actions=[
                {
                    "label": "清理遗留",
                    "handler": MagicMock(),
                    "context": False,
                }
            ],
        )
        self.addCleanup(dialog.deleteLater)

        self.assertFalse(dialog.btn_utility.isHidden())
        self.assertIsNotNone(dialog.btn_utility.menu())
        self.assertTrue(dialog.btn_copy.isHidden())
        self.assertTrue(dialog.btn_copy_row.isHidden())
        self.assertEqual(len(dialog._footer_extra_buttons), 1)
        self.assertEqual(dialog._footer_extra_buttons[0].text(), "清理遗留")


if __name__ == "__main__":
    unittest.main()
