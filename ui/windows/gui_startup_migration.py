"""Non-blocking startup data migration — banner, worker, and action guards."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from src.app.config import set_startup_migration_summary
from src.app.logging_utils import get_logger
from ui.threading_utils import shutdown_thread
from ui.widgets.styles import set_runtime_banner_warn
from ui.workers import StartupMigrationWorker

logger = get_logger("gui.startup_migration")


class StartupMigrationGuiMixin:
    """Background startup migration with guarded indexing/search actions."""

    def _init_startup_migration_state(self):
        self._startup_migration_busy = False
        self._startup_migration_worker = None
        self._startup_migration_finish_scheduled = False

    def begin_startup_migration(self):
        if getattr(self, "startup_cancelled", False):
            return
        from src.storage.migration_runner import run_startup_migration_quick

        try:
            summary = run_startup_migration_quick()
        except Exception as exc:
            logger.exception("Startup migration quick check failed")
            QMessageBox.critical(
                self,
                self.texts["startup_migration_failed_title"],
                self.texts["startup_migration_failed_body"].format(error=exc),
            )
            self.close()
            return

        set_startup_migration_summary(summary)
        if summary.get("needs_background"):
            self._startup_migration_busy = True
            self._apply_startup_migration_lock(True)
            self._update_startup_migration_banner(0, self.texts["startup_migration_running"])
            self._start_startup_migration_worker()
            return
        self._on_startup_migration_finished(summary)

    def _start_startup_migration_worker(self):
        shutdown_thread(getattr(self, "_startup_migration_worker", None))
        self._startup_migration_worker = StartupMigrationWorker()
        self._startup_migration_worker.progress_signal.connect(self._on_startup_migration_progress)
        self._startup_migration_worker.finished_signal.connect(self._on_startup_migration_finished)
        self._startup_migration_worker.error_signal.connect(self._on_startup_migration_failed)
        self._startup_migration_worker.start()

    def _on_startup_migration_progress(self, value, text):
        self._update_startup_migration_banner(int(value), str(text))

    def _on_startup_migration_finished(self, summary):
        shutdown_thread(getattr(self, "_startup_migration_worker", None))
        self._startup_migration_worker = None
        self._startup_migration_busy = False
        self._apply_startup_migration_lock(False)
        self._hide_startup_migration_banner()
        set_startup_migration_summary(summary)
        self._show_startup_migration_notice()
        if not getattr(self, "_startup_complete", False):
            self._finish_startup_sequence()
        else:
            self.refresh_library_table()

    def _on_startup_migration_failed(self, error_text):
        shutdown_thread(getattr(self, "_startup_migration_worker", None))
        self._startup_migration_worker = None
        self._startup_migration_busy = False
        self._apply_startup_migration_lock(False)
        self._hide_startup_migration_banner()
        logger.error("Background startup migration failed: %s", error_text)
        QMessageBox.critical(
            self,
            self.texts["startup_migration_failed_title"],
            self.texts["startup_migration_failed_body"].format(error=error_text),
        )

    def is_startup_migration_busy(self):
        return bool(getattr(self, "_startup_migration_busy", False))

    def _ensure_startup_migration_idle(self, feature_key: str) -> bool:
        if not self.is_startup_migration_busy():
            return True
        self.show_info_dialog(
            self.texts["startup_migration_busy_title"],
            self.texts["startup_migration_busy_body"].format(feature=self.texts.get(feature_key, feature_key)),
            kind="warning",
        )
        return False

    def _apply_startup_migration_lock(self, locked: bool):
        widgets = [
            self.search_page.btn_search,
            self.library_page.btn_sync_db,
            self.library_page.btn_refresh_visual_library,
            self.link_page.btn_probe,
            self.link_page.btn_download,
            self.settings_page.btn_save,
        ]
        for widget in widgets:
            widget.setEnabled(not locked)

    def _update_startup_migration_banner(self, value: int, text: str):
        hint = self.sidebar.runtime_hint
        hint.setText(self.texts["startup_migration_banner"].format(percent=int(value), message=text))
        hint.setProperty("state", "warn")
        hint.show()
        for page in self._iter_runtime_banner_pages():
            banner = page.header.runtime_banner
            banner_text = page.header.runtime_banner_text
            action = page.header.runtime_banner_action
            action.hide()
            banner_text.setText(self.texts["startup_migration_banner"].format(percent=int(value), message=text))
            set_runtime_banner_warn(banner, True)
            banner.show()

    def _hide_startup_migration_banner(self):
        self.sidebar.runtime_hint.hide()
        for page in self._iter_runtime_banner_pages():
            page.header.runtime_banner.hide()
            page.header.runtime_banner_action.show()
        if hasattr(self, "push_resources_status"):
            self.push_resources_status()
