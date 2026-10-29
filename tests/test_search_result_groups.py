"""Visual result grouping: nearby frames in one video, stricter merge across videos."""

from __future__ import annotations

import math
import unittest

import numpy as np

from src.domain.search_hit import SearchHit
from src.services.search_result_groups import flatten_result_groups, focus_group_rows, group_search_hits


def _hit(path: str, start: float, score: float, video_id: str = "") -> SearchHit:
    return SearchHit(start, start, score, path, video_id=video_id)


def _unit(cosine: float) -> np.ndarray:
    return np.array([cosine, math.sqrt(max(0.0, 1.0 - cosine * cosine))], dtype=np.float32)


class SearchResultGroupTests(unittest.TestCase):
    def test_disabled_keeps_every_hit(self):
        hits = [_hit("a.mp4", 1.0, 0.9), _hit("a.mp4", 2.0, 0.8)]
        groups = group_search_hits(hits, enabled=False)
        self.assertEqual(len(groups), 2)
        self.assertTrue(all(group.kind == "single" for group in groups))

    def test_same_video_nearby_frames_group_without_vectors(self):
        hits = [_hit("a.mp4", 10.0, 0.4), _hit("a.mp4", 12.0, 0.9), _hit("a.mp4", 40.0, 0.95)]
        groups = group_search_hits(hits, enabled=True)
        self.assertEqual(len(groups), 2)
        near = next(group for group in groups if group.kind == "near")
        self.assertEqual(float(near.representative.start_sec), 12.0)
        self.assertEqual(float(near.representative.score), 0.9)
        self.assertEqual(len(near.members), 2)

    def test_nearby_chain_stays_one_group(self):
        hits = [_hit("a.mp4", 0.0, 0.2), _hit("a.mp4", 3.0, 0.3), _hit("a.mp4", 6.0, 0.5)]
        groups = group_search_hits(hits, enabled=True)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].kind, "near")
        self.assertEqual(len(groups[0].members), 3)

    def test_cross_video_uses_sensitivity(self):
        hits = [_hit("ep1.mp4", 1.0, 0.7, "1"), _hit("ep2.mp4", 2.0, 0.95, "2")]
        vectors = [np.array([1.0, 0.0], dtype=np.float32), _unit(0.95)]
        standard = group_search_hits(hits, vectors, enabled=True, sensitivity="standard")
        strict = group_search_hits(hits, vectors, enabled=True, sensitivity="strict")
        self.assertEqual(len(standard), 1)
        self.assertEqual(standard[0].kind, "cross")
        self.assertEqual(standard[0].unique_videos, 2)
        self.assertEqual(float(standard[0].representative.score), 0.95)
        self.assertEqual(len(strict), 2)

    def test_weak_cross_video_similarity_stays_split(self):
        hits = [_hit("ep1.mp4", 1.0, 0.7, "1"), _hit("ep2.mp4", 2.0, 0.6, "2")]
        vectors = [np.array([1.0, 0.0], dtype=np.float32), _unit(0.5)]
        groups = group_search_hits(hits, vectors, enabled=True, sensitivity="loose")
        self.assertEqual(len(groups), 2)

    def test_flatten_puts_members_under_the_representative(self):
        hits = [_hit("a.mp4", 1.0, 0.4), _hit("a.mp4", 2.0, 0.9)]
        groups = group_search_hits(hits, enabled=True)
        collapsed = flatten_result_groups(groups)
        self.assertEqual(len(collapsed), 1)
        self.assertTrue(collapsed[0].show_badge)
        opened = flatten_result_groups(groups, expanded={0})
        self.assertEqual(len(opened), 2)
        self.assertTrue(opened[0].is_representative)
        self.assertFalse(opened[1].is_representative)
        self.assertEqual(float(opened[1].start_sec), 1.0)

    def test_focus_lists_members_without_badges(self):
        hits = [_hit("ep1.mp4", 5.0, 0.4, "1"), _hit("ep2.mp4", 1.0, 0.9, "2")]
        vectors = [np.array([1.0, 0.0], dtype=np.float32), np.array([1.0, 0.0], dtype=np.float32)]
        groups = group_search_hits(hits, vectors, enabled=True)
        rows = focus_group_rows(groups[0], group_id=0)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(not row.show_badge for row in rows))
        self.assertEqual(rows[0].video_path, "ep1.mp4")
        self.assertEqual(rows[1].video_path, "ep2.mp4")


if __name__ == "__main__":
    unittest.main()
