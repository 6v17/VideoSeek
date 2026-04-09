import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget, QHBoxLayout

from src.app.config import DEFAULT_CONFIG, get_app_version, load_config, save_config
from src.app.i18n import get_texts
from src.core.clip_embedding import get_engine_runtime_status, reset_engine
from src.services.about_service import get_local_about_payload
from src.services.library_service import (
    add_library,
    list_libraries,
    list_local_vector_details,
    remove_library as remove_library_entry,
)
from src.services.notice_service import get_local_notice_payload
from src.services.remote_library_service import list_remote_link_details
from src.services.remote_link_precheck_service import precheck_remote_links
from src.workflows.update_video import delete_physical_video_data
from src.utils import (
    get_ffmpeg_status_text,
    get_configured_model_dir,
    open_folder_in_explorer,
    open_in_explorer,
    sync_ffmpeg_path_to_config,
    sync_model_dir_to_config,
)
from src.services.version_service import get_local_version_status
from ui.app_meta_controller import AppMetaController
from ui.components import LibraryPage, LinkSearchPage, NavigationSidebar, SearchPage, SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, NoticeDialog, ResourceTableDialog
from ui.indexing_controller import IndexingController
from ui.layout import WINDOW_SIZES, apply_window_size
from ui.network_search_controller import NetworkSearchController
from ui.preview_controller import PreviewController
from ui.runtime_resource_controller import RuntimeResourceController
from ui.search_controller import SearchController
from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.table_views import populate_library_table


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.startup_cancelled = False
        self.current_img_path = None
        self.network_query_img_path = None
        self.version_info = None
        self.notice_payload = None
        self.about_payload = None
        self.models_ready = True

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
        self.media_player.setVideoOutput(self.video_widget)
        sync_model_dir_to_config()
        sync_ffmpeg_path_to_config()
        self.apply_texts()
        self.load_settings_values()
        self.check_runtime_resources()
        if self.startup_cancelled:
            return
        self.refresh_library_table()
        self.apply_theme()
        self.app_meta_controller.refresh(self.language)

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
        self.pages.addWidget(self._build_scroll_page(self.settings_page))
        content_layout.addWidget(self.pages)
        main_layout.addWidget(self.content, 1)

        self.search_page.preview_placeholder.hide()
        self.video_widget = QVideoWidget()
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
        self.library_page.btn_vector_details.clicked.connect(self.show_local_vector_details)

        self.settings_page.btn_save.clicked.connect(self.save_settings)
        self.settings_page.btn_reset.clicked.connect(self.reset_settings)

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
        self.library_page.btn_vector_details.setText(t["library_vectors_detail"])

        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.setText(t["settings_page_desc"])
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        self.settings_page.hint_ffmpeg_active.setText(
            t["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        )
        self._update_inference_backend_hint()

        if not self.current_img_path and not self.search_page.img_label.pixmap():
            self.search_page.img_label.setText(t["image_drop_hint"])

        self.search_page.lbl_status.setText(t["ready"])
        self.link_page.lbl_build_status.setText(t["ready"])
        self.link_page.lbl_search_status.setText(t["ready"])
        self.library_page.lbl_status.setText(t["ready"])
        self.settings_page.lbl_status.setText(t["settings_hint"])
        self.refresh_library_table()

    def load_settings_values(self):
        try:
            config = load_config()
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_load_failed"], exc)
            return
        self.settings_page.input_fps.setValue(config.get("fps", DEFAULT_CONFIG["fps"]))
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
        self.settings_page.input_ffmpeg_path.setText(config.get("ffmpeg_path", DEFAULT_CONFIG["ffmpeg_path"]))
        self.settings_page.input_model_dir.setText(config.get("model_dir", DEFAULT_CONFIG["model_dir"]))
        self.settings_page.hint_ffmpeg_active.setText(
            self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        )
        self._update_inference_backend_hint()

    def save_settings(self):
        try:
            config = load_config()
            previous_fps = config.get("fps", DEFAULT_CONFIG["fps"])
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
            new_similarity_threshold = float(self.settings_page.input_similarity_threshold.value())
            new_max_chunk_duration = float(self.settings_page.input_max_chunk_duration.value())
            new_min_chunk_size = int(self.settings_page.input_min_chunk_size.value())
            new_chunk_similarity_mode = str(self.settings_page.input_chunk_similarity_mode.currentData())
            config["fps"] = new_fps
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
            config["ffmpeg_path"] = self.settings_page.input_ffmpeg_path.text().strip()
            config["model_dir"] = self.settings_page.input_model_dir.text().strip() or DEFAULT_CONFIG["model_dir"]
            save_config(config)
            fps_changed = previous_fps != new_fps
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
            self.settings_page.hint_ffmpeg_active.setText(
                self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
            )
            self._update_inference_backend_hint()
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
            self.settings_page.hint_ffmpeg_active.setText(
                self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
            )
            self._update_inference_backend_hint()
            self.settings_page.lbl_status.setText(self.texts["reset_settings_done"])
            self.show_info_dialog(self.texts["success_title"], self.texts["reset_settings_done"], kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

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
        query = text_query if text_query else self.current_img_path
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
        confirmed = QMessageBox.question(
            self,
            self.texts["confirm_title"],
            self.texts["remove_library_confirm"].format(path=path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmed != QMessageBox.Yes:
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
        try:
            if not self.check_runtime_resources():
                self.library_page.lbl_status.setText(self.texts["model_features_disabled"])
                return
            self.switch_page("library")
            if self.indexing_controller.is_running():
                return
            self.library_page.btn_sync_db.setEnabled(False)
            self.library_page.btn_add_lib.setEnabled(False)
            self.library_page.progress_bar.setVisible(True)
            self.indexing_controller.start(target_lib=target_lib)
        except Exception as exc:
            self.show_error_dialog(self.texts["index_start_failed"], exc)

    def _update_indexing_progress(self, value, text):
        self.library_page.progress_bar.setValue(value)
        self.library_page.lbl_status.setText(text)

    def _finish_indexing(self, success, target_lib):
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.progress_bar.setVisible(False)
        self.refresh_library_table()
        if success:
            status_text = self.texts["index_updated_single"] if target_lib else self.texts["index_updated"]
        else:
            status_text = self.texts["index_failed"]
        self.library_page.lbl_status.setText(status_text)

    def handle_play(self, path, sec):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        if not self.preview_controller.play(path, sec):
            self.search_page.lbl_status.setText(self.texts["preview_failed"])

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

    def _shutdown_thread(self, thread, stop_first=False):
        if not thread or not thread.isRunning():
            return
        if stop_first and hasattr(thread, "stop"):
            thread.stop()
        thread.quit()
        if thread.wait(1500):
            return
        thread.requestInterruption()
        if thread.wait(1500):
            return
        thread.terminate()
        thread.wait(1000)

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
                if status.get("issue") == "cuda":
                    issue_text = self.texts["setting_runtime_issue_cuda"]
                elif status.get("issue") == "cudnn":
                    issue_text = self.texts["setting_runtime_issue_cudnn"]
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

        self.settings_page.hint_inference_backend.setText(
            self.texts["setting_inference_backend"].format(backend=backend_text)
            if backend_text else ""
        )
        self.settings_page.hint_inference_backend.setVisible(bool(backend_text))
        self.settings_page.hint_gpu_runtime.setText(self.texts["setting_gpu_runtime_link_only"])
        self.settings_page.hint_gpu_runtime.setVisible(show_help_link)
        self.settings_page.hint_inference_backend.style().unpolish(self.settings_page.hint_inference_backend)
        self.settings_page.hint_inference_backend.style().polish(self.settings_page.hint_inference_backend)

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
            for index, item in enumerate(detail["entries"], start=1):
                rows.append(
                    [
                        index,
                        item["library_path"],
                        item["video_rel_path"],
                        item["vector_file"],
                        item["index_file"],
                        self.texts["details_yes"] if item["vector_exists"] else self.texts["details_no"],
                        self.texts["details_yes"] if item["index_exists"] else self.texts["details_no"],
                    ]
                )
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
                export_default_name="local_vector_details.json",
            ).exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_vectors_load_failed"], exc)

    def show_network_link_details(self):
        try:
            detail = list_remote_link_details()
            headers = self.texts["network_links_headers"]
            rows = []
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
                export_default_name="remote_link_details.json",
                stretch_column=2,
                fixed_column_widths={
                    0: 52,
                    3: 86,
                    4: 116,
                    5: 116,
                },
            ).exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["network_links_load_failed"], exc)

    def open_network_download_cache_folder(self):
        cache_dirs = [
            os.path.join("data", "remote_build_cache"),
            os.path.join("data", "link_cache"),
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
            self.settings_page.hint_ffmpeg_active.setText(
                self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
            )

    def _apply_runtime_resource_status(self, status):
        self.models_ready = status["model_ready"]
        self.search_page.btn_search.setEnabled(self.models_ready)
        self.network_search_controller.refresh_status()
        self.library_page.btn_sync_db.setEnabled(status["resources_ready"])
        if not status["resources_ready"]:
            status_text = self.texts["model_features_disabled"]
            self.search_page.lbl_status.setText(status_text)
            self.link_page.lbl_build_status.setText(status_text)
            self.link_page.lbl_search_status.setText(status_text)
            self.library_page.lbl_status.setText(status_text)
