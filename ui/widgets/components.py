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
from ui.widgets.remix_scope_tree import RemixScopeTreeWidget
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.result_table import LinkResultTable, RemixResultTable, ResultTable
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

# Remix match parameter presets (see remix_preset_guide_* in i18n).
# Tuned for industrial-style QC: favor precision and stable line fits over marginal speed.
REMIX_PRESETS = {
    "strict": {
        "sample_fps": 2.0,
        "score_threshold": 0.33,
        "merge_gap": 1.75,
        "min_segment": 2.5,
        "remix_cluster_gap": 1.75,
        "faiss_top_k": 36,
        "speed_min": 0.35,
        "speed_max": 3.5,
        "ransac_iters": 1024,
        "min_line_points": 4,
    },
    "standard": {
        "sample_fps": 2.0,
        "score_threshold": 0.28,
        "merge_gap": 2.15,
        "min_segment": 2.0,
        "remix_cluster_gap": 2.1,
        "faiss_top_k": 44,
        "speed_min": 0.28,
        "speed_max": 3.5,
        "ransac_iters": 512,
        "min_line_points": 3,
    },
    "loose": {
        "sample_fps": 2.0,
        "score_threshold": 0.24,
        "merge_gap": 2.55,
        "min_segment": 1.2,
        "remix_cluster_gap": 2.35,
        "faiss_top_k": 56,
        "speed_min": 0.22,
        "speed_max": 6.0,
        "ransac_iters": 1536,
        "min_line_points": 2,
    },
}


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


class RemixDisclosureHeader(QWidget):
    """Single-row disclosure header: title + fold arrow (Qt style), entire row toggles expand/collapse."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RemixDisclosureHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._toggle = None
        self._expanded = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(10)

        self.title_label = QLabel()
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._fold_btn = QToolButton()
        self._fold_btn.setObjectName("RemixDisclosureChevronBtn")
        self._fold_btn.setAutoRaise(True)
        self._fold_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fold_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fold_btn.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        lay.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._fold_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self.set_expanded(False)

    def set_toggle_handler(self, handler):
        self._toggle = handler

    def set_expanded(self, expanded: bool):
        self._expanded = bool(expanded)
        # Same idiom as library scope cards: right arrow = collapsed, down = expanded.
        self._fold_btn.setArrowType(Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            if callable(self._toggle):
                self._toggle()
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
        self.btn_page_remix = self._build_nav_button("Remix", checked=False)
        self.btn_page_link = self._build_nav_button("Link Match")
        self.btn_page_settings = self._build_nav_button("Settings")
        layout.addWidget(self.btn_page_search)
        layout.addWidget(self.btn_page_library)
        layout.addWidget(self.btn_page_remix)
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
            "remix": self.btn_page_remix,
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

        self.session_card = VSCard(margins=(18, 12, 18, 12), spacing=12)
        session_layout = QHBoxLayout()
        session_layout.setSpacing(12)
        self.session_title = QLabel()
        self.session_title.setObjectName("CardTitle")
        self.session_hint = QLabel()
        self.session_hint.setObjectName("CardHint")
        self.session_hint.setWordWrap(True)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        session_layout.addWidget(self.session_title, 0)
        session_layout.addWidget(self.session_hint, 1)
        session_layout.addWidget(self.lbl_status, 1)
        self.session_card.content_layout.addLayout(session_layout)
        page_body.addWidget(self.session_card)

        compare_row = QHBoxLayout()
        compare_row.setSpacing(12)

        self.search_panel = SearchPanel()
        self.query_card = self.search_panel
        self.controls_title = self.search_panel.controls_title
        self.controls_hint = self.search_panel.controls_hint
        self.img_label = self.search_panel.img_label
        self.text_search = self.search_panel.text_search
        self.search_mode = self.search_panel.search_mode
        self.search_mode_label = self.search_panel.search_mode_label
        self.mobile_toggle_label = self.search_panel.mobile_toggle_label
        self.btn_mobile_toggle = self.search_panel.btn_mobile_toggle
        self.btn_mobile_qr = self.search_panel.btn_mobile_qr
        self.btn_search = self.search_panel.btn_search
        self.btn_clear = self.search_panel.btn_clear
        self.search_scope_cluster = self.search_panel.search_scope_cluster
        self.search_scope_label = self.search_panel.search_scope_label
        self.search_scope_select = self.search_panel.search_scope_select

        self.preview_panel = PreviewPanel()
        self.preview_card = self.preview_panel
        self.preview_title = self.preview_panel.preview_title
        self.preview_host = self.preview_panel.preview_host
        self.preview_host_layout = self.preview_panel.preview_host_layout
        self.preview_placeholder = self.preview_panel.preview_placeholder

        compare_row.addWidget(self.search_panel, 5)
        compare_row.addWidget(self.preview_panel, 7)
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

        results_toolbar.addWidget(self.search_presets_bar, 1)
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


class RemixMatchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.match_activity_notice, self.match_activity_text = make_runtime_banner()
        self.match_activity_notice.hide()
        page_body.addWidget(self.match_activity_notice)

        spin_w = max(104, COMPONENT_SIZES.get("settings_input_width", 116) + 8)

        def make_divider():
            line = QFrame()
            line.setObjectName("RemixSectionDivider")
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Plain)
            line.setFixedHeight(1)
            return line

        self.mix_label = QLabel()
        self.mix_label.setObjectName("CardTitle")
        self.mix_hint = QLabel()
        self.mix_hint.setObjectName("CardHint")
        self.mix_hint.setWordWrap(True)
        self.mix_path_frame = QFrame()
        self.mix_path_frame.setObjectName("RemixMixPathRow")
        mix_inner = QHBoxLayout(self.mix_path_frame)
        mix_inner.setContentsMargins(0, 0, 0, 0)
        mix_inner.setSpacing(0)
        self.input_mix_path = QLineEdit()
        self.input_mix_path.setObjectName("RemixMixPathEdit")
        self.input_mix_path.setFrame(False)
        self.input_mix_path.setClearButtonEnabled(True)
        self.input_mix_path.setMinimumHeight(42)
        self.btn_browse_mix = QPushButton()
        self.btn_browse_mix.setObjectName("RemixMixBrowseBtn")
        self.btn_browse_mix.setMinimumWidth(108)
        self.btn_browse_mix.setMinimumHeight(42)
        self.btn_browse_mix.setCursor(Qt.CursorShape.PointingHandCursor)
        mix_inner.addWidget(self.input_mix_path, 1)
        mix_inner.addWidget(self.btn_browse_mix, 0)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("PrimaryButton")
        self.btn_run.setMinimumWidth(140)
        self.btn_stop = QPushButton()
        self.btn_stop.setObjectName("DangerGhostButton")
        self.btn_stop.setMinimumWidth(100)
        self.btn_stop.setEnabled(False)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("GhostButton")
        action_row.addWidget(self.btn_run)
        action_row.addWidget(self.btn_stop)
        action_row.addWidget(self.btn_clear)
        action_row.addStretch(1)
        self.match_progress = QProgressBar()
        self.match_progress.setObjectName("ProgressBar")
        self.match_progress.setTextVisible(False)
        self.match_progress.setMinimum(0)
        self.match_progress.setMaximum(100)
        self.match_progress.hide()
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)

        self.remix_source_card = VSCard(spacing=12)
        source_layout = self.remix_source_card.content_layout
        source_layout.addWidget(self.mix_label)
        source_layout.addWidget(self.mix_hint)
        source_layout.addWidget(self.mix_path_frame)
        source_layout.addWidget(make_divider())
        source_layout.addLayout(action_row)
        source_layout.addWidget(self.match_progress)
        source_layout.addWidget(self.lbl_status)

        self.params_disclosure = RemixDisclosureHeader()
        self.params_disclosure.set_toggle_handler(self._toggle_remix_params_visible)
        self.section_params_title = self.params_disclosure.title_label
        self._remix_params_expanded = False

        self._remix_param_popup = SettingDetailPopup(is_dark=True)
        self._remix_param_bindings: list = []
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.installEventFilter(self._remix_param_popup)

        params = QGridLayout()
        params.setHorizontalSpacing(14)
        params.setVerticalSpacing(4)
        params.setColumnMinimumWidth(0, 220)
        params.setColumnStretch(1, 1)

        def bind_lbl(lbl: ClickableLabel, hint: QLabel):
            hint.setVisible(False)
            self._remix_param_bindings.append((lbl, hint))
            lbl.setWordWrap(True)
            lbl.set_click_handler(lambda _l=lbl, h=hint: self._activate_remix_param_detail(_l, h))

        self.lbl_sample_fps = ClickableLabel()
        self.hint_sample_fps = QLabel()
        bind_lbl(self.lbl_sample_fps, self.hint_sample_fps)
        self.input_sample_fps = NoWheelDoubleSpinBox()
        self.input_sample_fps.setRange(0.1, 12.0)
        self.input_sample_fps.setDecimals(2)
        self.input_sample_fps.setSingleStep(0.1)
        self.input_sample_fps.setValue(2.0)

        self.lbl_score = ClickableLabel()
        self.hint_score = QLabel()
        bind_lbl(self.lbl_score, self.hint_score)
        self.input_score_threshold = NoWheelDoubleSpinBox()
        self.input_score_threshold.setRange(0.05, 0.99)
        self.input_score_threshold.setDecimals(2)
        self.input_score_threshold.setSingleStep(0.02)
        self.input_score_threshold.setValue(0.26)

        self.lbl_gap = ClickableLabel()
        self.hint_gap = QLabel()
        bind_lbl(self.lbl_gap, self.hint_gap)
        self.input_merge_gap = NoWheelDoubleSpinBox()
        self.input_merge_gap.setRange(0.2, 30.0)
        self.input_merge_gap.setDecimals(1)
        self.input_merge_gap.setSingleStep(0.5)
        self.input_merge_gap.setValue(2.5)

        self.lbl_min_seg = ClickableLabel()
        self.hint_min_seg = QLabel()
        bind_lbl(self.lbl_min_seg, self.hint_min_seg)
        self.input_min_segment = NoWheelDoubleSpinBox()
        self.input_min_segment.setRange(0.0, 120.0)
        self.input_min_segment.setDecimals(1)
        self.input_min_segment.setSingleStep(0.5)
        self.input_min_segment.setValue(1.5)

        self.lbl_remix_cluster = ClickableLabel()
        self.hint_remix_cluster = QLabel()
        bind_lbl(self.lbl_remix_cluster, self.hint_remix_cluster)
        self.input_remix_cluster_gap = NoWheelDoubleSpinBox()
        self.input_remix_cluster_gap.setRange(0.1, 90.0)
        self.input_remix_cluster_gap.setDecimals(1)
        self.input_remix_cluster_gap.setSingleStep(0.5)
        self.input_remix_cluster_gap.setValue(2.5)

        self.lbl_faiss_top_k = ClickableLabel()
        self.hint_faiss_top_k = QLabel()
        bind_lbl(self.lbl_faiss_top_k, self.hint_faiss_top_k)
        self.input_faiss_top_k = NoWheelSpinBox()
        self.input_faiss_top_k.setRange(1, 200)
        self.input_faiss_top_k.setValue(48)

        self.lbl_speed_min = ClickableLabel()
        self.hint_speed_min = QLabel()
        bind_lbl(self.lbl_speed_min, self.hint_speed_min)
        self.input_speed_min = NoWheelDoubleSpinBox()
        self.input_speed_min.setRange(0.05, 3.0)
        self.input_speed_min.setDecimals(2)
        self.input_speed_min.setSingleStep(0.05)
        self.input_speed_min.setValue(0.25)

        self.lbl_speed_max = ClickableLabel()
        self.hint_speed_max = QLabel()
        bind_lbl(self.lbl_speed_max, self.hint_speed_max)
        self.input_speed_max = NoWheelDoubleSpinBox()
        self.input_speed_max.setRange(0.5, 12.0)
        self.input_speed_max.setDecimals(2)
        self.input_speed_max.setSingleStep(0.1)
        self.input_speed_max.setValue(4.0)

        self.lbl_ransac_iters = ClickableLabel()
        self.hint_ransac_iters = QLabel()
        bind_lbl(self.lbl_ransac_iters, self.hint_ransac_iters)
        self.input_ransac_iters = NoWheelSpinBox()
        self.input_ransac_iters.setRange(32, 8000)
        self.input_ransac_iters.setSingleStep(32)
        self.input_ransac_iters.setValue(384)

        self.lbl_min_line_pts = ClickableLabel()
        self.hint_min_line_pts = QLabel()
        bind_lbl(self.lbl_min_line_pts, self.hint_min_line_pts)
        self.input_min_line_points = NoWheelSpinBox()
        self.input_min_line_points.setRange(2, 60)
        self.input_min_line_points.setValue(2)

        for spin in (
            self.input_sample_fps,
            self.input_score_threshold,
            self.input_merge_gap,
            self.input_min_segment,
            self.input_remix_cluster_gap,
            self.input_faiss_top_k,
            self.input_speed_min,
            self.input_speed_max,
            self.input_ransac_iters,
            self.input_min_line_points,
        ):
            spin.setMinimumWidth(spin_w)

        pr = 0
        params.addWidget(self.lbl_sample_fps, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_sample_fps, pr, 1)
        pr += 1
        params.addWidget(self.lbl_score, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_score_threshold, pr, 1)
        pr += 1
        params.addWidget(self.lbl_gap, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_merge_gap, pr, 1)
        pr += 1
        params.addWidget(self.lbl_min_seg, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_min_segment, pr, 1)
        pr += 1
        params.addWidget(self.lbl_remix_cluster, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_remix_cluster_gap, pr, 1)
        pr += 1
        params.addWidget(self.lbl_faiss_top_k, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_faiss_top_k, pr, 1)
        pr += 1
        params.addWidget(self.lbl_speed_min, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_speed_min, pr, 1)
        pr += 1
        params.addWidget(self.lbl_speed_max, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_speed_max, pr, 1)
        pr += 1
        params.addWidget(self.lbl_ransac_iters, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_ransac_iters, pr, 1)
        pr += 1
        params.addWidget(self.lbl_min_line_pts, pr, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        params.addWidget(self.input_min_line_points, pr, 1)

        self.remix_params_short_hint = QLabel()
        self.remix_params_short_hint.setObjectName("CardHint")
        self.remix_params_short_hint.setWordWrap(True)
        self.btn_open_remix_cache = QPushButton()
        self.btn_open_remix_cache.setObjectName("AccentGhostButton")
        self.btn_open_remix_cache.setMinimumWidth(120)
        params_footer = QHBoxLayout()
        params_footer.setSpacing(12)
        params_footer.addWidget(self.remix_params_short_hint, 1)
        params_footer.addWidget(self.btn_open_remix_cache, 0)

        self.lbl_remix_preset = QLabel()
        self.lbl_remix_preset.setObjectName("FormLabel")
        self.combo_remix_preset = QComboBox()
        self.combo_remix_preset.setMinimumWidth(max(160, spin_w + 24))
        for _ in range(4):
            self.combo_remix_preset.addItem("")
        self.remix_preset_guide = QLabel()
        self.remix_preset_guide.setObjectName("CardHint")
        self.remix_preset_guide.setWordWrap(True)
        self._remix_texts_cache: dict = {}
        self._remix_preset_block = False

        preset_top = QHBoxLayout()
        preset_top.setSpacing(12)
        preset_top.addWidget(self.lbl_remix_preset, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        preset_top.addWidget(self.combo_remix_preset, 1)

        self.remix_params_body = QWidget()
        remix_params_body_layout = QVBoxLayout(self.remix_params_body)
        remix_params_body_layout.setContentsMargins(0, 0, 0, 0)
        remix_params_body_layout.setSpacing(12)
        remix_params_body_layout.addLayout(params)
        remix_params_body_layout.addLayout(params_footer)

        self.combo_remix_preset.currentIndexChanged.connect(self._on_remix_preset_index_changed)
        for _spin in (
            self.input_sample_fps,
            self.input_score_threshold,
            self.input_merge_gap,
            self.input_min_segment,
            self.input_remix_cluster_gap,
            self.input_faiss_top_k,
            self.input_speed_min,
            self.input_speed_max,
            self.input_ransac_iters,
            self.input_min_line_points,
        ):
            _spin.valueChanged.connect(self._on_remix_spin_param_changed)

        self.remix_params_card = VSCard(spacing=12)
        params_card_layout = self.remix_params_card.content_layout
        params_card_layout.addWidget(self.params_disclosure)
        params_card_layout.addLayout(preset_top)
        params_card_layout.addWidget(self.remix_preset_guide)
        params_card_layout.addWidget(self.remix_params_body)
        self.remix_params_body.setVisible(False)
        # Default: Standard preset, parameters collapsed; expand when user selects Custom or edits into Custom.
        self._apply_remix_preset("standard")
        self._remix_preset_block = True
        try:
            self.combo_remix_preset.setCurrentIndex(1)
        finally:
            self._remix_preset_block = False
        self._remix_params_expanded = False
        self._sync_remix_disclosure_headers()

        self.scope_card = VSCard(spacing=12)
        scope_layout = self.scope_card.content_layout

        self.scope_section_title = QLabel()
        self.scope_section_title.setObjectName("CardTitle")
        self.scope_card_hint = QLabel()
        self.scope_card_hint.setObjectName("CardHint")
        self.scope_card_hint.setWordWrap(True)
        self.lbl_scope_summary = QLabel()
        self.lbl_scope_summary.setObjectName("CardHint")
        self.lbl_scope_summary.setWordWrap(True)

        self.btn_edit_scope = QPushButton()
        self.btn_edit_scope.setObjectName("AccentGhostButton")
        self.btn_edit_scope.setMinimumWidth(160)

        scope_action = QHBoxLayout()
        scope_action.setSpacing(12)
        scope_action.addWidget(self.btn_edit_scope, 0)
        scope_action.addStretch(1)

        scope_layout.addWidget(self.scope_section_title)
        scope_layout.addWidget(self.scope_card_hint)
        scope_layout.addWidget(self.lbl_scope_summary)
        scope_layout.addLayout(scope_action)

        self.scope_table_hint = QLabel()
        self.scope_table_hint.setObjectName("RemixScopeHint")
        self.scope_table_hint.setWordWrap(True)
        scope_tool_row = QHBoxLayout()
        scope_tool_row.setSpacing(8)
        self.btn_scope_all = QPushButton()
        self.btn_scope_all.setObjectName("GhostButton")
        self.btn_scope_none = QPushButton()
        self.btn_scope_none.setObjectName("GhostButton")
        scope_tool_row.addWidget(self.btn_scope_all)
        scope_tool_row.addWidget(self.btn_scope_none)
        scope_tool_row.addStretch(1)
        self.scope_tree = RemixScopeTreeWidget()
        self.scope_tree.setObjectName("RemixScopeTree")
        _scope_h = int(COMPONENT_SIZES.get("remix_scope_tree_min_height", 200))
        self.scope_tree.setMinimumHeight(_scope_h)
        self.scope_tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.scope_tree_wrap = QFrame()
        self.scope_tree_wrap.setObjectName("SubPanelCard")
        self.scope_tree_wrap.setMinimumHeight(_scope_h + 24)
        self.scope_tree_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        _stw = QVBoxLayout(self.scope_tree_wrap)
        _stw.setContentsMargins(12, 12, 12, 12)
        _stw.setSpacing(0)
        _stw.addWidget(self.scope_tree)

        self.scope_list_body = QWidget()
        scope_list_layout = QVBoxLayout(self.scope_list_body)
        scope_list_layout.setContentsMargins(0, 0, 0, 0)
        scope_list_layout.setSpacing(12)
        scope_list_layout.addWidget(self.scope_table_hint)
        scope_list_layout.addLayout(scope_tool_row)
        scope_list_layout.addWidget(self.scope_tree_wrap, 1)

        self._scope_editor_stash = QWidget()
        self._scope_editor_stash.setVisible(False)
        self._scope_editor_stash.setMaximumHeight(0)
        self._scope_editor_stash.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._scope_stash_layout = QVBoxLayout(self._scope_editor_stash)
        self._scope_stash_layout.setContentsMargins(0, 0, 0, 0)
        self._scope_stash_layout.setSpacing(0)
        self._scope_stash_layout.addWidget(self.scope_list_body)

        page_body.addWidget(self.remix_params_card)
        page_body.addWidget(self.scope_card, 1)
        page_body.addWidget(self._scope_editor_stash)

        self.results_card = VSCard()
        results_layout = self.results_card.content_layout
        results_header = QHBoxLayout()
        results_header.setContentsMargins(0, 0, 0, 0)
        results_header.setSpacing(10)
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.btn_export_tasks = QPushButton()
        self.btn_export_tasks.setObjectName("GhostButton")
        results_header.addWidget(self.results_title, 1)
        results_header.addWidget(self.btn_export_tasks)
        self.result_view = ResultView(
            table=RemixResultTable(),
            min_table_height=min(440, COMPONENT_SIZES["result_table_min_height"]),
        )
        self.result_table = self.result_view.table
        results_layout.addLayout(results_header)
        results_layout.addWidget(self.result_view)
        page_body.addWidget(self.remix_source_card)
        page_body.addWidget(self.results_card, 1)

    def _sync_remix_disclosure_headers(self):
        self.params_disclosure.set_expanded(self._remix_params_expanded)
        self.remix_params_body.setVisible(self._remix_params_expanded)

    def _sync_remix_params_expanded_for_preset_key(self, key: str) -> None:
        """Only auto-expand when entering Custom (combo or spin drift); never auto-collapse on preset changes."""
        if key != "custom":
            return
        if not self._remix_params_expanded:
            self._remix_params_expanded = True
            self.remix_params_body.setVisible(True)
            self._sync_remix_disclosure_headers()

    def configure_remix_scope_section(self, texts: dict) -> None:
        self.scope_section_title.setText(texts.get("remix_scope_title", ""))
        self.scope_card_hint.setText(texts.get("remix_scope_card_hint", ""))
        self.btn_edit_scope.setText(texts.get("remix_scope_edit", "…"))
        self.scope_table_hint.setText(texts.get("remix_scope_table_hint", ""))
        self.btn_scope_all.setText(texts["remix_select_all"])
        self.btn_scope_none.setText(texts["remix_select_none"])
        self.scope_tree.set_header_labels(texts.get("remix_scope_tree_name_col", ""))
        self.refresh_scope_summary(texts)

    def refresh_scope_summary(self, texts: dict) -> None:
        n_vid, n_lib = self.scope_tree.scope_selection_counts()
        total = self.scope_tree.total_video_items()
        if total <= 0:
            self.lbl_scope_summary.setText(texts.get("remix_scope_summary_no_indexed", ""))
        else:
            tpl = texts.get("remix_scope_summary", "{videos} · {libs}")
            self.lbl_scope_summary.setText(tpl.format(videos=n_vid, libs=n_lib))

    def _toggle_remix_params_visible(self):
        self._remix_params_expanded = not self._remix_params_expanded
        self.remix_params_body.setVisible(self._remix_params_expanded)
        self._sync_remix_disclosure_headers()

    def _activate_remix_param_detail(self, label: ClickableLabel, hint: QLabel):
        body = hint.text().strip()
        if not body:
            return
        for lbl, _ in self._remix_param_bindings:
            lbl.setProperty("detailActive", lbl is label)
            repolish_widget(lbl)
        self._remix_param_popup.set_dark_mode(getattr(self.window(), "is_dark_mode", True))
        self._remix_param_popup.show_for_label(label, label.text().strip(), body)

    def _remix_values_match_preset(self, key: str) -> bool:
        spec = REMIX_PRESETS[key]
        return (
            abs(float(self.input_sample_fps.value()) - spec["sample_fps"]) < 0.051
            and abs(float(self.input_score_threshold.value()) - spec["score_threshold"]) < 0.002
            and abs(float(self.input_merge_gap.value()) - spec["merge_gap"]) < 0.051
            and abs(float(self.input_min_segment.value()) - spec["min_segment"]) < 0.051
            and abs(float(self.input_remix_cluster_gap.value()) - spec["remix_cluster_gap"]) < 0.051
            and int(self.input_faiss_top_k.value()) == int(spec["faiss_top_k"])
            and abs(float(self.input_speed_min.value()) - spec["speed_min"]) < 0.021
            and abs(float(self.input_speed_max.value()) - spec["speed_max"]) < 0.051
            and int(self.input_ransac_iters.value()) == int(spec["ransac_iters"])
            and int(self.input_min_line_points.value()) == int(spec["min_line_points"])
        )

    def _remix_detect_preset_key(self) -> str:
        for key in ("strict", "standard", "loose"):
            if self._remix_values_match_preset(key):
                return key
        return "custom"

    def _set_remix_preset_hint(self, key: str) -> None:
        texts = self._remix_texts_cache or {}
        self.remix_preset_guide.setText(texts.get(f"remix_preset_guide_{key}", ""))

    def _sync_remix_preset_combo_from_values(self) -> None:
        if self._remix_preset_block:
            return
        key = self._remix_detect_preset_key()
        idx = {"strict": 0, "standard": 1, "loose": 2, "custom": 3}[key]
        self._remix_preset_block = True
        try:
            if self.combo_remix_preset.currentIndex() != idx:
                self.combo_remix_preset.setCurrentIndex(idx)
        finally:
            self._remix_preset_block = False
        self._set_remix_preset_hint(key)
        self._sync_remix_params_expanded_for_preset_key(key)

    def _apply_remix_preset(self, key: str) -> None:
        spec = REMIX_PRESETS.get(key)
        if spec is None:
            return
        self._remix_preset_block = True
        try:
            self.input_sample_fps.setValue(float(spec["sample_fps"]))
            self.input_score_threshold.setValue(float(spec["score_threshold"]))
            self.input_merge_gap.setValue(float(spec["merge_gap"]))
            self.input_min_segment.setValue(float(spec["min_segment"]))
            self.input_remix_cluster_gap.setValue(float(spec["remix_cluster_gap"]))
            self.input_faiss_top_k.setValue(int(spec["faiss_top_k"]))
            self.input_speed_min.setValue(float(spec["speed_min"]))
            self.input_speed_max.setValue(float(spec["speed_max"]))
            self.input_ransac_iters.setValue(int(spec["ransac_iters"]))
            self.input_min_line_points.setValue(int(spec["min_line_points"]))
        finally:
            self._remix_preset_block = False
        self._set_remix_preset_hint(key)

    def _on_remix_preset_index_changed(self, index: int) -> None:
        if self._remix_preset_block:
            return
        keys = ("strict", "standard", "loose")
        if index < len(keys):
            self._apply_remix_preset(keys[index])
        else:
            self._set_remix_preset_hint("custom")
            self._sync_remix_params_expanded_for_preset_key("custom")

    def _on_remix_spin_param_changed(self, *_args) -> None:
        if self._remix_preset_block:
            return
        self._sync_remix_preset_combo_from_values()

    def configure_remix_params(self, texts: dict):
        self._remix_texts_cache = texts
        for lbl, _ in self._remix_param_bindings:
            lbl.setProperty("detailActive", False)
            repolish_widget(lbl)
            lbl.setToolTip("")
        self.lbl_remix_preset.setText(texts.get("remix_preset_level", "Preset"))
        self.combo_remix_preset.setItemText(0, texts.get("remix_preset_strict", "Strict"))
        self.combo_remix_preset.setItemText(1, texts.get("remix_preset_standard", "Standard"))
        self.combo_remix_preset.setItemText(2, texts.get("remix_preset_loose", "Loose"))
        self.combo_remix_preset.setItemText(3, texts.get("remix_preset_custom", "Custom"))
        self.combo_remix_preset.setToolTip(texts.get("remix_preset_combo_tip", ""))
        self.remix_params_short_hint.setText(texts.get("remix_params_short_hint", ""))
        self.lbl_sample_fps.setText(texts["remix_sample_fps"])
        self.hint_sample_fps.setText(texts.get("remix_sample_fps_tip", ""))
        self.lbl_score.setText(texts["remix_score_threshold"])
        self.hint_score.setText(texts.get("remix_score_threshold_tip", ""))
        self.lbl_gap.setText(texts["remix_merge_gap"])
        self.hint_gap.setText(texts.get("remix_merge_gap_tip", ""))
        self.lbl_min_seg.setText(texts["remix_min_segment"])
        self.hint_min_seg.setText(texts.get("remix_min_segment_tip", ""))
        self.lbl_remix_cluster.setText(texts["remix_cluster_gap"])
        self.hint_remix_cluster.setText(texts.get("remix_cluster_gap_tip", ""))
        self.lbl_faiss_top_k.setText(texts["remix_faiss_top_k"])
        self.hint_faiss_top_k.setText(texts.get("remix_faiss_top_k_tip", ""))
        self.lbl_speed_min.setText(texts["remix_speed_min"])
        self.hint_speed_min.setText(texts.get("remix_speed_min_tip", ""))
        self.lbl_speed_max.setText(texts["remix_speed_max"])
        self.hint_speed_max.setText(texts.get("remix_speed_max_tip", ""))
        self.lbl_ransac_iters.setText(texts["remix_ransac_iters"])
        self.hint_ransac_iters.setText(texts.get("remix_ransac_iters_tip", ""))
        self.lbl_min_line_pts.setText(texts["remix_min_line_points"])
        self.hint_min_line_pts.setText(texts.get("remix_min_line_points_tip", ""))
        self.btn_open_remix_cache.setText(texts.get("remix_open_cache_dir", texts.get("network_open_cache", "")))
        self.btn_open_remix_cache.setToolTip("")
        for spin in (
            self.input_sample_fps,
            self.input_score_threshold,
            self.input_merge_gap,
            self.input_min_segment,
            self.input_remix_cluster_gap,
            self.input_faiss_top_k,
            self.input_speed_min,
            self.input_speed_max,
            self.input_ransac_iters,
            self.input_min_line_points,
        ):
            spin.setToolTip("")
        self._sync_remix_preset_combo_from_values()
        self._sync_remix_disclosure_headers()
