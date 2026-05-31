import time

from PySide6.QtCore import QObject

from src.core.clip_embedding import get_engine_runtime_status, get_engine_runtime_warning
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
        self._scope_library_paths = []
        self._gpu_warning_shown = False
        self._warmup_started = False
        self._is_shutdown = False

    def _result_view(self):
        return self.parent_window.search_page.result_view

    def start_search(
        self,
        query,
        is_text,
        scope_library_paths=None,
        scope_video_paths=None,
        query_vector=None,
        search_mode=None,
        top_k=None,
        min_score=None,
        search_precision_mode=None,
        pixel_query_data=None,
        preview_anchor_sec=None,
    ):
        self.stop_thumbnail_loading()
        self.start_time = time.time()
        self._scope_library_paths = list(scope_library_paths or [])

        self.parent_window.search_page.btn_search.setEnabled(False)
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["searching"])

        self.worker = SearchWorker(
            query=query,
            is_text=is_text,
            scope_library_paths=self._scope_library_paths,
            scope_video_paths=scope_video_paths,
            query_vector=query_vector,
            search_mode=search_mode,
            top_k=top_k,
            min_score=min_score,
            search_precision_mode=search_precision_mode,
            pixel_query_data=pixel_query_data,
            preview_anchor_sec=preview_anchor_sec,
        )
        self.worker.result_ready.connect(self._display_results)
        self.worker.error_signal.connect(self._handle_search_error)
        self.worker.finished.connect(self._finish_search)
        self.worker.start()

    def start_preset_search(self, preset_id):
        from src.services.search_request_service import resolve_search_query_inputs
        from src.services.search_scope import resolve_active_search_mode, resolve_effective_search_scope

        query_part = resolve_search_query_inputs(preset_id=preset_id)
        preset = query_part["preset"]
        scope_video_paths, scope_library_paths = resolve_effective_search_scope(
            None,
            preset_scope_video_paths=query_part.get("preset_scope_video_paths"),
        )
        is_text = bool(query_part["is_text"])
        has_image = bool(query_part["has_image"])
        search_precision_mode = self.parent_window._resolve_search_precision_mode(
            is_text=is_text,
            has_image=has_image,
        )
        if hasattr(self.parent_window, "apply_search_preset_to_ui"):
            self.parent_window.apply_search_preset_to_ui(preset)
        self.start_search(
            query=query_part.get("query_data"),
            is_text=is_text,
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            query_vector=query_part.get("query_vector"),
            search_mode=resolve_active_search_mode(),
            top_k=query_part.get("default_top_k"),
            min_score=query_part.get("default_min_score"),
            search_precision_mode=search_precision_mode,
            pixel_query_data=query_part.get("pixel_query_data"),
        )

    def clear_results(self):
        self.stop_thumbnail_loading()
        self._result_view().clear()

    def shutdown(self):
        self._is_shutdown = True
        self.stop_thumbnail_loading()
        self._disconnect_search_worker(self.worker)
        shutdown_thread(self.worker, allow_terminate=False)
        self.worker = None
        self._disconnect_warmup_worker(self.warmup_worker)
        shutdown_thread(self.warmup_worker, allow_terminate=False)
        self.warmup_worker = None

    def _disconnect_search_worker(self, worker):
        if worker is None:
            return
        for signal, slot in (
            (worker.result_ready, self._display_results),
            (worker.error_signal, self._handle_search_error),
            (worker.finished, self._finish_search),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _disconnect_warmup_worker(self, worker):
        if worker is None:
            return
        try:
            worker.finished.disconnect(self._finish_warmup)
        except (RuntimeError, TypeError):
            pass

    def start_warmup(self):
        if self._warmup_started:
            return
        self._warmup_started = True
        self.warmup_worker = SearchWarmupWorker()
        self.warmup_worker.finished.connect(self._finish_warmup)
        self.warmup_worker.start()

    def stop_thumbnail_loading(self):
        thread = self.thumb_thread
        self.thumb_thread = None
        if thread is None:
            return
        try:
            thread.thumb_ready.disconnect(self._on_thumb_ready)
        except (RuntimeError, TypeError):
            pass
        shutdown_thread(thread, stop_first=True, allow_terminate=False)

    def _on_thumb_ready(self, row, pixmap):
        if self._is_shutdown:
            return
        self._result_view().set_thumbnail(row, pixmap)

    def _display_results(self, results):
        if self._is_shutdown:
            return
        self.parent_window.push_inference_status()
        result_view = self._result_view()
        if not results:
            result_view.clear()
            self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["no_results"])
            return

        result_view.populate_local(
            results,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.handle_export_clip,
            self.parent_window.texts,
            on_deep_locate=getattr(self.parent_window, "start_in_video_deep_search", None),
        )
        duration = time.time() - self.start_time
        status_text = self.parent_window.texts["search_done"].format(duration=duration, count=len(results))
        self.parent_window.search_page.lbl_status.setText(status_text)

        self.thumb_thread = ThumbLoader(results)
        self.thumb_thread.thumb_ready.connect(self._on_thumb_ready)
        self.thumb_thread.start()

    def _finish_search(self):
        if self._is_shutdown:
            return
        self.parent_window.search_page.btn_search.setEnabled(True)

    def _finish_warmup(self):
        if self._is_shutdown:
            return
        self.warmup_worker = None
        self.parent_window.push_inference_status()

    def _handle_search_error(self, error_text):
        if self._is_shutdown:
            return
        self.parent_window.push_inference_status()
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["search_failed"])
        runtime_warning = get_engine_runtime_warning()
        if runtime_warning:
            if not self._gpu_warning_shown:
                self._gpu_warning_shown = True
                runtime_status = get_engine_runtime_status()
                runtime_detail = self.parent_window._build_runtime_diagnostics_detail(runtime_status)
                if runtime_detail:
                    runtime_warning = f"{runtime_warning}\n\n{runtime_detail}"
                self.parent_window.show_info_dialog(
                    self.parent_window.texts["warning_title"],
                    self.parent_window.texts["gpu_runtime_unavailable"].format(detail=runtime_warning),
                    kind="warning",
                )
            return
        self.parent_window.show_error_dialog(self.parent_window.texts["search_failed"], error_text)
