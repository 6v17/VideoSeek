"""Reusable page shell primitives (Phase 0 componentization).

See docs/pyside6_ui_architecture.md §9 for component ↔ objectName mapping and roadmap.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.layout import COMPONENT_SIZES

# QSS objectName variants (see ui/widgets/styles.py STYLE_TEMPLATE).
CARD_VARIANTS = {
    "panel": "PanelCard",
    "sub": "SubPanelCard",
    "notice": "NoticeCard",
    "dialog": "Card",
}


class VSCard(QFrame):
    """Styled content card with a standard inner layout."""

    def __init__(
        self,
        variant: str = "panel",
        margins: tuple[int, int, int, int] = (18, 18, 18, 18),
        spacing: int = 10,
        parent=None,
        *,
        object_name: str | None = None,
    ):
        super().__init__(parent)
        resolved = (object_name or "").strip() or CARD_VARIANTS.get(variant, CARD_VARIANTS["panel"])
        self.setObjectName(resolved)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._layout


class VSProgressStatusRow(QWidget):
    """Horizontal progress bar + status label (library indexing, link build, etc.)."""

    def __init__(self, parent=None, *, progress_text_visible: bool = True):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(progress_text_visible)
        self.progress_bar.setFixedHeight(COMPONENT_SIZES["progress_bar_height"])
        self.progress_bar.setMinimumWidth(COMPONENT_SIZES["progress_bar_min_width"])

        self.status_label = QLabel()
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setWordWrap(True)

        row.addWidget(self.progress_bar, 1)
        row.addWidget(self.status_label, 1)

    @property
    def lbl_status(self) -> QLabel:
        return self.status_label

    def set_progress_visible(self, visible: bool) -> None:
        self.progress_bar.setVisible(visible)

    def set_progress_value(self, value: int) -> None:
        self.progress_bar.setValue(value)

    def set_status_text(self, text: str) -> None:
        self.status_label.setText(text)


def make_runtime_banner(parent=None) -> tuple[QFrame, QLabel]:
    """Runtime / indexing banner frame (#RuntimeBanner) with a text label."""
    frame = QFrame(parent)
    frame.setObjectName("RuntimeBanner")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(8)
    label = QLabel(frame)
    label.setObjectName("RuntimeBannerText")
    label.setWordWrap(True)
    layout.addWidget(label, 1)
    return frame, label


class PageHeader(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.badge = QLabel()
        self.badge.setObjectName("PageTitleBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.hide()
        title_row.addWidget(self.title, 0)
        title_row.addWidget(self.badge, 0)
        title_row.addStretch(1)
        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.runtime_banner = QFrame()
        self.runtime_banner.setObjectName("RuntimeBanner")
        banner_layout = QHBoxLayout(self.runtime_banner)
        banner_layout.setContentsMargins(10, 8, 10, 8)
        banner_layout.setSpacing(8)
        self.runtime_banner_text = QLabel()
        self.runtime_banner_text.setObjectName("RuntimeBannerText")
        self.runtime_banner_text.setWordWrap(True)
        self.runtime_banner_action = QPushButton()
        self.runtime_banner_action.setObjectName("AccentGhostButton")
        self.runtime_banner_action.setMinimumHeight(30)
        banner_layout.addWidget(self.runtime_banner_text, 1)
        banner_layout.addWidget(self.runtime_banner_action, 0)
        self.runtime_banner.hide()
        layout.addLayout(title_row)
        layout.addWidget(self.subtitle)
        layout.addWidget(self.runtime_banner)

    def set_badge(self, text: str = "", *, visible: bool | None = None) -> None:
        label = str(text or "").strip()
        self.badge.setText(label)
        show = bool(label) if visible is None else bool(visible)
        self.badge.setVisible(show and bool(label))


class PageScaffold(QWidget):
    """Page shell: header + vertical content area with consistent spacing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)
        self.header = PageHeader()
        outer.addWidget(self.header)
        self.content_host = QWidget()
        self.content_layout = QVBoxLayout(self.content_host)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        outer.addWidget(self.content_host, 1)
