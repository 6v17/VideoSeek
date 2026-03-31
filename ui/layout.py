from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication


WINDOW_SIZES = {
    "main": {
        "preferred": QSize(1280, 820),
        "minimum": QSize(960, 640),
        "screen_margin": 72,
    },
    "about_dialog": {
        "preferred": QSize(420, 520),
        "minimum": QSize(360, 420),
        "screen_margin": 96,
    },
    "notice_dialog": {
        "preferred": QSize(450, 340),
        "minimum": QSize(360, 280),
        "screen_margin": 96,
    },
    "message_dialog": {
        "minimum_width": 440,
        "screen_margin": 96,
    },
}

COMPONENT_SIZES = {
    "sidebar_width": 248,
    "nav_button_height": 42,
    "sidebar_action_height": 36,
    "image_drop_min_height": 260,
    "preview_host_min_height": 300,
    "result_table_min_height": 520,
    "progress_bar_height": 18,
    "progress_bar_min_width": 260,
    "settings_input_width": 88,
    "settings_path_input_width": 260,
}


def _available_size(margin):
    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app else None
    if not screen:
        return None

    geometry = screen.availableGeometry()
    width = max(320, geometry.width() - margin)
    height = max(240, geometry.height() - margin)
    return QSize(width, height)


def clamp_size(preferred, margin):
    available = _available_size(margin)
    if not available:
        return QSize(preferred)
    return QSize(min(preferred.width(), available.width()), min(preferred.height(), available.height()))


def apply_window_size(window, preferred, minimum, margin):
    target = clamp_size(preferred, margin)
    min_width = min(minimum.width(), target.width())
    min_height = min(minimum.height(), target.height())
    window.setMinimumSize(min_width, min_height)
    window.resize(target)


def apply_dialog_size(dialog, preferred, minimum, margin):
    target = clamp_size(preferred, margin)
    min_width = min(minimum.width(), target.width())
    min_height = min(minimum.height(), target.height())
    dialog.setMinimumSize(min_width, min_height)
    dialog.resize(target)


def message_dialog_min_width(default_width, margin):
    available = _available_size(margin)
    if not available:
        return default_width
    return min(default_width, available.width())
