"""Portrait indexing drops large static bars and keeps the moving middle."""

from __future__ import annotations

import unittest

import numpy as np

from src.core.portrait_content_band import content_band_fractions, crop_filter_from_fractions


def _bars(seed: int, *, height=320, width=180, top=100, bottom=220) -> np.ndarray:
    rng = np.random.default_rng(seed)
    frame = np.full((height, width, 3), 28, np.uint8)
    frame[top:bottom] = rng.integers(0, 255, size=(bottom - top, width, 3), dtype=np.uint8)
    return frame


class PortraitContentBandTests(unittest.TestCase):
    def test_large_static_bars_leave_the_moving_middle(self):
        frames = [_bars(seed) for seed in (1, 2, 3, 4)]
        band = content_band_fractions(frames)
        self.assertIsNotNone(band)
        y0, y1 = band
        self.assertAlmostEqual(y0, 100 / 320, delta=0.04)
        self.assertAlmostEqual(y1, 220 / 320, delta=0.04)
        filt = crop_filter_from_fractions(180, 320, y0, y1)
        self.assertTrue(filt.startswith("crop="))
        self.assertIn(":0:", filt)

    def test_a_still_title_card_stays_whole(self):
        frame = _bars(1)
        self.assertIsNone(content_band_fractions([frame, frame.copy(), frame.copy()]))

    def test_thin_bars_stay_whole(self):
        frames = [_bars(seed, top=8, bottom=312) for seed in (1, 2, 3)]
        self.assertIsNone(content_band_fractions(frames))

    def test_a_bar_on_only_one_side_stays_whole(self):
        frames = [_bars(seed, top=80, bottom=320) for seed in (1, 2, 3)]
        self.assertIsNone(content_band_fractions(frames))

    def test_landscape_stays_whole(self):
        frames = [_bars(seed, height=180, width=320, top=40, bottom=140) for seed in (1, 2, 3)]
        self.assertIsNone(content_band_fractions(frames))


if __name__ == "__main__":
    unittest.main()
