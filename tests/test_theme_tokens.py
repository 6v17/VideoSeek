import unittest

from ui.widgets.theme_tokens import load_merged_theme_colors, theme_colors_path
from ui.widgets.styles import THEME_COLORS_DARK_BASE


def _channel(value: int) -> float:
    color = value / 255.0
    if color <= 0.04045:
        return color / 12.92
    return ((color + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    text = hex_color.lstrip("#")
    red, green, blue = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(left: str, right: str) -> float:
    lighter, darker = sorted((_luminance(left), _luminance(right)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


class ThemeTokenTests(unittest.TestCase):
    def test_figma_dark_window_overrides_base(self):
        merged = load_merged_theme_colors(True, THEME_COLORS_DARK_BASE)
        self.assertEqual(merged["WINDOW"], "#141414")
        self.assertEqual(merged["BUTTON_SOFT_PRESSED"], "#2a2a2a")
        self.assertEqual(merged["ACCENT_SOFT_HOVER"], "#2a5080")
        self.assertIn("HERO", merged)

    def test_figma_light_surface_overrides_base(self):
        from ui.widgets.styles import THEME_COLORS_LIGHT_BASE

        merged = load_merged_theme_colors(False, THEME_COLORS_LIGHT_BASE)
        self.assertEqual(merged["WINDOW"], "#d4d4d4")
        self.assertEqual(merged["FIELD"], "#e7e7e7")
        self.assertEqual(merged["BUTTON_SOFT_HOVER"], "#e2e2e2")
        self.assertEqual(merged["SUCCESS_SOFT_HOVER"], "#cfead9")
        self.assertEqual(merged["SELECTION_BG"], "rgba(0,120,212,0.14)")
        self.assertEqual(merged["SCRIM"], "rgba(0,0,0,0.25)")

    def test_surface_steps_read_as_separate_blocks(self):
        from ui.widgets.styles import THEME_COLORS_LIGHT_BASE

        for base, dark in ((THEME_COLORS_DARK_BASE, True), (THEME_COLORS_LIGHT_BASE, False)):
            merged = load_merged_theme_colors(dark, base)
            self.assertGreater(_contrast(merged["PANEL"], merged["WINDOW"]), 1.4)
            self.assertNotEqual(merged["SIDEBAR"], merged["WINDOW"])
            self.assertNotEqual(merged["FIELD"], merged["PANEL"])

    def test_token_files_exist(self):
        self.assertTrue(theme_colors_path(True).is_file())
        self.assertTrue(theme_colors_path(False).is_file())


if __name__ == "__main__":
    unittest.main()
