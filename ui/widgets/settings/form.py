"""Settings form row/section helpers (Phase 3)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.components import ClickableLabel
from ui.widgets.styles import repolish_widget


class SettingsFormMixin:
    """Grid rows, detail popups, and section shells for SettingsPage."""

    def _configure_setting_input(self, widget, width, expanding=False):
        widget.setMinimumWidth(width)
        widget.setMaximumWidth(16777215 if expanding else width + 44)
        widget.setMinimumHeight(34)
        widget.setSizePolicy(QSizePolicy.Expanding if expanding else QSizePolicy.Fixed, QSizePolicy.Fixed)
        widget.setProperty("settingField", True)

    def _configure_setting_label(self, label):
        label.setMinimumWidth(140)
        label.setMaximumWidth(210)
        label.setMinimumHeight(40)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setWordWrap(True)
        label.setProperty("settingLabel", True)

    def _create_settings_section(self, title_label):
        card = QFrame()
        card.setObjectName("SubPanelCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title_label.setObjectName("CardTitle")
        title_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_wrap = QWidget()
        title_wrap.setObjectName("SettingsSectionHeader")
        title_wrap_layout = QHBoxLayout(title_wrap)
        title_wrap_layout.setContentsMargins(16, 14, 16, 14)
        title_wrap_layout.setSpacing(0)
        title_wrap_layout.addWidget(title_label)
        title_wrap_layout.addStretch()
        layout.addWidget(title_wrap)
        form = QGridLayout()
        form.setContentsMargins(16, 4, 16, 8)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(0)
        form.setColumnMinimumWidth(0, 260)
        form.setColumnStretch(0, 0)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        return card, form

    def _add_setting_row(
        self,
        grid,
        row,
        label,
        field,
        hint_label,
        *extra_hint_labels,
        show_help=True,
        label_vcenter=True,
    ):
        row_widget = self._build_setting_row(field)
        label_block = self._build_setting_label_block(label, hint_label, extra_hint_labels)
        row_container = QWidget()
        row_container.setObjectName("SettingRowContainer")
        row_layout = QGridLayout(row_container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setHorizontalSpacing(16)
        row_layout.setVerticalSpacing(0)
        row_layout.setColumnMinimumWidth(0, 260)
        row_layout.setColumnStretch(0, 0)
        row_layout.setColumnStretch(1, 1)
        label_alignment = Qt.AlignLeft | (Qt.AlignVCenter if label_vcenter else Qt.AlignTop)
        row_layout.addWidget(label_block, 0, 0, label_alignment)
        row_layout.addWidget(row_widget, 0, 1)
        grid.addWidget(row_container, row, 0, 1, 2)
        return row_container

    def _add_section_note(self, grid, row, note_label: QLabel):
        note_label.setObjectName("StatusHint")
        note_label.setWordWrap(True)
        wrap = QWidget()
        wrap_layout = QVBoxLayout(wrap)
        wrap_layout.setContentsMargins(0, 0, 0, 8)
        wrap_layout.setSpacing(0)
        wrap_layout.addWidget(note_label)
        grid.addWidget(wrap, row, 0, 1, 2)
        return wrap

    def _build_setting_label_block(self, label, hint_label, extra_hint_labels):
        block = QWidget()
        block.setObjectName("SettingLabelBlock")
        layout = QVBoxLayout(block)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        title_row.addWidget(label, 1)
        layout.addLayout(title_row)
        self._bind_setting_detail(label, hint_label, extra_hint_labels)
        return block

    def _build_setting_detail_text(self, hint_label, extra_hint_labels):
        message_parts = []
        hint_text = hint_label.text().strip() if hint_label is not None else ""
        if hint_text:
            message_parts.append(hint_text)
        for extra_hint in extra_hint_labels:
            if extra_hint is None:
                continue
            extra_text = extra_hint.text().strip()
            if extra_text:
                message_parts.append(extra_text)
        return "\n\n".join(message_parts)

    def _bind_setting_detail(self, label, hint_label, extra_hint_labels):
        self._setting_detail_bindings.append((label, hint_label, extra_hint_labels))
        label.set_click_handler(
            lambda l=label, h=hint_label, e=extra_hint_labels: self._activate_setting_detail(l, h, e)
        )

    def _activate_setting_detail(self, label, hint_label, extra_hint_labels):
        detail_text = self._build_setting_detail_text(hint_label, extra_hint_labels)
        if not detail_text:
            return
        self._active_setting_label = label
        for current_label, _, _ in self._setting_detail_bindings:
            current_label.setProperty("detailActive", current_label is label)
            repolish_widget(current_label)
        self.detail_popup.set_dark_mode(getattr(self.window(), "is_dark_mode", True))
        self.detail_popup.show_for_label(label, label.text().strip(), detail_text)

    def _build_setting_row(self, field):
        row = QWidget()
        row.setObjectName("SettingRow")
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(0)
        field_row = QHBoxLayout()
        field_row.setContentsMargins(0, 0, 0, 0)
        field_row.setSpacing(0)
        stretch = 1 if field.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding else 0
        field_row.addWidget(field, stretch, Qt.AlignLeft)
        if not stretch:
            field_row.addStretch(1)
        layout.addLayout(field_row)
        return row
