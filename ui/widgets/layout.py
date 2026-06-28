from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication


WINDOW_SIZES = {
    "main": {
        "preferred": QSize(1360, 850),
        "minimum": QSize(1080, 680),
        "screen_margin": 72,
    },
    "about_dialog": {
        "preferred": QSize(620, 700),
        "minimum": QSize(520, 560),
        "screen_margin": 96,
    },
    "notice_dialog": {
        "preferred": QSize(620, 500),
        "minimum": QSize(560, 420),
        "screen_margin": 96,
    },
    "donate_dialog": {
        "preferred": QSize(520, 720),
        "minimum": QSize(460, 640),
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
    "image_drop_min_height": 300,
    "preview_host_min_height": 340,
    "search_compare_baseline_height": 548,
    "search_panel_width_extra": 28,
    "compose_image_strip_height": 86,
    "link_query_preview_min_height": 210,
    "result_table_min_height": 520,
    "video_scope_tree_min_height": 200,
    "progress_bar_height": 18,
    "progress_bar_min_width": 260,
    "settings_input_width": 116,
    "search_option_combo_width": 96,
    "search_scope_select_width": 92,
    "mobile_bridge_qr_width": 56,
    "search_field_label_width": 60,
    "search_field_gap": 4,
    "search_controls_group_gap": 12,
    "search_panel_card_margin": 12,
    "settings_path_input_width": 520,
}


def compute_search_panel_width(config=None) -> int:
    sizes = dict(COMPONENT_SIZES)
    if isinstance(config, dict):
        sizes.update(config)
    label = int(sizes.get("search_field_label_width", 72))
    scope = int(sizes.get("search_scope_select_width", 104))
    qr = int(sizes.get("mobile_bridge_qr_width", 56))
    toggle = 52
    field_gap = int(sizes.get("search_field_gap", 4))
    group_gap = int(sizes.get("search_controls_group_gap", 12))
    card_margin = int(sizes.get("search_panel_card_margin", 12)) * 2
    cluster = label + field_gap + scope
    row1 = cluster + group_gap + label + field_gap + toggle + field_gap + qr
    row2 = cluster + group_gap + label + field_gap + toggle + field_gap + qr
    extra = int(sizes.get("search_panel_width_extra", 0))
    return max(row1, row2) + card_margin + extra


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
