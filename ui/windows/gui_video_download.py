"""Video download page actions — mixed into MainWindow."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog

from src.app.config import load_config, save_config
from src.services.legacy_network_cleanup_service import clear_legacy_network_assets, scan_legacy_network_assets
from src.services.video_download_service import get_download_default_dir
from src.utils import open_folder_in_explorer


class VideoDownloadGuiMixin:
    def start_video_download_probe(self):
        if not self._ensure_startup_migration_idle("feature_video_download"):
            return
        self.video_download_controller.start_probe(self.link_page.links_input.toPlainText())

    def start_video_download(self):
        if not self._ensure_startup_migration_idle("feature_video_download"):
            return
        self.video_download_controller.start_download_all()

    def clear_video_download_content(self):
        self.video_download_controller.reset_after_clear()

    def choose_download_default_dir(self):
        current = get_download_default_dir()
        path = QFileDialog.getExistingDirectory(
            self,
            self.texts.get("download_choose_dir_title", ""),
            current,
        )
        if not path:
            return
        config = load_config()
        config["download_default_dir"] = path
        save_config(config)
        self.video_download_controller.refresh_default_dir_label()

    def browse_download_cookie_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts.get("download_cookie_browse_title", ""),
            "",
            "Text files (*.txt);;All files (*.*)",
        )
        if not path:
            return
        self.link_page.set_cookie_file_path(path)
        self.video_download_controller.save_settings_to_config()
        self.video_download_controller.refresh_cookie_admin_hint()

    def clear_download_cookie_file(self):
        self.link_page.clear_cookie_file()
        self.video_download_controller.save_settings_to_config()
        self.video_download_controller.refresh_cookie_admin_hint()

    def show_download_cookie_help(self):
        self.show_info_dialog(
            self.texts.get("download_cookie_help_title", ""),
            self.texts.get("download_cookie_help_body", ""),
            kind="info",
        )

    def _on_download_settings_changed(self, *_args):
        self.video_download_controller.save_settings_to_config()

    def open_download_default_dir(self):
        path = get_download_default_dir()
        os.makedirs(path, exist_ok=True)
        open_folder_in_explorer(path)

    def clear_legacy_network_data(self):
        scan = scan_legacy_network_assets()
        if not scan.paths:
            self.show_info_dialog(
                self.texts.get("download_clear_legacy_title", ""),
                self.texts.get("download_clear_legacy_empty", ""),
                kind="info",
            )
            return
        size_mb = max(1, int(scan.total_bytes / (1024 * 1024)))
        confirm = self.texts.get("download_clear_legacy_confirm", "").format(
            count=len(scan.paths),
            size=size_mb,
        )
        if not self.show_confirm_dialog(self.texts.get("download_clear_legacy_title", ""), confirm):
            return
        result = clear_legacy_network_assets()
        if result.errors:
            self.show_error_dialog(
                self.texts.get("download_clear_legacy_title", ""),
                "\n".join(result.errors),
            )
            return
        self.show_info_dialog(
            self.texts.get("download_clear_legacy_title", ""),
            self.texts.get("download_clear_legacy_done", "").format(
                count=result.deleted_count,
                size=max(1, int(result.freed_bytes / (1024 * 1024))),
            ),
            kind="success",
        )
