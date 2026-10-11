"""Shared in-page preview: player host, back row, and a strip of clips.

Search results and the understanding page each own one of these. The single
preview dialog is reparented into whichever layer is showing.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.scaffold import VSCard


class EmbeddedPreviewLayer(QWidget):
    """Full-page embedded player chrome. The dialog itself is supplied later."""

    def __init__(
        self,
        parent=None,
        *,
        show_detail: bool = True,
        show_actions: bool = True,
        object_name: str = "EmbeddedPreviewLayer",
    ):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.show_detail = bool(show_detail)
        self.show_actions = bool(show_actions)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        back_row = QHBoxLayout()
        back_row.setContentsMargins(0, 0, 0, 0)
        back_row.setSpacing(8)
        self.btn_preview_back = QPushButton("返回")
        self.btn_preview_back.setObjectName("GhostButton")
        self.btn_preview_back.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_preview_back.setMinimumHeight(30)
        back_row.addWidget(self.btn_preview_back, 0)

        self.btn_preview_shot_list = None
        self.btn_preview_export_tasks = None
        if self.show_actions:
            self.btn_preview_shot_list = QPushButton()
            self.btn_preview_shot_list.setObjectName("GhostButton")
            self.btn_preview_shot_list.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_preview_shot_list.setMinimumHeight(30)
            self.btn_preview_export_tasks = QPushButton()
            self.btn_preview_export_tasks.setObjectName("GhostButton")
            self.btn_preview_export_tasks.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_preview_export_tasks.setMinimumHeight(30)
            back_row.addWidget(self.btn_preview_shot_list, 0)
            back_row.addWidget(self.btn_preview_export_tasks, 0)
        back_row.addStretch(1)
        layout.addLayout(back_row)

        stage = QWidget()
        stage.setObjectName("SearchPreviewStage")
        stage_row = QHBoxLayout(stage)
        stage_row.setContentsMargins(0, 0, 0, 0)
        stage_row.setSpacing(10)
        self.preview_layer_host = QWidget()
        self.preview_layer_host_layout = QVBoxLayout(self.preview_layer_host)
        self.preview_layer_host_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_layer_host_layout.setSpacing(0)
        stage_row.addWidget(self.preview_layer_host, 1)

        self.preview_detail = None
        self.preview_detail_title = None
        self.preview_detail_name = None
        self.preview_detail_body = None
        if self.show_detail:
            self.preview_detail = VSCard(variant="sub", margins=(12, 12, 12, 12), spacing=6)
            self.preview_detail.setFixedWidth(280)
            self.preview_detail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            detail_layout = self.preview_detail.content_layout
            self.preview_detail_title = QLabel("当前视频")
            self.preview_detail_title.setObjectName("SectionTitle")
            self.preview_detail_name = QLabel()
            self.preview_detail_name.setObjectName("DialogMetaLabel")
            self.preview_detail_name.setWordWrap(True)
            self.preview_detail_body = QLabel()
            self.preview_detail_body.setObjectName("Hint")
            self.preview_detail_body.setWordWrap(True)
            self.preview_detail_body.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            self.preview_detail_body.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            detail_layout.addWidget(self.preview_detail_title)
            detail_layout.addWidget(self.preview_detail_name)
            detail_layout.addWidget(self.preview_detail_body, 1)
            stage_row.addWidget(self.preview_detail, 0)
        layout.addWidget(stage, 1)

        self.preview_strip_wrap = QWidget()
        strip_col = QVBoxLayout(self.preview_strip_wrap)
        strip_col.setContentsMargins(0, 0, 0, 0)
        strip_col.setSpacing(4)
        self.preview_strip_label = QLabel()
        self.preview_strip_label.setObjectName("StatusHint")
        strip_col.addWidget(self.preview_strip_label)
        self.preview_strip = QScrollArea()
        self.preview_strip.setObjectName("SearchPreviewStrip")
        self.preview_strip.setWidgetResizable(False)
        self.preview_strip.setFixedHeight(108)
        self.preview_strip_wrap.setMinimumHeight(128)
        self.preview_strip.setFrameShape(QFrame.Shape.NoFrame)
        self.preview_strip.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preview_strip.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.preview_strip_host = QWidget()
        self.preview_strip_host.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.preview_strip_host.setFixedHeight(86)
        self.preview_strip_row = QHBoxLayout(self.preview_strip_host)
        self.preview_strip_row.setContentsMargins(0, 0, 0, 0)
        self.preview_strip_row.setSpacing(8)
        self.preview_strip_row.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.preview_strip.setWidget(self.preview_strip_host)
        strip_col.addWidget(self.preview_strip)
        layout.addWidget(self.preview_strip_wrap, 0)
