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

from ui.widgets.button_roles import set_button_role
from ui.widgets.elevation import apply_elevation
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
        apply_elevation(self, 3 if variant == "dialog" else 1)
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


def make_runtime_inline_tip(parent=None) -> tuple[QFrame, QLabel, QPushButton]:
    """Single content-area tip: one label and one action, shared by every page."""
    frame = QFrame(parent)
    frame.setObjectName("RuntimeInlineTip")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label = QLabel(frame)
    label.setObjectName("RuntimeInlineTipText")
    label.setWordWrap(False)
    label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
    action = QPushButton(frame)
    set_button_role(action, "AccentGhostButton", chrome="textLink")
    action.setCursor(Qt.CursorShape.PointingHandCursor)
    action.setFlat(True)
    action.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    layout.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addWidget(action, 0, Qt.AlignmentFlag.AlignVCenter)
    frame.hide()
    return frame, label, action


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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_block = QWidget()
        title_col = QVBoxLayout(title_block)
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)

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
        title_col.addLayout(title_row)

        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.hide()
        title_col.addWidget(self.subtitle)

        layout.addWidget(title_block, 1)

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
