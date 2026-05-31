from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
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
)
from ui.widgets.settings import SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, MobileBridgeDialog, NoticeDialog
from ui.controllers.indexing_controller import IndexingController
from ui.widgets.layout import WINDOW_SIZES, apply_window_size
from ui.controllers.agent_api_controller import AgentApiController
from ui.controllers.mobile_bridge_controller import MobileBridgeController
from ui.controllers.network_search_controller import NetworkSearchController
from ui.controllers.preview_controller import PreviewController
from ui.controllers.runtime_resource_controller import RuntimeResourceController
from ui.controllers.search_controller import SearchController
from ui.widgets.styles import DARK_STYLE, LIGHT_STYLE
from ui.windows.gui_settings import SettingsGuiMixin
from ui.windows.gui_preview import PreviewGuiMixin
from ui.windows.gui_library_indexing import LibraryIndexingGuiMixin
from ui.windows.gui_vector_network import VectorNetworkGuiMixin
from ui.windows.gui_runtime import RuntimeGuiMixin
from ui.windows.gui_model_packages import ModelPackagesGuiMixin
from ui.windows.gui_ui_state import AppUiStateMixin
from ui.windows.gui_tray import TrayGuiMixin
from ui.windows.gui_startup_migration import StartupMigrationGuiMixin
from ui.windows.gui_search_scope import SearchScopeGuiMixin
from ui.windows.gui_search_presets import SearchPresetsGuiMixin
from ui.windows.gui_search_panel_state import SearchPanelStateMixin


class MainWindow(
    QMainWindow,
    StartupMigrationGuiMixin,
    TrayGuiMixin,
    SettingsGuiMixin,
    PreviewGuiMixin,
    LibraryIndexingGuiMixin,
    VectorNetworkGuiMixin,
    RuntimeGuiMixin,
    AppUiStateMixin,
    ModelPackagesGuiMixin,
    SearchScopeGuiMixin,
    SearchPresetsGuiMixin,
    SearchPanelStateMixin,
):
    """Sidebar / stacked widget order: local search → library → remote link → settings."""

    _NAV_PAGE_ORDER = ("search", "library", "link", "settings")

    def __init__(self):
        super().__init__()
        self._init_startup_migration_state()
        self.startup_cancelled = False
        self._close_when_indexing_stops = False
        self.current_img_path = None
        self.network_query_img_path = None
        self.version_info = None
        self.notice_payload = None
        self.about_payload = None
        self._startup_complete = False
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
        self.preview_controller = PreviewController(self)
        self.search_controller = SearchController(self)
        self.network_search_controller = NetworkSearchController(self)
        self._init_search_presets_ui()
        self.mobile_bridge_controller = MobileBridgeController(self)
        self.mobile_bridge_controller.upload_received.connect(self._handle_mobile_upload_received)
        self.mobile_bridge_controller.status_changed.connect(self._handle_mobile_bridge_status_changed)
        self.agent_api_controller = AgentApiController(self)
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
        self.settings_page = SettingsPage()
        self.pages.addWidget(self._build_scroll_page(self.search_page))
        self.pages.addWidget(self._build_scroll_page(self.library_page))
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
        self.search_page.preview_host.mouseDoubleClickEvent = self.open_current_preview_dialog
        self.search_page.preview_host_layout.addWidget(self.video_widget, 1)

        self.result_table = self.search_page.result_table

        self.sidebar.btn_page_search.clicked.connect(lambda: self.switch_page("search"))
        self.sidebar.btn_page_link.clicked.connect(lambda: self.switch_page("link"))
        self.sidebar.btn_page_library.clicked.connect(lambda: self.switch_page("library"))
        self.sidebar.btn_page_settings.clicked.connect(lambda: self.switch_page("settings"))
        self.sidebar.btn_theme.clicked.connect(self.toggle_theme)
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
        self.search_page.search_precision_toggle.toggled.connect(self._on_search_precision_toggled)
        self.search_page.text_search.textChanged.connect(self._refresh_search_panel_state)
        self.search_page.search_query_tabs.currentChanged.connect(self._on_search_query_tab_changed)
        self.search_page.img_label.mousePressEvent = lambda e: self.upload_file()
        self._init_search_scope_state()
        self.link_page.query_image_label.mousePressEvent = lambda e: self.upload_network_query_image()
        self.link_page.btn_build.clicked.connect(self.start_network_build)
        self.link_page.btn_import.clicked.connect(self.import_network_library)
        self.link_page.btn_export.clicked.connect(self.export_network_library)
        self.link_page.btn_run.clicked.connect(self.start_network_search)
        self.link_page.btn_clear.clicked.connect(self.clear_link_search_content)
        self.link_page.btn_link_details.clicked.connect(self.show_network_link_details)
        self.link_page.btn_open_cache.clicked.connect(self.open_network_download_cache_folder)

        self.library_page.btn_add_lib.clicked.connect(self.select_video_folder)
        self.library_page.btn_sync_db.clicked.connect(self.start_update_index)
        self.library_page.btn_rebuild_index_vectors.clicked.connect(self.rebuild_index_from_vectors)
        self.library_page.btn_stop_index.clicked.connect(self.stop_update_index)
        self.library_page.btn_index_issues.clicked.connect(self.show_last_index_issue_details)
        self.library_page.btn_cleanup_missing.clicked.connect(self.cleanup_missing_library_vectors)
        self.library_page.btn_vector_details.clicked.connect(self.show_local_vector_details)
        self.library_page.btn_debug_gpu_oom.clicked.connect(self.start_debug_gpu_oom)
        self.library_page.btn_debug_system_oom.clicked.connect(self.start_debug_system_oom)

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
        self.settings_page.btn_cleanup_old_data_root.clicked.connect(self.cleanup_old_data_root)
        self.settings_page.btn_cleanup_old_model_dir.clicked.connect(self.cleanup_old_model_dir)
        self.settings_page.btn_copy_agent_api_url.clicked.connect(self.copy_agent_api_url)
        self.settings_page.btn_copy_agent_starter.clicked.connect(self.copy_agent_starter)

        self.setAcceptDrops(True)
        for page in (self.search_page, self.link_page, self.library_page, self.settings_page):
            page.header.runtime_banner_action.clicked.connect(self.open_runtime_resource_dialog)

    def _build_scroll_page(self, page_widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page_widget)
        return scroll

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

    def _update_version_info(self, version_info):
        self.version_info = version_info
        self.apply_texts()

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
        self.sidebar.hero_tag.setText(t["hero_tag"])
        self.sidebar.hero_title.setText(t["hero_title"])
        self.sidebar.hero_body.setText(t["hero_body"])
        self.sidebar.btn_page_search.setText(t["nav_search"])
        self.sidebar.btn_page_link.setText(t["nav_link"])
        self.sidebar.btn_page_library.setText(t["nav_library"])
        self.sidebar.btn_page_settings.setText(t["nav_settings"])
        self.sidebar.btn_notice.setText(t["notice_short"])
        if self.version_info and self.version_info.get("has_update"):
            self.sidebar.btn_about.setText(t["about_short_update"])
            self.sidebar.btn_about.setObjectName("UpdateButton")
        else:
            self.sidebar.btn_about.setText(t["about_short"])
            self.sidebar.btn_about.setObjectName("SidebarFooterButton")
        self.sidebar.btn_about.style().unpolish(self.sidebar.btn_about)
        self.sidebar.btn_about.style().polish(self.sidebar.btn_about)
        self.sidebar.btn_about.update()
        self.sidebar.btn_language.setText(t["language_toggle"])
        self.sidebar.btn_theme.setText(t["theme_light"] if self.is_dark_mode else t["theme_dark"])
        self.sidebar.runtime_hint.hide()
        self.sidebar.runtime_hint.setToolTip("")

        self.search_page.header.title.setText(t["search_page_title"])
        self.search_page.header.subtitle.setText(t["search_page_desc"])
        current_mode = self.search_page.search_mode.currentData()
        self.search_page.search_mode_label.setText(t["setting_search_mode"])
        self.search_page.search_mode.blockSignals(True)
        self.search_page.search_mode.clear()
        self.search_page.search_mode.addItem(t["setting_search_mode_frame"], "frame")
        self.search_page.search_mode.addItem(t["setting_search_mode_chunk"], "chunk")
        self.search_page.search_mode.setCurrentIndex(1 if current_mode == "chunk" else 0)
        self.search_page.search_mode.blockSignals(False)
        self.search_page.search_precision_label.setText(t["search_precision_label"])
        self.search_page.indexing_notice_text.setText(t.get("search_during_indexing_hint", ""))
        self._refresh_search_panel_state()
        self.search_page.preview_title.setText(t["preview_panel"])
        self.search_page.btn_expand_preview.setText(t.get("preview_expand", "放大预览"))
        self.search_page.results_title.setText(t["results_panel"])
        self.search_page.btn_export_tasks.setText(t.get("preview_export_tasks", "Export Tasks"))
        self._update_expand_preview_button()
        self.search_page.text_search.setPlaceholderText(t["search_placeholder"])
        self.search_page.mobile_toggle_label.setText(t.get("mobile_bridge_toggle_label", t["mobile_bridge_start"]))
        self.search_page.btn_mobile_toggle.setText(self._mobile_bridge_toggle_text(self.mobile_bridge_controller.is_running(), texts=t))
        self.search_page.btn_mobile_toggle.setToolTip(
            t["mobile_bridge_stop"] if self.mobile_bridge_controller.is_running() else t["mobile_bridge_start"]
        )
        self.search_page.btn_mobile_toggle.setChecked(self.mobile_bridge_controller.is_running())
        self.search_page.btn_mobile_qr.setText(t["mobile_bridge_qr"])
        self.search_page.btn_mobile_qr.setEnabled(self.mobile_bridge_controller.is_running())
        self.search_page.btn_search.setText(t["search"])
        self.search_page.btn_clear.setText(t["clear"])
        self.search_page.search_scope_label.setText(t.get("search_scope_label", ""))
        self.search_page.preview_placeholder.setText(t["preview_placeholder"])
        self.result_table.apply_header_labels(t)
        self.search_page.result_view.set_empty_message(t["no_results"])

        self.link_page.header.title.setText(t["link_page_title"])
        self.link_page.header.subtitle.setText(t["link_page_desc"])
        self.link_page.notice_body.setText(t["network_notice_body"])
        self.link_page.build_title.setText(t.get("network_build_section_title", t["controls_label"]))
        self.link_page.build_hint.setText(t.get("network_build_section_hint", t["controls_hint"]))
        self.link_page.search_title.setText(t.get("network_search_section_title", t["link_controls_label"]))
        self.link_page.search_hint.setText(t.get("network_search_section_hint", t["link_controls_hint"]))
        self.link_page.mode_label.show()
        self.link_page.mode_combo.show()
        self.link_page.mode_label.setText(t["network_build_mode"])
        self.link_page.mode_combo.blockSignals(True)
        self.link_page.mode_combo.clear()
        self.link_page.mode_combo.addItem(t["link_mode_download"], "download")
        self.link_page.mode_combo.addItem(t["link_mode_stream"], "stream")
        self.link_page.mode_combo.blockSignals(False)
        self.link_page.build_links_input.setPlaceholderText(t["network_link_editor_placeholder"])
        self.link_page.input_link.setPlaceholderText(t["link_input_placeholder"])
        self.link_page.query_image_label.setText(t["network_image_preview_hint"])
        self.link_page.btn_build.setText(t["network_build"])
        self.link_page.btn_import.setText(t["network_import"])
        self.link_page.btn_export.setText(t["network_export"])
        self.link_page.btn_link_details.setText(t["network_links_detail"])
        self.link_page.btn_open_cache.setText(t["network_open_cache"])
        self.link_page.btn_run.setText(t["link_run"])
        self.link_page.btn_clear.setText(t["clear"])
        self.link_page.results_title.setText(t["link_results_panel"])
        self.link_page.result_table.apply_header_labels(t)
        self.link_page.result_view.set_empty_message(t["no_results"])

        self.library_page.header.title.setText(t["library_page_title"])
        self.library_page.header.subtitle.setText(t["library_page_desc"])
        self.library_page.table_title.setText(t["library_table_title"])
        self.library_page.btn_add_lib.setText(t["add_folder"])
        self.library_page.btn_sync_db.setText(t["update_index"])
        self.library_page.btn_rebuild_index_vectors.setText(t["rebuild_index_vectors"])
        self.library_page.btn_stop_index.setText(t["stop"])
        self.library_page.btn_index_issues.setText(t["index_issues_button"])
        self.library_page.btn_cleanup_missing.setText(t["cleanup_missing_vectors"])
        self.library_page.btn_vector_details.setText(t["library_vectors_detail"])
        self.library_page.btn_debug_gpu_oom.setText(t["debug_gpu_oom"])
        self.library_page.btn_debug_system_oom.setText(t["debug_system_oom"])
        self.library_page.btn_debug_gpu_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self.library_page.btn_debug_system_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self._apply_index_issue_button_state(bool(self._last_index_issues))

        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.setText(t["settings_page_desc"])
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        if hasattr(self, "_rebuild_tray_menu"):
            self._rebuild_tray_menu()
        self.push_inference_status()
        self._refresh_pending_cleanup_actions(config)

        if not self.current_img_path and not self.search_page.img_label.pixmap():
            self.search_page.img_label.setText(t["image_drop_hint"])

        self.search_page.lbl_status.setText(t["ready"])
        self.link_page.lbl_build_status.setText(t["ready"])
        self.link_page.lbl_search_status.setText(t["ready"])
        self.library_page.lbl_status.setText(t["ready"])
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
        self.refresh_library_table()
        self.refresh_search_presets_ui()
        self._prompt_resume_partial_indexing()
        self.app_meta_controller.refresh(self.language)
        self._apply_agent_api_settings()

    def show_notice(self):
        NoticeDialog(self, self.is_dark_mode, self.language, notice=self.notice_payload).exec()

    def show_about(self):
        AboutDialog(
            self,
            self.is_dark_mode,
            self.language,
            version_info=self.version_info,
            about=self.about_payload,
        ).exec()

    def start_search(self):
        if not self._ensure_startup_migration_idle("feature_search"):
            return
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return

        active_tab = self._search_active_tab()
        if active_tab == self.SEARCH_TAB_COMPOSE:
            self._start_compose_search()
            return

        text_query = self.search_page.search_panel.text_query()
        if active_tab == self.SEARCH_TAB_TEXT:
            if not text_query:
                self.search_page.lbl_status.setText(self.texts.get("search_empty_text", self.texts["empty_query"]))
                return
            query_info = prepare_text_query(text_query)
            if query_info["too_short"]:
                self.search_page.lbl_status.setText(self.texts["query_too_short"])
                return
            if query_info["changed"]:
                self.search_page.search_panel.set_text_query(query_info["normalized"])
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query = query_info["normalized"]
            is_text = True
            has_image = False
        else:
            query = self.current_img_path
            if not query:
                self.search_page.lbl_status.setText(self.texts.get("search_empty_image", self.texts["empty_query"]))
                return
            is_text = False
            has_image = True
        if not query:
            self.search_page.lbl_status.setText(self.texts["empty_query"])
            return
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return

        self.switch_page("search")
        from src.services.search_scope import resolve_default_active_search_scope

        scope_video_paths, scope_library_paths = resolve_default_active_search_scope()
        # Manual search uses text when both are present; image-only path when text is empty.
        search_precision_mode = self._resolve_search_precision_mode(
            is_text=is_text,
            has_image=has_image,
        )
        self.search_controller.start_search(
            query,
            is_text,
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            search_precision_mode=search_precision_mode,
        )

    def _start_compose_search(self):
        from src.services.search_preset_service import build_compose_search_plan
        from src.services.search_scope import resolve_active_search_mode, resolve_default_active_search_scope

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
        image_paths = compose_form.image_paths()
        if not query and not image_paths:
            self.search_page.lbl_status.setText(
                self.texts.get("search_compose_empty", self.texts["empty_query"])
            )
            return
        if query:
            query_info = prepare_text_query(query)
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query = str(query_info["normalized"] or query).strip()
            if query_info["changed"]:
                compose_form.input_description.setPlainText(query)
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return

        self.switch_page("search")
        try:
            plan = build_compose_search_plan(
                query=query,
                source_image_paths=image_paths,
                fusion=compose_form.current_fusion(),
            )
        except Exception as exc:
            self.show_error_dialog(self.texts["search_failed"], exc)
            return

        scope_video_paths, scope_library_paths = resolve_default_active_search_scope()
        search_precision_mode = self._resolve_search_precision_mode(
            is_text=bool(plan["is_text"]),
            has_image=bool(plan["has_image"]),
        )
        self.search_controller.start_search(
            plan["query_data"],
            plan["is_text"],
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            query_vector=plan["query_vector"],
            search_mode=resolve_active_search_mode(),
            top_k=plan.get("top_k"),
            min_score=plan.get("min_score"),
            search_precision_mode=search_precision_mode,
            pixel_query_data=plan.get("pixel_query_data"),
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

    def start_in_video_deep_search(self, video_path: str, preview_sec: float | None = None):
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

        self.switch_page("search")
        self._set_search_precision_mode_ui("precise")
        self.search_page.lbl_status.setText(self.texts.get("search_in_video_running", self.texts["searching"]))
        self.search_controller.start_search(
            image_path,
            False,
            scope_video_paths=[target],
            scope_library_paths=None,
            search_precision_mode="precise",
            preview_anchor_sec=preview_sec,
        )

    def toggle_mobile_bridge(self):
        try:
            url = self.mobile_bridge_controller.toggle()
        except Exception as exc:
            self.show_error_dialog(self.texts["mobile_bridge_start_failed"], exc)
            return

        if url:
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_running"].format(url=url))
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

    def _handle_mobile_upload_received(self, path, _source):
        self.switch_page("search")
        if self._search_active_tab() == self.SEARCH_TAB_COMPOSE:
            self.search_page.search_panel.compose_form.add_image(path)
            self.search_page.lbl_status.setText(self.texts["mobile_bridge_received"])
            self._refresh_search_panel_state()
            return
        self._set_image_query(path, clear_text=True)
        self.search_page.lbl_status.setText(self.texts["mobile_bridge_received"])
        self.start_search()

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
        self.search_page.btn_mobile_qr.setObjectName("MobileBridgeQrButton")
        self.search_page.btn_mobile_qr.style().unpolish(self.search_page.btn_mobile_qr)
        self.search_page.btn_mobile_qr.style().polish(self.search_page.btn_mobile_qr)
        self.search_page.btn_mobile_qr.update()
        self.search_page.btn_mobile_toggle.setText(self._mobile_bridge_toggle_text(is_running))
        self.search_page.btn_mobile_toggle.setToolTip(
            self.texts["mobile_bridge_stop"] if is_running else self.texts["mobile_bridge_start"]
        )
        self.search_page.btn_mobile_qr.setEnabled(is_running)

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

    def clear_all_content(self):
        self.current_img_path = None
        self.search_page.search_panel.clear_text_query()
        self.search_page.search_panel.compose_form.clear()
        self.search_page.img_label.clear()
        self.search_page.img_label.setText(self.texts["image_drop_hint"])
        self.search_controller.clear_results()
        self.preview_controller.stop_preview()
        self._update_expand_preview_button()
        self._refresh_search_panel_state()
        self.search_page.lbl_status.setText(self.texts["ready"])

    def clear_link_search_content(self):
        if hasattr(self, "network_search_controller"):
            self.network_search_controller.clear()
            return
        self.link_page.input_link.clear()
        self.network_query_img_path = None
        self.link_page.query_image_label.clear()
        self.link_page.query_image_label.setText(self.texts["network_image_preview_hint"])
        self.link_page.progress_bar.setValue(0)
        self.link_page.result_table.setRowCount(0)
        self.link_page.lbl_build_status.setText(self.texts["ready"])
        self.link_page.lbl_search_status.setText(self.texts["ready"])

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
        self.sidebar.btn_theme.setText(self.texts["theme_light"] if self.is_dark_mode else self.texts["theme_dark"])

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
                self.upload_network_file_path(dropped_path)
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
        if self.indexing_controller.is_running() and not self._force_application_quit:
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
