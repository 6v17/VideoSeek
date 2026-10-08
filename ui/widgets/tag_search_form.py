"""Tags search form: bar + selected chips + always-visible suggestion list."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QSize, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.styles import repolish_widget


class _StripHint(QLabel):
    """Help text that must not become its own window when shown."""

    def __init__(self, parent: QWidget, target: QWidget):
        super().__init__(parent)
        self._target = target
        self._shown = False
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        super().hide()

    def setText(self, text: str) -> None:
        super().setText(text)
        self._sync_tip()

    def setVisible(self, visible: bool) -> None:
        self._shown = bool(visible)
        super().setVisible(False)
        self._sync_tip()

    def show(self) -> None:
        self.setVisible(True)

    def _sync_tip(self) -> None:
        tip = self.text().strip() if self._shown else ""
        self._target.setToolTip(tip)


class _TagFilterEdit(QLineEdit):
    navigate = Signal(int)
    activate = Signal()
    dismiss = Signal()
    focus_changed = Signal(bool)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(0, hint.height())

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        text = self.text()
        if not text:
            return QSize(24, hint.height())
        width = self.fontMetrics().horizontalAdvance(text) + 16
        return QSize(max(24, width), hint.height())

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.focus_changed.emit(False)

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

    # Keep suggest rows compact even when the list stretches to fill the tab.
    _SUGGEST_ROW_PX = 22

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TagSearchForm")
        self._selected: list[str] = []
        self._selected_cf: set[str] = set()
        self._follow_chip_end = False
        self._chip_origin = 0
        self._placeholder = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        self.field = QFrame()
        self.field.setObjectName("TagSearchField")
        self.field.setFixedHeight(32)
        self.field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        field_row = QHBoxLayout(self.field)
        field_row.setContentsMargins(6, 0, 4, 0)
        field_row.setSpacing(4)
        field_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.chips_box = QWidget()
        self.chips_box.setObjectName("TagChipHost")
        self.chips_box.setFixedHeight(26)
        self.chips_box.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.chips_row = QHBoxLayout(self.chips_box)
        self.chips_row.setContentsMargins(0, 0, 0, 0)
        self.chips_row.setSpacing(4)
        self.chips_box.setVisible(False)
        field_row.addWidget(self.chips_box, 0)

        self.filter_edit = _TagFilterEdit()
        self.filter_edit.setObjectName("TagSearchBar")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.filter_edit.setMinimumWidth(0)
        self.filter_edit.setFixedHeight(28)
        field_row.addWidget(self.filter_edit, 0)
        field_row.addStretch(1)

        self.btn_chips_prev = QPushButton("‹")
        self.btn_chips_next = QPushButton("›")
        for button in (self.btn_chips_prev, self.btn_chips_next):
            button.setObjectName("TagChipNavButton")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(22, 32)
            button.hide()
        self.btn_chips_prev.clicked.connect(lambda: self._scroll_chips(-1))
        self.btn_chips_next.clicked.connect(lambda: self._scroll_chips(1))
        root.addWidget(self.btn_chips_prev, 0)
        root.addWidget(self.field, 1)
        root.addWidget(self.btn_chips_next, 0)

        self.field.installEventFilter(self)
        self._suggest_armed = False

        self.suggest_popup = None
        self.suggest_list = QListWidget(self)
        self.suggest_list.setObjectName("TagSuggestList")
        self.suggest_list.hide()
        self.suggest_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.suggest_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.suggest_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.suggest_list.setSpacing(0)
        self.suggest_list.setUniformItemSizes(True)
        self.suggest_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggest_list.setMaximumHeight(self._SUGGEST_ROW_PX * 8)

        self.hint_label = _StripHint(self, self.filter_edit)
        self.hint_label.setObjectName("StatusHint")

        self.setFixedHeight(34)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.filter_edit.focus_changed.connect(self._set_field_focused)
        self.filter_edit.textChanged.connect(self.filter_changed.emit)
        self.filter_edit.textChanged.connect(lambda _text: self._sync_chip_geometry())
        self.filter_edit.navigate.connect(self._move_suggestion)
        self.filter_edit.activate.connect(self._activate_from_filter)
        self.filter_edit.dismiss.connect(self._remove_last_chip)
        self.suggest_list.itemClicked.connect(self._on_item_clicked)
        self.suggest_list.itemActivated.connect(self._on_item_clicked)

        # Keep API compatibility with older panel wiring.
        self.tags_search = self.filter_edit
        self._suppress_selection_signal = False

    def apply_bar_height(self, height: int) -> None:
        """Match the shared query row. The line stays one row; the box is tall enough for two."""
        height = max(32, int(height))
        self.setFixedHeight(height)
        self.field.setFixedHeight(height)
        edit_h = max(24, height - 8)
        self.filter_edit.setFixedHeight(edit_h)
        self.chips_box.setFixedHeight(min(26, edit_h))
        for button in (self.btn_chips_prev, self.btn_chips_next):
            button.setFixedSize(22, height)
        lay = self.layout()
        if lay is not None:
            lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

    def filter_text(self) -> str:
        return self.filter_edit.text().strip()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
            app.installEventFilter(self)

    def hideEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        popup = self.suggest_popup
        if popup is not None:
            popup.hide()
        super().hideEvent(event)

    def _is_field_button(self, widget: QWidget | None) -> bool:
        while widget is not None and widget is not self.field:
            if isinstance(widget, QPushButton):
                return True
            widget = widget.parentWidget()
        return False

    def _ancestor_is(self, widget: QWidget | None, ancestor: QWidget | None) -> bool:
        while widget is not None and ancestor is not None:
            if widget is ancestor:
                return True
            widget = widget.parentWidget()
        return False

    def eventFilter(self, watched, event) -> bool:
        if event.type() != QEvent.Type.MouseButtonPress:
            return super().eventFilter(watched, event)
        target = watched if isinstance(watched, QWidget) else None
        if self._is_field_button(target):
            # Chip × and the scroll arrows must receive the click. Focusing the
            # editor on press cancels the button.
            return super().eventFilter(watched, event)
        if target is self.field or self._ancestor_is(target, self.field):
            self.filter_edit.setFocus()
            # The edit often still has focus after the list closes, so a second
            # click does not emit focus-in. Open from the click itself.
            self._arm_suggestions()
            return super().eventFilter(watched, event)
        popup = self.suggest_popup
        if popup is not None and popup.isVisible() and not self._ancestor_is(target, popup):
            self._suggest_armed = False
            popup.hide()
        return super().eventFilter(watched, event)

    def _arm_suggestions(self) -> None:
        self._suggest_armed = True
        if self.suggest_list.count() > 0:
            QTimer.singleShot(0, self._show_suggestions)
        self.filter_changed.emit(self.filter_edit.text())

    def _set_field_focused(self, focused: bool) -> None:
        self.field.setProperty("focused", bool(focused))
        repolish_widget(self.field)
        if focused:
            self._arm_suggestions()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_chip_geometry()

    def _sync_chip_geometry(self) -> None:
        self._apply_placeholder()
        chips = self._chip_buttons()
        lay = self.field.layout()
        if not chips:
            self._chip_origin = 0
            self.chips_box.setVisible(False)
            self.chips_box.setFixedWidth(0)
            self.btn_chips_prev.hide()
            self.btn_chips_next.hide()
            self.filter_edit.setMinimumWidth(0)
            self.filter_edit.setMaximumWidth(16777215)
            self.filter_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if lay is not None:
                lay.setStretch(1, 1)
                lay.setStretch(2, 0)
                lay.activate()
            return
        spacing = 4
        widths: list[int] = []
        for chip in chips:
            width = max(36, chip.fontMetrics().horizontalAdvance(chip.text()) + 28)
            chip.setFixedWidth(width)
            chip.setFixedHeight(22)
            widths.append(width)
        edit_w = self._edit_pixel_width()
        self.filter_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.filter_edit.setFixedWidth(edit_w)
        if lay is not None:
            lay.setStretch(1, 0)
            lay.setStretch(2, 1)
        inner = max(0, int(self.field.width()) - 10)
        full = sum(widths) + spacing * (len(widths) - 1)
        budget = max(widths[0], inner - edit_w - spacing) if inner >= 48 else full
        if self._follow_chip_end:
            origin = self._origin_showing_end(widths, budget, spacing)
            self._follow_chip_end = False
        else:
            origin = max(0, min(int(self._chip_origin), len(chips) - 1))
        origin, count, used = self._chip_window(widths, origin, budget, spacing)
        self._chip_origin = origin
        end = origin + count
        for index, chip in enumerate(chips):
            chip.setVisible(origin <= index < end)
        self.chips_box.setFixedWidth(max(1, used))
        self.chips_box.setVisible(True)
        paging = origin > 0 or end < len(chips)
        self.btn_chips_prev.setVisible(paging)
        self.btn_chips_next.setVisible(paging)
        self.btn_chips_prev.setEnabled(origin > 0)
        self.btn_chips_next.setEnabled(end < len(chips))
        if lay is not None:
            lay.activate()

    def _chip_window(self, widths: list[int], origin: int, budget: int, spacing: int) -> tuple[int, int, int]:
        origin = max(0, min(origin, len(widths) - 1))
        used = 0
        count = 0
        for index in range(origin, len(widths)):
            need = widths[index] + (spacing if count else 0)
            if count and used + need > budget:
                break
            if count == 0 and widths[index] > budget:
                return origin, 1, budget
            used += need
            count += 1
        return origin, max(1, count), max(1, used)

    def _origin_showing_end(self, widths: list[int], budget: int, spacing: int) -> int:
        origin = len(widths)
        used = 0
        count = 0
        while origin > 0:
            need = widths[origin - 1] + (spacing if count else 0)
            if count and used + need > budget:
                break
            used += need
            count += 1
            origin -= 1
        return origin

    def _scroll_chips(self, step: int) -> None:
        if not self._chip_buttons():
            return
        self._follow_chip_end = False
        if int(step) < 0:
            self._chip_origin = max(0, int(self._chip_origin) - 1)
        else:
            self._chip_origin = int(self._chip_origin) + 1
        self._sync_chip_geometry()

    def _edit_pixel_width(self) -> int:
        typed = self.filter_edit.text()
        if not typed:
            return 28
        return max(28, self.filter_edit.fontMetrics().horizontalAdvance(typed) + 20)

    def _apply_placeholder(self) -> None:
        # The hint is only for an empty field. It must not keep a slot once tags exist.
        show = "" if self._selected else self._placeholder
        if self.filter_edit.placeholderText() != show:
            self.filter_edit.setPlaceholderText(show)

    def _chip_buttons(self) -> list[QPushButton]:
        chips: list[QPushButton] = []
        for index in range(self.chips_row.count()):
            widget = self.chips_row.itemAt(index).widget()
            if isinstance(widget, QPushButton) and widget.objectName() == "TagChipButton":
                chips.append(widget)
        return chips

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
        message = str(text or "")
        self.hint_label.setText(message)
        self.filter_edit.setToolTip(message)

    def set_placeholder(self, text: str) -> None:
        self._placeholder = str(text or "")
        self._apply_placeholder()

    def set_nav_tooltips(self, previous: str, following: str) -> None:
        self.btn_chips_prev.setToolTip(str(previous or ""))
        self.btn_chips_next.setToolTip(str(following or ""))

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
        self._follow_chip_end = True
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
        exclude = set(self._selected_cf)
        incoming: list[str] = []
        for raw in tags or []:
            tag = str(raw or "").strip()
            if not tag or tag.casefold() in exclude:
                continue
            incoming.append(tag)
        existing = [
            str(self.suggest_list.item(index).text() or "")
            for index in range(self.suggest_list.count())
        ]
        if existing == incoming:
            if incoming:
                self._show_suggestions(quiet=True)
            elif self.suggest_popup is not None:
                self.suggest_popup.hide()
            return
        row_h = int(self._SUGGEST_ROW_PX)
        self.suggest_list.setUpdatesEnabled(False)
        self.suggest_list.blockSignals(True)
        self.suggest_list.clear()
        for tag in incoming:
            entry = QListWidgetItem(tag)
            entry.setSizeHint(QSize(0, row_h))
            self.suggest_list.addItem(entry)
        self.suggest_list.blockSignals(False)
        self.suggest_list.setUpdatesEnabled(True)
        if self.suggest_list.count() <= 0:
            if self.suggest_popup is not None:
                self.suggest_popup.hide()
            return
        restore = 0
        if current:
            for index in range(self.suggest_list.count()):
                if str(self.suggest_list.item(index).text() or "").casefold() == current:
                    restore = index
                    break
        self.suggest_list.setCurrentRow(restore)
        self._show_suggestions(quiet=True)

    def _ensure_suggest_popup(self) -> QFrame:
        host = self.window()
        popup = self.suggest_popup
        if popup is not None and popup.parentWidget() is host:
            return popup
        if popup is not None:
            popup.hide()
            popup.deleteLater()
            self.suggest_popup = None
        popup = QFrame(
            host,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        popup.setObjectName("TagSuggestPopup")
        popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        popup.hide()
        layout = QVBoxLayout(popup)
        layout.setContentsMargins(0, 0, 0, 0)
        self.suggest_list.setParent(popup)
        self.suggest_list.show()
        layout.addWidget(self.suggest_list)
        self.suggest_popup = popup
        return popup

    def _show_suggestions(self, *, quiet: bool = False) -> None:
        armed = self._suggest_armed or self.filter_edit.hasFocus()
        if self.suggest_list.count() <= 0 or not armed or not self.isVisible():
            if self.suggest_popup is not None:
                self.suggest_popup.hide()
            return
        popup = self._ensure_suggest_popup()
        rows = min(8, max(1, self.suggest_list.count()))
        list_h = rows * self._SUGGEST_ROW_PX + 4
        width = max(240, int(self.field.width()))
        origin = self.field.mapToGlobal(QPoint(0, self.field.height() + 2))
        size_changed = popup.size() != QSize(width, list_h)
        pos_changed = popup.pos() != origin
        if size_changed:
            self.suggest_list.setFixedHeight(list_h)
            popup.setFixedSize(width, list_h)
        if pos_changed:
            popup.move(origin)
        if popup.isVisible():
            return
        popup.show()
        popup.raise_()
        if quiet:
            return
        handle = popup.windowHandle()
        if handle is not None:
            handle.raise_()

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
            chip.setFixedHeight(22)
            chip.clicked.connect(lambda _checked=False, value=tag: self.remove_tag(value))
            self.chips_row.addWidget(chip, 0)
        self._sync_chip_geometry()
        # Button widths are 0 until the style polishes them. Measure again next tick.
        QTimer.singleShot(0, self._sync_chip_geometry)

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
        # Keep the list up so the next tag can be picked. Selection refresh
        # replaces the rows; closing here made every pick look like a dismiss.
        self._suggest_armed = True
        self.filter_edit.setFocus()
