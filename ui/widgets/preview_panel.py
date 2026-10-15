"""Embedded video preview card for the local search page."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout

from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome
from ui.widgets.layout import (
    compare_row_card_height,
    compare_row_min_height,
    layout_viewport_height,
    preview_host_min_height,
)
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


scroll_ancestor_vertically = _scroll_ancestor_vertically


class PreviewHostFrame(QFrame):
    """Picture well. The VLC host inside is the native window; this frame stays a normal widget.

    A native frame keeps the first paint of the transport when it grows over that row,
    so startup shows a second 暂停 bar inside the picture.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return False

    def wheelEvent(self, event):  # noqa: N802
        if _scroll_ancestor_vertically(self, event):
            event.accept()
            return
        event.ignore()


class _DetailFrame(QFrame):
    """Detail block. Its wrapped text must not change the column's height budget."""

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return False


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
        self.btn_collapse = QToolButton()
        self.btn_collapse.setObjectName("SidebarIconButton")
        self.btn_collapse.setText("»")
        self.btn_collapse.setToolTip("收起预览")
        self.btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse.setFixedSize(28, 28)
        self.btn_collapse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_collapse.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        preview_header.addWidget(self.preview_title, 1)
        preview_header.addWidget(self.btn_collapse, 0, Qt.AlignmentFlag.AlignTop)

        self.preview_host = PreviewHostFrame()
        # Flat well. The video window fills it; a second bordered frame reads as a nested player.
        self.preview_host.setObjectName("PreviewHost")
        self.preview_host.setMinimumHeight(preview_host_min_height(viewport_height=self._layout_viewport()))
        self.preview_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_host_layout.setSpacing(0)
        self.preview_placeholder = QLabel()
        self.preview_placeholder.setObjectName("PreviewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_host_layout.addWidget(self.preview_placeholder)

        self.expanded_chrome = ExpandedPreviewChrome(self)
        self.expanded_chrome.collapse_button.hide()

        self.detail_wrap = _DetailFrame()
        self.detail_wrap.setObjectName("PreviewDetail")
        self.detail_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        detail_layout = QVBoxLayout(self.detail_wrap)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)
        detail_layout.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        self.detail_title = QLabel("当前视频")
        self.detail_title.setObjectName("SectionTitle")
        self.detail_name = QLabel()
        self.detail_name.setObjectName("DialogMetaLabel")
        self.detail_name.setWordWrap(True)
        self.detail_body = QLabel()
        self.detail_body.setObjectName("Hint")
        self.detail_body.setWordWrap(True)
        self.detail_body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.detail_body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # The detail text can be several lines. Its size hint must not be a
        # minimum, or a short column paints this block on top of the transport.
        for widget in (self.detail_wrap, self.detail_title, self.detail_name, self.detail_body):
            widget.setMinimumHeight(0)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.detail_name)
        detail_layout.addWidget(self.detail_body, 1)
        self.detail_wrap.hide()

        layout.addLayout(preview_header)
        layout.addWidget(self.preview_host, 0)
        layout.addWidget(self.expanded_chrome, 0)
        layout.addWidget(self.detail_wrap, 1)
        self.expanded_chrome.show_chrome()
        self._docked = False
        self._host_aspect_height = 0
        self._apply_normal_geometry()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._docked and self.isVisible():
            self._fit_host_aspect()
        self._follow_video_frame()

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self._follow_video_frame()

    def _follow_video_frame(self) -> None:
        """The VLC window is a native child. Move it when this card moves."""
        window = self.window()
        schedule = getattr(window, "_schedule_preview_video_frame", None)
        if callable(schedule):
            schedule()

    def set_docked(self, docked: bool = True) -> None:
        """Sit beside the results. The search bar stays full width above them."""
        self._docked = bool(docked)
        if self._docked:
            self._apply_docked_geometry()
        else:
            self._apply_normal_geometry()

    def _apply_docked_geometry(self, viewport_height: int | None = None) -> None:
        del viewport_height
        self.setMinimumWidth(320)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.detail_wrap.show()
        self.expanded_chrome.show_chrome()
        self.expanded_chrome.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.expanded_chrome.raise_()
        self._host_aspect_height = -1
        self._fit_host_aspect()

    def _fit_host_aspect(self) -> None:
        """Keep the transport under the picture. Never let the detail cover it."""
        control_h = max(88, self.expanded_chrome.sizeHint().height())
        self.expanded_chrome.setMinimumHeight(control_h)
        self.expanded_chrome.setMaximumHeight(control_h)
        width = self.preview_host.width()
        if width < 80:
            width = max(160, self.width() - 28)
        aspect = max(1, int(round(width * 9 / 16)))
        layout = self.content_layout
        margins = layout.contentsMargins()
        gaps = max(0, layout.spacing()) * 3
        title_h = self.preview_title.sizeHint().height()
        fixed = margins.top() + margins.bottom() + gaps + title_h + control_h
        picture_budget = max(1, self.height() - fixed)
        if picture_budget > aspect + 72:
            height = aspect
        elif picture_budget > 136:
            height = picture_budget - 72
        else:
            height = picture_budget
        height = max(1, min(aspect, height, picture_budget))
        if (
            height == self._host_aspect_height
            and self.preview_host.maximumHeight() == height
            and self.preview_host.minimumHeight() == height
        ):
            self.expanded_chrome.raise_()
            return
        self._host_aspect_height = height
        self.preview_host.setMinimumHeight(height)
        self.preview_host.setMaximumHeight(height)
        self.preview_host.update()
        self.expanded_chrome.raise_()
        self.expanded_chrome.update()
        player = getattr(getattr(self.window(), "preview_controller", None), "vlc_player", None)
        rebind = getattr(player, "rebind_output_window", None)
        if callable(rebind):
            rebind()

    def is_maximized(self) -> bool:
        return self._maximized

    def set_maximized(self, maximized: bool):
        """Optionally fill the search page; same video host / player."""
        if self._docked:
            self._maximized = False
            self.expanded_chrome.set_maximized_state(False)
            self._apply_docked_geometry()
            return
        maximized = bool(maximized)
        self._maximized = maximized
        self.expanded_chrome.set_maximized_state(maximized)
        if maximized:
            self._apply_maximized_geometry()
        else:
            self._apply_normal_geometry()

    def _layout_viewport(self) -> int | None:
        return layout_viewport_height(self.window())

    def apply_viewport_budget(self, viewport_height: int | None) -> None:
        """Match search-page mins to the live window, not the screen."""
        try:
            vh = int(viewport_height) if viewport_height is not None else None
        except (TypeError, ValueError):
            vh = None
        if vh is not None and vh < 240:
            vh = None
        if self._docked:
            if not self.isVisible():
                return
            self._apply_docked_geometry(vh)
        elif self._maximized:
            self._apply_maximized_geometry(vh)
        else:
            self._apply_normal_geometry(vh)

    def _apply_normal_geometry(self, viewport_height: int | None = None):
        vh = self._layout_viewport() if viewport_height is None else viewport_height
        self._panel_height = compare_row_card_height()
        self.preview_host.setMinimumHeight(preview_host_min_height(viewport_height=vh))
        self.preview_host.setMaximumHeight(16777215)
        self._host_aspect_height = 0
        self.detail_wrap.hide()
        # Min shrinks on short windows; sizeHint still prefers _panel_height via parent splitter.
        self.setMinimumHeight(compare_row_min_height(viewport_height=vh))
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _apply_maximized_geometry(self, viewport_height: int | None = None):
        vh = self._layout_viewport() if viewport_height is None else viewport_height
        host_min = max(280, preview_host_min_height(viewport_height=vh))
        self.preview_host.setMinimumHeight(host_min)
        self.preview_host.setMaximumHeight(16777215)
        self._host_aspect_height = 0
        self.detail_wrap.hide()
        self.setMinimumHeight(
            min(self.MAXIMIZED_MIN_HEIGHT, max(compare_row_min_height(viewport_height=vh), host_min + 120))
        )
        self.setMaximumHeight(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
