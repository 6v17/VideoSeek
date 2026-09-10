from PySide6.QtCore import QSize
from PySide6.QtGui import QGuiApplication


WINDOW_SIZES = {
    "main": {
        "preferred": QSize(1360, 850),
        # Soft floor; apply_window_size further clamps against available geometry.
        "minimum": QSize(1024, 600),
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
    "understanding_services_dialog": {
        "preferred": QSize(920, 640),
        "minimum": QSize(780, 520),
        "screen_margin": 72,
    },
    "recap_beats_dialog": {
        "preferred": QSize(1280, 820),
        "minimum": QSize(1040, 680),
        "screen_margin": 72,
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
    "nav_button_height": 36,
    "sidebar_action_height": 32,
    "image_drop_min_height": 280,
    "search_query_tab_chrome_height": 41,
    "search_query_tab_page_margins_v": 8,
    # Must fit #SearchModeSelect (1px border + padding + text); too short clips the bottom edge.
    "search_image_options_row_height": 36,
    "preview_host_min_height": 240,
    "search_compare_baseline_height": 470,
    "search_panel_width_extra": 28,
    "compose_image_strip_height": 72,
    "link_query_preview_min_height": 210,
    "result_table_min_height": 420,
    "result_table_min_height_floor": 180,
    "compare_row_min_height_floor": 260,
    # Tall screens: do not lock the compare row to its preferred height, or results stay short.
    "compare_row_min_height_cap": 380,
    "preview_host_min_height_floor": 160,
    "video_scope_tree_min_height": 200,
    "progress_bar_height": 18,
    "progress_bar_min_width": 260,
    "settings_input_width": 116,
    "search_option_combo_width": 96,
    "search_scope_select_width": 92,
    "mobile_bridge_qr_width": 56,
    "search_field_label_width": 60,
    "search_field_gap": 4,
    "search_controls_group_gap": 8,
    "search_panel_card_margin": 8,
    "search_panel_row_spacing": 4,
    "settings_path_input_width": 160,
    "understanding_form_label_width": 96,
}


def compute_search_query_tabs_height(config=None) -> int:
    sizes = dict(COMPONENT_SIZES)
    if isinstance(config, dict):
        sizes.update(config)
    body = int(sizes["image_drop_min_height"]) + int(sizes.get("search_query_tab_page_margins_v", 12))
    chrome = int(sizes.get("search_query_tab_chrome_height", 41))
    return body + chrome


def compare_row_card_height(config=None) -> int:
    """Preferred height for search/preview cards (sizeHint / first-run defaults)."""
    sizes = dict(COMPONENT_SIZES)
    if isinstance(config, dict):
        sizes.update(config)
    return int(sizes["search_compare_baseline_height"]) + 22


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


def _available_height(margin=None) -> int | None:
    if margin is None:
        margin = WINDOW_SIZES["main"]["screen_margin"]
    available = _available_size(margin)
    return int(available.height()) if available is not None else None


def compare_row_min_height(config=None) -> int:
    """Hard minimum for the compare row; shrinks on short / high-DPI screens.

    Preferred card height is only a sizeHint / first-run default. Using it as the
    hard minimum on tall screens locked the top pane and starved the results table.
    """
    sizes = dict(COMPONENT_SIZES)
    if isinstance(config, dict):
        sizes.update(config)
    preferred = compare_row_card_height(sizes)
    floor = int(sizes.get("compare_row_min_height_floor", 280))
    soft_cap = int(sizes.get("compare_row_min_height_cap", 380))
    available = _available_height()
    if available is None:
        return min(preferred, soft_cap, 320)
    if available >= 800:
        return min(preferred, soft_cap)
    if available >= 700:
        return min(preferred, 300)
    return min(preferred, floor)


def result_table_min_height(config=None) -> int:
    """Hard minimum for the search results table; shrinks on short screens."""
    sizes = dict(COMPONENT_SIZES)
    if isinstance(config, dict):
        sizes.update(config)
    preferred = int(sizes["result_table_min_height"])
    floor = int(sizes.get("result_table_min_height_floor", 180))
    available = _available_height()
    if available is None:
        return min(preferred, 240)
    if available >= 900:
        return preferred
    if available >= 800:
        return min(preferred, 280)
    if available >= 700:
        return min(preferred, 220)
    return min(preferred, floor)


def preview_host_min_height(config=None) -> int:
    """Minimum preview surface height inside the compare row."""
    sizes = dict(COMPONENT_SIZES)
    if isinstance(config, dict):
        sizes.update(config)
    preferred = int(sizes["preview_host_min_height"])
    floor = int(sizes.get("preview_host_min_height_floor", 180))
    available = _available_height()
    if available is None:
        return min(preferred, 220)
    if available >= 900:
        return preferred
    if available >= 800:
        return min(preferred, 240)
    if available >= 700:
        return min(preferred, 200)
    return min(preferred, floor)


def clamp_size(preferred, margin):
    available = _available_size(margin)
    if not available:
        return QSize(preferred)
    return QSize(min(preferred.width(), available.width()), min(preferred.height(), available.height()))


def apply_window_size(window, preferred, minimum, margin):
    target = clamp_size(preferred, margin)
    available = _available_size(margin)
    min_width = min(minimum.width(), target.width())
    min_height = min(minimum.height(), target.height())
    if available is not None:
        # Keep mins inside ~95% of the usable desktop so high-DPI laptops are not forced taller.
        min_width = min(min_width, max(320, int(available.width() * 0.95)))
        min_height = min(min_height, max(240, int(available.height() * 0.95)))
    window.setMinimumSize(min_width, min_height)
    window.resize(target)


def apply_dialog_size(dialog, preferred, minimum, margin):
    target = clamp_size(preferred, margin)
    available = _available_size(margin)
    min_width = min(minimum.width(), target.width())
    min_height = min(minimum.height(), target.height())
    if available is not None:
        min_width = min(min_width, max(320, int(available.width() * 0.95)))
        min_height = min(min_height, max(240, int(available.height() * 0.95)))
    dialog.setMinimumSize(min_width, min_height)
    dialog.resize(target)


def message_dialog_min_width(default_width, margin):
    available = _available_size(margin)
    if not available:
        return default_width
    return min(default_width, available.width())


def fit_splitter_pair(
    total: int,
    saved_a: int,
    saved_b: int,
    *,
    a_min: int,
    b_min: int,
    default_a: int,
    default_b: int,
    drift_ratio: float = 0.25,
) -> list[int]:
    """Scale or discard a saved splitter pair so both sides respect mins on the current viewport."""
    total = max(0, int(total or 0))
    a_min = max(1, int(a_min))
    b_min = max(1, int(b_min))
    default_a = max(a_min, int(default_a))
    default_b = max(b_min, int(default_b))

    def _defaults() -> list[int]:
        if total <= 0:
            return [default_a, default_b]
        need = a_min + b_min
        if total < need:
            if total <= a_min:
                return [max(1, total // 2), max(1, total - total // 2)]
            top = min(a_min, total - 1)
            return [top, max(1, total - top)]
        a = min(default_a, total - b_min)
        a = max(a_min, a)
        return [a, max(b_min, total - a)]

    saved_a = int(saved_a or 0)
    saved_b = int(saved_b or 0)
    saved_total = saved_a + saved_b
    if saved_a <= 0 or saved_b <= 0 or saved_total <= 0:
        return _defaults()

    if total <= 0:
        return [max(a_min, saved_a), max(b_min, saved_b)]

    drift = abs(saved_total - total) / float(max(total, 1))
    if drift > drift_ratio:
        a = int(round(total * (saved_a / float(saved_total))))
        b = total - a
    else:
        a, b = saved_a, saved_b
        if a + b != total and a + b > 0:
            a = int(round(total * (a / float(a + b))))
            b = total - a

    if a < a_min or b < b_min:
        return _defaults()
    return [a, b]
