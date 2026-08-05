"""Settings page — Phase 3 split from components.py."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.components import (
    ClickableLabel,
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
    SettingDetailPopup,
    _fallback_text,
)
from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import PageScaffold, VSCard
from ui.widgets.settings.form import SettingsFormMixin
from ui.widgets.styles import repolish_widget


class SettingsPage(QWidget, SettingsFormMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        shell_layout = self.scaffold.content_layout

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        shell_layout.addWidget(self.scroll, 1)

        self.scroll_content = QWidget()
        self.scroll.setWidget(self.scroll_content)
        content_layout = QVBoxLayout(self.scroll_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self.general_title = QLabel()
        self.general_title.setObjectName("CardTitle")

        self.runtime_status_title = QLabel()
        self.runtime_status_title.setObjectName("CardTitle")
        self.runtime_status_header = QWidget()
        runtime_status_header_layout = QHBoxLayout(self.runtime_status_header)
        runtime_status_header_layout.setContentsMargins(0, 0, 0, 0)
        runtime_status_header_layout.setSpacing(8)
        self.runtime_status_backend = QLabel()
        self.runtime_status_backend.setObjectName("StatusHint")
        self.runtime_status_backend.setWordWrap(True)
        self.runtime_status_backend.setTextFormat(Qt.RichText)
        self.runtime_status_backend.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.runtime_status_backend.setOpenExternalLinks(True)
        self.btn_show_runtime_diagnostics = QPushButton()
        self.btn_show_runtime_diagnostics.setObjectName("AccentGhostButton")
        self.btn_show_runtime_diagnostics.setMinimumHeight(30)
        self.btn_show_runtime_diagnostics.setMinimumWidth(150)
        self.runtime_status_ffmpeg = QLabel()
        self.runtime_status_ffmpeg.setObjectName("StatusHint")
        self.runtime_status_ffmpeg.setWordWrap(True)
        self.runtime_status_data = QLabel()
        self.runtime_status_data.setObjectName("StatusHint")
        self.runtime_status_data.setWordWrap(True)
        runtime_status_header_layout.addWidget(self.runtime_status_title, 0)
        runtime_status_header_layout.addStretch(1)
        runtime_status_header_layout.addWidget(self.btn_show_runtime_diagnostics, 0)

        self.search_telemetry_title = QLabel()
        self.search_telemetry_title.setObjectName("CardTitle")
        self.btn_search_telemetry_collapse = QToolButton()
        self.btn_search_telemetry_collapse.setObjectName("VideoScopeCollapseBtn")
        self.btn_search_telemetry_collapse.setAutoRaise(True)
        self.btn_search_telemetry_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.search_telemetry_header = QWidget()
        search_telemetry_header_layout = QHBoxLayout(self.search_telemetry_header)
        search_telemetry_header_layout.setContentsMargins(0, 0, 0, 0)
        search_telemetry_header_layout.setSpacing(8)
        self.btn_refresh_search_telemetry = QPushButton()
        self.btn_refresh_search_telemetry.setObjectName("AccentGhostButton")
        self.btn_refresh_search_telemetry.setMinimumHeight(30)
        self.btn_refresh_search_telemetry.setMinimumWidth(120)
        self.search_telemetry_body = QLabel()
        self.search_telemetry_body.setObjectName("StatusHint")
        self.search_telemetry_body.setWordWrap(True)
        self.search_telemetry_body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.search_telemetry_hint = QLabel()
        self.search_telemetry_hint.setObjectName("StatusHint")
        self.search_telemetry_hint.setWordWrap(True)
        self.search_telemetry_file = QLabel()
        self.search_telemetry_file.setObjectName("StatusHint")
        self.search_telemetry_file.setWordWrap(True)
        self.search_telemetry_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.search_telemetry_body_widget = QWidget()
        search_telemetry_body_layout = QVBoxLayout(self.search_telemetry_body_widget)
        search_telemetry_body_layout.setContentsMargins(0, 0, 0, 0)
        search_telemetry_body_layout.setSpacing(8)
        search_telemetry_body_layout.addWidget(self.search_telemetry_body)
        search_telemetry_body_layout.addWidget(self.search_telemetry_hint)
        search_telemetry_body_layout.addWidget(self.search_telemetry_file)
        search_telemetry_header_layout.addWidget(self.btn_search_telemetry_collapse, 0)
        search_telemetry_header_layout.addWidget(self.search_telemetry_title, 0)
        search_telemetry_header_layout.addStretch(1)
        search_telemetry_header_layout.addWidget(self.btn_refresh_search_telemetry, 0)
        self.btn_search_telemetry_collapse.clicked.connect(self._toggle_search_telemetry_panel)
        self._search_telemetry_expanded = False
        self._set_search_telemetry_expanded(False)

        self.input_fps = NoWheelDoubleSpinBox()
        self.input_fps.setRange(0.01, 24.0)
        self.input_fps.setDecimals(2)
        self.input_fps.setSingleStep(0.1)
        self.input_sampling_fps_mode = NoWheelComboBox()
        self.input_sampling_fps_rules = QLineEdit(self)
        self.input_top_k = NoWheelSpinBox()
        self.input_top_k.setRange(1, 200)
        self.input_frame_neighbor_rerank_enabled = NoWheelComboBox()
        self.input_frame_neighbor_rerank_top_n = NoWheelSpinBox()
        self.input_frame_neighbor_rerank_top_n.setRange(1, 100)
        self.input_frame_neighbor_rerank_window = NoWheelSpinBox()
        self.input_frame_neighbor_rerank_window.setRange(1, 12)
        self.input_image_pixel_rerank_top_n = NoWheelSpinBox()
        self.input_image_pixel_rerank_top_n.setRange(1, 100)
        self.input_image_pixel_rerank_probe_mode = NoWheelComboBox()
        self.input_image_pixel_rerank_time_window_sec = NoWheelDoubleSpinBox()
        self.input_image_pixel_rerank_time_window_sec.setRange(0.5, 10.0)
        self.input_image_pixel_rerank_time_window_sec.setSingleStep(0.5)
        self.input_image_pixel_rerank_time_window_sec.setDecimals(1)
        self.input_image_pixel_rerank_probe_step_sec = NoWheelDoubleSpinBox()
        self.input_image_pixel_rerank_probe_step_sec.setRange(0.25, 0.5)
        self.input_image_pixel_rerank_probe_step_sec.setSingleStep(0.05)
        self.input_image_pixel_rerank_probe_step_sec.setDecimals(2)
        self.input_image_search_fetch_multiplier = NoWheelSpinBox()
        self.input_image_search_fetch_multiplier.setRange(1, 8)
        self.input_preview_seconds = NoWheelSpinBox()
        self.input_preview_seconds.setRange(2, 20)
        self.input_thumb_width = NoWheelSpinBox()
        self.input_thumb_width.setRange(80, 480)
        self.input_thumb_height = NoWheelSpinBox()
        self.input_thumb_height.setRange(45, 320)
        self.input_embedding_batch_size = NoWheelSpinBox()
        self.input_embedding_batch_size.setRange(1, 64)
        self.input_chunk_policy = NoWheelComboBox()
        self.input_similarity_threshold = NoWheelDoubleSpinBox()
        self.input_similarity_threshold.setRange(0.1, 1.0)
        self.input_similarity_threshold.setSingleStep(0.01)
        self.input_similarity_threshold.setDecimals(2)
        self.input_min_chunk_size = NoWheelSpinBox()
        self.input_min_chunk_size.setRange(1, 50)
        self.input_min_chunk_duration = NoWheelDoubleSpinBox()
        self.input_min_chunk_duration.setRange(0.0, 30.0)
        self.input_min_chunk_duration.setSingleStep(0.5)
        self.input_min_chunk_duration.setDecimals(1)
        self.input_prefer_gpu = NoWheelComboBox()
        self.input_experimental_hw_decode = NoWheelComboBox()
        self.input_gpu_probe_unknown_keep_gpu = NoWheelComboBox()
        self.input_auto_cleanup_missing_files = NoWheelComboBox()
        self.input_close_window_action = NoWheelComboBox()
        self.input_agent_api_enabled = NoWheelComboBox()
        self.lbl_agent_api_status = QLabel()
        self.lbl_agent_api_status.setObjectName("StatusHint")
        self.lbl_agent_api_status.setWordWrap(True)
        self.btn_copy_agent_api_url = QPushButton()
        self.btn_copy_agent_api_url.setObjectName("AccentGhostButton")
        self.btn_copy_agent_api_url.setMinimumHeight(34)
        self.btn_copy_agent_starter = QPushButton()
        self.btn_copy_agent_starter.setObjectName("SuccessGhostButton")
        self.btn_copy_agent_starter.setMinimumHeight(34)
        self.input_agent_api_bundle = QWidget()
        agent_api_bundle_layout = QHBoxLayout(self.input_agent_api_bundle)
        agent_api_bundle_layout.setContentsMargins(0, 0, 0, 0)
        agent_api_bundle_layout.setSpacing(8)
        agent_api_bundle_layout.addWidget(self.input_agent_api_enabled, 0)
        agent_api_bundle_layout.addWidget(self.lbl_agent_api_status, 1)
        agent_api_buttons = QWidget()
        agent_api_buttons_layout = QHBoxLayout(agent_api_buttons)
        agent_api_buttons_layout.setContentsMargins(0, 0, 0, 0)
        agent_api_buttons_layout.setSpacing(6)
        agent_api_buttons_layout.addWidget(self.btn_copy_agent_api_url, 0)
        agent_api_buttons_layout.addWidget(self.btn_copy_agent_starter, 0)
        agent_api_bundle_layout.addWidget(agent_api_buttons, 0)
        self.input_team_mode = NoWheelComboBox()
        self.input_team_server_url = QLineEdit()
        self.input_team_server_url.setPlaceholderText("http://192.168.1.10:8765")
        self.lbl_team_status = QLabel()
        self.lbl_team_status.setObjectName("StatusHint")
        self.lbl_team_status.setWordWrap(True)
        self.btn_team_apply = QPushButton()
        self.btn_team_apply.setObjectName("AccentGhostButton")
        self.btn_team_apply.setMinimumHeight(34)
        self.input_team_bundle = QWidget()
        team_bundle_layout = QVBoxLayout(self.input_team_bundle)
        team_bundle_layout.setContentsMargins(0, 0, 0, 0)
        team_bundle_layout.setSpacing(6)
        team_row = QWidget()
        team_row_layout = QHBoxLayout(team_row)
        team_row_layout.setContentsMargins(0, 0, 0, 0)
        team_row_layout.setSpacing(8)
        team_row_layout.addWidget(self.input_team_mode, 0)
        team_row_layout.addWidget(self.input_team_server_url, 1)
        team_row_layout.addWidget(self.btn_team_apply, 0)
        team_bundle_layout.addWidget(team_row)
        team_bundle_layout.addWidget(self.lbl_team_status)
        self.input_export_video_silent = NoWheelComboBox()
        self.input_active_model_profile = NoWheelComboBox()
        self.btn_download_runtime_resources = QPushButton()
        self.btn_remove_model_profile = QPushButton()
        self.input_data_root = QLineEdit()
        self.btn_browse_data_root = QPushButton()
        self.input_ffmpeg_path = QLineEdit()
        self.btn_browse_ffmpeg_path = QPushButton()
        self.input_model_dir = QLineEdit()
        self.btn_browse_model_dir = QPushButton()
        self.btn_migrate_model_dir = QPushButton()
        self.section_search_title = QLabel()
        self.section_fast_image_search_title = QLabel()
        self.hint_fast_image_search_section = QLabel()
        self.section_precise_search_title = QLabel()
        self.hint_precise_search_section = QLabel()
        self.section_preview_title = QLabel()
        self.section_indexing_title = QLabel()
        self.section_model_gpu_title = QLabel()
        self.section_paths_title = QLabel()
        self.label_fps = ClickableLabel()
        self.label_top_k = ClickableLabel()
        self.label_frame_neighbor_rerank_enabled = ClickableLabel()
        self.label_frame_neighbor_rerank_top_n = ClickableLabel()
        self.label_frame_neighbor_rerank_window = ClickableLabel()
        self.label_image_pixel_rerank_top_n = ClickableLabel()
        self.label_image_pixel_rerank_probe_mode = ClickableLabel()
        self.label_image_pixel_rerank_time_window_sec = ClickableLabel()
        self.label_image_pixel_rerank_probe_step_sec = ClickableLabel()
        self.label_image_search_fetch_multiplier = ClickableLabel()
        self.label_preview_seconds = ClickableLabel()
        self.label_thumb_width = ClickableLabel()
        self.label_thumb_height = ClickableLabel()
        self.label_export_video_silent = ClickableLabel()
        self.label_embedding_batch_size = ClickableLabel()
        self.label_chunk_policy = ClickableLabel()
        self.label_similarity_threshold = ClickableLabel()
        self.label_min_chunk_size = ClickableLabel()
        self.label_min_chunk_duration = ClickableLabel()
        self.label_prefer_gpu = ClickableLabel()
        self.label_experimental_hw_decode = ClickableLabel()
        self.label_gpu_probe_unknown_keep_gpu = ClickableLabel()
        self.label_auto_cleanup_missing_files = ClickableLabel()
        self.label_close_window_action = ClickableLabel()
        self.label_agent_api_enabled = ClickableLabel()
        self.label_team_mode = ClickableLabel()
        self.label_active_model_profile = ClickableLabel()
        self.label_data_root = ClickableLabel()
        self.label_ffmpeg_path = ClickableLabel()
        self.label_model_dir = ClickableLabel()
        self.hint_fps = QLabel()
        self.hint_sampling_fps_mode = QLabel()
        self.hint_sampling_fps_rules = QLabel()
        self.hint_sampling_fps_preview = QLabel()
        self.sampling_rules_summary = QLabel()
        self.btn_edit_sampling_rules = QPushButton()
        self.hint_top_k = QLabel()
        self.hint_frame_neighbor_rerank_enabled = QLabel()
        self.hint_frame_neighbor_rerank_top_n = QLabel()
        self.hint_frame_neighbor_rerank_window = QLabel()
        self.hint_image_pixel_rerank_top_n = QLabel()
        self.hint_image_pixel_rerank_probe_mode = QLabel()
        self.hint_image_pixel_rerank_time_window_sec = QLabel()
        self.hint_image_pixel_rerank_probe_step_sec = QLabel()
        self.hint_image_search_fetch_multiplier = QLabel()
        self.hint_preview_seconds = QLabel()
        self.hint_thumb_width = QLabel()
        self.hint_thumb_height = QLabel()
        self.hint_export_video_silent = QLabel()
        self.hint_embedding_batch_size = QLabel()
        self.hint_indexing_note = QLabel()
        self.hint_chunk_policy = QLabel()
        self.btn_toggle_chunk_advanced = QPushButton()
        self.btn_toggle_chunk_advanced.setObjectName("LinkUtilityButton")
        self.btn_toggle_chunk_advanced.setFlat(True)
        self.btn_toggle_chunk_advanced.setCursor(Qt.PointingHandCursor)
        self.input_chunk_policy_bundle = QWidget()
        self.chunk_advanced_body = QFrame()
        self.chunk_advanced_body.setObjectName("SubPanelCard")
        self._chunk_advanced_expanded = False
        self.hint_similarity_threshold = QLabel()
        self.hint_min_chunk_size = QLabel()
        self.hint_min_chunk_duration = QLabel()
        self.hint_prefer_gpu = QLabel()
        self.hint_experimental_hw_decode = QLabel()
        self.hint_gpu_probe_unknown_keep_gpu = QLabel()
        self.hint_auto_cleanup_missing_files = QLabel()
        self.hint_close_window_action = QLabel()
        self.hint_agent_api_enabled = QLabel()
        self.hint_team_mode = QLabel()
        self.hint_active_model_profile = QLabel()
        self.hint_data_root = QLabel()
        self.hint_ffmpeg_path = QLabel()
        self.hint_ffmpeg_active = QLabel()
        self.hint_inference_backend = QLabel()
        self.hint_gpu_runtime = QLabel()
        self.hint_model_dir = QLabel()
        self.sampling_rule_rows = []
        self._setting_detail_bindings = []
        self._active_setting_label = None
        self._chunk_policy_syncing = False
        self.detail_popup = SettingDetailPopup(is_dark=True)
        QApplication.instance().installEventFilter(self.detail_popup)

        self._configure_setting_input(self.input_fps, width=94)
        self._configure_setting_input(self.input_sampling_fps_mode, width=136)
        self._configure_setting_input(self.input_top_k, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(
            self.input_frame_neighbor_rerank_enabled,
            width=COMPONENT_SIZES["settings_input_width"] + 36,
        )
        self._configure_setting_input(
            self.input_frame_neighbor_rerank_top_n,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(
            self.input_frame_neighbor_rerank_window,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(
            self.input_image_pixel_rerank_top_n,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(
            self.input_image_pixel_rerank_probe_mode,
            width=COMPONENT_SIZES["settings_input_width"] + 36,
        )
        self._configure_setting_input(
            self.input_image_pixel_rerank_time_window_sec,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(
            self.input_image_pixel_rerank_probe_step_sec,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(
            self.input_image_search_fetch_multiplier,
            width=COMPONENT_SIZES["settings_input_width"],
        )
        self._configure_setting_input(self.input_preview_seconds, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_thumb_width, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_thumb_height, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_embedding_batch_size, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(
            self.input_chunk_policy,
            width=COMPONENT_SIZES["settings_input_width"] + 36,
        )
        self._configure_setting_input(self.input_similarity_threshold, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_min_chunk_size, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_min_chunk_duration, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_prefer_gpu, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_experimental_hw_decode, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_gpu_probe_unknown_keep_gpu, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_auto_cleanup_missing_files, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_close_window_action, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_agent_api_enabled, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_team_mode, width=COMPONENT_SIZES["settings_input_width"] + 72)
        self._configure_setting_input(self.input_export_video_silent, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_active_model_profile, width=COMPONENT_SIZES["settings_input_width"] + 120)
        self.btn_download_runtime_resources.setObjectName("AccentGhostButton")
        self.btn_download_runtime_resources.setMinimumHeight(34)
        self.btn_remove_model_profile.setObjectName("DangerGhostButton")
        self.btn_remove_model_profile.setMinimumHeight(34)
        self._configure_setting_input(self.input_data_root, width=COMPONENT_SIZES["settings_path_input_width"], expanding=True)
        self._configure_setting_input(self.input_ffmpeg_path, width=COMPONENT_SIZES["settings_path_input_width"], expanding=True)
        self._configure_setting_input(self.input_model_dir, width=COMPONENT_SIZES["settings_path_input_width"], expanding=True)
        self.btn_browse_data_root.setObjectName("AccentGhostButton")
        self.btn_browse_data_root.setMinimumHeight(34)
        self.btn_browse_ffmpeg_path.setObjectName("AccentGhostButton")
        self.btn_browse_ffmpeg_path.setMinimumHeight(34)
        self.btn_browse_model_dir.setObjectName("SuccessGhostButton")
        self.btn_browse_model_dir.setMinimumHeight(34)
        self.btn_migrate_model_dir.setObjectName("AccentGhostButton")
        self.btn_migrate_model_dir.setMinimumHeight(34)

        self.input_data_root_bundle = QWidget()
        input_data_root_bundle_layout = QHBoxLayout(self.input_data_root_bundle)
        input_data_root_bundle_layout.setContentsMargins(0, 0, 0, 0)
        input_data_root_bundle_layout.setSpacing(8)
        input_data_root_bundle_layout.addWidget(self.input_data_root, 1)
        input_data_root_bundle_layout.addWidget(self.btn_browse_data_root, 0)

        self.input_ffmpeg_path_bundle = QWidget()
        input_ffmpeg_path_bundle_layout = QHBoxLayout(self.input_ffmpeg_path_bundle)
        input_ffmpeg_path_bundle_layout.setContentsMargins(0, 0, 0, 0)
        input_ffmpeg_path_bundle_layout.setSpacing(8)
        input_ffmpeg_path_bundle_layout.addWidget(self.input_ffmpeg_path, 1)
        input_ffmpeg_path_bundle_layout.addWidget(self.btn_browse_ffmpeg_path, 0)

        self.input_model_dir_bundle = QWidget()
        input_model_dir_bundle_layout = QHBoxLayout(self.input_model_dir_bundle)
        input_model_dir_bundle_layout.setContentsMargins(0, 0, 0, 0)
        input_model_dir_bundle_layout.setSpacing(8)
        self.model_dir_buttons_row = QWidget()
        model_dir_buttons_layout = QHBoxLayout(self.model_dir_buttons_row)
        model_dir_buttons_layout.setContentsMargins(0, 0, 0, 0)
        model_dir_buttons_layout.setSpacing(8)
        model_dir_buttons_layout.addWidget(self.btn_browse_model_dir, 0)
        model_dir_buttons_layout.addWidget(self.btn_migrate_model_dir, 0)
        input_model_dir_bundle_layout.addWidget(self.input_model_dir, 1)
        input_model_dir_bundle_layout.addWidget(self.model_dir_buttons_row, 0)

        self.input_active_model_profile_bundle = QWidget()
        active_model_profile_bundle_layout = QHBoxLayout(self.input_active_model_profile_bundle)
        active_model_profile_bundle_layout.setContentsMargins(0, 0, 0, 0)
        active_model_profile_bundle_layout.setSpacing(8)
        active_model_profile_bundle_layout.addWidget(self.input_active_model_profile, 1)
        active_model_profile_bundle_layout.addWidget(self.btn_download_runtime_resources, 0)
        active_model_profile_bundle_layout.addWidget(self.btn_remove_model_profile, 0)

        for hint_label in (
            self.hint_sampling_fps_mode,
            self.hint_sampling_fps_rules,
            self.hint_sampling_fps_preview,
        ):
            hint_label.setObjectName("StatusHint")
            hint_label.setWordWrap(True)
        self.sampling_rules_summary.setObjectName("StatusHint")
        self.sampling_rules_summary.setWordWrap(False)

        self.input_sampling_bundle = QWidget()
        self.input_sampling_bundle.setObjectName("SamplingBundle")
        sampling_bundle_layout = QHBoxLayout(self.input_sampling_bundle)
        sampling_bundle_layout.setContentsMargins(0, 0, 0, 0)
        sampling_bundle_layout.setSpacing(8)
        sampling_bundle_layout.addWidget(self.input_sampling_fps_mode, 0)
        sampling_bundle_layout.addWidget(self.input_fps, 0)
        self.btn_edit_sampling_rules.setObjectName("AccentGhostButton")
        sampling_bundle_layout.addWidget(self.btn_edit_sampling_rules, 0)
        self.sampling_rules_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sampling_bundle_layout.addWidget(self.sampling_rules_summary, 1)
        self.input_sampling_fps_rules.hide()

        self.input_chunk_policy_bundle.setObjectName("ChunkPolicyBundle")
        chunk_policy_bundle_layout = QHBoxLayout(self.input_chunk_policy_bundle)
        chunk_policy_bundle_layout.setContentsMargins(0, 0, 0, 0)
        chunk_policy_bundle_layout.setSpacing(10)
        chunk_policy_bundle_layout.addWidget(self.input_chunk_policy, 1)
        chunk_policy_bundle_layout.addWidget(self.btn_toggle_chunk_advanced, 0, Qt.AlignRight | Qt.AlignVCenter)

        self.section_search_card, self.section_search_form = self._create_settings_section(self.section_search_title)
        self.section_fast_image_search_card, self.section_fast_image_search_form = self._create_settings_section(
            self.section_fast_image_search_title
        )
        self.section_precise_search_card, self.section_precise_search_form = self._create_settings_section(
            self.section_precise_search_title
        )
        self.section_preview_card, self.section_preview_form = self._create_settings_section(self.section_preview_title)
        self.section_indexing_card, self.section_indexing_form = self._create_settings_section(self.section_indexing_title)
        self.chunk_advanced_form = QGridLayout(self.chunk_advanced_body)
        self.chunk_advanced_form.setContentsMargins(12, 8, 12, 10)
        self.chunk_advanced_form.setHorizontalSpacing(16)
        self.chunk_advanced_form.setVerticalSpacing(0)
        self.chunk_advanced_form.setColumnMinimumWidth(0, 260)
        self.chunk_advanced_form.setColumnStretch(0, 0)
        self.chunk_advanced_form.setColumnStretch(1, 1)
        self.section_model_gpu_card, self.section_model_gpu_form = self._create_settings_section(self.section_model_gpu_title)
        self.section_paths_card, self.section_paths_form = self._create_settings_section(self.section_paths_title)
        self.section_general_form_host = QWidget()
        self.section_general_form = QGridLayout(self.section_general_form_host)
        self.section_general_form.setContentsMargins(0, 0, 0, 0)
        self.section_general_form.setHorizontalSpacing(16)
        self.section_general_form.setVerticalSpacing(0)
        self.section_general_form.setColumnMinimumWidth(0, 260)
        self.section_general_form.setColumnStretch(0, 0)
        self.section_general_form.setColumnStretch(1, 1)
        self._add_setting_row(
            self.section_search_form,
            0,
            self.label_top_k,
            self.input_top_k,
            self.hint_top_k,
        )
        self._add_section_note(self.section_fast_image_search_form, 0, self.hint_fast_image_search_section)
        self._add_setting_row(
            self.section_fast_image_search_form,
            1,
            self.label_frame_neighbor_rerank_enabled,
            self.input_frame_neighbor_rerank_enabled,
            self.hint_frame_neighbor_rerank_enabled,
        )
        self.frame_neighbor_rerank_top_n_row = self._add_setting_row(
            self.section_fast_image_search_form,
            2,
            self.label_frame_neighbor_rerank_top_n,
            self.input_frame_neighbor_rerank_top_n,
            self.hint_frame_neighbor_rerank_top_n,
        )
        self.frame_neighbor_rerank_window_row = self._add_setting_row(
            self.section_fast_image_search_form,
            3,
            self.label_frame_neighbor_rerank_window,
            self.input_frame_neighbor_rerank_window,
            self.hint_frame_neighbor_rerank_window,
        )
        self._add_section_note(self.section_precise_search_form, 0, self.hint_precise_search_section)
        self._add_setting_row(
            self.section_precise_search_form,
            1,
            self.label_image_search_fetch_multiplier,
            self.input_image_search_fetch_multiplier,
            self.hint_image_search_fetch_multiplier,
        )
        self._add_setting_row(
            self.section_precise_search_form,
            2,
            self.label_image_pixel_rerank_top_n,
            self.input_image_pixel_rerank_top_n,
            self.hint_image_pixel_rerank_top_n,
        )
        self._add_setting_row(
            self.section_precise_search_form,
            3,
            self.label_image_pixel_rerank_probe_mode,
            self.input_image_pixel_rerank_probe_mode,
            self.hint_image_pixel_rerank_probe_mode,
        )
        self.image_pixel_rerank_time_window_row = self._add_setting_row(
            self.section_precise_search_form,
            4,
            self.label_image_pixel_rerank_time_window_sec,
            self.input_image_pixel_rerank_time_window_sec,
            self.hint_image_pixel_rerank_time_window_sec,
        )
        self.image_pixel_rerank_probe_step_row = self._add_setting_row(
            self.section_precise_search_form,
            5,
            self.label_image_pixel_rerank_probe_step_sec,
            self.input_image_pixel_rerank_probe_step_sec,
            self.hint_image_pixel_rerank_probe_step_sec,
        )

        self._add_setting_row(self.section_preview_form, 0, self.label_preview_seconds, self.input_preview_seconds, self.hint_preview_seconds)
        self._add_setting_row(self.section_preview_form, 1, self.label_thumb_width, self.input_thumb_width, self.hint_thumb_width)
        self._add_setting_row(self.section_preview_form, 2, self.label_thumb_height, self.input_thumb_height, self.hint_thumb_height)
        self._add_setting_row(
            self.section_preview_form,
            3,
            self.label_export_video_silent,
            self.input_export_video_silent,
            self.hint_export_video_silent,
        )

        self._add_setting_row(
            self.section_indexing_form,
            0,
            self.label_fps,
            self.input_sampling_bundle,
            self.hint_fps,
            show_help=False,
        )
        self._add_setting_row(
            self.section_indexing_form,
            1,
            self.label_embedding_batch_size,
            self.input_embedding_batch_size,
            self.hint_embedding_batch_size,
        )
        self._add_section_note(self.section_indexing_form, 2, self.hint_indexing_note)
        self._configure_setting_input(
            self.input_chunk_policy,
            width=COMPONENT_SIZES["settings_input_width"] + 36,
        )
        self._add_setting_row(
            self.section_indexing_form,
            3,
            self.label_chunk_policy,
            self.input_chunk_policy_bundle,
            self.hint_chunk_policy,
        )
        self.section_indexing_form.addWidget(self.chunk_advanced_body, 4, 0, 1, 2)
        self._add_setting_row(
            self.chunk_advanced_form,
            0,
            self.label_similarity_threshold,
            self.input_similarity_threshold,
            self.hint_similarity_threshold,
        )
        self._add_setting_row(
            self.chunk_advanced_form,
            1,
            self.label_min_chunk_size,
            self.input_min_chunk_size,
            self.hint_min_chunk_size,
        )
        self._add_setting_row(
            self.chunk_advanced_form,
            2,
            self.label_min_chunk_duration,
            self.input_min_chunk_duration,
            self.hint_min_chunk_duration,
        )
        self._add_setting_row(
            self.section_general_form,
            0,
            self.label_auto_cleanup_missing_files,
            self.input_auto_cleanup_missing_files,
            self.hint_auto_cleanup_missing_files,
        )
        self._add_setting_row(
            self.section_general_form,
            1,
            self.label_close_window_action,
            self.input_close_window_action,
            self.hint_close_window_action,
        )
        self._add_setting_row(
            self.section_general_form,
            2,
            self.label_agent_api_enabled,
            self.input_agent_api_bundle,
            self.hint_agent_api_enabled,
        )
        self._add_setting_row(
            self.section_general_form,
            3,
            self.label_team_mode,
            self.input_team_bundle,
            self.hint_team_mode,
        )
        self._add_setting_row(
            self.section_model_gpu_form,
            0,
            self.label_prefer_gpu,
            self.input_prefer_gpu,
            self.hint_prefer_gpu,
        )
        self._add_setting_row(
            self.section_model_gpu_form,
            1,
            self.label_experimental_hw_decode,
            self.input_experimental_hw_decode,
            self.hint_experimental_hw_decode,
        )
        self._add_setting_row(
            self.section_model_gpu_form,
            2,
            self.label_gpu_probe_unknown_keep_gpu,
            self.input_gpu_probe_unknown_keep_gpu,
            self.hint_gpu_probe_unknown_keep_gpu,
        )
        self._add_setting_row(
            self.section_model_gpu_form,
            3,
            self.label_active_model_profile,
            self.input_active_model_profile_bundle,
            self.hint_active_model_profile,
        )
        self._add_setting_row(
            self.section_paths_form,
            0,
            self.label_data_root,
            self.input_data_root_bundle,
            self.hint_data_root,
        )
        self._add_setting_row(
            self.section_paths_form,
            1,
            self.label_ffmpeg_path,
            self.input_ffmpeg_path_bundle,
            self.hint_ffmpeg_path,
        )
        self._add_setting_row(
            self.section_paths_form,
            2,
            self.label_model_dir,
            self.input_model_dir_bundle,
            self.hint_model_dir,
        )

        self.card_general = VSCard()
        self.card_general.content_layout.addWidget(self.general_title)
        self.card_general.content_layout.addWidget(self.section_general_form_host)

        self.card_search_preview = VSCard()
        search_preview_host = QWidget()
        search_preview_layout = QVBoxLayout(search_preview_host)
        search_preview_layout.setContentsMargins(0, 0, 0, 0)
        search_preview_layout.setSpacing(12)
        search_preview_layout.addWidget(self.section_search_card)
        search_preview_layout.addWidget(self.section_fast_image_search_card)
        search_preview_layout.addWidget(self.section_precise_search_card)
        search_preview_layout.addWidget(self.section_preview_card)
        self.card_search_preview.content_layout.addWidget(search_preview_host)

        self.card_indexing = VSCard()
        indexing_host = QWidget()
        indexing_layout = QVBoxLayout(indexing_host)
        indexing_layout.setContentsMargins(0, 0, 0, 0)
        indexing_layout.setSpacing(12)
        indexing_layout.addWidget(self.section_indexing_card)
        self.card_indexing.content_layout.addWidget(indexing_host)

        self.card_model_gpu = VSCard()
        model_gpu_host = QWidget()
        model_gpu_layout = QVBoxLayout(model_gpu_host)
        model_gpu_layout.setContentsMargins(0, 0, 0, 0)
        model_gpu_layout.setSpacing(12)
        model_gpu_layout.addWidget(self.section_model_gpu_card)
        self.card_model_gpu.content_layout.addWidget(model_gpu_host)

        self.card_paths = VSCard()
        self.card_paths.content_layout.addWidget(self.section_paths_card)

        self.card_runtime_status = VSCard()
        self.card_runtime_status.content_layout.addWidget(self.runtime_status_header)
        self.card_runtime_status.content_layout.addWidget(self.runtime_status_backend)
        self.card_runtime_status.content_layout.addWidget(self.runtime_status_ffmpeg)
        self.card_runtime_status.content_layout.addWidget(self.runtime_status_data)

        self.card_search_telemetry = VSCard()
        self.card_search_telemetry.content_layout.addWidget(self.search_telemetry_header)
        self.card_search_telemetry.content_layout.addWidget(self.search_telemetry_body_widget)

        for card in (
            self.card_runtime_status,
            self.card_search_telemetry,
            self.card_general,
            self.card_search_preview,
            self.card_indexing,
            self.card_model_gpu,
            self.card_paths,
        ):
            content_layout.addWidget(card)
        content_layout.addStretch()

        self.action_card = VSCard(margins=(18, 14, 18, 14))
        action_card_layout = self.action_card.content_layout

        action_primary_row = QHBoxLayout()
        action_primary_row.setSpacing(8)
        self.btn_save = QPushButton()
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_reset = QPushButton()
        self.btn_reset.setObjectName("GhostButton")
        action_primary_row.addWidget(self.btn_save)
        action_primary_row.addWidget(self.btn_reset)
        action_primary_row.addStretch()
        action_card_layout.addLayout(action_primary_row)

        action_cleanup_row = QHBoxLayout()
        action_cleanup_row.setSpacing(8)
        self.btn_cleanup_old_data_root = QPushButton()
        self.btn_cleanup_old_data_root.setObjectName("DangerGhostButton")
        self.btn_cleanup_old_data_root.hide()
        self.btn_cleanup_old_model_dir = QPushButton()
        self.btn_cleanup_old_model_dir.setObjectName("DangerGhostButton")
        self.btn_cleanup_old_model_dir.hide()
        action_cleanup_row.addWidget(self.btn_cleanup_old_data_root)
        action_cleanup_row.addWidget(self.btn_cleanup_old_model_dir)
        action_cleanup_row.addStretch()
        action_card_layout.addLayout(action_cleanup_row)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        action_card_layout.addWidget(self.lbl_status)
        shell_layout.addWidget(self.action_card, 0)
        self.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_changed)
        self.input_frame_neighbor_rerank_enabled.currentIndexChanged.connect(
            self._handle_frame_neighbor_rerank_enabled_changed
        )
        self.input_image_pixel_rerank_probe_mode.currentIndexChanged.connect(
            self._handle_image_pixel_probe_mode_changed
        )
        self._update_sampling_mode_visibility()
        self._update_frame_neighbor_rerank_visibility()
        self._update_image_pixel_probe_mode_visibility()
        self.btn_toggle_chunk_advanced.clicked.connect(self._toggle_chunk_advanced_panel)
        self.set_chunk_advanced_expanded(False)

    def _handle_sampling_mode_changed(self, *_args):
        self._update_sampling_mode_visibility()

    def _handle_frame_neighbor_rerank_enabled_changed(self, *_args):
        self._update_frame_neighbor_rerank_visibility()

    def _update_sampling_mode_visibility(self):
        is_dynamic = self.get_sampling_fps_mode() == "dynamic"
        self.input_fps.setVisible(not is_dynamic)
        self.btn_edit_sampling_rules.setVisible(is_dynamic)
        self.sampling_rules_summary.setVisible(is_dynamic)
        self.hint_fps.setVisible(False)
        self.hint_sampling_fps_mode.setVisible(False)
        self.hint_sampling_fps_rules.setVisible(False)
        self.hint_sampling_fps_preview.setVisible(False)

    def _handle_image_pixel_probe_mode_changed(self, *_args):
        self._update_image_pixel_probe_mode_visibility()

    def _update_image_pixel_probe_mode_visibility(self):
        is_fixed = str(self.input_image_pixel_rerank_probe_mode.currentData() or "index") == "fixed"
        if hasattr(self, "image_pixel_rerank_time_window_row"):
            self.image_pixel_rerank_time_window_row.setVisible(is_fixed)
        if hasattr(self, "image_pixel_rerank_probe_step_row"):
            self.image_pixel_rerank_probe_step_row.setVisible(is_fixed)

    def _update_frame_neighbor_rerank_visibility(self):
        enabled = bool(self.input_frame_neighbor_rerank_enabled.currentData())
        if hasattr(self, "frame_neighbor_rerank_top_n_row"):
            self.frame_neighbor_rerank_top_n_row.setVisible(enabled)
        if hasattr(self, "frame_neighbor_rerank_window_row"):
            self.frame_neighbor_rerank_window_row.setVisible(enabled)

    def get_sampling_fps_mode(self):
        return str(self.input_sampling_fps_mode.currentData() or "fixed")

    def set_sampling_fps_mode(self, mode):
        normalized_mode = str(mode or "fixed")
        index = self.input_sampling_fps_mode.findData(normalized_mode)
        self.input_sampling_fps_mode.setCurrentIndex(0 if index < 0 else index)
        self._update_sampling_mode_visibility()

    def set_sampling_fps_rules_text(self, rules_text):
        self.input_sampling_fps_rules.setText(str(rules_text or "").strip())
        self.refresh_sampling_rules_summary()

    def get_sampling_fps_rules_text(self):
        return self.input_sampling_fps_rules.text().strip()

    def set_sampling_rules_error_state(self, has_error):
        self.sampling_rules_summary.setProperty("state", "error" if has_error else "neutral")
        repolish_widget(self.sampling_rules_summary)

    def refresh_sampling_rules_summary(self):
        normalized = self.get_sampling_fps_rules_text()
        if not normalized:
            self.sampling_rules_summary.setText("")
            return
        parts = []
        for chunk in normalized.split(";"):
            item = chunk.strip()
            if item:
                parts.append(item)
        self.sampling_rules_summary.setText(" | ".join(parts[:3]) + (" ..." if len(parts) > 3 else ""))

    def get_sampling_fps_mode(self):
        return str(self.input_sampling_fps_mode.currentData() or "fixed")

    def set_sampling_fps_mode(self, mode):
        normalized_mode = str(mode or "fixed")
        index = self.input_sampling_fps_mode.findData(normalized_mode)
        self.input_sampling_fps_mode.setCurrentIndex(0 if index < 0 else index)
        self._update_sampling_mode_visibility()

    def set_sampling_fps_rules_text(self, rules_text):
        self.input_sampling_fps_rules.setText(str(rules_text or "").strip())
        self.refresh_sampling_rules_summary()

    def get_sampling_fps_rules_text(self):
        return self.input_sampling_fps_rules.text().strip()

    def set_sampling_rules_error_state(self, has_error):
        self.sampling_rules_summary.setProperty("state", "error" if has_error else "neutral")
        repolish_widget(self.sampling_rules_summary)

    def refresh_sampling_rules_summary(self):
        normalized = self.get_sampling_fps_rules_text()
        if not normalized:
            self.sampling_rules_summary.setText("")
            return
        parts = []
        for chunk in normalized.split(";"):
            item = chunk.strip()
            if item:
                parts.append(item)
        self.sampling_rules_summary.setText(" | ".join(parts[:3]) + (" ..." if len(parts) > 3 else ""))

    def is_chunk_policy_syncing(self) -> bool:
        return bool(self._chunk_policy_syncing)

    def set_chunk_advanced_expanded(self, expanded: bool) -> None:
        self._chunk_advanced_expanded = bool(expanded)
        self._refresh_chunk_advanced_visibility()

    def sync_chunk_advanced_visibility(self) -> None:
        if self.get_chunk_policy_id() == "custom":
            self.set_chunk_advanced_expanded(True)
        else:
            self._refresh_chunk_advanced_visibility()

    def _toggle_chunk_advanced_panel(self) -> None:
        self.set_chunk_advanced_expanded(not self._chunk_advanced_expanded)

    def _refresh_chunk_advanced_visibility(self) -> None:
        visible = self._chunk_advanced_expanded
        self.chunk_advanced_body.setVisible(visible)
        texts = getattr(self, "_current_texts", {}) or {}
        if visible:
            self.btn_toggle_chunk_advanced.setText(
                texts.get("setting_chunk_advanced_collapse", "收起")
            )
        else:
            self.btn_toggle_chunk_advanced.setText(
                texts.get("setting_chunk_advanced_expand", "微调")
            )

    def get_chunk_policy_id(self) -> str:
        return str(self.input_chunk_policy.currentData() or "balanced")

    def set_chunk_policy_id(self, policy_id: str) -> None:
        normalized = str(policy_id or "balanced")
        index = self.input_chunk_policy.findData(normalized)
        self.input_chunk_policy.setCurrentIndex(0 if index < 0 else index)

    def apply_chunk_policy_values(self, values: dict) -> None:
        self._chunk_policy_syncing = True
        try:
            if "similarity_threshold" in values:
                self.input_similarity_threshold.setValue(float(values["similarity_threshold"]))
            if "min_chunk_size" in values:
                self.input_min_chunk_size.setValue(int(values["min_chunk_size"]))
            if "min_chunk_duration" in values:
                self.input_min_chunk_duration.setValue(float(values["min_chunk_duration"]))
        finally:
            self._chunk_policy_syncing = False

    def configure_form_labels(self, texts):
        self._current_texts = texts
        self.section_search_title.setText(_fallback_text(texts, "settings_section_search", "检索", "Search"))
        self.section_fast_image_search_title.setText(
            _fallback_text(texts, "settings_section_fast_image_search", "快速图搜", "Fast Image Search")
        )
        self.hint_fast_image_search_section.setText(
            texts.get(
                "settings_section_fast_image_search_note",
                "Applies when Deep search is OFF on the search page.",
            )
        )
        self.section_precise_search_title.setText(
            _fallback_text(texts, "settings_section_precise_search", "图搜精搜", "Precise Image Search")
        )
        self.hint_precise_search_section.setText(
            texts.get(
                "settings_section_precise_search_note",
                "Applies when Deep search is ON. Cropped queries skip pixel rerank.",
            )
        )
        self.section_preview_title.setText(_fallback_text(texts, "settings_section_preview", "预览与缩略图", "Preview & Thumbnails"))
        self.section_indexing_title.setText(
            _fallback_text(texts, "settings_section_indexing", "视频索引", "Video Indexing")
        )
        self.section_model_gpu_title.setText(
            _fallback_text(texts, "settings_section_model_gpu", "模型与 GPU", "Model & GPU")
        )
        self.section_paths_title.setText(
            _fallback_text(texts, "settings_section_paths", "路径管理", "Path Management")
        )
        self.runtime_status_title.setText(_fallback_text(texts, "settings_runtime_status", "当前运行状态", "Current Runtime"))
        self.search_telemetry_title.setText(
            _fallback_text(texts, "search_telemetry_panel_title", "截图搜索诊断", "Screenshot Search Stats")
        )
        self.btn_refresh_search_telemetry.setText(
            texts.get("search_telemetry_panel_refresh", "Refresh stats")
        )
        self.search_telemetry_hint.setText(
            texts.get(
                "search_telemetry_panel_hint",
                "Read-only product metrics from local screenshot searches. Use playback bias first when judging accuracy.",
            )
        )
        self.label_fps.setText(texts["setting_fps"])
        current_mode = self.get_sampling_fps_mode()
        self.input_sampling_fps_mode.blockSignals(True)
        self.input_sampling_fps_mode.clear()
        self.input_sampling_fps_mode.addItem(texts["setting_sampling_fps_mode_fixed"], "fixed")
        self.input_sampling_fps_mode.addItem(texts["setting_sampling_fps_mode_dynamic"], "dynamic")
        restore_index = self.input_sampling_fps_mode.findData(current_mode)
        self.input_sampling_fps_mode.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_sampling_fps_mode.blockSignals(False)
        self.input_sampling_fps_rules.setPlaceholderText(texts["setting_sampling_fps_rules_placeholder"])
        self.btn_edit_sampling_rules.setText(texts["setting_sampling_fps_rules_edit"])
        self.refresh_sampling_rules_summary()
        self.label_top_k.setText(texts["setting_top_k"])
        self.label_frame_neighbor_rerank_enabled.setText(texts["setting_frame_neighbor_rerank_enabled"])
        self.label_frame_neighbor_rerank_top_n.setText(texts["setting_frame_neighbor_rerank_top_n"])
        self.label_frame_neighbor_rerank_window.setText(texts["setting_frame_neighbor_rerank_window"])
        self.label_image_pixel_rerank_top_n.setText(texts["setting_image_pixel_rerank_top_n"])
        self.label_image_pixel_rerank_probe_mode.setText(texts["setting_image_pixel_rerank_probe_mode"])
        self.label_image_pixel_rerank_time_window_sec.setText(texts["setting_image_pixel_rerank_time_window_sec"])
        self.label_image_pixel_rerank_probe_step_sec.setText(texts["setting_image_pixel_rerank_probe_step_sec"])
        self.label_image_search_fetch_multiplier.setText(texts["setting_image_search_fetch_multiplier"])
        self.label_preview_seconds.setText(texts["setting_preview_seconds"])
        self.label_thumb_width.setText(texts["setting_thumb_width"])
        self.label_thumb_height.setText(texts["setting_thumb_height"])
        self.label_export_video_silent.setText(texts["setting_export_video_silent"])
        self.label_embedding_batch_size.setText(texts["setting_embedding_batch_size"])
        self.label_chunk_policy.setText(texts["setting_chunk_policy"])
        self.label_similarity_threshold.setText(texts["setting_similarity_threshold"])
        self.label_min_chunk_size.setText(texts["setting_min_chunk_size"])
        self.label_min_chunk_duration.setText(texts["setting_min_chunk_duration"])
        self.label_prefer_gpu.setText(texts["setting_prefer_gpu"])
        self.label_experimental_hw_decode.setText(texts["setting_experimental_hw_decode"])
        self.label_gpu_probe_unknown_keep_gpu.setText(texts["setting_gpu_probe_unknown_keep_gpu"])
        self.label_auto_cleanup_missing_files.setText(texts["setting_auto_cleanup_missing_files"])
        self.label_close_window_action.setText(texts["setting_close_window_action"])
        self.label_agent_api_enabled.setText(texts["setting_agent_api_enabled"])
        self.label_team_mode.setText(
            texts.get("setting_team_mode", _fallback_text(texts, "setting_team_mode", "团队模式", "Team mode"))
        )
        self.btn_team_apply.setText(
            texts.get("setting_team_apply", _fallback_text(texts, "setting_team_apply", "应用团队模式", "Apply team mode"))
        )
        current_team_mode = self.input_team_mode.currentData()
        self.input_team_mode.blockSignals(True)
        self.input_team_mode.clear()
        self.input_team_mode.addItem(
            texts.get("setting_team_mode_off", "关闭（本机）"), "off"
        )
        self.input_team_mode.addItem(
            texts.get("setting_team_mode_server", "本机作为服务机"), "server"
        )
        self.input_team_mode.addItem(
            texts.get("setting_team_mode_client", "本机作为员工机"), "client"
        )
        restore_team = self.input_team_mode.findData(current_team_mode)
        self.input_team_mode.setCurrentIndex(0 if restore_team < 0 else restore_team)
        self.input_team_mode.blockSignals(False)
        self.btn_copy_agent_api_url.setText(texts["setting_agent_api_copy_url"])
        self.btn_copy_agent_starter.setText(texts["setting_agent_api_copy_starter"])
        current_agent_api_enabled = self.input_agent_api_enabled.currentData()
        self.input_agent_api_enabled.blockSignals(True)
        self.input_agent_api_enabled.clear()
        self.input_agent_api_enabled.addItem(texts["setting_agent_api_enabled_option_off"], False)
        self.input_agent_api_enabled.addItem(texts["setting_agent_api_enabled_option_on"], True)
        restore_index = self.input_agent_api_enabled.findData(current_agent_api_enabled)
        self.input_agent_api_enabled.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_agent_api_enabled.blockSignals(False)
        self.label_active_model_profile.setText(
            _fallback_text(texts, "setting_active_model_profile", "当前模型", "Active Model")
        )
        current_chunk_policy = self.input_chunk_policy.currentData()
        self.input_chunk_policy.blockSignals(True)
        self.input_chunk_policy.clear()
        self.input_chunk_policy.addItem(texts["setting_chunk_policy_balanced"], "balanced")
        self.input_chunk_policy.addItem(texts["setting_chunk_policy_sensitive"], "sensitive")
        self.input_chunk_policy.addItem(texts["setting_chunk_policy_stable"], "stable")
        self.input_chunk_policy.addItem(texts["setting_chunk_policy_custom"], "custom")
        restore_index = self.input_chunk_policy.findData(current_chunk_policy)
        self.input_chunk_policy.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_chunk_policy.blockSignals(False)
        current_prefer_gpu = self.input_prefer_gpu.currentData()
        self.input_prefer_gpu.blockSignals(True)
        self.input_prefer_gpu.clear()
        self.input_prefer_gpu.addItem(texts["setting_prefer_gpu_option_gpu"], True)
        self.input_prefer_gpu.addItem(texts["setting_prefer_gpu_option_cpu"], False)
        restore_index = self.input_prefer_gpu.findData(current_prefer_gpu)
        self.input_prefer_gpu.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_prefer_gpu.blockSignals(False)
        current_experimental_hw_decode = self.input_experimental_hw_decode.currentData()
        self.input_experimental_hw_decode.blockSignals(True)
        self.input_experimental_hw_decode.clear()
        self.input_experimental_hw_decode.addItem(texts["setting_experimental_hw_decode_option_off"], False)
        self.input_experimental_hw_decode.addItem(texts["setting_experimental_hw_decode_option_on"], True)
        restore_hw_index = self.input_experimental_hw_decode.findData(current_experimental_hw_decode)
        self.input_experimental_hw_decode.setCurrentIndex(0 if restore_hw_index < 0 else restore_hw_index)
        self.input_experimental_hw_decode.blockSignals(False)
        current_gpu_probe_unknown_keep_gpu = self.input_gpu_probe_unknown_keep_gpu.currentData()
        self.input_gpu_probe_unknown_keep_gpu.blockSignals(True)
        self.input_gpu_probe_unknown_keep_gpu.clear()
        self.input_gpu_probe_unknown_keep_gpu.addItem(texts["setting_gpu_probe_unknown_keep_gpu_option_off"], False)
        self.input_gpu_probe_unknown_keep_gpu.addItem(texts["setting_gpu_probe_unknown_keep_gpu_option_on"], True)
        restore_index = self.input_gpu_probe_unknown_keep_gpu.findData(current_gpu_probe_unknown_keep_gpu)
        self.input_gpu_probe_unknown_keep_gpu.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_gpu_probe_unknown_keep_gpu.blockSignals(False)
        current_auto_cleanup_missing_files = self.input_auto_cleanup_missing_files.currentData()
        self.input_auto_cleanup_missing_files.blockSignals(True)
        self.input_auto_cleanup_missing_files.clear()
        self.input_auto_cleanup_missing_files.addItem(texts["setting_auto_cleanup_missing_files_option_off"], False)
        self.input_auto_cleanup_missing_files.addItem(texts["setting_auto_cleanup_missing_files_option_on"], True)
        restore_index = self.input_auto_cleanup_missing_files.findData(current_auto_cleanup_missing_files)
        self.input_auto_cleanup_missing_files.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_auto_cleanup_missing_files.blockSignals(False)
        current_close_window_action = self.input_close_window_action.currentData()
        self.input_close_window_action.blockSignals(True)
        self.input_close_window_action.clear()
        self.input_close_window_action.addItem(texts["setting_close_window_action_exit"], "exit")
        self.input_close_window_action.addItem(texts["setting_close_window_action_tray"], "tray")
        restore_index = self.input_close_window_action.findData(current_close_window_action)
        self.input_close_window_action.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_close_window_action.blockSignals(False)
        current_export_video_silent = self.input_export_video_silent.currentData()
        self.input_export_video_silent.blockSignals(True)
        self.input_export_video_silent.clear()
        self.input_export_video_silent.addItem(texts["setting_export_video_silent_option_off"], False)
        self.input_export_video_silent.addItem(texts["setting_export_video_silent_option_on"], True)
        restore_index = self.input_export_video_silent.findData(current_export_video_silent)
        self.input_export_video_silent.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_export_video_silent.blockSignals(False)
        current_neighbor_rerank_enabled = self.input_frame_neighbor_rerank_enabled.currentData()
        self.input_frame_neighbor_rerank_enabled.blockSignals(True)
        self.input_frame_neighbor_rerank_enabled.clear()
        self.input_frame_neighbor_rerank_enabled.addItem(texts["setting_frame_neighbor_rerank_enabled_option_off"], False)
        self.input_frame_neighbor_rerank_enabled.addItem(texts["setting_frame_neighbor_rerank_enabled_option_on"], True)
        restore_index = self.input_frame_neighbor_rerank_enabled.findData(current_neighbor_rerank_enabled)
        self.input_frame_neighbor_rerank_enabled.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_frame_neighbor_rerank_enabled.blockSignals(False)
        current_image_pixel_probe_mode = self.input_image_pixel_rerank_probe_mode.currentData()
        self.input_image_pixel_rerank_probe_mode.blockSignals(True)
        self.input_image_pixel_rerank_probe_mode.clear()
        self.input_image_pixel_rerank_probe_mode.addItem(texts["setting_image_pixel_rerank_probe_mode_index"], "index")
        self.input_image_pixel_rerank_probe_mode.addItem(texts["setting_image_pixel_rerank_probe_mode_fixed"], "fixed")
        restore_index = self.input_image_pixel_rerank_probe_mode.findData(current_image_pixel_probe_mode)
        self.input_image_pixel_rerank_probe_mode.setCurrentIndex(0 if restore_index < 0 else restore_index)
        self.input_image_pixel_rerank_probe_mode.blockSignals(False)
        self.label_data_root.setText(texts["setting_data_root"])
        self.btn_browse_data_root.setText(texts["browse_data_root"])
        self.btn_browse_ffmpeg_path.setText(texts["browse_file"])
        self.btn_browse_model_dir.setText(texts["browse_folder"])
        self.btn_migrate_model_dir.setText(texts["migrate_model_root"])
        self.btn_download_runtime_resources.setText(texts.get("import_runtime_resources", texts["download_models"]))
        self.btn_remove_model_profile.setText(
            texts.get("remove_model_profile", "Remove Current Model")
        )
        self.btn_cleanup_old_data_root.setText(texts["cleanup_old_data_root"])
        self.btn_cleanup_old_model_dir.setText(texts["cleanup_old_model_dir"])
        self.label_ffmpeg_path.setText(texts["setting_ffmpeg_path"])
        self.label_model_dir.setText(texts["setting_model_dir"])
        self.hint_fps.setText(texts["setting_fps_hint"])
        self.hint_sampling_fps_mode.setText(texts["setting_sampling_fps_mode_hint"])
        self.hint_sampling_fps_rules.setText(texts["setting_sampling_fps_rules_hint"])
        self.hint_sampling_fps_preview.setText(texts["setting_sampling_fps_preview"])
        self.hint_top_k.setText(texts["setting_top_k_hint"])
        self.hint_frame_neighbor_rerank_enabled.setText(texts["setting_frame_neighbor_rerank_enabled_hint"])
        self.hint_frame_neighbor_rerank_top_n.setText(texts["setting_frame_neighbor_rerank_top_n_hint"])
        self.hint_frame_neighbor_rerank_window.setText(texts["setting_frame_neighbor_rerank_window_hint"])
        self.hint_image_pixel_rerank_top_n.setText(texts["setting_image_pixel_rerank_top_n_hint"])
        self.hint_image_pixel_rerank_probe_mode.setText(texts["setting_image_pixel_rerank_probe_mode_hint"])
        self.hint_image_pixel_rerank_time_window_sec.setText(texts["setting_image_pixel_rerank_time_window_sec_hint"])
        self.hint_image_pixel_rerank_probe_step_sec.setText(texts["setting_image_pixel_rerank_probe_step_sec_hint"])
        self.hint_image_search_fetch_multiplier.setText(texts["setting_image_search_fetch_multiplier_hint"])
        self.hint_preview_seconds.setText(texts["setting_preview_seconds_hint"])
        self.hint_thumb_width.setText(texts["setting_thumb_width_hint"])
        self.hint_thumb_height.setText(texts["setting_thumb_height_hint"])
        self.hint_export_video_silent.setText(texts["setting_export_video_silent_hint"])
        self.hint_embedding_batch_size.setText(texts["setting_embedding_batch_size_hint"])
        self.hint_indexing_note.setText(texts["setting_indexing_note"])
        self.hint_chunk_policy.setText(texts["setting_chunk_policy_hint"])
        self._refresh_chunk_advanced_visibility()
        self.hint_similarity_threshold.setText(texts["setting_similarity_threshold_hint"])
        self.hint_min_chunk_size.setText(texts["setting_min_chunk_size_hint"])
        self.hint_min_chunk_duration.setText(texts["setting_min_chunk_duration_hint"])
        self.hint_prefer_gpu.setText(texts["setting_prefer_gpu_hint"])
        self.hint_experimental_hw_decode.setText(texts["setting_experimental_hw_decode_hint"])
        self.hint_gpu_probe_unknown_keep_gpu.setText(texts["setting_gpu_probe_unknown_keep_gpu_hint"])
        self.hint_auto_cleanup_missing_files.setText(texts["setting_auto_cleanup_missing_files_hint"])
        self.hint_close_window_action.setText(texts["setting_close_window_action_hint"])
        self.hint_agent_api_enabled.setText(texts["setting_agent_api_enabled_hint"])
        self.hint_team_mode.setText(
            texts.get(
                "setting_team_mode_hint",
                "服务机：启动局域网搜索 + nginx 视频分享。员工机：填写服务机地址后，搜索走服务器，预览用 HTTP URL。",
            )
        )
        self.hint_active_model_profile.setText(
            _fallback_text(
                texts,
                "setting_active_model_profile_hint",
                "切换后将使用该模型独立的数据目录与模型资源目录。",
                "Switching changes both model resources and model-scoped data paths.",
            )
        )
        self.hint_data_root.setText(texts["setting_data_root_hint"])
        self.hint_ffmpeg_path.setText(texts["setting_ffmpeg_path_hint"])
        self.hint_ffmpeg_active.setText(texts["setting_ffmpeg_active"].format(path=texts["setting_ffmpeg_unknown"]))
        self.hint_inference_backend.setText(
            texts["setting_inference_backend"].format(backend=texts["setting_inference_uninitialized"])
        )
        self.hint_inference_backend.setProperty("state", "neutral")
        self.btn_show_runtime_diagnostics.setText(texts.get("setting_show_runtime_diagnostics", "Show diagnostics"))
        self.hint_gpu_runtime.setText(texts["setting_gpu_runtime_link_only"])
        self.hint_gpu_runtime.setOpenExternalLinks(True)
        self.hint_gpu_runtime.setTextFormat(Qt.RichText)
        self.hint_gpu_runtime.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.hint_gpu_runtime.setVisible(False)
        self.hint_model_dir.setText(texts["setting_model_dir_hint"])
        self._update_sampling_mode_visibility()
        self._update_frame_neighbor_rerank_visibility()
        self._update_image_pixel_probe_mode_visibility()
        for label in [
            self.label_fps,
            self.label_top_k,
            self.label_frame_neighbor_rerank_enabled,
            self.label_frame_neighbor_rerank_top_n,
            self.label_frame_neighbor_rerank_window,
            self.label_image_pixel_rerank_top_n,
            self.label_image_pixel_rerank_probe_mode,
            self.label_image_pixel_rerank_time_window_sec,
            self.label_image_pixel_rerank_probe_step_sec,
            self.label_image_search_fetch_multiplier,
            self.label_preview_seconds,
            self.label_thumb_width,
            self.label_thumb_height,
            self.label_export_video_silent,
            self.label_embedding_batch_size,
            self.label_chunk_policy,
            self.label_similarity_threshold,
            self.label_min_chunk_size,
            self.label_min_chunk_duration,
            self.label_prefer_gpu,
            self.label_experimental_hw_decode,
            self.label_gpu_probe_unknown_keep_gpu,
            self.label_auto_cleanup_missing_files,
            self.label_close_window_action,
            self.label_agent_api_enabled,
            self.label_active_model_profile,
            self.label_data_root,
            self.label_ffmpeg_path,
            self.label_model_dir,
        ]:
            self._configure_setting_label(label)
            label.setProperty("detailActive", False)
            repolish_widget(label)
    def refresh_active_setting_detail(self):
        if self._active_setting_label is not None:
            for label, hint_label, extra_hint_labels in self._setting_detail_bindings:
                if label is self._active_setting_label:
                    self._activate_setting_detail(label, hint_label, extra_hint_labels)
                    return
        if self._setting_detail_bindings:
            label, hint_label, extra_hint_labels = self._setting_detail_bindings[0]
            self._activate_setting_detail(label, hint_label, extra_hint_labels)

    def set_runtime_status_texts(self, backend_text, ffmpeg_text, data_text=""):
        self.runtime_status_backend.setText(backend_text or "")
        self.runtime_status_ffmpeg.setText(ffmpeg_text or "")
        self.runtime_status_data.setText(data_text or "")

    def set_search_telemetry_panel(self, body_text, *, file_path="", updated_at=""):
        self.search_telemetry_body.setText(body_text or "")
        if file_path:
            suffix = f" ({updated_at})" if updated_at else ""
            self.search_telemetry_file.setText(f"{file_path}{suffix}")
        else:
            self.search_telemetry_file.setText("")

    def _set_search_telemetry_expanded(self, expanded: bool) -> None:
        self._search_telemetry_expanded = bool(expanded)
        self.search_telemetry_body_widget.setVisible(self._search_telemetry_expanded)
        self.btn_search_telemetry_collapse.setArrowType(
            Qt.ArrowType.DownArrow if self._search_telemetry_expanded else Qt.ArrowType.RightArrow
        )

    def _toggle_search_telemetry_panel(self) -> None:
        self._set_search_telemetry_expanded(not self._search_telemetry_expanded)

