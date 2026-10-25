"""Virtualized search-result table: model + visible-only action editors."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QPushButton

from src.domain.search_hit import SearchHit
from ui.widgets.result_table import ResultTable
from ui.widgets.result_view import VIEW_GRID, VIEW_TABLE, ResultView
from ui.widgets.search_result_table_model import SearchResultTableModel, ThumbRole
from ui.widgets.table_specs import LocalSearchCol


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
        "shot_list_add": "Add",
        "shot_list_add_tip": "",
        "deep_locate": "Find shot",
        "deep_locate_tip": "",
        "result_mode_frame": "Frame",
        "result_mode_chunk": "Chunk",
        "result_mode_video": "Video",
        "result_mode_dialogue": "Dialogue",
        "time_preview_label": "Preview ~{time}",
    }


def _hits(n: int = 50):
    return [
        SearchHit(float(i), float(i) + 1.0, 0.9 - i * 0.001, rf"D:\videos\clip_{i}.mp4", match_kind="frame")
        for i in range(n)
    ]


class SearchResultTableModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_model_holds_thousands_without_widgets(self):
        # Real QObject parent (not MagicMock) — QAbstractTableModel requires it.
        parent = QObject()
        model = SearchResultTableModel(parent)
        model.set_hits(_hits(3000), texts=_texts(), rank_offset=0)
        self.assertEqual(model.rowCount(), 3000)
        self.assertEqual(model.data(model.index(0, LocalSearchCol.ORDER), Qt.ItemDataRole.DisplayRole), "1")
        self.assertEqual(model.data(model.index(2999, LocalSearchCol.ORDER), Qt.ItemDataRole.DisplayRole), "3000")
        payload = model.data(model.index(2, LocalSearchCol.ORDER), Qt.ItemDataRole.UserRole)
        self.assertEqual(payload["video_path"], r"D:\videos\clip_2.mp4")

    def test_set_thumbnail_updates_thumb_role(self):
        model = SearchResultTableModel()
        model.set_hits(_hits(3), texts=_texts())
        pix = QPixmap(32, 18)
        pix.fill(Qt.GlobalColor.red)
        model.set_thumbnail(1, pix)
        got = model.data(model.index(1, LocalSearchCol.PREVIEW), ThumbRole)
        self.assertIsNotNone(got)
        self.assertFalse(got.isNull())
        model.set_thumbnail(1, None)
        self.assertIsNone(model.data(model.index(1, LocalSearchCol.PREVIEW), ThumbRole))

    def test_result_table_opens_action_editors_only_for_visible_rows(self):
        table = ResultTable()
        table.resize(900, 400)
        table.show()
        self.app.processEvents()

        clicks = []

        def on_preview(path, start, end):
            clicks.append(("preview", path, start, end))

        def on_locate(path):
            clicks.append(("locate", path))

        def on_export(path, start, end):
            clicks.append(("export", path, start, end))

        table.populate_results(
            _hits(80),
            on_preview,
            on_locate,
            on_export,
            _texts(),
            on_add_to_shot_list=lambda *a: clicks.append(("add", a)),
        )
        self.app.processEvents()
        table._sync_action_editors()
        self.app.processEvents()

        self.assertEqual(table.rowCount(), 80)
        # Off-screen rows must not hold action button hosts.
        open_rows = set(table._open_action_rows)
        self.assertGreater(len(open_rows), 0)
        self.assertLess(len(open_rows), 80)
        # Roughly viewport-sized (±1 buffer).
        self.assertLessEqual(len(open_rows), 20)

        buttons = table.findChildren(QPushButton)
        self.assertGreater(len(buttons), 0)
        # 80 rows × ≥3 buttons would be 240+; visible-only should stay well under that.
        self.assertLess(len(buttons), 120)

        # Thumbnail still applies through the model (no setCellWidget).
        pix = QPixmap(40, 24)
        pix.fill(Qt.GlobalColor.blue)
        table.set_thumbnail(0, pix)
        self.assertIsNotNone(table.result_model.data(table.result_model.index(0, LocalSearchCol.PREVIEW), ThumbRole))
        payload = table.hit_payload(0)
        self.assertEqual(payload["video_path"], r"D:\videos\clip_0.mp4")
        self.assertTrue(hasattr(table, "doubleClicked"))
        self.assertFalse(hasattr(table, "cellDoubleClicked"))

        table.hide()

    def test_result_view_apis_table_and_grid(self):
        view = ResultView()
        self.assertEqual(view.view_mode, VIEW_TABLE)
        texts = _texts()
        hits = _hits(4)

        def _noop(*_a, **_k):
            return None

        view.populate_local(hits, _noop, _noop, _noop, texts)
        self.assertEqual(view.table.rowCount(), 4)
        self.assertEqual(view.grid.count(), 0)

        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.green)
        view.set_thumbnail(1, pix)
        self.assertIsNotNone(
            view.table.result_model.data(view.table.result_model.index(1, LocalSearchCol.PREVIEW), ThumbRole)
        )

        view.set_view_mode(VIEW_GRID, emit=False)
        view.populate_local(hits, _noop, _noop, _noop, texts)
        self.assertEqual(view.grid.count(), 4)
        self.assertEqual(view.table.rowCount(), 0)

        view.clear()
        self.assertEqual(view.grid.count(), 0)
        self.assertEqual(view.table.rowCount(), 0)

    def test_append_and_rank_offset(self):
        table = ResultTable()
        texts = _texts()

        def _noop(*_a, **_k):
            return None

        table.populate_results(_hits(5), _noop, _noop, _noop, texts, rank_offset=0)
        table.append_results(_hits(3), _noop, _noop, _noop, texts, rank_offset=5)
        self.assertEqual(table.rowCount(), 8)
        self.assertEqual(
            table.result_model.data(table.result_model.index(5, LocalSearchCol.ORDER), Qt.ItemDataRole.DisplayRole),
            "6",
        )

    def test_grid_defers_action_buttons_until_hover(self):
        from ui.widgets.result_grid import ResultGrid, ResultGridCard

        grid = ResultGrid()
        texts = _texts()

        def _noop(*_a, **_k):
            return None

        grid.populate(_hits(6), _noop, _noop, _noop, texts)
        card: ResultGridCard = grid._cards[0]
        self.assertFalse(card._actions_ready)
        self.assertEqual(len(card.findChildren(QPushButton)), 0)
        card._show_overlay_now()
        self.assertTrue(card._actions_ready)
        self.assertGreater(len(card.findChildren(QPushButton)), 0)


if __name__ == "__main__":
    unittest.main()
