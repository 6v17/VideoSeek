import time

from PySide6.QtCore import QObject

from src.app.logging_utils import get_logger
from src.core.clip_embedding import get_engine_runtime_status, get_engine_runtime_warning
from ui.threading_utils import shutdown_thread
from ui.views.table_visibility import visible_table_row_range
from ui.workers import SearchConfig, SearchWarmupWorker, SearchWorker, ThumbLoader

logger = get_logger("search_controller")


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
        self._last_coarse_results = []

    def _result_view(self):
        return self.parent_window.search_page.result_view

    def _visible_result_rows(self, table):
        return set(visible_table_row_range(table))

    def is_search_running(self) -> bool:
        worker = self.worker
        return worker is not None and worker.isRunning()

    def _stop_active_search_worker(self):
        worker = self.worker
        if worker is None:
            return
        self._disconnect_search_worker(worker)
        shutdown_thread(worker, allow_terminate=False)
        if worker is self.worker:
            self.worker = None

    def _is_current_worker(self, worker=None):
        target = worker if worker is not None else self.sender()
        return target is self.worker

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
        locate_anchor_score=None,
        locate_score_margin=None,
        video_discovery_enabled=None,
    ):
        self._stop_active_search_worker()
        self.stop_thumbnail_loading()
        self.start_time = time.time()
        self._scope_library_paths = list(scope_library_paths or [])

        self.parent_window.search_page.btn_search.setEnabled(False)
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["searching"])

        self.worker = SearchWorker(
            SearchConfig(
                query=query,
                is_text=is_text,
                scope_library_paths=self._scope_library_paths,
                scope_video_paths=list(scope_video_paths or []),
                query_vector=query_vector,
                search_mode=search_mode,
                top_k=top_k,
                min_score=min_score,
                search_precision_mode=search_precision_mode,
                pixel_query_data=pixel_query_data,
                preview_anchor_sec=preview_anchor_sec,
                locate_anchor_score=locate_anchor_score,
                locate_score_margin=locate_score_margin,
                video_discovery_enabled=video_discovery_enabled,
            )
        )
        self.worker.result_ready.connect(self._display_results)
        self.worker.error_signal.connect(self._handle_search_error)
        self.worker.progress_signal.connect(self._on_search_progress)
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
            video_discovery_enabled=self.parent_window._resolve_video_discovery_enabled(
                is_text=is_text,
                has_image=has_image,
            ),
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
            (worker.progress_signal, self._on_search_progress),
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

    def _on_search_progress(self, progress_key: str):
        if self._is_shutdown or not self._is_current_worker():
            return
        key = str(progress_key or "").strip()
        if not key:
            return
        texts = self.parent_window.texts
        label = texts.get(key, key)
        self.parent_window.search_page.lbl_status.setText(label)

    def _display_results(self, results):
        if self._is_shutdown or not self._is_current_worker():
            return
        is_locate_run = bool(getattr(self.worker, "preview_anchor_sec", None) is not None)
        if not is_locate_run:
            self._last_coarse_results = list(results or [])
        self.parent_window.push_inference_status()
        result_view = self._result_view()
        if not results:
            result_view.clear()
            self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["no_results"])
            return

        texts = self.parent_window.texts
        clip_score_mode = False
        low_confidence_threshold = None
        image_path = str(getattr(self.parent_window, "current_img_path", "") or "").strip()
        if image_path:
            try:
                from src.services.image_search_rerank import is_likely_cropped_query_image
                from src.services.search_service import _LOCATE_CROP_MIN_CLIP_SCORE

                if is_likely_cropped_query_image(image_path):
                    clip_score_mode = True
                    low_confidence_threshold = _LOCATE_CROP_MIN_CLIP_SCORE
            except Exception as exc:
                logger.debug("Crop query clip-score UI hint skipped: %s", exc)

        result_view.populate_local(
            results,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.handle_export_clip,
            texts,
            on_deep_locate=getattr(self.parent_window, "start_in_video_deep_search", None),
            on_add_to_shot_list=getattr(self.parent_window, "add_hit_to_shot_list", None),
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_threshold,
        )
        duration = time.time() - self.start_time
        status_text = texts["search_done"].format(duration=duration, count=len(results))
        if clip_score_mode:
            try:
                from src.domain.search_hit import coerce_search_hit
                from src.services.search_service import (
                    format_clip_score_percent,
                    resolve_clip_confidence_label,
                    resolve_clip_confidence_tier_key,
                )
                from src.services.search_telemetry import record_crop_confidence

                precise_mode = str(getattr(self.worker, "search_precision_mode", "") or "").strip().lower() == "precise"
                if precise_mode:
                    hint = texts.get("search_crop_clip_only_hint", "")
                    if hint:
                        status_text = f"{status_text} · {hint}"
                top_score = float(coerce_search_hit(results[0]).score)
                top_label = format_clip_score_percent(top_score)
                tier_label = resolve_clip_confidence_label(top_score, texts)
                tier_key = resolve_clip_confidence_tier_key(top_score)
                is_locate = getattr(self.worker, "preview_anchor_sec", None) is not None
                record_crop_confidence(
                    score=top_score,
                    tier_key=tier_key,
                    source="crop_locate" if is_locate else "crop_search",
                )
                status_text = (
                    f"{status_text} · "
                    f"{texts.get('search_top_clip_score', 'Top1 CLIP {score}').format(score=top_label)}"
                )
                if tier_label:
                    status_text = (
                        f"{status_text} · "
                        f"{texts.get('search_clip_confidence_level', '置信度 {level}').format(level=tier_label)}"
                    )
            except Exception as exc:
                logger.debug("Crop confidence status formatting skipped: %s", exc)
        warning_key = getattr(self.worker, "locate_warning_key", None)
        if warning_key:
            warn_template = texts.get(warning_key, "")
            if warn_template:
                if warning_key == "locate_crop_low_confidence" and results:
                    from src.domain.search_hit import coerce_search_hit
                    from src.services.search_service import format_clip_score_percent

                    top_score = float(coerce_search_hit(results[0]).score)
                    warn = warn_template.format(score=format_clip_score_percent(top_score))
                else:
                    warn = warn_template
                status_text = f"{status_text} · {warn}"
        self.parent_window.search_page.lbl_status.setText(status_text)

        self.thumb_thread = ThumbLoader(results, priority_rows=self._visible_result_rows(result_view.table))
        self.thumb_thread.thumb_ready.connect(self._on_thumb_ready)
        self.thumb_thread.start()

    def _finish_search(self):
        if self._is_shutdown or not self._is_current_worker():
            return
        self.parent_window.search_page.btn_search.setEnabled(True)

    def _finish_warmup(self):
        if self._is_shutdown:
            return
        self.warmup_worker = None
        self.parent_window.push_inference_status()

    def _handle_search_error(self, error_text):
        if self._is_shutdown or not self._is_current_worker():
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
