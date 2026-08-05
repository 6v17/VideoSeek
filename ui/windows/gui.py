from collections import deque

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QPixmap, QWheelEvent
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QMainWindow,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.app.config import (
    DEFAULT_CONFIG,
    get_app_version,
    load_config,
    pop_migration_notice,
    pop_startup_migration_summary,
    save_config,
)
from src.app.i18n import get_texts
from src.services.about_service import get_local_about_payload
from src.services.donate_service import get_donate_payload
from src.services.library_service import (
    list_partial_libraries,
)
from src.services.notice_service import get_local_notice_payload
from src.services.query_text_service import prepare_text_query
from src.web.display_qr import build_qr_pixmap
from src.utils import (
    open_in_explorer,
    sync_ffmpeg_path_to_config,
    sync_model_dir_to_config,
)
from src.services.version_service import get_local_version_status
from ui.controllers.app_meta_controller import AppMetaController
from ui.widgets.components import (
    LibraryPage,
    LinkSearchPage,
    NavigationSidebar,
    SearchPage,
    UnderstandingEvidencePage,
)
from ui.widgets.settings import SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, DonateDialog, MobileBridgeDialog, NoticeDialog
from ui.dialogs.html_links import open_html_link
from ui.widgets.sidebar_icons import (
    bilibili_toolbar_icon,
    github_toolbar_icon,
    qq_toolbar_icon,
    sidebar_toolbar_icon_size,
)
from ui.controllers.indexing_controller import IndexingController
from ui.controllers.understanding_controller import UnderstandingController
from ui.widgets.layout import WINDOW_SIZES, apply_window_size
from ui.widgets.preview_panel import _scroll_ancestor_vertically
from ui.controllers.agent_api_controller import AgentApiController
from ui.controllers.team_mode_controller import TeamModeController
from ui.controllers.mobile_bridge_controller import MobileBridgeController
from ui.controllers.video_download_controller import VideoDownloadController
from ui.controllers.preview_controller import PreviewController
from ui.controllers.runtime_resource_controller import RuntimeResourceController
from ui.controllers.search_controller import SearchController
from ui.widgets.styles import DARK_STYLE, LIGHT_STYLE
from ui.windows.gui_settings import SettingsGuiMixin
from ui.windows.gui_preview import PreviewGuiMixin
from ui.windows.gui_library_indexing import LibraryIndexingGuiMixin
from ui.windows.gui_understanding import UnderstandingGuiMixin
from ui.windows.gui_video_download import VideoDownloadGuiMixin
from ui.windows.gui_runtime import RuntimeGuiMixin
from ui.windows.gui_model_packages import ModelPackagesGuiMixin
from ui.windows.gui_ui_state import AppUiStateMixin
from ui.windows.gui_tray import TrayGuiMixin
from ui.windows.gui_startup_migration import StartupMigrationGuiMixin
from ui.windows.gui_search_scope import SearchScopeGuiMixin
from ui.windows.gui_search_presets import SearchPresetsGuiMixin
from ui.windows.gui_search_panel_state import SearchPanelStateMixin
from ui.windows.gui_shot_list import ShotListGuiMixin


class MainWindow(
    QMainWindow,
    StartupMigrationGuiMixin,
    TrayGuiMixin,
    SettingsGuiMixin,
    PreviewGuiMixin,
    LibraryIndexingGuiMixin,
    UnderstandingGuiMixin,
    VideoDownloadGuiMixin,
    RuntimeGuiMixin,
    AppUiStateMixin,
    ModelPackagesGuiMixin,
    SearchScopeGuiMixin,
    SearchPresetsGuiMixin,
    SearchPanelStateMixin,
    ShotListGuiMixin,
):
    """Sidebar / stacked widget order: local search → library → remote link → settings."""

    _NAV_PAGE_ORDER = ("search", "library", "understanding", "link", "settings")

    def __init__(self):
        super().__init__()
        self._init_startup_migration_state()
        self.startup_cancelled = False
        self._close_when_indexing_stops = False
        self.current_img_path = None
        self.notice_payload = None
        self.about_payload = None
        self._startup_complete = False
        self._update_notice_auto_show_pending = False
        self._defer_runtime_warmup = False
        self._preview_dialog_cooldown_until = 0.0
        self._preview_dialog_opening = False
        self._preview_export_queue = deque()
        self._preview_export_active = {}
        self._preview_export_seq = 0
        self._preview_export_tasks = []
        self._local_vector_detail_worker = None
        self._model_package_import_worker = None
        self._ffmpeg_imported_with_package = False
        self._settings_dirty = False
        self._settings_loading = False
        self._settings_dirty_tracking_bound = False
        self._last_index_issues = []
        self._last_index_issue_target = None
        self._search_indexing_notice_effect = None
        self._search_indexing_notice_animation = None
        cfg = load_config()
        self._debug_tools_enabled = bool(cfg.get("show_debug_test_buttons", False))
        self.is_dark_mode = cfg.get("theme", "dark") == "dark"
        self.language = cfg.get("language", "zh")
        self.texts = get_texts(self.language)
        self.version_info = get_local_version_status(self.language)
        self.notice_payload = get_local_notice_payload(self.language)
        self.about_payload = get_local_about_payload(self.language)

        self.init_ui()
        self.app_meta_controller = AppMetaController(self)
        self.app_meta_controller.version_ready.connect(self._update_version_info)
        self.app_meta_controller.notice_ready.connect(self._update_notice_payload)
        self.app_meta_controller.about_ready.connect(self._update_about_payload)
        self.indexing_controller = IndexingController(self)
        self.indexing_controller.status_changed.connect(self._update_indexing_progress)
        self.indexing_controller.runtime_status_changed.connect(self.push_inference_status)
        self.indexing_controller.error_occurred.connect(self._handle_indexing_error)
        self.indexing_controller.finished.connect(self._finish_indexing)
        self.dialogue_index_worker = None
        self.understanding_controller = UnderstandingController(self)
        self.understanding_controller.status_changed.connect(self._update_understanding_progress)
        self.understanding_controller.error_occurred.connect(self._handle_understanding_error)
        self.understanding_controller.chunk_completed.connect(self._handle_understanding_chunk_completed)
        self.understanding_controller.finished.connect(self._finish_understanding_generation)
        self.preview_controller = PreviewController(self)
        self.search_controller = SearchController(self)
        self.search_page.results_pager.page_changed.connect(self.search_controller.go_to_results_page)
        self.video_download_controller = VideoDownloadController(self)
        self.video_download_controller.refresh_default_dir_label()
        self.video_download_controller.load_settings_from_config()
        self._init_search_presets_ui()
        self._init_shot_list_ui()
        self.mobile_bridge_controller = MobileBridgeController(self)
        self.mobile_bridge_controller.search_requested.connect(self._handle_mobile_search_requested)
        self.mobile_bridge_controller.status_changed.connect(self._handle_mobile_bridge_status_changed)
        self.agent_api_controller = AgentApiController(self)
        self.team_mode_controller = TeamModeController(self)
        self.runtime_resource_controller = RuntimeResourceController(self)
        self.runtime_resource_controller.startup_cancelled.connect(self._handle_runtime_resource_exit)
        self.runtime_resource_controller.resources_ready.connect(self._finish_runtime_resource_download)
        self.runtime_resource_controller.status_changed.connect(self.push_resources_status)
        self._init_ui_state()
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self._update_expand_preview_button()
        self._init_system_tray()
        self.apply_texts()
        self._bind_settings_dirty_tracking()
        self.load_settings_values()
        self._set_search_precision_mode_ui("fast")
        self._set_settings_dirty(False)
        self.check_runtime_resources(show_dialog=False)
        if self.startup_cancelled:
            self.search_controller.shutdown()
            self.preview_controller.shutdown()
            return
        self.apply_theme()

    def init_ui(self):
        self.setWindowTitle(f"VideoSeek v{get_app_version()}")
        apply_window_size(
            self,
            WINDOW_SIZES["main"]["preferred"],
            WINDOW_SIZES["main"]["minimum"],
            WINDOW_SIZES["main"]["screen_margin"],
        )

        central = QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        self.sidebar = NavigationSidebar()
        main_layout.addWidget(self.sidebar)

        self.content = QWidget()
        self.content.setObjectName("ContentArea")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        self.pages = QStackedWidget()
        self.search_page = SearchPage()
        self.link_page = LinkSearchPage()
        self.library_page = LibraryPage()
        self.understanding_page = UnderstandingEvidencePage()
        self.settings_page = SettingsPage()
        self.pages.addWidget(self._build_scroll_page(self.search_page))
        self.pages.addWidget(self._build_scroll_page(self.library_page))
        self.pages.addWidget(self._build_scroll_page(self.understanding_page))
        self.pages.addWidget(self._build_scroll_page(self.link_page))
        self.pages.addWidget(self.settings_page)
        content_layout.addWidget(self.pages)
        main_layout.addWidget(self.content, 1)

        self.search_page.preview_placeholder.hide()
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video_widget.setAttribute(Qt.WA_NativeWindow, True)
        # QVideoWidget is nested under QScrollArea / #PanelCard; without this, Qt may
        # promote ancestors to QWidgetWindow and log: "must be a top level window."
        dont_native_ancestors = getattr(
            Qt.WidgetAttribute, "WA_DontCreateNativeAncestors", None
        )
        if dont_native_ancestors is not None:
            self.video_widget.setAttribute(dont_native_ancestors, True)
        self.video_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.video_widget.installEventFilter(self)
        self.search_page.preview_host.mouseDoubleClickEvent = self.open_current_preview_dialog
        self.search_page.btn_manage_presets.installEventFilter(self)
        self.search_page.preview_host_layout.addWidget(self.video_widget, 1)

        self.result_table = self.search_page.result_table

        self.sidebar.btn_page_search.clicked.connect(lambda: self.switch_page("search"))
        self.sidebar.btn_page_link.clicked.connect(lambda: self.switch_page("link"))
        self.sidebar.btn_page_library.clicked.connect(lambda: self.switch_page("library"))
        self.sidebar.btn_page_understanding.clicked.connect(lambda: self.switch_page("understanding"))
        self.sidebar.btn_page_settings.clicked.connect(lambda: self.switch_page("settings"))
        self.sidebar.btn_theme.clicked.connect(self.toggle_theme)
        self.sidebar.btn_donate.clicked.connect(self.show_donate)
        self.sidebar.btn_github.clicked.connect(self.open_github)
        self.sidebar.btn_bilibili.clicked.connect(self.open_bilibili)
        self.sidebar.btn_qq.clicked.connect(self.open_qq)
        self.sidebar.btn_language.clicked.connect(self.toggle_language)
        self.sidebar.btn_about.clicked.connect(self.show_about)
        self.sidebar.btn_notice.clicked.connect(self.show_notice)

        self.search_page.btn_search.clicked.connect(self.start_search)
        self.search_page.btn_save_preset.clicked.connect(self.save_compose_as_preset)
        self.search_page.btn_clear.clicked.connect(self.clear_all_content)
        self.search_page.search_scope_select.editor_requested.connect(self.open_search_scope_editor)
        self.search_page.btn_mobile_toggle.clicked.connect(self.toggle_mobile_bridge)
        self.search_page.btn_mobile_qr.clicked.connect(self.show_mobile_bridge_qr)
        self.search_page.btn_expand_preview.clicked.connect(self.open_current_preview_dialog)
        self.search_page.btn_export_tasks.clicked.connect(self.show_preview_export_tasks)
        self.search_page.search_mode.currentIndexChanged.connect(self._on_search_mode_changed)
        self.search_page.image_search_mode.currentIndexChanged.connect(self._on_image_search_mode_changed)
        if hasattr(self.search_page, "dialogue_search_mode"):
            self.search_page.dialogue_search_mode.currentIndexChanged.connect(
                self._on_dialogue_search_mode_changed
            )
        # Do not rebuild scope/library details on every keystroke.
        self.search_page.text_search.textChanged.connect(
            lambda *_: self._refresh_search_panel_state(refresh_scope=False)
        )
        self.search_page.search_query_tabs.currentChanged.connect(self._on_search_query_tab_changed)
        self.search_page.img_label.mousePressEvent = lambda e: self.upload_file()
        self._init_search_scope_state()
        self.link_page.btn_probe.clicked.connect(self.start_video_download_probe)
        self.link_page.btn_download.clicked.connect(self.start_video_download)
        self.link_page.btn_clear.clicked.connect(self.clear_video_download_content)
        self.link_page.btn_change_dir.clicked.connect(self.choose_download_default_dir)
        self.link_page.btn_open_dir.clicked.connect(self.open_download_default_dir)
        self.link_page.btn_browse_cookie.clicked.connect(self.browse_download_cookie_file)
        self.link_page.btn_clear_cookie.clicked.connect(self.clear_download_cookie_file)
        self.link_page.btn_cookie_help.clicked.connect(self.show_download_cookie_help)
        self.link_page.btn_clear_legacy.clicked.connect(self.clear_legacy_network_data)

        self.library_page.btn_add_lib.clicked.connect(self.select_video_folder)
        self.library_page.btn_remove_lib.clicked.connect(self.remove_selected_libraries)
        self.library_page.btn_sync_db.clicked.connect(
            lambda: self.start_update_index(checked_only=True)
        )
        self.library_page.btn_build_dialogue_index.clicked.connect(self.start_dialogue_index)
        self.library_page.btn_reembed_dialogue.clicked.connect(self.start_dialogue_reembed)
        self.library_page.btn_clear_dialogue.clicked.connect(self.clear_selected_dialogue_transcripts)
        self.library_page.btn_refresh_dialogue_library.clicked.connect(self.refresh_dialogue_library_table)
        self.library_page.btn_export_dialogue.clicked.connect(self.export_dialogue_library)
        self.library_page.input_subtitle_sample_interval.editingFinished.connect(
            self._on_subtitle_sample_interval_changed
        )
        self.library_page.input_subtitle_ocr_batch.editingFinished.connect(
            self._on_subtitle_ocr_batch_changed
        )
        self.library_page.input_subtitle_ocr_batch.valueChanged.connect(
            self._on_subtitle_ocr_batch_changed
        )
        self.library_page.btn_stop_dialogue_index.clicked.connect(self.stop_update_index)
        self.library_page.btn_stop_index.clicked.connect(self.stop_update_index)
        self.library_page.library_stack.currentChanged.connect(self._on_library_tab_changed)
        self.library_page.btn_index_issues.clicked.connect(self.show_last_index_issue_details)
        self.library_page.btn_cleanup_missing.clicked.connect(self.cleanup_missing_library_vectors)
        self.library_page.btn_vector_details.clicked.connect(self.show_local_vector_details)
        self.library_page.btn_debug_gpu_oom.clicked.connect(self.start_debug_gpu_oom)
        self.library_page.btn_debug_system_oom.clicked.connect(self.start_debug_system_oom)

        self.understanding_page.btn_generate_evidence.clicked.connect(self.start_generate_understanding_evidence)
        self.understanding_page.btn_evidence_details.clicked.connect(self.show_local_evidence_details)
        self.understanding_page.btn_export_video_json.clicked.connect(self.export_current_video_understanding_json)
        self.understanding_page.btn_understanding_setup.clicked.connect(self.open_understanding_settings)
        self.understanding_page.btn_stop.clicked.connect(self.stop_understanding_generation)
        self.understanding_page.btn_save_config.clicked.connect(self.save_understanding_settings)
        self.understanding_page.btn_test_vlm_connection.clicked.connect(self.test_understanding_vlm_connection)
        self.understanding_page.input_vlm_provider_mode.currentIndexChanged.connect(self._on_vlm_provider_mode_changed)
        self.understanding_page.input_vlm_provider_preset.currentIndexChanged.connect(self._on_vlm_provider_preset_changed)
        self.understanding_page.scope_combo.currentIndexChanged.connect(self._on_understanding_scope_changed)
        self.understanding_page.video_combo.currentIndexChanged.connect(self._on_understanding_video_changed)
        self.understanding_page.chunk_timeline.chunk_clicked.connect(self._on_understanding_chunk_clicked)
        self.understanding_page.chunk_timeline.chunk_double_clicked.connect(self._on_understanding_chunk_double_clicked)
        self._understanding_chunk_payloads = {}
        self._understanding_index_chunks = []

        self.settings_page.btn_save.clicked.connect(self.save_settings)
        self.settings_page.btn_reset.clicked.connect(self.reset_settings)
        self.settings_page.btn_edit_sampling_rules.clicked.connect(self._open_sampling_rules_dialog)
        self.settings_page.btn_browse_data_root.clicked.connect(self._browse_data_root)
        self.settings_page.btn_browse_ffmpeg_path.clicked.connect(self._browse_ffmpeg_path)
        self.settings_page.btn_browse_model_dir.clicked.connect(self._browse_model_dir)
        self.settings_page.btn_migrate_model_dir.clicked.connect(self._migrate_model_root)
        self.settings_page.btn_download_runtime_resources.clicked.connect(self.open_runtime_resource_dialog)
        self.settings_page.btn_remove_model_profile.clicked.connect(self.remove_current_model_profile)
        self.settings_page.input_active_model_profile.currentIndexChanged.connect(self._on_active_model_profile_changed)
        self.settings_page.btn_show_runtime_diagnostics.clicked.connect(self.show_runtime_diagnostics)
        self.settings_page.btn_refresh_search_telemetry.clicked.connect(self.refresh_search_telemetry_panel)
        self.settings_page.btn_cleanup_old_data_root.clicked.connect(self.cleanup_old_data_root)
        self.settings_page.btn_cleanup_old_model_dir.clicked.connect(self.cleanup_old_model_dir)
        self.settings_page.btn_copy_agent_api_url.clicked.connect(self.copy_agent_api_url)
        self.settings_page.btn_copy_agent_starter.clicked.connect(self.copy_agent_starter)
        self.settings_page.btn_team_copy_share.clicked.connect(self.copy_team_share_info)

        self.setAcceptDrops(True)
        for page in (self.search_page, self.link_page, self.library_page, self.understanding_page, self.settings_page):
            page.header.runtime_banner_action.clicked.connect(self.open_runtime_resource_dialog)

    def _build_scroll_page(self, page_widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page_widget)
        return scroll

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.Wheel and isinstance(event, QWheelEvent):
            if watched is getattr(self, "video_widget", None) or watched is getattr(
                getattr(self, "search_page", None), "btn_manage_presets", None
            ):
                # Native video surface / focused buttons would otherwise swallow page scrolling.
                if _scroll_ancestor_vertically(watched, event):
                    return True
                event.ignore()
                return False
        return super().eventFilter(watched, event)

    def _nav_page_index(self, page_name: str) -> int:
        return self._NAV_PAGE_ORDER.index(page_name)

    def switch_page(self, page_name):
        mapping = {name: i for i, name in enumerate(self._NAV_PAGE_ORDER)}
        prev_idx = self.pages.currentIndex()
        next_idx = mapping[page_name]
        self.pages.setCurrentIndex(next_idx)
        self.sidebar.set_current_page(page_name)
        if prev_idx == mapping["search"] and next_idx != mapping["search"]:
            self.preview_controller.stop_preview()
            dlg = getattr(self, "_preview_dialog", None)
            if dlg is not None:
                dlg.dismiss_for_page_switch()
        if page_name == "settings":
            self._refresh_agent_api_status()
            self.refresh_search_telemetry_panel()
        if page_name == "understanding":
            if hasattr(self, "load_understanding_settings"):
                self.load_understanding_settings(refresh_status=False)
            # Load timeline/scope before first paint settles so the track does not jump.
            if hasattr(self, "_refresh_understanding_scope_options"):
                self._refresh_understanding_scope_options()
            QTimer.singleShot(0, self._deferred_understanding_page_refresh)
        if page_name == "link":
            if hasattr(self, "video_download_controller"):
                self.video_download_controller.refresh_default_dir_label()

    def _update_version_info(self, version_info):
        self.version_info = version_info
        self.apply_texts()
        self._maybe_auto_show_startup_notices()

    def _update_notice_payload(self, notice_payload):
        self.notice_payload = notice_payload

    def _update_about_payload(self, about_payload):
        self.about_payload = about_payload

    def apply_texts(self):
        self.texts = get_texts(self.language)
        t = self.texts
        try:
            config = load_config()
        except Exception as exc:
            self.show_error_dialog(t["settings_load_failed"], exc)
            return

        self.setWindowTitle(f"{t['app_name']} v{get_app_version()}")
        self.sidebar.title.setText(t["app_name"])
        self.sidebar.subtitle.setText(t["app_subtitle"])
        github_url = str(get_donate_payload().get("github_url") or "").strip() or "https://github.com/6v17/VideoSeek"
        tip = t.get("brand_free_tip", "永久免费 · 开源")
        self.sidebar.free_tip.setText(f'<a href="{github_url}">{tip}</a>')
        self.sidebar.free_tip.setToolTip(t.get("brand_free_tip_tooltip", github_url))
        self.sidebar.hero_tag.setText(t["hero_tag"])
        self.sidebar.hero_title.setText(t["hero_title"])
        self.sidebar.hero_body.setText(t["hero_body"])
        self.sidebar.btn_page_search.setText(t["nav_search"])
        self.sidebar.btn_page_link.setText(t["nav_link"])
        self.sidebar.btn_page_library.setText(t["nav_library"])
        self.sidebar.btn_page_understanding.setText(t["nav_understanding"])
        self.sidebar.btn_page_settings.setText(t["nav_settings"])
        self.sidebar.btn_notice.setText(
            t["notice_short_update"]
            if self.version_info and self.version_info.get("has_update")
            else t["notice_short"]
        )
        if self.version_info and self.version_info.get("has_update"):
            self.sidebar.btn_notice.setObjectName("UpdateButton")
        else:
            self.sidebar.btn_notice.setObjectName("SidebarFooterButton")
        self.sidebar.btn_notice.style().unpolish(self.sidebar.btn_notice)
        self.sidebar.btn_notice.style().polish(self.sidebar.btn_notice)
        self.sidebar.btn_notice.update()
        self.sidebar.btn_about.setText(t["about_short"])
        self.sidebar.btn_about.setObjectName("SidebarFooterButton")
        self.sidebar.btn_about.style().unpolish(self.sidebar.btn_about)
        self.sidebar.btn_about.style().polish(self.sidebar.btn_about)
        self.sidebar.btn_about.update()
        self.sidebar.btn_language.setText(t["language_toggle"])
        self._refresh_sidebar_icon_buttons(t)
        self.sidebar.runtime_hint.hide()
        self.sidebar.runtime_hint.setToolTip("")

        self.search_page.header.title.setText(t["search_page_title"])
        self.search_page.header.subtitle.setText(t["search_page_desc"])
        self.search_page.indexing_notice_text.setText(t.get("search_during_indexing_hint", ""))
        self._refresh_search_panel_state()
        self.search_page.preview_title.setText(t["preview_panel"])
        self.search_page.btn_expand_preview.setText(t.get("preview_expand", "放大预览"))
        self.search_page.results_title.setText(t["results_panel"])
        self.search_page.btn_export_tasks.setText(t.get("preview_export_tasks", "Export Tasks"))
        self._update_shot_list_button()
        self._update_expand_preview_button()
        self.search_page.text_search.setPlaceholderText(t["search_placeholder"])
        self.search_page.mobile_toggle_label.setText(t.get("mobile_bridge_toggle_label", t["mobile_bridge_start"]))
        self.search_page.btn_mobile_qr.setText(t["mobile_bridge_qr"])
        self._update_mobile_bridge_controls()
        self.search_page.btn_search.setText(t["search"])
        self.search_page.btn_clear.setText(t["clear"])
        self.search_page.search_scope_label.setText(t.get("search_scope_label", ""))
        self.search_page.preview_placeholder.setText(t["preview_placeholder"])
        self.result_table.apply_header_labels(t)
        self.search_page.result_view.set_empty_message(t["no_results"])
        self.search_page.results_pager.set_texts(t)
        self.search_controller._sync_results_pager()

        self.link_page.header.title.setText(t["link_page_title"])
        self.link_page.header.subtitle.setText(t["link_page_desc"])
        self.link_page.links_input.setPlaceholderText(t["download_links_placeholder"])
        self.link_page.btn_change_dir.setText(t["download_change_dir"])
        cfg = load_config()
        self.link_page.set_download_texts(t)
        self.link_page.set_cookie_file_path(str(cfg.get("download_cookie_file", "") or ""))
        self.video_download_controller.refresh_cookie_admin_hint()
        self.link_page.list_title.setText(t["download_list_title"])
        self.link_page.set_list_headers(t["download_list_headers"])
        self.link_page.btn_probe.setText(t["download_btn_probe"])
        self.link_page.btn_download.setText(t["download_btn_start_all"])
        self.link_page.btn_clear.setText(t["clear"])
        self.link_page.btn_open_dir.setText(t["download_btn_open_dir"])
        self.link_page.btn_clear_legacy.setText(t["download_btn_clear_legacy"])
        self.video_download_controller.refresh_default_dir_label()

        self.library_page.header.title.setText(t["library_page_title"])
        self.library_page.header.subtitle.setText(t["library_page_desc"])
        self.library_page.btn_tab_visual.setText(t.get("library_tab_visual", "Videos"))
        self.library_page.btn_tab_dialogue.setText(t.get("library_tab_dialogue", "Dialogue"))
        self.library_page.table_title.setText(t["library_table_title"])
        self.library_page.dialogue_table_title.setText(
            t.get("dialogue_library_table_title", "Extracted dialogue")
        )
        self.library_page.lbl_shared_library_hint.setText(
            t.get(
                "library_shared_add_hint",
                "Add a folder once; then sync visuals or extract subtitles from the tabs below.",
            )
        )
        if hasattr(self, "_refresh_team_client_library_chrome"):
            self._refresh_team_client_library_chrome()
        self.library_page.btn_add_lib.setText(t["add_folder"])
        self.library_page.btn_remove_lib.setText(t.get("remove_library", "Remove Library"))
        if hasattr(self, "_refresh_library_action_hints"):
            self._refresh_library_action_hints()
        else:
            self.library_page.btn_remove_lib.setToolTip(t.get("remove_library_hint", ""))
        self.library_page.btn_sync_db.setText(
            t.get("sync_selected_videos", t.get("update_index", "Sync selected"))
        )
        self.library_page.visual_video_tree.set_action_texts(
            open_text=t.get("open_folder", "Open"),
            empty_text=t.get("library_list_empty", ""),
            status_template=t.get("library_sync_status", "{ready}/{total} synced"),
            header_video=t.get("library_col_video", t.get("search_scope_video_col", "Video")),
            header_count=t.get("library_col_count", "Count"),
            header_status=t.get("library_col_status", "Status"),
            header_action=t.get("library_col_action", "Action"),
        )
        self.library_page.subtitle_video_tree.set_action_texts(
            open_text=t.get("open_folder", "Open"),
            empty_text=t.get("dialogue_library_empty", ""),
            status_template=t.get("library_extract_status", "{ready}/{total} extracted"),
            header_video=t.get("library_col_video", t.get("search_scope_video_col", "Video")),
            header_count=t.get("library_col_count", "Count"),
            header_status=t.get("library_col_status", "Status"),
            header_action=t.get("library_col_action", "Action"),
        )
        self.library_page.btn_build_dialogue_index.setText(t.get("build_dialogue_index", "Build dialogue index"))
        self.library_page.btn_build_dialogue_index.setToolTip(
            t.get("build_dialogue_index_hint", "")
        )
        self.library_page.btn_reembed_dialogue.setText(
            t.get("reembed_dialogue_index", "Re-embed dialogue vectors")
        )
        self.library_page.btn_reembed_dialogue.setToolTip(
            t.get("reembed_dialogue_index_hint", "")
        )
        self.library_page.btn_clear_dialogue.setText(
            t.get("clear_dialogue_index", "Clear selected subtitles")
        )
        self.library_page.btn_clear_dialogue.setToolTip(
            t.get("clear_dialogue_index_hint", "")
        )
        self.library_page.lbl_subtitle_sample_interval.setText(
            t.get("subtitle_sample_interval", "Frame interval")
        )
        interval_tip = t.get(
            "subtitle_sample_interval_hint",
            "OCR frame sample interval inside speech segments (0.1–6.0s).",
        )
        self.library_page.lbl_subtitle_sample_interval.setToolTip(interval_tip)
        self.library_page.input_subtitle_sample_interval.setToolTip(interval_tip)
        if hasattr(self, "load_subtitle_sample_interval"):
            self.load_subtitle_sample_interval()
        self.library_page.lbl_subtitle_ocr_batch.setText(
            t.get("subtitle_ocr_batch", "OCR stack")
        )
        batch_tip = t.get(
            "subtitle_ocr_batch_hint",
            "Frames stacked per OCR pass (1–6). 1=per-frame; higher is usually faster, with automatic per-frame fallback if ambiguous.",
        )
        self.library_page.lbl_subtitle_ocr_batch.setToolTip(batch_tip)
        self.library_page.input_subtitle_ocr_batch.setToolTip(batch_tip)
        if hasattr(self, "load_subtitle_ocr_batch"):
            self.load_subtitle_ocr_batch()
        self.library_page.btn_export_dialogue.setText(
            t.get("export_dialogue_library", "Export dialogue")
        )
        self.library_page.btn_export_dialogue.setToolTip(
            t.get("export_dialogue_library_hint", "")
        )
        self.library_page.btn_refresh_dialogue_library.setText(
            t.get("refresh_dialogue_library", "Refresh")
        )
        self.library_page.btn_refresh_dialogue_library.setToolTip(
            t.get("refresh_dialogue_library_hint", "")
        )
        self.library_page.btn_stop_index.setText(t["stop"])
        self.library_page.btn_stop_dialogue_index.setText(t["stop"])
        self.library_page.btn_index_issues.setText(t["index_issues_button"])
        self.library_page.btn_cleanup_missing.setText(t["cleanup_missing_vectors"])
        self.library_page.btn_vector_details.setText(t["library_vectors_detail"])
        self.library_page.btn_debug_gpu_oom.setText(t["debug_gpu_oom"])
        self.library_page.btn_debug_system_oom.setText(t["debug_system_oom"])
        self.library_page.btn_debug_gpu_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self.library_page.btn_debug_system_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self._apply_index_issue_button_state(bool(self._last_index_issues))

        self.understanding_page.header.title.setText(t["understanding_page_title"])
        self.understanding_page.header.subtitle.setText(t["understanding_page_desc"])
        self.understanding_page.config_title.setText(t["understanding_config_title"])
        self.understanding_page.workspace_title.setText(t["understanding_workspace_title"])
        self.understanding_page.label_vlm_provider_mode.setText(t["understanding_vlm_provider_mode_label"])
        self.understanding_page.input_vlm_provider_mode.setToolTip(t["understanding_vlm_provider_mode_hint"])
        current_vlm_mode = self.understanding_page.input_vlm_provider_mode.currentData()
        self._populate_vlm_provider_mode_options(current_vlm_mode or "local")
        self.understanding_page.label_vlm_provider_preset.setText(t["understanding_vlm_provider_preset_label"])
        self.understanding_page.input_vlm_provider_preset.setToolTip(t["understanding_vlm_provider_preset_hint"])
        current_vlm_preset = self.understanding_page.input_vlm_provider_preset.currentData()
        self._populate_vlm_provider_preset_options(current_vlm_mode or "local", current_vlm_preset or "lm_studio")
        self._sync_vlm_provider_ui()
        self.understanding_page.label_remote_vlm_base_url.setText(t["setting_remote_vlm_base_url"])
        self.understanding_page.input_remote_vlm_base_url.setToolTip(t["setting_remote_vlm_base_url_hint"])
        self.understanding_page.label_remote_vlm_api_key.setText(t["setting_remote_vlm_api_key"])
        self.understanding_page.input_remote_vlm_api_key.setToolTip(t["setting_remote_vlm_api_key_hint"])
        self.understanding_page.label_remote_vlm_model.setText(t["setting_remote_vlm_model"])
        self.understanding_page.input_remote_vlm_model.setToolTip(t["setting_remote_vlm_model_hint"])
        self.understanding_page.label_caption_language.setText(t["understanding_caption_language_label"])
        current_language = self.understanding_page.input_caption_language.currentData()
        self._populate_understanding_caption_language_options(current_language or "zh")
        self.understanding_page.input_caption_language.setToolTip(t["understanding_caption_language_hint"])
        self.understanding_page.label_caption_concurrency.setText(t["understanding_caption_concurrency_label"])
        self.understanding_page.input_caption_concurrency.setToolTip(t["understanding_caption_concurrency_hint"])
        self.understanding_page.btn_save_config.setText(t["understanding_save_config"])
        self.understanding_page.btn_test_vlm_connection.setText(t["understanding_test_vlm_connection"])
        self.understanding_page.btn_test_vlm_connection.setToolTip(t["understanding_test_vlm_connection_hint"])
        self.understanding_page.scope_label.setText(t["understanding_scope_label"])
        self.understanding_page.video_label.setText(t["understanding_video_label"])
        self.understanding_page.timeline_label.setText(t["understanding_timeline_label"])
        self.understanding_page.timeline_hint.setText(t["understanding_timeline_hint"])
        self.understanding_page.chunk_detail_title.setText(t["understanding_chunk_detail_title"])
        self.understanding_page.video_summary_title.setText(t["understanding_video_summary_title"])
        self.understanding_page.btn_generate_evidence.setText(t["understanding_generate_selected_video"])
        self.understanding_page.btn_evidence_details.setText(t["library_evidence_detail"])
        self.understanding_page.btn_export_video_json.setText(t["understanding_export_video_json"])
        self.understanding_page.btn_understanding_setup.setText(t["understanding_setup_action"])
        self.understanding_page.btn_stop.setText(t["stop"])
        if self._is_current_page("understanding"):
            if hasattr(self, "_refresh_understanding_page_fast"):
                self._refresh_understanding_page_fast()
        else:
            self._refresh_understanding_ui()
            if hasattr(self, "_refresh_understanding_settings_status"):
                self._refresh_understanding_settings_status()

        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.setText(t["settings_page_desc"])
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        self.refresh_search_telemetry_panel()
        if hasattr(self, "_rebuild_tray_menu"):
            self._rebuild_tray_menu()
        self.push_inference_status()
        self._refresh_pending_cleanup_actions(config)

        if not self.current_img_path and not self.search_page.img_label.pixmap():
            self.search_page.img_label.setText(t["image_drop_hint"])

        self.search_page.lbl_status.setText(t["ready"])
        self.library_page.lbl_status.setText(t["ready"])
        if not (
            getattr(self, "understanding_controller", None)
            and self.understanding_controller.is_running()
        ):
            self.understanding_page.lbl_status.setText(t["ready"])
        self.settings_page.lbl_status.setText(t["settings_hint"])
        self._bind_sampling_preview_signals()
        self._update_sampling_preview()
        if self._startup_complete:
            self.refresh_library_table()
            self.refresh_search_presets_ui()

    def _finish_startup_sequence(self):
        synced_model_dir = sync_model_dir_to_config()
        synced_path = sync_ffmpeg_path_to_config()
        if synced_model_dir:
            self.settings_page.input_model_dir.setText(synced_model_dir)
        if synced_path:
            self.settings_page.input_ffmpeg_path.setText(synced_path)
        self._startup_complete = True
        if getattr(self, "_defer_runtime_warmup", False):
            self._defer_runtime_warmup = False
            self._start_runtime_warmup()
        # Show UI first; heavy orphan/index cleanup can wait until the event loop is idle.
        self.refresh_library_table()
        self.refresh_search_presets_ui()
        self._prompt_resume_partial_indexing()
        self.app_meta_controller.refresh(self.language)
        self._apply_team_mode_settings()
        self._apply_agent_api_settings()
        QTimer.singleShot(0, self._bootstrap_understanding_resources)
        QTimer.singleShot(1500, self._idle_maintain_library_metadata)
        QTimer.singleShot(700, self._maybe_auto_show_startup_notices)

    def _idle_maintain_library_metadata(self) -> None:
        try:
            from src.services.library_service import maintain_library_metadata

            maintain_library_metadata()
        except Exception:
            pass

    def _bootstrap_understanding_resources(self):
        """Copy built-in understanding profiles/components once after startup (off the page-click path)."""
        try:
            from src.services.understanding_resource_service import (
                ensure_understanding_components_installed,
                ensure_understanding_profiles_installed,
            )

            ensure_understanding_profiles_installed()
            ensure_understanding_components_installed()
        except Exception:
            pass

    def show_notice(self):
        had_update = bool(self.version_info and self.version_info.get("has_update"))
        NoticeDialog(
            self,
            self.is_dark_mode,
            self.language,
            notice=self.notice_payload,
            version_info=self.version_info,
        ).exec()
        if had_update:
            self._mark_update_notice_seen()

    def _should_auto_show_free_notice(self) -> bool:
        if not getattr(self, "_startup_complete", False):
            return False
        # Session lock: once claimed/shown this run, never queue again.
        if getattr(self, "_free_notice_handled", False):
            return False
        try:
            config = load_config()
        except Exception:
            return False
        return not bool(config.get("free_notice_seen", False))

    def _mark_free_notice_seen(self) -> None:
        self._free_notice_handled = True
        try:
            config = load_config()
            config["free_notice_seen"] = True
            save_config(config)
        except Exception:
            return

    def _should_auto_show_update_notice(self) -> bool:
        if not getattr(self, "_startup_complete", False):
            return False
        # Wait until free-notice flow is finished for this session.
        if getattr(self, "_free_notice_auto_show_pending", False):
            return False
        if self._should_auto_show_free_notice():
            return False
        info = self.version_info or {}
        if not info.get("has_update"):
            return False
        latest = str(info.get("latest_version") or "").strip()
        if not latest:
            return False
        try:
            config = load_config()
        except Exception:
            return False
        dismissed = str(config.get("update_notice_dismissed_version") or "").strip()
        return dismissed != latest

    def _mark_update_notice_seen(self) -> None:
        info = self.version_info or {}
        latest = str(info.get("latest_version") or "").strip()
        if not latest:
            return
        try:
            config = load_config()
            config["update_notice_dismissed_version"] = latest
            save_config(config)
        except Exception:
            return

    def _maybe_auto_show_startup_notices(self) -> None:
        if not getattr(self, "_startup_complete", False):
            return
        if getattr(self, "_startup_notices_scheduled", False):
            return
        self._startup_notices_scheduled = True
        if self._should_auto_show_free_notice():
            self._maybe_auto_show_free_notice()
            return
        self._maybe_auto_show_update_notice()

    def _maybe_auto_show_free_notice(self) -> None:
        if not self._should_auto_show_free_notice():
            self._maybe_auto_show_update_notice()
            return
        if getattr(self, "_free_notice_auto_show_pending", False):
            return
        # Claim + persist before the modal opens, so overlapping startup callbacks
        # cannot queue a second dialog while .exec() is blocking.
        self._free_notice_auto_show_pending = True
        self._mark_free_notice_seen()
        QTimer.singleShot(200, self._auto_show_free_notice)

    def _auto_show_free_notice(self) -> None:
        self._free_notice_auto_show_pending = False
        self.show_info_dialog(
            self.texts.get("free_notice_title", "使用说明"),
            self.texts.get(
                "free_notice_body",
                "VideoSeek 永久免费。\n有人收费卖给你或收代装费，那是骗子。\n官方：https://github.com/6v17/VideoSeek",
            ),
            kind="info",
        )
        self._maybe_auto_show_update_notice()

    def _maybe_auto_show_update_notice(self) -> None:
        if not self._should_auto_show_update_notice():
            return
        if getattr(self, "_update_notice_auto_show_pending", False):
            return
        self._update_notice_auto_show_pending = True
        QTimer.singleShot(300, self._auto_show_update_notice)

    def _auto_show_update_notice(self) -> None:
        self._update_notice_auto_show_pending = False
        if not self._should_auto_show_update_notice():
            return
        self.show_notice()

    def show_about(self):
        AboutDialog(
            self,
            self.is_dark_mode,
            self.language,
            version_info=self.version_info,
            about=self.about_payload,
        ).exec()

    def show_donate(self):
        DonateDialog(
            self,
            is_dark=self.is_dark_mode,
            language=self.language,
            donate=get_donate_payload(),
        ).exec()

    def open_github(self):
        self._open_social_link("github_url")

    def open_bilibili(self):
        self._open_social_link("bilibili_url")

    def open_qq(self):
        self._open_social_link("qq_url")

    def _open_social_link(self, key: str):
        url = str(get_donate_payload().get(key, "") or "").strip()
        if url:
            open_html_link(url)

    def _refresh_sidebar_icon_buttons(self, texts=None):
        t = texts or self.texts
        social = get_donate_payload()
        icon_size = sidebar_toolbar_icon_size()
        self.sidebar.btn_theme.setText("☀" if self.is_dark_mode else "🌙")
        self.sidebar.btn_theme.setToolTip(
            t["theme_switch_to_light"] if self.is_dark_mode else t["theme_switch_to_dark"]
        )
        self.sidebar.btn_donate.setText("❤")
        self.sidebar.btn_donate.setToolTip(t["donate_tooltip"])
        self.sidebar.btn_github.setIcon(github_toolbar_icon(is_dark=self.is_dark_mode))
        self.sidebar.btn_github.setIconSize(icon_size)
        self.sidebar.btn_github.setToolTip(t["sidebar_github_tooltip"])
        self.sidebar.btn_github.setVisible(bool(social.get("github_url")))

        has_bilibili = bool(social.get("bilibili_url"))
        self.sidebar.btn_bilibili.setIcon(bilibili_toolbar_icon())
        self.sidebar.btn_bilibili.setIconSize(icon_size)
        self.sidebar.btn_bilibili.setToolTip(t["sidebar_bilibili_tooltip"])
        self.sidebar.btn_bilibili.setVisible(has_bilibili)

        has_qq = bool(social.get("qq_url"))
        self.sidebar.btn_qq.setIcon(qq_toolbar_icon())
        self.sidebar.btn_qq.setIconSize(icon_size)
        self.sidebar.btn_qq.setToolTip(t["sidebar_qq_tooltip"])
        self.sidebar.btn_qq.setVisible(has_qq)

    def start_search(self):
        if not self._ensure_startup_migration_idle("feature_search"):
            return

        active_tab = self._search_active_tab()
        # Subtitle keyword search uses the global transcript store — no CLIP model.
        if active_tab == self.SEARCH_TAB_DIALOGUE:
            dialogue_query = self.search_page.search_panel.dialogue_query()
            if not dialogue_query:
                self.search_page.lbl_status.setText(
                    self.texts.get("search_empty_dialogue", self.texts["empty_query"])
                )
                return
            self._run_dialogue_search(dialogue_query)
            return

        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return

        if active_tab == self.SEARCH_TAB_COMPOSE:
            self._start_compose_search()
            return

        text_query = self.search_page.search_panel.text_query()
        if active_tab == self.SEARCH_TAB_TEXT:
            if not text_query:
                self.search_page.lbl_status.setText(self.texts.get("search_empty_text", self.texts["empty_query"]))
                return
            self._run_text_search(text_query)
            return

        if not self.current_img_path:
            self.search_page.lbl_status.setText(self.texts.get("search_empty_image", self.texts["empty_query"]))
            return
        self._run_image_search(self.current_img_path)

    def _run_text_search(self, raw_query, *, sync_ui=True):
        query_info = prepare_text_query(str(raw_query or ""))
        if query_info["too_short"]:
            self.search_page.lbl_status.setText(self.texts["query_too_short"])
            return False
        if query_info["generic"] and sync_ui:
            self.show_info_dialog(
                self.texts["query_generic_title"],
                self.texts["query_generic_hint"],
                kind="info",
            )
        query = str(query_info["normalized"] or "").strip()
        if not query:
            self.search_page.lbl_status.setText(self.texts.get("search_empty_text", self.texts["empty_query"]))
            return False
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return False

        if sync_ui:
            self.switch_page("search")
            self._set_search_query_tab(self.SEARCH_TAB_TEXT)
            self.search_page.search_panel.set_text_query(query)

        from src.services.search_scope import resolve_default_active_search_scope

        scope_video_paths, scope_library_paths = resolve_default_active_search_scope()
        search_precision_mode = self._resolve_search_precision_mode(
            is_text=True,
            has_image=False,
        )
        self.search_controller.start_search(
            query,
            True,
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            search_mode=self._resolve_effective_search_mode(
                is_text=True,
                has_image=False,
                search_precision_mode=search_precision_mode,
            ),
            search_precision_mode=search_precision_mode,
        )
        return True

    def _run_dialogue_search(self, raw_query, *, sync_ui=True):
        query = str(raw_query or "").strip()
        if not query:
            self.search_page.lbl_status.setText(
                self.texts.get("search_empty_dialogue", self.texts["empty_query"])
            )
            return False
        # Switch to the subtitle tab before scope validation so dialogue scope is used.
        if sync_ui:
            self.switch_page("search")
            self._set_search_query_tab(self.SEARCH_TAB_DIALOGUE)
            self.search_page.search_panel.set_dialogue_query(query)
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return False

        from src.services.search_scope import resolve_default_active_dialogue_search_scope

        scope_video_paths, scope_library_paths = resolve_default_active_dialogue_search_scope()
        match_mode = "exact"
        if hasattr(self, "_dialogue_match_mode_from_ui"):
            match_mode = self._dialogue_match_mode_from_ui()
        self.search_controller.start_search(
            query,
            True,
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            search_kind="dialogue",
            search_mode=match_mode,
        )
        return True

    def _run_image_search(self, image_path, *, sync_ui=True):
        """Execute the PC image-tab search path for a concrete image file."""
        path = str(image_path or "").strip()
        if not path:
            self.search_page.lbl_status.setText(self.texts.get("search_empty_image", self.texts["empty_query"]))
            return False
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return False

        if sync_ui:
            self.switch_page("search")
            self._set_image_query(path, clear_text=False)
        elif not self.current_img_path:
            self.current_img_path = path
        if not self.current_img_path:
            return False

        from src.services.search_scope import resolve_default_active_search_scope

        scope_video_paths, scope_library_paths = resolve_default_active_search_scope()
        search_precision_mode = self._resolve_search_precision_mode(
            is_text=False,
            has_image=True,
        )
        self.search_controller.start_search(
            path,
            False,
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            search_mode=self._resolve_effective_search_mode(
                is_text=False,
                has_image=True,
                search_precision_mode=search_precision_mode,
            ),
            search_precision_mode=search_precision_mode,
            video_discovery_enabled=self._resolve_video_discovery_enabled(
                is_text=False,
                has_image=True,
            ),
        )
        return True

    def _run_compose_search_with_inputs(
        self,
        raw_query,
        image_paths,
        fusion=None,
        *,
        sync_ui=True,
    ):
        from src.services.search_preset_service import build_compose_search_plan
        from src.services.search_scope import resolve_default_active_search_scope

        query = str(raw_query or "").strip()
        paths = [str(path or "").strip() for path in (image_paths or []) if str(path or "").strip()]
        if not query and not paths:
            self.search_page.lbl_status.setText(
                self.texts.get("search_compose_empty", self.texts["empty_query"])
            )
            return False
        if query:
            try:
                query_info = prepare_text_query(query)
            except Exception:
                query_info = {"normalized": query, "too_short": False, "generic": False, "changed": False}
            if query_info.get("too_short"):
                self.search_page.lbl_status.setText(self.texts["query_too_short"])
                return False
            if query_info.get("generic") and sync_ui:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query = str(query_info.get("normalized") or query).strip()
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return False

        effective_fusion = fusion
        if sync_ui:
            self.switch_page("search")
            compose_form = self.search_page.search_panel.compose_form
            self._set_search_query_tab(self.SEARCH_TAB_COMPOSE)
            compose_form.clear()
            if query:
                compose_form.input_description.setPlainText(query)
            for image_path in paths:
                compose_form.add_image(image_path)
            if effective_fusion is None:
                effective_fusion = compose_form.current_fusion()
            self._refresh_search_panel_state()
        try:
            plan = build_compose_search_plan(
                query=query,
                source_image_paths=paths,
                fusion=effective_fusion,
            )
        except Exception as exc:
            self.show_error_dialog(self.texts["search_failed"], exc)
            return False

        scope_video_paths, scope_library_paths = resolve_default_active_search_scope()
        # Compose keeps only frame/chunk granularity — no deep search / video discovery.
        if hasattr(self, "_text_search_mode_from_ui"):
            compose_mode = self._text_search_mode_from_ui()
        else:
            compose_mode = "frame"
        self.search_controller.start_search(
            plan["query_data"],
            plan["is_text"],
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            query_vector=plan["query_vector"],
            search_mode=compose_mode,
            top_k=plan.get("top_k"),
            min_score=plan.get("min_score"),
            search_precision_mode="fast",
            pixel_query_data=plan.get("pixel_query_data"),
            video_discovery_enabled=False,
        )
        return True

    def _ensure_mobile_search_ready(self) -> bool:
        if not self._ensure_startup_migration_idle("feature_search"):
            return False
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return False
        return True

    def _apply_mobile_search_modes(self, data: dict) -> None:
        """Sync desktop search mode widgets from a mobile request before running search."""
        image_mode = str(data.get("image_search_mode") or "").strip().lower()
        if image_mode and hasattr(self, "_set_image_search_mode_ui"):
            self._set_image_search_mode_ui(image_mode)
            if hasattr(self, "_save_image_search_mode"):
                self._save_image_search_mode()
        text_mode = str(data.get("search_mode") or "").strip().lower()
        if text_mode in {"frame", "chunk"} and hasattr(self.search_page, "search_mode"):
            combo = self.search_page.search_mode
            index = combo.findData(text_mode)
            if index >= 0 and combo.currentIndex() != index:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
                if hasattr(self, "_save_search_mode"):
                    self._save_search_mode()
        dialogue_mode = str(data.get("dialogue_search_mode") or "").strip().lower()
        if dialogue_mode in {"exact", "fuzzy", "tolerant", "approx"}:
            combo = getattr(self.search_page, "dialogue_search_mode", None)
            if combo is not None:
                target = "fuzzy" if dialogue_mode in {"fuzzy", "tolerant", "approx"} else "exact"
                index = combo.findData(target)
                if index >= 0 and combo.currentIndex() != index:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(index)
                    combo.blockSignals(False)

    def _handle_mobile_search_requested(self, payload):
        data = dict(payload or {})
        kind = str(data.get("search_kind") or "image").strip().lower()
        # Subtitle search uses the OCR transcript store and does not need CLIP.
        if kind == "dialogue":
            if not self._ensure_startup_migration_idle("feature_search"):
                return
            self._apply_mobile_search_modes(data)
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_received"])
            self._run_dialogue_search(str(data.get("query") or ""), sync_ui=True)
            return
        if not self._ensure_mobile_search_ready():
            return
        self._apply_mobile_search_modes(data)
        self.search_page.lbl_status.setText(self.texts["mobile_bridge_received"])
        if kind == "text":
            self._run_text_search(str(data.get("query") or ""), sync_ui=True)
            return
        if kind == "compose":
            image_paths = [str(path or "").strip() for path in (data.get("image_paths") or []) if str(path or "").strip()]
            if not image_paths:
                single = str(data.get("image_path") or "").strip()
                if single:
                    image_paths = [single]
            self._run_compose_search_with_inputs(
                str(data.get("query") or ""),
                image_paths,
                data.get("fusion"),
                sync_ui=True,
            )
            return
        image_paths = [str(path or "").strip() for path in (data.get("image_paths") or []) if str(path or "").strip()]
        image_path = image_paths[0] if image_paths else str(data.get("image_path") or "").strip()
        self._run_image_search(image_path, sync_ui=True)

    def _start_compose_search(self):
        compose_form = self.search_page.search_panel.compose_form
        if not compose_form.has_content():
            self.search_page.lbl_status.setText(
                self.texts.get("search_compose_empty", self.texts["empty_query"])
            )
            return
        try:
            query = compose_form.normalized_query()
        except ValueError:
            self.search_page.lbl_status.setText(self.texts["query_too_short"])
            return
        self.switch_page("search")
        self._run_compose_search_with_inputs(
            query,
            compose_form.image_paths(),
            compose_form.current_fusion(),
            sync_ui=False,
        )

    def save_compose_as_preset(self):
        from PySide6.QtWidgets import QInputDialog

        from src.services.search_preset_service import create_preset

        if self._search_active_tab() != self.SEARCH_TAB_COMPOSE:
            return
        compose_form = self.search_page.search_panel.compose_form
        if not compose_form.has_content():
            self.search_page.lbl_status.setText(
                self.texts.get("search_presets_save_empty", self.texts["empty_query"])
            )
            return
        try:
            query = compose_form.normalized_query()
        except ValueError:
            self.search_page.lbl_status.setText(self.texts["query_too_short"])
            return
        image_paths = compose_form.image_paths()
        if not query and not image_paths:
            self.search_page.lbl_status.setText(
                self.texts.get("search_presets_save_empty", self.texts["empty_query"])
            )
            return

        default_name = query[:24] if query else self.texts.get("search_presets_default_image_name", "Preset")
        if not default_name:
            default_name = self.texts.get("search_compose_default_name", "组合搜索")
        name, ok = QInputDialog.getText(
            self,
            self.texts.get("search_compose_save_name_title", self.texts.get("search_presets_save_title", "")),
            self.texts.get("search_presets_save_prompt", "Preset name"),
            text=default_name,
        )
        if not ok:
            return
        name = str(name or "").strip()
        if not name:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("search_presets_name_required", ""),
                kind="warning",
            )
            return
        try:
            payload = {
                "name": name,
                "query": query,
                "source_image_paths": list(image_paths),
            }
            fusion = compose_form.current_fusion()
            if fusion is not None:
                payload["fusion"] = fusion
            create_preset(**payload)
        except Exception as exc:
            self.show_error_dialog(self.texts.get("search_presets_save_failed", ""), exc)
            return
        self.refresh_search_presets_ui()
        self.search_page.lbl_status.setText(self.texts.get("search_presets_save_done", ""))

    def start_in_video_deep_search(
        self,
        video_path: str,
        preview_sec: float | None = None,
        anchor_score: float | None = None,
    ):
        """Re-run image search inside one video with deep (moment) pipeline."""
        if not self._ensure_startup_migration_idle("feature_search"):
            return
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        image_path = str(getattr(self, "current_img_path", "") or "").strip()
        if not image_path:
            self.search_page.lbl_status.setText(self.texts.get("search_in_video_requires_image", ""))
            return
        target = str(video_path or "").strip()
        if not target:
            return
        if self.search_controller.is_search_running():
            self.search_page.lbl_status.setText(self.texts.get("search_busy", self.texts["searching"]))
            return

        from src.services.search_service import compute_locate_score_margin

        coarse_results = list(getattr(self.search_controller, "_last_coarse_results", []) or [])
        score_margin = compute_locate_score_margin(anchor_score, coarse_results)

        self.switch_page("search")
        self.search_page.lbl_status.setText(self.texts.get("search_in_video_running", self.texts["searching"]))
        self.search_controller.start_search(
            image_path,
            False,
            scope_video_paths=[target],
            scope_library_paths=None,
            search_mode="frame",
            search_precision_mode="precise",
            preview_anchor_sec=preview_sec,
            locate_anchor_score=anchor_score,
            locate_score_margin=score_margin,
        )

    def toggle_mobile_bridge(self):
        try:
            url = self.mobile_bridge_controller.toggle()
        except Exception as exc:
            self.show_error_dialog(self.texts["mobile_bridge_start_failed"], exc)
            return

        if url:
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_running"])
            self.show_mobile_bridge_qr()
        else:
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_stopped"])
        self._update_mobile_bridge_controls()

    def show_mobile_bridge_qr(self):
        if not self.mobile_bridge_controller.is_running():
            return
        url = self.mobile_bridge_controller.get_access_url()
        MobileBridgeDialog(
            url=url,
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            qr_pixmap=build_qr_pixmap(url),
        ).exec()

    def _handle_mobile_bridge_status_changed(self, _state):
        self._update_mobile_bridge_controls()

    def _update_mobile_bridge_controls(self):
        is_running = hasattr(self, "mobile_bridge_controller") and self.mobile_bridge_controller.is_running()
        self.search_page.btn_mobile_toggle.blockSignals(True)
        self.search_page.btn_mobile_toggle.setChecked(is_running)
        self.search_page.btn_mobile_toggle.blockSignals(False)
        self.search_page.btn_mobile_toggle.setProperty("bridgeState", "on" if is_running else "off")
        self.search_page.btn_mobile_toggle.style().unpolish(self.search_page.btn_mobile_toggle)
        self.search_page.btn_mobile_toggle.style().polish(self.search_page.btn_mobile_toggle)
        self.search_page.btn_mobile_toggle.update()
        self.search_page.btn_mobile_toggle.setText(self._mobile_bridge_toggle_text(is_running))
        self.search_page.btn_mobile_toggle.setToolTip(
            self.texts["mobile_bridge_stop"] if is_running else self.texts["mobile_bridge_start"]
        )
        self.search_page.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        self.search_page.btn_mobile_qr.setProperty("qrState", "visible" if is_running else "hidden")
        self.search_page.btn_mobile_qr.setEnabled(is_running)
        self.search_page.btn_mobile_qr.style().unpolish(self.search_page.btn_mobile_qr)
        self.search_page.btn_mobile_qr.style().polish(self.search_page.btn_mobile_qr)
        self.search_page.btn_mobile_qr.update()

    def _mobile_bridge_toggle_text(self, is_running, texts=None):
        t = texts or self.texts
        return t.get("mobile_bridge_toggle_on" if is_running else "mobile_bridge_toggle_off", "ON" if is_running else "OFF")

    def _save_search_mode(self):
        try:
            config = load_config()
            search_mode = str(self.search_page.search_mode.currentData() or DEFAULT_CONFIG["search_mode"])
            config["search_mode"] = search_mode
            save_config(config)
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _save_image_search_mode(self):
        try:
            config = load_config()
            image_mode = str(
                self.search_page.image_search_mode.currentData() or DEFAULT_CONFIG["image_search_mode"]
            ).strip().lower()
            if image_mode not in self.IMAGE_SEARCH_MODES:
                image_mode = str(DEFAULT_CONFIG["image_search_mode"])
            config["image_search_mode"] = image_mode
            config["search_video_discovery_enabled"] = image_mode == "video_discovery"
            save_config(config)
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def clear_all_content(self):
        self.current_img_path = None
        self.search_page.search_panel.clear_text_query()
        self.search_page.search_panel.clear_dialogue_query()
        self.search_page.search_panel.compose_form.clear()
        self.search_page.img_label.clear()
        self.search_page.img_label.setText(self.texts["image_drop_hint"])
        self.search_controller.clear_results()
        self.preview_controller.stop_preview()
        self._update_expand_preview_button()
        try:
            self._refresh_search_panel_state()
        except Exception:
            # Safe after removing all CLIP models (fallback profile may have empty asset dirs).
            pass
        self.search_page.lbl_status.setText(self.texts["ready"])

    def open_result_in_explorer(self, path):
        open_in_explorer(path)

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.texts["select_image"], "", self.texts["image_filter"])
        if path:
            self._set_image_query(path, clear_text=True)

    def apply_theme(self):
        style = DARK_STYLE if self.is_dark_mode else LIGHT_STYLE
        app = QApplication.instance()
        if app:
            app.setProperty("videoseek_is_dark", self.is_dark_mode)
            app.setStyleSheet(style)
        self.update()
        self.sidebar.btn_theme.setText("☀" if self.is_dark_mode else "🌙")
        self._refresh_sidebar_icon_buttons()

    def toggle_theme(self):
        self.is_dark_mode = not self.is_dark_mode
        self.apply_theme()
        config = load_config()
        config["theme"] = "dark" if self.is_dark_mode else "light"
        save_config(config)

    def toggle_language(self):
        self.language = "en" if self.language == "zh" else "zh"
        config = load_config()
        config["language"] = self.language
        save_config(config)
        self.version_info = get_local_version_status(self.language)
        self.notice_payload = get_local_notice_payload(self.language)
        self.about_payload = get_local_about_payload(self.language)
        self.apply_texts()
        self.load_settings_values()
        self.apply_theme()
        self.app_meta_controller.refresh(self.language)

    def show_error_dialog(self, message, exc=None):
        detail = self.texts["generic_detail"].format(detail=str(exc)) if exc else ""
        text = f"{message}\n\n{detail}".strip()
        AppMessageDialog(
            self.texts["error_title"],
            text,
            kind="error",
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
        ).exec()

    def show_info_dialog(self, title, text, kind="info"):
        AppMessageDialog(
            title,
            text,
            kind=kind,
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
        ).exec()

    def show_confirm_dialog(self, title, text, kind="warning"):
        dialog = AppMessageDialog(
            title,
            text,
            kind=kind,
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            confirm=True,
        )
        dialog.exec()
        return dialog.confirmed()

    def _show_startup_migration_notice(self):
        parts = []
        config_notice = pop_migration_notice()
        if config_notice:
            parts.append(
                self.texts["migration_notice_body"].format(
                    config_file=config_notice["config_file"],
                    data_dir=config_notice["data_dir"],
                )
            )

        summary = pop_startup_migration_summary()
        summary_text = self._build_startup_migration_summary_text(summary)
        if summary_text:
            parts.append(summary_text)

        if not parts:
            return

        if config_notice and summary_text:
            title = self.texts["migration_combined_title"]
        elif summary_text:
            title = self.texts["migration_summary_title"]
        else:
            title = self.texts["migration_notice_title"]
        self.show_info_dialog(title, "\n\n".join(parts), kind="info")

    def _build_startup_migration_summary_text(self, summary):
        if not isinstance(summary, dict):
            return ""

        lines = []
        schema_lines = []
        local_files = int(summary.get("migrated_local_asset_files", 0) or 0)
        local_payloads = int(summary.get("migrated_local_payloads", 0) or 0)
        global_payloads = int(summary.get("migrated_global_payloads", 0) or 0)
        remote_payloads = int(summary.get("migrated_remote_payloads", 0) or 0)
        if local_files > 0:
            schema_lines.append(
                self.texts["migration_summary_schema_local_files"].format(count=local_files)
            )
        if local_payloads > 0:
            schema_lines.append(
                self.texts["migration_summary_schema_local_payloads"].format(count=local_payloads)
            )
        if global_payloads > 0:
            schema_lines.append(
                self.texts["migration_summary_schema_global"].format(count=global_payloads)
            )
        if remote_payloads > 0:
            schema_lines.append(
                self.texts["migration_summary_schema_remote"].format(count=remote_payloads)
            )
        if schema_lines:
            lines.append(self.texts["migration_summary_schema_section"])
            lines.extend(schema_lines)

        video_lines = []
        migrated_video_ids = int(summary.get("migrated_video_ids", 0) or 0)
        failed_video_ids = int(summary.get("failed_video_ids", 0) or 0)
        if migrated_video_ids > 0:
            video_lines.append(
                self.texts["migration_summary_video_id_migrated"].format(count=migrated_video_ids)
            )
        if failed_video_ids > 0:
            video_lines.append(
                self.texts["migration_summary_video_id_failed"].format(count=failed_video_ids)
            )
        if summary.get("pending_legacy"):
            video_lines.append(self.texts["migration_summary_video_id_pending"])
        if video_lines:
            lines.append(self.texts["migration_summary_video_id_section"])
            lines.extend(video_lines)

        if summary.get("search_index_upgraded"):
            if int(summary.get("lance_videos_imported", 0) or 0) > 0 or int(
                summary.get("lance_legacy_removed", 0) or 0
            ) > 0:
                lines.append(self.texts["migration_summary_lance_section"])
                imported = int(summary.get("lance_videos_imported", 0) or 0)
                if imported > 0:
                    lines.append(
                        self.texts["migration_summary_lance_imported"].format(count=imported)
                    )
                removed = int(summary.get("lance_legacy_removed", 0) or 0)
                if removed > 0:
                    lines.append(
                        self.texts["migration_summary_lance_legacy_removed"].format(count=removed)
                    )
                failed = int(summary.get("lance_videos_failed", 0) or 0)
                if failed > 0:
                    lines.append(
                        self.texts["migration_summary_lance_import_failed"].format(count=failed)
                    )
            else:
                lines.append(self.texts["migration_summary_search_index_section"])
                lines.append(
                    self.texts["migration_summary_search_index_built"].format(
                        count=int(summary.get("search_index_libraries_built", 0) or 0),
                    )
                )
                if summary.get("search_index_global_built"):
                    lines.append(self.texts["migration_summary_search_index_global"])

        backup_dir = str(summary.get("backup_dir", "") or "").strip()
        if backup_dir:
            lines.append(self.texts["migration_summary_backup"].format(path=backup_dir))

        if not lines:
            return ""
        return self.texts["migration_summary_intro"] + "\n\n" + "\n".join(lines)

    def _prompt_resume_partial_indexing(self):
        partial_libraries = list_partial_libraries(include_offline=False)
        if not partial_libraries or self.indexing_controller.is_running():
            return

        if len(partial_libraries) == 1:
            message = self.texts["partial_resume_body_single"].format(library=partial_libraries[0])
        else:
            message = self.texts["partial_resume_body_multi"].format(count=len(partial_libraries))

        if not self.show_confirm_dialog(
            self.texts["partial_resume_title"],
            message,
            kind="warning",
        ):
            return

        self.switch_page("library")
        self.library_page.lbl_status.setText(self.texts["partial_resume_status"])
        self.start_update_index()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            dropped_path = urls[0].toLocalFile()
            if self.pages.currentIndex() == self._nav_page_index("link"):
                if dropped_path.lower().endswith(".txt"):
                    try:
                        with open(dropped_path, "r", encoding="utf-8", errors="ignore") as handle:
                            content = handle.read().strip()
                        if content:
                            existing = self.link_page.links_input.toPlainText().strip()
                            merged = f"{existing}\n{content}".strip() if existing else content
                            self.link_page.links_input.setPlainText(merged)
                    except OSError:
                        pass
                return
            self.upload_file_path(dropped_path)

    def upload_file_path(self, path):
        if self._search_active_tab() == self.SEARCH_TAB_COMPOSE:
            self.search_page.search_panel.compose_form.add_image(path)
            self.switch_page("search")
            self._set_search_query_tab(self.SEARCH_TAB_COMPOSE)
            self._refresh_search_panel_state()
            return
        self._set_image_query(path, clear_text=False)
        self.switch_page("search")

    def closeEvent(self, event):
        if self._preview_export_active or self._preview_export_queue:
            cancelled = self._cancel_all_preview_exports()
            if not cancelled:
                self.search_page.lbl_status.setText(
                    self.texts.get("preview_dialog_export_running", "Clip export is still running. Please wait.")
                )
                event.ignore()
                return
        if (
            (
                self.indexing_controller.is_running()
                or (
                    getattr(self, "understanding_controller", None)
                    and self.understanding_controller.is_running()
                )
            )
            and not self._force_application_quit
        ):
            if self._handle_indexing_window_close(event):
                return
        if self._try_minimize_to_tray_on_close(event):
            return
        self._shutdown_application(event)

    def _set_image_query(self, path, clear_text):
        from src.core.image_io import pixmap_from_image_path

        self._set_search_query_tab(self.SEARCH_TAB_IMAGE)
        self.current_img_path = path
        pixmap = pixmap_from_image_path(path, 420, 280)
        if pixmap.isNull():
            self.search_page.lbl_status.setText(self.texts["image_load_failed"])
            return
        self.search_page.img_label.setPixmap(pixmap)
        if clear_text:
            self.search_page.search_panel.clear_text_query()
        self.search_page.lbl_status.setText(self.texts["image_loaded"])
        self._refresh_search_panel_state()
