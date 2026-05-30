import unittest
import unittest.mock

import numpy as np

from src.core.frame_hash import compute_dhash, dhash_similarity
from src.domain.search_hit import SearchHit
from src.services.image_search_rerank import apply_image_pixel_rerank


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
            config={"image_pixel_rerank_top_n": 2, "image_pixel_rerank_time_window_sec": 0.0},
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
            config={"image_pixel_rerank_top_n": 1, "image_pixel_rerank_time_window_sec": 1.0},
            top_k=1,
        )
        self.assertEqual(reranked[0].start_sec, 54.5)


if __name__ == "__main__":
    unittest.main()
