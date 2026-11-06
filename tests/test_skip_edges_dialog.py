"""Skip-range dialog is a start and end clock on every video."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QApplication

from src.services.search_edge_filter import resolve_skip_edges_chrome
from ui.dialogs.skip_edges import SkipEdgesDialog


class SkipEdgesDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_clocks_round_trip_absolute_ranges(self):
        dialog = SkipEdgesDialog(language="zh", ranges_text="0-90; 10:00-12:00")
        self.assertEqual(len(dialog._rows), 2)
        first, second = dialog._rows
        self.assertEqual(first.start_edit.time(), QTime(0, 0, 0))
        self.assertEqual(first.end_edit.time(), QTime(0, 1, 30))
        self.assertEqual(second.start_edit.time(), QTime(0, 10, 0))
        self.assertEqual(second.end_edit.time(), QTime(0, 12, 0))

        first.end_edit.setTime(QTime(0, 2, 0))
        dialog._apply()
        self.assertEqual(dialog.ranges_text(), "0-2:00; 10:00-12:00")

    def test_all_zero_clears_the_filter(self):
        dialog = SkipEdgesDialog(language="zh", ranges_text="0-90")
        dialog._rows[0].end_edit.setTime(QTime(0, 0, 0))
        dialog._apply()
        self.assertEqual(dialog.ranges_text(), "")

    def test_end_before_start_is_rejected(self):
        dialog = SkipEdgesDialog(language="zh", ranges_text="")
        row = dialog._rows[0]
        row.start_edit.setTime(QTime(0, 12, 0))
        row.end_edit.setTime(QTime(0, 10, 0))
        with self.assertRaises(ValueError):
            row.range_text()

    def test_button_summary_is_the_time_range(self):
        chrome = resolve_skip_edges_chrome(
            team_mode="off",
            ranges_text="0-90",
            texts={"search_skip_edges_off": "不过滤"},
        )
        self.assertEqual(chrome["summary"], "0:00–1:30")
        self.assertEqual(chrome["tooltip"], "0:00–1:30")
