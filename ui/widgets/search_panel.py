"""Local search query controls (text, image drop, mode, mobile bridge, actions)."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import VSCard


class SearchScopeSelect(QComboBox):
    """Read-only combobox look; click opens the library scope editor."""

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
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = self.content_layout

        self.controls_title = QLabel()
        self.controls_title.setObjectName("CardTitle")
        self.controls_hint = QLabel()
        self.controls_hint.setObjectName("CardHint")
        self.controls_hint.setWordWrap(True)

        self.img_label = QLabel()
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setWordWrap(True)
        self.img_label.setFixedHeight(COMPONENT_SIZES["image_drop_min_height"])
        self.img_label.setMinimumWidth(0)
        self.img_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        self.text_search = QLineEdit()
        self.text_search.setObjectName("SearchInput")

        combo_width = int(COMPONENT_SIZES.get("search_option_combo_width", 96))
        combo_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.search_mode = QComboBox()
        self.search_mode.setObjectName("SearchModeSelect")
        self.search_mode.setFixedWidth(combo_width)
        self.search_mode.setSizePolicy(combo_policy)
        self.search_mode_label = QLabel()
        self.search_mode_label.setObjectName("CardHint")
        self.search_scope_label = QLabel()
        self.search_scope_label.setObjectName("CardHint")
        self.search_scope_select = SearchScopeSelect()
        self.search_scope_select.setFixedWidth(combo_width)
        self.search_scope_select.setSizePolicy(combo_policy)

        self.search_scope_cluster = QWidget()
        self.search_scope_cluster.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        scope_cluster = QHBoxLayout(self.search_scope_cluster)
        scope_cluster.setContentsMargins(0, 0, 0, 0)
        scope_cluster.setSpacing(8)
        scope_cluster.addWidget(self.search_scope_label)
        scope_cluster.addWidget(self.search_scope_select)

        options_row = QHBoxLayout()
        options_row.setSpacing(8)
        options_row.addWidget(self.search_mode_label)
        options_row.addWidget(self.search_mode)
        options_row.addSpacing(12)
        options_row.addWidget(self.search_scope_cluster)
        options_row.addStretch(1)

        mobile_row = QHBoxLayout()
        mobile_row.setSpacing(8)
        self.mobile_toggle_label = QLabel()
        self.mobile_toggle_label.setObjectName("CardHint")
        self.btn_mobile_toggle = QPushButton()
        self.btn_mobile_toggle.setObjectName("MobileBridgeToggle")
        self.btn_mobile_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_mobile_toggle.setCheckable(True)
        self.btn_mobile_qr = QPushButton()
        self.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        mobile_row.addWidget(self.mobile_toggle_label)
        mobile_row.addWidget(self.btn_mobile_toggle)
        mobile_row.addWidget(self.btn_mobile_qr)
        mobile_row.addStretch()

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_search = QPushButton()
        self.btn_search.setObjectName("SearchButton")
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        action_row.addWidget(self.btn_search, 1)
        action_row.addWidget(self.btn_clear)

        layout.addWidget(self.controls_title)
        layout.addWidget(self.controls_hint)
        layout.addWidget(self.img_label)
        layout.addWidget(self.text_search)
        layout.addLayout(options_row)
        layout.addLayout(mobile_row)
        layout.addLayout(action_row)
