"""Tests for responsive search layout helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import QSize

from ui.widgets import layout as layout_mod
from ui.widgets.layout import (
    compare_row_card_height,
    compare_row_idle_min_height,
    compare_row_min_height,
    compute_search_query_tabs_height,
    fit_splitter_pair,
    image_drop_min_height,
    result_table_min_height,
    search_panel_min_height,
)


class LayoutResponsiveTests(unittest.TestCase):
    def test_image_drop_shrinks_on_short_viewport(self):
        preferred = layout_mod.COMPONENT_SIZES["image_drop_min_height"]
        floor = layout_mod.COMPONENT_SIZES["image_drop_min_height_floor"]
        self.assertEqual(image_drop_min_height(viewport_height=900), preferred)
        self.assertLess(image_drop_min_height(viewport_height=700), preferred)
        self.assertEqual(image_drop_min_height(viewport_height=500), floor)

    def test_search_panel_min_shrinks_with_viewport(self):
        tall = search_panel_min_height(viewport_height=900)
        short = search_panel_min_height(viewport_height=640)
        self.assertGreater(tall, short)
        # Option-row chrome stays; only the tab/drop body compresses.
        self.assertGreaterEqual(short, compute_search_query_tabs_height(viewport_height=640) + 120)

    def test_compare_row_min_shrinks_on_short_screen(self):
        preferred = compare_row_card_height()
        content = search_panel_min_height(viewport_height=650)
        with patch.object(layout_mod, "_available_height", return_value=650):
            # Short screens keep the adaptive query-card floor (no crushed rows).
            self.assertEqual(compare_row_min_height(), content)
        with patch.object(layout_mod, "_available_height", return_value=950):
            content_tall = search_panel_min_height(viewport_height=950)
            soft_cap = max(
                layout_mod.COMPONENT_SIZES["compare_row_min_height_cap"],
                content_tall,
            )
            expected = min(
                max(preferred, content_tall),
                soft_cap,
                950 - 120 - layout_mod.COMPONENT_SIZES["result_table_min_height_floor"],
            )
            self.assertEqual(compare_row_min_height(), expected)

    def test_compare_row_idle_min_is_below_preferred_card(self):
        idle = compare_row_idle_min_height(viewport_height=900)
        preferred = compare_row_card_height()
        self.assertEqual(idle, search_panel_min_height(viewport_height=900))
        self.assertLess(idle, preferred)
        self.assertGreaterEqual(idle, 200)
        self.assertLessEqual(idle, preferred - 40)

    def test_search_panel_min_fits_option_rows(self):
        # Scope/mobile + mode + search button must not crush into each other.
        self.assertGreaterEqual(
            search_panel_min_height(viewport_height=900),
            compute_search_query_tabs_height(viewport_height=900) + 120,
        )

    def test_compare_row_min_reserves_results_budget(self):
        with patch.object(layout_mod, "_available_height", return_value=744):
            top = compare_row_min_height()
            results_floor = layout_mod.COMPONENT_SIZES["result_table_min_height_floor"]
            self.assertLessEqual(top + 120 + results_floor, 744)
            self.assertGreaterEqual(top, search_panel_min_height(viewport_height=744))
            self.assertLess(
                layout_mod.COMPONENT_SIZES["image_drop_min_height"],
                280,
                "image drop should be smaller so query card fits with results",
            )

    def test_result_table_min_shrinks_on_short_screen(self):
        with patch.object(layout_mod, "_available_height", return_value=650):
            self.assertEqual(result_table_min_height(), 180)
        with patch.object(layout_mod, "_available_height", return_value=950):
            self.assertEqual(result_table_min_height(), 420)

    def test_fit_splitter_pair_discards_when_below_min(self):
        sizes = fit_splitter_pair(
            700,
            600,
            50,
            a_min=280,
            b_min=180,
            default_a=400,
            default_b=300,
        )
        self.assertEqual(sizes[0] + sizes[1], 700)
        self.assertGreaterEqual(sizes[0], 280)
        self.assertGreaterEqual(sizes[1], 180)

    def test_fit_splitter_pair_scales_on_large_drift(self):
        # Saved for a tall window; current viewport is much shorter.
        sizes = fit_splitter_pair(
            600,
            900,
            600,
            a_min=200,
            b_min=160,
            default_a=320,
            default_b=280,
        )
        self.assertEqual(sizes[0] + sizes[1], 600)
        self.assertGreaterEqual(sizes[0], 200)
        self.assertGreaterEqual(sizes[1], 160)

    def test_apply_window_size_clamps_minimum_to_available(self):
        class _Win:
            def __init__(self):
                self.min_size = None
                self.size = None

            def setMinimumSize(self, w, h=None):
                if isinstance(w, QSize):
                    self.min_size = w
                else:
                    self.min_size = QSize(int(w), int(h))

            def resize(self, size):
                self.size = size

        win = _Win()
        with patch.object(layout_mod, "_available_size", return_value=QSize(1280, 640)):
            layout_mod.apply_window_size(
                win,
                preferred=QSize(1360, 850),
                minimum=QSize(1024, 600),
                margin=72,
            )
        self.assertIsNotNone(win.min_size)
        self.assertLessEqual(win.min_size.height(), 640)
        self.assertEqual(win.size, QSize(1280, 640))


if __name__ == "__main__":
    unittest.main()
