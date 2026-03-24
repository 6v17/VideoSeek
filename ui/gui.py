import os
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QLabel, QMainWindow, QMessageBox, QScrollArea, QStackedWidget, QVBoxLayout, QWidget, QHBoxLayout

from src.app.config import DEFAULT_CONFIG, get_app_version, load_config, save_config
from src.app.i18n import get_texts
from src.services.library_service import add_library, list_libraries, remove_library as remove_library_entry
from src.services.notice_service import get_local_notice_payload
from src.workflows.update_video import delete_physical_video_data
from src.utils import build_preview_cache_path, create_preview_clip, open_folder_in_explorer, open_in_explorer
from src.services.version_service import get_local_version_status
from ui.components import LibraryPage, NavigationSidebar, SearchPage, SettingsPage
from ui.dialogs import AboutDialog, AppMessageDialog, NoticeDialog
from ui.styles import DARK_STYLE, LIGHT_STYLE
from ui.table_views import populate_library_table, populate_result_table
from ui.workers import IndexUpdateWorker, NoticeFetchWorker, SearchWorker, ThumbLoader, VersionCheckWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_img_path = None
        self.worker = None
        self.up_worker = None
        self.thumb_thread = None
        self.start_time = 0.0
        self.current_preview_path = None
        self.current_update_target = None
        self.version_info = None
        self.version_worker = None
        self.notice_payload = None
        self.notice_worker = None

        cfg = load_config()
        self.is_dark_mode = cfg.get("theme", "dark") == "dark"
        self.language = cfg.get("language", "zh")
        self.texts = get_texts(self.language)
        self.version_info = get_local_version_status(self.language)
        self.notice_payload = get_local_notice_payload(self.language)

        self.init_ui()
        self.media_player = QMediaPlayer()
        self.media_player.setVideoOutput(self.video_widget)
        self.load_settings_values()
        self.apply_texts()
        self.refresh_library_table()
        self.apply_theme()
        self.start_version_check()
        self.start_notice_fetch()

    def init_ui(self):
        config = load_config()
        self.setWindowTitle(f"VideoSeek v{get_app_version()}")
        self.resize(1280, 820)
        self.setMinimumSize(1080, 700)

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

    def start_version_check(self):
        if self.version_worker and self.version_worker.isRunning():
            return
        self.version_worker = VersionCheckWorker(self.language)
        self.version_worker.result_ready.connect(self._update_version_info)
        self.version_worker.start()

    def _update_version_info(self, version_info):
        self.version_info = version_info
        self.apply_texts()

    def start_notice_fetch(self):
        if self.notice_worker and self.notice_worker.isRunning():
            return
        self.notice_worker = NoticeFetchWorker(self.language)
        self.notice_worker.result_ready.connect(self._update_notice_payload)
        self.notice_worker.start()

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
            save_config(config)
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
            self.load_settings_values()
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
            is_indexing = self.up_worker is not None and self.up_worker.isRunning()
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
        if self.thumb_thread and self.thumb_thread.isRunning():
            self.thumb_thread.stop()
            self.thumb_thread.wait()

        text_query = self.search_page.text_search.text().strip()
        query = text_query if text_query else self.current_img_path
        if not query:
            self.search_page.lbl_status.setText(self.texts["empty_query"])
            return

        self.switch_page("search")
        self.start_time = time.time()
        self.search_page.btn_search.setEnabled(False)
        self.search_page.lbl_status.setText(self.texts["searching"])
        self.worker = SearchWorker(query, bool(text_query))
        self.worker.result_ready.connect(self.display_results)
        self.worker.finished.connect(lambda: self.search_page.btn_search.setEnabled(True))
        self.worker.start()

    def display_results(self, results):
        if not results:
            self.result_table.setRowCount(0)
            self.search_page.lbl_status.setText(self.texts["no_results"])
            return

        populate_result_table(self.result_table, results, self.handle_play, open_in_explorer, self.texts)
        duration = time.time() - self.start_time
        self.search_page.lbl_status.setText(self.texts["search_done"].format(duration=duration, count=len(results)))

        self.thumb_thread = ThumbLoader(results)
        self.thumb_thread.thumb_ready.connect(self.update_row_thumb)
        self.thumb_thread.start()

    def update_row_thumb(self, row, pixmap):
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap)
        self.result_table.setCellWidget(row, 1, label)

    def clear_all_content(self):
        self.current_img_path = None
        self.search_page.text_search.clear()
        self.search_page.img_label.clear()
        self.search_page.img_label.setText(self.texts["image_drop_hint"])
        self.result_table.setRowCount(0)
        self.media_player.stop()
        if self.thumb_thread:
            self.thumb_thread.stop()
        self.search_page.lbl_status.setText(self.texts["ready"])

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
            self.switch_page("library")
            if self.up_worker and self.up_worker.isRunning():
                return
            self.library_page.btn_sync_db.setEnabled(False)
            self.library_page.btn_add_lib.setEnabled(False)
            self.library_page.progress_bar.setVisible(True)
            self.current_update_target = target_lib
            self.up_worker = IndexUpdateWorker(target_lib=target_lib)
            self.up_worker.progress_signal.connect(
                lambda value, text: (self.library_page.progress_bar.setValue(value), self.library_page.lbl_status.setText(text))
            )
            self.up_worker.finished_signal.connect(self.on_update_finished)
            self.up_worker.start()
        except Exception as exc:
            self.show_error_dialog(self.texts["index_start_failed"], exc)

    def on_update_finished(self, success):
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.progress_bar.setVisible(False)
        self.refresh_library_table()
        if success:
            status_text = self.texts["index_updated_single"] if self.current_update_target else self.texts["index_updated"]
        else:
            status_text = self.texts["index_failed"]
        self.library_page.lbl_status.setText(status_text)
        self.current_update_target = None

    def handle_play(self, path, sec):
        self.media_player.stop()
        self.media_player.setSource(QUrl())

        cache_path = build_preview_cache_path(path, sec)
        result = create_preview_clip(path, sec, cache_path)
        if result.returncode == 0:
            self._cleanup_previous_preview()
            self.current_preview_path = cache_path
            self.media_player.setSource(QUrl.fromLocalFile(cache_path))
            self.media_player.play()
        else:
            if os.path.exists(cache_path):
                os.remove(cache_path)
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
        self.start_version_check()
        self.start_notice_fetch()

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
        if self.worker:
            self.worker.quit()
        if self.up_worker:
            self.up_worker.quit()
        if self.thumb_thread:
            self.thumb_thread.stop()
        if self.version_worker:
            self.version_worker.quit()
        if self.notice_worker:
            self.notice_worker.quit()
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self._cleanup_previous_preview()
        event.accept()

    def _set_image_query(self, path, clear_text):
        self.current_img_path = path
        self.search_page.img_label.setPixmap(
            QPixmap(path).scaled(420, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        if clear_text:
            self.search_page.text_search.clear()
        self.search_page.lbl_status.setText(self.texts["image_loaded"])

    def _cleanup_previous_preview(self):
        if not self.current_preview_path:
            return
        if os.path.exists(self.current_preview_path):
            try:
                os.remove(self.current_preview_path)
            except OSError:
                pass
        self.current_preview_path = None
