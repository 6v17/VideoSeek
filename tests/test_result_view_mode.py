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

    def test_grid_video_discovery_includes_deep_locate_and_elides_title(self):
        from ui.widgets.result_grid import ResultGridCard

        card = ResultGridCard()
        deep_calls = []
        long_name = (
            "very_long_video_file_name_for_elide_check_"
            "abcdefghijklmnop_qrstuvwxyz_0123456789_extra_tail.mp4"
        )
        hit = SearchHit(12.0, 12.0, 0.88, rf"D:\videos\{long_name}", match_kind="video")
        texts = {
            "preview": "预览",
            "preview_tip": "",
            "locate": "定位",
            "locate_tip": "",
            "deep_locate": "定位镜头",
            "deep_locate_tip": "",
            "export_clip": "导出",
            "export_clip_tip": "",
            "shot_list_add": "加入",
            "shot_list_add_tip": "",
            "thumb_loading": "...",
            "time_preview_label": "Preview ~{time}",
        }

        def _noop(*_a, **_k):
            return None

        card.bind(
            rank=1,
            hit=hit,
            texts=texts,
            on_preview=_noop,
            on_locate=_noop,
            on_export=_noop,
            on_deep_locate=lambda *args: deep_calls.append(args),
            on_add_to_shot_list=_noop,
        )
        card.setFixedWidth(312)
        card.title_label.setFixedWidth(160)
        card._refresh_title_elide()

        action_row = card.actions_host.layout().itemAt(0).widget()
        from PySide6.QtWidgets import QPushButton

        labels = [btn.text() for btn in action_row.findChildren(QPushButton)]
        self.assertEqual(labels, ["预览", "定位镜头", "定位", "导出", "加入"])
        locate = next(btn for btn in action_row.findChildren(QPushButton) if btn.text() == "定位")
        self.assertEqual(locate.property("class"), "TableLocateBtn")
        shown = card.title_label.text()
        self.assertNotEqual(shown, long_name)
        self.assertLess(len(shown), len(long_name))
        self.assertTrue("…" in shown or "..." in shown)
        self.assertTrue(card.title_label.toolTip().endswith(long_name))


if __name__ == "__main__":
    unittest.main()
