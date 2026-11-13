import unittest

from src.domain.search_hit import SearchHit
from src.services.search_query import filter_hits_by_min_score
from src.storage.config_store import (
    SEARCH_CANDIDATE_LIMIT,
    SEARCH_TOP_K_MAX,
    clamp_search_top_k,
    get_search_min_score,
    get_search_top_k,
    resolve_effective_min_score,
    resolve_search_score_kind,
)


class SearchScoreKindTests(unittest.TestCase):
    def test_image_modes_keep_separate_floors(self):
        self.assertEqual(resolve_search_score_kind(is_text=False, search_mode="frame"), "image")
        self.assertEqual(resolve_search_score_kind(is_text=False, search_mode="chunk"), "image_chunk")
        self.assertEqual(
            resolve_search_score_kind(is_text=False, video_discovery_enabled=True),
            "image",
        )
        self.assertEqual(
            resolve_search_score_kind(is_text=False, search_precision_mode="precise"),
            "image",
        )

    def test_text_compose_and_dialogue_have_floors_tags_do_not(self):
        self.assertEqual(resolve_search_score_kind(is_text=True, search_mode="chunk"), "text")
        self.assertEqual(resolve_search_score_kind(search_kind="compose", compose_text="a"), "compose")
        self.assertIsNone(resolve_search_score_kind(search_kind="dialogue", search_mode="exact"))
        self.assertEqual(
            resolve_search_score_kind(search_kind="dialogue", search_mode="fuzzy"),
            "dialogue",
        )
        self.assertIsNone(resolve_search_score_kind(search_kind="tags"))

    def test_new_modes_use_their_own_defaults(self):
        blank = {"language": "zh"}
        self.assertEqual(get_search_min_score(blank, kind="image"), 0.12)
        self.assertEqual(get_search_min_score(blank, kind="image_chunk"), 0.12)
        self.assertEqual(get_search_min_score(blank, kind="dialogue"), 0.0)
        stored = {
            "search_min_score_image_chunk": 0.33,
            "search_min_score_dialogue": 0.4,
        }
        self.assertEqual(get_search_min_score(stored, kind="image_chunk"), 0.33)
        self.assertEqual(get_search_min_score(stored, kind="dialogue"), 0.4)

    def test_omitted_top_k_is_the_first_window(self):
        self.assertEqual(get_search_top_k({"search_top_k": 20}), SEARCH_CANDIDATE_LIMIT)

    def test_explicit_window_can_grow_past_the_old_cap(self):
        self.assertEqual(clamp_search_top_k(400, default=100), 400)
        self.assertEqual(clamp_search_top_k(None, default=100), 100)
        self.assertEqual(clamp_search_top_k(10**9, default=100), SEARCH_TOP_K_MAX)

    def test_omitted_score_uses_the_host_floor_for_that_mode(self):
        blank = {"language": "zh"}
        self.assertEqual(
            resolve_effective_min_score(None, config=blank, is_text=False, search_mode="chunk"),
            0.12,
        )
        self.assertEqual(
            resolve_effective_min_score(0.4, config=blank, is_text=False, search_mode="chunk"),
            0.4,
        )
        saved_text = {"search_min_score_text": 0.1}
        self.assertEqual(
            resolve_effective_min_score(0.0, config=saved_text, is_text=True),
            0.0,
        )
        self.assertIsNone(resolve_effective_min_score(None, config=blank, search_kind="tags"))

    def test_slider_keeps_hits_at_or_above_that_similarity(self):
        hits = [
            SearchHit(0.0, 1.0, 0.393, "noise.mp4"),
            SearchHit(1.0, 2.0, 0.353, "hit.mp4"),
            SearchHit(2.0, 3.0, 0.20, "tail.mp4"),
            SearchHit(3.0, 4.0, 0.09, "below.mp4"),
        ]
        kept = filter_hits_by_min_score(hits, 0.10)
        self.assertEqual([hit.video_path for hit in kept], ["noise.mp4", "hit.mp4", "tail.mp4"])
        self.assertEqual(filter_hits_by_min_score(hits, 0.0), hits)


class ScoreSliderResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication

        cls._app = QApplication.instance() or QApplication([])

    def test_moving_off_the_old_floor_searches_again(self):
        from PySide6.QtCore import QObject

        from ui.controllers.search_controller import SearchController
        from ui.workers import SearchConfig

        parent = QObject()
        controller = SearchController(parent)
        controller._search_config = SearchConfig(query="雨夜", is_text=True, min_score=None)
        started = {}

        def fake_start(*args, **kwargs):
            started["query"] = args[0]
            started["min_score"] = kwargs.get("min_score")

        controller.start_search = fake_start
        self.assertTrue(controller.restart_with_min_score(0.0))
        self.assertEqual(started["query"], "雨夜")
        self.assertEqual(started["min_score"], 0.0)

        controller._search_config = SearchConfig(query="雨夜", is_text=True, min_score=0.0)
        self.assertFalse(controller.restart_with_min_score(0.0))


class SliderMinScoreTests(unittest.TestCase):
    def test_zero_on_the_slider_is_the_value_search_uses(self):
        from ui.windows.gui_search_panel_state import SearchPanelStateMixin

        class _Panel:
            def score_threshold(self, kind):
                self.kind = kind
                return 0.0

        class _Page:
            search_panel = _Panel()

        host = SearchPanelStateMixin()
        host.search_page = _Page()
        host._active_search_score_kind = lambda: "text"
        saved: list[str] = []
        host._save_search_score_threshold = saved.append

        self.assertEqual(host._slider_search_min_score(), 0.0)
        self.assertEqual(saved, ["text"])
        self.assertEqual(host.search_page.search_panel.kind, "text")

    def test_modes_without_a_slider_do_not_invent_a_floor(self):
        from ui.windows.gui_search_panel_state import SearchPanelStateMixin

        host = SearchPanelStateMixin()
        host._active_search_score_kind = lambda: None
        host._save_search_score_threshold = lambda kind: self.fail(kind)

        self.assertIsNone(host._slider_search_min_score())


if __name__ == "__main__":
    unittest.main()
