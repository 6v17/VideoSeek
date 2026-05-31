import unittest

from src.app.config import DEFAULT_CONFIG, _sanitize_general_settings
from src.services.image_search_rerank import (
    _image_pixel_rerank_top_n,
    resolve_probe_params,
)
from src.services.search_scope import resolve_per_video_fetch_top_k
from src.services.search_service import (
    _aggregate_hits_to_video_discovery,
    _apply_video_discovery_presentation,
    _cap_hits_per_video,
    _locate_frames_in_recalled_videos,
    _neighbor_rerank_enabled,
    _precise_pixel_localize_top_n,
    _resolve_frame_fetch_top_k,
    _resolve_stage1_global_fetch_k,
    _top_video_paths_from_hits,
    _use_video_discovery_results,
)
from src.domain.search_hit import SearchHit


class PreciseSearchSettingsWiringTests(unittest.TestCase):
    def test_sanitize_preserves_precise_search_keys(self):
        raw = {
            **DEFAULT_CONFIG,
            "image_pixel_rerank_top_n": 12,
            "image_pixel_rerank_probe_mode": "fixed",
            "image_pixel_rerank_time_window_sec": 1.5,
            "image_pixel_rerank_probe_step_sec": 0.4,
            "image_search_fetch_multiplier": 2,
            "frame_neighbor_rerank_enabled": True,
            "frame_neighbor_rerank_top_n": 8,
            "frame_neighbor_rerank_window": 3,
        }
        sanitized = _sanitize_general_settings(raw)
        self.assertEqual(sanitized["image_pixel_rerank_top_n"], 12)
        self.assertEqual(sanitized["image_pixel_rerank_probe_mode"], "fixed")
        self.assertAlmostEqual(sanitized["image_pixel_rerank_time_window_sec"], 1.5)
        self.assertAlmostEqual(sanitized["image_pixel_rerank_probe_step_sec"], 0.4)
        self.assertEqual(sanitized["image_search_fetch_multiplier"], 2)
        self.assertEqual(sanitized["frame_neighbor_rerank_top_n"], 8)

    def test_fetch_multiplier_expands_precise_recall(self):
        config = dict(DEFAULT_CONFIG)
        config["image_search_fetch_multiplier"] = 3
        fetch_k = _resolve_frame_fetch_top_k(20, scoped=False, is_text=False, config=config, precise_image=True)
        self.assertGreaterEqual(fetch_k, 100)
        self.assertLessEqual(fetch_k, 200)
        self.assertEqual(
            _resolve_frame_fetch_top_k(20, scoped=False, is_text=False, config=config, precise_image=False),
            20,
        )
        self.assertEqual(
            _resolve_frame_fetch_top_k(20, scoped=False, is_text=True, config=config, precise_image=False),
            20,
        )

    def test_pixel_top_n_read_from_config(self):
        config = {"image_pixel_rerank_top_n": 12}
        self.assertEqual(_image_pixel_rerank_top_n(config, 30), 12)

    def test_fixed_probe_mode_uses_manual_window_and_step(self):
        config = {
            "image_pixel_rerank_probe_mode": "fixed",
            "image_pixel_rerank_time_window_sec": 1.5,
            "image_pixel_rerank_probe_step_sec": 0.4,
        }
        window, step = resolve_probe_params(2.0, config)
        self.assertAlmostEqual(window, 1.5)
        self.assertAlmostEqual(step, 0.4)

    def test_index_probe_mode_derives_from_index_step(self):
        config = {"image_pixel_rerank_probe_mode": "index"}
        window, step = resolve_probe_params(1.0, config)
        self.assertAlmostEqual(window, 1.0)
        self.assertAlmostEqual(step, 0.5)
        self.assertLess(step, 1.0)

    def test_neighbor_rerank_only_when_explicitly_enabled(self):
        config = dict(DEFAULT_CONFIG)
        config["frame_neighbor_rerank_enabled"] = False
        self.assertTrue(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=True)
        )
        self.assertFalse(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=False)
        )
        config["frame_neighbor_rerank_enabled"] = True
        self.assertTrue(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=False)
        )

    def test_top_video_paths_from_hits_prefers_best_score(self):
        hits = [
            SearchHit(1.0, 1.0, 0.7, "D:/a.mp4"),
            SearchHit(2.0, 2.0, 0.95, "D:/b.mp4"),
            SearchHit(3.0, 3.0, 0.8, "D:/a.mp4"),
        ]
        ordered = _top_video_paths_from_hits(hits, 2)
        self.assertEqual(ordered[0], "D:/b.mp4")
        self.assertIn("D:/a.mp4", ordered)

    def test_cap_hits_per_video_limits_each_video(self):
        hits = [
            SearchHit(1.0, 1.0, 0.9, "D:/a.mp4"),
            SearchHit(2.0, 2.0, 0.8, "D:/a.mp4"),
            SearchHit(3.0, 3.0, 0.95, "D:/b.mp4"),
            SearchHit(4.0, 4.0, 0.7, "D:/b.mp4"),
        ]
        capped = _cap_hits_per_video(hits, 1)
        self.assertEqual(len(capped), 2)
        self.assertEqual(capped[0].video_path, "D:/b.mp4")
        self.assertEqual(capped[1].video_path, "D:/a.mp4")

    def test_stage1_global_fetch_expands_for_video_recall(self):
        config = dict(DEFAULT_CONFIG)
        config["image_search_fetch_multiplier"] = 3
        fetch_k = _resolve_stage1_global_fetch_k(50, config)
        self.assertGreaterEqual(fetch_k, 200)
        self.assertLessEqual(fetch_k, 400)

    def test_video_discovery_mode_only_for_global_fast_image(self):
        self.assertTrue(_use_video_discovery_results(is_text=False, precise_image=False, scoped=False))
        self.assertFalse(_use_video_discovery_results(is_text=False, precise_image=True, scoped=False))
        self.assertFalse(_use_video_discovery_results(is_text=False, precise_image=False, scoped=True))
        self.assertFalse(_use_video_discovery_results(is_text=True, precise_image=False, scoped=False))

    def test_aggregate_hits_to_video_discovery_marks_video_kind(self):
        hits = [
            SearchHit(10.0, 10.0, 0.7, "D:/a.mp4"),
            SearchHit(20.0, 20.0, 0.95, "D:/b.mp4"),
            SearchHit(30.0, 30.0, 0.8, "D:/a.mp4"),
        ]
        aggregated = _aggregate_hits_to_video_discovery(hits, 2)
        self.assertEqual(len(aggregated), 2)
        self.assertEqual(aggregated[0].video_path, "D:/b.mp4")
        self.assertEqual(aggregated[0].match_kind, "video")
        self.assertAlmostEqual(float(aggregated[0].start_sec), 20.0)

    def test_apply_video_discovery_presentation_caps_per_video(self):
        hits = [
            SearchHit(float(i), float(i), 0.99 - i * 0.01, "D:/a.mp4")
            for i in range(6)
        ] + [SearchHit(50.0, 50.0, 0.95, "D:/b.mp4")]
        presented = _apply_video_discovery_presentation(hits, 2, enabled=True)
        self.assertEqual(len(presented), 2)
        self.assertEqual({hit.video_path for hit in presented}, {"D:/a.mp4", "D:/b.mp4"})
        self.assertTrue(all(hit.match_kind == "video" for hit in presented))

    def test_single_video_per_video_fetch_expands(self):
        self.assertGreaterEqual(resolve_per_video_fetch_top_k(50, 1), 200)

    def test_in_video_pixel_localize_uses_larger_pool(self):
        config = dict(DEFAULT_CONFIG)
        config["image_pixel_rerank_top_n"] = 12
        single_video_hits = [SearchHit(float(i), float(i), 0.9 - i * 0.01, "D:/a.mp4") for i in range(20)]
        multi_video_hits = single_video_hits + [SearchHit(1.0, 1.0, 0.5, "D:/b.mp4")]
        self.assertEqual(_precise_pixel_localize_top_n(config, single_video_hits), 12)
        self.assertEqual(_precise_pixel_localize_top_n(config, multi_video_hits), 3)


if __name__ == "__main__":
    unittest.main()
