"""Placement rules for a timeline music bed."""

from __future__ import annotations

import os
import tempfile
import unittest

from src.services.timeline_audio import place_timeline_audio


class TimelineAudioTests(unittest.TestCase):
    def test_music_stops_at_the_end_of_the_cut(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bed.mp3")
            with open(path, "wb") as handle:
                handle.write(b"fake")
            placed = place_timeline_audio(
                {"path": path, "volume": 1, "fade_out_sec": 2, "duration_sec": 180},
                timeline_duration_sec=60.4,
            )
        self.assertEqual(placed["start_sec"], 0.0)
        self.assertAlmostEqual(placed["duration_sec"], 60.4)
        self.assertEqual(placed["fade_out_sec"], 2.0)

    def test_short_file_ends_when_the_file_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bed.mp3")
            with open(path, "wb") as handle:
                handle.write(b"fake")
            placed = place_timeline_audio(
                {"path": path, "start_sec": 4, "fade_out_sec": 9, "duration_sec": 3},
                timeline_duration_sec=20,
            )
        self.assertEqual(placed["start_sec"], 4.0)
        self.assertEqual(placed["duration_sec"], 3.0)
        self.assertEqual(placed["fade_out_sec"], 3.0)

    def test_missing_file_is_an_error(self):
        with self.assertRaises(ValueError):
            place_timeline_audio(
                {"path": "D:/no/such/bed.mp3", "duration_sec": 10},
                timeline_duration_sec=5,
            )


if __name__ == "__main__":
    unittest.main()
