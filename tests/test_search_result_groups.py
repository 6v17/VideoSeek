"""Visual result grouping: nearby frames in one video, stricter merge across videos."""

from __future__ import annotations

import math
import unittest
from unittest.mock import patch

import numpy as np

from src.domain.search_hit import SearchHit
from src.services.search_result_groups import (
    fetch_hit_frame_vectors,
    flatten_result_groups,
    focus_group_rows,
    group_hit_batches,
    group_search_hits,
)


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

    def test_later_batch_stays_below_a_higher_score(self):
        first = [_hit("a.mp4", 10.0, 0.4), _hit("a.mp4", 12.0, 0.5)]
        second = [_hit("a.mp4", 14.0, 0.99)]
        together = group_search_hits(first + second, enabled=True)
        batched = group_hit_batches([first, second], enabled=True)
        self.assertEqual(len(together), 1)
        self.assertEqual(len(batched), 2)
        self.assertEqual(float(batched[0].representative.score), 0.5)
        self.assertEqual(float(batched[1].representative.start_sec), 14.0)
        rows = flatten_result_groups(batched)
        self.assertEqual([row.display_rank for row in rows], [1, 2])
        self.assertEqual(float(rows[0].score), 0.5)
        self.assertEqual(float(rows[1].score), 0.99)

    def test_later_batch_does_not_cross_merge(self):
        first = [_hit("ep1.mp4", 1.0, 0.7, "1")]
        second = [_hit("ep2.mp4", 2.0, 0.95, "2")]
        vectors = [np.array([1.0, 0.0], dtype=np.float32), _unit(0.95)]
        together = group_search_hits(first + second, vectors, enabled=True, sensitivity="standard")
        batched = group_hit_batches(
            [first, second],
            [[vectors[0]], [vectors[1]]],
            enabled=True,
            sensitivity="standard",
        )
        self.assertEqual(len(together), 1)
        self.assertEqual(together[0].kind, "cross")
        self.assertEqual(len(batched), 2)
        self.assertEqual(batched[0].representative.video_path, "ep1.mp4")
        self.assertEqual(batched[1].representative.video_path, "ep2.mp4")

    def test_flatten_offset_keeps_earlier_group_ids(self):
        extra = group_search_hits([_hit("b.mp4", 1.0, 0.2)], enabled=True)
        rows = flatten_result_groups(extra, id_offset=4)
        self.assertEqual(rows[0].group_id, 4)
        self.assertEqual(rows[0].display_rank, 5)

    def test_blocked_cross_video_matches_the_full_matrix(self):
        count = 800
        rng = np.random.default_rng(7)
        raw = rng.standard_normal((count, 512)).astype(np.float32)
        raw /= np.linalg.norm(raw, axis=1, keepdims=True)
        step = math.acos(0.96)
        for turn, index in enumerate((0, 500, 700)):
            theta = step * turn
            raw[index] = 0
            raw[index, 0] = math.cos(theta)
            raw[index, 1] = math.sin(theta)
        hits = [_hit(f"v{index}.mp4", index * 100.0, 1.0 - index * 1e-6, str(index)) for index in range(count)]
        groups = group_search_hits(hits, [row.copy() for row in raw], enabled=True, sensitivity="standard")
        self.assertEqual(_member_sets(groups), _full_matrix_sets(hits, raw, 0.94))
        chained = {0.0, 50000.0, 70000.0}
        self.assertTrue(any(chained <= {start for _path, start in members} for members in _member_sets(groups)))

    def test_one_video_spread_stays_unmerged(self):
        count = 400
        hits = [_hit("same.mp4", index * 30.0, 1.0 - index * 1e-6, "same") for index in range(count)]
        vector = np.zeros(32, dtype=np.float32)
        vector[0] = 1
        groups = group_search_hits(hits, [vector.copy() for _index in range(count)], enabled=True)
        self.assertEqual(len(groups), count)
        self.assertTrue(all(group.kind == "single" for group in groups))

    def test_chunk_vector_follows_the_scoring_frame(self):
        chunk_start = np.array([1.0, 0.0], dtype=np.float32)
        scoring = np.array([0.0, 1.0], dtype=np.float32)
        neighbor = np.array([0.2, 0.8], dtype=np.float32)
        hit = SearchHit(10.0, 18.0, 0.9, "ep.mp4", video_id="7", peak_sec=16.0)
        seen = {}

        def fetch(seeds, window_sec=0.0):
            seen["seeds"] = list(seeds)
            seen["window"] = window_sec
            return [[_Frame(10.0, chunk_start), _Frame(16.0, scoring), _Frame(16.3, neighbor)]]

        vectors = _fetch_vectors([hit], fetch)
        self.assertEqual(seen["seeds"], [("ep.mp4", 16.0, "7")])
        self.assertEqual(seen["window"], 0.45)
        self.assertTrue(np.allclose(vectors[0], scoring))

    def test_close_frame_hits_keep_their_own_vectors(self):
        first = np.array([1.0, 0.0], dtype=np.float32)
        second = np.array([0.0, 1.0], dtype=np.float32)
        hits = [
            SearchHit(10.0, 10.0, 0.8, "a.mp4", video_id="1"),
            SearchHit(10.2, 10.2, 0.7, "a.mp4", video_id="1"),
        ]
        shared = [_Frame(10.0, first), _Frame(10.2, second)]

        def fetch(seeds, window_sec=0.0):
            self.assertEqual([seed[1] for seed in seeds], [10.0, 10.2])
            self.assertEqual(window_sec, 0.45)
            return [shared, shared]

        vectors = _fetch_vectors(hits, fetch)
        self.assertTrue(np.allclose(vectors[0], first))
        self.assertTrue(np.allclose(vectors[1], second))


class _Frame:
    def __init__(self, timestamp: float, vector: np.ndarray):
        self.timestamp = timestamp
        self.vector = vector


def _fetch_vectors(hits, fetch):
    index = type("Index", (), {"fetch_neighbor_rows_grouped": staticmethod(fetch)})()
    with patch("src.services.search_assets.load_search_assets", return_value=(index, None, None)):
        return fetch_hit_frame_vectors(hits, {})


def _member_sets(groups) -> set[frozenset]:
    return {
        frozenset((hit.video_path, float(hit.start_sec)) for hit in group.members)
        for group in groups
    }


def _full_matrix_sets(hits, vectors, threshold: float) -> set[frozenset]:
    """Previous cross-video rule: one similarity matrix, then every pair above the threshold."""
    units = []
    for vector in vectors:
        array = np.asarray(vector, dtype=np.float32).reshape(-1)
        array = array / float(np.linalg.norm(array))
        units.append(array)
    similarity = np.stack(units) @ np.stack(units).T
    parent = list(range(len(hits)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for left in range(len(hits)):
        for right in range(left + 1, len(hits)):
            if hits[left].video_id == hits[right].video_id:
                continue
            if float(similarity[left, right]) >= threshold:
                root = find(right)
                parent[root] = find(left)
    found: dict[int, set] = {}
    for index, hit in enumerate(hits):
        found.setdefault(find(index), set()).add((hit.video_path, float(hit.start_sec)))
    return {frozenset(members) for members in found.values()}


if __name__ == "__main__":
    unittest.main()
