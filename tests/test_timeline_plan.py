"""Beat-grid expansion for agent timeline plans."""

from __future__ import annotations

import unittest

from src.services.timeline_plan import beat_duration_sec, expand_timeline_plan


class TimelinePlanTests(unittest.TestCase):
    def test_expands_a_short_pool_to_cover_the_song(self):
        beat = beat_duration_sec(bpm=83.4, beats_per_cut=2)
        self.assertAlmostEqual(beat, 60.0 / 83.4 * 2, places=6)
        items, meta = expand_timeline_plan(
            {
                "bpm": 83.4,
                "beats_per_cut": 2,
                "total_sec": 268.748,
                "shots": [
                    {"video_path": "D:/a.mp4", "start_sec": 10.0, "end_sec": 22.0},
                    {"video_path": "D:/b.mp4", "start_sec": 5.0, "end_sec": 8.0},
                ],
            },
            max_clips=256,
        )
        self.assertEqual(len(items), 187)
        self.assertAlmostEqual(meta["filled_sec"], 268.748, places=3)
        self.assertAlmostEqual(items[0]["end_sec"] - items[0]["start_sec"], beat, places=5)
        self.assertEqual(items[0]["video_path"], "D:/a.mp4")
        self.assertEqual(items[1]["video_path"], "D:/b.mp4")
        self.assertEqual(items[2]["video_path"], "D:/a.mp4")

    def test_fit_chunk_keeps_a_short_chunk_short(self):
        items, meta = expand_timeline_plan(
            {
                "bpm": 120.0,
                "beats_per_cut": 2,
                "total_sec": 3.0,
                "fit_chunk": True,
                "shots": [
                    {"video_path": "D:/short.mp4", "start_sec": 1.0, "end_sec": 2.0},
                    {"video_path": "D:/long.mp4", "start_sec": 4.0, "end_sec": 20.0},
                ],
            },
            max_clips=64,
        )
        # beat = 1.0s; short chunk becomes 1.0s (its full length), long uses beat.
        self.assertTrue(meta["fit_chunk"])
        self.assertAlmostEqual(items[0]["end_sec"] - items[0]["start_sec"], 1.0, places=5)
        self.assertAlmostEqual(items[1]["end_sec"] - items[1]["start_sec"], 1.0, places=5)
        self.assertAlmostEqual(meta["filled_sec"], 3.0, places=5)


if __name__ == "__main__":
    unittest.main()
