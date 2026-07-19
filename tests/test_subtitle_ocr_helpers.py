import unittest

from src.core.subtitle_ocr.frame_sample import sample_times_across_timeline, sample_times_in_segment
from src.core.subtitle_ocr.merge_cues import merge_ocr_observations
from src.services.subtitle_index_service import resolve_subtitle_frame_budget


class SubtitleOcrHelpersTests(unittest.TestCase):
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

    def test_frame_budget_scales_with_speech_duration(self):
        short = resolve_subtitle_frame_budget(60.0, sample_interval_sec=0.8, segment_count=5)
        long = resolve_subtitle_frame_budget(600.0, sample_interval_sec=0.8, segment_count=20)
        self.assertGreater(long, short)
        self.assertGreaterEqual(short, 40)
        # ~600/0.8 ≈ 750, plus headroom — should be near that, not a flat 500.
        self.assertGreaterEqual(long, 700)

    def test_frame_budget_optional_ceiling(self):
        capped = resolve_subtitle_frame_budget(
            600.0,
            sample_interval_sec=0.8,
            segment_count=20,
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


if __name__ == "__main__":
    unittest.main()
