import unittest

from src.app.config import DEFAULT_CONFIG, _sanitize_general_settings
from src.services.image_search_rerank import (
    _image_pixel_rerank_top_n,
    resolve_probe_params,
)
from src.services.search_service import _neighbor_rerank_enabled, _resolve_frame_fetch_top_k


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
        self.assertGreaterEqual(fetch_k, 60)
        self.assertEqual(
            _resolve_frame_fetch_top_k(20, scoped=False, is_text=False, config=config, precise_image=False),
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

    def test_neighbor_rerank_auto_enabled_for_precise_image(self):
        config = dict(DEFAULT_CONFIG)
        config["frame_neighbor_rerank_enabled"] = False
        self.assertTrue(
            _neighbor_rerank_enabled(config, is_text=False, precise_image=True)
        )


if __name__ == "__main__":
    unittest.main()
