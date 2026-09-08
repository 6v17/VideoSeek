"""Understanding page: stacked workflow cards (tags/summary vs ASR-first recap)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.chunk_timeline import ChunkTimelineWidget
from ui.widgets.components import NoWheelComboBox
from ui.widgets.data_table import DataTable
from ui.widgets.recap_review_delegate import RecapReviewItemDelegate
from ui.widgets.scaffold import PageScaffold, VSCard, VSProgressStatusRow, make_runtime_banner
from ui.widgets.searchable_id_combo import SearchableIdCombo
from ui.widgets.table_specs import (
    UNDERSTANDING_DIALOGUE_TABLE_SPEC,
)
from ui.widgets.vertical_stretch import add_vertically_stretchable


def _action_button(object_name: str) -> QPushButton:
    button = QPushButton()
    button.setObjectName(object_name)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    # Mouse activates without taking focus — avoids QScrollArea yanking to the button.
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setAutoDefault(False)
    button.setDefault(False)
    return button


def _step_hint() -> QLabel:
    hint = QLabel()
    hint.setObjectName("CardHint")
    hint.setWordWrap(True)
    return hint


def _status_hint() -> QLabel:
    hint = QLabel()
    hint.setObjectName("StatusHint")
    hint.setWordWrap(True)
    return hint


def _field_label() -> QLabel:
    label = QLabel()
    label.setObjectName("InlineFieldLabel")
    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return label


def _stack_field(label: QLabel, field: QWidget) -> QWidget:
    host = QWidget()
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    layout.addWidget(label)
    layout.addWidget(field)
    return host


def _command_bar(object_name: str = "UnderstandingCommandBar") -> tuple[QWidget, QHBoxLayout]:
    bar = QWidget()
    bar.setObjectName(object_name)
    row = QHBoxLayout(bar)
    row.setContentsMargins(0, 2, 0, 2)
    row.setSpacing(8)
    row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return bar, row


def _add_step_header(
    layout: QVBoxLayout,
    title: QLabel,
    hint: QLabel,
    trailing: QWidget | None = None,
) -> None:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
    row.addStretch(1)
    if trailing is not None:
        row.addWidget(trailing, 0, Qt.AlignmentFlag.AlignVCenter)
    layout.addLayout(row)
    layout.addWidget(hint)


class _UnderstandingSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("UnderstandingSection")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 2, 0, 0)
        self._layout.setSpacing(8)

    @property
    def content_layout(self) -> QVBoxLayout:
        return self._layout


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

        self.workspace_card = VSCard(margins=(20, 16, 20, 16), spacing=12)
        self.workspace_title = QLabel()
        self.workspace_title.setObjectName("CardTitle")
        self.select_hint = _step_hint()
        self.btn_open_services = _action_button("AccentGhostButton")
        _add_step_header(
            self.workspace_card.content_layout,
            self.workspace_title,
            self.select_hint,
            self.btn_open_services,
        )
        self._build_select_step(self.workspace_card.content_layout)
        page_body.addWidget(self.workspace_card)

        self.generate_card = VSCard(margins=(20, 16, 20, 16), spacing=12)
        self.generate_title = QLabel()
        self.generate_title.setObjectName("CardTitle")
        self.generate_hint = _step_hint()
        _add_step_header(self.generate_card.content_layout, self.generate_title, self.generate_hint)
        self._build_generate_step(self.generate_card.content_layout)
        page_body.addWidget(self.generate_card)

        self.dialogue_card = VSCard(margins=(20, 16, 20, 16), spacing=12)
        self.dialogue_title = QLabel()
        self.dialogue_title.setObjectName("CardTitle")
        self.dialogue_hint = _step_hint()
        _add_step_header(self.dialogue_card.content_layout, self.dialogue_title, self.dialogue_hint)
        self._build_dialogue_step(self.dialogue_card.content_layout)
        page_body.addWidget(self.dialogue_card)

        self.export_card = VSCard(margins=(20, 16, 20, 16), spacing=12)
        self.export_title = QLabel()
        self.export_title.setObjectName("CardTitle")
        self.export_hint = _step_hint()
        _add_step_header(self.export_card.content_layout, self.export_title, self.export_hint)
        self._build_export_step(self.export_card.content_layout)
        page_body.addWidget(self.export_card)
        self.video_summary_card.hide()
        page_body.addStretch(1)
        self.order_workflow_cards(recap_first=True)

    def order_workflow_cards(self, *, recap_first: bool) -> None:
        layout = self.scaffold.content_layout
        if recap_first:
            cards = (self.workspace_card, self.dialogue_card, self.generate_card, self.export_card)
        else:
            cards = (self.workspace_card, self.generate_card, self.dialogue_card, self.export_card)
        insert_at = layout.indexOf(self.understanding_notice) + 1
        if insert_at <= 0:
            insert_at = 0
        # Reshuffling an already-correct order rebuilds geometry and jumps the page scroll.
        already = True
        for offset, card in enumerate(cards):
            item = layout.itemAt(insert_at + offset)
            if item is None or item.widget() is not card:
                already = False
                break
        if already:
            return
        for card in cards:
            layout.removeWidget(card)
        for offset, card in enumerate(cards):
            layout.insertWidget(insert_at + offset, card)

    def _build_select_step(self, layout: QVBoxLayout) -> None:
        self.picker_strip = QWidget()
        self.picker_strip.setObjectName("UnderstandingCommandBar")
        grid = QGridLayout(self.picker_strip)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        self.scope_label = _field_label()
        self.scope_combo = NoWheelComboBox()
        self.scope_combo.setObjectName("SearchModeSelect")
        self.scope_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.video_label = _field_label()
        self.video_combo = SearchableIdCombo()
        self.video_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self.label_caption_language = _field_label()
        self.input_caption_language = NoWheelComboBox()
        self.input_caption_language.setObjectName("SearchModeSelect")
        self.input_caption_language.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        grid.addWidget(_stack_field(self.scope_label, self.scope_combo), 0, 0)
        grid.addWidget(_stack_field(self.video_label, self.video_combo), 0, 1)
        grid.addWidget(_stack_field(self.label_caption_language, self.input_caption_language), 1, 0)
        layout.addWidget(self.picker_strip)

        self.lbl_understanding_hint = _status_hint()
        layout.addWidget(self.lbl_understanding_hint)

    def _build_generate_step(self, layout: QVBoxLayout) -> None:
        prompt_row = QHBoxLayout()
        prompt_row.setContentsMargins(0, 0, 0, 0)
        prompt_row.setSpacing(8)
        self.vlm_prompt_label = QLabel()
        self.vlm_prompt_label.setObjectName("InlineFieldLabel")
        self.btn_reset_custom_prompts = _action_button("GhostButton")
        prompt_row.addWidget(self.vlm_prompt_label, 0, Qt.AlignmentFlag.AlignVCenter)
        prompt_row.addStretch(1)
        prompt_row.addWidget(self.btn_reset_custom_prompts, 0)
        layout.addLayout(prompt_row)
        self.vlm_prompt_hint = _step_hint()
        layout.addWidget(self.vlm_prompt_hint)

        self.vlm_prompt_tabs = QTabWidget()
        self.vlm_prompt_tabs.setObjectName("RecapPromptTabs")
        self.input_custom_caption_prompt = QPlainTextEdit()
        self.input_custom_description_prompt = QPlainTextEdit()
        self.input_custom_motion_prompt = QPlainTextEdit()
        self.input_custom_summary_prompt = QPlainTextEdit()
        for editor in (
            self.input_custom_caption_prompt,
            self.input_custom_description_prompt,
            self.input_custom_motion_prompt,
            self.input_custom_summary_prompt,
        ):
            editor.setObjectName("UnderstandingOutput")
            editor.setMinimumHeight(80)
            editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            editor.setTabChangesFocus(True)
        self.vlm_prompt_tabs.addTab(self.input_custom_caption_prompt, "")
        self.vlm_prompt_tabs.addTab(self.input_custom_description_prompt, "")
        self.vlm_prompt_tabs.addTab(self.input_custom_motion_prompt, "")
        self.vlm_prompt_tabs.addTab(self.input_custom_summary_prompt, "")
        self._vlm_prompt_stretch = add_vertically_stretchable(
            layout,
            self.vlm_prompt_tabs,
            default_height=168,
            min_height=120,
            max_height=720,
        )

        actions, row = _command_bar()
        self.btn_generate_evidence = _action_button("PrimaryButton")
        self.btn_generate_batch = _action_button("AccentGhostButton")
        self.btn_project_tags = _action_button("SuccessGhostButton")
        self.btn_export_video_json = _action_button("GhostButton")
        self.btn_evidence_details = _action_button("GhostButton")
        self.btn_stop = _action_button("DangerGhostButton")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setVisible(False)
        row.addWidget(self.btn_generate_evidence, 0)
        row.addWidget(self.btn_generate_batch, 0)
        row.addWidget(self.btn_project_tags, 0)
        row.addStretch(1)
        row.addWidget(self.btn_export_video_json, 0)
        row.addWidget(self.btn_evidence_details, 0)
        row.addWidget(self.btn_stop, 0)
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
        timeline_layout.setSpacing(6)

        timeline_header = QHBoxLayout()
        timeline_header.setContentsMargins(0, 0, 0, 0)
        timeline_header.setSpacing(8)
        self.timeline_label = QLabel()
        self.timeline_label.setObjectName("InlineFieldLabel")
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
        self.chunk_timeline_scroll.setFixedHeight(48)
        self.chunk_timeline = ChunkTimelineWidget()
        self.chunk_timeline.setFixedHeight(28)
        self.chunk_timeline_scroll.setWidget(self.chunk_timeline)
        timeline_layout.addWidget(self.chunk_timeline_scroll)
        layout.addWidget(timeline_block)

        self.chunk_detail_card = _UnderstandingSection()
        chunk_detail_layout = self.chunk_detail_card.content_layout
        segment_header = QHBoxLayout()
        segment_header.setContentsMargins(0, 0, 0, 0)
        segment_header.setSpacing(10)
        self.chunk_detail_title = QLabel()
        self.chunk_detail_title.setObjectName("InlineFieldLabel")
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
        self._chunk_caption_stretch = add_vertically_stretchable(
            chunk_detail_layout,
            self.chunk_caption_text,
            default_height=160,
            min_height=100,
            max_height=900,
        )
        layout.addWidget(self.chunk_detail_card)

        self.video_summary_card = _UnderstandingSection()
        summary_layout = self.video_summary_card.content_layout
        self.video_summary_title = QLabel()
        self.video_summary_title.setObjectName("InlineFieldLabel")
        summary_layout.addWidget(self.video_summary_title)
        self.video_summary_text = QPlainTextEdit()
        self.video_summary_text.setObjectName("UnderstandingOutput")
        self.video_summary_text.setReadOnly(True)
        self._video_summary_stretch = add_vertically_stretchable(
            summary_layout,
            self.video_summary_text,
            default_height=140,
            min_height=100,
            max_height=900,
        )
        self.video_summary_meta_label = QLabel()
        self.video_summary_meta_label.setObjectName("StatusHint")
        self.video_summary_meta_label.setWordWrap(True)
        self.video_summary_meta_label.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum
        )
        summary_layout.addWidget(self.video_summary_meta_label)
        layout.addWidget(self.video_summary_card)

    def _build_dialogue_step(self, layout: QVBoxLayout) -> None:
        actions, row = _command_bar()
        self.btn_open_subtitle_library = _action_button("GhostButton")
        self.btn_open_subtitle_library.setVisible(False)
        self.btn_extract_asr = _action_button("PrimaryButton")
        self.btn_cluster_speakers = _action_button("AccentGhostButton")
        self.btn_rename_speakers = _action_button("NeutralToolButton")
        self.btn_reset_speakers = _action_button("DangerGhostButton")
        self.btn_export_dialogue_json = _action_button("GhostButton")
        self.btn_stop_asr = _action_button("DangerGhostButton")
        self.btn_stop_asr.setEnabled(False)
        self.btn_stop_asr.setVisible(False)
        row.addWidget(self.btn_extract_asr, 0)
        row.addWidget(self.btn_cluster_speakers, 0)
        row.addWidget(self.btn_rename_speakers, 0)
        row.addWidget(self.btn_reset_speakers, 0)
        row.addWidget(self.btn_open_subtitle_library, 0)
        row.addStretch(1)
        row.addWidget(self.btn_export_dialogue_json, 0)
        row.addWidget(self.btn_stop_asr, 0)
        layout.addWidget(actions)

        self.dialogue_status = _status_hint()
        layout.addWidget(self.dialogue_status)
        self.dialogue_progress_status = VSProgressStatusRow()
        self.dialogue_progress_bar = self.dialogue_progress_status.progress_bar
        self.dialogue_progress_bar.setVisible(False)
        layout.addWidget(self.dialogue_progress_status)
        self.dialogue_table = DataTable(spec=UNDERSTANDING_DIALOGUE_TABLE_SPEC)
        self.dialogue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.dialogue_table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.dialogue_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._dialogue_table_stretch = add_vertically_stretchable(
            layout,
            self.dialogue_table,
            default_height=240,
            min_height=140,
            max_height=1200,
        )

    def _build_export_step(self, layout: QVBoxLayout) -> None:
        prompt_row = QHBoxLayout()
        prompt_row.setContentsMargins(0, 0, 0, 0)
        prompt_row.setSpacing(8)
        self.recap_prompt_label = QLabel()
        self.recap_prompt_label.setObjectName("InlineFieldLabel")
        self.btn_reset_recap_prompt = _action_button("GhostButton")
        prompt_row.addWidget(self.recap_prompt_label, 0, Qt.AlignmentFlag.AlignVCenter)
        prompt_row.addStretch(1)
        prompt_row.addWidget(self.btn_reset_recap_prompt, 0)
        layout.addLayout(prompt_row)
        self.recap_prompt_hint = _step_hint()
        layout.addWidget(self.recap_prompt_hint)

        self.recap_prompt_tabs = QTabWidget()
        self.recap_prompt_tabs.setObjectName("RecapPromptTabs")
        self.input_recap_plan_prompt = QPlainTextEdit()
        self.input_recap_prompt = QPlainTextEdit()
        self.input_recap_caption_prompt = QPlainTextEdit()
        self.input_recap_polish_prompt = QPlainTextEdit()
        for editor in (
            self.input_recap_plan_prompt,
            self.input_recap_prompt,
            self.input_recap_caption_prompt,
            self.input_recap_polish_prompt,
        ):
            editor.setObjectName("UnderstandingOutput")
            editor.setMinimumHeight(80)
            editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.recap_prompt_tabs.addTab(self.input_recap_plan_prompt, "")
        self.recap_prompt_tabs.addTab(self.input_recap_prompt, "")
        self.recap_prompt_tabs.addTab(self.input_recap_caption_prompt, "")
        self.recap_prompt_tabs.addTab(self.input_recap_polish_prompt, "")
        self._recap_prompt_stretch = add_vertically_stretchable(
            layout,
            self.recap_prompt_tabs,
            default_height=168,
            min_height=120,
            max_height=720,
        )

        steps, step_row = _command_bar("UnderstandingStepBar")
        self.recap_step_bar = steps
        self.btn_recap_step_plan = _action_button("GhostButton")
        self.btn_recap_step_match = _action_button("GhostButton")
        self.btn_recap_step_captions = _action_button("GhostButton")
        step_row.addWidget(self.btn_recap_step_plan, 0)
        step_row.addWidget(self.btn_recap_step_match, 0)
        step_row.addWidget(self.btn_recap_step_captions, 0)
        step_row.addStretch(1)
        layout.addWidget(steps)

        actions, row = _command_bar()
        self.recap_main_bar = actions
        self.btn_export_recap = _action_button("PrimaryButton")
        self.btn_edit_recap_beats = _action_button("GhostButton")
        self.btn_recap_jianying = _action_button("SuccessGhostButton")
        self.btn_recap_fcpxml = _action_button("AccentGhostButton")
        row.addWidget(self.btn_export_recap, 0)
        row.addWidget(self.btn_edit_recap_beats, 0)
        row.addStretch(1)
        row.addWidget(self.btn_recap_jianying, 0)
        row.addWidget(self.btn_recap_fcpxml, 0)
        layout.addWidget(actions)
        self.recap_start_hint = _step_hint()
        layout.addWidget(self.recap_start_hint)
        self.recap_progress_status = VSProgressStatusRow()
        self.recap_progress_bar = self.recap_progress_status.progress_bar
        self.recap_progress_bar.setVisible(False)
        layout.addWidget(self.recap_progress_status)

        self.recap_review_panel = VSCard(
            variant="sub",
            margins=(14, 12, 14, 12),
            spacing=8,
            object_name="RecapReviewPanel",
        )
        review = self.recap_review_panel.content_layout
        self.recap_review_title = QLabel()
        self.recap_review_title.setObjectName("SectionTitle")
        self.recap_review_hint = _step_hint()
        _add_step_header(review, self.recap_review_title, self.recap_review_hint)
        self.recap_review_status = _status_hint()
        review.addWidget(self.recap_review_status)
        self.recap_review_detail = QLabel()
        self.recap_review_detail.setObjectName("RecapReviewDetail")
        self.recap_review_detail.setWordWrap(True)
        self.recap_review_detail.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self.recap_review_detail.setMinimumHeight(76)
        self.recap_review_detail.setMaximumHeight(110)
        self.recap_review_detail.setTextFormat(Qt.TextFormat.RichText)
        self.recap_review_detail.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        review.addWidget(self.recap_review_detail)
        review_actions, review_row = _command_bar()
        self.recap_review_action_bar = review_actions
        self.btn_edit_recap_unit_vo = _action_button("AccentGhostButton")
        self.btn_edit_recap_unit_vo.setEnabled(False)
        self.btn_recap_shot_up = _action_button("GhostButton")
        self.btn_recap_shot_up.setEnabled(False)
        self.btn_recap_shot_down = _action_button("GhostButton")
        self.btn_recap_shot_down.setEnabled(False)
        self.btn_add_recap_shot = _action_button("SuccessGhostButton")
        self.btn_add_recap_shot.setEnabled(False)
        self.btn_delete_recap = _action_button("DangerGhostButton")
        self.btn_delete_recap.setEnabled(False)
        # Legacy LLM review actions kept hidden (generation stays 4-prompt only).
        self.btn_rewrite_recap_vo = _action_button("GhostButton")
        self.btn_rewrite_recap_vo.setVisible(False)
        self.btn_rematch_recap_beat = _action_button("GhostButton")
        self.btn_rematch_recap_beat.setVisible(False)
        self.btn_rematch_weak_beats = _action_button("GhostButton")
        self.btn_rematch_weak_beats.setVisible(False)
        review_row.addWidget(self.btn_edit_recap_unit_vo, 0)
        review_row.addWidget(self.btn_recap_shot_up, 0)
        review_row.addWidget(self.btn_recap_shot_down, 0)
        review_row.addWidget(self.btn_add_recap_shot, 0)
        review_row.addWidget(self.btn_delete_recap, 0)
        review_row.addStretch(1)
        review.addWidget(review_actions)
        self.recap_review_tree = QTreeWidget()
        self.recap_review_tree.setObjectName("RecapReviewTree")
        self.recap_review_tree.setColumnCount(4)
        self.recap_review_tree.setHeaderLabels(["", "", "", ""])
        self.recap_review_tree.setRootIsDecorated(True)
        self.recap_review_tree.setItemsExpandable(True)
        self.recap_review_tree.setExpandsOnDoubleClick(False)
        self.recap_review_tree.setUniformRowHeights(True)
        self.recap_review_tree.setAlternatingRowColors(False)
        self.recap_review_tree.setIndentation(22)
        self.recap_review_tree.setItemDelegate(RecapReviewItemDelegate(self.recap_review_tree))
        self.recap_review_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.recap_review_tree.setAutoScroll(False)
        self.recap_review_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.recap_review_tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.recap_review_tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.recap_review_tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.recap_review_tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.recap_review_tree.setAnimated(False)
        header = self.recap_review_tree.header()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.recap_review_tree.setColumnWidth(0, 176)
        self.recap_review_tree.setColumnWidth(1, 118)
        self.recap_review_tree.setColumnWidth(2, 118)
        self._recap_review_stretch = add_vertically_stretchable(
            review,
            self.recap_review_tree,
            default_height=420,
            min_height=220,
            max_height=1600,
        )
        # Alias for older callers that still look for recap_review_table.
        self.recap_review_table = self.recap_review_tree
        self.recap_review_panel.setVisible(False)
        layout.addWidget(self.recap_review_panel)
