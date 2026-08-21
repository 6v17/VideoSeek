from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTabWidget,  # retained for other pages
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.chunk_timeline import ChunkTimelineWidget
from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.result_table import ResultTable
from ui.widgets.search_results_pager import SearchResultsPager
from ui.widgets.result_view import ResultView
from ui.widgets.results_float_window import ResultsFloatWindow, force_widget_foreground
from ui.widgets.search_presets_bar import SearchPresetsBar
from ui.widgets.scaffold import (
    PageHeader,
    PageScaffold,
    VSCard,
    VSProgressStatusRow,
    make_runtime_banner,
)
from ui.widgets.search_panel import SearchPanel
from ui.widgets.styles import repolish_widget
from ui.widgets.library_video_tree import LibraryGroupedVideoTree
from ui.widgets.searchable_id_combo import SearchableIdCombo
from ui.widgets.video_download_page import VideoDownloadPage

LinkSearchPage = VideoDownloadPage


def _fallback_text(texts, key, zh_text, en_text):
    if key in texts:
        return texts[key]
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(COMPONENT_SIZES["sidebar_width"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)

        self.title = QLabel("VideoSeek")
        self.title.setObjectName("BrandTitle")
        self.subtitle = QLabel("Local video search workspace")
        self.subtitle.setObjectName("BrandSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
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

        self.btn_page_search = self._build_nav_button("Search", checked=True)
        self.btn_page_library = self._build_nav_button("Libraries")
        self.btn_page_understanding = self._build_nav_button("Evidence")
        self.btn_page_link = self._build_nav_button("Link Match")
        self.btn_page_settings = self._build_nav_button("Settings")
        layout.addWidget(self.btn_page_search)
        layout.addWidget(self.btn_page_library)
        layout.addWidget(self.btn_page_understanding)
        layout.addWidget(self.btn_page_link)
        layout.addWidget(self.btn_page_settings)
        self.runtime_hint = QLabel("")
        self.runtime_hint.setObjectName("StatusLabel")
        self.runtime_hint.setWordWrap(True)
        self.runtime_hint.hide()
        layout.addWidget(self.runtime_hint)
        layout.addStretch()

        self.btn_notice = QPushButton("Notes")
        self.btn_notice.setObjectName("SidebarFooterButton")
        self.btn_about = QPushButton("About")
        self.btn_about.setObjectName("SidebarFooterButton")
        self.btn_language = QPushButton("EN")
        self.btn_language.setObjectName("SidebarFooterGhost")

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
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setChecked(checked)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(COMPONENT_SIZES["nav_button_height"])
        return button

    def set_current_page(self, page_name):
        mapping = {
            "search": self.btn_page_search,
            "link": self.btn_page_link,
            "library": self.btn_page_library,
            "understanding": self.btn_page_understanding,
            "settings": self.btn_page_settings,
        }
        for name, button in mapping.items():
            button.setChecked(name == page_name)


class SearchPage(QWidget):
    results_float_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.indexing_notice, self.indexing_notice_text = make_runtime_banner()
        self.indexing_notice.hide()
        page_body.addWidget(self.indexing_notice)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(False)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        compare_row = QHBoxLayout()
        compare_row.setSpacing(12)

        self.search_panel = SearchPanel()
        self.query_card = self.search_panel
        self.lbl_active_model = self.search_panel.lbl_active_model
        self.lbl_text_model_hint = self.search_panel.lbl_text_model_hint
        self.lbl_dialogue_hint = self.search_panel.lbl_dialogue_hint
        self.search_query_tabs = self.search_panel.search_query_tabs
        self.img_label = self.search_panel.img_label
        self.text_search = self.search_panel.text_search
        self.dialogue_search = self.search_panel.dialogue_search
        self.search_mode = self.search_panel.search_mode
        self.search_mode_label = self.search_panel.search_mode_label
        self.image_search_mode = self.search_panel.image_search_mode
        self.image_search_mode_label = self.search_panel.image_search_mode_label
        self.image_search_mode_cluster = self.search_panel.image_search_mode_cluster
        self.dialogue_search_mode = self.search_panel.dialogue_search_mode
        self.dialogue_search_mode_label = self.search_panel.dialogue_search_mode_label
        self.dialogue_search_mode_cluster = self.search_panel.dialogue_search_mode_cluster
        self.text_granularity_cluster = self.search_panel.text_granularity_cluster
        self.search_granularity_cluster = self.search_panel.text_granularity_cluster
        self.search_mode_options_stack = self.search_panel.search_mode_options_stack
        self.mobile_toggle_label = self.search_panel.mobile_toggle_label
        self.btn_mobile_toggle = self.search_panel.btn_mobile_toggle
        self.btn_mobile_qr = self.search_panel.btn_mobile_qr
        self.btn_search = self.search_panel.btn_search
        self.btn_clear = self.search_panel.btn_clear
        self.search_scope_cluster = self.search_panel.search_scope_cluster
        self.search_scope_label = self.search_panel.search_scope_label
        self.search_scope_select = self.search_panel.search_scope_select
        self.options_block = self.search_panel.options_block
        self.options_title = self.search_panel.options_title
        self.mobile_row = self.search_panel.mobile_row
        self.compose_form = self.search_panel.compose_form
        self.btn_save_preset = self.search_panel.btn_save_preset

        self.preview_panel = PreviewPanel()
        self.preview_card = self.preview_panel
        self.preview_title = self.preview_panel.preview_title
        self.preview_host = self.preview_panel.preview_host
        self.preview_host_layout = self.preview_panel.preview_host_layout
        self.preview_placeholder = self.preview_panel.preview_placeholder
        self.expanded_chrome = self.preview_panel.expanded_chrome

        compare_row.addWidget(self.search_panel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        compare_row.addWidget(self.preview_panel, 1, Qt.AlignmentFlag.AlignTop)
        page_body.addLayout(compare_row, 2)
        self._compare_row = compare_row
        self._page_body = page_body
        self._preview_layout_maximized = False

        # Slot stays in the page layout; results_card can reparent into a float window.
        self.results_slot = QWidget()
        self.results_slot.setObjectName("SearchResultsSlot")
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
        self.search_presets_bar = SearchPresetsBar()
        self.btn_manage_presets = QPushButton()
        self.btn_manage_presets.setObjectName("PresetManageButton")
        self.btn_detach_results = QPushButton("弹出窗口")
        self.btn_detach_results.setObjectName("GhostButton")
        self.btn_export_tasks = QPushButton()
        self.btn_export_tasks.setObjectName("GhostButton")
        self.btn_shot_list = QPushButton()
        self.btn_shot_list.setObjectName("GhostButton")

        self.results_actions = QWidget()
        self.results_actions.setObjectName("SearchResultsActions")
        actions_layout = QHBoxLayout(self.results_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        actions_layout.addWidget(self.btn_manage_presets)
        actions_layout.addWidget(self.btn_detach_results)
        actions_layout.addWidget(self.btn_shot_list)
        actions_layout.addWidget(self.btn_export_tasks)

        results_toolbar.addWidget(self.lbl_status, 1)
        results_toolbar.addWidget(self.search_presets_bar, 2)
        results_toolbar.addWidget(self.results_actions, 0)

        self.results_pager = SearchResultsPager()
        self.result_view = ResultView(min_table_height=COMPONENT_SIZES["result_table_min_height"])
        self.result_table = self.result_view.table
        results_layout.addWidget(self.results_title)
        results_layout.addLayout(results_toolbar)
        results_layout.addWidget(self.results_pager, 0, Qt.AlignmentFlag.AlignHCenter)
        results_layout.setSpacing(8)
        results_layout.addWidget(self.result_view)

        # Slim stand-in while results are floated — keep it card-sized, not a full-page banner.
        self.results_float_placeholder = VSCard(margins=(14, 10, 14, 10), spacing=8)
        self.results_float_placeholder.setObjectName("PanelCard")
        self.results_float_placeholder.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.results_float_placeholder.setFixedHeight(52)
        placeholder_layout = self.results_float_placeholder.content_layout
        placeholder_row = QHBoxLayout()
        placeholder_row.setContentsMargins(0, 0, 0, 0)
        placeholder_row.setSpacing(10)
        self.results_float_hint = QLabel()
        self.results_float_hint.setObjectName("Hint")
        self.results_float_hint.setWordWrap(False)
        self.btn_focus_results = QPushButton()
        self.btn_focus_results.setObjectName("AccentGhostButton")
        self.btn_focus_results.setMinimumHeight(30)
        self.btn_dock_results = QPushButton()
        self.btn_dock_results.setObjectName("GhostButton")
        self.btn_dock_results.setMinimumHeight(30)
        placeholder_row.addWidget(self.results_float_hint, 1)
        placeholder_row.addWidget(self.btn_focus_results, 0)
        placeholder_row.addWidget(self.btn_dock_results, 0)
        placeholder_layout.addLayout(placeholder_row)
        self.results_float_placeholder.hide()

        self.results_slot_layout.addWidget(self.results_card)
        page_body.addWidget(self.results_slot, 5)

        self._results_float_window = None
        self._results_float_texts = {
            "title": "检索结果",
            "detach": "弹出窗口",
            "dock": "嵌回主窗口",
            "focus": "返回列表",
            "hint": "检索结果已在独立窗口中显示。",
        }
        self.btn_detach_results.clicked.connect(self.toggle_results_float)
        self.btn_focus_results.clicked.connect(self.focus_results_float)
        self.btn_dock_results.clicked.connect(self.dock_results)
        self._sync_detach_button_label()

    def is_results_floating(self) -> bool:
        window = self._results_float_window
        return window is not None and window.isVisible() and window.is_hosting()

    def set_preview_maximized(self, maximized: bool) -> None:
        """Hide search/results so the shared preview fills the page."""
        maximized = bool(maximized)
        self._preview_layout_maximized = maximized
        self.search_panel.setVisible(not maximized)
        if not self.is_results_floating():
            self.results_slot.setVisible(not maximized)
        self.preview_panel.set_maximized(maximized)
        body = getattr(self, "_page_body", None)
        if body is not None:
            for i in range(body.count()):
                item = body.itemAt(i)
                if item is None:
                    continue
                widget = item.widget()
                layout = item.layout()
                if widget is self.results_slot:
                    body.setStretch(i, 0 if maximized else 5)
                elif layout is getattr(self, "_compare_row", None):
                    body.setStretch(i, 1 if maximized else 2)

    def is_preview_maximized(self) -> bool:
        return bool(self.preview_panel.is_maximized())

    def apply_results_float_texts(self, texts: dict) -> None:
        title = str(texts.get("results_panel", self._results_float_texts["title"]) or "检索结果")
        detach = str(texts.get("results_detach", self._results_float_texts["detach"]) or "弹出窗口")
        dock = str(texts.get("results_dock", self._results_float_texts["dock"]) or "嵌回主窗口")
        focus = str(texts.get("results_focus_list", self._results_float_texts["focus"]) or "返回列表")
        hint = str(
            texts.get("results_float_hint", self._results_float_texts["hint"])
            or "检索结果已在独立窗口中显示。"
        )
        self._results_float_texts = {
            "title": title,
            "detach": detach,
            "dock": dock,
            "focus": focus,
            "hint": hint,
        }
        self.results_float_hint.setText(hint)
        self.btn_focus_results.setText(focus)
        self.btn_focus_results.setToolTip(focus)
        self.btn_dock_results.setText(dock)
        if self._results_float_window is not None:
            self._results_float_window.setWindowTitle(title)
        self._sync_detach_button_label()

    def _sync_detach_button_label(self) -> None:
        floating = self.is_results_floating()
        label = self._results_float_texts["dock" if floating else "detach"]
        self.btn_detach_results.setText(label)
        self.btn_detach_results.setToolTip(label)

    def toggle_results_float(self) -> None:
        if self.is_results_floating():
            self.dock_results()
        else:
            self.float_results()

    def focus_results_float(self) -> None:
        """Bring the floated results window to the front without docking."""
        if not self.is_results_floating():
            return
        window = self._results_float_window
        if window is None:
            return
        force_widget_foreground(window)

    def lower_results_float(self) -> None:
        """Send the floated results window behind other windows (e.g. before preview)."""
        window = self._results_float_window
        if window is None or not window.isVisible():
            return
        window.lower()

    def float_results(self) -> None:
        if self.is_results_floating():
            self.focus_results_float()
            return
        window = self._ensure_results_float_window()
        self.results_slot_layout.removeWidget(self.results_card)
        window.take_card(self.results_card)
        self.results_slot_layout.addWidget(self.results_float_placeholder, 0)
        self.results_slot_layout.addStretch(1)
        self.results_float_placeholder.show()
        window.setWindowTitle(self._results_float_texts["title"])
        force_widget_foreground(window)
        self._sync_detach_button_label()
        self.results_float_changed.emit(True)

    def dock_results(self) -> None:
        window = self._results_float_window
        if window is None or not window.is_hosting():
            self._sync_detach_button_label()
            return
        card = window.release_card()
        window.hide()
        while self.results_slot_layout.count():
            item = self.results_slot_layout.takeAt(0)
            widget = item.widget()
            if widget is self.results_float_placeholder:
                self.results_float_placeholder.hide()
                self.results_float_placeholder.setParent(self)
        if card is not None:
            self.results_slot_layout.addWidget(card)
            card.show()
        self._sync_detach_button_label()
        self.results_float_changed.emit(False)

    def _ensure_results_float_window(self) -> ResultsFloatWindow:
        if self._results_float_window is None:
            # Top-level (no parent) so the float can sit behind the main window on preview.
            self._results_float_window = ResultsFloatWindow(None)
            self._results_float_window.dock_requested.connect(self.dock_results)
        return self._results_float_window

    def shutdown_results_float(self) -> None:
        """Dock back and release the float window (app shutdown)."""
        if self._results_float_window is not None and self._results_float_window.is_hosting():
            self.dock_results()
        window = self._results_float_window
        self._results_float_window = None
        if window is not None:
            window.close()
            window.deleteLater()


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
            return divider

        # Chrome: mode switch + add/remove as one left-packed group, hint underneath
        self.shared_toolbar_card = VSCard(
            variant="sub",
            margins=(14, 12, 14, 12),
            spacing=10,
            object_name="LibrarySharedStrip",
        )
        shared_outer = self.shared_toolbar_card.content_layout

        chrome_row = QHBoxLayout()
        chrome_row.setContentsMargins(0, 0, 0, 0)
        chrome_row.setSpacing(14)
        chrome_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        mode_block = QVBoxLayout()
        mode_block.setContentsMargins(0, 0, 0, 0)
        mode_block.setSpacing(4)
        self.lbl_mode_caption = QLabel()
        self.lbl_mode_caption.setObjectName("LibraryChromeCaption")
        mode_block.addWidget(self.lbl_mode_caption)

        self.mode_segment = QFrame()
        self.mode_segment.setObjectName("LibraryModeSegment")
        mode_row = QHBoxLayout(self.mode_segment)
        mode_row.setContentsMargins(3, 3, 3, 3)
        mode_row.setSpacing(2)
        mode_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.btn_tab_visual = QPushButton()
        self.btn_tab_visual.setObjectName("LibraryModeBtn")
        self.btn_tab_visual.setCheckable(True)
        self.btn_tab_visual.setChecked(True)
        self.btn_tab_visual.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_visual.setMinimumWidth(96)
        self.btn_tab_dialogue = QPushButton()
        self.btn_tab_dialogue.setObjectName("LibraryModeBtn")
        self.btn_tab_dialogue.setCheckable(True)
        self.btn_tab_dialogue.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_tab_dialogue.setMinimumWidth(96)
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
        action_block.setSpacing(4)
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
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
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

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
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
        self.btn_cleanup_missing = QPushButton()
        self.btn_cleanup_missing.setObjectName("GhostButton")
        self.btn_vector_details = QPushButton()
        self.btn_vector_details.setObjectName("GhostButton")
        self.btn_debug_gpu_oom = QPushButton()
        self.btn_debug_gpu_oom.setObjectName("GhostButton")
        self.btn_debug_gpu_oom.setVisible(False)
        self.btn_debug_system_oom = QPushButton()
        self.btn_debug_system_oom.setObjectName("GhostButton")
        self.btn_debug_system_oom.setVisible(False)
        toolbar.addWidget(self.btn_sync_db)
        toolbar.addWidget(self.btn_refresh_visual_library)
        toolbar.addSpacing(4)
        toolbar.addWidget(_toolbar_divider())
        toolbar.addSpacing(4)
        toolbar.addWidget(self.btn_index_issues)
        toolbar.addWidget(self.btn_cleanup_missing)
        toolbar.addWidget(self.btn_vector_details)
        toolbar.addWidget(self.btn_debug_gpu_oom)
        toolbar.addWidget(self.btn_debug_system_oom)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_stop_index)
        table_layout.addLayout(toolbar)

        self.visual_video_tree = LibraryGroupedVideoTree()
        self.visual_video_tree.setMinimumHeight(280)
        self.library_list = self.visual_video_tree
        self.library_column_header_labels = []
        table_layout.addWidget(self.visual_video_tree, 1)
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

        dialogue_toolbar = QHBoxLayout()
        dialogue_toolbar.setSpacing(8)
        self.btn_build_dialogue_index = QPushButton()
        self.btn_build_dialogue_index.setObjectName("PrimaryButton")
        self.btn_reembed_dialogue = QPushButton()
        self.btn_reembed_dialogue.setObjectName("AccentGhostButton")
        self.btn_clear_dialogue = QPushButton()
        self.btn_clear_dialogue.setObjectName("GhostButton")
        self.btn_export_dialogue = QPushButton()
        self.btn_export_dialogue.setObjectName("GhostButton")
        self.btn_refresh_dialogue_library = QPushButton()
        self.btn_refresh_dialogue_library.setObjectName("GhostButton")
        self.lbl_subtitle_sample_interval = QLabel()
        self.lbl_subtitle_sample_interval.setObjectName("CardHint")
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
        self.input_subtitle_sample_strategy = NoWheelComboBox()
        self.input_subtitle_sample_strategy.setObjectName("SearchModeSelect")
        self.input_subtitle_sample_strategy.setMinimumWidth(120)
        self.input_subtitle_sample_strategy.setMaximumWidth(160)
        self.lbl_subtitle_ocr_batch = QLabel()
        self.lbl_subtitle_ocr_batch.setObjectName("CardHint")
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
        dialogue_toolbar.addWidget(self.btn_build_dialogue_index)
        dialogue_toolbar.addWidget(self.btn_reembed_dialogue)
        dialogue_toolbar.addWidget(self.btn_clear_dialogue)
        dialogue_toolbar.addWidget(self.btn_export_dialogue)
        dialogue_toolbar.addWidget(self.btn_refresh_dialogue_library)
        dialogue_toolbar.addSpacing(8)
        dialogue_toolbar.addWidget(self.lbl_subtitle_sample_strategy)
        dialogue_toolbar.addWidget(self.input_subtitle_sample_strategy)
        dialogue_toolbar.addSpacing(8)
        dialogue_toolbar.addWidget(self.lbl_subtitle_sample_interval)
        dialogue_toolbar.addWidget(self.input_subtitle_sample_interval)
        dialogue_toolbar.addSpacing(8)
        dialogue_toolbar.addWidget(self.lbl_subtitle_ocr_batch)
        dialogue_toolbar.addWidget(self.input_subtitle_ocr_batch)
        dialogue_toolbar.addStretch()
        dialogue_toolbar.addWidget(self.btn_stop_dialogue_index)
        dialogue_table_layout.addLayout(dialogue_toolbar)

        self.subtitle_video_tree = LibraryGroupedVideoTree()
        self.subtitle_video_tree.setMinimumHeight(280)
        self.dialogue_list = self.subtitle_video_tree
        dialogue_table_layout.addWidget(self.subtitle_video_tree, 1)
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


def _understanding_field_label(text=""):
    label = QLabel(text)
    label.setObjectName("CardHint")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setFixedWidth(COMPONENT_SIZES.get("understanding_form_label_width", 96))
    return label


def _understanding_value_hint(text=""):
    label = QLabel(text)
    label.setObjectName("CardHint")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    return label


def _understanding_picker_label(text=""):
    label = QLabel(text)
    label.setObjectName("CardHint")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


def _configure_understanding_line_edit(field: QLineEdit, *, width: int):
    field.setMinimumWidth(width)
    field.setMaximumWidth(width)
    field.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


class UnderstandingEvidencePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.understanding_notice, self.understanding_notice_text = make_runtime_banner()
        self.btn_understanding_setup = QPushButton()
        self.btn_understanding_setup.setObjectName("GhostButton")
        self.btn_understanding_setup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_understanding_setup.setMinimumHeight(30)
        self.understanding_notice.layout().addWidget(self.btn_understanding_setup, 0)
        self.understanding_notice.hide()
        page_body.addWidget(self.understanding_notice)

        self.config_card = VSCard(margins=(18, 16, 18, 16), spacing=10)
        config_layout = self.config_card.content_layout

        self.config_header = QFrame()
        self.config_header.setObjectName("UnderstandingConfigHeader")
        self.config_header.setCursor(Qt.CursorShape.PointingHandCursor)
        config_header_layout = QHBoxLayout(self.config_header)
        config_header_layout.setContentsMargins(4, 2, 4, 2)
        config_header_layout.setSpacing(8)
        self.btn_config_collapse = QToolButton()
        self.btn_config_collapse.setObjectName("VideoScopeCollapseBtn")
        self.btn_config_collapse.setAutoRaise(True)
        self.btn_config_collapse.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.config_title = QLabel()
        self.config_title.setObjectName("CardTitle")
        self.config_title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        config_header_layout.addWidget(self.btn_config_collapse, 0)
        config_header_layout.addWidget(self.config_title, 0)
        config_header_layout.addStretch(1)
        config_layout.addWidget(self.config_header)

        self.config_body = QWidget()
        config_body_layout = QVBoxLayout(self.config_body)
        config_body_layout.setContentsMargins(0, 0, 0, 0)
        config_body_layout.setSpacing(10)

        config_form_host = QWidget()
        config_form = QFormLayout(config_form_host)
        config_form.setContentsMargins(0, 0, 0, 0)
        config_form.setHorizontalSpacing(12)
        config_form.setVerticalSpacing(10)
        config_form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        config_form.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        config_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint
        )
        config_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

        self.label_vlm_section = QLabel()
        self.label_vlm_section.setObjectName("CardHint")
        self.label_vlm_section.hide()

        self.label_vlm_provider_mode = _understanding_field_label()
        self.input_vlm_provider_mode = NoWheelComboBox()
        self.input_vlm_provider_mode.setObjectName("SearchModeSelect")
        self.input_vlm_provider_mode.setMinimumWidth(180)
        self.input_vlm_provider_mode.setMaximumWidth(260)
        config_form.addRow(self.label_vlm_provider_mode, self.input_vlm_provider_mode)

        self.label_vlm_provider_preset = _understanding_field_label()
        self.input_vlm_provider_preset = NoWheelComboBox()
        self.input_vlm_provider_preset.setObjectName("SearchModeSelect")
        self.input_vlm_provider_preset.setMinimumWidth(220)
        self.input_vlm_provider_preset.setMaximumWidth(320)
        config_form.addRow(self.label_vlm_provider_preset, self.input_vlm_provider_preset)

        self.hint_vlm_preset_summary = _understanding_value_hint()
        self.hint_vlm_preset_summary.hide()
        config_form.addRow(self.hint_vlm_preset_summary)

        self.label_remote_vlm_api_key = _understanding_field_label()
        self.input_remote_vlm_api_key = QLineEdit()
        self.input_remote_vlm_api_key.setObjectName("SearchInput")
        self.input_remote_vlm_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        _configure_understanding_line_edit(
            self.input_remote_vlm_api_key,
            width=COMPONENT_SIZES.get("settings_path_input_width", 520),
        )
        self.hint_remote_vlm_api_key = QLabel()
        self.hint_remote_vlm_api_key.setObjectName("CardHint")
        self.hint_remote_vlm_api_key.hide()
        config_form.addRow(self.label_remote_vlm_api_key, self.input_remote_vlm_api_key)

        self.label_remote_vlm_base_url = _understanding_field_label()
        self.input_remote_vlm_base_url = QLineEdit()
        self.input_remote_vlm_base_url.setObjectName("SearchInput")
        _configure_understanding_line_edit(
            self.input_remote_vlm_base_url,
            width=COMPONENT_SIZES.get("settings_path_input_width", 520),
        )
        self.hint_remote_vlm_base_url = QLabel()
        self.hint_remote_vlm_base_url.setObjectName("CardHint")
        self.hint_remote_vlm_base_url.hide()
        config_form.addRow(self.label_remote_vlm_base_url, self.input_remote_vlm_base_url)

        self.label_remote_vlm_model = _understanding_field_label()
        self.input_remote_vlm_model = QLineEdit()
        self.input_remote_vlm_model.setObjectName("SearchInput")
        _configure_understanding_line_edit(
            self.input_remote_vlm_model,
            width=COMPONENT_SIZES.get("settings_input_width", 116) + 180,
        )
        self.hint_remote_vlm_model = QLabel()
        self.hint_remote_vlm_model.setObjectName("CardHint")
        self.hint_remote_vlm_model.hide()
        config_form.addRow(self.label_remote_vlm_model, self.input_remote_vlm_model)

        self.label_caption_language = _understanding_field_label()
        self.input_caption_language = NoWheelComboBox()
        self.input_caption_language.setObjectName("SearchModeSelect")
        self.input_caption_language.setMinimumWidth(160)
        self.input_caption_language.setMaximumWidth(220)
        config_form.addRow(self.label_caption_language, self.input_caption_language)

        self.label_understanding_mode = _understanding_field_label()
        self.input_understanding_mode = NoWheelComboBox()
        self.input_understanding_mode.setObjectName("SearchModeSelect")
        self.input_understanding_mode.setMinimumWidth(160)
        self.input_understanding_mode.setMaximumWidth(220)
        config_form.addRow(self.label_understanding_mode, self.input_understanding_mode)

        self.label_caption_concurrency = _understanding_field_label()
        self.input_caption_concurrency = QSpinBox()
        self.input_caption_concurrency.setObjectName("SearchModeSelect")
        self.input_caption_concurrency.setMinimum(1)
        self.input_caption_concurrency.setMaximum(4)
        self.input_caption_concurrency.setMinimumWidth(80)
        self.input_caption_concurrency.setMaximumWidth(120)
        config_form.addRow(self.label_caption_concurrency, self.input_caption_concurrency)

        config_body_layout.addWidget(config_form_host)

        self.prompt_advanced = QFrame()
        self.prompt_advanced.setObjectName("UnderstandingPromptAdvanced")
        prompt_adv_layout = QVBoxLayout(self.prompt_advanced)
        prompt_adv_layout.setContentsMargins(0, 4, 0, 0)
        prompt_adv_layout.setSpacing(8)

        self.chk_use_custom_prompts = QCheckBox()
        prompt_adv_layout.addWidget(self.chk_use_custom_prompts, 0)

        self.custom_prompt_fields = QWidget()
        custom_fields_layout = QVBoxLayout(self.custom_prompt_fields)
        custom_fields_layout.setContentsMargins(0, 0, 0, 0)
        custom_fields_layout.setSpacing(8)

        self.hint_custom_prompts = QLabel()
        self.hint_custom_prompts.setObjectName("CardHint")
        self.hint_custom_prompts.setWordWrap(True)
        custom_fields_layout.addWidget(self.hint_custom_prompts)

        self.label_custom_caption_prompt = _understanding_field_label()
        self.label_custom_caption_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_caption_prompt)
        self.input_custom_caption_prompt = QPlainTextEdit()
        self.input_custom_caption_prompt.setObjectName("SearchInput")
        self.input_custom_caption_prompt.setFixedHeight(72)
        self.input_custom_caption_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_caption_prompt)

        self.label_custom_description_prompt = _understanding_field_label()
        self.label_custom_description_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_description_prompt)
        self.input_custom_description_prompt = QPlainTextEdit()
        self.input_custom_description_prompt.setObjectName("SearchInput")
        self.input_custom_description_prompt.setFixedHeight(72)
        self.input_custom_description_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_description_prompt)

        self.label_custom_summary_prompt = _understanding_field_label()
        self.label_custom_summary_prompt.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        custom_fields_layout.addWidget(self.label_custom_summary_prompt)
        self.input_custom_summary_prompt = QPlainTextEdit()
        self.input_custom_summary_prompt.setObjectName("SearchInput")
        self.input_custom_summary_prompt.setFixedHeight(72)
        self.input_custom_summary_prompt.setTabChangesFocus(True)
        custom_fields_layout.addWidget(self.input_custom_summary_prompt)

        reset_row = QHBoxLayout()
        reset_row.setContentsMargins(0, 0, 0, 0)
        reset_row.setSpacing(8)
        self.btn_reset_custom_prompts = QPushButton()
        self.btn_reset_custom_prompts.setObjectName("GhostButton")
        self.btn_reset_custom_prompts.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset_custom_prompts.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        reset_row.addWidget(self.btn_reset_custom_prompts, 0)
        reset_row.addStretch(1)
        custom_fields_layout.addLayout(reset_row)

        self.custom_prompt_fields.hide()
        prompt_adv_layout.addWidget(self.custom_prompt_fields)
        config_body_layout.addWidget(self.prompt_advanced)

        config_footer = QHBoxLayout()
        config_footer.setSpacing(10)
        self.hint_understanding_status = QLabel()
        self.hint_understanding_status.setObjectName("StatusHint")
        self.hint_understanding_status.setWordWrap(True)
        self.btn_save_config = QPushButton()
        self.btn_save_config.setObjectName("PrimaryButton")
        self.btn_save_config.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_config.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        config_footer.addWidget(self.hint_understanding_status, 1)
        self.btn_test_vlm_connection = QPushButton()
        self.btn_test_vlm_connection.setObjectName("GhostButton")
        self.btn_test_vlm_connection.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_test_vlm_connection.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        config_footer.addWidget(self.btn_test_vlm_connection, 0)
        config_footer.addWidget(self.btn_save_config, 0)
        config_body_layout.addLayout(config_footer)
        config_layout.addWidget(self.config_body)

        self.config_header.installEventFilter(self)
        self._config_expanded = False
        self._set_config_expanded(False)
        page_body.addWidget(self.config_card)

        self.workspace_card = VSCard(margins=(18, 16, 18, 16), spacing=12)
        workspace_layout = self.workspace_card.content_layout
        self.workspace_title = QLabel()
        self.workspace_title.setObjectName("CardTitle")
        workspace_layout.addWidget(self.workspace_title)

        self.picker_strip = QFrame()
        self.picker_strip.setObjectName("UnderstandingToolbar")
        picker_outer = QHBoxLayout(self.picker_strip)
        picker_outer.setContentsMargins(12, 10, 12, 10)
        picker_outer.setSpacing(12)

        picker_fields = QHBoxLayout()
        picker_fields.setContentsMargins(0, 0, 0, 0)
        picker_fields.setSpacing(8)
        picker_fields.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.scope_label = _understanding_picker_label()
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("SearchModeSelect")
        self.scope_combo.setMinimumWidth(180)
        self.scope_combo.setMaximumWidth(280)
        self.scope_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.video_label = _understanding_picker_label()
        self.video_combo = SearchableIdCombo()
        self.video_combo.setMinimumWidth(240)
        self.video_combo.setMaximumWidth(520)
        self.video_combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        picker_fields.addWidget(self.scope_label, 0)
        picker_fields.addWidget(self.scope_combo, 0)
        picker_fields.addSpacing(6)
        picker_fields.addWidget(self.video_label, 0)
        picker_fields.addWidget(self.video_combo, 0)
        picker_fields.addStretch(1)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        action_row.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.btn_generate_evidence = QPushButton()
        self.btn_generate_evidence.setObjectName("PrimaryButton")
        self.btn_generate_evidence.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate_evidence.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_generate_batch = QPushButton()
        self.btn_generate_batch.setObjectName("GhostButton")
        self.btn_generate_batch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate_batch.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_generate_summary = QPushButton()
        self.btn_generate_summary.setObjectName("GhostButton")
        self.btn_generate_summary.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_generate_summary.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_generate_summary.hide()
        self.btn_evidence_details = QPushButton()
        self.btn_evidence_details.setObjectName("GhostButton")
        self.btn_evidence_details.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_evidence_details.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_export_video_json = QPushButton()
        self.btn_export_video_json.setObjectName("GhostButton")
        self.btn_export_video_json.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_export_video_json.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_stop = QPushButton()
        self.btn_stop.setObjectName("DangerGhostButton")
        self.btn_stop.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        self.btn_stop.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        action_row.addWidget(self.btn_generate_evidence, 0)
        action_row.addWidget(self.btn_generate_batch, 0)
        action_row.addWidget(self.btn_evidence_details, 0)
        action_row.addWidget(self.btn_export_video_json, 0)
        action_row.addWidget(self.btn_stop, 0)

        picker_outer.addLayout(picker_fields, 1)
        picker_outer.addLayout(action_row, 0)
        workspace_layout.addWidget(self.picker_strip)

        timeline_block = QFrame()
        timeline_block.setObjectName("UnderstandingTimelineBlock")
        timeline_layout = QVBoxLayout(timeline_block)
        timeline_layout.setContentsMargins(12, 10, 12, 10)
        timeline_layout.setSpacing(8)

        timeline_header = QHBoxLayout()
        timeline_header.setSpacing(8)
        self.timeline_label = QLabel()
        self.timeline_label.setObjectName("CardHint")
        self.timeline_hint = QLabel()
        self.timeline_hint.setObjectName("StatusHint")
        # Fixed single-line slot so hint text length does not shove the track.
        self.timeline_hint.setWordWrap(False)
        self.timeline_hint.setFixedHeight(18)
        timeline_header.addWidget(self.timeline_label, 0)
        timeline_header.addWidget(self.timeline_hint, 1)
        timeline_layout.addLayout(timeline_header)

        self.chunk_timeline_scroll = QScrollArea()
        self.chunk_timeline_scroll.setObjectName("ChunkTimelineScroll")
        self.chunk_timeline_scroll.setWidgetResizable(False)
        # Reserve the horizontal bar slot so first content load does not steal height.
        self.chunk_timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.chunk_timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chunk_timeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chunk_timeline_scroll.setFixedHeight(56)
        self.chunk_timeline = ChunkTimelineWidget()
        self.chunk_timeline.setFixedHeight(32)
        self.chunk_timeline_scroll.setWidget(self.chunk_timeline)
        timeline_layout.addWidget(self.chunk_timeline_scroll)
        workspace_layout.addWidget(timeline_block)

        detail_host = QWidget()
        detail_row = QHBoxLayout(detail_host)
        detail_row.setContentsMargins(0, 0, 0, 0)
        detail_row.setSpacing(12)

        self.chunk_detail_card = VSCard(
            variant="sub",
            margins=(14, 12, 14, 12),
            spacing=8,
            object_name="UnderstandingDetailPanel",
        )
        chunk_detail_layout = self.chunk_detail_card.content_layout
        segment_header = QHBoxLayout()
        segment_header.setContentsMargins(0, 0, 0, 0)
        segment_header.setSpacing(10)
        self.chunk_detail_title = QLabel()
        self.chunk_detail_title.setObjectName("CardTitle")
        self.chunk_time_label = QLabel()
        self.chunk_time_label.setObjectName("UnderstandingChunkTimeLabel")
        self.chunk_time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        segment_header.addWidget(self.chunk_detail_title, 0)
        segment_header.addStretch(1)
        segment_header.addWidget(self.chunk_time_label, 0)
        chunk_detail_layout.addLayout(segment_header)
        self.chunk_caption_text = QPlainTextEdit()
        self.chunk_caption_text.setObjectName("UnderstandingOutput")
        self.chunk_caption_text.setReadOnly(True)
        self.chunk_caption_text.setMinimumHeight(148)
        self.chunk_caption_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.chunk_caption_text.setPlaceholderText("")
        chunk_detail_layout.addWidget(self.chunk_caption_text, 1)

        self.video_summary_card = VSCard(
            variant="sub",
            margins=(14, 12, 14, 12),
            spacing=8,
            object_name="UnderstandingDetailPanel",
        )
        summary_layout = self.video_summary_card.content_layout
        summary_header = QHBoxLayout()
        summary_header.setContentsMargins(0, 0, 0, 0)
        summary_header.setSpacing(8)
        self.video_summary_title = QLabel()
        self.video_summary_title.setObjectName("CardTitle")
        summary_header.addWidget(self.video_summary_title, 0)
        summary_header.addStretch(1)
        summary_layout.addLayout(summary_header)
        self.video_summary_text = QPlainTextEdit()
        self.video_summary_text.setObjectName("UnderstandingOutput")
        self.video_summary_text.setReadOnly(True)
        self.video_summary_text.setMinimumHeight(148)
        self.video_summary_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        summary_layout.addWidget(self.video_summary_text, 1)
        self.video_summary_meta_label = QLabel()
        self.video_summary_meta_label.setObjectName("StatusHint")
        self.video_summary_meta_label.setWordWrap(True)
        self.video_summary_meta_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        summary_layout.addWidget(self.video_summary_meta_label)

        detail_row.addWidget(self.chunk_detail_card, 1)
        detail_row.addWidget(self.video_summary_card, 1)
        workspace_layout.addWidget(detail_host, 1)

        self.lbl_understanding_hint = QLabel()
        self.lbl_understanding_hint.setObjectName("UnderstandingChromeHint")
        self.lbl_understanding_hint.setWordWrap(True)
        workspace_layout.addWidget(self.lbl_understanding_hint)

        self.progress_status = VSProgressStatusRow()
        self.progress_bar = self.progress_status.progress_bar
        self.lbl_status = self.progress_status.status_label
        self.progress_bar.setVisible(False)
        workspace_layout.addWidget(self.progress_status)
        workspace_layout.addStretch(0)
        page_body.addWidget(self.workspace_card, 0)
        page_body.addStretch(1)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "config_header", None) and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                self._toggle_config_panel()
                return True
        return super().eventFilter(obj, event)

    def _set_config_expanded(self, expanded: bool) -> None:
        self._config_expanded = bool(expanded)
        self.config_body.setVisible(self._config_expanded)
        self.btn_config_collapse.setArrowType(
            Qt.ArrowType.DownArrow if self._config_expanded else Qt.ArrowType.RightArrow
        )
        header = getattr(self, "config_header", None)
        if header is not None:
            header.setProperty("expanded", "true" if self._config_expanded else "false")
            repolish_widget(header)

    def _toggle_config_panel(self) -> None:
        self._set_config_expanded(not self._config_expanded)

    def expand_config_panel(self) -> None:
        self._set_config_expanded(True)

