"""Search preset chips shown above local search results."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QWidget

_TRACK_HEIGHT = 32
_CHIP_HEIGHT = 26


class PresetChip(QFrame):
    clicked = Signal()

    def __init__(self, name: str, *, accent_color: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("PresetChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(_CHIP_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 10, 0)
        layout.setSpacing(6)

        color = str(accent_color or "").strip()
        if color:
            accent = QFrame(self)
            accent.setObjectName("PresetChipAccent")
            accent.setFixedSize(2, 14)
            accent.setStyleSheet(f"background-color: {color}; border-radius: 1px;")
            layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(str(name or ""))
        label.setObjectName("PresetChipLabel")
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        # Forward wheel to the preset track's horizontal scrollbar (chips would otherwise swallow it).
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, SearchPresetsBar):
                delta = event.angleDelta().y() or event.angleDelta().x()
                if delta:
                    bar = parent.scroll.horizontalScrollBar()
                    bar.setValue(bar.value() - delta)
                    event.accept()
                    return
                break
            parent = parent.parentWidget()
        event.ignore()


class SearchPresetsBar(QWidget):
    preset_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchPresetsTrack")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(120)
        self.setFixedHeight(_TRACK_HEIGHT)
        self._has_chips = False
        self._track_hover = False

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 3, 6, 3)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("SearchPresetsScroll")
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.scroll.viewport().setObjectName("SearchPresetsViewport")
        self.scroll.viewport().installEventFilter(self)

        self.chips_host = QWidget()
        self.chips_host.setObjectName("SearchPresetsHost")
        self.chips_layout = QHBoxLayout(self.chips_host)
        self.chips_layout.setContentsMargins(0, 0, 0, 0)
        self.chips_layout.setSpacing(6)
        self.chips_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.scroll.setWidget(self.chips_host)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("PresetTrackEmpty")
        self.empty_label.setWordWrap(False)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self.scroll, 1)
        self._chip_widgets: list[PresetChip] = []
        self._empty_text = ""
        self._sync_track_hover()

    def set_texts(self, texts: dict) -> None:
        self._empty_text = texts.get("search_presets_empty", "")
        self.empty_label.setText(self._empty_text)

    def _clear_chips_layout(self) -> None:
        self.empty_label.hide()
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is self.empty_label:
                continue
            if widget is not None:
                widget.deleteLater()
        self._chip_widgets = []
        self._has_chips = False

    def _sync_track_hover(self) -> None:
        self.setProperty("trackHover", self._track_hover)
        self.scroll.setProperty("trackHover", self._track_hover)
        self.style().unpolish(self)
        self.style().polish(self)
        self.style().unpolish(self.scroll)
        self.style().polish(self.scroll)
        self.update()

    def enterEvent(self, event):  # noqa: N802
        self._track_hover = True
        self._sync_track_hover()
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._track_hover = False
        self._sync_track_hover()
        super().leaveEvent(event)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.scroll.viewport() and event.type() == QEvent.Type.Wheel:
            if isinstance(event, QWheelEvent):
                delta = event.angleDelta().y() or event.angleDelta().x()
                if delta:
                    bar = self.scroll.horizontalScrollBar()
                    bar.setValue(bar.value() - delta)
                    return True
        return super().eventFilter(obj, event)

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y() or event.angleDelta().x()
        if delta:
            bar = self.scroll.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
            event.accept()
            return
        event.ignore()

    def _content_width(self) -> int:
        spacing = self.chips_layout.spacing()
        margins = self.chips_layout.contentsMargins()
        width = margins.left() + margins.right()
        visible = 0
        for index in range(self.chips_layout.count()):
            item = self.chips_layout.itemAt(index)
            if item is None:
                continue
            widget = item.widget()
            if widget is None:
                continue
            width += widget.sizeHint().width()
            visible += 1
            if visible > 1:
                width += spacing
        return max(width, 0)

    def _apply_chip_geometry(self) -> None:
        content_width = max(self._content_width(), 1)
        self.chips_host.setFixedHeight(_CHIP_HEIGHT)
        self.chips_host.setFixedWidth(content_width)

    def set_presets(self, presets) -> None:
        self._clear_chips_layout()

        preset_items = list(presets or [])
        if not preset_items:
            self.scroll.setWidgetResizable(True)
            self.chips_host.setMinimumWidth(0)
            self.chips_host.setMaximumWidth(16777215)
            self.chips_host.setFixedHeight(_CHIP_HEIGHT)
            self.empty_label.setText(self._empty_text)
            self.empty_label.show()
            self.chips_layout.addStretch(1)
            self.chips_layout.addWidget(self.empty_label)
            self.chips_layout.addStretch(1)
            return

        self.empty_label.hide()
        self.scroll.setWidgetResizable(False)
        for preset in preset_items:
            preset_id = str(preset.get("id", "") or "").strip()
            if not preset_id:
                continue
            name = str(preset.get("name", "") or preset_id)
            color = str((preset.get("ui") or {}).get("color", "") or "").strip()
            chip = PresetChip(name, accent_color=color, parent=self.chips_host)
            chip.clicked.connect(lambda pid=preset_id: self.preset_clicked.emit(pid))
            self.chips_layout.addWidget(chip)
            self._chip_widgets.append(chip)

        self._has_chips = bool(self._chip_widgets)
        self._apply_chip_geometry()
        self.scroll.horizontalScrollBar().setValue(0)
