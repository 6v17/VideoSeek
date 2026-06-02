"""Choose fast (stream copy) or precise (re-encode) clip export."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.utils import EXPORT_ENCODE_MODE_COPY, EXPORT_ENCODE_MODE_ORIGINAL
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width
from ui.widgets.scaffold import VSCard
from ui.widgets.styles import (
    THEME_COLORS_DARK_BASE,
    THEME_COLORS_LIGHT_BASE,
    load_merged_theme_colors,
    repolish_widget,
)


def _theme_colors_for(widget: QWidget) -> dict[str, str]:
    window = widget.window() or widget
    bg = window.palette().color(window.backgroundRole())
    is_dark = bg.lightness() < 128
    base = THEME_COLORS_DARK_BASE if is_dark else THEME_COLORS_LIGHT_BASE
    return load_merged_theme_colors(is_dark, base)


class ExportRadioIndicator(QWidget):
    """Circular radio indicator (hollow ring + center dot when checked)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = False
        self.setFixedSize(20, 20)

    def set_checked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self.update()

    def is_checked(self) -> bool:
        return self._checked

    def paintEvent(self, _event):
        colors = _theme_colors_for(self)
        line = QColor(colors.get("LINE_STRONG", "#40557f"))
        accent = QColor(colors.get("ACCENT", "#4e8cff"))
        field = QColor(colors.get("FIELD", "#0f1a2b"))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        outer = self.rect().adjusted(2, 2, -2, -2)
        if self._checked:
            painter.setPen(QPen(accent, 2))
            painter.setBrush(QBrush(field))
            painter.drawEllipse(outer)
            center = outer.center()
            dot_radius = 4
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(accent))
            painter.drawEllipse(
                center.x() - dot_radius,
                center.y() - dot_radius,
                dot_radius * 2,
                dot_radius * 2,
            )
        else:
            painter.setPen(QPen(line, 2))
            painter.setBrush(QBrush(field))
            painter.drawEllipse(outer)


class ExportModeOption(QFrame):
    """Selectable export mode row with a radio indicator beside the full text block."""

    clicked = Signal()

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        hint: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setObjectName("ExportModeOptionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("selected", "false")

        self._indicator = ExportRadioIndicator(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(0)

        title_label = QLabel(title)
        title_label.setObjectName("ExportModeTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("ExportModeSubtitle")
        subtitle_label.setWordWrap(True)
        hint_label = QLabel(hint)
        hint_label.setObjectName("DialogBodyLabel")
        hint_label.setWordWrap(True)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)
        content_layout.addWidget(title_label)
        content_layout.addWidget(subtitle_label)
        content_layout.addWidget(hint_label)

        row = QHBoxLayout()
        row.setSpacing(10)
        indicator_col = QVBoxLayout()
        indicator_col.setContentsMargins(0, 0, 0, 0)
        indicator_col.setSpacing(0)
        indicator_col.addStretch(1)
        indicator_col.addWidget(self._indicator, 0, Qt.AlignmentFlag.AlignHCenter)
        indicator_col.addStretch(1)
        row.addLayout(indicator_col, 0)
        row.addWidget(content, 1)
        layout.addLayout(row)

    def set_selected(self, selected: bool):
        self._indicator.set_checked(selected)
        self.setProperty("selected", "true" if selected else "false")
        repolish_widget(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ExportClipModeDialog(QDialog):
    def __init__(
        self,
        texts: dict,
        *,
        parent=None,
        segment_duration_sec: float | None = None,
    ):
        super().__init__(parent)
        self._texts = texts
        self._selected_mode = EXPORT_ENCODE_MODE_COPY
        del segment_duration_sec

        self.setWindowTitle(texts.get("export_clip_mode_title", "Export clip"))
        self.setModal(True)
        self.setMinimumWidth(
            message_dialog_min_width(
                WINDOW_SIZES["message_dialog"]["minimum_width"] + 80,
                WINDOW_SIZES["message_dialog"]["screen_margin"],
            )
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        card = VSCard(variant="dialog", margins=(22, 22, 22, 18), spacing=14)
        layout = card.content_layout

        title_label = QLabel(texts.get("export_clip_mode_title", "Export clip"))
        title_label.setObjectName("DialogHeroTitle")
        prompt_label = QLabel(texts.get("export_clip_mode_prompt", "Choose export mode:"))
        prompt_label.setObjectName("DialogBodyLabel")
        prompt_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(prompt_label)

        options = QVBoxLayout()
        options.setSpacing(10)

        self._copy_option = ExportModeOption(
            title=texts.get("export_clip_mode_copy", "Fast export"),
            subtitle=texts.get("export_clip_mode_copy_quality", ""),
            hint=texts.get("export_clip_mode_copy_hint", ""),
        )
        self._original_option = ExportModeOption(
            title=texts.get("export_clip_mode_original", "Precise export"),
            subtitle=texts.get("export_clip_mode_original_quality", ""),
            hint=texts.get("export_clip_mode_original_hint", ""),
        )
        options.addWidget(self._copy_option)
        options.addWidget(self._original_option)
        layout.addLayout(options)

        footer = QHBoxLayout()
        footer.addStretch()
        cancel_btn = QPushButton(texts.get("cancel", "Cancel"))
        cancel_btn.setObjectName("GhostButton")
        cancel_btn.clicked.connect(self.reject)
        export_btn = QPushButton(texts.get("export_clip_mode_confirm", "Export"))
        export_btn.setObjectName("PrimaryButton")
        export_btn.clicked.connect(self.accept)
        footer.addWidget(cancel_btn)
        footer.addWidget(export_btn)
        layout.addLayout(footer)
        outer.addWidget(card)

        self._copy_option.clicked.connect(lambda: self._select_mode(EXPORT_ENCODE_MODE_COPY))
        self._original_option.clicked.connect(lambda: self._select_mode(EXPORT_ENCODE_MODE_ORIGINAL))
        self._select_mode(EXPORT_ENCODE_MODE_COPY)

    def _select_mode(self, mode: str):
        self._selected_mode = mode
        self._copy_option.set_selected(mode == EXPORT_ENCODE_MODE_COPY)
        self._original_option.set_selected(mode == EXPORT_ENCODE_MODE_ORIGINAL)

    def selected_mode(self) -> str:
        return self._selected_mode


def prompt_export_encode_mode(
    texts: dict,
    *,
    parent=None,
    segment_duration_sec: float | None = None,
) -> str | None:
    dialog = ExportClipModeDialog(
        texts,
        parent=parent,
        segment_duration_sec=segment_duration_sec,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.selected_mode()
