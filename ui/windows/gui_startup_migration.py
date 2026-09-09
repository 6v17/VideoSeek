"""Manual / optional data migration — banner, worker, and action guards.

Heavy npy/Lance upgrades are no longer auto-run at launch. Launch only does a
quick check; if work is needed, a dismissible tip points users to Settings.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from src.app.config import set_startup_migration_summary
from src.app.logging_utils import get_logger
from ui.threading_utils import shutdown_thread
from ui.widgets.styles import set_runtime_banner_warn
from ui.workers import StartupMigrationWorker

logger = get_logger("gui.startup_migration")


class StartupMigrationGuiMixin:
    """Background data migration with guarded indexing/search actions."""

    def _init_startup_migration_state(self):
        self._startup_migration_busy = False
        self._startup_migration_worker = None
        self._startup_migration_finish_scheduled = False
        self._legacy_migration_tip_visible = False

    def begin_startup_migration(self):
        """Post-show bootstrap: quick check only; never auto-start heavy migrate."""
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
            logger.info("Legacy data migration needed; deferring to Settings (no auto-run)")
            self._legacy_migration_tip_visible = True
            self._refresh_legacy_migration_settings_ui()
            if not getattr(self, "_startup_complete", False):
                self._finish_startup_sequence()
            self._show_legacy_migration_tip_banner()
            return

        self._legacy_migration_tip_visible = False
        self._on_startup_migration_finished(summary)

    def start_manual_legacy_migration(self) -> bool:
        """User-triggered migrate from Settings. Returns False if already busy."""
        if self.is_startup_migration_busy():
            self._ensure_startup_migration_idle("feature_settings")
            return False
        from src.storage.migration_runner import needs_background_startup_migration

        if not needs_background_startup_migration():
            self.show_info_dialog(
                self.texts.get("legacy_migration_up_to_date_title", "Data layout"),
                self.texts.get(
                    "legacy_migration_up_to_date_body",
                    "Local search data is already up to date. No migration needed.",
                ),
                kind="info",
            )
            self._legacy_migration_tip_visible = False
            self._refresh_legacy_migration_settings_ui()
            if hasattr(self, "push_resources_status"):
                self.push_resources_status()
            return False

        self._legacy_migration_tip_visible = False
        self._startup_migration_busy = True
        self._apply_startup_migration_lock(True)
        self._update_startup_migration_banner(0, self.texts["startup_migration_running"])
        self._refresh_legacy_migration_settings_ui()
        self._start_startup_migration_worker()
        return True

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
        self._legacy_migration_tip_visible = False
        self._apply_startup_migration_lock(False)
        self._hide_startup_migration_banner()
        set_startup_migration_summary(summary)
        self._refresh_legacy_migration_settings_ui()
        self._show_startup_migration_notice()
        if not getattr(self, "_startup_complete", False):
            self._finish_startup_sequence()
        else:
            self.refresh_library_table()
            if hasattr(self, "push_resources_status"):
                self.push_resources_status()

    def _on_startup_migration_failed(self, error_text):
        shutdown_thread(getattr(self, "_startup_migration_worker", None))
        self._startup_migration_worker = None
        self._startup_migration_busy = False
        self._apply_startup_migration_lock(False)
        self._hide_startup_migration_banner()
        self._refresh_legacy_migration_settings_ui()
        logger.error("Background data migration failed: %s", error_text)
        QMessageBox.critical(
            self,
            self.texts["startup_migration_failed_title"],
            self.texts["startup_migration_failed_body"].format(error=error_text),
        )
        # Tip can come back if legacy work is still pending.
        from src.storage.migration_runner import needs_background_startup_migration

        if needs_background_startup_migration():
            self._legacy_migration_tip_visible = True
            self._show_legacy_migration_tip_banner()

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
        btn_migrate = getattr(self.settings_page, "btn_migrate_legacy_index", None)
        if btn_migrate is not None:
            widgets.append(btn_migrate)
        for widget in widgets:
            widget.setEnabled(not locked)
        if not locked:
            self._refresh_legacy_migration_settings_ui()

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
        if hasattr(self, "_start_runtime_inline_tip_breathing"):
            self._start_runtime_inline_tip_breathing()

    def _hide_startup_migration_banner(self):
        self.sidebar.runtime_hint.hide()
        for page in self._iter_runtime_banner_pages():
            page.header.runtime_banner.setProperty("tipKind", "")
            page.header.runtime_banner.hide()
            page.header.runtime_banner_action.show()
        if hasattr(self, "_stop_runtime_inline_tip_breathing"):
            self._stop_runtime_inline_tip_breathing()
        if hasattr(self, "push_resources_status"):
            self.push_resources_status()

    def _show_legacy_migration_tip_banner(self):
        if not getattr(self, "_legacy_migration_tip_visible", False):
            return
        if self.is_startup_migration_busy():
            return
        tip = self.texts.get(
            "legacy_migration_tip_banner",
            "Legacy search index detected. Migrate it under Settings when ready.",
        )
        action_text = self.texts.get("legacy_migration_tip_action", "Open Settings")
        hint = self.sidebar.runtime_hint
        hint.setText(tip)
        hint.setProperty("state", "warn")
        hint.show()
        for page in self._iter_runtime_banner_pages():
            banner = page.header.runtime_banner
            banner_text = page.header.runtime_banner_text
            action = page.header.runtime_banner_action
            banner_text.setText(tip)
            action.setText(action_text)
            banner.setProperty("tipKind", "legacy_migration")
            action.show()
            set_runtime_banner_warn(banner, True)
            banner.show()
        if hasattr(self, "_start_runtime_inline_tip_breathing"):
            self._start_runtime_inline_tip_breathing()

    def _dismiss_legacy_migration_tip(self):
        self._legacy_migration_tip_visible = False
        self.sidebar.runtime_hint.hide()
        if hasattr(self, "push_resources_status"):
            self.push_resources_status()

    def _open_settings_for_legacy_migration(self):
        self._dismiss_legacy_migration_tip()
        try:
            self.switch_page("settings")
        except Exception:
            try:
                self.stack.setCurrentWidget(self.settings_page)
            except Exception:
                pass
        btn = getattr(self.settings_page, "btn_migrate_legacy_index", None)
        if btn is not None:
            btn.setFocus()

    def _refresh_legacy_migration_settings_ui(self):
        page = getattr(self, "settings_page", None)
        if page is None:
            return
        status = getattr(page, "lbl_legacy_migration_status", None)
        btn = getattr(page, "btn_migrate_legacy_index", None)
        if status is None and btn is None:
            return
        from src.storage.migration_runner import needs_background_startup_migration

        busy = self.is_startup_migration_busy()
        needed = False if busy else needs_background_startup_migration()
        if status is not None:
            if busy:
                status.setText(
                    self.texts.get("legacy_migration_status_busy", "Migration in progress…")
                )
            elif needed:
                status.setText(
                    self.texts.get(
                        "legacy_migration_status_needed",
                        "Legacy index found — migrate when convenient.",
                    )
                )
            else:
                status.setText(
                    self.texts.get("legacy_migration_status_ready", "Already up to date.")
                )
        if btn is not None and not busy:
            btn.setEnabled(True)
