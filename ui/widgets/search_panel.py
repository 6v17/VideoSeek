"""Local search panel with image/text query tabs and shared scope + mobile upload."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import VSCard
from ui.widgets.search_compose_form import SearchComposeFormWidget


class SearchScopeSelect(QComboBox):
    """Read-only combobox look; click opens the video scope editor."""

    editor_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchModeSelect")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_display_text(self, text: str) -> None:
        blocked = self.blockSignals(True)
        self.clear()
        if text:
            self.addItem(text)
            self.setCurrentIndex(0)
        self.blockSignals(blocked)

    def showPopup(self) -> None:
        self.editor_requested.emit()

    def wheelEvent(self, event) -> None:
        event.ignore()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (
            Qt.Key.Key_Up,
            Qt.Key.Key_Down,
            Qt.Key.Key_PageUp,
            Qt.Key.Key_PageDown,
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.editor_requested.emit()
            return
        super().keyPressEvent(event)


class SearchPanel(VSCard):
    TAB_IMAGE = 0
    TAB_TEXT = 1
    TAB_COMPOSE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = self.content_layout
        layout.setSpacing(12)

        combo_width = int(COMPONENT_SIZES.get("search_option_combo_width", 96))
        combo_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        compare_baseline = int(COMPONENT_SIZES["search_compare_baseline_height"])

        self.img_label = QLabel()
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setWordWrap(True)
        self.img_label.setFixedHeight(COMPONENT_SIZES["image_drop_min_height"])
        self.img_label.setMinimumWidth(0)
        self.img_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.text_search = QTextEdit()
        self.text_search.setObjectName("SearchInput")
        self.text_search.setMinimumHeight(140)
        self.text_search.setAcceptRichText(False)

        self.search_precision_label = QLabel()
        self.search_precision_label.setObjectName("InlineFieldLabel")
        self.search_precision_toggle = QPushButton()
        self.search_precision_toggle.setObjectName("SearchPrecisionToggle")
        self.search_precision_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_precision_toggle.setCheckable(True)
        self.search_precision_toggle.setFixedWidth(52)
        self.search_precision_toggle.setSizePolicy(combo_policy)
        self.search_precision_cluster = QWidget()
        precision_row = QHBoxLayout(self.search_precision_cluster)
        precision_row.setContentsMargins(0, 0, 0, 0)
        precision_row.setSpacing(8)
        precision_row.addWidget(self.search_precision_label, 0)
        precision_row.addWidget(self.search_precision_toggle, 0)

        self.search_mode_label = QLabel()
        self.search_mode_label.setObjectName("InlineFieldLabel")
        self.search_mode = QComboBox()
        self.search_mode.setObjectName("SearchModeSelect")
        self.search_mode.setFixedWidth(combo_width)
        self.search_mode.setSizePolicy(combo_policy)
        self.text_granularity_cluster = QWidget()
        granularity_row = QHBoxLayout(self.text_granularity_cluster)
        granularity_row.setContentsMargins(0, 0, 0, 0)
        granularity_row.setSpacing(8)
        granularity_row.addWidget(self.search_mode_label, 0)
        granularity_row.addWidget(self.search_mode, 0)
        granularity_row.addStretch(1)

        self.image_tab = QWidget()
        image_tab_layout = QVBoxLayout(self.image_tab)
        image_tab_layout.setContentsMargins(4, 8, 4, 4)
        image_tab_layout.setSpacing(10)
        image_tab_layout.addWidget(self.img_label)

        self.text_tab = QWidget()
        text_tab_layout = QVBoxLayout(self.text_tab)
        text_tab_layout.setContentsMargins(4, 8, 4, 4)
        text_tab_layout.setSpacing(10)
        text_tab_layout.addWidget(self.text_search)
        text_tab_layout.addWidget(self.text_granularity_cluster)

        self.compose_form = SearchComposeFormWidget(fill_text=True)
        self.compose_tab = QWidget()
        compose_tab_layout = QVBoxLayout(self.compose_tab)
        compose_tab_layout.setContentsMargins(4, 8, 4, 4)
        compose_tab_layout.setSpacing(0)
        compose_tab_layout.addWidget(self.compose_form, 1)

        self.search_query_tabs = QTabWidget()
        self.search_query_tabs.setObjectName("SearchQueryTabs")
        self.search_query_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_query_tabs.addTab(self.image_tab, "")
        self.search_query_tabs.addTab(self.text_tab, "")
        self.search_query_tabs.addTab(self.compose_tab, "")

        self.search_scope_label = QLabel()
        self.search_scope_label.setObjectName("InlineFieldLabel")
        self.search_scope_select = SearchScopeSelect()
        self.search_scope_select.setMinimumWidth(combo_width + 40)
        self.search_scope_select.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_scope_cluster = QWidget()
        scope_row = QHBoxLayout(self.search_scope_cluster)
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_row.setSpacing(8)
        scope_row.addWidget(self.search_scope_label, 0)
        scope_row.addWidget(self.search_scope_select, 1)

        self.options_block = self.search_scope_cluster
        self.options_title = self.search_scope_label

        self.mobile_row = QWidget()
        self.mobile_row.setObjectName("SearchMobileRow")
        mobile_row_layout = QHBoxLayout(self.mobile_row)
        mobile_row_layout.setContentsMargins(0, 0, 0, 0)
        mobile_row_layout.setSpacing(8)
        self.mobile_toggle_label = QLabel()
        self.mobile_toggle_label.setObjectName("InlineFieldLabel")
        self.btn_mobile_toggle = QPushButton()
        self.btn_mobile_toggle.setObjectName("MobileBridgeToggle")
        self.btn_mobile_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_mobile_toggle.setCheckable(True)
        self.btn_mobile_qr = QPushButton()
        self.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        mobile_row_layout.addWidget(self.mobile_toggle_label, 0)
        mobile_row_layout.addWidget(self.btn_mobile_toggle, 0)
        mobile_row_layout.addWidget(self.btn_mobile_qr, 0)
        mobile_row_layout.addStretch(1)
        mobile_row_layout.addWidget(self.search_precision_cluster, 0)

        self.btn_search = QPushButton()
        self.btn_search.setObjectName("SearchButton")
        self.btn_save_preset = QPushButton()
        self.btn_save_preset.setObjectName("GhostButton")
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self.btn_search, 1)
        action_row.addWidget(self.btn_save_preset, 0)
        action_row.addWidget(self.btn_clear)

        layout.addWidget(self.search_query_tabs)
        layout.addWidget(self.search_scope_cluster)
        layout.addWidget(self.mobile_row)
        layout.addLayout(action_row)

        self.setFixedHeight(compare_baseline)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def text_query(self) -> str:
        return self.text_search.toPlainText().strip()

    def set_text_query(self, text: str) -> None:
        self.text_search.setPlainText(str(text or ""))

    def clear_text_query(self) -> None:
        self.text_search.clear()
