"""Path fields keep the full value while showing a middle ellipsis."""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ui.widgets.settings.page import ElidedPathEdit


class ElidedPathEditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_narrow_field_elides_but_text_stays_complete(self):
        edit = ElidedPathEdit()
        seen = []
        edit.textChanged.connect(seen.append)
        full = r"C:\Users\LiuWei\AppData\Local\VideoSeek\ffmpeg\bin\ffmpeg.exe"
        edit.setFixedWidth(160)
        edit.setText(full)
        self.assertEqual(edit.text(), full)
        self.assertEqual(edit.toolTip(), full)
        self.assertIn("…", edit.displayText())
        self.assertNotEqual(edit.displayText(), full)
        self.assertEqual(seen, [full])
        edit.deleteLater()


if __name__ == "__main__":
    unittest.main()
