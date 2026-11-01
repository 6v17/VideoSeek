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

        page.compare_splitter.setSizes([900, 470])
        self.app.processEvents()
        page.yield_preview_column(True)
        self.app.processEvents()
        self.assertFalse(page.preview_panel.isVisible())
        self.assertLessEqual(page.compare_splitter.sizes()[1], 16)
        self.assertEqual(page.preview_detail.minimumWidth(), 280)
        self.assertEqual(page.preview_detail.maximumWidth(), 280)
        page.yield_preview_column(False)
        self.app.processEvents()
        self.assertTrue(page.preview_panel.isVisible())
        self.assertGreaterEqual(page.compare_splitter.sizes()[1], 320)
        page.hide()

    def test_gallery_tab_swaps_the_player_for_the_still_board(self):
        from PySide6.QtGui import QImage

        page = SearchPage()
        page.resize(1400, 800)
        page.show()
        self.app.processEvents()
        self.assertTrue(page.preview_panel.isVisible())
        self.assertFalse(page.gallery_board.isVisible())

        page.set_gallery_results_active(True)
        self.app.processEvents()
        self.assertFalse(page.preview_panel.isVisible())
        self.assertTrue(page.gallery_board.isVisible())
        self.assertFalse(page.result_view.isVisible())
        self.assertTrue(page.gallery_results.isVisible())
        self.assertTrue(page.results_size_cluster.isVisible())
        self.assertFalse(hasattr(page, "btn_open_gallery"))
        self.assertFalse(page.gallery_board.btn_copy.isEnabled())
        empty_ratio = page.gallery_board.well.height() / max(1, page.gallery_board.well.width())
        self.assertGreater(page.gallery_board.well.height(), 160)
        self.assertAlmostEqual(empty_ratio, 9 / 16, delta=0.08)
        self.assertGreater(page.gallery_board.height(), page.gallery_board.well.height() + 40)
        page.set_results_display_scale(140, emit=False, snap=True)
        self.assertEqual(page.gallery_results.display_scale_percent, 140)
        self.assertEqual(page.result_view.display_scale_percent, 140)
        from src.domain.search_hit import SearchHit

        page.gallery_results.populate_local(
            [SearchHit(0.0, 0.0, 0.82, r"D:\photos\nest\still.jpg", match_kind="image")],
            lambda *_args: None,
            lambda *_args: None,
            None,
            {"thumb_loading": "…"},
        )
        self.app.processEvents()
        card = page.gallery_results.grid._bound.get(0)
        self.assertIsNotNone(card)
        self.assertEqual(card.title_label.text(), "still.jpg")
        self.assertEqual(card._meta_full, "82%")
        self.assertNotIn("00:", card._meta_full)
        located = []
        opened = []
        card._on_locate = lambda path: located.append(path)
        card._on_export = lambda path, _start, _end: opened.append(path)
        card._rebuild_action_buttons(
            {"preview": "预览", "locate": "定位", "gallery_open": "打开原图", "locate_tip": "在资源管理器中定位文件"}
        )
        labels = [button.text() for button in card._overlay_buttons]
        self.assertEqual(labels, ["预览", "定位", "打开原图"])
        card._overlay_buttons[1].click()
        card._overlay_buttons[2].click()
        self.assertEqual(located, [r"D:\photos\nest\still.jpg"])
        self.assertEqual(opened, [r"D:\photos\nest\still.jpg"])

        image = QImage(12, 8, QImage.Format.Format_RGB32)
        image.fill(0)
        page.gallery_board.show_still(
            image,
            r"D:\photos\nest\still.jpg",
            0.842,
            {
                "gallery_board_title": "展板",
                "gallery_info_location": "位置",
                "gallery_info_dimensions": "尺寸",
                "gallery_info_bytes": "大小",
                "gallery_info_modified": "修改时间",
                "gallery_info_score": "相似度",
                "gallery_file_missing": "missing",
                "gallery_preview_empty": "empty",
                "details_copy_selected": "复制路径",
                "copied": "已复制",
            },
        )
        self.app.processEvents()
        board = page.gallery_board
        self.assertEqual(board.name_label.text(), "still.jpg")
        self.assertIn("still.jpg", board._rows["location"][1].text())
        self.assertEqual(board._rows["score"][1].text(), "0.842")
        self.assertTrue(board.info_wrap.isVisible())
        self.assertFalse(board.image_label.pixmap().isNull())
        self.assertLess(board.well.geometry().bottom(), board.info_wrap.geometry().top())
        shown_ratio = board.well.height() / max(1, board.well.width())
        self.assertAlmostEqual(shown_ratio, 9 / 16, delta=0.08)
        self.assertGreater(board.height(), board.well.height() + board.info_wrap.height())
        self.assertTrue(board.btn_copy.isEnabled())
        board.btn_copy.click()
        self.assertEqual(QApplication.clipboard().text(), r"D:\photos\nest\still.jpg")
        self.assertEqual(board.btn_copy.text(), "已复制")

        page.set_preview_collapsed(True, emit=False)
        self.app.processEvents()
        self.assertFalse(page.gallery_board.isVisible())
        self.assertFalse(page.preview_panel.isVisible())
        page.set_preview_collapsed(False, emit=False)
        self.app.processEvents()
        self.assertTrue(page.gallery_board.isVisible())
        self.assertFalse(page.preview_panel.isVisible())

        page.set_gallery_results_active(False)
        self.app.processEvents()
        self.assertTrue(page.preview_panel.isVisible())
        self.assertFalse(page.gallery_board.isVisible())
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
        card = view.grid.card_at(0) or next(c for c in view.grid._cards if c.isVisible())
        self.assertGreaterEqual(card.width(), 300)
        view.grid.hide()
        card._show_overlay_now()
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
