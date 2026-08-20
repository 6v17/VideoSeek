import unittest

from src.core.subtitle_ocr.frame_sample import (
    crop_subtitle_rois,
    sample_times_across_timeline,
    sample_times_in_segment,
)
from src.core.subtitle_ocr.merge_cues import merge_ocr_observations
from src.services.subtitle_index_service import (
    SUBTITLE_SAMPLE_STRATEGY_TIMELINE,
    SUBTITLE_SAMPLE_STRATEGY_VAD,
    normalize_subtitle_sample_strategy,
    resolve_subtitle_frame_budget,
    resolve_subtitle_sample_strategy,
)


class SubtitleOcrHelpersTests(unittest.TestCase):
    def test_sample_strategy_normalize(self):
        self.assertEqual(normalize_subtitle_sample_strategy("vad"), SUBTITLE_SAMPLE_STRATEGY_VAD)
        self.assertEqual(normalize_subtitle_sample_strategy("speech"), SUBTITLE_SAMPLE_STRATEGY_VAD)
        self.assertEqual(normalize_subtitle_sample_strategy("timeline"), SUBTITLE_SAMPLE_STRATEGY_TIMELINE)
        self.assertEqual(normalize_subtitle_sample_strategy("pv"), SUBTITLE_SAMPLE_STRATEGY_TIMELINE)
        self.assertEqual(normalize_subtitle_sample_strategy(""), SUBTITLE_SAMPLE_STRATEGY_TIMELINE)

    def test_sample_strategy_resolve_explicit_and_config(self):
        self.assertEqual(
            resolve_subtitle_sample_strategy(explicit="vad"),
            SUBTITLE_SAMPLE_STRATEGY_VAD,
        )
        self.assertEqual(
            resolve_subtitle_sample_strategy(config={"subtitle_sample_strategy": "vad"}),
            SUBTITLE_SAMPLE_STRATEGY_VAD,
        )
        self.assertEqual(
            resolve_subtitle_sample_strategy(config={"subtitle_sample_strategy": "timeline"}),
            SUBTITLE_SAMPLE_STRATEGY_TIMELINE,
        )

    def test_sample_times_respects_max_frames(self):
        times = sample_times_in_segment(0.0, 20.0, interval_sec=0.5, max_frames=4)
        self.assertLessEqual(len(times), 4)
        self.assertGreaterEqual(times[0], 0.0)

    def test_sample_times_unlimited_follows_interval(self):
        times = sample_times_in_segment(0.0, 8.0, interval_sec=0.8, max_frames=0)
        self.assertGreaterEqual(len(times), 9)
        self.assertLessEqual(times[-1], 8.0)

    def test_sample_times_allows_fine_interval(self):
        times = sample_times_in_segment(0.0, 1.2, interval_sec=0.1, max_frames=0)
        self.assertGreaterEqual(len(times), 5)

    def test_timeline_sampling_covers_duration(self):
        times = sample_times_across_timeline(30.0, interval_sec=2.0, max_frames=100)
        self.assertGreaterEqual(len(times), 2)
        self.assertLessEqual(times[-1], 30.0)
        self.assertLessEqual(len(times), 16)

    def test_frame_budget_scales_with_duration(self):
        short = resolve_subtitle_frame_budget(60.0, sample_interval_sec=0.8)
        long = resolve_subtitle_frame_budget(600.0, sample_interval_sec=0.8)
        self.assertGreater(long, short)
        self.assertGreaterEqual(short, 40)
        # ~600/0.8 ≈ 750, plus headroom — should be near that, not a flat 500.
        self.assertGreaterEqual(long, 700)

    def test_frame_budget_optional_ceiling(self):
        capped = resolve_subtitle_frame_budget(
            600.0,
            sample_interval_sec=0.8,
            max_total_frames=200,
        )
        self.assertEqual(capped, 200)

    def test_merge_collapses_same_text(self):
        merged = merge_ocr_observations(
            [
                {"start": 1.0, "end": 1.5, "text": "你好"},
                {"start": 1.6, "end": 2.0, "text": "你好"},
                {"start": 5.0, "end": 5.5, "text": "世界"},
            ]
        )
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["text"], "你好")
        self.assertAlmostEqual(merged[0]["end"], 2.0)
        self.assertEqual(merged[1]["text"], "世界")

    def test_crop_rois_bottom_only_by_default(self):
        import numpy as np

        frame = np.zeros((1000, 800, 3), dtype=np.uint8)
        bands = crop_subtitle_rois(frame, include_top=False)
        self.assertEqual([b for b, _ in bands], ["bottom"])
        self.assertEqual(bands[0][1].shape[0], 400)  # lower 40%

    def test_crop_rois_includes_top_band(self):
        import numpy as np

        frame = np.zeros((1000, 800, 3), dtype=np.uint8)
        bands = crop_subtitle_rois(frame, include_top=True, top_ratio=0.20, bottom_ratio=0.40)
        self.assertEqual([b for b, _ in bands], ["top", "bottom"])
        self.assertEqual(bands[0][1].shape[0], 200)
        # Top band drops 20% left + 20% right (middle 60%).
        self.assertEqual(bands[0][1].shape[1], 480)
        self.assertEqual(bands[1][1].shape[0], 400)
        self.assertEqual(bands[1][1].shape[1], 800)


if __name__ == "__main__":
    unittest.main()
