
from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.flow_layout import FlowLayout
from ui.widgets.layout import (
    COMPONENT_SIZES,
    layout_viewport_height,
    result_table_min_height,
)
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.search_results_pager import SearchResultsPager
from ui.widgets.result_view import ResultView
from ui.widgets.scaffold import (
    PageScaffold,
    VSCard,
    VSProgressStatusRow,
    make_runtime_banner,
)
from ui.widgets.search_panel import SearchPanel
from ui.widgets.button_roles import set_button_role
from ui.widgets.styles import repolish_widget
from ui.widgets.library_video_tree import LibraryGroupedVideoTree
from ui.widgets.video_download_page import VideoDownloadPage

LinkSearchPage = VideoDownloadPage


def _fallback_text(texts, key, zh_text, en_text):
    if key in texts:
        return texts[key]
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


fallback_text = _fallback_text

# Transport row (play, range, export) needs about this much. Narrower clips the buttons.
_DOCKED_PREVIEW_WIDTH = 470


class SamplingRuleRow(QWidget):
    def __init__(self, on_change, on_remove, parent=None):
        super().__init__(parent)
        self._on_change = on_change
        self._on_remove = on_remove

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.start_input = QLineEdit()
        self.end_input = QLineEdit()
        self.fps_input = NoWheelDoubleSpinBox()
        self.fps_input.setRange(0.01, 24.0)
        self.fps_input.setDecimals(2)
        self.fps_input.setSingleStep(0.1)
        self.btn_remove = QPushButton()
        self.btn_remove.setObjectName("GhostButton")
        self.btn_remove.setMinimumHeight(34)

        for widget, width in ((self.start_input, 92), (self.end_input, 92)):
            widget.setMinimumWidth(width)
            widget.setMaximumWidth(width + 36)
            widget.setMinimumHeight(34)

        self.fps_input.setMinimumWidth(86)
        self.fps_input.setMaximumWidth(126)
        self.fps_input.setMinimumHeight(34)

        layout.addWidget(self.start_input, 0)
        layout.addWidget(self.end_input, 0)
        layout.addWidget(self.fps_input, 0)
        layout.addWidget(self.btn_remove, 0)
        layout.addStretch(1)

        self.start_input.textChanged.connect(self._emit_change)
        self.end_input.textChanged.connect(self._emit_change)
        self.fps_input.valueChanged.connect(self._emit_change)
        self.btn_remove.clicked.connect(lambda: self._on_remove(self))

    def _emit_change(self, *_args):
        self._on_change()

    def set_texts(self, start_text, end_text, fps_value):
        self.start_input.setText(start_text)
        self.end_input.setText(end_text)
        self.fps_input.setValue(max(0.01, float(fps_value)))

    def get_rule_text(self):
        start_text = self.start_input.text().strip()
        end_text = self.end_input.text().strip()
        fps_text = f"{self.fps_input.value():.2f}".rstrip("0").rstrip(".")
        if not start_text and not end_text:
            return ""
        return f"{start_text}-{end_text}={fps_text}"


class ClickableLabel(QLabel):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._click_handler = None

    def set_click_handler(self, handler):
        self._click_handler = handler
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and callable(self._click_handler) and self.rect().contains(event.position().toPoint()):
            self._click_handler()
        super().mouseReleaseEvent(event)


class _NoWheelMixin:
    def wheelEvent(self, event):
        event.ignore()


class NoWheelSpinBox(_NoWheelMixin, QSpinBox):
    pass


class NoWheelSlider(_NoWheelMixin, QSlider):
    pass


class NoWheelDoubleSpinBox(_NoWheelMixin, QDoubleSpinBox):
    pass


class NoWheelComboBox(_NoWheelMixin, QComboBox):
    pass


class SettingDetailPopup(QFrame):
    def __init__(self, parent=None, is_dark=True):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setObjectName("SettingDetailPopup")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._anchor_label = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        self.title_label = QLabel()
        self.title_label.setObjectName("SettingDetailPopupTitle")
        self.title_label.setWordWrap(True)

        self.body_label = QLabel()
        self.body_label.setObjectName("SettingDetailPopupBody")
        self.body_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.body_label)
        self.set_dark_mode(is_dark)

    def set_dark_mode(self, is_dark):
        self._is_dark = is_dark
        self.setGraphicsEffect(None)
        repolish_widget(self)

    def show_for_label(self, label, title, text):
        self._anchor_label = label
        self.title_label.setText(title)
        self.body_label.setText(text)
        self.body_label.setMaximumWidth(320)
        self.adjustSize()

        anchor_global = label.mapToGlobal(label.rect().topRight())
        x = anchor_global.x() + 10
        y = anchor_global.y() - 4
        screen = label.screen()
        available = screen.availableGeometry() if screen is not None else self.screen().availableGeometry()

        if x + self.width() > available.right() - 12:
            left_anchor = label.mapToGlobal(label.rect().topLeft())
            x = left_anchor.x() - self.width() - 10
        if x < available.left() + 12:
            x = available.left() + 12
        if y + self.height() > available.bottom() - 12:
            y = max(available.top() + 12, available.bottom() - self.height() - 12)
        if y < available.top() + 12:
            y = available.top() + 12

        self.move(QPoint(x, y))
        self.show()
        self.raise_()

    def hide_and_clear(self):
        self._anchor_label = None
        self.hide()

    def eventFilter(self, watched, event):
        if not self.isVisible():
            return False
        if event.type() == QEvent.MouseButtonPress:
            global_pos = event.globalPosition().toPoint()
            if self.geometry().contains(global_pos):
                return False
            if self._anchor_label is not None:
                anchor_rect = self._anchor_label.rect()
                anchor_pos = self._anchor_label.mapFromGlobal(global_pos)
                if anchor_rect.contains(anchor_pos):
                    return False
            self.hide_and_clear()
        elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.hide_and_clear()
        elif event.type() in {QEvent.Wheel, QEvent.Scroll, QEvent.ScrollPrepare}:
            self.hide_and_clear()
        elif event.type() == QEvent.WindowDeactivate:
            self.hide_and_clear()
        return False

    def closeEvent(self, event):
        self.hide_and_clear()
        super().closeEvent(event)


def _apply_sidebar_icon_font(button: QToolButton, *, point_size: int = 14) -> None:
    font = QFont(button.font())
    font.setPointSize(point_size)
    font.setBold(True)
    button.setFont(font)


def _apply_sidebar_footer_icon_size(button: QToolButton) -> None:
    height = COMPONENT_SIZES["sidebar_action_height"]
    button.setFixedHeight(height)
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


def _make_sidebar_icon_button() -> QToolButton:
    button = QToolButton()
    button.setObjectName("SidebarIconButton")
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
    button.setIconSize(QSize(20, 20))
    _apply_sidebar_footer_icon_size(button)
    return button


class NavigationSidebar(QWidget):
    collapse_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(COMPONENT_SIZES["sidebar_width"])

        self._nav_layout = QVBoxLayout(self)
        layout = self._nav_layout
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        self.title = QLabel("VideoSeek")
        self.title.setObjectName("BrandTitle")
        self.btn_collapse = QToolButton()
        self.btn_collapse.setObjectName("SidebarIconButton")
        self.btn_collapse.setText("«")
        self.btn_collapse.setToolTip("隐藏侧边栏 (Ctrl+B)")
        self.btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse.setFixedSize(28, 28)
        self.btn_collapse.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_collapse.clicked.connect(self.collapse_requested.emit)
        title_row.addWidget(self.title, 1)
        title_row.addWidget(self.btn_collapse, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)
        self.subtitle = QLabel("Local video search workspace")
        self.subtitle.setObjectName("BrandSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.subtitle)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(12, 10, 12, 10)
        hero_layout.setSpacing(4)
        self.hero_tag = QLabel("WORKSPACE")
        self.hero_tag.setObjectName("HeroTag")
        self.hero_title = QLabel("Operate search, indexing, and settings separately")
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setWordWrap(True)
        self.hero_body = QLabel("A cleaner shell for search, libraries, and runtime controls.")
        self.hero_body.setObjectName("HeroBody")
        self.hero_body.setWordWrap(True)
        hero_layout.addWidget(self.hero_tag)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_body)
        layout.addWidget(self.hero_card)

        self._nav_buttons: dict[str, QPushButton] = {}
        self.btn_page_search = self._build_nav_button("Search", checked=True)
        self.btn_page_library = self._build_nav_button("Libraries")
        self.btn_page_understanding = self._build_nav_button("Evidence")
        self.btn_page_link = self._build_nav_button("Link Match")
        self.btn_page_settings = self._build_nav_button("Settings")
        for page_id, button in (
            ("search", self.btn_page_search),
            ("library", self.btn_page_library),
            ("understanding", self.btn_page_understanding),
            ("link", self.btn_page_link),
            ("settings", self.btn_page_settings),
        ):
            self._nav_buttons[page_id] = button
            layout.addWidget(button)
        self.runtime_hint = QLabel("")
        self.runtime_hint.setObjectName("StatusLabel")
        self.runtime_hint.setWordWrap(True)
        self.runtime_hint.hide()
        layout.addWidget(self.runtime_hint)
        layout.addStretch()

        self.btn_notice = QPushButton("Notes")
        set_button_role(self.btn_notice, "GhostButton", chrome="sidebarFooter")
        self.btn_about = QPushButton("About")
        set_button_role(self.btn_about, "GhostButton", chrome="sidebarFooter")
        self.btn_language = QPushButton("EN")
        set_button_role(self.btn_language, "GhostButton", chrome="sidebarFooterGhost")

        self.footer_icon_row = QWidget()
        footer_icon_layout = QHBoxLayout(self.footer_icon_row)
        footer_icon_layout.setContentsMargins(0, 0, 0, 0)
        footer_icon_layout.setSpacing(6)

        self.btn_theme = QToolButton()
        self.btn_theme.setObjectName("SidebarIconButton")
        self.btn_theme.setText("☀")
        self.btn_theme.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        _apply_sidebar_footer_icon_size(self.btn_theme)
        _apply_sidebar_icon_font(self.btn_theme)

        self.btn_donate = QToolButton()
        self.btn_donate.setObjectName("SidebarDonateButton")
        self.btn_donate.setText("❤")
        self.btn_donate.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        _apply_sidebar_footer_icon_size(self.btn_donate)
        _apply_sidebar_icon_font(self.btn_donate)

        self.btn_github = _make_sidebar_icon_button()
        self.btn_bilibili = _make_sidebar_icon_button()
        self.btn_qq = _make_sidebar_icon_button()

        for button in (
            self.btn_theme,
            self.btn_donate,
            self.btn_github,
            self.btn_bilibili,
            self.btn_qq,
        ):
            footer_icon_layout.addWidget(button, 1)

        for button in [self.btn_notice, self.btn_about, self.btn_language]:
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(COMPONENT_SIZES["sidebar_action_height"])
            layout.addWidget(button)

        for button in [self.btn_theme, self.btn_donate, self.btn_github, self.btn_bilibili, self.btn_qq]:
            button.setCursor(Qt.PointingHandCursor)

        layout.addWidget(self.footer_icon_row)

    def _build_nav_button(self, text, checked=False):
        button = QPushButton(text)
        set_button_role(button, "GhostButton", chrome="nav")
        button.setCheckable(True)
        button.setChecked(checked)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(COMPONENT_SIZES["nav_button_height"])
        return button

    def register_nav_page(self, page_id: str, label: str, *, insert_after: str = "understanding"):
        """Insert an optional nav button after ``insert_after`` (plugin pages)."""
        page_id = str(page_id or "").strip()
        if not page_id:
            raise ValueError("page_id is required")
        existing = self._nav_buttons.get(page_id)
        if existing is not None:
            return existing
        button = self._build_nav_button(str(label or page_id))
        self._nav_buttons[page_id] = button
        setattr(self, f"btn_page_{page_id}", button)
        anchor = self._nav_buttons.get(str(insert_after or "").strip())
        if anchor is not None:
            idx = self._nav_layout.indexOf(anchor)
            self._nav_layout.insertWidget(idx + 1, button)
        else:
            settings_btn = self._nav_buttons.get("settings")
            if settings_btn is not None:
                idx = self._nav_layout.indexOf(settings_btn)
                self._nav_layout.insertWidget(idx, button)
            else:
                self._nav_layout.insertWidget(self._nav_layout.count(), button)
        return button

    def nav_button(self, page_id: str):
        return self._nav_buttons.get(str(page_id or "").strip())

    def set_current_page(self, page_name):
        target = str(page_name or "").strip()
        for name, button in self._nav_buttons.items():
            button.setChecked(name == target)


class SearchPage(QWidget):
    search_collapsed_changed = Signal(bool)
    preview_collapsed_changed = Signal(bool)
    results_scale_settled = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        self.scaffold.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.scaffold, 1)
        self.header = self.scaffold.header
        self.header.subtitle.hide()
        page_body = self.scaffold.content_layout
        page_body.setSpacing(6)

        self.indexing_notice, self.indexing_notice_text = make_runtime_banner()
        self.indexing_notice.hide()

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(False)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self.search_panel = SearchPanel()
        self.query_card = self.search_panel
        self.lbl_active_model = self.search_panel.lbl_active_model
        self.lbl_text_model_hint = self.search_panel.lbl_text_model_hint
        self.lbl_dialogue_hint = self.search_panel.lbl_dialogue_hint
        self.lbl_tags_hint = self.search_panel.lbl_tags_hint
        self.search_query_tabs = self.search_panel.search_query_tabs
        self.img_label = self.search_panel.img_label
        self.text_search = self.search_panel.text_search
        self.dialogue_search = self.search_panel.dialogue_search
        self.tags_search = self.search_panel.tags_search
        self.search_mode = self.search_panel.search_mode
        self.search_mode_label = self.search_panel.search_mode_label
        self.text_search_enhance = self.search_panel.text_search_enhance
        self.text_search_enhance_label = self.search_panel.text_search_enhance_label
        self.image_search_mode = self.search_panel.image_search_mode
        self.image_search_mode_label = self.search_panel.image_search_mode_label
        self.image_search_mode_cluster = self.search_panel.image_search_mode_cluster
        self.dialogue_search_mode = self.search_panel.dialogue_search_mode
        self.dialogue_search_mode_label = self.search_panel.dialogue_search_mode_label
        self.dialogue_search_mode_cluster = self.search_panel.dialogue_search_mode_cluster
        self.text_granularity_cluster = self.search_panel.text_granularity_cluster
        self.search_granularity_cluster = self.search_panel.text_granularity_cluster
        self.search_mode_options_stack = self.search_panel.search_mode_options_stack
        self.btn_search = self.search_panel.btn_search
        self.btn_clear = self.search_panel.btn_clear
        self.btn_filters = self.search_panel.btn_filters
        self.score_input = self.search_panel.score_input
        self.score_label = self.search_panel.score_label
        self.score_cluster = self.search_panel.score_cluster
        self.search_scope_cluster = self.search_panel.search_scope_cluster
        self.search_scope_label = self.search_panel.search_scope_label
        self.search_scope_select = self.search_panel.search_scope_select
        self.skip_edges_cluster = self.search_panel.skip_edges_cluster
        self.skip_edges_label = self.search_panel.skip_edges_label
        self.btn_skip_edges = self.search_panel.btn_skip_edges
        self.options_block = self.search_panel.options_block
        self.options_title = self.search_panel.options_title
        self.mobile_row = self.search_panel.mobile_row
        self.compose_form = self.search_panel.compose_form
        self.btn_save_preset = self.search_panel.btn_save_preset
        self.search_presets_bar = self.search_panel.search_presets_bar
        self.btn_manage_presets = self.search_panel.btn_manage_presets

        # Search spans the page. Results and the preview column split the space under it.
        self.preview_panel = PreviewPanel(self)
        self.preview_panel.set_docked(True)
        self.preview_card = self.preview_panel
        self.preview_title = self.preview_panel.preview_title
        self.preview_host = self.preview_panel.preview_host
        self.preview_host_layout = self.preview_panel.preview_host_layout
        self.preview_placeholder = self.preview_panel.preview_placeholder
        self.expanded_chrome = self.preview_panel.expanded_chrome

        self.compare_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.compare_splitter.setObjectName("SearchCompareSplitter")
        self.compare_splitter.setChildrenCollapsible(False)
        self.compare_splitter.setHandleWidth(10)
        self._compare_splitter = self.compare_splitter
        self._compare_row = self.compare_splitter
        self._compare_sizes_set = False
        self._page_body = page_body
        self._preview_layout_maximized = False
        self._workspace_sizes_before_preview_max = None
        self._search_collapsed = False
        self._preview_collapsed = False
        self._preview_width_before_collapse = _DOCKED_PREVIEW_WIDTH

        self.results_slot = QWidget()
        self.results_slot.setObjectName("SearchResultsSlot")
        self.results_slot.setMinimumHeight(160)
        self.results_slot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.results_slot_layout = QVBoxLayout(self.results_slot)
        self.results_slot_layout.setContentsMargins(0, 0, 0, 0)
        self.results_slot_layout.setSpacing(0)

        self.results_card = VSCard()
        results_layout = self.results_card.content_layout
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")

        results_toolbar = QHBoxLayout()
        results_toolbar.setContentsMargins(0, 0, 0, 0)
        results_toolbar.setSpacing(10)
        results_toolbar.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.btn_export_tasks = QPushButton()
        self.btn_export_tasks.setObjectName("GhostButton")
        self.btn_shot_list = QPushButton()
        self.btn_shot_list.setObjectName("GhostButton")

        self.results_actions = QWidget()
        self.results_actions.setObjectName("SearchResultsActions")
        actions_layout = QHBoxLayout(self.results_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)

        self.results_view_segment = QFrame()
        self.results_view_segment.setObjectName("LibraryModeSegment")
        view_row = QHBoxLayout(self.results_view_segment)
        view_row.setContentsMargins(2, 2, 2, 2)
        view_row.setSpacing(2)
        self.btn_results_view_table = QPushButton()
        set_button_role(self.btn_results_view_table, "GhostButton", chrome="modeSegment")
        self.btn_results_view_table.setCheckable(True)
        self.btn_results_view_table.setChecked(False)
        self.btn_results_view_table.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_results_view_table.setMinimumWidth(52)
        self.btn_results_view_grid = QPushButton()
        set_button_role(self.btn_results_view_grid, "GhostButton", chrome="modeSegment")
        self.btn_results_view_grid.setCheckable(True)
        self.btn_results_view_grid.setChecked(True)
        self.btn_results_view_grid.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_results_view_grid.setMinimumWidth(52)
        view_row.addWidget(self.btn_results_view_table)
        view_row.addWidget(self.btn_results_view_grid)
        self._results_view_group = QButtonGroup(self)
        self._results_view_group.setExclusive(True)
        self._results_view_group.addButton(self.btn_results_view_table, 0)
        self._results_view_group.addButton(self.btn_results_view_grid, 1)

        actions_layout.addWidget(self.results_view_segment)
        actions_layout.addWidget(self.btn_shot_list)
        actions_layout.addWidget(self.btn_export_tasks)

        self.results_size_cluster = QWidget()
        self.results_size_cluster.setObjectName("SearchResultsSize")
        size_row = QHBoxLayout(self.results_size_cluster)
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(6)
        self.results_size_label = QLabel("大小")
        self.results_size_label.setObjectName("InlineFieldLabel")
        self.results_size_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.results_size_slider.setObjectName("ResultSizeSlider")
        self.results_size_slider.setRange(70, 160)
        self.results_size_slider.setSingleStep(10)
        self.results_size_slider.setPageStep(10)
        self.results_size_slider.setValue(100)
        self.results_size_slider.setFixedWidth(112)
        self.results_size_slider.setFixedHeight(28)
        self.results_size_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.results_size_value = QLabel("100%")
        self.results_size_value.setObjectName("SearchScoreValue")
        self.results_size_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.results_size_value.setFixedWidth(40)
        size_row.addWidget(self.results_size_label, 0)
        size_row.addWidget(self.results_size_slider, 0)
        size_row.addWidget(self.results_size_value, 0)

        results_toolbar.addWidget(self.lbl_status, 1)
        results_toolbar.addWidget(self.results_size_cluster, 0)
        results_toolbar.addWidget(self.results_actions, 0)

        self.results_pager = SearchResultsPager()
        self.result_view = ResultView(min_table_height=result_table_min_height())
        self.result_table = self.result_view.table
        results_layout.addWidget(self.results_title)
        results_layout.addLayout(results_toolbar)
        results_layout.addWidget(self.results_pager, 0, Qt.AlignmentFlag.AlignHCenter)
        results_layout.setSpacing(8)
        results_layout.addWidget(self.result_view, 1)

        self.results_slot_layout.addWidget(self.results_card, 1)

        self.browse_stack = QStackedWidget()
        self.browse_stack.setObjectName("SearchBrowseStack")
        self.browse_stack.setMinimumWidth(280)
        self.browse_stack.addWidget(self.results_slot)

        from ui.widgets.embedded_preview import EmbeddedPreviewLayer

        self.preview_layer = EmbeddedPreviewLayer(object_name="SearchPreviewLayer")
        self.btn_preview_back = self.preview_layer.btn_preview_back
        self.btn_preview_back.setText("返回结果")
        self.btn_preview_shot_list = self.preview_layer.btn_preview_shot_list
        self.btn_preview_export_tasks = self.preview_layer.btn_preview_export_tasks
        self.preview_layer_host = self.preview_layer.preview_layer_host
        self.preview_layer_host_layout = self.preview_layer.preview_layer_host_layout
        self.preview_detail = self.preview_layer.preview_detail
        self.preview_detail_title = self.preview_layer.preview_detail_title
        self.preview_detail_name = self.preview_layer.preview_detail_name
        self.preview_detail_body = self.preview_layer.preview_detail_body
        self.preview_strip_wrap = self.preview_layer.preview_strip_wrap
        self.preview_strip_label = self.preview_layer.preview_strip_label
        self.preview_strip_label.setText("同视频就近候选")
        self.preview_strip_label.setToolTip("双击播放")
        self.preview_strip = self.preview_layer.preview_strip
        self.preview_strip_host = self.preview_layer.preview_strip_host
        self.preview_strip_row = self.preview_layer.preview_strip_row
        self.browse_stack.addWidget(self.preview_layer)

        # Results stay in the left column. Search sits above both columns.
        self._original_column = QWidget()
        self._original_column.setObjectName("SearchOriginalColumn")
        self._original_column.setMinimumWidth(360)
        self._original_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        original_layout = QVBoxLayout(self._original_column)
        original_layout.setContentsMargins(0, 0, 0, 0)
        original_layout.setSpacing(0)
        original_layout.addWidget(self.browse_stack, 1)

        self.preview_column = QWidget()
        self.preview_column.setObjectName("SearchPreviewColumn")
        self.preview_column.setMinimumWidth(320)
        self.preview_column.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        preview_column_layout = QVBoxLayout(self.preview_column)
        preview_column_layout.setContentsMargins(0, 0, 0, 0)
        preview_column_layout.setSpacing(0)
        self.btn_preview_restore = QToolButton()
        self.btn_preview_restore.setObjectName("SidebarIconButton")
        self.btn_preview_restore.setText("«")
        self.btn_preview_restore.setToolTip("展开预览")
        self.btn_preview_restore.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preview_restore.setFixedSize(28, 48)
        self.btn_preview_restore.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_preview_restore.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_preview_restore.hide()
        preview_column_layout.addWidget(self.preview_panel, 1)
        preview_column_layout.addWidget(self.btn_preview_restore, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.compare_splitter.addWidget(self._original_column)
        self.compare_splitter.addWidget(self.preview_column)
        self.compare_splitter.setStretchFactor(0, 1)
        self.compare_splitter.setStretchFactor(1, 0)
        page_body.addWidget(self.indexing_notice)
        page_body.addWidget(self.search_panel, 0)
        page_body.addWidget(self.compare_splitter, 1)
        self._wire_workspace_chrome()
        self.workspace_splitter = None
        self._workspace_splitter = None

        self._viewport_budget_timer = QTimer(self)
        self._viewport_budget_timer.setSingleShot(True)
        self._viewport_budget_timer.setInterval(50)
        self._viewport_budget_timer.timeout.connect(self._apply_viewport_budget)
        QTimer.singleShot(0, self._apply_viewport_budget)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        timer = getattr(self, "_viewport_budget_timer", None)
        if timer is not None:
            timer.start()

    def _viewport_height(self) -> int | None:
        return layout_viewport_height(self.window())

    def _apply_viewport_budget(self) -> None:
        vh = self._viewport_height()
        panel = getattr(self, "search_panel", None)
        if panel is not None and hasattr(panel, "apply_viewport_budget"):
            panel.apply_viewport_budget(vh)
        panel = getattr(self, "preview_panel", None)
        if panel is not None and hasattr(panel, "apply_viewport_budget"):
            panel.apply_viewport_budget(vh)
        splitter = getattr(self, "compare_splitter", None)
        if splitter is not None and not getattr(self, "_compare_sizes_set", False) and splitter.width() > 200:
            if getattr(self, "_preview_collapsed", False):
                preview_w = 36
            else:
                preview_w = _DOCKED_PREVIEW_WIDTH
            splitter.setSizes([max(0, splitter.width() - preview_w), preview_w])
            self._compare_sizes_set = True
        view = getattr(self, "result_view", None)
        if view is not None and hasattr(view, "set_viewport_min_height"):
            view.set_viewport_min_height(result_table_min_height(viewport_height=vh))

    def adopt_preview_width(self) -> None:
        """After the page grows, bring a squeezed preview back up to the docked width."""
        if getattr(self, "_preview_collapsed", False):
            return
        splitter = getattr(self, "compare_splitter", None)
        if splitter is None or splitter.width() <= 200:
            return
        sizes = splitter.sizes()
        if len(sizes) != 2:
            return
        preview_w = int(sizes[1])
        target = _DOCKED_PREVIEW_WIDTH
        if preview_w >= target:
            return
        results_min = 360
        column = getattr(self, "_original_column", None)
        if column is not None:
            results_min = int(column.minimumWidth())
        spare = int(sizes[0]) - results_min
        if spare <= 0:
            return
        give = min(target - preview_w, spare)
        splitter.setSizes([int(sizes[0]) - give, preview_w + give])

    def set_preview_maximized(self, maximized: bool) -> None:
        """Preview is a dialog now; do not hide the browse layout."""
        del maximized
        self._preview_layout_maximized = False

    def is_preview_maximized(self) -> bool:
        return False

    @property
    def search_collapsed(self) -> bool:
        return bool(self._search_collapsed)

    @property
    def preview_collapsed(self) -> bool:
        return bool(self._preview_collapsed)

    def _wire_workspace_chrome(self) -> None:
        self.search_panel.btn_collapse.clicked.connect(
            lambda: self.set_search_collapsed(not self._search_collapsed)
        )
        self.preview_panel.btn_collapse.clicked.connect(
            lambda: self.set_preview_collapsed(not self._preview_collapsed)
        )
        self.btn_preview_restore.clicked.connect(lambda: self.set_preview_collapsed(False))
        self.results_size_slider.valueChanged.connect(self._on_results_size_slider)
        self.results_size_slider.sliderReleased.connect(self._on_results_size_released)
        self.compare_splitter.splitterMoved.connect(lambda *_args: self._schedule_video_follow())

    def _schedule_video_follow(self) -> None:
        window = self.window()
        schedule = getattr(window, "_schedule_preview_video_frame", None)
        if callable(schedule):
            schedule()

    def _apply_search_collapse_label(self) -> None:
        button = self.search_panel.btn_collapse
        window = self.window()
        texts = getattr(window, "texts", None) or {}
        if self._search_collapsed:
            button.setText("«")
            button.setToolTip(str(texts.get("search_card_expand", "展开搜索栏")))
        else:
            button.setText("»")
            button.setToolTip(str(texts.get("search_card_collapse", "收起搜索栏")))

    def set_search_collapsed(self, collapsed: bool, *, emit: bool = True) -> None:
        """Fold the query body. The same button stays on the left of the card."""
        collapsed = bool(collapsed)
        self._search_collapsed = collapsed
        self.search_panel.set_query_collapsed(collapsed)
        self._apply_search_collapse_label()
        self._schedule_video_follow()
        if emit:
            self.search_collapsed_changed.emit(collapsed)

    def set_preview_collapsed(self, collapsed: bool, *, emit: bool = True) -> None:
        """Hide the player card and keep a restore tab on the right edge."""
        collapsed = bool(collapsed)
        self._preview_collapsed = collapsed
        splitter = self.compare_splitter
        column = self.preview_column
        if collapsed:
            sizes = splitter.sizes()
            if len(sizes) == 2 and int(sizes[1]) > 80:
                self._preview_width_before_collapse = int(sizes[1])
            self.preview_panel.hide()
            self.btn_preview_restore.show()
            column.setMinimumWidth(36)
            column.setMaximumWidth(36)
            total = max(int(splitter.width()), sum(int(part) for part in sizes))
            if total > 80:
                splitter.setSizes([max(0, total - 36), 36])
        else:
            self.btn_preview_restore.hide()
            column.setMinimumWidth(320)
            column.setMaximumWidth(16777215)
            self.preview_panel.show()
            sizes = splitter.sizes()
            total = max(int(splitter.width()), sum(int(part) for part in sizes))
            target = max(320, int(self._preview_width_before_collapse or _DOCKED_PREVIEW_WIDTH))
            if total > target + 80:
                splitter.setSizes([max(0, total - target), target])
            fit = getattr(self.preview_panel, "_fit_host_aspect", None)
            if callable(fit):
                QTimer.singleShot(0, fit)
        self._schedule_video_follow()
        if emit:
            self.preview_collapsed_changed.emit(collapsed)

    def yield_preview_column(self, yielded: bool) -> None:
        """Give the docked column to the large preview. The info card width stays fixed."""
        yielded = bool(yielded)
        splitter = self.compare_splitter
        column = self.preview_column
        if yielded:
            if getattr(self, "_preview_column_yielded", False):
                self.preview_panel.hide()
                self.btn_preview_restore.hide()
                return
            sizes = splitter.sizes()
            self._preview_column_yielded = True
            self._preview_column_width_before_yield = int(sizes[1]) if len(sizes) == 2 else 0
            self._preview_column_collapsed_before_yield = bool(self._preview_collapsed)
            self.preview_panel.hide()
            self.btn_preview_restore.hide()
            column.setMinimumWidth(0)
            column.setMaximumWidth(0)
            total = max(int(splitter.width()), sum(int(part) for part in sizes))
            splitter.setSizes([max(total, 1), 0])
            self._schedule_video_follow()
            return
        if not getattr(self, "_preview_column_yielded", False):
            if not self._preview_collapsed:
                self.preview_panel.show()
            return
        self._preview_column_yielded = False
        if self._preview_column_collapsed_before_yield:
            self.set_preview_collapsed(True, emit=False)
            return
        column.setMinimumWidth(320)
        column.setMaximumWidth(16777215)
        self.preview_panel.show()
        self.btn_preview_restore.hide()
        width = int(getattr(self, "_preview_column_width_before_yield", 0) or 0)
        if width < 320:
            width = _DOCKED_PREVIEW_WIDTH
        total = max(int(splitter.width()), width + int(self._original_column.minimumWidth()))
        splitter.setSizes([max(0, total - width), width])
        self._schedule_video_follow()

    def set_results_display_scale(self, percent: int, *, emit: bool = True, snap: bool = False) -> None:
        from ui.widgets.result_grid import clamp_result_scale_percent

        percent = clamp_result_scale_percent(percent, snap=snap)
        slider = self.results_size_slider
        slider.blockSignals(True)
        slider.setValue(percent)
        slider.blockSignals(False)
        self.results_size_value.setText(f"{percent}%")
        self.result_view.set_display_scale(percent)
        if emit:
            self.results_scale_settled.emit(percent)

    def _on_results_size_slider(self, value: int) -> None:
        # Dragging only resizes the cards. Saving and sharper thumbnails wait for release.
        dragging = self.results_size_slider.isSliderDown()
        self.set_results_display_scale(value, emit=not dragging, snap=not dragging)

    def _on_results_size_released(self) -> None:
        self.set_results_display_scale(self.results_size_slider.value(), emit=True, snap=True)


class DialogueLibraryRow(QFrame):
    """Compact card row for the shared dialogue library list."""

    def __init__(self, title: str, meta: str, badge: str, *, ready: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("DialogueLibraryRow")
        self.setProperty("selected", False)
        self.setMinimumHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(4)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DialogueLibraryRowTitle")
        self.title_label.setWordWrap(False)
        self.meta_label = QLabel(meta)
        self.meta_label.setObjectName("DialogueLibraryRowMeta")
        self.meta_label.setWordWrap(False)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.meta_label)

        self.badge_label = QLabel(badge)
        self.badge_label.setObjectName("DialogueLibraryRowBadge")
        self.badge_label.setProperty("ready", bool(ready))
        self.badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(text_col, 1)
        layout.addWidget(self.badge_label, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        repolish_widget(self)


class LibraryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        def _toolbar_divider():
            divider = QFrame()
            divider.setFrameShape(QFrame.VLine)
            divider.setFrameShadow(QFrame.Plain)
            divider.setObjectName("ToolbarDivider")
            divider.setFixedSize(1, 22)
            return divider

        # Chrome: mode switch + add/remove as one left-packed group, hint underneath
        self.shared_toolbar_card = VSCard(
            variant="sub",
            margins=(12, 8, 12, 8),
            spacing=6,
            object_name="LibrarySharedStrip",
        )
        shared_outer = self.shared_toolbar_card.content_layout

        chrome_row = QHBoxLayout()
        chrome_row.setContentsMargins(0, 0, 0, 0)
        chrome_row.setSpacing(10)
        chrome_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        mode_block = QVBoxLayout()
        mode_block.setContentsMargins(0, 0, 0, 0)
        mode_block.setSpacing(2)
        self.lbl_mode_caption = QLabel()
        self.lbl_mode_caption.setObjectName("LibraryChromeCaption")
        mode_block.addWidget(self.lbl_mode_caption)

        self.mode_segment = QFrame()
        self.mode_segment.setObjectName("LibraryModeSegment")
        mode_row = QHBoxLayout(self.mode_segment)
        mode_row.setContentsMargins(2, 2, 2, 2)
        mode_row.setSpacing(2)
        mode_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.btn_tab_visual = QPushButton()
        set_button_role(self.btn_tab_visual, "GhostButton", chrome="modeSegment")
        self.btn_tab_visual.setCheckable(True)
        self.btn_tab_visual.setChecked(True)
        self.btn_tab_visual.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_visual.setMinimumWidth(108)
        self.btn_tab_dialogue = QPushButton()
        set_button_role(self.btn_tab_dialogue, "GhostButton", chrome="modeSegment")
        self.btn_tab_dialogue.setCheckable(True)
        self.btn_tab_dialogue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_dialogue.setMinimumWidth(108)
        mode_row.addWidget(self.btn_tab_visual)
        mode_row.addWidget(self.btn_tab_dialogue)
        self._library_mode_group = QButtonGroup(self)
        self._library_mode_group.setExclusive(True)
        self._library_mode_group.addButton(self.btn_tab_visual, 0)
        self._library_mode_group.addButton(self.btn_tab_dialogue, 1)
        self._library_mode_group.idClicked.connect(self.set_library_mode)
        mode_block.addWidget(self.mode_segment, 0)

        action_block = QVBoxLayout()
        action_block.setContentsMargins(0, 0, 0, 0)
        action_block.setSpacing(2)
        self.lbl_action_caption = QLabel()
        self.lbl_action_caption.setObjectName("LibraryChromeCaption")
        self.lbl_action_caption.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        action_block.addWidget(self.lbl_action_caption)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.btn_add_lib = QPushButton()
        self.btn_add_lib.setObjectName("SuccessGhostButton")
        self.btn_add_lib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove_lib = QPushButton()
        self.btn_remove_lib.setObjectName("DangerGhostButton")
        self.btn_remove_lib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove_lib.setEnabled(False)
        action_row.addWidget(self.btn_add_lib)
        action_row.addWidget(self.btn_remove_lib)
        action_block.addLayout(action_row)

        chrome_row.addLayout(mode_block, 0)
        chrome_row.addWidget(_toolbar_divider())
        chrome_row.addLayout(action_block, 0)
        chrome_row.addStretch(1)
        shared_outer.addLayout(chrome_row)

        self.lbl_shared_library_hint = QLabel()
        self.lbl_shared_library_hint.setObjectName("LibraryChromeHint")
        self.lbl_shared_library_hint.setWordWrap(True)
        self.lbl_shared_library_hint.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.lbl_shared_library_hint.hide()
        shared_outer.addWidget(self.lbl_shared_library_hint)
        page_body.addWidget(self.shared_toolbar_card)
        self.library_stack = QStackedWidget()
        self.library_stack.setObjectName("LibraryStack")
        # Compatibility alias: older code used QTabWidget APIs.
        self.library_tabs = self.library_stack

        # --- Panel: visual video library (one card: actions + tree) ---
        self.visual_tab = QWidget()
        visual_layout = QVBoxLayout(self.visual_tab)
        visual_layout.setContentsMargins(0, 8, 0, 0)
        visual_layout.setSpacing(0)

        self.table_card = VSCard(margins=(16, 14, 16, 14), spacing=12)
        self.toolbar_card = self.table_card
        table_layout = self.table_card.content_layout

        self.table_title = QLabel()
        self.table_title.setObjectName("CardTitle")
        table_layout.addWidget(self.table_title)

        toolbar_host = QWidget()
        toolbar_host.setObjectName("LibraryToolbarFlow")
        toolbar = FlowLayout(toolbar_host, spacing=8)
        self.btn_sync_db = QPushButton()
        self.btn_sync_db.setObjectName("PrimaryButton")
        self.btn_refresh_visual_library = QPushButton()
        self.btn_refresh_visual_library.setObjectName("GhostButton")
        self.btn_stop_index = QPushButton()
        self.btn_stop_index.setObjectName("DangerGhostButton")
        self.btn_stop_index.setEnabled(False)
        self.btn_stop_index.setVisible(False)
        self.btn_index_issues = QPushButton()
        self.btn_index_issues.setObjectName("GhostButton")
        self.btn_index_issues.setEnabled(False)
        self.btn_index_issues.setVisible(False)
        self.btn_fix_missing_vectors = QPushButton()
        self.btn_fix_missing_vectors.setObjectName("GhostButton")
        self.btn_fix_missing_vectors.setEnabled(False)
        self.btn_fix_missing_vectors.setVisible(False)
        self.btn_cleanup_missing = QPushButton()
        self.btn_cleanup_missing.setObjectName("GhostButton")
        self.btn_cleanup_missing.setVisible(False)
        self.btn_remove_selected_videos = QPushButton()
        self.btn_remove_selected_videos.setObjectName("DangerGhostButton")
        self.btn_remove_selected_videos.setEnabled(False)
        self.btn_vector_details = QPushButton()
        self.btn_vector_details.setObjectName("GhostButton")
        self.btn_debug_gpu_oom = QPushButton()
        self.btn_debug_gpu_oom.setObjectName("GhostButton")
        self.btn_debug_gpu_oom.setVisible(False)
        self.btn_debug_system_oom = QPushButton()
        self.btn_debug_system_oom.setObjectName("GhostButton")
        self.btn_debug_system_oom.setVisible(False)

        self.visual_video_tree = LibraryGroupedVideoTree()
        self.visual_video_tree.setMinimumHeight(280)
        self.library_list = self.visual_video_tree
        self.library_column_header_labels = []

        toolbar.addWidget(self.btn_sync_db)
        toolbar.addWidget(self.btn_refresh_visual_library)
        self.visual_repair_divider = _toolbar_divider()
        self.visual_repair_divider.setVisible(False)
        toolbar.addWidget(self.visual_repair_divider)
        toolbar.addWidget(self.btn_index_issues)
        toolbar.addWidget(self.btn_fix_missing_vectors)
        toolbar.addWidget(self.btn_cleanup_missing)
        toolbar.addWidget(self.btn_remove_selected_videos)
        toolbar.addWidget(self.btn_vector_details)
        toolbar.addWidget(self.btn_debug_gpu_oom)
        toolbar.addWidget(self.btn_debug_system_oom)
        toolbar.addWidget(self.visual_video_tree.find_bar)
        toolbar.addWidget(self.btn_stop_index)
        table_layout.addWidget(toolbar_host)
        table_layout.addWidget(self.visual_video_tree, 1)
        self.visual_video_tree.find_bar.install_shortcuts(self.table_card)
        visual_layout.addWidget(self.table_card, 1)

        # --- Panel: subtitle library (one card) ---
        self.dialogue_tab = QWidget()
        dialogue_layout = QVBoxLayout(self.dialogue_tab)
        dialogue_layout.setContentsMargins(0, 8, 0, 0)
        dialogue_layout.setSpacing(0)

        self.dialogue_table_card = VSCard(margins=(16, 14, 16, 14), spacing=12)
        self.dialogue_toolbar_card = self.dialogue_table_card
        dialogue_table_layout = self.dialogue_table_card.content_layout

        self.dialogue_table_title = QLabel()
        self.dialogue_table_title.setObjectName("CardTitle")
        dialogue_table_layout.addWidget(self.dialogue_table_title)

        dialogue_toolbar_host = QWidget()
        dialogue_toolbar_host.setObjectName("LibraryToolbarFlow")
        dialogue_toolbar = FlowLayout(dialogue_toolbar_host, spacing=8)
        self.btn_build_dialogue_index = QPushButton()
        self.btn_build_dialogue_index.setObjectName("PrimaryButton")
        self.btn_reembed_dialogue = QPushButton()
        self.btn_reembed_dialogue.setObjectName("AccentGhostButton")
        self.btn_clear_dialogue = QPushButton()
        self.btn_clear_dialogue.setObjectName("GhostButton")
        self.btn_import_subtitle_srt = QPushButton()
        self.btn_import_subtitle_srt.setObjectName("GhostButton")
        self.btn_export_dialogue = QPushButton()
        self.btn_export_dialogue.setObjectName("GhostButton")
        self.btn_refresh_dialogue_library = QPushButton()
        self.btn_refresh_dialogue_library.setObjectName("GhostButton")
        self.btn_subtitle_sample_advanced = QPushButton()
        self.btn_subtitle_sample_advanced.setObjectName("GhostButton")
        self.btn_subtitle_sample_advanced.setCheckable(True)
        self.btn_subtitle_sample_advanced.setChecked(False)
        self.lbl_subtitle_sample_interval = QLabel()
        self.lbl_subtitle_sample_interval.setObjectName("CardHint")
        self.lbl_subtitle_sample_interval.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.input_subtitle_sample_interval = NoWheelDoubleSpinBox()
        self.input_subtitle_sample_interval.setRange(0.1, 6.0)
        self.input_subtitle_sample_interval.setSingleStep(0.1)
        self.input_subtitle_sample_interval.setDecimals(1)
        self.input_subtitle_sample_interval.setValue(1.2)
        self.input_subtitle_sample_interval.setSuffix(" s")
        self.input_subtitle_sample_interval.setMinimumWidth(88)
        self.input_subtitle_sample_interval.setMaximumWidth(110)
        self.lbl_subtitle_sample_strategy = QLabel()
        self.lbl_subtitle_sample_strategy.setObjectName("CardHint")
        self.lbl_subtitle_sample_strategy.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.input_subtitle_sample_strategy = NoWheelComboBox()
        self.input_subtitle_sample_strategy.setObjectName("SearchModeSelect")
        self.input_subtitle_sample_strategy.setMinimumWidth(120)
        self.input_subtitle_sample_strategy.setMaximumWidth(160)
        self.lbl_subtitle_ocr_batch = QLabel()
        self.lbl_subtitle_ocr_batch.setObjectName("CardHint")
        self.lbl_subtitle_ocr_batch.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.input_subtitle_ocr_batch = NoWheelSpinBox()
        self.input_subtitle_ocr_batch.setRange(1, 6)
        self.input_subtitle_ocr_batch.setSingleStep(1)
        self.input_subtitle_ocr_batch.setValue(6)
        self.input_subtitle_ocr_batch.setMinimumWidth(64)
        self.input_subtitle_ocr_batch.setMaximumWidth(80)
        self.btn_stop_dialogue_index = QPushButton()
        self.btn_stop_dialogue_index.setObjectName("DangerGhostButton")
        self.btn_stop_dialogue_index.setEnabled(False)
        self.btn_stop_dialogue_index.setVisible(False)

        self.subtitle_video_tree = LibraryGroupedVideoTree()
        self.subtitle_video_tree.setMinimumHeight(280)
        self.dialogue_list = self.subtitle_video_tree

        dialogue_toolbar.addWidget(self.btn_build_dialogue_index)
        dialogue_toolbar.addWidget(self.btn_reembed_dialogue)
        dialogue_toolbar.addWidget(self.btn_clear_dialogue)
        dialogue_toolbar.addWidget(self.btn_import_subtitle_srt)
        dialogue_toolbar.addWidget(self.btn_export_dialogue)
        dialogue_toolbar.addWidget(self.btn_refresh_dialogue_library)
        dialogue_toolbar.addWidget(self.btn_subtitle_sample_advanced)
        dialogue_toolbar.addWidget(self.subtitle_video_tree.find_bar)
        dialogue_toolbar.addWidget(self.btn_stop_dialogue_index)
        dialogue_table_layout.addWidget(dialogue_toolbar_host)

        self.subtitle_sample_advanced_row = QWidget()
        advanced_row = QHBoxLayout(self.subtitle_sample_advanced_row)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.setSpacing(8)
        advanced_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.lbl_subtitle_sample_strategy, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.input_subtitle_sample_strategy, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.lbl_subtitle_sample_interval, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.input_subtitle_sample_interval, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.lbl_subtitle_ocr_batch, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.input_subtitle_ocr_batch, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addStretch(1)
        self.subtitle_sample_advanced_row.setVisible(False)
        self.btn_subtitle_sample_advanced.toggled.connect(self.subtitle_sample_advanced_row.setVisible)
        dialogue_table_layout.addWidget(self.subtitle_sample_advanced_row)

        dialogue_table_layout.addWidget(self.subtitle_video_tree, 1)
        self.subtitle_video_tree.find_bar.install_shortcuts(self.dialogue_table_card)
        dialogue_layout.addWidget(self.dialogue_table_card, 1)

        self.library_stack.addWidget(self.visual_tab)
        self.library_stack.addWidget(self.dialogue_tab)
        page_body.addWidget(self.library_stack, 1)

        # Shared progress row (visual indexing + dialogue jobs)
        self.progress_status = VSProgressStatusRow()
        self.progress_bar = self.progress_status.progress_bar
        self.lbl_status = self.progress_status.status_label
        page_body.addWidget(self.progress_status)

        self.set_library_mode(0)

    def set_library_mode(self, index: int) -> None:
        idx = 0 if int(index) <= 0 else 1
        if self.library_stack.currentIndex() != idx:
            self.library_stack.setCurrentIndex(idx)
        self.btn_tab_visual.setChecked(idx == 0)
        self.btn_tab_dialogue.setChecked(idx == 1)

    def library_mode(self) -> int:
        return int(self.library_stack.currentIndex())

