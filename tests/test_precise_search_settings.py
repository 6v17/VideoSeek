import unittest
from unittest import mock

from src.app.config import DEFAULT_CONFIG, _sanitize_general_settings
from src.services.image_search_rerank import (
    _image_pixel_rerank_top_n,
    is_likely_cropped_query_image,
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
    _refine_precise_seed_hits,
    _resolve_frame_fetch_top_k,
    _resolve_locate_result_top_k,
    _resolve_stage1_global_fetch_k,
    format_clip_score_percent,
    locate_crop_confidence_warning_key,
    resolve_clip_confidence_tier_key,
    _apply_locate_crop_anchor_stability,
    _search_frame_results_in_time_window,
    _search_locate_anchor_window_hits,
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
        self.assertAlmostEqual(step, 0.25)
        self.assertLess(step, 1.0)

    def test_neighbor_rerank_only_when_explicitly_enabled(self):
        config = dict(DEFAULT_CONFIG)
        config["frame_neighbor_rerank_enabled"] = False
        self.assertFalse(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=True)
        )
        self.assertFalse(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=False)
        )
        config["frame_neighbor_rerank_enabled"] = True
        self.assertFalse(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=True)
        )
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

    @mock.patch("src.services.search_service._top_video_paths_from_hits", return_value=["D:/runner-up.mp4"])
    @mock.patch("src.services.search_service._apply_frame_neighbor_rerank", side_effect=lambda results, *_args, **_kwargs: results)
    @mock.patch("src.services.search_service._search_frame_results_with_ids")
    @mock.patch("src.services.search_service._load_per_video_frame_assets")
    @mock.patch("src.services.search_service._resolve_scoped_video_targets")
    def test_locate_frames_preserves_stage1_hits_outside_candidates(
        self,
        mock_resolve_targets,
        mock_load_assets,
        mock_search_with_ids,
        _mock_neighbor,
        _mock_top_videos,
    ):
        import numpy as np

        stage1_hits = [
            SearchHit(10.0, 10.0, 0.99, "D:/winner.mp4"),
            SearchHit(20.0, 20.0, 0.95, "D:/runner-up.mp4"),
            SearchHit(30.0, 30.0, 0.50, "D:/outside-top20.mp4"),
        ]
        mock_resolve_targets.return_value = [("D:/runner-up.mp4", "vid-b")]
        mock_load_assets.return_value = (
            object(),
            np.array([20.0], dtype=np.float32),
            np.array(["D:/runner-up.mp4"], dtype=object),
            None,
        )
        mock_search_with_ids.return_value = (
            [SearchHit(21.0, 21.0, 0.97, "D:/runner-up.mp4")],
            [0],
        )

        located = _locate_frames_in_recalled_videos(
            np.array([[1.0, 0.0]], dtype=np.float32),
            stage1_hits,
            {},
        )

        paths = {hit.video_path for hit in located}
        self.assertIn("D:/runner-up.mp4", paths)
        self.assertIn("D:/outside-top20.mp4", paths)
        self.assertIn("D:/winner.mp4", paths)
        refined = next(hit for hit in located if hit.video_path == "D:/runner-up.mp4")
        self.assertAlmostEqual(float(refined.start_sec), 21.0)

    @mock.patch("src.services.search_service._top_video_paths_from_hits", return_value=["D:/a.mp4"])
    @mock.patch("src.services.search_service._apply_frame_neighbor_rerank", side_effect=lambda results, *_args, **_kwargs: results)
    @mock.patch("src.services.search_service._search_frame_results_with_ids")
    @mock.patch("src.services.search_service._load_per_video_frame_assets")
    @mock.patch("src.services.search_service._resolve_scoped_video_targets")
    def test_locate_frames_keeps_stage1_seed_when_stage2_prefers_other_times(
        self,
        mock_resolve_targets,
        mock_load_assets,
        mock_search_with_ids,
        _mock_neighbor,
        _mock_top_videos,
    ):
        import numpy as np

        stage1_hits = [SearchHit(64.0, 64.0, 0.99, "D:/a.mp4")]
        mock_resolve_targets.return_value = [("D:/a.mp4", "vid-a")]
        mock_load_assets.return_value = (
            object(),
            np.array([64.0, 200.0], dtype=np.float32),
            np.array(["D:/a.mp4", "D:/a.mp4"], dtype=object),
            None,
        )
        mock_search_with_ids.return_value = (
            [SearchHit(200.0, 200.0, 0.97, "D:/a.mp4")],
            [1],
        )

        located = _locate_frames_in_recalled_videos(
            np.array([[1.0, 0.0]], dtype=np.float32),
            stage1_hits,
            {},
        )

        anchor_hit = next(hit for hit in located if abs(float(hit.start_sec) - 64.0) < 0.01)
        self.assertAlmostEqual(float(anchor_hit.score), 0.99)

    def test_filter_scope_preserves_clip_seeds(self):
        hits = [
            SearchHit(64.0, 64.0, 0.99, "D:/a.mp4"),
            SearchHit(200.0, 200.0, 0.5, "D:/b.mp4"),
        ]
        seeds = [64.0, 200.0]
        from src.services.search_service import _scope_filter_hits_with_seeds

        scoped, scoped_seeds = _scope_filter_hits_with_seeds(
            hits,
            seeds,
            video_paths=["D:/a.mp4"],
        )
        self.assertEqual(len(scoped), 1)
        self.assertAlmostEqual(scoped_seeds[0], 64.0)

    def test_search_frame_results_in_time_window_limits_to_anchor_region(self):
        import numpy as np

        class DummyIndex:
            d = 2
            ntotal = 3

            def reconstruct(self, idx):
                vectors = {
                    0: np.array([1.0, 0.0], dtype=np.float32),
                    1: np.array([0.2, 0.9], dtype=np.float32),
                    2: np.array([0.9, 0.1], dtype=np.float32),
                }
                return vectors[int(idx)]

        timestamps = np.array([60.0, 64.0, 200.0], dtype=np.float32)
        paths = np.array(["D:/a.mp4", "D:/a.mp4", "D:/a.mp4"], dtype=object)
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)

        hits, ids = _search_frame_results_in_time_window(
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            center_sec=64.0,
            window_sec=10.0,
            top_k=5,
        )

        self.assertEqual(ids, [0, 1])
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(abs(float(hit.start_sec) - 64.0) <= 10.0 for hit in hits))

    def test_search_frame_results_in_time_window_prefers_high_scores_when_truncating(self):
        import numpy as np

        class DummyIndex:
            d = 2
            ntotal = 60

            def reconstruct(self, idx):
                if int(idx) == 25:
                    return np.array([1.0, 0.0], dtype=np.float32)
                return np.array([0.1, 0.9], dtype=np.float32)

        timestamps = np.array([float(34 + idx) for idx in range(60)], dtype=np.float32)
        paths = np.array(["D:/a.mp4"] * 60, dtype=object)
        query_vector = np.array([[1.0, 0.0]], dtype=np.float32)

        hits, ids = _search_frame_results_in_time_window(
            query_vector,
            DummyIndex(),
            timestamps,
            paths,
            center_sec=64.0,
            window_sec=30.0,
            top_k=1,
        )

        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(float(hits[0].start_sec), 59.0)
        self.assertIn(25, ids)

    @mock.patch("src.services.search_service.load_search_assets")
    @mock.patch("src.services.search_service._search_frame_results_in_time_window")
    def test_search_locate_anchor_window_prefers_per_video_index(self, mock_window, mock_load_assets):
        import numpy as np

        mock_window.return_value = ([SearchHit(64.0, 64.0, 0.91, "D:/a.mp4")], [0])

        hits = _search_locate_anchor_window_hits(
            np.array([[1.0, 0.0]], dtype=np.float32),
            "D:/a.mp4",
            64.0,
            20,
            {},
            per_video_index=object(),
            per_video_timestamps=np.array([64.0]),
            per_video_paths=np.array(["D:/a.mp4"], dtype=object),
        )

        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(float(hits[0].start_sec), 64.0)
        mock_window.assert_called_once()
        mock_load_assets.assert_not_called()

    @mock.patch("src.services.search_service._apply_bounded_neighbor_refine", side_effect=lambda hits, *_args, **_kwargs: hits)
    @mock.patch("src.services.search_service._search_frame_results_with_ids")
    @mock.patch("src.services.search_service.load_search_assets")
    def test_search_locate_anchor_window_uses_global_hits(self, mock_load_assets, mock_search_with_ids, _mock_neighbor):
        import numpy as np

        class DummyIndex:
            ntotal = 2

        mock_load_assets.return_value = (
            DummyIndex(),
            np.array([64.0, 200.0], dtype=np.float32),
            np.array(["D:/a.mp4", "D:/a.mp4"], dtype=object),
        )
        mock_search_with_ids.return_value = (
            [
                SearchHit(64.0, 64.0, 0.99, "D:/a.mp4"),
                SearchHit(200.0, 200.0, 0.95, "D:/b.mp4"),
            ],
            [0, 1],
        )

        hits = _search_locate_anchor_window_hits(
            np.array([[1.0, 0.0]], dtype=np.float32),
            "D:/a.mp4",
            64.0,
            20,
            {},
        )

        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(float(hits[0].start_sec), 64.0)
        mock_search_with_ids.assert_called_once()

    @mock.patch("src.services.search_service.apply_image_pixel_rerank")
    @mock.patch("src.services.search_service.is_likely_cropped_query_image", return_value=False)
    def test_refine_locate_pixels_only_top_three(self, _mock_crop, mock_pixel):
        hits = [
            SearchHit(float(idx), float(idx), 0.9 - idx * 0.01, "D:/a.mp4")
            for idx in range(5)
        ]
        mock_pixel.return_value = hits[:3]

        refined = _refine_precise_seed_hits(
            object(),
            hits,
            20,
            {},
            locate_anchor_sec=64.0,
        )

        self.assertEqual(len(refined), 5)
        mock_pixel.assert_called_once()
        passed_hits = mock_pixel.call_args.args[1]
        self.assertEqual(len(passed_hits), 3)

    @mock.patch("src.services.search_service.apply_image_pixel_rerank")
    @mock.patch("src.services.search_service.is_likely_cropped_query_image", return_value=True)
    def test_refine_locate_skips_pixel_for_cropped_query(self, _mock_crop, mock_pixel):
        hits = [SearchHit(64.0, 64.0, 0.99, "D:/a.mp4")]

        refined = _refine_precise_seed_hits(
            object(),
            hits,
            20,
            {},
            locate_anchor_sec=64.0,
        )

        self.assertEqual(len(refined), 1)
        self.assertAlmostEqual(float(refined[0].start_sec), 64.0)
        mock_pixel.assert_not_called()

    def test_resolve_locate_result_top_k_caps_to_three(self):
        self.assertEqual(_resolve_locate_result_top_k(20), 3)
        self.assertEqual(_resolve_locate_result_top_k(20, crop_query=True), 1)
        self.assertEqual(_resolve_locate_result_top_k(1), 1)

    @mock.patch("src.services.search_service._search_frame_results_in_time_window")
    @mock.patch("src.services.search_service.load_search_assets", return_value=(None, None, None))
    def test_search_locate_crop_trusted_uses_narrow_window(self, _mock_load, mock_window):
        import numpy as np

        mock_window.return_value = ([SearchHit(64.0, 64.0, 0.91, "D:/a.mp4")], [0])
        from src.services.search_service import _search_locate_crop_trusted_hits

        hits = _search_locate_crop_trusted_hits(
            np.array([[1.0, 0.0]], dtype=np.float32),
            "D:/a.mp4",
            64.0,
            {},
            per_video_index=object(),
            per_video_timestamps=np.array([64.0]),
            per_video_paths=np.array(["D:/a.mp4"], dtype=object),
        )

        self.assertEqual(len(hits), 1)
        mock_window.assert_called_once()
        self.assertAlmostEqual(float(mock_window.call_args.kwargs["window_sec"]), 5.0)
        self.assertEqual(int(mock_window.call_args.kwargs["top_k"]), 12)

    @mock.patch("src.services.search_service.apply_image_pixel_rerank")
    def test_refine_precise_skips_pixel_for_cropped_query(self, mock_pixel):
        import numpy as np

        hits = [SearchHit(10.0, 10.0, 0.9, "D:/a.mp4")]

        refined = _refine_precise_seed_hits(
            np.zeros((360, 640, 3), dtype=np.uint8),
            hits,
            5,
            {},
        )

        self.assertEqual(len(refined), 1)
        mock_pixel.assert_not_called()

    def test_emit_search_progress_invokes_callback(self):
        from src.services.search_progress import clear_search_progress_callback, emit_search_progress, set_search_progress_callback

        seen = []

        def _capture(phase, message=""):
            seen.append((phase, message))

        set_search_progress_callback(_capture)
        try:
            emit_search_progress("locate_progress_clip")
            emit_search_progress("locate_progress_pixel", "locate_progress_pixel")
        finally:
            clear_search_progress_callback()

        self.assertEqual(seen[0], ("locate_progress_clip", ""))
        self.assertEqual(seen[1], ("locate_progress_pixel", "locate_progress_pixel"))

    def test_format_clip_score_percent(self):
        self.assertEqual(format_clip_score_percent(0.623), "62.3%")
        self.assertEqual(format_clip_score_percent(1.0), "100%")
        self.assertEqual(format_clip_score_percent(0.05), "5.00%")

    def test_locate_crop_confidence_warning_key(self):
        import numpy as np

        crop = np.zeros((200, 400, 3), dtype=np.uint8)
        self.assertEqual(
            locate_crop_confidence_warning_key(
                [SearchHit(64.0, 64.0, 0.5, "D:/a.mp4")],
                crop,
                preview_anchor_sec=64.0,
            ),
            "locate_crop_low_confidence",
        )
        self.assertIsNone(
            locate_crop_confidence_warning_key(
                [SearchHit(64.0, 64.0, 0.7, "D:/a.mp4")],
                crop,
                preview_anchor_sec=64.0,
            ),
        )
        self.assertIsNone(
            locate_crop_confidence_warning_key(
                [SearchHit(64.0, 64.0, 0.5, "D:/a.mp4")],
                crop,
                preview_anchor_sec=None,
            ),
        )

    def test_resolve_clip_confidence_tier_key(self):
        self.assertEqual(resolve_clip_confidence_tier_key(0.90), "clip_confidence_very_high")
        self.assertEqual(resolve_clip_confidence_tier_key(0.80), "clip_confidence_high")
        self.assertEqual(resolve_clip_confidence_tier_key(0.65), "clip_confidence_medium")
        self.assertEqual(resolve_clip_confidence_tier_key(0.50), "clip_confidence_low")

    def test_apply_locate_crop_anchor_stability_keeps_preview_anchor(self):
        hits = [
            SearchHit(67.0, 67.0, 0.74, "D:/a.mp4"),
            SearchHit(64.5, 64.5, 0.72, "D:/a.mp4"),
        ]
        stable = _apply_locate_crop_anchor_stability(hits, 64.0, "D:/a.mp4")
        self.assertEqual(len(stable), 1)
        self.assertAlmostEqual(float(stable[0].start_sec), 64.0)
        self.assertAlmostEqual(float(stable[0].score), 0.72)

    def test_apply_locate_crop_anchor_stability_moves_on_large_gain(self):
        hits = [
            SearchHit(67.0, 67.0, 0.82, "D:/a.mp4"),
            SearchHit(64.5, 64.5, 0.70, "D:/a.mp4"),
        ]
        stable = _apply_locate_crop_anchor_stability(hits, 64.0, "D:/a.mp4")
        self.assertAlmostEqual(float(stable[0].start_sec), 67.0)
        self.assertAlmostEqual(float(stable[0].score), 0.82)


if __name__ == "__main__":
    unittest.main()
