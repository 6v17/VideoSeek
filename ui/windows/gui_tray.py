"""System tray: minimize on close and background indexing."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QDialog, QStyle, QSystemTrayIcon

from src.app.config import DEFAULT_CONFIG, load_config
from ui.dialogs.indexing_close_choice import IndexingCloseChoiceDialog


def resolve_close_window_action(config=None):
    value = str((config or load_config()).get("close_window_action", DEFAULT_CONFIG["close_window_action"]))
    return value if value in ("exit", "tray") else DEFAULT_CONFIG["close_window_action"]


def build_tray_icon():
    app = QApplication.instance()
    if app is not None and not app.windowIcon().isNull():
        return app.windowIcon()
    style = app.style() if app is not None else QApplication.style()
    return style.standardIcon(QStyle.StandardPixmap.SP_MediaPlay)


class TrayGuiMixin:
    """Tray icon + menu; close-to-tray when configured."""

    def _init_system_tray(self):
        self._force_application_quit = False
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(build_tray_icon())
        self._tray.activated.connect(self._on_tray_activated)
        self._tray_show_action = QAction(self)
        self._tray_stop_index_action = QAction(self)
        self._tray_quit_action = QAction(self)
        self._tray_show_action.triggered.connect(self._show_main_window_from_tray)
        self._tray_stop_index_action.triggered.connect(self._stop_indexing_from_tray)
        self._tray_quit_action.triggered.connect(self._quit_application_from_tray)
        self._tray_menu = None
        self._rebuild_tray_menu()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.show()

    def _close_window_action(self):
        return resolve_close_window_action()

    def _rebuild_tray_menu(self):
        if not hasattr(self, "_tray_show_action"):
            return
        texts = getattr(self, "texts", {}) or {}
        self._tray_show_action.setText(texts.get("tray_menu_show", "Show VideoSeek"))
        self._tray_stop_index_action.setText(texts.get("tray_menu_stop_index", "Stop indexing"))
        self._tray_quit_action.setText(texts.get("tray_menu_quit", "Quit"))
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        menu.addAction(self._tray_show_action)
        menu.addAction(self._tray_stop_index_action)
        menu.addSeparator()
        menu.addAction(self._tray_quit_action)
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        self._sync_tray_stop_action()

    def _sync_tray_stop_action(self):
        indexing_running = bool(getattr(self, "indexing_controller", None) and self.indexing_controller.is_running())
        understanding_running = bool(
            getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()
        )
        running = indexing_running or understanding_running
        self._tray_stop_index_action.setVisible(running)
        self._tray_stop_index_action.setEnabled(running)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_main_window_from_tray()

    def _show_main_window_from_tray(self):
        state = self.windowState()
        minimized = bool(state & Qt.WindowState.WindowMinimized)
        if minimized:
            self.setWindowState(state & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.show()
        if not minimized:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _stop_indexing_from_tray(self):
        if getattr(self, "indexing_controller", None) and self.indexing_controller.request_stop():
            self.library_page.lbl_status.setText(self.texts.get("index_stop_requested", ""))
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.request_stop():
            self.understanding_page.lbl_status.setText(self.texts.get("understanding_stop_requested", ""))

    def _quit_application_from_tray(self):
        self._force_application_quit = True
        self.close()

    def _prompt_indexing_close_choice(self):
        dialog = IndexingCloseChoiceDialog(
            self.texts,
            parent=self,
            is_dark=getattr(self, "is_dark_mode", True),
            language=getattr(self, "language", "zh"),
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "cancel"
        return dialog.choice()

    def _hide_window_to_tray(self, event, *, indexing_active=False, notify_key="tray_running_background"):
        event.ignore()
        self.hide()
        if not self._tray.isVisible():
            self._tray.show()
        self._sync_tray_stop_action()
        self._tray.showMessage(
            self.texts.get("tray_title", "VideoSeek"),
            self.texts.get(
                "tray_indexing_background" if indexing_active else notify_key,
                self.texts.get(notify_key, ""),
            ),
            QSystemTrayIcon.MessageIcon.Information,
            4000 if indexing_active else 3000,
        )

    def _handle_indexing_window_close(self, event):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._close_when_indexing_stops = True
            if getattr(self, "indexing_controller", None) and self.indexing_controller.is_running():
                self.indexing_controller.request_stop()
                self.library_page.lbl_status.setText(self.texts.get("index_stop_requested", ""))
            elif getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
                self.understanding_controller.request_stop()
                self.understanding_page.lbl_status.setText(self.texts.get("understanding_stop_requested", ""))
            event.ignore()
            return True

        choice = self._prompt_indexing_close_choice()
        if choice == "cancel":
            event.ignore()
            return True
        if choice == "background":
            # Session-only: do not persist close_window_action; use Settings for a permanent default.
            self._hide_window_to_tray(event, indexing_active=True)
            return True
        if choice == "stop_exit":
            self._close_when_indexing_stops = True
            if getattr(self, "indexing_controller", None) and self.indexing_controller.is_running():
                self.indexing_controller.request_stop()
                self.library_page.lbl_status.setText(self.texts.get("index_stop_requested", ""))
            elif getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
                self.understanding_controller.request_stop()
                self.understanding_page.lbl_status.setText(self.texts.get("understanding_stop_requested", ""))
            event.ignore()
            return True
        event.ignore()
        return True

    def _try_minimize_to_tray_on_close(self, event):
        if self._force_application_quit:
            return False
        if getattr(self, "indexing_controller", None) and self.indexing_controller.is_running():
            return False
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return False
        if self._close_window_action() != "tray":
            return False
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False
        if self._preview_export_active or self._preview_export_queue:
            cancelled = self._cancel_all_preview_exports()
            if not cancelled:
                self.search_page.lbl_status.setText(
                    self.texts.get("preview_dialog_export_running", "Clip export is still running. Please wait.")
                )
                event.ignore()
                return True
        indexing_active = bool(self.indexing_controller.is_running())
        self._hide_window_to_tray(
            event,
            indexing_active=indexing_active,
            notify_key="tray_running_background",
        )
        return True

    def _shutdown_application(self, event):
        if hasattr(self, "_preview_dialog") and self._preview_dialog is not None:
            self._preview_dialog.shutdown_player(fast=True)
        self.search_controller.shutdown()
        self.video_download_controller.shutdown()
        from ui.threading_utils import shutdown_thread

        shutdown_thread(getattr(self, "_model_package_import_worker", None), stop_first=True)
        shutdown_thread(getattr(self, "_startup_migration_worker", None), stop_first=True, wait_ms=2000)
        shutdown_thread(getattr(self, "dialogue_index_worker", None), stop_first=True, wait_ms=2000)
        shutdown_thread(getattr(self, "remove_library_worker", None), stop_first=True, wait_ms=2000)
        shutdown_thread(getattr(self, "_local_vector_detail_worker", None), wait_ms=1500)
        self.mobile_bridge_controller.shutdown()
        if hasattr(self, "agent_api_controller"):
            self.agent_api_controller.shutdown()
        self.indexing_controller.shutdown()
        if getattr(self, "understanding_controller", None):
            self.understanding_controller.shutdown()
        self.app_meta_controller.shutdown()
        self.runtime_resource_controller.shutdown()
        self.preview_controller.shutdown()
        if hasattr(self, "_tray"):
            self._tray.hide()
        app = QApplication.instance()
        server = getattr(app, "_videoseek_single_instance", None) if app is not None else None
        if server is not None and hasattr(server, "close"):
            try:
                server.close()
            except Exception:
                pass
            try:
                setattr(app, "_videoseek_single_instance", None)
            except Exception:
                pass
        event.accept()
        if app is not None:
            app.quit()
