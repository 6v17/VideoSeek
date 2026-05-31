import unittest
import unittest.mock

import numpy as np

from src.core.frame_hash import compute_dhash, dhash_similarity
from src.domain.search_hit import SearchHit
from src.services.image_search_rerank import (
    _hit_probe_plan,
    apply_image_pixel_rerank,
    build_index_step_by_video,
    median_index_step,
    resolve_probe_params,
)


def _fixed_probe_config(**overrides):
    config = {
        "image_pixel_rerank_probe_mode": "fixed",
        "image_pixel_rerank_time_window_sec": 1.0,
        "image_pixel_rerank_probe_step_sec": 0.5,
    }
    config.update(overrides)
    return config


class FrameHashTests(unittest.TestCase):
    def test_identical_images_have_high_similarity(self):
        image = np.zeros((120, 160, 3), dtype=np.uint8)
        image[20:80, 40:120] = (255, 128, 64)
        left = compute_dhash(image)
        right = compute_dhash(image.copy())
        self.assertEqual(dhash_similarity(left, right), 1.0)

    def test_different_images_have_lower_similarity(self):
        left_img = np.zeros((90, 120, 3), dtype=np.uint8)
        left_img[:, :60] = 255
        right_img = np.zeros((90, 120, 3), dtype=np.uint8)
        right_img[:, 60:] = 255
        self.assertLess(dhash_similarity(compute_dhash(left_img), compute_dhash(right_img)), 0.8)


class ImageSearchRerankTests(unittest.TestCase):
    @unittest.mock.patch("src.services.image_search_rerank.get_single_thumbnail")
    def test_pixel_rerank_prefers_matching_frame(self, mock_thumb):
        query = np.full((80, 80, 3), 128, dtype=np.uint8)
        query[30:50, 30:50] = (20, 180, 240)
        good_frame = query.copy()
        bad_frame = np.full((80, 80, 3), 128, dtype=np.uint8)

        def _thumb_side_effect(video_path, time_sec):
            if abs(float(time_sec) - 2.0) < 0.01:
                return good_frame
            return bad_frame

        mock_thumb.side_effect = _thumb_side_effect

        hits = [
            SearchHit(1.0, 1.0, 0.92, "a.mp4"),
            SearchHit(2.0, 2.0, 0.90, "a.mp4"),
        ]
        reranked = apply_image_pixel_rerank(
            query,
            hits,
            config=_fixed_probe_config(
                image_pixel_rerank_top_n=2,
                image_pixel_rerank_time_window_sec=0.0,
            ),
            top_k=2,
        )
        self.assertEqual(reranked[0].start_sec, 2.0)

    @unittest.mock.patch("src.services.image_search_rerank.get_single_thumbnail")
    def test_pixel_rerank_snaps_to_nearby_time(self, mock_thumb):
        query = np.full((80, 80, 3), 128, dtype=np.uint8)
        query[30:50, 30:50] = (20, 180, 240)
        match_frame = query.copy()

        def _thumb_side_effect(video_path, time_sec):
            if abs(float(time_sec) - 54.5) < 0.01:
                return match_frame
            return np.full((80, 80, 3), 128, dtype=np.uint8)

        mock_thumb.side_effect = _thumb_side_effect

        hits = [SearchHit(54.0, 54.0, 0.91, "a.mp4")]
        reranked = apply_image_pixel_rerank(
            query,
            hits,
            config=_fixed_probe_config(
                image_pixel_rerank_top_n=1,
                image_pixel_rerank_time_window_sec=1.0,
            ),
            top_k=1,
        )
        self.assertEqual(reranked[0].start_sec, 54.5)

    @unittest.mock.patch("src.services.image_search_rerank.compute_dhash", return_value=123456)
    @unittest.mock.patch("src.services.image_search_rerank.get_single_thumbnail")
    def test_pixel_rerank_does_not_promote_unreranked_tail(self, mock_thumb, _mock_dhash):
        query = np.full((80, 80, 3), 128, dtype=np.uint8)
        bad_frame = np.zeros((80, 80, 3), dtype=np.uint8)
        mock_thumb.return_value = bad_frame

        hits = [
            SearchHit(1.0, 1.0, 0.95, "a.mp4"),
            SearchHit(2.0, 2.0, 0.94, "a.mp4"),
            SearchHit(99.0, 99.0, 0.50, "tail.mp4"),
        ]
        reranked = apply_image_pixel_rerank(
            query,
            hits,
            config=_fixed_probe_config(
                image_pixel_rerank_top_n=2,
                image_pixel_rerank_time_window_sec=0.0,
                image_pixel_rerank_min_similarity=0.99,
            ),
            top_k=2,
        )
        self.assertEqual(len(reranked), 2)
        self.assertTrue(all(hit.video_path != "tail.mp4" for hit in reranked))

    @unittest.mock.patch("src.services.image_search_rerank.get_single_thumbnail")
    def test_pixel_rerank_reuses_thumbnail_cache_for_overlapping_probes(self, mock_thumb):
        query = np.full((80, 80, 3), 128, dtype=np.uint8)
        query[30:50, 30:50] = (20, 180, 240)
        frame = query.copy()
        mock_thumb.return_value = frame

        hits = [
            SearchHit(10.0, 10.0, 0.92, "a.mp4"),
            SearchHit(10.5, 10.5, 0.90, "a.mp4"),
        ]
        apply_image_pixel_rerank(
            query,
            hits,
            config=_fixed_probe_config(
                image_pixel_rerank_top_n=2,
                image_pixel_rerank_time_window_sec=1.0,
            ),
            top_k=2,
        )

        self.assertGreater(mock_thumb.call_count, 0)
        self.assertLess(mock_thumb.call_count, 18)

    @unittest.mock.patch("src.services.image_search_rerank.compute_dhash")
    @unittest.mock.patch("src.services.image_search_rerank.get_single_thumbnail")
    def test_pixel_rerank_reuses_probe_dhash_cache(self, mock_thumb, mock_dhash):
        query = np.full((80, 80, 3), 128, dtype=np.uint8)
        query[30:50, 30:50] = (20, 180, 240)
        frame = query.copy()
        mock_thumb.return_value = frame
        mock_dhash.return_value = 123456

        hits = [
            SearchHit(10.0, 10.0, 0.92, "a.mp4"),
            SearchHit(10.5, 10.5, 0.90, "a.mp4"),
        ]
        apply_image_pixel_rerank(
            query,
            hits,
            config=_fixed_probe_config(
                image_pixel_rerank_top_n=2,
                image_pixel_rerank_time_window_sec=1.0,
            ),
            top_k=2,
        )

        self.assertGreater(mock_dhash.call_count, 0)
        self.assertLess(mock_dhash.call_count, 18)


class DynamicProbeTests(unittest.TestCase):
    def test_median_index_step_uses_timestamp_deltas(self):
        self.assertAlmostEqual(median_index_step([0.0, 1.0, 2.0, 3.0]), 1.0)

    def test_build_index_step_by_video(self):
        from src.services.search_scope import normalize_scope_path

        lookup = build_index_step_by_video(["a.mp4", "a.mp4", "b.mp4", "b.mp4"], [0.0, 2.0, 0.0, 4.0])
        self.assertAlmostEqual(lookup[normalize_scope_path("a.mp4")], 2.0)
        self.assertAlmostEqual(lookup[normalize_scope_path("b.mp4")], 4.0)

    def test_resolve_probe_params_follow_index(self):
        window, step = resolve_probe_params(1.0, {"image_pixel_rerank_probe_mode": "index"})
        self.assertAlmostEqual(window, 1.0)
        self.assertAlmostEqual(step, 0.5)
        self.assertLess(step, 1.0)

    def test_resolve_probe_params_sparse_index_uses_fine_step(self):
        window, step = resolve_probe_params(2.0, {"image_pixel_rerank_probe_mode": "index"})
        self.assertAlmostEqual(window, 2.0)
        self.assertAlmostEqual(step, 0.5)
        self.assertLess(step, 2.0)

    def test_point_hit_probe_window_reaches_sparse_neighbors(self):
        from src.services.search_scope import normalize_scope_path

        hit = SearchHit(3265.0, 3265.0, 0.91, "a.mp4")
        lookup = {normalize_scope_path("a.mp4"): 15.0}
        window, _step = _hit_probe_plan(hit, {"image_pixel_rerank_probe_mode": "index"}, lookup=lookup)
        self.assertGreaterEqual(window, 6.0)

    @unittest.mock.patch("src.services.image_search_rerank.get_single_thumbnail")
    def test_index_mode_uses_lookup_step(self, mock_thumb):
        from src.services.search_scope import normalize_scope_path

        query = np.full((80, 80, 3), 128, dtype=np.uint8)
        query[30:50, 30:50] = (20, 180, 240)
        frame = query.copy()
        mock_thumb.return_value = frame

        hits = [SearchHit(10.0, 10.0, 0.92, "a.mp4")]
        apply_image_pixel_rerank(
            query,
            hits,
            config={"image_pixel_rerank_probe_mode": "index", "image_pixel_rerank_top_n": 1},
            top_k=1,
            index_step_lookup={normalize_scope_path("a.mp4"): 1.0},
        )
        # point hit widens window to 3.0 with step=0.5 => center + (±0.5..±3.0) => 13 probes
        self.assertEqual(mock_thumb.call_count, 13)


class NeighborScoreCacheTests(unittest.TestCase):
    def test_neighbor_candidate_score_reuses_cached_dot(self):
        from src.services import search_service

        reconstruct_calls = {"count": 0}

        class DummyIndex:
            def reconstruct(self, idx):
                reconstruct_calls["count"] += 1
                vectors = {
                    1: np.array([1.0, 0.0], dtype=np.float32),
                    2: np.array([0.8, 0.2], dtype=np.float32),
                }
                return vectors[int(idx)]

        index = DummyIndex()
        query = np.array([1.0, 0.0], dtype=np.float32)
        vector_cache = {}
        score_cache = {}

        first = search_service._neighbor_candidate_score(query, index, 1, vector_cache, score_cache)
        second = search_service._neighbor_candidate_score(query, index, 1, vector_cache, score_cache)
        third = search_service._neighbor_candidate_score(query, index, 2, vector_cache, score_cache)

        self.assertAlmostEqual(first, 1.0)
        self.assertAlmostEqual(second, 1.0)
        self.assertAlmostEqual(third, 0.8)
        self.assertEqual(reconstruct_calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
