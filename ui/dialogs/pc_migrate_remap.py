"""Prompt to remap missing library roots after a PC migrate import."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.shell import VSDialogShell
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width


class PcMigrateRemapDialog(VSDialogShell):
    def __init__(
        self,
        parent,
        *,
        texts: dict,
        missing_paths: list[str],
        is_dark: bool = True,
    ):
        del is_dark  # shell theming comes from parent app QSS
        super().__init__(
            parent,
            title=str(texts.get("pc_migrate_remap_title", "库路径重绑")),
            body=str(
                texts.get(
                    "pc_migrate_remap_body",
                    "导入完成，但下列视频库路径在本机不存在。请为每个旧路径选择新位置（视频文件结构需一致）。",
                )
            ),
            minimum_width=message_dialog_min_width(
                720, WINDOW_SIZES["message_dialog"]["screen_margin"]
            ),
            card_margins=(18, 16, 18, 16),
            card_spacing=12,
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(760, 480)
        self._texts = texts
        self._rows: list[tuple[str, QLineEdit]] = []

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(10)

        for old_path in missing_paths:
            old = str(old_path or "").strip()
            if not old:
                continue
            block = QWidget()
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(4)
            old_label = QLabel(
                str(texts.get("pc_migrate_remap_old", "旧路径：{path}")).format(path=old)
            )
            old_label.setObjectName("DialogMetaLabel")
            old_label.setWordWrap(True)
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            edit = QLineEdit()
            edit.setPlaceholderText(
                str(texts.get("pc_migrate_remap_placeholder", "选择本机对应文件夹…"))
            )
            browse = QPushButton(str(texts.get("browse_folder", "选择目录")))
            browse.setObjectName("AccentGhostButton")
            browse.clicked.connect(lambda _checked=False, field=edit, source=old: self._browse(field, source))
            row_layout.addWidget(edit, 1)
            row_layout.addWidget(browse, 0)
            block_layout.addWidget(old_label)
            block_layout.addWidget(row)
            host_layout.addWidget(block)
            self._rows.append((old, edit))

        host_layout.addStretch(1)
        scroll.setWidget(host)
        self.content_layout.addWidget(scroll, 1)

        self.add_footer_button(
            str(texts.get("pc_migrate_remap_skip", texts.get("cancel", "稍后处理"))),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(texts.get("pc_migrate_remap_apply", texts.get("confirm_action", "应用重绑"))),
            object_name="PrimaryButton",
            on_click=self._accept,
            default=True,
        )

    def _browse(self, field: QLineEdit, old_path: str) -> None:
        start = str(field.text() or "").strip() or os.path.dirname(old_path) or ""
        selected = QFileDialog.getExistingDirectory(
            self,
            str(self._texts.get("pc_migrate_remap_pick", self._texts.get("browse_folder", "选择目录"))),
            start,
        )
        if selected:
            field.setText(os.path.normpath(selected))

    def _accept(self) -> None:
        remaps = self.remaps()
        if not remaps:
            self.reject()
            return
        self.accept()

    def remaps(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for old, edit in self._rows:
            new = str(edit.text() or "").strip()
            if new and os.path.isdir(new):
                out[old] = os.path.normpath(new)
        return out
