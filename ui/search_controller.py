import time

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QLabel

from ui.table_views import populate_result_table
from ui.workers import SearchWorker, ThumbLoader


class SearchController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.thumb_thread = None
        self.start_time = 0.0

    def start_search(self, query, is_text):
        self.stop_thumbnail_loading()
        self.start_time = time.time()

        self.parent_window.search_page.btn_search.setEnabled(False)
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["searching"])

        self.worker = SearchWorker(query, is_text)
        self.worker.result_ready.connect(self._display_results)
        self.worker.finished.connect(self._finish_search)
        self.worker.start()

    def clear_results(self):
        self.stop_thumbnail_loading()
        self.parent_window.result_table.setRowCount(0)

    def shutdown(self):
        self.stop_thumbnail_loading()
        self._shutdown_thread(self.worker)

    def stop_thumbnail_loading(self):
        self._shutdown_thread(self.thumb_thread, stop_first=True)

    def _display_results(self, results):
        if not results:
            self.parent_window.result_table.setRowCount(0)
            self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["no_results"])
            return

        populate_result_table(
            self.parent_window.result_table,
            results,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.texts,
        )
        duration = time.time() - self.start_time
        self.parent_window.search_page.lbl_status.setText(
            self.parent_window.texts["search_done"].format(duration=duration, count=len(results))
        )

        self.thumb_thread = ThumbLoader(results)
        self.thumb_thread.thumb_ready.connect(self._update_row_thumb)
        self.thumb_thread.start()

    def _update_row_thumb(self, row, pixmap):
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap)
        self.parent_window.result_table.setCellWidget(row, 1, label)

    def _finish_search(self):
        self.parent_window.search_page.btn_search.setEnabled(True)

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
