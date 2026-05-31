from typing import Optional

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.result_table import LinkResultTable, ResultTable
from ui.widgets.result_view import ResultView
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


class NavigationSidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(COMPONENT_SIZES["sidebar_width"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

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
        hero_layout.setContentsMargins(14, 14, 14, 14)
        hero_layout.setSpacing(6)
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
        self.btn_page_link = self._build_nav_button("Link Match")
        self.btn_page_settings = self._build_nav_button("Settings")
        layout.addWidget(self.btn_page_search)
        layout.addWidget(self.btn_page_library)
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
        self.btn_theme = QPushButton("Dark")
        self.btn_theme.setObjectName("SidebarFooterButton")

        for button in [self.btn_notice, self.btn_about, self.btn_language, self.btn_theme]:
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(COMPONENT_SIZES["sidebar_action_height"])
            layout.addWidget(button)

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
            "settings": self.btn_page_settings,
        }
        for name, button in mapping.items():
            button.setChecked(name == page_name)


class SearchPage(QWidget):
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
        self.lbl_status.setWordWrap(True)

        compare_row = QHBoxLayout()
        compare_row.setSpacing(12)

        self.search_panel = SearchPanel()
        self.query_card = self.search_panel
        self.search_query_tabs = self.search_panel.search_query_tabs
        self.img_label = self.search_panel.img_label
        self.text_search = self.search_panel.text_search
        self.search_mode = self.search_panel.search_mode
        self.search_mode_label = self.search_panel.search_mode_label
        self.search_precision_toggle = self.search_panel.search_precision_toggle
        self.search_precision_label = self.search_panel.search_precision_label
        self.search_precision_cluster = self.search_panel.search_precision_cluster
        self.text_granularity_cluster = self.search_panel.text_granularity_cluster
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

        compare_row.addWidget(self.search_panel, 5, Qt.AlignmentFlag.AlignTop)
        compare_row.addWidget(self.preview_panel, 7, Qt.AlignmentFlag.AlignTop)
        page_body.addLayout(compare_row, 3)

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
        self.btn_expand_preview = QPushButton()
        self.btn_expand_preview.setObjectName("GhostButton")
        self.btn_export_tasks = QPushButton()
        self.btn_export_tasks.setObjectName("GhostButton")

        self.results_actions = QWidget()
        self.results_actions.setObjectName("SearchResultsActions")
        actions_layout = QHBoxLayout(self.results_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        actions_layout.addWidget(self.btn_manage_presets)
        actions_layout.addWidget(self.btn_expand_preview)
        actions_layout.addWidget(self.btn_export_tasks)

        results_toolbar.addWidget(self.lbl_status, 2)
        results_toolbar.addWidget(self.search_presets_bar, 3)
        results_toolbar.addWidget(self.results_actions, 0)

        self.result_view = ResultView(min_table_height=COMPONENT_SIZES["result_table_min_height"])
        self.result_table = self.result_view.table
        results_layout.addWidget(self.results_title)
        results_layout.addLayout(results_toolbar)
        results_layout.addWidget(self.result_view)
        page_body.addWidget(self.results_card, 4)


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

        self.toolbar_card = VSCard(margins=(18, 16, 18, 16), spacing=10)
        toolbar_card_layout = self.toolbar_card.content_layout

        def _toolbar_divider():
            divider = QFrame()
            divider.setFrameShape(QFrame.VLine)
            divider.setFrameShadow(QFrame.Plain)
            divider.setObjectName("ToolbarDivider")
            return divider

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.btn_add_lib = QPushButton()
        self.btn_add_lib.setObjectName("UpdateButton")
        self.btn_sync_db = QPushButton()
        self.btn_sync_db.setObjectName("PrimaryButton")
        self.btn_rebuild_index_vectors = QPushButton()
        self.btn_rebuild_index_vectors.setObjectName("GhostButton")
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
        toolbar.addWidget(self.btn_add_lib)
        toolbar.addWidget(self.btn_sync_db)
        toolbar.addWidget(self.btn_rebuild_index_vectors)
        toolbar.addSpacing(4)
        toolbar.addWidget(_toolbar_divider())
        toolbar.addSpacing(4)
        toolbar.addWidget(self.btn_index_issues)
        toolbar.addSpacing(4)
        toolbar.addWidget(_toolbar_divider())
        toolbar.addSpacing(4)
        toolbar.addWidget(self.btn_cleanup_missing)
        toolbar.addWidget(self.btn_vector_details)
        toolbar.addWidget(self.btn_debug_gpu_oom)
        toolbar.addWidget(self.btn_debug_system_oom)
        toolbar.addStretch()
        toolbar.addWidget(self.btn_stop_index)

        self.progress_status = VSProgressStatusRow()
        self.progress_bar = self.progress_status.progress_bar
        self.lbl_status = self.progress_status.status_label

        toolbar_card_layout.addLayout(toolbar)
        toolbar_card_layout.addWidget(self.progress_status)
        page_body.addWidget(self.toolbar_card)

        self.table_card = VSCard()
        table_layout = self.table_card.content_layout
        self.table_title = QLabel()
        self.table_title.setObjectName("CardTitle")
        self.library_column_header = QFrame()
        self.library_column_header.setObjectName("LibraryListColumnHeader")
        header_row = QHBoxLayout(self.library_column_header)
        header_row.setContentsMargins(16, 0, 16, 8)
        header_row.setSpacing(14)
        self.library_column_header_labels = []
        for spec in (
            ("index", 40, 0),
            ("path", 0, 1),
            ("state", 100, 0),
            ("actions", 200, 0),
        ):
            _, min_w, stretch = spec
            cell = QLabel("")
            cell.setObjectName("LibraryListHeaderCell")
            cell.setAlignment(Qt.AlignCenter)
            if min_w:
                cell.setMinimumWidth(min_w)
            self.library_column_header_labels.append(cell)
            header_row.addWidget(cell, stretch)
        self.library_scroll = QScrollArea()
        self.library_scroll.setObjectName("LibraryListScroll")
        self.library_scroll.setWidgetResizable(True)
        self.library_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.library_scroll.setFrameShape(QFrame.NoFrame)
        self.library_scroll.setMinimumHeight(300)
        self.library_list = QWidget()
        self.library_list.setObjectName("LibraryListHost")
        _list_layout = QVBoxLayout(self.library_list)
        _list_layout.setContentsMargins(0, 0, 0, 0)
        _list_layout.setSpacing(10)
        self.library_list._column_headers = self.library_column_header_labels
        self.library_scroll.setWidget(self.library_list)
        table_layout.addWidget(self.table_title)
        table_layout.addWidget(self.library_column_header)
        table_layout.addWidget(self.library_scroll, 1)
        page_body.addWidget(self.table_card, 1)



class LinkSearchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.notice_card = VSCard(variant="notice", margins=(16, 12, 16, 12), spacing=0)
        notice_layout = self.notice_card.content_layout
        self.notice_body = QLabel()
        self.notice_body.setObjectName("NoticeBody")
        self.notice_body.setWordWrap(True)
        notice_layout.addWidget(self.notice_body)
        page_body.addWidget(self.notice_card)

        self.control_card = VSCard(spacing=12)
        control_layout = self.control_card.content_layout

        self.input_link = QLineEdit()
        self.input_link.setObjectName("SearchInput")
        self.query_image_label = QLabel()
        self.query_image_label.setObjectName("ImageDropZone")
        self.query_image_label.setAlignment(Qt.AlignCenter)
        self.query_image_label.setWordWrap(True)
        self.query_image_label.setFixedHeight(COMPONENT_SIZES.get("link_query_preview_min_height", 210))
        self.query_image_label.setMinimumWidth(0)
        self.query_image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("CardHint")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("SearchModeSelect")
        self.mode_combo.setFixedWidth(COMPONENT_SIZES["settings_input_width"] + 72)
        self.build_links_input = QTextEdit()
        self.build_links_input.setObjectName("SearchInput")
        self.build_links_input.setMinimumHeight(140)
        mode_row.addWidget(self.mode_label)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()

        self.btn_build = QPushButton()
        self.btn_build.setObjectName("PrimaryButton")
        self.btn_build.setMinimumWidth(126)
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("SearchButton")
        self.btn_run.setMinimumWidth(156)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        self.btn_clear.setMinimumWidth(98)
        self.btn_import = QPushButton()
        self.btn_import.setObjectName("NeutralToolButton")
        self.btn_import.setMinimumWidth(126)
        self.btn_export = QPushButton()
        self.btn_export.setObjectName("NeutralToolButton")
        self.btn_export.setMinimumWidth(126)
        self.btn_link_details = QPushButton()
        self.btn_link_details.setObjectName("AccentGhostButton")
        self.btn_link_details.setMinimumWidth(126)
        self.btn_open_cache = QPushButton()
        self.btn_open_cache.setObjectName("NeutralToolButton")
        self.btn_open_cache.setMinimumWidth(126)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(COMPONENT_SIZES["progress_bar_height"])
        self.progress_bar.setVisible(False)

        self.build_title = QLabel()
        self.build_title.setObjectName("CardTitle")
        self.build_hint = QLabel()
        self.build_hint.setObjectName("CardHint")
        self.build_hint.setWordWrap(True)
        self.search_title = QLabel()
        self.search_title.setObjectName("CardTitle")
        self.search_hint = QLabel()
        self.search_hint.setObjectName("CardHint")
        self.search_hint.setWordWrap(True)
        self.lbl_build_status = QLabel()
        self.lbl_build_status.setObjectName("StatusLabel")
        self.lbl_build_status.setWordWrap(True)
        self.lbl_search_status = QLabel()
        self.lbl_search_status.setObjectName("StatusLabel")
        self.lbl_search_status.setWordWrap(True)

        build_utility_row = QGridLayout()
        build_utility_row.setHorizontalSpacing(8)
        build_utility_row.setVerticalSpacing(8)
        build_utility_row.addWidget(self.btn_build, 0, 0)
        build_utility_row.addWidget(self.btn_import, 0, 1)
        build_utility_row.addWidget(self.btn_export, 0, 2)
        build_utility_row.addWidget(self.btn_link_details, 1, 0)
        build_utility_row.addWidget(self.btn_open_cache, 1, 1)
        build_utility_row.setColumnStretch(0, 1)
        build_utility_row.setColumnStretch(1, 1)
        build_utility_row.setColumnStretch(2, 1)

        build_status_row = QHBoxLayout()
        build_status_row.setSpacing(12)
        build_status_row.addWidget(self.progress_bar, 2)
        build_status_row.addWidget(self.lbl_build_status, 3)

        build_panel = QWidget()
        build_layout = QVBoxLayout(build_panel)
        build_layout.setContentsMargins(0, 0, 0, 0)
        build_layout.setSpacing(10)
        build_layout.addWidget(self.build_title)
        build_layout.addWidget(self.build_hint)
        build_layout.addWidget(self.build_links_input)
        build_layout.addLayout(mode_row)
        build_layout.addLayout(build_utility_row)
        build_layout.addLayout(build_status_row)

        search_action_row = QHBoxLayout()
        search_action_row.setSpacing(8)
        search_action_row.addWidget(self.btn_run, 1)
        search_action_row.addWidget(self.btn_clear)

        search_panel = QWidget()
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        search_layout.addWidget(self.search_title)
        search_layout.addWidget(self.search_hint)
        search_layout.addWidget(self.input_link)
        search_layout.addWidget(self.query_image_label)
        search_layout.addLayout(search_action_row)
        search_layout.addWidget(self.lbl_search_status)

        section_row = QHBoxLayout()
        section_row.setSpacing(16)
        section_row.addWidget(build_panel, 1)
        section_row.addWidget(search_panel, 1)

        control_layout.addLayout(section_row)
        self.controls_title = self.build_title
        self.controls_hint = self.build_hint
        self.lbl_status = self.lbl_search_status
        page_body.addWidget(self.control_card)

        self.results_card = VSCard()
        results_layout = self.results_card.content_layout
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.result_view = ResultView(
            table=LinkResultTable(),
            min_table_height=COMPONENT_SIZES["result_table_min_height"],
        )
        self.result_table = self.result_view.table
        results_layout.addWidget(self.results_title)
        results_layout.addWidget(self.result_view)
        page_body.addWidget(self.results_card, 1)


