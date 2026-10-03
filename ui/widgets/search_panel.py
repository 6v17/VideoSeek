"""Local search panel with image/text query tabs and shared scope + mobile upload."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.layout import (
    COMPONENT_SIZES,
    compare_row_card_height,
    compare_row_min_height,
    compute_search_panel_width,
    compute_search_query_tabs_height,
    image_drop_min_height,
    search_panel_min_height,
)
from ui.widgets.scaffold import VSCard
from ui.widgets.search_compose_form import SearchComposeFormWidget
from ui.widgets.tag_search_form import TagSearchForm


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
    TAB_DIALOGUE = 3

    def __init__(self, parent=None):
        card_margin = int(COMPONENT_SIZES.get("search_panel_card_margin", 12))
        # Keep ≥6 so scope/mobile/mode rows do not sit on each other's borders.
        row_spacing = max(6, int(COMPONENT_SIZES.get("search_panel_row_spacing", 4)))
        super().__init__(parent, margins=(card_margin,) * 4, spacing=row_spacing)
        layout = self.content_layout
        layout.setSpacing(row_spacing)

        combo_width = int(COMPONENT_SIZES.get("search_option_combo_width", 96))
        scope_select_width = int(COMPONENT_SIZES.get("search_scope_select_width", 120))
        mobile_qr_width = int(COMPONENT_SIZES.get("mobile_bridge_qr_width", 56))
        field_label_width = int(COMPONENT_SIZES.get("search_field_label_width", 96))
        field_gap = int(COMPONENT_SIZES.get("search_field_gap", 4))
        group_gap = int(COMPONENT_SIZES.get("search_controls_group_gap", 12))
        toggle_width = 52
        group1_width = field_label_width + field_gap + scope_select_width
        group2_width = field_label_width + field_gap + toggle_width + field_gap + mobile_qr_width
        combo_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        def _configure_field_label(label: QLabel) -> None:
            # Size to text; do not lock a fixed px width (EN "Search scope" needs ~90px).
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        def _configure_field_group(container: QWidget, *, width: int) -> None:
            container.setMinimumWidth(width)
            container.setSizePolicy(
                QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
            )

        self.img_label = QLabel()
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setWordWrap(True)
        self.img_label.setMinimumHeight(image_drop_min_height())
        self.img_label.setMinimumWidth(0)
        self.img_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.text_search = QTextEdit()
        self.text_search.setObjectName("SearchInput")
        self.text_search.setMinimumHeight(68)
        self.text_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.text_search.setAcceptRichText(False)

        self.lbl_active_model = QLabel()
        self.lbl_active_model.setObjectName("StatusHint")
        # Single-line, reserved height — avoids panel jump when tab text changes.
        self.lbl_active_model.setWordWrap(False)
        self.lbl_active_model.setFixedHeight(20)

        self.lbl_text_model_hint = QLabel()
        self.lbl_text_model_hint.setObjectName("StatusHint")
        self.lbl_text_model_hint.setWordWrap(True)

        self.dialogue_search = QTextEdit()
        self.dialogue_search.setObjectName("SearchInput")
        self.dialogue_search.setMinimumHeight(68)
        self.dialogue_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.dialogue_search.setAcceptRichText(False)

        self.lbl_dialogue_hint = QLabel()
        self.lbl_dialogue_hint.setObjectName("StatusHint")
        self.lbl_dialogue_hint.setWordWrap(True)

        self.tags_form = TagSearchForm()
        self.tags_search = self.tags_form.tags_search
        self.tag_suggest_chosen = self.tags_form.suggestion_activated
        self.tag_search_activate = self.tags_form.activate_search
        self.tag_selection_changed = self.tags_form.selection_changed

        self.lbl_tags_hint = self.tags_form.hint_label


        mode_combo_width = max(combo_width, int(COMPONENT_SIZES.get("search_image_mode_combo_width", 108)))
        mode_cluster_width = field_label_width + field_gap + mode_combo_width
        # Stack/cluster slightly taller than the combo so QStackedWidget does not clip borders.
        options_row_height = int(COMPONENT_SIZES.get("search_image_options_row_height", 36))
        # Leave ~4px vertical slack in the row so the 1px bottom border is not clipped.
        options_combo_height = max(28, options_row_height - 4)

        self.search_mode_label = QLabel()
        self.search_mode_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.search_mode_label)
        self.search_mode = QComboBox()
        self.search_mode.setObjectName("SearchModeSelect")
        self.search_mode.setFixedWidth(mode_combo_width)
        self.search_mode.setFixedHeight(options_combo_height)
        self.search_mode.setSizePolicy(combo_policy)

        self.text_search_enhance_label = QLabel()
        self.text_search_enhance_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.text_search_enhance_label)
        enhance_combo_width = max(64, min(72, mode_combo_width - 28))
        self.text_search_enhance = QComboBox()
        self.text_search_enhance.setObjectName("SearchModeSelect")
        self.text_search_enhance.setFixedWidth(enhance_combo_width)
        self.text_search_enhance.setFixedHeight(options_combo_height)
        self.text_search_enhance.setSizePolicy(combo_policy)

        self.text_granularity_cluster = QWidget()
        text_granularity_row = QHBoxLayout(self.text_granularity_cluster)
        text_granularity_row.setContentsMargins(0, 2, 0, 2)
        text_granularity_row.setSpacing(field_gap)
        text_granularity_row.addWidget(self.search_mode_label, 0)
        text_granularity_row.addWidget(self.search_mode, 0)
        text_granularity_row.addSpacing(group_gap)
        text_granularity_row.addWidget(self.text_search_enhance_label, 0)
        text_granularity_row.addWidget(self.text_search_enhance, 0)
        text_granularity_row.addStretch(1)
        text_options_width = (
            field_label_width
            + field_gap
            + mode_combo_width
            + group_gap
            + field_label_width
            + field_gap
            + enhance_combo_width
        )
        self._text_options_width_with_enhance = text_options_width
        self._text_options_width_mode_only = mode_cluster_width
        _configure_field_group(self.text_granularity_cluster, width=text_options_width)
        self.text_granularity_cluster.setFixedHeight(options_row_height)
        self.search_granularity_cluster = self.text_granularity_cluster

        self.image_search_mode_label = QLabel()
        self.image_search_mode_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.image_search_mode_label)
        self.image_search_mode = QComboBox()
        self.image_search_mode.setObjectName("SearchModeSelect")
        self.image_search_mode.setFixedWidth(mode_combo_width)
        self.image_search_mode.setFixedHeight(options_combo_height)
        self.image_search_mode.setSizePolicy(combo_policy)
        self.image_search_mode_cluster = QWidget()
        image_mode_row = QHBoxLayout(self.image_search_mode_cluster)
        image_mode_row.setContentsMargins(0, 2, 0, 2)
        image_mode_row.setSpacing(field_gap)
        image_mode_row.addWidget(self.image_search_mode_label, 0)
        image_mode_row.addWidget(self.image_search_mode, 0)
        image_mode_row.addStretch(1)
        _configure_field_group(
            self.image_search_mode_cluster,
            width=mode_cluster_width,
        )
        self.image_search_mode_cluster.setFixedHeight(options_row_height)

        self.search_mode_options_stack = QStackedWidget()
        self.search_mode_options_stack.setObjectName("SearchModeOptionsStack")
        self.search_mode_options_stack.setFixedHeight(options_row_height)
        self.search_mode_options_stack.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )
        self.dialogue_search_mode_label = QLabel()
        self.dialogue_search_mode_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.dialogue_search_mode_label)
        self.dialogue_search_mode = QComboBox()
        self.dialogue_search_mode.setObjectName("SearchModeSelect")
        self.dialogue_search_mode.setFixedWidth(mode_combo_width)
        self.dialogue_search_mode.setFixedHeight(options_combo_height)
        self.dialogue_search_mode.setSizePolicy(combo_policy)
        self.dialogue_search_mode_cluster = QWidget()
        dialogue_mode_row = QHBoxLayout(self.dialogue_search_mode_cluster)
        dialogue_mode_row.setContentsMargins(0, 2, 0, 2)
        dialogue_mode_row.setSpacing(field_gap)
        dialogue_mode_row.addWidget(self.dialogue_search_mode_label, 0)
        dialogue_mode_row.addWidget(self.dialogue_search_mode, 0)
        dialogue_mode_row.addStretch(1)
        _configure_field_group(self.dialogue_search_mode_cluster, width=mode_cluster_width)
        self.dialogue_search_mode_cluster.setFixedHeight(options_row_height)

        self.search_mode_options_stack.addWidget(self.text_granularity_cluster)
        self.search_mode_options_stack.addWidget(self.image_search_mode_cluster)
        self.search_mode_options_placeholder = QWidget()
        self.search_mode_options_stack.addWidget(self.search_mode_options_placeholder)
        self.search_mode_options_stack.addWidget(self.dialogue_search_mode_cluster)

        tab_page_height = image_drop_min_height() + int(
            COMPONENT_SIZES.get("search_query_tab_page_margins_v", 12)
        )

        self.image_tab = QWidget()
        self.image_tab.setMinimumHeight(tab_page_height)
        image_tab_layout = QVBoxLayout(self.image_tab)
        image_tab_layout.setContentsMargins(4, 4, 4, 4)
        image_tab_layout.setSpacing(6)
        image_tab_layout.addWidget(self.img_label, 1)

        self.text_tab = QWidget()
        self.text_tab.setMinimumHeight(tab_page_height)
        text_tab_layout = QVBoxLayout(self.text_tab)
        text_tab_layout.setContentsMargins(4, 4, 4, 4)
        text_tab_layout.setSpacing(4)
        text_tab_layout.addWidget(self.text_search, 1)
        text_tab_layout.addWidget(self.lbl_text_model_hint, 0, Qt.AlignmentFlag.AlignTop)

        self.compose_form = SearchComposeFormWidget(fill_text=True)
        self.compose_tab = QWidget()
        self.compose_tab.setMinimumHeight(tab_page_height)
        compose_tab_layout = QVBoxLayout(self.compose_tab)
        compose_tab_layout.setContentsMargins(4, 4, 4, 4)
        compose_tab_layout.setSpacing(0)
        compose_tab_layout.addWidget(self.compose_form, 1)

        self.dialogue_tab = QWidget()
        self.dialogue_tab.setMinimumHeight(tab_page_height)
        dialogue_tab_layout = QVBoxLayout(self.dialogue_tab)
        dialogue_tab_layout.setContentsMargins(4, 4, 4, 4)
        dialogue_tab_layout.setSpacing(4)
        dialogue_tab_layout.addWidget(self.dialogue_search, 1)
        dialogue_tab_layout.addWidget(self.lbl_dialogue_hint, 0, Qt.AlignmentFlag.AlignTop)

        self.tags_tab = QWidget()
        self.tags_tab.setMinimumHeight(tab_page_height)
        tags_tab_layout = QVBoxLayout(self.tags_tab)
        tags_tab_layout.setContentsMargins(4, 4, 4, 4)
        tags_tab_layout.setSpacing(0)
        tags_tab_layout.addWidget(self.tags_form, 1)

        self.search_query_tabs = QTabWidget()
        self.search_query_tabs.setObjectName("SearchQueryTabs")
        tabs_min = compute_search_query_tabs_height()
        self.search_query_tabs.setMinimumHeight(tabs_min)
        # Soft ceiling so the query card can shrink without locking min==max.
        self.search_query_tabs.setMaximumHeight(tabs_min + 96)
        self.search_query_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.search_query_tabs.tabBar().setUsesScrollButtons(False)
        self.search_query_tabs.tabBar().setExpanding(False)
        self.search_query_tabs.addTab(self.image_tab, "")
        self.search_query_tabs.addTab(self.text_tab, "")
        self.search_query_tabs.addTab(self.compose_tab, "")
        self.search_query_tabs.addTab(self.dialogue_tab, "")
        self.search_query_tabs.addTab(self.tags_tab, "")

        self.search_scope_label = QLabel()
        self.search_scope_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.search_scope_label)
        self.search_scope_select = SearchScopeSelect()
        self.search_scope_select.setFixedWidth(scope_select_width)
        self.search_scope_select.setFixedHeight(options_combo_height)
        self.search_scope_select.setSizePolicy(combo_policy)
        self.search_scope_cluster = QWidget()
        scope_row = QHBoxLayout(self.search_scope_cluster)
        scope_row.setContentsMargins(0, 2, 0, 2)
        scope_row.setSpacing(field_gap)
        scope_row.addWidget(self.search_scope_label, 0)
        scope_row.addWidget(self.search_scope_select, 0)
        scope_row.addStretch(1)
        _configure_field_group(self.search_scope_cluster, width=group1_width)
        self.search_scope_cluster.setFixedHeight(options_row_height)

        self.skip_edges_label = QLabel()
        self.skip_edges_label.setObjectName("InlineFieldLabel")
        _configure_field_label(self.skip_edges_label)
        self.btn_skip_edges = SearchScopeSelect()
        self.btn_skip_edges.setFixedWidth(scope_select_width)
        self.btn_skip_edges.setFixedHeight(options_combo_height)
        self.btn_skip_edges.setSizePolicy(combo_policy)
        self.skip_edges_cluster = QWidget()
        skip_edges_row = QHBoxLayout(self.skip_edges_cluster)
        skip_edges_row.setContentsMargins(0, 2, 0, 2)
        skip_edges_row.setSpacing(field_gap)
        skip_edges_row.addWidget(self.skip_edges_label, 0)
        skip_edges_row.addWidget(self.btn_skip_edges, 0)
        skip_edges_row.addStretch(1)
        _configure_field_group(self.skip_edges_cluster, width=group1_width)
        self.skip_edges_cluster.setFixedHeight(options_row_height)

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
        self.btn_mobile_toggle.setFixedHeight(options_combo_height)
        self.btn_mobile_toggle.setSizePolicy(combo_policy)
        self.btn_mobile_qr = QPushButton()
        self.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        self.btn_mobile_qr.setFixedWidth(mobile_qr_width)
        self.btn_mobile_qr.setMinimumWidth(mobile_qr_width)
        self.btn_mobile_qr.setMaximumWidth(mobile_qr_width)
        self.btn_mobile_qr.setFixedHeight(options_combo_height)
        self.btn_mobile_qr.setProperty("qrState", "hidden")
        self.btn_mobile_qr.setEnabled(False)
        self.btn_mobile_qr.setSizePolicy(combo_policy)
        self.mobile_group = QWidget()
        mobile_group_layout = QHBoxLayout(self.mobile_group)
        mobile_group_layout.setContentsMargins(0, 2, 0, 2)
        mobile_group_layout.setSpacing(field_gap)
        mobile_group_layout.addWidget(self.mobile_toggle_label, 0)
        mobile_group_layout.addWidget(self.btn_mobile_toggle, 0)
        mobile_group_layout.addWidget(self.btn_mobile_qr, 0)
        _configure_field_group(self.mobile_group, width=group2_width)
        self.mobile_group.setFixedHeight(options_row_height)

        self.mobile_row = QWidget()
        self.mobile_row.setObjectName("SearchMobileRow")
        mobile_row_layout = QHBoxLayout(self.mobile_row)
        mobile_row_layout.setContentsMargins(0, 0, 0, 0)
        mobile_row_layout.setSpacing(group_gap)
        mobile_row_layout.addWidget(self.search_scope_cluster, 0)
        mobile_row_layout.addWidget(self.mobile_group, 0)
        self.mobile_row.setFixedHeight(options_row_height)
        self.mobile_row.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )

        self.options_row = QWidget()
        self.options_row.setObjectName("SearchOptionsRow")
        options_row_layout = QHBoxLayout(self.options_row)
        options_row_layout.setContentsMargins(0, 0, 0, 0)
        options_row_layout.setSpacing(group_gap)
        options_row_layout.addWidget(self.skip_edges_cluster, 0)
        options_row_layout.addWidget(self.search_mode_options_stack, 0)
        self.options_row.setFixedHeight(options_row_height)
        self.options_row.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        )

        self.btn_search = QPushButton()
        self.btn_search.setObjectName("SearchButton")
        self.btn_save_preset = QPushButton()
        self.btn_save_preset.setObjectName("GhostButton")
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        action_row = QHBoxLayout()
        # Extra top gap so the mode combo bottom border is not covered by 开始搜索.
        action_row.setContentsMargins(0, 8, 0, 0)
        action_row.setSpacing(8)
        action_row.addWidget(self.btn_search, 1)
        action_row.addWidget(self.btn_save_preset, 0)
        action_row.addWidget(self.btn_clear)

        layout.addWidget(self.lbl_active_model, 0)
        layout.addWidget(self.search_query_tabs, 0)
        layout.addWidget(self.mobile_row, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.options_row, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(action_row, 0)

        default_width = compute_search_panel_width()
        self._width_ceiling = default_width
        self._default_width = default_width
        self.setMinimumWidth(default_width)
        # Allow dragging wider for tags suggestions; keep a sane ceiling.
        self.setMaximumWidth(max(default_width + 280, int(default_width * 1.85)))
        # Preferred height for sizeHint; hard min must fit all fixed option rows.
        self._default_height = compare_row_card_height()
        self.setMinimumHeight(search_panel_min_height())
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self._field_label_pad = 4
        self._field_gap = field_gap
        self._scope_select_width = scope_select_width
        self._mode_combo_width = mode_combo_width
        self._enhance_combo_width = enhance_combo_width
        self._toggle_width = toggle_width
        self._mobile_qr_width = mobile_qr_width
        self._group_gap = group_gap
        self._viewport_budget_height: int | None = None

    def apply_viewport_budget(self, viewport_height: int | None) -> None:
        """Shrink tab/drop floors for short logical windows; keep option rows intact."""
        try:
            vh = int(viewport_height) if viewport_height is not None else None
        except (TypeError, ValueError):
            vh = None
        if vh is not None and vh < 240:
            vh = None
        if vh == getattr(self, "_viewport_budget_height", None):
            return
        self._viewport_budget_height = vh

        drop = image_drop_min_height(viewport_height=vh)
        margins = int(COMPONENT_SIZES.get("search_query_tab_page_margins_v", 12))
        tab_page = drop + margins
        self.img_label.setMinimumHeight(drop)
        for tab in (
            self.image_tab,
            self.text_tab,
            self.compose_tab,
            self.dialogue_tab,
            self.tags_tab,
        ):
            tab.setMinimumHeight(tab_page)

        tabs_min = compute_search_query_tabs_height(viewport_height=vh)
        # Shorter windows: less extra stretch above the drop zone.
        slack = 48 if (vh is not None and vh < 720) else 96
        self.search_query_tabs.setMinimumHeight(tabs_min)
        self.search_query_tabs.setMaximumHeight(tabs_min + slack)

        panel_min = search_panel_min_height(viewport_height=vh)
        self.setMinimumHeight(panel_min)
        # Prefer a shorter sizeHint when the viewport is cramped.
        if vh is not None and vh < 780:
            self._default_height = panel_min
        else:
            self._default_height = max(panel_min, compare_row_card_height())

    def relayout_inline_fields(self) -> None:
        """Hug each label to its text and size dropdowns to their copy."""
        labels = [
            getattr(self, name, None)
            for name in (
                "search_scope_label",
                "skip_edges_label",
                "mobile_toggle_label",
                "search_mode_label",
                "text_search_enhance_label",
                "image_search_mode_label",
                "dialogue_search_mode_label",
            )
        ]
        labeled = [label for label in labels if isinstance(label, QLabel)]
        if not labeled:
            return
        pad = int(getattr(self, "_field_label_pad", 4))
        label_widths = {}
        for label in labeled:
            text = str(label.text() or "").strip()
            if not text:
                label.setMinimumWidth(0)
                label.setMaximumWidth(16777215)
                label_widths[label] = 0
                continue
            width = int(label.fontMetrics().horizontalAdvance(text)) + pad + 6
            label.setMinimumWidth(width)
            label.setMaximumWidth(width)
            label_widths[label] = width

        field_gap = int(getattr(self, "_field_gap", 4))
        group_gap = int(getattr(self, "_group_gap", 8))
        scope_w = self._fit_combo_width(self.search_scope_select, floor=56, cap=120)
        skip_w = self._fit_combo_width(getattr(self, "btn_skip_edges", None), floor=56, cap=120)
        mode_w = self._fit_combo_width(self.search_mode, floor=56, cap=120)
        image_mode_w = self._fit_combo_width(self.image_search_mode, floor=56, cap=120)
        dialogue_mode_w = self._fit_combo_width(self.dialogue_search_mode, floor=56, cap=120)
        enhance_w = self._fit_combo_width(self.text_search_enhance, floor=48, cap=84)
        toggle_w = int(getattr(self, "_toggle_width", 52))
        qr_w = int(getattr(self, "_mobile_qr_width", 56))

        def _cluster_width(label, control_width) -> int:
            return int(label_widths.get(label, 0)) + field_gap + int(control_width)

        if hasattr(self, "search_scope_cluster"):
            self.search_scope_cluster.setMinimumWidth(
                _cluster_width(self.search_scope_label, scope_w)
            )
        if hasattr(self, "skip_edges_cluster"):
            self.skip_edges_cluster.setMinimumWidth(
                _cluster_width(self.skip_edges_label, skip_w)
            )
        if hasattr(self, "mobile_group"):
            self.mobile_group.setMinimumWidth(
                _cluster_width(self.mobile_toggle_label, toggle_w + field_gap + qr_w)
            )
        if hasattr(self, "image_search_mode_cluster"):
            self.image_search_mode_cluster.setMinimumWidth(
                _cluster_width(self.image_search_mode_label, image_mode_w)
            )
        if hasattr(self, "dialogue_search_mode_cluster"):
            self.dialogue_search_mode_cluster.setMinimumWidth(
                _cluster_width(self.dialogue_search_mode_label, dialogue_mode_w)
            )
        if hasattr(self, "text_granularity_cluster"):
            mode_only = _cluster_width(self.search_mode_label, mode_w)
            enhance = getattr(self, "text_search_enhance", None)
            enhance_label = getattr(self, "text_search_enhance_label", None)
            show_enhance = (
                enhance is not None
                and enhance.isVisible()
                and enhance_label is not None
                and enhance_label.isVisible()
            )
            with_enhance = mode_only + group_gap + _cluster_width(enhance_label, enhance_w)
            self._text_options_width_with_enhance = with_enhance
            self._text_options_width_mode_only = mode_only
            self.text_granularity_cluster.setMinimumWidth(with_enhance if show_enhance else mode_only)

        row1 = (
            _cluster_width(self.search_scope_label, scope_w)
            + group_gap
            + _cluster_width(self.mobile_toggle_label, toggle_w + field_gap + qr_w)
        )
        skip_label = getattr(self, "skip_edges_label", None)
        row2 = _cluster_width(skip_label, skip_w) + group_gap + int(
            getattr(self, "_text_options_width_with_enhance", 0) or 0
        )
        card_margin = int(COMPONENT_SIZES.get("search_panel_card_margin", 8)) * 2
        fitted = max(row1, row2) + card_margin
        ceiling = int(getattr(self, "_width_ceiling", fitted) or fitted)
        # A little wider than the tight fit, and never narrower than the original panel.
        self._default_width = max(fitted + 36, ceiling)
        self.setMinimumWidth(int(self._default_width))

    def _fit_combo_width(self, combo, *, floor: int, cap: int) -> int:
        if combo is None:
            return int(floor)
        longest = 0
        fm = combo.fontMetrics()
        for index in range(combo.count()):
            longest = max(longest, int(fm.horizontalAdvance(combo.itemText(index))))
        if longest <= 0:
            longest = int(fm.horizontalAdvance(combo.currentText() or ""))
        # Horizontal padding only. These combos have no drop-down arrow.
        width = max(int(floor), min(int(cap), longest + 20))
        combo.setFixedWidth(width)
        return width

    def sizeHint(self):
        from PySide6.QtCore import QSize

        # Initial preferred size; splitter can still shrink to minimumHeight / widen.
        return QSize(int(self._default_width), int(self._default_height))

    def text_query(self) -> str:
        return self.text_search.toPlainText().strip()

    def set_text_query(self, text: str) -> None:
        self.text_search.setPlainText(str(text or ""))

    def clear_text_query(self) -> None:
        self.text_search.clear()

    def dialogue_query(self) -> str:
        return self.dialogue_search.toPlainText().strip()

    def set_dialogue_query(self, text: str) -> None:
        self.dialogue_search.setPlainText(str(text or ""))

    def clear_dialogue_query(self) -> None:
        self.dialogue_search.clear()

    def tags_query(self) -> str:
        form = getattr(self, "tags_form", None)
        if form is not None:
            terms = form.search_terms()
            if terms:
                return " · ".join(terms)
            return form.filter_text()
        return self.tags_search.text().strip() if hasattr(self.tags_search, "text") else ""

    def tag_search_terms(self) -> list[str]:
        form = getattr(self, "tags_form", None)
        if form is not None:
            return form.search_terms()
        query = self.tags_query()
        return [query] if query else []

    def set_tags_query(self, text: str) -> None:
        form = getattr(self, "tags_form", None)
        value = str(text or "").strip()
        if form is None:
            if hasattr(self.tags_search, "setText"):
                self.tags_search.blockSignals(True)
                self.tags_search.setText(value)
                self.tags_search.blockSignals(False)
            return
        form._suppress_selection_signal = True
        try:
            form.clear(emit=False)
            if not value:
                return
            if " · " in value:
                for part in value.split(" · "):
                    form.add_tag(part.strip(), clear_filter=False, emit=False)
                form.set_filter_text("")
            else:
                form.add_tag(value, clear_filter=True, emit=False)
        finally:
            form._suppress_selection_signal = False

    def clear_tags_query(self) -> None:
        form = getattr(self, "tags_form", None)
        if form is not None:
            form.clear()
            return
        if hasattr(self.tags_search, "clear"):
            self.tags_search.blockSignals(True)
            self.tags_search.clear()
            self.tags_search.blockSignals(False)

    def show_tag_suggestions(self, tags: list[str]) -> None:
        form = getattr(self, "tags_form", None)
        if form is not None:
            form.set_suggestions(list(tags or []))

    def hide_tag_suggestions(self) -> None:
        # Inline list stays visible; clear only when idle with no chips/filter.
        form = getattr(self, "tags_form", None)
        if form is not None and not form.filter_text() and not form.selected_tags():
            form.set_suggestions([])
