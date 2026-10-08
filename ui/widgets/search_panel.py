"""Local search panel with image/text query tabs and shared scope + mobile upload."""

import os

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
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
    compute_search_panel_width,
)
from ui.widgets.scaffold import VSCard
from ui.widgets.search_compose_form import SearchComposeFormWidget
from ui.widgets.styles import repolish_widget
from ui.widgets.tag_search_form import TagSearchForm, _StripHint


class _ElidedPathLabel(QLabel):
    """Single-line path. The middle is elided; the tooltip keeps the full address."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImageQueryPath")
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(32)
        self.setMinimumWidth(0)
        self._full = ""
        self.hide()

    def set_path(self, path: str) -> None:
        self._full = str(path or "").strip()
        self.setToolTip(self._full)
        self.setVisible(bool(self._full))
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        if not self._full:
            super().setText("")
            return
        width = max(0, self.width() - 4)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, width))


class ImageQueryThumb(QFrame):
    """Compact image query. Click, drop, and paste stay on the existing handlers."""

    image_clear_requested = Signal()
    _HEIGHT = 48
    _PREVIEW_MAX = 280
    _EMPTY_CAPTION = "选择图片 / 拖入图片"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ImageQueryInput")
        self.setProperty("filled", False)
        self.setFixedHeight(self._HEIGHT)
        self.setMinimumWidth(220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._source: QPixmap | None = None
        self._hint = ""
        self._caption = self._EMPTY_CAPTION
        self._file_path = ""
        self._preview: QFrame | None = None
        self._preview_label: QLabel | None = None
        self._path_label: _ElidedPathLabel | None = None

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 4, 6, 4)
        row.setSpacing(8)

        self._thumb = QLabel()
        self._thumb.setObjectName("ImageQueryThumbPic")
        self._thumb.setFixedSize(40, 36)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._thumb.hide()

        self._text = QLabel(self._caption)
        self._text.setObjectName("ImageQueryInputText")
        self._text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self._clear = QPushButton("×")
        self._clear.setObjectName("ImageQueryClear")
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._clear.setFixedSize(22, 22)
        self._clear.setToolTip("移除图片")
        self._clear.hide()
        self._clear.clicked.connect(lambda _checked=False: self.image_clear_requested.emit())

        row.addWidget(self._thumb, 0)
        row.addWidget(self._text, 1)
        row.addWidget(self._clear, 0)
        self._show_caption()

    def set_path(self, path: str) -> None:
        self._file_path = str(path or "").strip()
        if self._path_label is not None:
            self._path_label.set_path("")
        if self._source is not None and not self._source.isNull():
            self._show_filled()

    def set_caption(self, text: str) -> None:
        self._caption = str(text or "").strip() or self._EMPTY_CAPTION
        if self._source is None or self._source.isNull():
            self._show_caption()

    def set_clear_tip(self, text: str) -> None:
        self._clear.setToolTip(str(text or "").strip() or "移除图片")

    def apply_bar_height(self, height: int) -> None:
        """Stay about one and a half times a normal field, not the full query row."""
        del height
        self._HEIGHT = 48
        self.setFixedHeight(self._HEIGHT)
        self._thumb.setFixedSize(40, 36)
        if self._source is not None and not self._source.isNull():
            self._show_filled()
        else:
            self._show_caption()

    def setText(self, text: str) -> None:  # noqa: N802 — kept for the existing drop hint
        self._hint = str(text or "")
        self.setToolTip(self._hint)
        if self._source is None or self._source.isNull():
            self._text.setToolTip(self._hint)

    def clear(self) -> None:  # noqa: N802 — Qt-style API used by the window
        self._source = None
        self._file_path = ""
        self._hide_preview()
        if self._path_label is not None:
            self._path_label.set_path("")
        self._show_caption()

    def setPixmap(self, pixmap: QPixmap) -> None:  # noqa: N802 — Qt-style API used by the window
        self._source = QPixmap(pixmap) if pixmap is not None else QPixmap()
        if self._source.isNull():
            self._show_caption()
            return
        self._show_filled()

    def pixmap(self) -> QPixmap:  # noqa: N802 — Qt-style API used by the window
        if self._source is not None and not self._source.isNull():
            return self._source
        return QPixmap()

    def _show_caption(self) -> None:
        self._thumb.hide()
        self._clear.hide()
        self._text.setToolTip(self._hint)
        self.setProperty("filled", False)
        repolish_widget(self)
        self._elide_text()

    def _show_filled(self) -> None:
        self._text.setToolTip(self._file_path or self._hint)
        thumb = self._source.scaled(
            40,
            36,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._thumb.setPixmap(thumb)
        self._thumb.show()
        self._clear.show()
        self.setProperty("filled", True)
        repolish_widget(self)
        self._elide_text()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._elide_text()

    def _elide_text(self) -> None:
        filled = self._source is not None and not self._source.isNull()
        full = os.path.basename(self._file_path) if filled and self._file_path else self._caption
        width = self._text.width()
        if width < 24:
            width = max(24, self.width() - (70 if filled else 28))
        shown = self._text.fontMetrics().elidedText(
            full,
            Qt.TextElideMode.ElideMiddle if filled else Qt.TextElideMode.ElideRight,
            width,
        )
        self._text.setText(shown)

    def enterEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().enterEvent(event)
        self._show_preview()

    def leaveEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._hide_preview()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 — Qt API
        self._hide_preview()
        super().hideEvent(event)

    def _ensure_preview(self) -> QFrame:
        host = self.window() or self
        preview = self._preview
        if preview is not None and preview.parentWidget() is host:
            return preview
        if preview is not None:
            preview.hide()
            preview.deleteLater()
        preview = QFrame(
            host,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        preview.setObjectName("ImageQueryPreview")
        preview.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        preview.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        layout = QVBoxLayout(preview)
        layout.setContentsMargins(4, 4, 4, 4)
        label = QLabel(preview)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        preview.hide()
        self._preview = preview
        self._preview_label = label
        return preview

    def _show_preview(self) -> None:
        if self._source is None or self._source.isNull() or not self.isVisible():
            return
        preview = self._ensure_preview()
        label = self._preview_label
        if label is None:
            return
        shown = self._source.scaled(
            self._PREVIEW_MAX,
            self._PREVIEW_MAX,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        label.setPixmap(shown)
        preview.adjustSize()
        origin = self.mapToGlobal(QPoint(0, self.height() + 6))
        preview.move(origin)
        preview.show()
        preview.raise_()

    def _hide_preview(self) -> None:
        if self._preview is not None:
            self._preview.hide()


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
        field_label_width = int(COMPONENT_SIZES.get("search_field_label_width", 96))
        field_gap = int(COMPONENT_SIZES.get("search_field_gap", 4))
        group_gap = int(COMPONENT_SIZES.get("search_controls_group_gap", 12))
        group1_width = field_label_width + field_gap + scope_select_width
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

        self.img_label = ImageQueryThumb()
        self.lbl_image_path = _ElidedPathLabel()
        self.img_label._path_label = self.lbl_image_path
        image_slot = QWidget()
        image_slot_row = QHBoxLayout(image_slot)
        image_slot_row.setContentsMargins(0, 0, 0, 0)
        image_slot_row.setSpacing(8)
        image_slot_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        image_slot_row.addWidget(self.img_label, 1)
        image_slot_row.addWidget(self.lbl_image_path, 1)

        self.text_search = QTextEdit()
        self.text_search.setObjectName("SearchInput")
        self.text_search.setFixedHeight(32)
        self.text_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.text_search.setAcceptRichText(False)

        self.lbl_active_model = QLabel()
        self.lbl_active_model.setObjectName("StatusHint")
        # Single-line, reserved height — avoids panel jump when tab text changes.
        self.lbl_active_model.setWordWrap(False)
        self.lbl_active_model.setFixedHeight(20)

        self.lbl_text_model_hint = _StripHint(self, self.text_search)
        self.lbl_text_model_hint.setObjectName("StatusHint")

        self.dialogue_search = QTextEdit()
        self.dialogue_search.setObjectName("SearchInput")
        self.dialogue_search.setFixedHeight(32)
        self.dialogue_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.dialogue_search.setAcceptRichText(False)

        self.lbl_dialogue_hint = _StripHint(self, self.dialogue_search)
        self.lbl_dialogue_hint.setObjectName("StatusHint")

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

        self.compose_form = SearchComposeFormWidget(fill_text=True, inline_bar=True)

        self.query_stack = QStackedWidget()
        self.query_stack.setObjectName("SearchQueryStack")
        self.query_stack.setFixedHeight(34)
        self.query_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for editor in (
            image_slot,
            self.text_search,
            self.compose_form,
            self.dialogue_search,
            self.tags_form,
        ):
            self.query_stack.addWidget(editor)

        self.search_query_tabs = QTabWidget()
        self.search_query_tabs.setObjectName("SearchQueryTabs")
        self.search_query_tabs.setProperty("barOnly", True)
        self.search_query_tabs.setDocumentMode(True)
        self.search_query_tabs.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.search_query_tabs.tabBar().setUsesScrollButtons(False)
        self.search_query_tabs.tabBar().setExpanding(False)
        self.search_query_tabs.tabBar().setFixedHeight(28)
        for _name in ("image", "text", "compose", "dialogue", "tags"):
            placeholder = QWidget()
            placeholder.setMaximumHeight(0)
            self.search_query_tabs.addTab(placeholder, "")
        self.search_query_tabs.setFixedHeight(30)
        self.search_query_tabs.currentChanged.connect(self.query_stack.setCurrentIndex)

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

        self.mobile_row = QWidget()
        self.mobile_row.hide()

        self._filter_row_height = options_row_height
        self.options_row = QWidget()
        self.options_row.setObjectName("SearchOptionsRow")
        options_row_layout = QHBoxLayout(self.options_row)
        options_row_layout.setContentsMargins(0, 0, 0, 0)
        options_row_layout.setSpacing(group_gap)
        options_row_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        options_row_layout.addWidget(self.search_scope_cluster, 0)
        options_row_layout.addWidget(self.skip_edges_cluster, 0)
        options_row_layout.addWidget(self.search_mode_options_stack, 0)
        self.options_row.setFixedHeight(options_row_height)
        self.options_row.setSizePolicy(
            QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        )

        self.btn_search = QPushButton()
        self.btn_search.setObjectName("SearchButton")
        self.btn_search.setFixedHeight(32)
        self.btn_save_preset = QPushButton()
        self.btn_save_preset.setObjectName("GhostButton")
        self.btn_save_preset.setFixedHeight(32)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        self.btn_clear.setFixedHeight(32)
        self.btn_filters = QPushButton("高级参数")
        self.btn_filters.setObjectName("SearchFilterToggle")
        self.btn_filters.setCheckable(True)
        self.btn_filters.setChecked(False)
        self.btn_filters.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_filters.setFixedHeight(32)
        self.btn_filters.setToolTip("搜索范围、跳过时段和搜索模式")
        self.lbl_filter_summary = QLabel()
        self.lbl_filter_summary.setObjectName("SearchFilterSummary")
        self.lbl_filter_summary.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_filter_summary.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.lbl_filter_summary.hide()
        self._filter_summary = ""
        options_row_layout.addWidget(self.btn_save_preset, 0)
        options_row_layout.addStretch(1)
        self.options_row.hide()
        self.btn_filters.toggled.connect(self._on_filters_toggled)

        tab_row = QHBoxLayout()
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(8)
        tab_row.addWidget(self.search_query_tabs, 0)
        tab_row.addStretch(1)
        tab_row.addWidget(self.lbl_active_model, 0)

        query_row = QHBoxLayout()
        query_row.setContentsMargins(0, 0, 0, 0)
        query_row.setSpacing(8)
        query_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._query_row = query_row
        query_row.addWidget(self.query_stack, 1)
        query_row.addWidget(self.btn_search, 0)
        query_row.addWidget(self.btn_clear, 0)
        query_row.addWidget(self.btn_filters, 0)
        query_row.addWidget(self.lbl_filter_summary, 0)
        query_row.addStretch(0)
        self.search_query_tabs.currentChanged.connect(self._sync_query_anchor)

        layout.addLayout(tab_row, 0)
        layout.addLayout(query_row, 0)
        layout.addWidget(self.options_row, 0)

        default_width = compute_search_panel_width()
        self._width_ceiling = default_width
        self._default_width = default_width
        self.setMinimumWidth(0)
        self.setMaximumWidth(16777215)
        # One short bar. The old card height belonged to the side preview, not the query.
        self._default_height = 116
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._sync_card_height()
        self._apply_query_box_height()
        self._field_label_pad = 4
        self._field_gap = field_gap
        self._scope_select_width = scope_select_width
        self._mode_combo_width = mode_combo_width
        self._enhance_combo_width = enhance_combo_width
        self._group_gap = group_gap
        self._viewport_budget_height: int | None = None
        self._sync_query_anchor()

    def apply_viewport_budget(self, viewport_height: int | None) -> None:
        """Keep the query bar at one fixed strip. Results own the leftover height."""
        del viewport_height
        self._sync_card_height()

    def _on_filters_toggled(self, opened: bool) -> None:
        self.options_row.setVisible(bool(opened))
        self._sync_card_height()
        self._apply_filter_summary_visibility()

    def _sync_card_height(self) -> None:
        """Collapsed bar stays 116. The filter row adds one line only while open."""
        extra = 0
        if self.btn_filters.isChecked():
            extra = int(self._filter_row_height) + int(self.content_layout.spacing())
        self.setFixedHeight(int(self._default_height or 116) + extra)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._sync_query_anchor()

    def _query_field_width(self) -> int:
        """Every query field takes about 55% of the bar so the actions sit against it."""
        margins = self.content_layout.contentsMargins()
        inner = max(0, self.width() - margins.left() - margins.right())
        if inner < 480:
            inner = 480
        target = int(inner * 0.55)
        floor = 280
        ceiling = max(floor, inner - 320)
        return max(floor, min(target, ceiling))

    def _sync_query_anchor(self) -> None:
        """Keep every query field the same width, with spare space after the buttons."""
        lay = getattr(self, "_query_row", None)
        if lay is None:
            return
        stack_index = lay.indexOf(self.query_stack)
        tail = lay.count() - 1
        if stack_index < 0 or tail <= stack_index:
            return
        width = self._query_field_width()
        self.query_stack.setMinimumWidth(width)
        self.query_stack.setMaximumWidth(width)
        lay.setStretch(stack_index, 0)
        lay.setStretch(tail, 1)

    def set_filter_summary(self, text: str) -> None:
        """Quiet reminder of filters that are not at their default."""
        full = " ".join(str(text or "").split())
        self._filter_summary = full
        self.lbl_filter_summary.setToolTip(full)
        if full:
            shown = self.lbl_filter_summary.fontMetrics().elidedText(
                full,
                Qt.TextElideMode.ElideRight,
                260,
            )
            self.lbl_filter_summary.setText(shown)
        else:
            self.lbl_filter_summary.clear()
        self.btn_filters.setProperty("active", bool(full))
        repolish_widget(self.btn_filters)
        self._apply_filter_summary_visibility()

    def _apply_filter_summary_visibility(self) -> None:
        self.lbl_filter_summary.setVisible(bool(self._filter_summary) and not self.btn_filters.isChecked())

    def _apply_query_box_height(self) -> None:
        """Give the query field two text lines without growing the card."""
        card = int(self._default_height or 116)
        margin_v = int(COMPONENT_SIZES.get("search_panel_card_margin", 8)) * 2
        spacing = max(6, int(COMPONENT_SIZES.get("search_panel_row_spacing", 4)))
        tabs = self.search_query_tabs.height() or 30
        # Panel border sits outside the layout.
        available = card - margin_v - spacing - int(tabs) - 2
        line = max(16, self.fontMetrics().lineSpacing())
        two_lines = line * 2 + 14
        # Use the card's leftover height so the field is at least two lines tall.
        height = available if available >= two_lines else max(36, available)
        self.query_stack.setFixedHeight(height)
        for editor in (self.text_search, self.dialogue_search):
            editor.setFixedHeight(height)
            editor.document().setDocumentMargin(2)
            editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
            editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tags_form.apply_bar_height(height)
        self.compose_form.apply_inline_height(height)
        self.img_label.apply_bar_height(height)
        self.lbl_image_path.setFixedHeight(min(32, height))

    def relayout_inline_fields(self) -> None:
        """Hug each label to its text and size dropdowns to their copy."""
        labels = [
            getattr(self, name, None)
            for name in (
                "search_scope_label",
                "skip_edges_label",
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

        row1 = _cluster_width(self.search_scope_label, scope_w)
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

        height = int(self.minimumHeight() or self._default_height)
        return QSize(max(int(self._default_width), 1), height)

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
