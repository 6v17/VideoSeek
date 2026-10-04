"""Multi-range skip filter for search result lists."""

import unittest

from src.domain.search_hit import SearchHit
from src.services import search_edge_filter as edge_mod
from src.services import search_hit_utils as hit_utils
from src.services.search_edge_filter import (
    expand_fetch_for_edge_filter,
    filter_search_edge_hits,
    hit_in_skipped_edge,
    merge_video_end_lookup,
    reset_video_end_lookup,
    resolve_skip_edges_chrome,
    skip_edges_api_meta,
)
from src.services.search_skip_ranges import parse_search_skip_ranges


class SearchEdgeFilterTests(unittest.TestCase):
    def setUp(self):
        reset_video_end_lookup()

    def tearDown(self):
        reset_video_end_lookup()

    def test_intro_and_outro_drop_with_end_lookup(self):
        cfg = {
            "search_skip_edges_enabled": True,
            "search_skip_ranges": "0-90; end-90",
        }
        end_lookup = {"a.mp4": 1400.0}
        rules = parse_search_skip_ranges(cfg["search_skip_ranges"])
        self.assertTrue(
            hit_in_skipped_edge(
                SearchHit(30.0, 30.0, 0.9, "a.mp4"),
                ranges=rules,
                end_lookup=end_lookup,
            )
        )
        self.assertTrue(
            hit_in_skipped_edge(
                SearchHit(1350.0, 1350.0, 0.9, "a.mp4"),
                ranges=rules,
                end_lookup=end_lookup,
            )
        )
        self.assertFalse(
            hit_in_skipped_edge(
                SearchHit(400.0, 400.0, 0.9, "a.mp4"),
                ranges=rules,
                end_lookup=end_lookup,
            )
        )
        kept = filter_search_edge_hits(
            [
                SearchHit(30.0, 30.0, 0.99, "a.mp4"),
                SearchHit(400.0, 400.0, 0.8, "a.mp4"),
                SearchHit(1350.0, 1350.0, 0.95, "a.mp4"),
            ],
            cfg,
            end_lookup=end_lookup,
        )
        self.assertEqual([float(h.start_sec) for h in kept], [400.0])

    def test_hms_and_compound_tokens(self):
        rules = parse_search_skip_ranges("0-1:30; 1:00:00-1:01:30; end-1h30m")
        self.assertEqual(rules[0]["start"], 0.0)
        self.assertEqual(rules[0]["end"], 90.0)
        self.assertEqual(rules[1]["start"], 3600.0)
        self.assertEqual(rules[1]["end"], 3690.0)
        self.assertEqual(rules[2]["kind"], "from_end")
        self.assertEqual(rules[2]["amount"], 5400.0)

    def test_multiple_absolute_ranges(self):
        cfg = {
            "search_skip_edges_enabled": True,
            "search_skip_ranges": "0-90; 600-720",
        }
        end_lookup = {"a.mp4": 1400.0}
        kept = filter_search_edge_hits(
            [
                SearchHit(30.0, 30.0, 0.99, "a.mp4"),
                SearchHit(650.0, 650.0, 0.95, "a.mp4"),
                SearchHit(800.0, 800.0, 0.8, "a.mp4"),
            ],
            cfg,
            end_lookup=end_lookup,
        )
        self.assertEqual([float(h.start_sec) for h in kept], [800.0])

    def test_short_video_is_not_filtered(self):
        rules = parse_search_skip_ranges("0-90; end-90")
        end_lookup = {"short.mp4": 120.0}
        self.assertFalse(
            hit_in_skipped_edge(
                SearchHit(10.0, 10.0, 0.9, "short.mp4"),
                ranges=rules,
                end_lookup=end_lookup,
            )
        )

    def test_merge_video_end_lookup_accepts_numpy_timestamps(self):
        import numpy as np

        from src.services.search_edge_filter import get_video_end_lookup

        merge_video_end_lookup(
            np.array(["a.mp4", "a.mp4"]),
            np.array([1.0, 12.5]),
        )
        self.assertEqual(max(get_video_end_lookup().values()), 12.5)

    def test_merge_backfills_after_edge_filter(self):
        merge_video_end_lookup(["a.mp4"] * 5, [0.0, 50.0, 200.0, 400.0, 1300.0])
        cfg = {
            "search_skip_edges_enabled": True,
            "search_skip_ranges": "0-90; end-90",
        }
        hits = [
            SearchHit(50.0, 50.0, 0.99, "a.mp4"),
            SearchHit(200.0, 200.0, 0.9, "a.mp4"),
            SearchHit(400.0, 400.0, 0.8, "a.mp4"),
            SearchHit(1300.0, 1300.0, 0.7, "a.mp4"),
        ]
        original = edge_mod.load_config
        edge_mod.load_config = lambda: cfg
        try:
            merged = hit_utils._merge_search_hits(hits, 2)
        finally:
            edge_mod.load_config = original
        self.assertEqual([float(h.start_sec) for h in merged], [200.0, 400.0])

    def test_legacy_intro_outro_still_works(self):
        cfg = {
            "search_skip_edges_enabled": True,
            "search_skip_intro_sec": 90,
            "search_skip_outro_sec": 90,
            "search_skip_ranges": "",
        }
        end_lookup = {"a.mp4": 1400.0}
        kept = filter_search_edge_hits(
            [
                SearchHit(30.0, 30.0, 0.99, "a.mp4"),
                SearchHit(400.0, 400.0, 0.8, "a.mp4"),
                SearchHit(1350.0, 1350.0, 0.95, "a.mp4"),
            ],
            cfg,
            end_lookup=end_lookup,
        )
        self.assertEqual([float(h.start_sec) for h in kept], [400.0])

    def test_expand_fetch_grows_pool_when_enabled(self):
        off = expand_fetch_for_edge_filter(100, 100, {"search_skip_edges_enabled": False})
        on = expand_fetch_for_edge_filter(
            100,
            100,
            {"search_skip_edges_enabled": True, "search_skip_ranges": "0-90"},
        )
        self.assertEqual(off, 100)
        self.assertGreaterEqual(on, 200)

    def test_result_pool_keeps_expanded_fetch_when_enabled(self):
        from src.services.search_edge_filter import resolve_result_pool_k

        self.assertEqual(
            resolve_result_pool_k(240, 100, {"search_skip_edges_enabled": False}),
            100,
        )
        self.assertEqual(
            resolve_result_pool_k(
                240,
                100,
                {"search_skip_edges_enabled": True, "search_skip_ranges": "0-90"},
            ),
            240,
        )
        self.assertEqual(
            resolve_result_pool_k(240, 100, {"search_skip_edges_enabled": False}, force_expand=True),
            240,
        )

    def test_team_client_skip_control_is_locked_to_server_rule(self):
        texts = {
            "search_skip_edges_team_client": "服务机",
            "search_skip_edges_team_client_hint": "由服务机统一设置",
            "search_skip_edges_team_server_hint": "对所有用户生效",
            "search_skip_edges_off": "不过滤",
            "search_skip_edges_count": "{count}段",
            "skip_edges_hint": "填写时段",
        }
        client = resolve_skip_edges_chrome(
            team_mode="client",
            ranges_text="0-90",
            texts=texts,
        )
        self.assertFalse(client["enabled"])
        self.assertEqual(client["summary"], "服务机")
        self.assertIn("服务机", client["tooltip"])

        local = resolve_skip_edges_chrome(
            team_mode="off",
            ranges_text="0-90; end-60",
            texts=texts,
        )
        self.assertTrue(local["enabled"])
        self.assertEqual(local["summary"], "2段")
        self.assertNotIn("对所有用户生效", local["tooltip"])

        server = resolve_skip_edges_chrome(
            team_mode="server",
            ranges_text="0-90",
            texts=texts,
        )
        self.assertTrue(server["enabled"])
        self.assertEqual(server["summary"], "0-90")
        self.assertIn("对所有用户生效", server["tooltip"])

    def test_api_meta_reports_server_rule_without_request_override(self):
        off = skip_edges_api_meta({"search_skip_ranges": "", "search_skip_edges_enabled": False})
        self.assertEqual(off["search_skip_ranges"], "")
        self.assertFalse(off["search_skip_edges_applied"])
        on = skip_edges_api_meta(
            {"search_skip_ranges": "0-90", "search_skip_edges_enabled": True}
        )
        self.assertEqual(on["search_skip_ranges"], "0-90")
        self.assertTrue(on["search_skip_edges_applied"])


if __name__ == "__main__":
    unittest.main()
