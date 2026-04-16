import os
import re
import time
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, \
    QVBoxLayout, QWidget, QHBoxLayout, QAbstractItemView

from src.app.config import DEFAULT_CONFIG, get_app_version, load_config, pop_migration_notice, save_config
from src.app.i18n import get_texts
from src.core.clip_embedding import get_engine_runtime_status, reset_engine
from src.services.about_service import get_local_about_payload
from src.services.library_service import (
    add_library,
    list_libraries,
    list_local_vector_details,
    list_partial_libraries,
    remove_library as remove_library_entry,
)
from src.services.notice_service import get_local_notice_payload
from src.services.indexing_service import list_missing_library_files
from src.services.query_text_service import prepare_text_query
from src.services.remote_library_service import list_remote_link_details
from src.services.remote_link_precheck_service import precheck_remote_links
from src.workflows.update_video import delete_physical_video_data
from src.utils import (
    get_app_data_dir,
    get_ffmpeg_status_text,
    get_configured_model_dir,
    load_meta,
    normalize_sampling_fps_mode,
    normalize_sampling_fps_rules_text,
    open_folder_in_explorer,
    open_in_explorer,
    parse_sampling_fps_rules,
    resolve_sampling_fps,
    validate_sampling_fps_rules,
    sync_ffmpeg_path_to_config,
    sync_model_dir_to_config,
)
from src.services.version_service import get_local_version_status
from ui.app_meta_controller import AppMetaController
from ui.components import LibraryPage, LinkSearchPage, NavigationSidebar, SearchPage, SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, NoticeDialog, ResourceTableDialog, SamplingRulesDialog
from ui.indexing_controller import IndexingController
from ui.layout import WINDOW_SIZES, apply_window_size
from ui.network_search_controller import NetworkSearchController
from ui.preview_dialog import PreviewDialog
from ui.preview_controller import PreviewController
from ui.runtime_resource_controller import RuntimeResourceController
from ui.search_controller import SearchController
from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.table_views import populate_library_table


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.startup_cancelled = False
        self._close_when_indexing_stops = False
        self.current_img_path = None
        self.network_query_img_path = None
        self.version_info = None
        self.notice_payload = None
        self.about_payload = None
        self.models_ready = True
        self._startup_complete = False
        self._preview_dialog_cooldown_until = 0.0
        self._preview_dialog_opening = False

        cfg = load_config()
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
        self.indexing_controller.finished.connect(self._finish_indexing)
        self.preview_controller = PreviewController(self)
        self.search_controller = SearchController(self)
        self.network_search_controller = NetworkSearchController(self)
        self.runtime_resource_controller = RuntimeResourceController(self)
        self.runtime_resource_controller.startup_cancelled.connect(self._handle_runtime_resource_exit)
        self.runtime_resource_controller.resources_ready.connect(self._finish_runtime_resource_download)
        self.runtime_resource_controller.status_changed.connect(self._apply_runtime_resource_status)
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.audio_output.setVolume(1.0)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        self.apply_texts()
        self.load_settings_values()
        self._show_startup_migration_notice()
        self.check_runtime_resources()
        if self.startup_cancelled:
            return
        self.apply_theme()
        QTimer.singleShot(0, self._finish_startup_sequence)

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
        self.pages.addWidget(self._build_scroll_page(self.link_page))
        self.pages.addWidget(self._build_scroll_page(self.library_page))
        self.pages.addWidget(self.settings_page)
        content_layout.addWidget(self.pages)
        main_layout.addWidget(self.content, 1)

        self.search_page.preview_placeholder.hide()
        self.video_widget = QVideoWidget()
        self.video_widget.setAttribute(Qt.WA_NativeWindow, True)
        self.video_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.search_page.preview_host.mouseDoubleClickEvent = self.open_current_preview_dialog
        self.search_page.preview_host_layout.addWidget(self.video_widget)

        self.result_table = self.search_page.result_table

        self.sidebar.btn_page_search.clicked.connect(lambda: self.switch_page("search"))
        self.sidebar.btn_page_link.clicked.connect(lambda: self.switch_page("link"))
        self.sidebar.btn_page_library.clicked.connect(lambda: self.switch_page("library"))
        self.sidebar.btn_page_settings.clicked.connect(lambda: self.switch_page("settings"))
        self.sidebar.btn_theme.clicked.connect(self.toggle_theme)
        self.sidebar.btn_language.clicked.connect(self.toggle_language)
        self.sidebar.btn_about.clicked.connect(self.show_about)
        self.sidebar.btn_notice.clicked.connect(self.show_notice)

        self.search_page.btn_browse.clicked.connect(self.upload_file)
        self.search_page.btn_search.clicked.connect(self.start_search)
        self.search_page.btn_clear.clicked.connect(self.clear_all_content)
        self.search_page.btn_expand_preview.clicked.connect(self.open_current_preview_dialog)
        self.search_page.search_mode.currentIndexChanged.connect(self._save_search_mode)
        self.search_page.img_label.mousePressEvent = lambda e: self.upload_file()
        self.link_page.query_image_label.mousePressEvent = lambda e: self.upload_network_query_image()
        self.link_page.btn_build.clicked.connect(self.start_network_build)
        self.link_page.btn_import.clicked.connect(self.import_network_library)
        self.link_page.btn_export.clicked.connect(self.export_network_library)
        self.link_page.btn_browse.clicked.connect(self.upload_network_query_image)
        self.link_page.btn_run.clicked.connect(self.start_network_search)
        self.link_page.btn_clear.clicked.connect(self.clear_link_search_content)
        self.link_page.btn_link_details.clicked.connect(self.show_network_link_details)
        self.link_page.btn_open_cache.clicked.connect(self.open_network_download_cache_folder)

        self.library_page.btn_add_lib.clicked.connect(self.select_video_folder)
        self.library_page.btn_sync_db.clicked.connect(self.start_update_index)
        self.library_page.btn_cleanup_missing.clicked.connect(self.cleanup_missing_library_vectors)
        self.library_page.btn_vector_details.clicked.connect(self.show_local_vector_details)

        self.settings_page.btn_save.clicked.connect(self.save_settings)
        self.settings_page.btn_reset.clicked.connect(self.reset_settings)
        self.settings_page.btn_edit_sampling_rules.clicked.connect(self._open_sampling_rules_dialog)

        self.setAcceptDrops(True)

    def _build_scroll_page(self, page_widget):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(page_widget)
        return scroll

    def switch_page(self, page_name):
        mapping = {"search": 0, "link": 1, "library": 2, "settings": 3}
        self.pages.setCurrentIndex(mapping[page_name])
        self.sidebar.set_current_page(page_name)

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
            self.sidebar.btn_about.setObjectName("SecondaryButton")
        self.sidebar.btn_about.style().unpolish(self.sidebar.btn_about)
        self.sidebar.btn_about.style().polish(self.sidebar.btn_about)
        self.sidebar.btn_about.update()
        self.sidebar.btn_language.setText(t["language_toggle"])
        self.sidebar.btn_theme.setText(t["theme_light"] if self.is_dark_mode else t["theme_dark"])
        self.sidebar.runtime_hint.hide()
        self.sidebar.runtime_hint.setToolTip("")

        self.search_page.header.title.setText(t["search_page_title"])
        self.search_page.header.subtitle.setText(t["search_page_desc"])
        self.search_page.controls_title.setText(t["controls_label"])
        self.search_page.controls_hint.setText(t["controls_hint"])
        current_mode = self.search_page.search_mode.currentData()
        self.search_page.search_mode_label.setText(t["setting_search_mode"])
        self.search_page.search_mode.blockSignals(True)
        self.search_page.search_mode.clear()
        self.search_page.search_mode.addItem(t["setting_search_mode_frame"], "frame")
        self.search_page.search_mode.addItem(t["setting_search_mode_chunk"], "chunk")
        self.search_page.search_mode.setCurrentIndex(1 if current_mode == "chunk" else 0)
        self.search_page.search_mode.blockSignals(False)
        self.search_page.session_title.setText(t["workspace_label"])
        self.search_page.session_hint.setText(t["workspace_hint"])
        self.search_page.preview_title.setText(t["preview_panel"])
        self.search_page.btn_expand_preview.setText(t.get("preview_expand", "放大预览"))
        self.search_page.results_title.setText(t["results_panel"])
        self.search_page.btn_browse.setText(t["browse_image"])
        self.search_page.text_search.setPlaceholderText(t["search_placeholder"])
        self.search_page.btn_search.setText(t["search"])
        self.search_page.btn_clear.setText(t["clear"])
        self.search_page.preview_placeholder.setText(t["preview_placeholder"])
        self.result_table.setHorizontalHeaderLabels(t["result_headers"])

        self.link_page.header.title.setText(t["link_page_title"])
        self.link_page.header.subtitle.setText(t["link_page_desc"])
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
        self.link_page.btn_browse.setText(t["browse_image"])
        self.link_page.query_image_label.setText(t["network_image_preview_hint"])
        self.link_page.btn_build.setText(t["network_build"])
        self.link_page.btn_import.setText(t["network_import"])
        self.link_page.btn_export.setText(t["network_export"])
        self.link_page.btn_link_details.setText(t["network_links_detail"])
        self.link_page.btn_open_cache.setText(t["network_open_cache"])
        self.link_page.btn_run.setText(t["link_run"])
        self.link_page.btn_clear.setText(t["clear"])
        self.link_page.results_title.setText(t["link_results_panel"])
        self.link_page.result_table.setHorizontalHeaderLabels(t["network_result_headers"])

        self.library_page.header.title.setText(t["library_page_title"])
        self.library_page.header.subtitle.setText(t["library_page_desc"])
        self.library_page.table_title.setText(t["library_table_title"])
        self.library_page.btn_add_lib.setText(t["add_folder"])
        self.library_page.btn_sync_db.setText(t["update_index"])
        self.library_page.btn_cleanup_missing.setText(t["cleanup_missing_vectors"])
        self.library_page.btn_vector_details.setText(t["library_vectors_detail"])

        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.setText(t["settings_page_desc"])
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        self._update_inference_backend_hint()

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

    def _finish_startup_sequence(self):
        synced_model_dir = sync_model_dir_to_config()
        synced_path = sync_ffmpeg_path_to_config()
        if synced_model_dir:
            self.settings_page.input_model_dir.setText(synced_model_dir)
        if synced_path:
            self.settings_page.input_ffmpeg_path.setText(synced_path)
        self._startup_complete = True
        self.refresh_library_table()
        self._prompt_resume_partial_indexing()
        self.app_meta_controller.refresh(self.language)

    def load_settings_values(self):
        try:
            config = load_config()
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_load_failed"], exc)
            return
        sampling_fps_mode = normalize_sampling_fps_mode(
            config.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
        )
        self.settings_page.set_sampling_fps_mode(sampling_fps_mode)
        self.settings_page.input_fps.setValue(config.get("fps", DEFAULT_CONFIG["fps"]))
        sampling_rules = normalize_sampling_fps_rules_text(
            config.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
        )
        if sampling_fps_mode == "dynamic" and not sampling_rules:
            sampling_rules = DEFAULT_CONFIG["sampling_fps_rules"]
        self.settings_page.set_sampling_fps_rules_text(sampling_rules)
        self.settings_page.input_top_k.setValue(config.get("search_top_k", DEFAULT_CONFIG["search_top_k"]))
        self.settings_page.input_preview_seconds.setValue(
            config.get("preview_seconds", DEFAULT_CONFIG["preview_seconds"])
        )
        self.settings_page.input_preview_width.setValue(
            config.get("preview_width", DEFAULT_CONFIG["preview_width"])
        )
        self.settings_page.input_preview_height.setValue(
            config.get("preview_height", DEFAULT_CONFIG["preview_height"])
        )
        self.settings_page.input_thumb_width.setValue(
            config.get("thumb_width", DEFAULT_CONFIG["thumb_width"])
        )
        self.settings_page.input_thumb_height.setValue(
            config.get("thumb_height", DEFAULT_CONFIG["thumb_height"])
        )
        self.settings_page.input_remote_max_frames.setValue(
            int(config.get("remote_max_frames", DEFAULT_CONFIG["remote_max_frames"]))
        )
        search_mode = config.get("search_mode", DEFAULT_CONFIG["search_mode"])
        self.search_page.search_mode.setCurrentIndex(0 if search_mode == "frame" else 1)
        self.settings_page.input_similarity_threshold.setValue(
            config.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"])
        )
        self.settings_page.input_max_chunk_duration.setValue(
            config.get("max_chunk_duration", DEFAULT_CONFIG["max_chunk_duration"])
        )
        self.settings_page.input_min_chunk_size.setValue(
            config.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"])
        )
        chunk_similarity_mode = config.get("chunk_similarity_mode", DEFAULT_CONFIG["chunk_similarity_mode"])
        self.settings_page.input_chunk_similarity_mode.setCurrentIndex(
            0 if chunk_similarity_mode == "chunk" else 1
        )
        prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
        self.settings_page.input_prefer_gpu.setCurrentIndex(0 if prefer_gpu else 1)
        auto_cleanup_missing_files = bool(
            config.get("auto_cleanup_missing_files", DEFAULT_CONFIG["auto_cleanup_missing_files"])
        )
        self.settings_page.input_auto_cleanup_missing_files.setCurrentIndex(1 if auto_cleanup_missing_files else 0)
        self.settings_page.input_ffmpeg_path.setText(config.get("ffmpeg_path", DEFAULT_CONFIG["ffmpeg_path"]))
        self.settings_page.input_model_dir.setText(config.get("model_dir", DEFAULT_CONFIG["model_dir"]))
        self._update_inference_backend_hint()
        self._update_sampling_rules_feedback()
        self._update_sampling_preview()

    def save_settings(self):
        try:
            config = load_config()
            previous_fps = config.get("fps", DEFAULT_CONFIG["fps"] )
            previous_sampling_fps_mode = normalize_sampling_fps_mode(
                config.get("sampling_fps_mode", DEFAULT_CONFIG["sampling_fps_mode"])
            )
            previous_sampling_fps_rules = normalize_sampling_fps_rules_text(
                config.get("sampling_fps_rules", DEFAULT_CONFIG["sampling_fps_rules"])
            )
            previous_similarity_threshold = float(
                config.get("similarity_threshold", DEFAULT_CONFIG["similarity_threshold"])
            )
            previous_max_chunk_duration = float(
                config.get("max_chunk_duration", DEFAULT_CONFIG["max_chunk_duration"])
            )
            previous_min_chunk_size = int(config.get("min_chunk_size", DEFAULT_CONFIG["min_chunk_size"]))
            previous_chunk_similarity_mode = str(
                config.get("chunk_similarity_mode", DEFAULT_CONFIG["chunk_similarity_mode"])
            )
            previous_prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
            new_fps = self.settings_page.input_fps.value()
            new_sampling_fps_mode = normalize_sampling_fps_mode(
                self.settings_page.get_sampling_fps_mode()
            )
            new_sampling_fps_rules = normalize_sampling_fps_rules_text(
                self.settings_page.get_sampling_fps_rules_text()
            )
            rules_valid, _ = validate_sampling_fps_rules(new_sampling_fps_rules)
            if new_sampling_fps_mode == "dynamic" and new_sampling_fps_rules and not rules_valid:
                self.settings_page.lbl_status.setText(self.texts["setting_sampling_fps_rules_invalid"] )
                self.show_info_dialog(
                    self.texts["error_title"],
                    self.texts["setting_sampling_fps_rules_invalid"],
                    kind="warning",
                )
                return
            new_similarity_threshold = float(self.settings_page.input_similarity_threshold.value())
            new_max_chunk_duration = float(self.settings_page.input_max_chunk_duration.value())
            new_min_chunk_size = int(self.settings_page.input_min_chunk_size.value())
            new_chunk_similarity_mode = str(self.settings_page.input_chunk_similarity_mode.currentData())
            config["fps"] = new_fps
            config["sampling_fps_mode"] = new_sampling_fps_mode
            # Preserve the user's rule set even while fixed mode is active so
            # switching back to dynamic mode does not silently drop it.
            config["sampling_fps_rules"] = new_sampling_fps_rules
            config["search_top_k"] = self.settings_page.input_top_k.value()
            config["preview_seconds"] = self.settings_page.input_preview_seconds.value()
            config["preview_width"] = self.settings_page.input_preview_width.value()
            config["preview_height"] = self.settings_page.input_preview_height.value()
            config["thumb_width"] = self.settings_page.input_thumb_width.value()
            config["thumb_height"] = self.settings_page.input_thumb_height.value()
            config["remote_max_frames"] = int(self.settings_page.input_remote_max_frames.value())
            config["similarity_threshold"] = new_similarity_threshold
            config["max_chunk_duration"] = new_max_chunk_duration
            config["min_chunk_size"] = new_min_chunk_size
            config["chunk_similarity_mode"] = new_chunk_similarity_mode
            config["prefer_gpu"] = bool(self.settings_page.input_prefer_gpu.currentData())
            config["auto_cleanup_missing_files"] = bool(
                self.settings_page.input_auto_cleanup_missing_files.currentData()
            )
            config["ffmpeg_path"] = self.settings_page.input_ffmpeg_path.text().strip()
            config["model_dir"] = self.settings_page.input_model_dir.text().strip() or DEFAULT_CONFIG["model_dir"]
            save_config(config)
            effective_rules = new_sampling_fps_rules if new_sampling_fps_mode == "dynamic" else ""
            fps_changed = (
                previous_fps != new_fps
                or previous_sampling_fps_mode != new_sampling_fps_mode
                or previous_sampling_fps_rules != effective_rules
            )
            chunk_changed = (
                previous_similarity_threshold != new_similarity_threshold
                or previous_max_chunk_duration != new_max_chunk_duration
                or previous_min_chunk_size != new_min_chunk_size
                or previous_chunk_similarity_mode != new_chunk_similarity_mode
            )
            if previous_prefer_gpu != config["prefer_gpu"]:
                reset_engine()
            if not config["model_dir"]:
                synced_model_dir = sync_model_dir_to_config()
                if synced_model_dir:
                    self.settings_page.input_model_dir.setText(synced_model_dir)
            if not config["ffmpeg_path"]:
                synced_path = sync_ffmpeg_path_to_config()
                if synced_path:
                    self.settings_page.input_ffmpeg_path.setText(synced_path)
            self.check_runtime_resources(show_dialog=False)
            self._update_inference_backend_hint()
            self._update_sampling_preview()
            save_message = self._build_settings_save_message(fps_changed, chunk_changed)
            self.settings_page.lbl_status.setText(save_message)
            self.show_info_dialog(self.texts["success_title"], save_message, kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def reset_settings(self):
        try:
            config = load_config()
            previous_prefer_gpu = config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"])
            for key, value in DEFAULT_CONFIG.items():
                if key in {"theme", "language"}:
                    continue
                config[key] = value
            save_config(config)
            if previous_prefer_gpu != config.get("prefer_gpu", DEFAULT_CONFIG["prefer_gpu"]):
                reset_engine()
            synced_model_dir = sync_model_dir_to_config()
            synced_path = sync_ffmpeg_path_to_config()
            self.load_settings_values()
            if synced_model_dir:
                self.settings_page.input_model_dir.setText(synced_model_dir)
            if synced_path:
                self.settings_page.input_ffmpeg_path.setText(synced_path)
            self.check_runtime_resources(show_dialog=False)
            self._update_inference_backend_hint()
            self._update_sampling_preview()
            self.settings_page.lbl_status.setText(self.texts["reset_settings_done"] )
            self.show_info_dialog(self.texts["success_title"], self.texts["reset_settings_done"], kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _bind_sampling_preview_signals(self):
        if getattr(self, "_sampling_preview_bound", False):
            return
        self._sampling_preview_bound = True
        self.settings_page.input_fps.valueChanged.connect(self._update_sampling_preview)
        self.settings_page.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_preview_changed)
        self.settings_page.input_sampling_fps_mode.currentIndexChanged.connect(self._handle_sampling_mode_feedback_changed)
        self.settings_page.input_sampling_fps_rules.textChanged.connect(self._update_sampling_preview)
        self.settings_page.input_sampling_fps_rules.textChanged.connect(self._update_sampling_rules_feedback)

    def _handle_sampling_mode_preview_changed(self, *_args):
        self._ensure_dynamic_sampling_defaults()
        self._update_sampling_preview()

    def _handle_sampling_mode_feedback_changed(self, *_args):
        self._ensure_dynamic_sampling_defaults()
        self._update_sampling_rules_feedback()

    def _open_sampling_rules_dialog(self):
        dialog = SamplingRulesDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            rules_text=self.settings_page.get_sampling_fps_rules_text() or DEFAULT_CONFIG["sampling_fps_rules"],
        )
        if dialog.exec():
            self.settings_page.set_sampling_fps_rules_text(dialog.rules_text())
            self._update_sampling_rules_feedback()
            self._update_sampling_preview()

    def _ensure_dynamic_sampling_defaults(self):
        if normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode()) != "dynamic":
            return
        current_rules_text = normalize_sampling_fps_rules_text(self.settings_page.get_sampling_fps_rules_text())
        if current_rules_text:
            return
        self.settings_page.set_sampling_fps_rules_text(DEFAULT_CONFIG["sampling_fps_rules"])

    def _update_sampling_rules_feedback(self):
        current_rules_text = self.settings_page.get_sampling_fps_rules_text()
        rules_text = normalize_sampling_fps_rules_text(current_rules_text)
        sampling_fps_mode = normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode())
        default_hint = self.texts["setting_sampling_fps_rules_hint"]
        if current_rules_text != rules_text:
            self.settings_page.set_sampling_fps_rules_text(rules_text)
            return
        if sampling_fps_mode != "dynamic":
            self.settings_page.set_sampling_rules_error_state(False)
            return

        is_valid, _ = validate_sampling_fps_rules(rules_text)
        if rules_text and not is_valid:
            self.settings_page.set_sampling_rules_error_state(True)
            return

        self.settings_page.set_sampling_rules_error_state(False)

    def _update_sampling_preview(self):
        base_fps = float(self.settings_page.input_fps.value())
        sampling_fps_mode = normalize_sampling_fps_mode(self.settings_page.get_sampling_fps_mode())
        rules_text = normalize_sampling_fps_rules_text(self.settings_page.get_sampling_fps_rules_text())
        rules_valid, _ = validate_sampling_fps_rules(rules_text)
        if sampling_fps_mode == "dynamic" and rules_text and not rules_valid:
            return
        samples = [
            ("2m", 120.0),
            ("10m", 600.0),
            ("30m", 1800.0),
            ("2h", 7200.0),
        ]
        preview_parts = []
        for label, duration_sec in samples:
            fps_value = resolve_sampling_fps(
                duration_sec=duration_sec,
                config={
                    "fps": base_fps,
                    "sampling_fps_mode": sampling_fps_mode,
                    "sampling_fps_rules": rules_text,
                },
            )
            frame_count = max(1, int(round(duration_sec * fps_value)))
            if self.language == "zh":
                preview_parts.append(f"{label} -> {fps_value:.2f} FPS / ~{frame_count}\u5e27")
            else:
                preview_parts.append(f"{label} -> {fps_value:.2f} FPS / ~{frame_count} frames")

        if self.language != "zh":
            prefix = "Fixed sampling" if sampling_fps_mode == "fixed" else "Duration-range sampling"
        else:
            prefix = "\u56fa\u5b9a\u91c7\u6837" if sampling_fps_mode == "fixed" else "\u603b\u957f\u5ea6\u533a\u95f4\u91c7\u6837"
        self.settings_page.hint_sampling_fps_preview.setText(f"{prefix}: " + " | ".join(preview_parts))

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

    def refresh_library_table(self):
        try:
            is_indexing = self.indexing_controller.is_running()
            populate_library_table(
                self.library_page.lib_table,
                list_libraries(),
                is_indexing,
                self.sync_library,
                self.remove_library_entry,
                self.open_library_folder,
                self.texts,
            )
        except Exception as exc:
            self.show_error_dialog(self.texts["library_load_failed"], exc)

    def sync_library(self, path):
        self.start_update_index(target_lib=path)

    def open_library_folder(self, path):
        open_folder_in_explorer(path)

    def start_search(self):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return

        text_query = self.search_page.text_search.text().strip()
        if text_query:
            query_info = prepare_text_query(text_query)
            if query_info["too_short"]:
                self.search_page.lbl_status.setText(self.texts["query_too_short"])
                return
            if query_info["changed"]:
                self.search_page.text_search.setText(query_info["normalized"])
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query = query_info["normalized"]
        else:
            query = self.current_img_path
        if not query:
            self.search_page.lbl_status.setText(self.texts["empty_query"])
            return

        self.switch_page("search")
        self.search_controller.start_search(query, bool(text_query))

    def _save_search_mode(self):
        try:
            config = load_config()
            search_mode = str(self.search_page.search_mode.currentData() or DEFAULT_CONFIG["search_mode"])
            config["search_mode"] = search_mode
            save_config(config)
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def _build_settings_save_message(self, fps_changed, chunk_changed):
        if fps_changed and chunk_changed:
            return self.texts["settings_saved_mixed_rebuild"]
        if fps_changed:
            return self.texts["settings_saved_full_rebuild"]
        if chunk_changed:
            return self.texts["settings_saved_chunk_rebuild"]
        return self.texts["settings_saved_no_rebuild"]

    def clear_all_content(self):
        self.current_img_path = None
        self.search_page.text_search.clear()
        self.search_page.img_label.clear()
        self.search_page.img_label.setText(self.texts["image_drop_hint"])
        self.search_controller.clear_results()
        self.media_player.stop()
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

    def select_video_folder(self):
        path = QFileDialog.getExistingDirectory(self, self.texts["select_folder"])
        if not path:
            return
        try:
            if add_library(path):
                self.refresh_library_table()
                self.library_page.lbl_status.setText(self.texts["library_added"])
                self.show_info_dialog(self.texts["success_title"], self.texts["library_added"], kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["library_add_failed"], exc)

    def remove_library_entry(self, path):
        if not self.show_confirm_dialog(self.texts["confirm_title"], self.texts["remove_library_confirm"].format(path=path)):
            return
        try:
            if remove_library_entry(path, delete_physical_video_data):
                self.refresh_library_table()
                self.library_page.lbl_status.setText(self.texts["library_removed"])
                self.show_info_dialog(self.texts["success_title"], self.texts["library_removed"], kind="success")
            else:
                self.library_page.lbl_status.setText(self.texts["library_remove_failed"])
        except Exception as exc:
            self.show_error_dialog(self.texts["library_remove_failed"], exc)

    def start_update_index(self, target_lib=None):
        self._start_index_update(target_lib=target_lib, force_cleanup_missing_files=False)

    def cleanup_missing_library_vectors(self):
        try:
            config = load_config()
            meta = load_meta(config["meta_file"])
            missing_entries = list(list_missing_library_files(meta, config))
        except Exception as exc:
            self.show_error_dialog(self.texts["library_load_failed"], exc)
            return

        if not missing_entries:
            self.show_info_dialog(
                self.texts["cleanup_missing_vectors_preview_title"],
                self.texts["cleanup_missing_vectors_preview_empty"],
                kind="info",
            )
            return

        reviewed_entries = self._show_cleanup_preview_dialog(missing_entries)
        if reviewed_entries is None:
            return
        if not reviewed_entries:
            self.show_info_dialog(
                self.texts["cleanup_missing_vectors_preview_title"],
                self.texts["cleanup_missing_vectors_preview_empty"],
                kind="info",
            )
            return

        if not self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["cleanup_missing_vectors_confirm"].format(count=len(reviewed_entries)),
            kind="warning",
        ):
            return
        self._start_index_update(target_lib=None, force_cleanup_missing_files=True)

    def _show_cleanup_preview_dialog(self, missing_entries):
        rows = []
        for index, entry in enumerate(missing_entries, start=1):
            rows.append(
                [
                    index,
                    entry["library_path"],
                    entry["video_rel_path"],
                    entry.get("video_id", "") or "",
                    entry["abs_path"],
                ]
            )

        subtitle = "\n".join(
            [
                self.texts["cleanup_missing_vectors_preview_summary"].format(
                    count=len(missing_entries),
                    libraries=len({entry["library_path"] for entry in missing_entries}),
                ),
                self.texts["cleanup_missing_vectors_preview_continue"],
            ]
        )
        dialog = ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts["cleanup_missing_vectors_preview_title"],
            subtitle=subtitle,
            headers=self.texts["cleanup_missing_vectors_headers"],
            rows=rows,
            export_default_name=self.texts["cleanup_missing_vectors_export_name"],
            stretch_column=4,
            fixed_column_widths={
                0: 52,
                2: 220,
                3: 140,
            },
            confirm_mode=True,
            confirm_text=self.texts["confirm_action"],
            issue_row_predicate=lambda row: True,
            summary_text=self.texts["cleanup_missing_vectors_preview_continue"],
            row_payloads=missing_entries,
            extra_actions=[
                {
                    "label": self.texts["details_exclude_selected"],
                    "object_name": "Ghost",
                    "handler": self._exclude_cleanup_preview_selection,
                }
            ],
            selection_mode=QAbstractItemView.ExtendedSelection,
        )
        if not dialog.exec():
            return None
        return dialog.row_payloads

    def _exclude_cleanup_preview_selection(self, dialog):
        removed = dialog.remove_selected_payloads()
        if not removed:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        dialog.status_hint.setText(self.texts["details_excluded_count"].format(count=removed))
        if not dialog.row_payloads:
            dialog.reject()

    def _start_index_update(self, target_lib=None, force_cleanup_missing_files=False):
        try:
            if not self.check_runtime_resources():
                self.library_page.lbl_status.setText(self.texts["model_features_disabled"])
                return
            self.switch_page("library")
            if self.indexing_controller.is_running():
                return
            self.library_page.btn_sync_db.setEnabled(False)
            self.library_page.btn_add_lib.setEnabled(False)
            self.library_page.btn_cleanup_missing.setEnabled(False)
            self.library_page.progress_bar.setVisible(True)
            self.indexing_controller.start(
                target_lib=target_lib,
                force_cleanup_missing_files=force_cleanup_missing_files,
            )
        except Exception as exc:
            self.show_error_dialog(self.texts["index_start_failed"], exc)

    def _update_indexing_progress(self, value, text):
        self.library_page.progress_bar.setValue(value)
        self.library_page.lbl_status.setText(text)

    def _finish_indexing(self, success, target_lib, stopped=False):
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.btn_cleanup_missing.setEnabled(True)
        self.library_page.progress_bar.setVisible(False)
        self.refresh_library_table()
        if stopped:
            status_text = self.texts["index_stopped"]
        elif success:
            status_text = self.texts["index_updated_single"] if target_lib else self.texts["index_updated"]
        else:
            status_text = self.texts["index_failed"]
        self.library_page.lbl_status.setText(status_text)
        if self._close_when_indexing_stops:
            self._close_when_indexing_stops = False
            self.close()

    def handle_play(self, path, sec, end_sec=None):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        if not self.preview_controller.play(path, sec, end_sec=end_sec):
            self.search_page.lbl_status.setText(self.texts["preview_failed"])

    def open_current_preview_dialog(self, _event=None):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        now = time.monotonic()
        if self._preview_dialog_opening or now < self._preview_dialog_cooldown_until:
            self.search_page.lbl_status.setText(
                self.texts.get("preview_dialog_busy", "Preview is still switching. Try again in a moment.")
            )
            return

        payload = self.preview_controller.get_current_preview_context()
        if not payload:
            return
        video_path = str(payload.get("video_path", "")).strip()
        if not video_path:
            return

        start_sec = float(payload.get("start_sec", 0.0))
        end_sec = float(payload.get("end_sec", start_sec))
        self.preview_controller.stop_preview()
        self._preview_dialog_opening = True
        self._preview_dialog_cooldown_until = now + 0.8

        try:
            if not hasattr(self, "_preview_dialog") or self._preview_dialog is None:
                self._preview_dialog = PreviewDialog(self, video_path, start_sec, end_sec, self.texts)
            else:
                self._preview_dialog.load_preview(video_path, start_sec, end_sec)
            self._preview_dialog.show()
            self._preview_dialog.raise_()
            self._preview_dialog.activateWindow()
        finally:
            QTimer.singleShot(800, self._release_preview_dialog_gate)

    def _release_preview_dialog_gate(self):
        self._preview_dialog_opening = False

    def handle_export_clip(self, path, sec, end_sec=None):
        base_name = os.path.splitext(os.path.basename(path))[0]
        suggested_name = f"{base_name}_clip_{int(float(sec)):06d}.mp4"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("export_clip_title", "\u5bfc\u51fa\u9884\u89c8\u7247\u6bb5"),
            suggested_name,
            self.texts.get("export_clip_filter", "\u89c6\u9891\u6587\u4ef6 (*.mp4 *.mkv *.mov)"),
        )
        if not save_path:
            return
        try:
            result = self.preview_controller.export_clip(path, sec, save_path, end_sec=end_sec)
            if result.returncode != 0:
                raise RuntimeError((result.stderr or b"").decode("utf-8", errors="ignore").strip())
            self.search_page.lbl_status.setText(
                self.texts.get("export_clip_success", "\u7247\u6bb5\u5df2\u5bfc\u51fa\uff1a{path}").format(path=save_path)
            )
        except Exception as exc:
            self.show_error_dialog(self.texts.get("export_clip_failed", "\u5bfc\u51fa\u7247\u6bb5\u5931\u8d25\u3002"), exc)

    def upload_file(self):
        path, _ = QFileDialog.getOpenFileName(self, self.texts["select_image"], "", self.texts["image_filter"])
        if path:
            self._set_image_query(path, clear_text=True)

    def apply_theme(self):
        style = DARK_STYLE if self.is_dark_mode else LIGHT_STYLE
        app = QApplication.instance()
        if app:
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
        notice = pop_migration_notice()
        if not notice:
            return
        self.show_info_dialog(
            self.texts["migration_notice_title"],
            self.texts["migration_notice_body"].format(
                config_file=notice["config_file"],
                data_dir=notice["data_dir"],
            ),
            kind="info",
        )

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
            if self.pages.currentIndex() == 1:
                self.upload_network_file_path(dropped_path)
                return
            self.upload_file_path(dropped_path)

    def upload_file_path(self, path):
        self._set_image_query(path, clear_text=False)
        self.switch_page("search")

    def upload_network_file_path(self, path):
        self._set_network_image_query(path)
        self.switch_page("link")

    def closeEvent(self, event):
        if hasattr(self, "_preview_dialog") and self._preview_dialog is not None:
            if self._preview_dialog.is_export_running():
                self.search_page.lbl_status.setText(
                    self.texts.get("preview_dialog_export_running", "Clip export is still running. Please wait.")
                )
                event.ignore()
                return
        if self.indexing_controller.is_running():
            self._close_when_indexing_stops = True
            self.indexing_controller.request_stop()
            self.library_page.lbl_status.setText(self.texts["index_stop_requested"])
            event.ignore()
            return
        if hasattr(self, "_preview_dialog") and self._preview_dialog is not None:
            self._preview_dialog.shutdown_player()
        self.search_controller.shutdown()
        self.network_search_controller.shutdown()
        self.indexing_controller.shutdown()
        self.app_meta_controller.shutdown()
        self.runtime_resource_controller.shutdown()
        self.preview_controller.shutdown()
        event.accept()

    def _set_image_query(self, path, clear_text):
        self.current_img_path = path
        self.search_page.img_label.setPixmap(
            QPixmap(path).scaled(420, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        if clear_text:
            self.search_page.text_search.clear()
        self.search_page.lbl_status.setText(self.texts["image_loaded"])

    def open_runtime_resource_folder(self):
        from src.services.runtime_resource_service import ensure_runtime_resource_dirs

        root_dir = ensure_runtime_resource_dirs()
        open_folder_in_explorer(root_dir)

    def _update_inference_backend_hint(self):
        status = get_engine_runtime_status()
        backend_text = ""
        show_help_link = False

        if status["initialized"]:
            backend_text = status["backend"] or ""
            if status["warning"]:
                issue_text = self.texts["setting_runtime_issue_unknown"]
                if status.get("issue") == "directml":
                    issue_text = self.texts["setting_runtime_issue_directml"]
                elif status.get("issue") == "directx":
                    issue_text = self.texts["setting_runtime_issue_directx"]
                elif status.get("issue") == "windows":
                    issue_text = self.texts["setting_runtime_issue_windows"]
                elif status.get("issue") == "windows_version":
                    issue_text = self.texts["setting_runtime_issue_windows_version"]
                elif status.get("issue") == "msvc":
                    issue_text = self.texts["setting_runtime_issue_msvc"]
                backend_text = self.texts["setting_inference_cpu_issue"].format(issue=issue_text)
                show_help_link = True
                self.settings_page.hint_inference_backend.setProperty("state", "warn")
            elif str(status["backend"]).upper() == "GPU":
                self.settings_page.hint_inference_backend.setProperty("state", "ok")
            else:
                self.settings_page.hint_inference_backend.setProperty("state", "neutral")
        else:
            self.settings_page.hint_inference_backend.setProperty("state", "neutral")

        backend_label = (
            self.texts["setting_inference_backend"].format(backend=backend_text)
            if backend_text else self.texts["setting_inference_backend"].format(
                backend=self.texts["setting_inference_uninitialized"]
            )
        )
        if show_help_link:
            backend_label = f"{backend_label} | {self.texts['setting_gpu_runtime_link_only']}"
        ffmpeg_label = self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        self.settings_page.set_runtime_status_texts(backend_label, ffmpeg_label)

    def _handle_runtime_resource_exit(self):
        self.startup_cancelled = True
        self.close()

    def check_runtime_resources(self, show_dialog=True):
        return self.runtime_resource_controller.check_resources(show_dialog=show_dialog)

    def start_runtime_resource_download(self):
        self.runtime_resource_controller.start_download()

    def start_network_search(self):
        if not self.check_runtime_resources():
            self.link_page.lbl_search_status.setText(self.texts["model_features_disabled"])
            return
        query_text = self.link_page.input_link.text().strip()
        query_data = query_text
        is_text = True
        if query_text:
            query_info = prepare_text_query(query_text)
            if query_info["too_short"]:
                self.link_page.lbl_search_status.setText(self.texts["query_too_short"])
                return
            if query_info["changed"]:
                self.link_page.input_link.setText(query_info["normalized"])
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query_data = query_info["normalized"]
        if not query_data:
            query_data = self.network_query_img_path
            is_text = False
        if not query_data:
            self.link_page.lbl_search_status.setText(self.texts["empty_query"])
            return
        self.switch_page("link")
        self.network_search_controller.start_search(query_data, is_text)

    def upload_network_query_image(self):
        path, _ = QFileDialog.getOpenFileName(self, self.texts["select_image"], "", self.texts["image_filter"])
        if not path:
            return
        self._set_network_image_query(path)

    def _set_network_image_query(self, path):
        self.network_query_img_path = path
        self.link_page.query_image_label.setPixmap(
            QPixmap(path).scaled(420, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.link_page.lbl_search_status.setText(self.texts["image_loaded"])

    def start_network_build(self):
        raw_text = self.link_page.build_links_input.toPlainText().strip()
        links = re.findall(r"https?://[^\s,]+", raw_text)
        if not links:
            self.link_page.lbl_build_status.setText(self.texts["network_link_editor_empty"])
            return
        precheck = precheck_remote_links(links)
        accepted_links = precheck.get("accepted_links", [])
        blocked_count = int(precheck.get("blocked_count", 0))
        risky_count = int(precheck.get("risky_count", 0))
        if not accepted_links:
            self.link_page.lbl_build_status.setText(
                f"{self.texts['network_precheck_all_blocked']} "
                f"({self.texts['network_precheck_summary'].format(accepted=0, blocked=blocked_count, risky=risky_count)})"
            )
            return
        mode = str(self.link_page.mode_combo.currentData() or "download")
        if blocked_count > 0 or risky_count > 0:
            self.link_page.lbl_build_status.setText(
                self.texts["network_precheck_summary"].format(
                    accepted=int(precheck.get("accepted_count", 0)),
                    blocked=blocked_count,
                    risky=risky_count,
                )
            )
        self.switch_page("link")
        self.network_search_controller.start_build(accepted_links, mode)

    def import_network_library(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["network_import_title"],
            "",
            self.texts["network_zip_filter"],
        )
        if not zip_path:
            return
        self.switch_page("link")
        try:
            self.network_search_controller.import_zip(zip_path)
        except Exception as exc:
            self.show_error_dialog(self.texts["network_import_failed"], exc)

    def export_network_library(self):
        zip_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts["network_export_title"],
            "remote_library.zip",
            self.texts["network_zip_filter"],
        )
        if not zip_path:
            return
        self.switch_page("link")
        try:
            self.network_search_controller.export_zip(zip_path)
        except Exception as exc:
            self.show_error_dialog(self.texts["network_export_failed"], exc)

    def show_local_vector_details(self):
        try:
            detail = list_local_vector_details()
            headers = self.texts["library_vectors_headers"]
            rows = []
            payloads = []
            for index, item in enumerate(detail["entries"], start=1):
                rows.append(
                    [
                        index,
                        item["library_path"],
                        item["video_rel_path"],
                        os.path.basename(item["vector_file"]) if item.get("vector_file") else "",
                        os.path.basename(item["index_file"]) if item.get("index_file") else "",
                        self.texts["details_yes"] if item["vector_exists"] else self.texts["details_no"],
                        self.texts["details_yes"] if item["index_exists"] else self.texts["details_no"],
                    ]
                )
                payloads.append(item)
            subtitle = self.texts["library_vectors_subtitle"].format(
                total=detail["total_entries"],
                vector_dir=detail["vector_dir"],
                index_dir=detail["index_dir"],
            )
            ResourceTableDialog(
                parent=self,
                is_dark=self.is_dark_mode,
                language=self.language,
                title=self.texts["library_vectors_title"],
                subtitle=subtitle,
                headers=headers,
                rows=rows,
                row_payloads=payloads,
                export_default_name="local_vector_details.json",
                stretch_column=3,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    1: 220,
                    2: 220,
                    5: 86,
                    6: 86,
                },
                issue_row_predicate=lambda row: row[5] == self.texts["details_no"] or row[6] == self.texts["details_no"],
                extra_actions=[
                    {
                        "label": self.texts["details_open_selected"],
                        "object_name": "Ghost",
                        "handler": self._open_selected_vector_detail_path,
                    },
                    {
                        "label": self.texts["details_copy_selected"],
                        "object_name": "Ghost",
                        "handler": self._copy_selected_vector_detail_path,
                    },
                ],
                row_double_click_handler=self._open_vector_detail_payload,
            ).exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_vectors_load_failed"], exc)

    def _open_vector_detail_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 3
        library_path = str(payload.get("library_path", "")).strip()
        video_rel_path = str(payload.get("video_rel_path", "")).strip()
        vector_file = str(payload.get("vector_file", "")).strip()
        index_file = str(payload.get("index_file", "")).strip()

        if column == 1:
            if not library_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_folder_in_explorer(library_path)
            dialog.status_hint.setText(library_path)
            return

        if column == 2:
            if not library_path or not video_rel_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            video_path = os.path.join(library_path, video_rel_path)
            if os.path.exists(video_path):
                open_in_explorer(video_path)
                dialog.status_hint.setText(video_path)
            else:
                open_folder_in_explorer(library_path)
                dialog.status_hint.setText(video_path)
            return

        if column == 3:
            if not vector_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_in_explorer(vector_file) if os.path.exists(vector_file) else open_folder_in_explorer(os.path.dirname(vector_file))
            dialog.status_hint.setText(vector_file)
            return

        if column == 4:
            if not index_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_in_explorer(index_file) if os.path.exists(index_file) else open_folder_in_explorer(os.path.dirname(index_file))
            dialog.status_hint.setText(index_file)

    def _open_selected_vector_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_vector_detail_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_vector_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = payload["vector_file"] if payload.get("vector_exists") else payload["index_file"]
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def show_network_link_details(self):
        try:
            detail = list_remote_link_details()
            headers = self.texts["network_links_headers"]
            rows = []
            payloads = []
            for index, item in enumerate(detail["entries"], start=1):
                rows.append(
                    [
                        index,
                        item.get("title", ""),
                        item.get("source_link", "") or item.get("source_id", ""),
                        int(item.get("frames", 0)),
                        f"{float(item.get('min_time', 0.0)):.2f}",
                        f"{float(item.get('max_time', 0.0)):.2f}",
                    ]
                )
                payloads.append(item)
            subtitle = self.texts["network_links_subtitle"].format(
                links=detail["total_links"],
                vectors=detail["total_vectors"],
                vector_file=detail["vector_file"],
            )
            ResourceTableDialog(
                parent=self,
                is_dark=self.is_dark_mode,
                language=self.language,
                title=self.texts["network_links_title"],
                subtitle=subtitle,
                headers=headers,
                rows=rows,
                row_payloads=payloads,
                export_default_name="remote_link_details.json",
                stretch_column=2,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    3: 86,
                    4: 116,
                    5: 116,
                },
                extra_actions=[
                    {
                        "label": self.texts["details_open_selected_link"],
                        "object_name": "Ghost",
                        "handler": self._open_selected_network_link,
                    },
                    {
                        "label": self.texts["details_copy_selected_link"],
                        "object_name": "Ghost",
                        "handler": self._copy_selected_network_link,
                    },
                ],
                row_double_click_handler=self._open_network_link_payload,
            ).exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["network_links_load_failed"], exc)

    def _open_network_link_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 2
        if column not in {1, 2}:
            return
        link = str(payload.get("source_link", "") or payload.get("source_id", "")).strip()
        if not link:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        webbrowser.open(link)
        dialog.status_hint.setText(link)

    def _open_selected_network_link(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_network_link_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_network_link(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        link = str(selected[0].get("source_link", "") or selected[0].get("source_id", "")).strip()
        if not link:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(link)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def open_network_download_cache_folder(self):
        cache_dirs = [
            os.path.join(get_app_data_dir(), "source", "remote_build_cache"),
            os.path.join(get_app_data_dir(), "source", "link_cache"),
        ]
        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
                open_folder_in_explorer(cache_dir)
                return
        os.makedirs(cache_dirs[0], exist_ok=True)
        open_folder_in_explorer(cache_dirs[0])

    def _finish_runtime_resource_download(self, result):
        self.check_runtime_resources(show_dialog=False)
        self.settings_page.input_model_dir.setText(result.get("model_dir", get_configured_model_dir()))
        if result.get("ffmpeg_path"):
            self.settings_page.input_ffmpeg_path.setText(result["ffmpeg_path"])
            self._update_inference_backend_hint()

    def _apply_runtime_resource_status(self, status):
        self.models_ready = status["model_ready"]
        self.search_page.btn_search.setEnabled(self.models_ready)
        self.network_search_controller.refresh_status()
        self.library_page.btn_sync_db.setEnabled(status["resources_ready"])
        if status["resources_ready"]:
            self.search_controller.start_warmup()
        if not status["resources_ready"]:
            status_text = self.texts["model_features_disabled"]
            self.search_page.lbl_status.setText(status_text)
            self.link_page.lbl_build_status.setText(status_text)
            self.link_page.lbl_search_status.setText(status_text)
            self.library_page.lbl_status.setText(status_text)
