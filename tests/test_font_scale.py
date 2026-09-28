"""Font scale collapse applied by build_style."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ui.widgets.styles import build_style


class FontScaleTests(unittest.TestCase):
    def test_build_style_collapses_adjacent_font_sizes(self):
        with patch("src.infra.paths.get_resource_path", side_effect=lambda p: p):
            style = build_style(
                {
                    "WINDOW": "#fff",
                    "TEXT": "#000",
                    "HEADLINE": "#000",
                    "MUTED": "#666",
                    "ACCENT": "#0078d4",
                    "ACCENT_HOVER": "#106ebe",
                    "ACCENT_SOFT": "#e6f2fb",
                    "SUCCESS": "#0f7b3a",
                    "SUCCESS_HOVER": "#0b5a2b",
                    "SUCCESS_SOFT": "#e7f6ee",
                    "WARN": "#b54708",
                    "WARN_SOFT": "#fff4e5",
                    "DANGER": "#c42b1c",
                    "DANGER_SOFT": "#fde7e9",
                    "SIDEBAR": "#f3f3f3",
                    "PANEL": "#ffffff",
                    "FIELD": "#ffffff",
                    "HERO": "#fafafa",
                    "HERO_LINE": "#e5e5e5",
                    "LINE": "#e5e5e5",
                    "LINE_STRONG": "#c4c4c4",
                    "TRACK": "#ededed",
                    "SCROLL": "#c4c4c4",
                    "BUTTON_SOFT": "#f5f5f5",
                    "BUTTON_SOFT_HOVER": "#ebebeb",
                    "VIDEO_BG": "#111",
                    "NOTICE_BG": "#e6f2fb",
                    "NOTICE_LINE": "#0078d4",
                    "INVERSE_TEXT": "#ffffff",
                }
            )
        self.assertNotIn("font-size: 11px", style)
        self.assertNotIn("font-size: 13px", style)
        self.assertNotIn("font-size: 15px", style)
        self.assertNotIn("font-size: 17px", style)
        self.assertNotIn("font-size: 20px", style)
        self.assertIn("font-size: 12px", style)
        self.assertIn("font-size: 14px", style)
        self.assertIn("font-size: 16px", style)
        self.assertIn("font-size: 18px", style)
        self.assertIn("font-size: 22px", style)


if __name__ == "__main__":
    unittest.main()
