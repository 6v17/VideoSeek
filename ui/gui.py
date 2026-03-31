import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget, QHBoxLayout

from src.app.config import DEFAULT_CONFIG, get_app_version, load_config, save_config
from src.app.i18n import get_texts
from src.services.library_service import add_library, list_libraries, remove_library as remove_library_entry
from src.services.notice_service import get_local_notice_payload
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
from ui.components import LibraryPage, NavigationSidebar, SearchPage, SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, NoticeDialog
from ui.indexing_controller import IndexingController
from ui.layout import WINDOW_SIZES, apply_window_size
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
        self.version_info = None
        self.notice_payload = None
        self.models_ready = True

        cfg = load_config()
        self.is_dark_mode = cfg.get("theme", "dark") == "dark"
        self.language = cfg.get("language", "zh")
        self.texts = get_texts(self.language)
        self.version_info = get_local_version_status(self.language)
        self.notice_payload = get_local_notice_payload(self.language)

        self.init_ui()
        self.app_meta_controller = AppMetaController(self)
        self.app_meta_controller.version_ready.connect(self._update_version_info)
        self.app_meta_controller.notice_ready.connect(self._update_notice_payload)
        self.indexing_controller = IndexingController(self)
        self.indexing_controller.status_changed.connect(self._update_indexing_progress)
        self.indexing_controller.finished.connect(self._finish_indexing)
        self.preview_controller = PreviewController(self)
        self.search_controller = SearchController(self)
        self.runtime_resource_controller = RuntimeResourceController(self)
        self.runtime_resource_controller.startup_cancelled.connect(self._handle_runtime_resource_exit)
        self.runtime_resource_controller.resources_ready.connect(self._finish_runtime_resource_download)
        self.runtime_resource_controller.status_changed.connect(self._apply_runtime_resource_status)
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        sync_model_dir_to_config()
        sync_ffmpeg_path_to_config()
        self.load_settings_values()
        self.apply_texts()
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
        self.library_page = LibraryPage()
        self.settings_page = SettingsPage()
        self.pages.addWidget(self._build_scroll_page(self.search_page))
        self.pages.addWidget(self._build_scroll_page(self.library_page))
        self.pages.addWidget(self._build_scroll_page(self.settings_page))
        content_layout.addWidget(self.pages)
        main_layout.addWidget(self.content, 1)

        self.search_page.preview_placeholder.hide()
        self.video_widget = QVideoWidget()
        self.search_page.preview_host_layout.addWidget(self.video_widget)

        self.result_table = self.search_page.result_table

        self.sidebar.btn_page_search.clicked.connect(lambda: self.switch_page("search"))
        self.sidebar.btn_page_library.clicked.connect(lambda: self.switch_page("library"))
        self.sidebar.btn_page_settings.clicked.connect(lambda: self.switch_page("settings"))
        self.sidebar.btn_theme.clicked.connect(self.toggle_theme)
        self.sidebar.btn_language.clicked.connect(self.toggle_language)
        self.sidebar.btn_about.clicked.connect(self.show_about)
        self.sidebar.btn_notice.clicked.connect(self.show_notice)

        self.search_page.btn_browse.clicked.connect(self.upload_file)
        self.search_page.btn_search.clicked.connect(self.start_search)
        self.search_page.btn_clear.clicked.connect(self.clear_all_content)
        self.search_page.img_label.mousePressEvent = lambda e: self.upload_file()

        self.library_page.btn_add_lib.clicked.connect(self.select_video_folder)
        self.library_page.btn_sync_db.clicked.connect(self.start_update_index)

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
        mapping = {"search": 0, "library": 1, "settings": 2}
        self.pages.setCurrentIndex(mapping[page_name])
        self.sidebar.set_current_page(page_name)

    def _update_version_info(self, version_info):
        self.version_info = version_info
        self.apply_texts()

    def _update_notice_payload(self, notice_payload):
        self.notice_payload = notice_payload

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

        self.search_page.header.title.setText(t["search_page_title"])
        self.search_page.header.subtitle.setText(t["search_page_desc"])
        self.search_page.controls_title.setText(t["controls_label"])
        self.search_page.controls_hint.setText(t["controls_hint"])
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

        self.library_page.header.title.setText(t["library_page_title"])
        self.library_page.header.subtitle.setText(t["library_page_desc"])
        self.library_page.table_title.setText(t["library_table_title"])
        self.library_page.btn_add_lib.setText(t["add_folder"])
        self.library_page.btn_sync_db.setText(t["update_index"])

        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.setText(t["settings_page_desc"])
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        self.settings_page.hint_ffmpeg_active.setText(
            t["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        )

        if not self.current_img_path and not self.search_page.img_label.pixmap():
            self.search_page.img_label.setText(t["image_drop_hint"])

        self.search_page.lbl_status.setText(t["ready"])
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
        self.settings_page.input_ffmpeg_path.setText(config.get("ffmpeg_path", DEFAULT_CONFIG["ffmpeg_path"]))
        self.settings_page.input_model_dir.setText(config.get("model_dir", DEFAULT_CONFIG["model_dir"]))
        self.settings_page.hint_ffmpeg_active.setText(
            self.texts["setting_ffmpeg_active"].format(path=get_ffmpeg_status_text())
        )

    def save_settings(self):
        try:
            config = load_config()
            config["fps"] = self.settings_page.input_fps.value()
            config["search_top_k"] = self.settings_page.input_top_k.value()
            config["preview_seconds"] = self.settings_page.input_preview_seconds.value()
            config["preview_width"] = self.settings_page.input_preview_width.value()
            config["preview_height"] = self.settings_page.input_preview_height.value()
            config["thumb_width"] = self.settings_page.input_thumb_width.value()
            config["thumb_height"] = self.settings_page.input_thumb_height.value()
            config["ffmpeg_path"] = self.settings_page.input_ffmpeg_path.text().strip()
            config["model_dir"] = self.settings_page.input_model_dir.text().strip() or DEFAULT_CONFIG["model_dir"]
            save_config(config)
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
            self.settings_page.lbl_status.setText(self.texts["saved_settings"])
            self.show_info_dialog(self.texts["success_title"], self.texts["saved_settings"], kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def reset_settings(self):
        try:
            config = load_config()
            for key, value in DEFAULT_CONFIG.items():
                if key in {"theme", "language"}:
                    continue
                config[key] = value
            save_config(config)
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
            self.settings_page.lbl_status.setText(self.texts["reset_settings_done"])
            self.show_info_dialog(self.texts["success_title"], self.texts["reset_settings_done"], kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts["settings_save_failed"], exc)

    def show_notice(self):
        NoticeDialog(self, self.is_dark_mode, self.language, notice=self.notice_payload).exec()

    def show_about(self):
        AboutDialog(self, self.is_dark_mode, self.language, version_info=self.version_info).exec()

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

    def clear_all_content(self):
        self.current_img_path = None
        self.search_page.text_search.clear()
        self.search_page.img_label.clear()
        self.search_page.img_label.setText(self.texts["image_drop_hint"])
        self.search_controller.clear_results()
        self.media_player.stop()
        self.search_page.lbl_status.setText(self.texts["ready"])

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
        self.apply_texts()
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
            self.upload_file_path(urls[0].toLocalFile())

    def upload_file_path(self, path):
        self._set_image_query(path, clear_text=False)
        self.switch_page("search")

    def closeEvent(self, event):
        self.search_controller.shutdown()
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

    def _handle_runtime_resource_exit(self):
        self.startup_cancelled = True
        self.close()

    def check_runtime_resources(self, show_dialog=True):
        return self.runtime_resource_controller.check_resources(show_dialog=show_dialog)

    def start_runtime_resource_download(self):
        self.runtime_resource_controller.start_download()

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
        self.library_page.btn_sync_db.setEnabled(status["resources_ready"])
        if not status["resources_ready"]:
            status_text = self.texts["model_features_disabled"]
            self.search_page.lbl_status.setText(status_text)
            self.library_page.lbl_status.setText(status_text)
