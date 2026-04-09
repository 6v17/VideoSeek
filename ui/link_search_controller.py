import time

from PySide6.QtCore import QObject

from ui.table_views import populate_link_result_table
from ui.workers import LinkSearchWorker


class LinkSearchController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.start_time = 0.0

    def start_search(self, link, mode):
        if self.worker and self.worker.isRunning():
            return

        self.start_time = time.time()
        self.parent_window.link_page.btn_run.setEnabled(False)
        self.parent_window.link_page.progress_bar.setValue(0)
        self.parent_window.link_page.lbl_status.setText(self.parent_window.texts["link_search_starting"])
        self.parent_window.link_page.result_table.setRowCount(0)

        self.worker = LinkSearchWorker(link, mode)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.result_ready.connect(self._display_results)
        self.worker.error_signal.connect(self._handle_error)
        self.worker.finished.connect(self._finish_search)
        self.worker.start()

    def clear(self):
        self.parent_window.link_page.input_link.clear()
        self.parent_window.link_page.progress_bar.setValue(0)
        self.parent_window.link_page.result_table.setRowCount(0)
        self.parent_window.link_page.lbl_status.setText(self.parent_window.texts["ready"])

    def shutdown(self):
        self._shutdown_thread(self.worker)

    def _on_progress(self, percent, text):
        self.parent_window.link_page.progress_bar.setValue(int(percent))
        self.parent_window.link_page.lbl_status.setText(str(text))

    def _display_results(self, payload):
        results = payload.get("results") or []
        source_link = payload.get("source_link") or ""
        if not results:
            self.parent_window.link_page.lbl_status.setText(self.parent_window.texts["no_results"])
            self.parent_window.link_page.result_table.setRowCount(0)
            return

        populate_link_result_table(
            self.parent_window.link_page.result_table,
            results,
            source_link,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.texts,
        )
        elapsed = time.time() - self.start_time
        self.parent_window.link_page.lbl_status.setText(
            self.parent_window.texts["link_search_done"].format(
                duration=elapsed,
                count=len(results),
            )
        )

    def _handle_error(self, error_text):
        self.parent_window.link_page.lbl_status.setText(self.parent_window.texts["search_failed"])
        self.parent_window.show_error_dialog(self.parent_window.texts["link_search_failed"], error_text)

    def _finish_search(self):
        self.parent_window.link_page.btn_run.setEnabled(True)

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
