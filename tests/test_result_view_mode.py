import unittest

from PySide6.QtWidgets import QApplication

from src.domain.search_hit import SearchHit
from ui.widgets.result_view import VIEW_GRID, VIEW_TABLE, ResultView


_APP = None


def _ensure_app():
    global _APP
    app = QApplication.instance()
    if app is None:
        _APP = QApplication([])
    return QApplication.instance()


class ResultViewModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _ensure_app()

    def test_default_table_mode_and_grid_populate(self):
        view = ResultView()
        self.assertEqual(view.view_mode, VIEW_TABLE)
        texts = {
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
        hits = [
            SearchHit(1.0, 2.0, 0.91, r"D:\videos\a.mp4", match_kind="frame"),
            SearchHit(3.0, 5.0, 0.8, r"D:\videos\b.mp4", match_kind="chunk"),
        ]

        def _noop(*_args, **_kwargs):
            return None

        view.populate_local(hits, _noop, _noop, _noop, texts)
        self.assertEqual(view.table.rowCount(), 2)
        self.assertEqual(view.grid.count(), 0)

        view.set_view_mode(VIEW_GRID, emit=False)
        view.populate_local(hits, _noop, _noop, _noop, texts)
        self.assertEqual(view.view_mode, VIEW_GRID)
        self.assertEqual(view.grid.count(), 2)
        self.assertEqual(view.table.rowCount(), 0)

        view.clear()
        self.assertEqual(view.grid.count(), 0)
        self.assertEqual(view.table.rowCount(), 0)

    def test_grid_card_elides_title_and_opens_preview_on_double_click(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        from ui.widgets.result_grid import ResultGridCard

        card = ResultGridCard()
        opened = []
        long_name = (
            "very_long_video_file_name_for_elide_check_"
            "abcdefghijklmnop_qrstuvwxyz_0123456789_extra_tail.mp4"
        )
        hit = SearchHit(12.0, 12.0, 0.88, rf"D:\videos\{long_name}", match_kind="video")
        texts = {
            "thumb_loading": "...",
            "time_preview_label": "Preview ~{time}",
        }
        card.bind(
            rank=1,
            hit=hit,
            texts=texts,
            on_preview=lambda *args: opened.append(args),
        )
        card.title_label.setFixedWidth(160)
        card._refresh_title_elide()

        shown = card.title_label.text()
        self.assertNotEqual(shown, long_name)
        self.assertLess(len(shown), len(long_name))
        self.assertTrue("…" in shown or "..." in shown)
        self.assertTrue(card.title_label.toolTip().endswith(long_name))
        self.assertFalse(hasattr(card, "actions_host"))

        local = QPointF(card.rect().center())
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            local,
            local,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        selected = []
        card._on_select = lambda item: selected.append(item)
        card.mousePressEvent(press)
        self.assertEqual(selected, [card])
        self.assertEqual(opened, [])

        dbl = QMouseEvent(
            QEvent.Type.MouseButtonDblClick,
            local,
            local,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        card.mouseDoubleClickEvent(dbl)
        self.assertEqual(len(opened), 1)
        self.assertEqual(opened[0][0], hit.video_path)

    def test_compact_grid_fits_five_columns_on_browse_width(self):
        from ui.widgets.result_grid import ResultGrid, _CARD_SPACING, _CARD_WIDTH, _GRID_BOTTOM_PAD

        usable = 1100 - 16
        cols = max(1, (usable + _CARD_SPACING) // (_CARD_WIDTH + _CARD_SPACING))
        self.assertGreaterEqual(cols, 5)

        grid = ResultGrid()
        texts = {"thumb_loading": "...", "result_mode_frame": "Frame"}
        hits = [
            SearchHit(1.0, 2.0, 0.9, rf"D:\videos\clip_{i}.mp4", match_kind="frame")
            for i in range(6)
        ]

        def _noop(*_a, **_k):
            return None

        grid.populate(hits, _noop, _noop, _noop, texts)
        grid._sync_host_height()
        self.assertEqual(grid._cards[0].width(), _CARD_WIDTH)
        self.assertFalse(hasattr(grid._cards[0], "actions_host"))
        self.assertGreater(grid._host.minimumHeight(), _GRID_BOTTOM_PAD)


if __name__ == "__main__":
    unittest.main()
