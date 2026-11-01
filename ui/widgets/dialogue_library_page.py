"""Subtitle library page. Same chrome as the video library, without the mode switch."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ui.widgets.components import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.library_video_tree import LibraryGroupedVideoTree, LibraryIconButton
from ui.widgets.scaffold import PageScaffold, VSCard


class DialogueLibraryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.shared_toolbar_card = VSCard(
            variant="sub",
            margins=(12, 8, 12, 8),
            spacing=6,
            object_name="LibrarySharedStrip",
        )
        shared_outer = self.shared_toolbar_card.content_layout
        chrome_row = QHBoxLayout()
        chrome_row.setContentsMargins(0, 0, 0, 0)
        chrome_row.setSpacing(10)
        chrome_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        action_block = QVBoxLayout()
        action_block.setContentsMargins(0, 0, 0, 0)
        action_block.setSpacing(2)
        self.lbl_action_caption = QLabel()
        self.lbl_action_caption.setObjectName("LibraryChromeCaption")
        action_block.addWidget(self.lbl_action_caption)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.btn_add_lib = QPushButton()
        self.btn_add_lib.setObjectName("SuccessGhostButton")
        self.btn_add_lib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove_lib = QPushButton()
        self.btn_remove_lib.setObjectName("DangerGhostButton")
        self.btn_remove_lib.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_remove_lib.setEnabled(False)
        action_row.addWidget(self.btn_add_lib)
        action_row.addWidget(self.btn_remove_lib)
        action_block.addLayout(action_row)
        chrome_row.addLayout(action_block, 0)
        chrome_row.addStretch(1)
        shared_outer.addLayout(chrome_row)

        self.lbl_shared_library_hint = QLabel()
        self.lbl_shared_library_hint.setObjectName("LibraryChromeHint")
        self.lbl_shared_library_hint.setWordWrap(True)
        self.lbl_shared_library_hint.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.lbl_shared_library_hint.hide()
        shared_outer.addWidget(self.lbl_shared_library_hint)
        page_body.addWidget(self.shared_toolbar_card)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 8, 0, 0)
        body_layout.setSpacing(0)

        self.dialogue_table_card = VSCard(margins=(16, 14, 16, 14), spacing=12)
        self.dialogue_toolbar_card = self.dialogue_table_card
        dialogue_table_layout = self.dialogue_table_card.content_layout

        self.dialogue_table_title = QLabel()
        self.dialogue_table_title.setObjectName("CardTitle")
        dialogue_table_layout.addWidget(self.dialogue_table_title)

        dialogue_toolbar_host = QWidget()
        dialogue_toolbar_host.setObjectName("LibraryToolbarFlow")
        dialogue_toolbar = FlowLayout(dialogue_toolbar_host, spacing=8)
        self.btn_build_dialogue_index = QPushButton()
        self.btn_build_dialogue_index.setObjectName("PrimaryButton")
        self.btn_reembed_dialogue = QPushButton()
        self.btn_reembed_dialogue.setObjectName("AccentGhostButton")
        self.btn_clear_dialogue = QPushButton()
        self.btn_clear_dialogue.setObjectName("GhostButton")
        self.btn_import_subtitle_srt = QPushButton()
        self.btn_import_subtitle_srt.setObjectName("GhostButton")
        self.btn_export_dialogue = QPushButton()
        self.btn_export_dialogue.setObjectName("GhostButton")
        self.btn_refresh_dialogue_library = LibraryIconButton("refresh")
        self.btn_refresh_dialogue_library.setObjectName("GhostButton")
        self.btn_subtitle_sample_advanced = QPushButton()
        self.btn_subtitle_sample_advanced.setObjectName("GhostButton")
        self.btn_subtitle_sample_advanced.setCheckable(True)
        self.btn_subtitle_sample_advanced.setChecked(False)
        self.lbl_subtitle_sample_interval = QLabel()
        self.lbl_subtitle_sample_interval.setObjectName("CardHint")
        self.lbl_subtitle_sample_interval.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.input_subtitle_sample_interval = NoWheelDoubleSpinBox()
        self.input_subtitle_sample_interval.setRange(0.1, 6.0)
        self.input_subtitle_sample_interval.setSingleStep(0.1)
        self.input_subtitle_sample_interval.setDecimals(1)
        self.input_subtitle_sample_interval.setValue(1.2)
        self.input_subtitle_sample_interval.setSuffix(" s")
        self.input_subtitle_sample_interval.setMinimumWidth(88)
        self.input_subtitle_sample_interval.setMaximumWidth(110)
        self.lbl_subtitle_sample_strategy = QLabel()
        self.lbl_subtitle_sample_strategy.setObjectName("CardHint")
        self.lbl_subtitle_sample_strategy.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.input_subtitle_sample_strategy = NoWheelComboBox()
        self.input_subtitle_sample_strategy.setObjectName("SearchModeSelect")
        self.input_subtitle_sample_strategy.setMinimumWidth(120)
        self.input_subtitle_sample_strategy.setMaximumWidth(160)
        self.lbl_subtitle_ocr_batch = QLabel()
        self.lbl_subtitle_ocr_batch.setObjectName("CardHint")
        self.lbl_subtitle_ocr_batch.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.input_subtitle_ocr_batch = NoWheelSpinBox()
        self.input_subtitle_ocr_batch.setRange(1, 6)
        self.input_subtitle_ocr_batch.setSingleStep(1)
        self.input_subtitle_ocr_batch.setValue(6)
        self.input_subtitle_ocr_batch.setMinimumWidth(64)
        self.input_subtitle_ocr_batch.setMaximumWidth(80)
        self.btn_stop_dialogue_index = QPushButton()
        self.btn_stop_dialogue_index.setObjectName("DangerGhostButton")
        self.btn_stop_dialogue_index.setEnabled(False)
        self.btn_stop_dialogue_index.setVisible(False)

        self.subtitle_video_tree = LibraryGroupedVideoTree()
        self.subtitle_video_tree.setMinimumHeight(280)
        self.dialogue_list = self.subtitle_video_tree

        dialogue_toolbar.addWidget(self.btn_build_dialogue_index)
        dialogue_toolbar.addWidget(self.btn_reembed_dialogue)
        dialogue_toolbar.addWidget(self.btn_clear_dialogue)
        dialogue_toolbar.addWidget(self.btn_import_subtitle_srt)
        dialogue_toolbar.addWidget(self.btn_export_dialogue)
        dialogue_toolbar.addWidget(self.btn_refresh_dialogue_library)
        dialogue_toolbar.addWidget(self.btn_subtitle_sample_advanced)
        dialogue_toolbar.addWidget(self.subtitle_video_tree.find_bar)
        dialogue_toolbar.addWidget(self.btn_stop_dialogue_index)
        dialogue_table_layout.addWidget(dialogue_toolbar_host)

        self.subtitle_sample_advanced_row = QWidget()
        advanced_row = QHBoxLayout(self.subtitle_sample_advanced_row)
        advanced_row.setContentsMargins(0, 0, 0, 0)
        advanced_row.setSpacing(8)
        advanced_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.lbl_subtitle_sample_strategy, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.input_subtitle_sample_strategy, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.lbl_subtitle_sample_interval, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.input_subtitle_sample_interval, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.lbl_subtitle_ocr_batch, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addWidget(self.input_subtitle_ocr_batch, 0, Qt.AlignmentFlag.AlignVCenter)
        advanced_row.addStretch(1)
        self.subtitle_sample_advanced_row.setVisible(False)
        self.btn_subtitle_sample_advanced.toggled.connect(self.subtitle_sample_advanced_row.setVisible)
        dialogue_table_layout.addWidget(self.subtitle_sample_advanced_row)

        dialogue_table_layout.addWidget(self.subtitle_video_tree, 1)
        self.subtitle_video_tree.find_bar.install_shortcuts(self.dialogue_table_card)
        body_layout.addWidget(self.dialogue_table_card, 1)
        page_body.addWidget(body, 1)

        self.progress_host = QWidget()
        self.progress_host_layout = QVBoxLayout(self.progress_host)
        self.progress_host_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_host_layout.setSpacing(0)
        page_body.addWidget(self.progress_host)
