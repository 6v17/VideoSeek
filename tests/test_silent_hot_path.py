"""Hot-path failures stay visible and are not stored as a normal result."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from src.domain.search_hit import SearchHit
from src.services.search_frame_query import _search_frame_results_in_time_window
from src.services.search_neighbor_rerank import _apply_bounded_neighbor_refine_lance
from src.web.agent_api.constants import _duration_cache
from src.web.agent_api.search import _get_video_duration_cached


class _BadQuery:
    ndim = 2

    @property
    def shape(self):
        return (1, 4)

    def __getitem__(self, _index):
        raise RuntimeError("bad query")


class _Index:
    ntotal = 3
    d = 0


class SilentHotPathTests(unittest.TestCase):
    def setUp(self):
        _duration_cache.clear()

    def tearDown(self):
        _duration_cache.clear()

    def test_neighbor_rerank_records_a_bad_query_and_keeps_hits(self):
        hit = SearchHit(1.5, 1.5, 0.4, "a.mp4")
        with patch("src.app.logging_utils.note_swallowed") as noted:
            kept = _apply_bounded_neighbor_refine_lance([hit], _BadQuery(), None)
        self.assertEqual(float(kept[0].start_sec), 1.5)
        noted.assert_called()

    def test_time_window_search_records_a_bad_query(self):
        query = np.empty((1, 1), dtype=object)
        with patch("src.app.logging_utils.note_swallowed") as noted:
            hits, ids = _search_frame_results_in_time_window(
                query,
                _Index(),
                [0.0, 1.0, 2.0],
                ["a.mp4", "a.mp4", "a.mp4"],
                center_sec=1.0,
                window_sec=2.0,
                top_k=3,
            )
        self.assertEqual(hits, [])
        self.assertEqual(ids, [])
        noted.assert_called()

    def test_failed_duration_probe_is_not_cached(self):
        with patch("src.utils.get_video_duration_seconds", side_effect=OSError("unread")) as probe:
            self.assertIsNone(_get_video_duration_cached(r"D:\lib\a.mp4"))
            self.assertIsNone(_get_video_duration_cached(r"D:\lib\a.mp4"))
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(_duration_cache, {})

    def test_known_duration_is_cached(self):
        with patch("src.utils.get_video_duration_seconds", return_value=12.5) as probe:
            self.assertEqual(_get_video_duration_cached(r"D:\lib\a.mp4"), 12.5)
            self.assertEqual(_get_video_duration_cached(r"D:\lib\a.mp4"), 12.5)
        self.assertEqual(probe.call_count, 1)
