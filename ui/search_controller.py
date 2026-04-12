import time

from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QLabel

from src.core.clip_embedding import get_engine_runtime_warning
from ui.table_views import populate_result_table
from ui.threading_utils import shutdown_thread
from ui.workers import SearchWarmupWorker, SearchWorker, ThumbLoader


class SearchController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.worker = None
        self.warmup_worker = None
        self.thumb_thread = None
        self.start_time = 0.0
        self._gpu_warning_shown = False
        self._warmup_started = False

    def start_search(self, query, is_text):
        self.stop_thumbnail_loading()
        self.start_time = time.time()

        self.parent_window.search_page.btn_search.setEnabled(False)
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["searching"])

        self.worker = SearchWorker(query, is_text)
        self.worker.result_ready.connect(self._display_results)
        self.worker.error_signal.connect(self._handle_search_error)
        self.worker.finished.connect(self._finish_search)
        self.worker.start()

    def clear_results(self):
        self.stop_thumbnail_loading()
        self.parent_window.result_table.setRowCount(0)

    def shutdown(self):
        self.stop_thumbnail_loading()
        shutdown_thread(self.worker)
        shutdown_thread(self.warmup_worker)

    def start_warmup(self):
        if self._warmup_started:
            return
        self._warmup_started = True
        self.warmup_worker = SearchWarmupWorker()
        self.warmup_worker.finished.connect(self._finish_warmup)
        self.warmup_worker.start()

    def stop_thumbnail_loading(self):
        shutdown_thread(self.thumb_thread, stop_first=True)

    def _display_results(self, results):
        self.parent_window._update_inference_backend_hint()
        if not results:
            self.parent_window.result_table.setRowCount(0)
            self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["no_results"])
            return

        populate_result_table(
            self.parent_window.result_table,
            results,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.handle_export_clip,
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

    def _finish_warmup(self):
        self.warmup_worker = None

    def _handle_search_error(self, error_text):
        self.parent_window._update_inference_backend_hint()
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["search_failed"])
        runtime_warning = get_engine_runtime_warning()
        if runtime_warning:
            if not self._gpu_warning_shown:
                self._gpu_warning_shown = True
                self.parent_window.show_info_dialog(
                    self.parent_window.texts["warning_title"],
                    self.parent_window.texts["gpu_runtime_unavailable"].format(detail=runtime_warning),
                    kind="warning",
                )
            return
        self.parent_window.show_error_dialog(self.parent_window.texts["search_failed"], error_text)
