"""Searchable id picker for large lists (10k+): filter box + virtualized QListView."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_MAX_POPUP_HEIGHT = 360
_POPUP_WIDTH_PAD = 24


class _IdListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, Any]] = []  # (label, data)

    def set_rows(self, rows: list[tuple[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = list(rows or [])
        self.endResetModel()

    def clear(self) -> None:
        self.set_rows([])

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._rows):
            return None
        label, payload = self._rows[row]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.ToolTipRole):
            return label
        if role == Qt.ItemDataRole.UserRole:
            return payload
        return None

    def label_at(self, row: int) -> str:
        if 0 <= row < len(self._rows):
            return self._rows[row][0]
        return ""

    def data_at(self, row: int) -> Any:
        if 0 <= row < len(self._rows):
            return self._rows[row][1]
        return None


class SearchableIdCombo(QWidget):
    """Drop-in-ish replacement for a data-bearing QComboBox on large catalogs.

    Emits ``currentIndexChanged`` when the selected id changes (index is source-model row).
    """

    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchableIdCombo")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._model = _IdListModel(self)
        self._proxy = QSortFilterProxyModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._proxy.setFilterRole(Qt.ItemDataRole.DisplayRole)

        self._current_index = -1
        self._placeholder = ""
        self._filter_placeholder = "Filter…"
        self._popup: QFrame | None = None
        self._filter_edit: QLineEdit | None = None
        self._list_view: QListView | None = None

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._button = QToolButton(self)
        self._button.setObjectName("SearchModeSelect")
        self._button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self._button.setArrowType(Qt.ArrowType.NoArrow)
        self._button.setAutoRaise(False)
        self._button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._button.clicked.connect(self._toggle_popup)
        root.addWidget(self._button, 1)

        self._sync_button_text()

    def setMinimumWidth(self, width: int) -> None:  # noqa: N802 — Qt API
        super().setMinimumWidth(width)
        self._button.setMinimumWidth(width)

    def setMaximumWidth(self, width: int) -> None:  # noqa: N802 — Qt API
        super().setMaximumWidth(width)
        self._button.setMaximumWidth(width)

    def set_placeholders(self, *, empty: str = "", filter_text: str = "") -> None:
        if empty:
            self._placeholder = empty
        if filter_text:
            self._filter_placeholder = filter_text
        if self._filter_edit is not None:
            self._filter_edit.setPlaceholderText(self._filter_placeholder)
        self._sync_button_text()

    def clear(self) -> None:
        self._close_popup()
        self._model.clear()
        self._set_current_index(-1, emit=False)

    def count(self) -> int:
        return self._model.rowCount()

    def set_items(self, items: list[tuple[str, Any]], *, current_data: Any = None) -> None:
        """Replace all rows. ``items`` is ``(label, user_data)``."""
        self._close_popup()
        prev = self.currentData()
        wanted = current_data if current_data is not None else prev
        self._model.set_rows(items)
        restore = -1
        if wanted is not None and wanted != "":
            restore = self.findData(wanted)
        if restore < 0 and self.count() > 0:
            restore = 0
        self._set_current_index(restore, emit=False)
        self._sync_button_text()

    def findData(self, value, role: int = Qt.ItemDataRole.UserRole) -> int:  # noqa: N802
        if role != Qt.ItemDataRole.UserRole:
            return -1
        for i in range(self._model.rowCount()):
            if self._model.data_at(i) == value:
                return i
        return -1

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        self._set_current_index(int(index), emit=True)

    def currentIndex(self) -> int:  # noqa: N802
        return self._current_index

    def currentData(self, role: int = Qt.ItemDataRole.UserRole):  # noqa: N802
        if role != Qt.ItemDataRole.UserRole:
            return None
        return self._model.data_at(self._current_index)

    def currentText(self) -> str:  # noqa: N802
        if self._current_index < 0:
            return self._placeholder
        return self._model.label_at(self._current_index)

    def _set_current_index(self, index: int, *, emit: bool) -> None:
        if index < 0 or index >= self.count():
            index = -1
        changed = index != self._current_index
        self._current_index = index
        self._sync_button_text()
        if emit and changed and not self.signalsBlocked():
            self.currentIndexChanged.emit(self._current_index)

    def _sync_button_text(self) -> None:
        text = self.currentText() if self._current_index >= 0 else (self._placeholder or "—")
        # Keep the face readable; full path stays on tooltip.
        self._button.setText(text)
        self._button.setToolTip(text)
        style = self.style()
        if style is not None:
            icon = style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
            self._button.setIcon(icon)

    def _ensure_popup(self) -> QFrame:
        if self._popup is not None:
            return self._popup

        popup = QFrame(None, Qt.WindowType.Popup)
        popup.setObjectName("SearchableIdComboPopup")
        popup.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        filter_edit = QLineEdit(popup)
        filter_edit.setObjectName("SearchableIdComboFilter")
        filter_edit.setClearButtonEnabled(True)
        filter_edit.setPlaceholderText(self._filter_placeholder)
        filter_edit.textChanged.connect(self._on_filter_text_changed)
        filter_edit.returnPressed.connect(self._select_current_proxy_row)
        layout.addWidget(filter_edit)

        hint = QLabel(popup)
        hint.setObjectName("StatusHint")
        hint.setVisible(False)
        self._count_hint = hint
        layout.addWidget(hint)

        view = QListView(popup)
        view.setObjectName("SearchableIdComboView")
        view.setModel(self._proxy)
        view.setUniformItemSizes(True)
        view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.clicked.connect(self._on_view_clicked)
        view.activated.connect(self._on_view_clicked)
        layout.addWidget(view, 1)

        self._popup = popup
        self._filter_edit = filter_edit
        self._list_view = view
        return popup

    def _on_filter_text_changed(self, text: str) -> None:
        # Wildcard contains match.
        pattern = text.strip()
        if pattern:
            self._proxy.setFilterWildcard(f"*{pattern}*")
        else:
            self._proxy.setFilterWildcard("")
        self._update_count_hint()

    def _update_count_hint(self) -> None:
        hint = getattr(self, "_count_hint", None)
        if hint is None:
            return
        total = self._model.rowCount()
        shown = self._proxy.rowCount()
        if total <= 0:
            hint.setVisible(False)
            return
        if shown < total:
            hint.setText(f"{shown} / {total}")
            hint.setVisible(True)
        else:
            hint.setVisible(False)

    def _toggle_popup(self) -> None:
        if self._popup is not None and self._popup.isVisible():
            self._close_popup()
            return
        self._open_popup()

    def _open_popup(self) -> None:
        if self.count() <= 0:
            return
        popup = self._ensure_popup()
        assert self._filter_edit is not None and self._list_view is not None

        self._proxy.setFilterWildcard("")
        self._filter_edit.blockSignals(True)
        self._filter_edit.clear()
        self._filter_edit.blockSignals(False)
        self._update_count_hint()

        width = max(self.width(), 320) + _POPUP_WIDTH_PAD
        screen = QGuiApplication.screenAt(self.mapToGlobal(self.rect().bottomLeft()))
        avail_h = screen.availableGeometry().height() if screen else _MAX_POPUP_HEIGHT
        height = min(_MAX_POPUP_HEIGHT, max(220, avail_h // 3))
        popup.resize(width, height)

        pos = self.mapToGlobal(self.rect().bottomLeft())
        if screen is not None:
            geo = screen.availableGeometry()
            if pos.y() + height > geo.bottom():
                pos = self.mapToGlobal(self.rect().topLeft())
                pos.setY(pos.y() - height)
            if pos.x() + width > geo.right():
                pos.setX(max(geo.left(), geo.right() - width))
        popup.move(pos)
        popup.show()
        self._filter_edit.setFocus(Qt.FocusReason.PopupFocusReason)

        if self._current_index >= 0:
            proxy_index = self._proxy.mapFromSource(self._model.index(self._current_index, 0))
            if proxy_index.isValid():
                self._list_view.setCurrentIndex(proxy_index)
                self._list_view.scrollTo(proxy_index)

    def _close_popup(self) -> None:
        if self._popup is not None:
            self._popup.hide()

    def _on_view_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        source = self._proxy.mapToSource(index)
        if not source.isValid():
            return
        self._set_current_index(source.row(), emit=True)
        self._close_popup()

    def _select_current_proxy_row(self) -> None:
        if self._list_view is None:
            return
        index = self._list_view.currentIndex()
        if not index.isValid() and self._proxy.rowCount() > 0:
            index = self._proxy.index(0, 0)
        self._on_view_clicked(index)

    def hideEvent(self, event) -> None:
        self._close_popup()
        super().hideEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_popup()
            event.accept()
            return
        super().keyPressEvent(event)
