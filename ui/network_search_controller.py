import time

from PySide6.QtCore import QObject

from src.services.remote_library_service import (
    export_remote_library_zip,
    get_remote_library_status,
    import_remote_library_zip,
)
from ui.network_build_presenter import format_build_finished_status, format_build_progress_text
from ui.table_views import populate_network_result_table
from ui.workers import RemoteLibraryBuildWorker, RemoteSearchWorker


class NetworkSearchController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.search_worker = None
        self.build_worker = None
        self.start_time = 0.0

    def start_search(self, query_data, is_text):
        if self.search_worker and self.search_worker.isRunning():
            return
        self.start_time = time.time()
        self.parent_window.link_page.btn_run.setEnabled(False)
        self.parent_window.link_page.lbl_search_status.setText(self.parent_window.texts["searching"])
        self.parent_window.link_page.result_table.setRowCount(0)

        self.search_worker = RemoteSearchWorker(query_data, is_text)
        self.search_worker.result_ready.connect(self._display_results)
        self.search_worker.error_signal.connect(self._handle_search_error)
        self.search_worker.finished.connect(self._finish_search)
        self.search_worker.start()

    def start_build(self, links, mode):
        if self.build_worker and self.build_worker.isRunning():
            return
        self.parent_window.link_page.btn_build.setEnabled(False)
        self.parent_window.link_page.progress_bar.setRange(0, 100)
        self.parent_window.link_page.progress_bar.setValue(0)
        self.parent_window.link_page.progress_bar.setVisible(True)
        self.parent_window.link_page.lbl_build_status.setText(self.parent_window.texts["network_building"])
        self.build_worker = RemoteLibraryBuildWorker(links, mode)
        self.build_worker.progress_signal.connect(self._on_build_progress)
        self.build_worker.finished_signal.connect(self._on_build_finished)
        self.build_worker.error_signal.connect(self._on_build_error)
        self.build_worker.start()

    def export_zip(self, zip_path):
        export_remote_library_zip(zip_path)
        self.parent_window.link_page.lbl_build_status.setText(
            self.parent_window.texts["network_export_done"].format(path=zip_path)
        )

    def import_zip(self, zip_path):
        status = import_remote_library_zip(zip_path)
        if status.get("ready"):
            self.parent_window.link_page.lbl_build_status.setText(
                self.parent_window.texts["network_import_done"].format(path=zip_path)
            )
        self.refresh_status()

    def clear(self):
        self.parent_window.link_page.input_link.clear()
        self.parent_window.network_query_img_path = None
        self.parent_window.link_page.query_image_label.clear()
        self.parent_window.link_page.query_image_label.setText(
            self.parent_window.texts["network_image_preview_hint"]
        )
        self.parent_window.link_page.result_table.setRowCount(0)
        self.parent_window.link_page.progress_bar.setRange(0, 100)
        self.parent_window.link_page.progress_bar.setValue(0)
        self.parent_window.link_page.progress_bar.setVisible(False)
        self.parent_window.link_page.lbl_build_status.setText(self.parent_window.texts["ready"])
        self.parent_window.link_page.lbl_search_status.setText(self.parent_window.texts["ready"])

    def refresh_status(self):
        status = get_remote_library_status()
        self.parent_window.link_page.btn_run.setEnabled(status["ready"] and self.parent_window.models_ready)
        if not status["ready"]:
            self.parent_window.link_page.lbl_search_status.setText(
                self.parent_window.texts["network_index_missing"]
            )

    def shutdown(self):
        self._shutdown_thread(self.search_worker)
        self._shutdown_thread(self.build_worker)

    def _display_results(self, results):
        if not results:
            self.parent_window.link_page.lbl_search_status.setText(self.parent_window.texts["no_results"])
            return
        populate_network_result_table(self.parent_window.link_page.result_table, results, self.parent_window.texts)
        elapsed = time.time() - self.start_time
        self.parent_window.link_page.lbl_search_status.setText(
            self.parent_window.texts["search_done"].format(duration=elapsed, count=len(results))
        )

    def _finish_search(self):
        self.parent_window.link_page.btn_run.setEnabled(True)

    def _handle_search_error(self, error_text):
        self.parent_window.link_page.lbl_search_status.setText(self.parent_window.texts["search_failed"])
        self.parent_window.show_error_dialog(self.parent_window.texts["search_failed"], error_text)

    def _on_build_progress(self, value, text):
        self.parent_window.link_page.progress_bar.setVisible(True)
        self.parent_window.link_page.progress_bar.setValue(int(value))
        self.parent_window.link_page.lbl_build_status.setText(
            format_build_progress_text(str(text), self.parent_window.texts)
        )

    def _on_build_finished(self, status):
        self.parent_window.link_page.btn_build.setEnabled(True)
        self.parent_window.link_page.btn_run.setEnabled(bool(status.get("ready", False)) and self.parent_window.models_ready)
        self.parent_window.link_page.progress_bar.setValue(0)
        self.parent_window.link_page.progress_bar.setVisible(False)
        self.parent_window.link_page.lbl_build_status.setText(
            format_build_finished_status(
                status,
                self.parent_window.texts,
            )
        )

    def _on_build_error(self, error_text):
        self.parent_window.link_page.btn_build.setEnabled(True)
        self.parent_window.link_page.progress_bar.setValue(0)
        self.parent_window.link_page.progress_bar.setVisible(False)
        self.parent_window.show_error_dialog(self.parent_window.texts["network_build_failed"], error_text)
        self.refresh_status()

    def _shutdown_thread(self, thread):
        if not thread or not thread.isRunning():
            return
        thread.quit()
        if thread.wait(1500):
            return
        thread.requestInterruption()
        if thread.wait(1500):
            return
        thread.terminate()
        thread.wait(1000)
