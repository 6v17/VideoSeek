import unittest

from ui.widgets.theme_tokens import load_merged_theme_colors, theme_colors_path
from ui.widgets.styles import THEME_COLORS_DARK_BASE


class ThemeTokenTests(unittest.TestCase):
    def test_figma_dark_window_overrides_base(self):
        merged = load_merged_theme_colors(True, THEME_COLORS_DARK_BASE)
        self.assertEqual(merged["WINDOW"], "#202020")
        self.assertIn("HERO", merged)

    def test_token_files_exist(self):
        self.assertTrue(theme_colors_path(True).is_file())
        self.assertTrue(theme_colors_path(False).is_file())


if __name__ == "__main__":
    unittest.main()
