"""Floating tag-name suggestions under the Tags search box (search-engine style)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout, QWidget


class TagSuggestPopup(QFrame):
    """Popup list of complete tags; click or Enter selects one."""

    tag_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        # Popup so outside click dismisses; stays above the search panel.
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("TagSuggestPopup")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setObjectName("TagSuggestList")
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        self._max_visible = 8
        self._row_height = 28

    def set_suggestions(self, tags: list[str], *, anchor: QWidget) -> None:
        tags = [str(t).strip() for t in (tags or []) if str(t or "").strip()]
        self._list.clear()
        if not tags or anchor is None:
            self.hide()
            return
        for tag in tags:
            item = QListWidgetItem(tag)
            item.setToolTip(tag)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

        width = max(160, int(anchor.width()))
        visible = min(self._max_visible, self._list.count())
        height = max(self._row_height, visible * self._row_height + 4)
        self.setFixedWidth(width)
        self.setFixedHeight(height)

        origin = anchor.mapToGlobal(QPoint(0, anchor.height()))
        self.move(origin)
        self.show()
        self.raise_()

    def clear_and_hide(self) -> None:
        self._list.clear()
        self.hide()

    def move_selection(self, delta: int) -> None:
        if not self.isVisible() or self._list.count() <= 0:
            return
        row = self._list.currentRow()
        if row < 0:
            row = 0
        else:
            row = (row + int(delta)) % self._list.count()
        self._list.setCurrentRow(row)

    def choose_current(self) -> bool:
        if not self.isVisible():
            return False
        item = self._list.currentItem()
        if item is None:
            return False
        text = str(item.text() or "").strip()
        if not text:
            return False
        self.tag_chosen.emit(text)
        self.clear_and_hide()
        return True

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        text = str(item.text() or "").strip() if item is not None else ""
        if not text:
            return
        self.tag_chosen.emit(text)
        self.clear_and_hide()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Keys are usually forwarded from the editor; keep a safe fallback.
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.choose_current():
                event.accept()
                return
        if key == Qt.Key.Key_Escape:
            self.clear_and_hide()
            event.accept()
            return
        super().keyPressEvent(event)
