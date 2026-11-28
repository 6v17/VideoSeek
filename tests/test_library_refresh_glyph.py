"""Refresh glyph and library empty-state visibility."""

from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

from ui.widgets.library_video_tree import LibraryGroupedVideoTree, _paint_library_glyph
from ui.widgets.scaffold import VSProgressStatusRow


def _opaque(image: QImage, x: int, y: int, alpha: int = 80) -> bool:
    if x < 0 or y < 0 or x >= image.width() or y >= image.height():
        return False
    return image.pixelColor(x, y).alpha() >= alpha


class LibraryRefreshGlyphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_refresh_glyph_has_a_gap_and_an_arrowhead(self):
        image = QImage(64, 64, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        _paint_library_glyph(painter, QRect(0, 0, 64, 64), QColor("white"), "refresh")
        painter.end()

        self.assertTrue(_opaque(image, 36, 18), "arrowhead should sit above the ring")
        self.assertFalse(_opaque(image, 32, 32), "the middle of the ring stays open")
        # 3 o'clock is the gap, so this is not a closed circle.
        self.assertFalse(_opaque(image, 44, 32))
        # 12 o'clock is on the arc.
        self.assertTrue(_opaque(image, 32, 20))

    def test_empty_library_hint_shows_before_the_first_refresh(self):
        tree = LibraryGroupedVideoTree()
        tree.set_action_texts(empty_text="还没有视频库。点上方「添加库」。")
        self.assertFalse(tree._empty_label.isHidden())
        self.assertTrue(tree._scroll.isHidden())
        self.assertEqual(tree._empty_label.objectName(), "LibraryEmptyHint")
        self.assertIn("添加库", tree._empty_label.text())
        tree.refresh_from_entries(
            [{"video_id": "v1", "library_path": "D:/lib", "video_path": "D:/lib/a.mp4", "source_exists": True}],
            library_paths=["D:/lib"],
        )
        self.assertTrue(tree._empty_label.isHidden())
        self.assertFalse(tree._scroll.isHidden())
        tree.deleteLater()

    def test_blank_progress_status_hides_the_chip(self):
        row = VSProgressStatusRow()
        self.assertTrue(row.status_label.isHidden())
        row.set_status_text("正在同步")
        self.assertFalse(row.status_label.isHidden())
        row.set_status_text("  ")
        self.assertTrue(row.status_label.isHidden())
        row.deleteLater()


if __name__ == "__main__":
    unittest.main()
