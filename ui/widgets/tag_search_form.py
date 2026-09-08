"""Tags search form: bar + selected chips + always-visible suggestion list."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class _TagFilterEdit(QLineEdit):
    navigate = Signal(int)
    activate = Signal()
    dismiss = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Down:
            self.navigate.emit(1)
            event.accept()
            return
        if key == Qt.Key.Key_Up:
            self.navigate.emit(-1)
            event.accept()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.activate.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Escape:
            self.dismiss.emit()
            event.accept()
            return
        if key == Qt.Key.Key_Backspace and not self.text():
            self.dismiss.emit()
        super().keyPressEvent(event)


class TagSearchForm(QWidget):
    """Distinct Tags-tab chrome: chips + search bar + scrollable suggestions."""

    filter_changed = Signal(str)
    selection_changed = Signal()
    activate_search = Signal()
    suggestion_activated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TagSearchForm")
        self._selected: list[str] = []
        self._selected_cf: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.chips_scroll = QScrollArea()
        self.chips_scroll.setObjectName("TagChipScroll")
        self.chips_scroll.setWidgetResizable(True)
        self.chips_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.chips_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chips_scroll.setFixedHeight(34)
        self.chips_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chips_host = QWidget()
        self.chips_host.setObjectName("TagChipHost")
        self.chips_row = QHBoxLayout(self.chips_host)
        self.chips_row.setContentsMargins(0, 0, 0, 0)
        self.chips_row.setSpacing(6)
        self.chips_row.addStretch(1)
        self.chips_scroll.setWidget(self.chips_host)
        self.chips_scroll.setVisible(False)
        root.addWidget(self.chips_scroll, 0)

        self.filter_edit = _TagFilterEdit()
        self.filter_edit.setObjectName("TagSearchBar")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_edit.setFixedHeight(32)
        root.addWidget(self.filter_edit, 0)

        self.suggest_list = QListWidget()
        self.suggest_list.setObjectName("TagSuggestList")
        self.suggest_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.suggest_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.suggest_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.suggest_list.setSpacing(0)
        self.suggest_list.setUniformItemSizes(True)
        self.suggest_list.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self.suggest_list, 1)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("StatusHint")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label, 0)

        self.filter_edit.textChanged.connect(self.filter_changed.emit)
        self.filter_edit.navigate.connect(self._move_suggestion)
        self.filter_edit.activate.connect(self._activate_from_filter)
        self.filter_edit.dismiss.connect(self._remove_last_chip)
        self.suggest_list.itemClicked.connect(self._on_item_clicked)
        self.suggest_list.itemActivated.connect(self._on_item_clicked)

        # Keep API compatibility with older panel wiring.
        self.tags_search = self.filter_edit
        self._suppress_selection_signal = False

    def filter_text(self) -> str:
        return self.filter_edit.text().strip()

    def selected_tags(self) -> list[str]:
        return list(self._selected)

    def search_terms(self) -> list[str]:
        """Chips plus free text (if any) for AND search."""
        terms = list(self._selected)
        typed = self.filter_text()
        if typed:
            key = typed.casefold()
            if key not in self._selected_cf:
                terms.append(typed)
        return terms

    def set_filter_text(self, text: str) -> None:
        self.filter_edit.blockSignals(True)
        self.filter_edit.setText(str(text or ""))
        self.filter_edit.blockSignals(False)

    def set_hint(self, text: str) -> None:
        self.hint_label.setText(str(text or ""))

    def set_placeholder(self, text: str) -> None:
        self.filter_edit.setPlaceholderText(str(text or ""))

    def clear(self, *, emit: bool = True) -> None:
        self._selected.clear()
        self._selected_cf.clear()
        self._rebuild_chips()
        self.set_filter_text("")
        self.suggest_list.clear()
        if emit:
            self.selection_changed.emit()

    def add_tag(self, tag: str, *, clear_filter: bool = True, emit: bool = True) -> bool:
        text = str(tag or "").strip()
        if not text:
            return False
        key = text.casefold()
        if key in self._selected_cf:
            if clear_filter:
                self.set_filter_text("")
            return False
        self._selected.append(text)
        self._selected_cf.add(key)
        self._rebuild_chips()
        if clear_filter:
            self.set_filter_text("")
        if emit and not self._suppress_selection_signal:
            self.selection_changed.emit()
        return True

    def remove_tag(self, tag: str) -> None:
        key = str(tag or "").strip().casefold()
        if not key:
            return
        self._selected = [t for t in self._selected if t.casefold() != key]
        self._selected_cf = {t.casefold() for t in self._selected}
        self._rebuild_chips()
        if not self._suppress_selection_signal:
            self.selection_changed.emit()

    def set_suggestions(self, tags: list[str]) -> None:
        current = ""
        item = self.suggest_list.currentItem()
        if item is not None:
            current = str(item.text() or "").strip().casefold()
        self.suggest_list.clear()
        exclude = set(self._selected_cf)
        for raw in tags or []:
            tag = str(raw or "").strip()
            if not tag or tag.casefold() in exclude:
                continue
            self.suggest_list.addItem(QListWidgetItem(tag))
        if self.suggest_list.count() <= 0:
            return
        restore = 0
        if current:
            for index in range(self.suggest_list.count()):
                if str(self.suggest_list.item(index).text() or "").casefold() == current:
                    restore = index
                    break
        self.suggest_list.setCurrentRow(restore)

    def _rebuild_chips(self) -> None:
        while self.chips_row.count():
            item = self.chips_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for tag in self._selected:
            chip = QPushButton(f"{tag} ×")
            chip.setObjectName("TagChipButton")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setToolTip(tag)
            chip.clicked.connect(lambda _checked=False, value=tag: self.remove_tag(value))
            self.chips_row.addWidget(chip, 0)
        self.chips_row.addStretch(1)
        self.chips_scroll.setVisible(bool(self._selected))

    def _move_suggestion(self, delta: int) -> None:
        count = self.suggest_list.count()
        if count <= 0:
            return
        row = self.suggest_list.currentRow()
        if row < 0:
            row = 0
        else:
            row = (row + int(delta)) % count
        self.suggest_list.setCurrentRow(row)

    def _activate_from_filter(self) -> None:
        """Enter: commit typed/highlighted suggestion into a chip, then search."""
        item = self.suggest_list.currentItem()
        if item is not None and self.suggest_list.count() > 0 and self.filter_text():
            # Only auto-pick the highlighted row when the user is filtering.
            self._accept_suggestion(str(item.text() or ""))
        else:
            typed = self.filter_text()
            if typed:
                self.add_tag(typed, clear_filter=True)
        self.activate_search.emit()

    def _remove_last_chip(self) -> None:
        if self.filter_text():
            return
        if not self._selected:
            return
        self.remove_tag(self._selected[-1])

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        self._accept_suggestion(str(item.text() or ""))

    def _accept_suggestion(self, tag: str) -> None:
        text = str(tag or "").strip()
        if not text:
            return
        self.add_tag(text, clear_filter=True)
        self.suggestion_activated.emit(text)
