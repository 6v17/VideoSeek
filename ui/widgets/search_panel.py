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

from ui.widgets.layout import COMPONENT_SIZES, compute_search_panel_width, compute_search_query_tabs_height
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

    def set_display_text(self, text: str, *, tooltip: str = "") -> None:
        blocked = self.blockSignals(True)
        self.clear()
        if text:
            self.addItem(text)
            self.setCurrentIndex(0)
        self.setToolTip(tooltip or text)
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
        card_margin = int(COMPONENT_SIZES.get("search_panel_card_margin", 12))
        super().__init__(parent, margins=(card_margin,) * 4, spacing=8)
        layout = self.content_layout
        layout.setSpacing(8)

        combo_width = int(COMPONENT_SIZES.get("search_option_combo_width", 96))
        scope_select_width = int(COMPONENT_SIZES.get("search_scope_select_width", 120))
        mobile_qr_width = int(COMPONENT_SIZES.get("mobile_bridge_qr_width", 56))
        field_label_width = int(COMPONENT_SIZES.get("search_field_label_width", 80))
        field_gap = int(COMPONENT_SIZES.get("search_field_gap", 4))
        group_gap = int(COMPONENT_SIZES.get("search_controls_group_gap", 12))
        toggle_width = 52
        group1_width = field_label_width + field_gap + scope_select_width
        group2_width = field_label_width + field_gap + toggle_width + field_gap + mobile_qr_width
        combo_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        def _configure_field_label(label: QLabel) -> None:
            label.setFixedWidth(field_label_width)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        def _configure_field_group(container: QWidget, *, width: int) -> None:
            container.setFixedWidth(width)
            container.setSizePolicy(
                QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            )

        self.img_label = QLabel()
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setWordWrap(True)
        self.img_label.setFixedHeight(COMPONENT_SIZES["image_drop_min_height"])
        self.img_label.setMinimumWidth(0)
        self.img_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.text_search = QTextEdit()
        self.text_search.setObjectName("SearchInput")
        self.text_search.setMinimumHeight(72)
        self.text_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_search.setAcceptRichText(False)

        self.lbl_active_model = QLabel()
        self.lbl_active_model.setObjectName("StatusHint")
        self.lbl_active_model.setWordWrap(True)

        self.lbl_text_model_hint = QLabel()
        self.lbl_text_model_hint.setObjectName("StatusHint")
        self.lbl_text_model_hint.setWordWrap(True)

        image_mode_combo_width = max(combo_width, int(COMPONENT_SIZES.get("search_image_mode_combo_width", 108)))

        self.search_mode_label = QLabel()
        self.search_mode_label.setObjectName("InlineFieldLabel")
        self.search_mode = QComboBox()
        self.search_mode.setObjectName("SearchModeSelect")
        self.search_mode.setFixedWidth(combo_width)
        self.search_mode.setSizePolicy(combo_policy)
        self.text_granularity_cluster = QWidget()
        text_granularity_row = QHBoxLayout(self.text_granularity_cluster)
        text_granularity_row.setContentsMargins(0, 0, 0, 0)
        text_granularity_row.setSpacing(8)
        text_granularity_row.addWidget(self.search_mode_label, 0)
        text_granularity_row.addWidget(self.search_mode, 0)
        text_granularity_row.addStretch(1)
        self.search_granularity_cluster = self.text_granularity_cluster

        self.image_search_mode_label = QLabel()
        self.image_search_mode_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.image_search_mode_label)
        self.image_search_mode = QComboBox()
        self.image_search_mode.setObjectName("SearchImageModeSelect")
        self.image_search_mode.setFixedWidth(image_mode_combo_width)
        self.image_search_mode.setSizePolicy(combo_policy)
        self.image_search_mode_cluster = QWidget()
        image_mode_row = QHBoxLayout(self.image_search_mode_cluster)
        image_mode_row.setContentsMargins(0, 0, 0, 0)
        image_mode_row.setSpacing(field_gap)
        image_mode_row.addWidget(self.image_search_mode_label, 0)
        image_mode_row.addWidget(self.image_search_mode, 0)
        image_mode_row.addStretch(1)
        _configure_field_group(
            self.image_search_mode_cluster,
            width=field_label_width + field_gap + image_mode_combo_width,
        )
        options_row_height = int(COMPONENT_SIZES.get("search_image_options_row_height", 28))
        self.image_search_mode_cluster.setFixedHeight(options_row_height)
        self.image_search_mode_cluster.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )

        tab_page_height = int(COMPONENT_SIZES["image_drop_min_height"]) + int(
            COMPONENT_SIZES.get("search_query_tab_page_margins_v", 12)
        )

        self.image_tab = QWidget()
        self.image_tab.setFixedHeight(tab_page_height)
        image_tab_layout = QVBoxLayout(self.image_tab)
        image_tab_layout.setContentsMargins(4, 8, 4, 4)
        image_tab_layout.setSpacing(10)
        image_tab_layout.addWidget(self.img_label, 0, Qt.AlignmentFlag.AlignTop)
        image_tab_layout.addStretch(1)

        self.text_tab = QWidget()
        self.text_tab.setFixedHeight(tab_page_height)
        text_tab_layout = QVBoxLayout(self.text_tab)
        text_tab_layout.setContentsMargins(4, 8, 4, 4)
        text_tab_layout.setSpacing(8)
        text_tab_layout.addWidget(self.text_search, 1)
        text_tab_layout.addWidget(self.lbl_text_model_hint, 0, Qt.AlignmentFlag.AlignTop)
        text_tab_layout.addWidget(self.text_granularity_cluster, 0, Qt.AlignmentFlag.AlignTop)

        self.compose_form = SearchComposeFormWidget(fill_text=True)
        self.compose_tab = QWidget()
        self.compose_tab.setFixedHeight(tab_page_height)
        compose_tab_layout = QVBoxLayout(self.compose_tab)
        compose_tab_layout.setContentsMargins(4, 8, 4, 4)
        compose_tab_layout.setSpacing(0)
        compose_tab_layout.addWidget(self.compose_form, 1)

        self.search_query_tabs = QTabWidget()
        self.search_query_tabs.setObjectName("SearchQueryTabs")
        self.search_query_tabs.setFixedHeight(compute_search_query_tabs_height())
        self.search_query_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.search_query_tabs.addTab(self.image_tab, "")
        self.search_query_tabs.addTab(self.text_tab, "")
        self.search_query_tabs.addTab(self.compose_tab, "")

        self.search_scope_label = QLabel()
        self.search_scope_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.search_scope_label)
        self.search_scope_select = SearchScopeSelect()
        self.search_scope_select.setFixedWidth(scope_select_width)
        self.search_scope_select.setSizePolicy(combo_policy)
        self.search_scope_cluster = QWidget()
        scope_row = QHBoxLayout(self.search_scope_cluster)
        scope_row.setContentsMargins(0, 0, 0, 0)
        scope_row.setSpacing(field_gap)
        scope_row.addWidget(self.search_scope_label, 0)
        scope_row.addWidget(self.search_scope_select, 0)
        scope_row.addStretch(1)
        _configure_field_group(self.search_scope_cluster, width=group1_width)

        self.options_block = self.search_scope_cluster
        self.options_title = self.search_scope_label

        self.mobile_toggle_label = QLabel()
        self.mobile_toggle_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.mobile_toggle_label)
        self.btn_mobile_toggle = QPushButton()
        self.btn_mobile_toggle.setObjectName("MobileBridgeToggle")
        self.btn_mobile_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_mobile_toggle.setCheckable(True)
        self.btn_mobile_toggle.setFixedWidth(toggle_width)
        self.btn_mobile_toggle.setSizePolicy(combo_policy)
        self.btn_mobile_qr = QPushButton()
        self.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        self.btn_mobile_qr.setFixedWidth(mobile_qr_width)
        self.btn_mobile_qr.setMinimumWidth(mobile_qr_width)
        self.btn_mobile_qr.setMaximumWidth(mobile_qr_width)
        self.btn_mobile_qr.setProperty("qrState", "hidden")
        self.btn_mobile_qr.setEnabled(False)
        self.btn_mobile_qr.setSizePolicy(combo_policy)
        self.mobile_group = QWidget()
        mobile_group_layout = QHBoxLayout(self.mobile_group)
        mobile_group_layout.setContentsMargins(0, 0, 0, 0)
        mobile_group_layout.setSpacing(field_gap)
        mobile_group_layout.addWidget(self.mobile_toggle_label, 0)
        mobile_group_layout.addWidget(self.btn_mobile_toggle, 0)
        mobile_group_layout.addWidget(self.btn_mobile_qr, 0)
        _configure_field_group(self.mobile_group, width=group2_width)

        self.mobile_row = QWidget()
        self.mobile_row.setObjectName("SearchMobileRow")
        mobile_row_layout = QHBoxLayout(self.mobile_row)
        mobile_row_layout.setContentsMargins(0, 0, 0, 0)
        mobile_row_layout.setSpacing(group_gap)
        mobile_row_layout.addWidget(self.search_scope_cluster, 0)
        mobile_row_layout.addWidget(self.mobile_group, 0)
        self.mobile_row.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )

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

        layout.addWidget(self.lbl_active_model)
        layout.addWidget(self.search_query_tabs)
        layout.addWidget(self.mobile_row, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.image_search_mode_cluster, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(action_row)

        self.setFixedHeight(int(COMPONENT_SIZES["search_compare_baseline_height"]) + 24)
        self.setFixedWidth(compute_search_panel_width())
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def text_query(self) -> str:
        return self.text_search.toPlainText().strip()

    def set_text_query(self, text: str) -> None:
        self.text_search.setPlainText(str(text or ""))

    def clear_text_query(self) -> None:
        self.text_search.clear()
