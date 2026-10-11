import unittest

from ui.widgets.theme_tokens import load_merged_theme_colors, theme_colors_path
from ui.widgets.styles import THEME_COLORS_DARK_BASE


class ThemeTokenTests(unittest.TestCase):
    def test_figma_dark_window_overrides_base(self):
        merged = load_merged_theme_colors(True, THEME_COLORS_DARK_BASE)
        self.assertEqual(merged["WINDOW"], "#181818")
        self.assertEqual(merged["BUTTON_SOFT_PRESSED"], "#323232")
        self.assertEqual(merged["ACCENT_SOFT_HOVER"], "#2a5080")
        self.assertIn("HERO", merged)

    def test_figma_light_surface_overrides_base(self):
        from ui.widgets.styles import THEME_COLORS_LIGHT_BASE

        merged = load_merged_theme_colors(False, THEME_COLORS_LIGHT_BASE)
        self.assertEqual(merged["WINDOW"], "#e8e8e8")
        self.assertEqual(merged["FIELD"], "#f6f6f6")
        self.assertEqual(merged["BUTTON_SOFT_HOVER"], "#e2e2e2")
        self.assertEqual(merged["SUCCESS_SOFT_HOVER"], "#cfead9")
        self.assertEqual(merged["SELECTION_BG"], "rgba(0,120,212,0.14)")
        self.assertEqual(merged["SCRIM"], "rgba(0,0,0,0.25)")

    def test_token_files_exist(self):
        self.assertTrue(theme_colors_path(True).is_file())
        self.assertTrue(theme_colors_path(False).is_file())


if __name__ == "__main__":
    unittest.main()
