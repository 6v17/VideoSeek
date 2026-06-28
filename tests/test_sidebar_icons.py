import unittest

from PySide6.QtWidgets import QApplication

from ui.widgets.sidebar_icons import bilibili_toolbar_icon, github_toolbar_icon, qq_toolbar_icon


class SidebarIconsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def test_brand_icons_render(self):
        for factory in (
            lambda: github_toolbar_icon(is_dark=True),
            lambda: github_toolbar_icon(is_dark=False),
            bilibili_toolbar_icon,
            qq_toolbar_icon,
        ):
            icon = factory()
            pixmap = icon.pixmap(20, 20)
            self.assertFalse(pixmap.isNull())
            self.assertGreater(pixmap.width(), 0)
            self.assertGreater(pixmap.height(), 0)


if __name__ == "__main__":
    unittest.main()
