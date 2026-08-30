"""Understanding page: select → generate → export, stacked top to bottom."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.chunk_timeline import ChunkTimelineWidget
from ui.widgets.components import NoWheelComboBox
from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import PageScaffold, VSCard, VSProgressStatusRow, make_runtime_banner
from ui.widgets.data_table import DataTable
from ui.widgets.searchable_id_combo import SearchableIdCombo
from ui.widgets.table_specs import UNDERSTANDING_DIALOGUE_TABLE_SPEC


def _field_label(text=""):
    label = QLabel(text)
    label.setObjectName("CardHint")
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    label.setFixedWidth(COMPONENT_SIZES.get("understanding_form_label_width", 96))
    return label


def _action_button(object_name: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return button


def _toolbar_frame() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("UnderstandingToolbar")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(10)
    return frame, layout


def _button_row() -> QHBoxLayout:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return row


def _step_hint() -> QLabel:
    hint = QLabel()
    hint.setObjectName("CardHint")
    hint.setWordWrap(True)
    return hint


class UnderstandingEvidencePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.understanding_notice, self.understanding_notice_text = make_runtime_banner()
        self.btn_understanding_setup = _action_button("GhostButton")
        self.btn_understanding_setup.setMinimumHeight(30)
        self.understanding_notice.layout().addWidget(self.btn_understanding_setup, 0)
        self.understanding_notice.hide()
        page_body.addWidget(self.understanding_notice)

        self.workspace_card = VSCard(margins=(18, 16, 18, 16), spacing=10)
        self.workspace_title = QLabel()
        self.workspace_title.setObjectName("CardTitle")
        self.select_hint = _step_hint()
        self.workspace_card.content_layout.addWidget(self.workspace_title)
        self.workspace_card.content_layout.addWidget(self.select_hint)
        self._build_select_step(self.workspace_card.content_layout)
        page_body.addWidget(self.workspace_card)

        self.generate_card = VSCard(margins=(18, 16, 18, 16), spacing=10)
        self.generate_title = QLabel()
        self.generate_title.setObjectName("CardTitle")
        self.generate_hint = _step_hint()
        self.generate_card.content_layout.addWidget(self.generate_title)
        self.generate_card.content_layout.addWidget(self.generate_hint)
        self._build_generate_step(self.generate_card.content_layout)
        page_body.addWidget(self.generate_card)

        self.dialogue_card = VSCard(margins=(18, 16, 18, 16), spacing=10)
        self.dialogue_title = QLabel()
        self.dialogue_title.setObjectName("CardTitle")
        self.dialogue_hint = _step_hint()
        self.dialogue_card.content_layout.addWidget(self.dialogue_title)
        self.dialogue_card.content_layout.addWidget(self.dialogue_hint)
        self._build_dialogue_step(self.dialogue_card.content_layout)
        page_body.addWidget(self.dialogue_card)

        self.export_card = VSCard(margins=(18, 16, 18, 16), spacing=10)
        self.export_title = QLabel()
        self.export_title.setObjectName("CardTitle")
        self.export_hint = _step_hint()
        self.export_card.content_layout.addWidget(self.export_title)
        self.export_card.content_layout.addWidget(self.export_hint)
        self._build_export_step(self.export_card.content_layout)
        page_body.addWidget(self.export_card)
        self.dialogue_card.hide()
        self.export_card.hide()
        self.video_summary_card.hide()
        page_body.addStretch(1)

    def _build_select_step(self, layout: QVBoxLayout) -> None:
        self.picker_strip, strip_layout = _toolbar_frame()
        form_host = QWidget()
        config_form = QFormLayout(form_host)
        config_form.setContentsMargins(0, 0, 0, 0)
        config_form.setHorizontalSpacing(12)
        config_form.setVerticalSpacing(10)
        config_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        config_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        config_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        self.scope_label = _field_label()
        self.scope_combo = QComboBox()
        self.scope_combo.setObjectName("SearchModeSelect")
        self.scope_combo.setMinimumWidth(220)
        self.scope_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.video_label = _field_label()
        self.video_combo = SearchableIdCombo()
        self.video_combo.setMinimumWidth(240)
        self.video_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.label_understanding_mode = _field_label()
        self.input_understanding_mode = NoWheelComboBox()
        self.input_understanding_mode.setObjectName("SearchModeSelect")
        self.input_understanding_mode.setMinimumWidth(160)
        self.input_understanding_mode.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.label_caption_language = _field_label()
        self.input_caption_language = NoWheelComboBox()
        self.input_caption_language.setObjectName("SearchModeSelect")
        self.input_caption_language.setMinimumWidth(160)
        self.input_caption_language.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.btn_open_services = _action_button("GhostButton")

        config_form.addRow(self.scope_label, self.scope_combo)
        config_form.addRow(self.video_label, self.video_combo)
        config_form.addRow(self.label_understanding_mode, self.input_understanding_mode)
        config_form.addRow(self.label_caption_language, self.input_caption_language)
        services_label = QWidget()
        services_label.setFixedWidth(COMPONENT_SIZES.get("understanding_form_label_width", 96))
        config_form.addRow(services_label, self.btn_open_services)
        strip_layout.addWidget(form_host)
        layout.addWidget(self.picker_strip)

        self.lbl_understanding_hint = QLabel()
        self.lbl_understanding_hint.setObjectName("UnderstandingChromeHint")
        self.lbl_understanding_hint.setWordWrap(True)
        layout.addWidget(self.lbl_understanding_hint)

    def _build_generate_step(self, layout: QVBoxLayout) -> None:
        actions, actions_layout = _toolbar_frame()
        row = _button_row()
        self.btn_generate_evidence = _action_button("PrimaryButton")
        self.btn_generate_batch = _action_button("GhostButton")
        self.btn_generate_summary = _action_button("GhostButton")
        self.btn_generate_summary.hide()
        self.btn_stop = _action_button("DangerGhostButton")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        row.addWidget(self.btn_generate_evidence, 0)
        row.addWidget(self.btn_generate_batch, 0)
        row.addWidget(self.btn_generate_summary, 0)
        self.btn_export_video_json = _action_button("GhostButton")
        self.btn_evidence_details = _action_button("GhostButton")
        row.addWidget(self.btn_export_video_json, 0)
        row.addWidget(self.btn_evidence_details, 0)
        row.addWidget(self.btn_stop, 0)
        row.addStretch(1)
        actions_layout.addLayout(row)
        layout.addWidget(actions)

        self.progress_status = VSProgressStatusRow()
        self.progress_bar = self.progress_status.progress_bar
        self.lbl_status = self.progress_status.status_label
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_status)

        timeline_block = QFrame()
        timeline_block.setObjectName("UnderstandingTimelineBlock")
        timeline_layout = QVBoxLayout(timeline_block)
        timeline_layout.setContentsMargins(12, 10, 12, 10)
        timeline_layout.setSpacing(8)

        timeline_header = QHBoxLayout()
        timeline_header.setSpacing(8)
        self.timeline_label = QLabel()
        self.timeline_label.setObjectName("CardHint")
        self.timeline_hint = QLabel()
        self.timeline_hint.setObjectName("StatusHint")
        self.timeline_hint.setWordWrap(False)
        self.timeline_hint.setFixedHeight(18)
        timeline_header.addWidget(self.timeline_label, 0)
        timeline_header.addWidget(self.timeline_hint, 1)
        timeline_layout.addLayout(timeline_header)

        self.chunk_timeline_scroll = QScrollArea()
        self.chunk_timeline_scroll.setObjectName("ChunkTimelineScroll")
        self.chunk_timeline_scroll.setWidgetResizable(False)
        self.chunk_timeline_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.chunk_timeline_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chunk_timeline_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chunk_timeline_scroll.setFixedHeight(56)
        self.chunk_timeline = ChunkTimelineWidget()
        self.chunk_timeline.setFixedHeight(32)
        self.chunk_timeline_scroll.setWidget(self.chunk_timeline)
        timeline_layout.addWidget(self.chunk_timeline_scroll)
        layout.addWidget(timeline_block)

        self.chunk_detail_card = VSCard(
            variant="sub",
            margins=(14, 12, 14, 12),
            spacing=8,
            object_name="UnderstandingDetailPanel",
        )
        chunk_detail_layout = self.chunk_detail_card.content_layout
        segment_header = QHBoxLayout()
        segment_header.setContentsMargins(0, 0, 0, 0)
        segment_header.setSpacing(10)
        self.chunk_detail_title = QLabel()
        self.chunk_detail_title.setObjectName("CardTitle")
        self.chunk_time_label = QLabel()
        self.chunk_time_label.setObjectName("UnderstandingChunkTimeLabel")
        self.chunk_time_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        segment_header.addWidget(self.chunk_detail_title, 0)
        segment_header.addStretch(1)
        segment_header.addWidget(self.chunk_time_label, 0)
        chunk_detail_layout.addLayout(segment_header)

        self.chunk_sample_frames = QWidget()
        sample_frames_layout = QHBoxLayout(self.chunk_sample_frames)
        sample_frames_layout.setContentsMargins(0, 0, 0, 0)
        sample_frames_layout.setSpacing(8)
        self.chunk_frame_start = QLabel()
        self.chunk_frame_start.setObjectName("UnderstandingSampleFrame")
        self.chunk_frame_start.setFixedHeight(96)
        self.chunk_frame_start.setMinimumWidth(120)
        self.chunk_frame_start.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chunk_frame_end = QLabel()
        self.chunk_frame_end.setObjectName("UnderstandingSampleFrame")
        self.chunk_frame_end.setFixedHeight(96)
        self.chunk_frame_end.setMinimumWidth(120)
        self.chunk_frame_end.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sample_frames_layout.addWidget(self.chunk_frame_start, 1)
        sample_frames_layout.addWidget(self.chunk_frame_end, 1)
        self.chunk_sample_frames.setVisible(False)
        chunk_detail_layout.addWidget(self.chunk_sample_frames)

        self.chunk_caption_text = QPlainTextEdit()
        self.chunk_caption_text.setObjectName("UnderstandingOutput")
        self.chunk_caption_text.setReadOnly(True)
        self.chunk_caption_text.setMinimumHeight(168)
        self.chunk_caption_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        chunk_detail_layout.addWidget(self.chunk_caption_text, 1)
        layout.addWidget(self.chunk_detail_card)

        self.video_summary_card = VSCard(
            variant="sub",
            margins=(14, 12, 14, 12),
            spacing=8,
            object_name="UnderstandingDetailPanel",
        )
        summary_layout = self.video_summary_card.content_layout
        summary_header = QHBoxLayout()
        summary_header.setContentsMargins(0, 0, 0, 0)
        summary_header.setSpacing(8)
        self.video_summary_title = QLabel()
        self.video_summary_title.setObjectName("CardTitle")
        summary_header.addWidget(self.video_summary_title, 0)
        summary_header.addStretch(1)
        summary_layout.addLayout(summary_header)
        self.video_summary_text = QPlainTextEdit()
        self.video_summary_text.setObjectName("UnderstandingOutput")
        self.video_summary_text.setReadOnly(True)
        self.video_summary_text.setMinimumHeight(148)
        self.video_summary_text.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        summary_layout.addWidget(self.video_summary_text, 1)
        self.video_summary_meta_label = QLabel()
        self.video_summary_meta_label.setObjectName("StatusHint")
        self.video_summary_meta_label.setWordWrap(True)
        self.video_summary_meta_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        summary_layout.addWidget(self.video_summary_meta_label)
        layout.addWidget(self.video_summary_card)

    def _build_dialogue_step(self, layout: QVBoxLayout) -> None:
        actions, actions_layout = _toolbar_frame()
        row = _button_row()
        self.btn_open_subtitle_library = _action_button("AccentGhostButton")
        self.btn_open_subtitle_library.setVisible(False)
        self.btn_extract_asr = _action_button("AccentGhostButton")
        row.addWidget(self.btn_open_subtitle_library, 0)
        row.addWidget(self.btn_extract_asr, 0)
        self.btn_export_dialogue_json = _action_button("GhostButton")
        row.addWidget(self.btn_export_dialogue_json, 0)
        self.btn_stop_asr = _action_button("DangerGhostButton")
        self.btn_stop_asr.setEnabled(False)
        self.btn_stop_asr.setVisible(False)
        row.addWidget(self.btn_stop_asr, 0)
        row.addStretch(1)
        actions_layout.addLayout(row)
        layout.addWidget(actions)
        self.dialogue_status = QLabel()
        self.dialogue_status.setObjectName("UnderstandingChromeHint")
        self.dialogue_status.setWordWrap(True)
        layout.addWidget(self.dialogue_status)
        self.dialogue_progress_status = VSProgressStatusRow()
        self.dialogue_progress_bar = self.dialogue_progress_status.progress_bar
        self.dialogue_progress_bar.setVisible(False)
        layout.addWidget(self.dialogue_progress_status)
        self.dialogue_table = DataTable(spec=UNDERSTANDING_DIALOGUE_TABLE_SPEC)
        self.dialogue_table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.dialogue_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.dialogue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.dialogue_table.setMinimumHeight(200)
        self.dialogue_table.setMaximumHeight(280)
        self.dialogue_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.dialogue_table)

    def _build_export_step(self, layout: QVBoxLayout) -> None:
        prompt_header = QHBoxLayout()
        prompt_header.setContentsMargins(0, 0, 0, 0)
        prompt_header.setSpacing(8)
        self.recap_prompt_label = QLabel()
        self.recap_prompt_label.setObjectName("CardTitle")
        self.btn_reset_recap_prompt = _action_button("GhostButton")
        prompt_header.addWidget(self.recap_prompt_label, 0)
        prompt_header.addStretch(1)
        prompt_header.addWidget(self.btn_reset_recap_prompt, 0)
        layout.addLayout(prompt_header)
        self.recap_prompt_hint = _step_hint()
        layout.addWidget(self.recap_prompt_hint)

        self.recap_prompt_tabs = QTabWidget()
        self.recap_prompt_tabs.setObjectName("RecapPromptTabs")
        self.input_recap_plan_prompt = QPlainTextEdit()
        self.input_recap_prompt = QPlainTextEdit()
        self.input_recap_caption_prompt = QPlainTextEdit()
        for editor in (
            self.input_recap_plan_prompt,
            self.input_recap_prompt,
            self.input_recap_caption_prompt,
        ):
            editor.setObjectName("UnderstandingOutput")
            editor.setMinimumHeight(148)
            editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.recap_prompt_tabs.addTab(self.input_recap_plan_prompt, "")
        self.recap_prompt_tabs.addTab(self.input_recap_prompt, "")
        self.recap_prompt_tabs.addTab(self.input_recap_caption_prompt, "")
        layout.addWidget(self.recap_prompt_tabs)

        start_row = _button_row()
        self.recap_start_label = QLabel()
        self.recap_start_label.setObjectName("CardHint")
        self.input_recap_start = NoWheelComboBox()
        self.input_recap_start.setObjectName("SearchModeSelect")
        self.input_recap_start.setMinimumWidth(240)
        self.input_recap_start.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        start_row.addWidget(self.recap_start_label, 0)
        start_row.addWidget(self.input_recap_start, 1)
        layout.addLayout(start_row)

        actions, actions_layout = _toolbar_frame()
        row = _button_row()
        self.btn_export_recap = _action_button("PrimaryButton")
        self.btn_recap_jianying = _action_button("GhostButton")
        self.btn_recap_fcpxml = _action_button("GhostButton")
        row.addWidget(self.btn_export_recap, 0)
        row.addWidget(self.btn_recap_jianying, 0)
        row.addWidget(self.btn_recap_fcpxml, 0)
        row.addStretch(1)
        actions_layout.addLayout(row)
        layout.addWidget(actions)
        self.recap_progress_status = VSProgressStatusRow()
        self.recap_progress_bar = self.recap_progress_status.progress_bar
        self.recap_progress_bar.setVisible(False)
        layout.addWidget(self.recap_progress_status)
