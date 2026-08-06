"""Embedded video preview card for the local search page."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout

from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome
from ui.widgets.layout import COMPONENT_SIZES, compare_row_card_height
from ui.widgets.scaffold import VSCard


def _scroll_ancestor_vertically(widget, event: QWheelEvent) -> bool:
    """Apply vertical wheel to the nearest page QScrollArea. Returns True if handled."""
    delta = event.angleDelta().y()
    if not delta:
        return False
    parent = widget.parentWidget() if widget is not None else None
    while parent is not None:
        if isinstance(parent, QScrollArea):
            bar = parent.verticalScrollBar()
            if bar is not None and bar.maximum() > 0:
                bar.setValue(bar.value() - delta)
                return True
            return False
        parent = parent.parentWidget()
    return False


class PreviewHostFrame(QFrame):
    """Preview surface that forwards vertical wheel to the page scroll area."""

    def wheelEvent(self, event):  # noqa: N802
        if _scroll_ancestor_vertically(self, event):
            event.accept()
            return
        event.ignore()


class PreviewPanel(VSCard):
    """Main-window preview: always the full transport UI (single shared VLC host)."""

    MAXIMIZED_MIN_HEIGHT = 640

    def __init__(self, parent=None):
        super().__init__(margins=(14, 12, 14, 12), spacing=6, parent=parent)
        layout = self.content_layout
        self._maximized = False
        self._panel_height = compare_row_card_height()

        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_header.setSpacing(8)
        self.preview_title = QLabel()
        self.preview_title.setObjectName("CardTitle")
        preview_header.addWidget(self.preview_title, 1)

        self.preview_host = PreviewHostFrame()
        self.preview_host.setObjectName("VideoContainer")
        self.preview_host.setMinimumHeight(max(320, int(COMPONENT_SIZES["preview_host_min_height"])))
        self.preview_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_placeholder = QLabel()
        self.preview_placeholder.setObjectName("PreviewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_host_layout.addWidget(self.preview_placeholder)

        self.expanded_chrome = ExpandedPreviewChrome()
        self.expanded_chrome.collapse_button.hide()
        self.expanded_chrome.show_chrome()

        layout.addLayout(preview_header)
        layout.addWidget(self.preview_host, 1)
        layout.addWidget(self.expanded_chrome, 0)
        self._apply_normal_geometry()

    def is_maximized(self) -> bool:
        return self._maximized

    def set_maximized(self, maximized: bool):
        """Optionally fill the search page; same video host / player."""
        maximized = bool(maximized)
        self._maximized = maximized
        self.expanded_chrome.set_maximized_state(maximized)
        if maximized:
            self._apply_maximized_geometry()
        else:
            self._apply_normal_geometry()

    def _apply_normal_geometry(self):
        self._panel_height = compare_row_card_height()
        self.preview_host.setMinimumHeight(320)
        self.setMinimumHeight(self._panel_height)
        self.setMaximumHeight(self._panel_height)
        self.setFixedHeight(self._panel_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _apply_maximized_geometry(self):
        self.preview_host.setMinimumHeight(480)
        self.setMinimumHeight(self.MAXIMIZED_MIN_HEIGHT)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
