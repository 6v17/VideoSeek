"""Search card, preview card, and result size can be folded or resized."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from src.domain.search_hit import SearchHit
from ui.widgets.components import SearchPage
from ui.widgets.result_grid import grid_column_plan, grid_metrics
from ui.widgets.result_view import VIEW_TABLE, ResultView, table_display_metrics


def _hits():
    return [
        SearchHit(1.0, 2.0, 0.9, rf"D:\videos\clip_{index}.mp4", match_kind="frame")
        for index in range(4)
    ]


def _texts():
    return {
        "result_headers": ["#", "Preview", "Video", "Range", "Mode", "Score", "Actions"],
        "thumb_loading": "...",
        "preview": "Preview",
        "preview_tip": "",
        "locate": "Locate",
        "locate_tip": "",
        "export_clip": "Export",
        "export_clip_tip": "",
        "result_mode_frame": "Frame",
        "result_mode_chunk": "Chunk",
    }


class SearchWorkspaceChromeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_search_and_preview_cards_collapse_like_the_sidebar(self):
        page = SearchPage()
        page.resize(1400, 800)
        page.show()
        self.app.processEvents()

        self.assertTrue(page.search_panel.isVisible())
        self.assertTrue(page.search_panel.search_body.isVisible())
        self.assertEqual(page.search_panel.btn_collapse.objectName(), "SidebarIconButton")
        self.assertEqual(page.preview_panel.btn_collapse.objectName(), "SidebarIconButton")
        self.assertTrue(page.preview_panel.isVisible())
        self.assertFalse(page.btn_preview_restore.isVisible())

        button = page.search_panel.btn_collapse
        before = button.mapTo(page, QPoint(button.width(), 0))
        page.set_search_collapsed(True, emit=False)
        self.app.processEvents()
        after = button.mapTo(page, QPoint(button.width(), 0))
        self.assertTrue(page.search_collapsed)
        self.assertTrue(page.search_panel.isVisible())
        self.assertFalse(page.search_panel.search_body.isVisible())
        self.assertTrue(button.isVisible())
        self.assertEqual(button.text(), "«")
        self.assertAlmostEqual(before.x(), after.x(), delta=4)

        page.set_search_collapsed(False, emit=False)
        self.app.processEvents()
        self.assertTrue(page.search_panel.search_body.isVisible())
        self.assertEqual(button.text(), "»")

        page.set_preview_collapsed(True, emit=False)
        self.app.processEvents()
        self.assertTrue(page.preview_collapsed)
        self.assertFalse(page.preview_panel.isVisible())
        self.assertTrue(page.btn_preview_restore.isVisible())
        self.assertLessEqual(page.preview_column.maximumWidth(), 36)
        self.assertLessEqual(page.compare_splitter.sizes()[1], 48)

        page.set_preview_collapsed(False, emit=False)
        self.app.processEvents()
        self.assertTrue(page.preview_panel.isVisible())
        self.assertFalse(page.btn_preview_restore.isVisible())
        self.assertGreaterEqual(page.preview_column.maximumWidth(), 320)
        page.hide()

    def test_result_size_scales_grid_cards_and_table_rows(self):
        default_pref, _default_min, _default_thumb = grid_metrics(100)
        wide_pref, _wide_min, _wide_thumb = grid_metrics(160)
        self.assertEqual(default_pref, 240)
        self.assertGreater(wide_pref, default_pref)

        _cols, card_w, _thumb = grid_column_plan(1200, 160)
        self.assertGreaterEqual(card_w, 360)

        row_h, preview_w = table_display_metrics(160)
        self.assertGreater(row_h, 128)
        self.assertGreater(preview_w, 220)

        view = ResultView(view_mode=VIEW_TABLE)

        def _noop(*_args, **_kwargs):
            return None

        view.populate_local(_hits(), _noop, _noop, _noop, _texts())
        view.set_display_scale(160)
        self.assertEqual(view.table.rowHeight(0), row_h)
        self.assertEqual(view.display_scale_percent, 160)

        view.set_view_mode("grid", emit=False)
        view.populate_local(_hits(), _noop, _noop, _noop, _texts())
        view.grid.resize(1200, 700)
        view.grid.show()
        self.app.processEvents()
        view.set_display_scale(160)
        self.app.processEvents()
        self.assertGreaterEqual(view.grid._cards[0].width(), 300)
        view.grid.hide()
        card = view.grid._cards[0]
        card.apply_slot(168, 96)
        self.assertTrue(bool(card._overlay_buttons[0].property("compact")))
        _row, col, _row_span, _col_span = card._actions_layout.getItemPosition(1)
        self.assertEqual(col, 1)
        self.assertLessEqual(card._overlay_buttons[0].width(), 84)
        card.apply_slot(280, 160)
        self.assertFalse(bool(card._overlay_buttons[0].property("compact")))
        _row, col, _row_span, _col_span = card._actions_layout.getItemPosition(1)
        self.assertEqual(col, 1)


if __name__ == "__main__":
    unittest.main()
