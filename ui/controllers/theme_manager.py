"""Apply the global stylesheet and keep font scale in step with the screen."""

from PySide6.QtCore import QObject
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from ui.widgets.styles import build_style, font_scale_for_screen, theme_color_map


class ThemeManager(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.window = parent_window
        self._dpi_screen = None

    def bind_screen(self):
        app = QGuiApplication.instance()
        if app is None:
            return
        app.primaryScreenChanged.connect(self._on_primary_screen_changed)
        self._watch_screen(app.primaryScreen())

    def apply(self, is_dark: bool):
        colors = theme_color_map(bool(is_dark))
        style = build_style(colors, font_scale=font_scale_for_screen())
        app = QApplication.instance()
        if app is None:
            return colors
        app.setProperty("videoseek_is_dark", bool(is_dark))
        app.setStyleSheet(style)
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor(str(colors.get("ACCENT") or "#0078d4")))
        palette.setColor(
            QPalette.ColorRole.HighlightedText,
            QColor(str(colors.get("INVERSE_TEXT") or "#ffffff")),
        )
        app.setPalette(palette)
        return colors

    def _watch_screen(self, screen):
        if screen is None or self._dpi_screen is screen:
            return
        previous = self._dpi_screen
        if previous is not None:
            try:
                previous.logicalDotsPerInchChanged.disconnect(self._on_logical_dpi_changed)
            except (RuntimeError, TypeError):
                pass
        screen.logicalDotsPerInchChanged.connect(self._on_logical_dpi_changed)
        self._dpi_screen = screen

    def _on_logical_dpi_changed(self, _dpi):
        self.window.apply_theme()

    def _on_primary_screen_changed(self, screen):
        self._watch_screen(screen)
        self.window.apply_theme()
