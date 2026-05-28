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
        )
        self.worker.result_ready.connect(self._display_results)
        self.worker.error_signal.connect(self._handle_search_error)
        self.worker.finished.connect(self._finish_search)
        self.worker.start()

    def start_preset_search(self, preset_id):
        from src.services.search_preset_service import build_preset_search_plan
        from src.services.search_scope import resolve_active_search_library_scope, resolve_active_search_mode

        plan = build_preset_search_plan(preset_id)
        preset = plan["preset"]
        scope_library_paths = resolve_active_search_library_scope()
        if hasattr(self.parent_window, "apply_search_preset_to_ui"):
            self.parent_window.apply_search_preset_to_ui(preset)
        self.start_search(
            query=plan.get("query_data"),
            is_text=bool(plan.get("is_text")),
            scope_library_paths=scope_library_paths,
            scope_video_paths=None,
            query_vector=plan.get("query_vector"),
            search_mode=resolve_active_search_mode(),
            top_k=plan.get("top_k"),
            min_score=plan.get("min_score"),
        )

    def clear_results(self):
        self.stop_thumbnail_loading()
        self._result_view().clear()

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
        )
        duration = time.time() - self.start_time
        status_text = self.parent_window.texts["search_done"].format(duration=duration, count=len(results))
        self.parent_window.search_page.lbl_status.setText(status_text)

        self.thumb_thread = ThumbLoader(results)
        self.thumb_thread.thumb_ready.connect(result_view.set_thumbnail)
        self.thumb_thread.start()

    def _finish_search(self):
        self.parent_window.search_page.btn_search.setEnabled(True)

    def _finish_warmup(self):
        self.warmup_worker = None
        self.parent_window.push_inference_status()

    def _handle_search_error(self, error_text):
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
