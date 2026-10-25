"""ResultGrid viewport card pool: off-screen hits stay data-only."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from src.domain.search_hit import SearchHit
from ui.widgets.result_grid import ResultGrid, ResultGridCard


def _texts():
    return {
        "thumb_loading": "...",
        "preview": "Preview",
        "preview_tip": "",
        "locate": "Locate",
        "locate_tip": "",
        "export_clip": "Export",
        "export_clip_tip": "",
        "shot_list_add": "Add",
        "shot_list_add_tip": "",
        "deep_locate": "Find shot",
        "deep_locate_tip": "",
        "result_mode_frame": "Frame",
        "time_preview_label": "Preview ~{time}",
    }


def _hits(n: int = 50):
    return [
        SearchHit(float(i), float(i) + 1.0, 0.9 - i * 0.001, rf"D:\videos\clip_{i}.mp4", match_kind="frame")
        for i in range(n)
    ]


def _noop(*_a, **_k):
    return None


class ResultGridVirtualizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _show_grid(self, n: int = 200, width: int = 900, height: int = 420) -> ResultGrid:
        grid = ResultGrid()
        grid.resize(width, height)
        grid.show()
        self.app.processEvents()
        grid.populate(_hits(n), _noop, _noop, _noop, _texts())
        self.app.processEvents()
        grid._reflow(force=True)
        self.app.processEvents()
        return grid

    def test_populate_many_creates_pool_not_n_cards(self):
        grid = self._show_grid(200)
        self.assertEqual(grid.count(), 200)
        live = [c for c in grid._cards if c.isVisible()]
        self.assertGreater(len(live), 0)
        self.assertLess(len(grid._cards), 200)
        self.assertLessEqual(len(live), 40)
        # Every live card is a ResultGridCard bound to a logical index.
        for card in live:
            self.assertIsInstance(card, ResultGridCard)
            self.assertIsInstance(card._logical_index, int)
        grid.hide()

    def test_grid_defers_action_buttons_until_hover(self):
        grid = self._show_grid(30, height=500)
        self.app.processEvents()
        bound = [c for c in grid._cards if c.isVisible() and c._logical_index is not None]
        self.assertGreater(len(bound), 0)
        card = bound[0]
        self.assertFalse(card._actions_ready)
        self.assertEqual(card._overlay_buttons, [])
        card._show_overlay_now()
        self.assertTrue(card._actions_ready)
        self.assertGreater(len(card._overlay_buttons), 0)
        grid.hide()

    def test_scroll_rebinds_different_logical_indices(self):
        grid = self._show_grid(120, height=360)
        before = {
            id(c): c._logical_index
            for c in grid._cards
            if c.isVisible() and c._logical_index is not None
        }
        self.assertGreater(len(before), 0)
        bar = grid.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        bar.setValue(bar.maximum())
        self.app.processEvents()
        grid._sync_visible(force_rebind=True)
        self.app.processEvents()
        after = {
            c._logical_index
            for c in grid._cards
            if c.isVisible() and c._logical_index is not None
        }
        self.assertGreater(len(after), 0)
        # Bottom of a tall list should bind high indices.
        self.assertGreater(max(after), max(before.values()))
        grid.hide()

    def test_set_thumbnail_offscreen_then_onscreen(self):
        grid = self._show_grid(80, height=320)
        pix = QPixmap(40, 24)
        pix.fill(Qt.GlobalColor.green)
        # Last hit is off-screen after populate at top.
        last = grid.count() - 1
        self.assertIsNone(grid.card_at(last))
        grid.set_thumbnail(last, pix)
        self.assertIsNotNone(grid._items[last]["pixmap"])
        # Scroll to bottom; recycled card should paint cached pixmap.
        bar = grid.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.app.processEvents()
        grid._sync_visible(force_rebind=True)
        self.app.processEvents()
        card = grid.card_at(last)
        self.assertIsNotNone(card)
        self.assertIsNotNone(card._source_pixmap)
        self.assertFalse(card._source_pixmap.isNull())
        grid.hide()

    def test_append_preserves_scroll(self):
        grid = self._show_grid(60, height=360)
        bar = grid.verticalScrollBar()
        bar.setValue(min(200, bar.maximum()))
        self.app.processEvents()
        pos = int(bar.value())
        grid.append(_hits(40), _noop, _noop, _noop, _texts(), rank_offset=60)
        self.app.processEvents()
        grid._restore_scroll(pos)
        self.app.processEvents()
        self.assertEqual(grid.count(), 100)
        self.assertEqual(int(bar.value()), pos)
        grid.hide()

    def test_select_match_across_recycle(self):
        grid = self._show_grid(50, height=360)
        target = r"D:\videos\clip_40.mp4"
        self.assertTrue(grid.select_match(target, 40.0))
        self.assertEqual(grid._selected_index, 40)
        card = grid.card_at(40)
        self.assertIsNotNone(card)
        self.assertTrue(bool(card.property("selected")))
        # Another card must not stay selected.
        for other in grid._cards:
            if other is card or not other.isVisible():
                continue
            self.assertFalse(bool(other.property("selected")))
        grid.hide()

    def test_overlay_compact_after_show_overlay_now(self):
        """Chrome scale pattern: call _show_overlay_now before compact asserts."""
        grid = self._show_grid(8, width=1200, height=700)
        grid.set_display_scale(160)
        self.app.processEvents()
        card = next(c for c in grid._cards if c.isVisible())
        card._show_overlay_now()
        card.apply_slot(168, 96)
        self.assertTrue(bool(card._overlay_buttons[0].property("compact")))
        card.apply_slot(280, 160)
        self.assertFalse(bool(card._overlay_buttons[0].property("compact")))
        grid.hide()


if __name__ == "__main__":
    unittest.main()
