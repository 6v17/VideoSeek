import time
from dataclasses import replace

from PySide6.QtCore import QObject

from src.app.logging_utils import get_logger
from src.app.search_results_paging import slice_search_results_page, visible_end_index
from src.domain.search_hit import coerce_search_hit
from src.storage.config_store import (
    SEARCH_CANDIDATE_LIMIT,
    next_result_window,
)
from ui.threading_utils import shutdown_thread
from ui.workers import SearchConfig, SearchWarmupWorker, SearchWorker, ThumbLoader

logger = get_logger("search_controller")


def _hit_key(row) -> tuple:
    hit = coerce_search_hit(row)
    return (
        str(hit.video_path or ""),
        round(float(hit.start_sec), 3),
        round(float(hit.end_sec), 3),
        str(hit.match_kind or ""),
    )


def _unseen_hits(existing, incoming):
    seen = {_hit_key(row) for row in existing or []}
    extra = []
    for row in incoming or []:
        key = _hit_key(row)
        if key in seen:
            continue
        seen.add(key)
        extra.append(row)
    return extra


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
        self._all_results = []
        self._source_hits = []
        self._source_vectors = None
        self._result_groups = []
        self._visual_results_flat = False
        self._expanded_group_ids = set()
        self._grid_group_focus = None
        self._group_return = None
        self._group_hooks = False
        self._current_page = 0
        self._last_search_duration = 0.0
        self._result_display_context = {}
        self._more_worker = None
        self._search_config = None
        self._window_limit = 0
        self._window_exhausted = True
        self._window_epoch = 0
        self._prefetch_hold = False
        self._scroll_hooked = False
        self._suppress_window_growth = False
        self._resetting_scroll = False
        self._pin_top_guard = False
        self._pin_top_on_resume = False
        self._thumb_loading_indices: set[int] = set()
        self._thumb_scroll_timer = None

    def _result_view(self):
        return self.parent_window.search_page.result_view

    def is_search_running(self) -> bool:
        worker = self.worker
        return worker is not None and worker.isRunning()

    def _stop_active_search_worker(self):
        worker = self.worker
        if worker is None:
            return
        self._disconnect_search_worker(worker)
        # Never terminate(): encode holds _INFERENCE_LOCK; hard-kill can deadlock the app.
        shutdown_thread(worker, stop_first=True, allow_terminate=False, wait_ms=1500)
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
        search_kind=None,
        top_k=None,
        min_score=None,
        search_precision_mode=None,
        pixel_query_data=None,
        preview_anchor_sec=None,
        locate_anchor_score=None,
        locate_score_margin=None,
        video_discovery_enabled=None,
        compose_text=None,
        compose_image_paths=None,
        compose_fusion=None,
        required_tags=None,
    ):
        self._stop_active_search_worker()
        self._stop_more_worker()
        self._window_epoch += 1
        self._window_limit = 0
        self._window_exhausted = True
        self._prefetch_hold = False
        self._search_config = None
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
                search_kind=search_kind,
                top_k=top_k,
                min_score=min_score,
                search_precision_mode=search_precision_mode,
                pixel_query_data=pixel_query_data,
                preview_anchor_sec=preview_anchor_sec,
                locate_anchor_score=locate_anchor_score,
                locate_score_margin=locate_score_margin,
                video_discovery_enabled=video_discovery_enabled,
                compose_text=compose_text,
                compose_image_paths=list(compose_image_paths or []) if compose_image_paths is not None else None,
                compose_fusion=compose_fusion,
                required_tags=list(required_tags or []) if required_tags is not None else None,
            )
        )
        self.worker.result_ready.connect(self._display_results)
        self.worker.error_signal.connect(self._handle_search_error)
        self.worker.progress_signal.connect(self._on_search_progress)
        self.worker.finished.connect(self._finish_search)
        self.worker.start()

    def start_preset_search(self, preset_id):
        """Load preset into Compose and run the same path as clicking Search.

        Older code searched with a cached query_vector and skipped compose/text-enhance,
        so chip results disagreed with a manual Compose search of the same content.
        """
        if self.is_search_running():
            page = getattr(self.parent_window, "search_page", None)
            if page is not None and hasattr(page, "lbl_status"):
                texts = getattr(self.parent_window, "texts", {}) or {}
                page.lbl_status.setText(texts.get("search_busy", texts.get("searching", "Searching...")))
            return
        from src.services.search_preset_model import get_preset

        preset = get_preset(str(preset_id or "").strip())
        if preset is None:
            page = getattr(self.parent_window, "search_page", None)
            if page is not None and hasattr(page, "lbl_status"):
                texts = getattr(self.parent_window, "texts", {}) or {}
                page.lbl_status.setText(texts.get("search_presets_empty", "Preset not found"))
            return
        if hasattr(self.parent_window, "apply_search_preset_to_ui"):
            self.parent_window.apply_search_preset_to_ui(preset)
        if hasattr(self.parent_window, "_start_compose_search"):
            self.parent_window._start_compose_search()
            return
        # Fallback if Compose entry is missing (should not happen in desktop UI).
        from src.services.search_request_service import resolve_search_query_inputs
        from src.services.search_scope import resolve_effective_search_scope

        query_part = resolve_search_query_inputs(preset_id=preset_id)
        scope_video_paths, scope_library_paths = resolve_effective_search_scope(
            None,
            preset_scope_video_paths=query_part.get("preset_scope_video_paths"),
        )
        compose_mode = "frame"
        if hasattr(self.parent_window, "_text_search_mode_from_ui"):
            compose_mode = self.parent_window._text_search_mode_from_ui()
        self.start_search(
            query=query_part.get("query_data"),
            is_text=bool(query_part["is_text"]),
            scope_library_paths=scope_library_paths,
            scope_video_paths=scope_video_paths,
            query_vector=None,
            search_mode=compose_mode,
            search_kind="compose",
            top_k=query_part.get("default_top_k"),
            min_score=query_part.get("default_min_score"),
            search_precision_mode="fast",
            pixel_query_data=query_part.get("pixel_query_data"),
            video_discovery_enabled=False,
            compose_text=str((query_part.get("preset") or {}).get("query") or ""),
            compose_image_paths=list(
                ((query_part.get("preset") or {}).get("source_image_paths") or [])
            ),
            compose_fusion=(query_part.get("preset") or {}).get("fusion"),
        )

    def clear_results(self):
        self._stop_more_worker()
        self._window_epoch += 1
        self._window_exhausted = True
        self._window_limit = 0
        self._search_config = None
        self.stop_thumbnail_loading()
        self._all_results = []
        self._source_hits = []
        self._source_vectors = None
        self._result_groups = []
        self._visual_results_flat = False
        self._expanded_group_ids = set()
        self._grid_group_focus = None
        self._group_return = None
        self._current_page = 0
        self._result_display_context = {}
        self._result_view().clear()
        self._set_group_return(None)
        self._pin_top_guard = True
        self._reset_result_scroll()
        self._pin_top_guard = False
        self._sync_results_pager()

    def _results_page_size(self) -> int:
        """Mount the whole hit list. The result view scrolls; a short fixed page looks empty on a large screen."""
        return max(1, len(self._all_results))

    def go_to_results_page(self, page_index: int) -> None:
        if not self._all_results:
            return
        page_size = self._results_page_size()
        pages = max(1, (len(self._all_results) + page_size - 1) // page_size)
        self._current_page = max(0, min(int(page_index), pages - 1))
        self._render_current_page()
        result_view = self._result_view()
        if result_view.view_mode == "grid":
            if result_view.grid.count() > 0:
                result_view.grid.verticalScrollBar().setValue(0)
        else:
            table = result_view.table
            if table.rowCount() > 0:
                table.scrollToTop()

    def _sync_results_pager(self) -> None:
        pager = getattr(self.parent_window.search_page, "results_pager", None)
        if pager is None:
            return
        pager.configure(
            total_count=len(self._all_results),
            current_page=self._current_page,
            page_size=self._results_page_size(),
        )

    def shutdown(self):
        self._is_shutdown = True
        self.stop_thumbnail_loading()
        self._stop_more_worker()
        self._disconnect_search_worker(self.worker)
        shutdown_thread(self.worker, stop_first=True, allow_terminate=False, wait_ms=2000)
        self.worker = None
        self._disconnect_warmup_worker(self.warmup_worker)
        shutdown_thread(self.warmup_worker, allow_terminate=True, wait_ms=2000)
        self.warmup_worker = None

    def _stop_more_worker(self):
        worker = self._more_worker
        if worker is None:
            return
        self._disconnect_more_worker(worker)
        shutdown_thread(worker, stop_first=True, allow_terminate=False, wait_ms=1500)
        if worker is self._more_worker:
            self._more_worker = None

    def _disconnect_more_worker(self, worker):
        if worker is None:
            return
        for signal, slot in (
            (worker.result_ready, self._on_window_ready),
            (worker.error_signal, self._on_window_error),
            (worker.finished, self._on_window_finished),
        ):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    def _ensure_result_scroll_hooks(self) -> None:
        if self._scroll_hooked:
            return
        view = self._result_view()
        view.grid.verticalScrollBar().valueChanged.connect(self._on_results_scrolled)
        view.table.verticalScrollBar().valueChanged.connect(self._on_results_scrolled)
        self._scroll_hooked = True

    def _reset_result_scroll(self) -> None:
        """New searches start at the first row. A leftover scrollbar looks like the user already scrolled."""
        view = self._result_view()
        self._resetting_scroll = True
        try:
            view.grid.verticalScrollBar().setValue(0)
            view.table.scrollToTop()
            view.table.verticalScrollBar().setValue(0)
        finally:
            self._resetting_scroll = False

    def _on_results_scrolled(self, _value: int = 0) -> None:
        if self._resetting_scroll:
            return
        if self._pin_top_guard:
            if int(_value) > 0:
                self._reset_result_scroll()
            return
        furthest = self._furthest_visible_index()
        if self._prefetch_hold and furthest > int(getattr(self, "_prefetch_hold_index", -1)):
            self._prefetch_hold = False
        self._maybe_grow_window()
        self._schedule_visible_thumbnails()

    def _furthest_visible_index(self) -> int:
        """Last row that has entered the viewport. -1 when the list is empty."""
        view = self._result_view()
        if view.view_mode == "grid":
            grid = view.grid
            count = int(grid.count())
            cards = list(getattr(grid, "_cards", None) or [])
            card_h = int(cards[0].sizeHint().height()) + 12 if cards else 192
            cols = max(1, int(getattr(grid, "_cols", 1) or 1))
            bar = grid.verticalScrollBar()
            return visible_end_index(
                count,
                int(bar.value()),
                int(bar.maximum()),
                int(grid.viewport().height()),
                card_h,
                cols,
            )
        table = view.table
        header = table.verticalHeader()
        row_h = max(1, int(header.defaultSectionSize() or 88))
        bar = table.verticalScrollBar()
        if int(bar.value()) > 0:
            idx = table.rowAt(max(0, int(table.viewport().height()) - 1))
            if idx >= 0:
                return min(int(table.rowCount()) - 1, int(idx)) if table.rowCount() else -1
        return visible_end_index(
            int(table.rowCount()),
            int(bar.value()),
            int(bar.maximum()),
            int(table.viewport().height()),
            row_h,
            1,
        )

    def _arm_result_window(self) -> None:
        """Desktop searches start at 300 and grow. An explicit top_k stays fixed."""
        config = self._search_config
        if config is None or config.top_k is not None:
            self._window_limit = int(getattr(config, "top_k", 0) or 0)
            self._window_exhausted = True
            return
        self._window_limit = int(SEARCH_CANDIDATE_LIMIT)
        # A short first page (chunk collapse, nearby-frame dedupe) is not the end.
        # Growth stops only when a larger fetch adds no new hits.
        self._window_exhausted = len(self._source_hits) == 0
        self._prefetch_hold = False

    def _maybe_grow_window(self, *, ignore_worker=None) -> None:
        if self._suppress_window_growth or self._is_shutdown or self._window_exhausted or self._prefetch_hold:
            return
        if self._search_config is None or self._search_config.top_k is not None:
            return
        active = self._more_worker
        if active is not None and active is not ignore_worker and active.isRunning():
            return
        nxt = next_result_window(
            self._window_limit,
            self._furthest_visible_index(),
            exhausted=self._window_exhausted,
            loaded_count=len(self._source_hits),
        )
        if nxt is None:
            return
        self._start_window_prefetch(int(nxt), retiring=ignore_worker)

    def _start_window_prefetch(self, limit: int, *, retiring=None) -> None:
        config = self._search_config
        if config is None:
            return
        current = self._more_worker
        if current is not None and current is retiring:
            self._disconnect_more_worker(current)
            self._more_worker = None
        else:
            self._stop_more_worker()
        worker = SearchWorker(replace(config, top_k=int(limit)))
        worker.window_limit = int(limit)
        worker.window_epoch = int(self._window_epoch)
        worker.result_ready.connect(self._on_window_ready)
        worker.error_signal.connect(self._on_window_error)
        worker.finished.connect(self._on_window_finished)
        self._more_worker = worker
        worker.start()

    def _on_window_ready(self, rows) -> None:
        worker = self.sender()
        if self._is_shutdown or worker is not self._more_worker:
            return
        if int(getattr(worker, "window_epoch", -1)) != int(self._window_epoch):
            return
        requested = int(getattr(worker, "window_limit", 0) or 0)
        incoming = list(rows or [])
        extra = _unseen_hits(self._source_hits, incoming)
        if not extra:
            self._window_exhausted = True
        else:
            self._source_hits = incoming
            vectors = getattr(worker, "hit_vectors", None)
            self._source_vectors = list(vectors) if isinstance(vectors, list) else None
            self.rebuild_grouped_results(pin_top=False)
        if requested > 0:
            self._window_limit = requested
        self._maybe_grow_window(ignore_worker=worker)

    def _on_window_error(self, _error_text) -> None:
        worker = self.sender()
        if worker is not self._more_worker:
            return
        logger.warning("Search window prefetch failed")
        self._prefetch_hold = True
        self._prefetch_hold_index = self._furthest_visible_index()

    def _on_window_finished(self) -> None:
        worker = self.sender()
        if worker is None or worker is not self._more_worker:
            return
        if not worker.isRunning():
            self._more_worker = None

    def _append_rendered(self, extra) -> None:
        if not extra:
            return
        texts = self.parent_window.texts
        context = dict(self._result_display_context or {})
        rank_offset = len(self._all_results) - len(extra)
        self._result_view().append_local(
            extra,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.handle_export_clip,
            texts,
            on_deep_locate=getattr(self.parent_window, "start_in_video_deep_search", None),
            on_add_to_shot_list=getattr(self.parent_window, "add_hit_to_shot_list", None),
            clip_score_mode=bool(context.get("clip_score_mode")),
            low_confidence_score=context.get("low_confidence_score"),
            rank_offset=rank_offset,
            highlight_query=str(context.get("highlight_query") or ""),
            dialogue_match_mode=str(context.get("dialogue_match_mode") or ""),
        )
        self._sync_results_pager()

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
        if self.is_warmup_running():
            return
        if self._warmup_started:
            return
        self._warmup_started = True
        self.warmup_worker = SearchWarmupWorker()
        self.warmup_worker.finished.connect(self._finish_warmup)
        self.warmup_worker.start()

    def is_warmup_running(self) -> bool:
        worker = self.warmup_worker
        return worker is not None and worker.isRunning()

    def stop_thumbnail_loading(self):
        timer = self._thumb_scroll_timer
        if timer is not None:
            timer.stop()
        self._thumb_loading_indices = set()
        thread = self.thumb_thread
        self.thumb_thread = None
        if thread is None:
            return
        try:
            thread.thumb_ready.disconnect(self._on_thumb_ready)
        except (RuntimeError, TypeError):
            pass
        shutdown_thread(thread, stop_first=True, allow_terminate=False, wait_ms=1500)

    def _on_thumb_ready(self, row, image):
        if self._is_shutdown:
            return
        try:
            self._thumb_loading_indices.discard(int(row))
        except (TypeError, ValueError):
            pass
        from PySide6.QtGui import QImage, QPixmap

        pixmap = None
        if isinstance(image, QImage) and not image.isNull():
            pixmap = QPixmap.fromImage(image)
        elif image is not None and not isinstance(image, QImage):
            # Legacy cache / mistaken emit of QPixmap — accept but do not create off-thread.
            pixmap = image
        self._result_view().set_thumbnail(row, pixmap)
        updater = getattr(self.parent_window, "_update_search_preview_strip_thumb", None)
        if updater is not None and pixmap is not None:
            updater(row, pixmap)

    def _on_search_progress(self, progress_key: str):
        if self._is_shutdown or not self._is_current_worker():
            return
        key = str(progress_key or "").strip()
        if not key:
            return
        texts = self.parent_window.texts
        label = texts.get(key, key)
        self.parent_window.search_page.lbl_status.setText(label)

    def _resolve_empty_search_status(self) -> str:
        """Human empty-state copy: index readiness, dialogue/tags, then mode tips."""
        texts = self.parent_window.texts
        status = str(texts.get("no_results", "") or "").strip()
        worker_config = getattr(self.worker, "config", None)
        search_kind = ""
        if worker_config is not None:
            search_kind = str(getattr(worker_config, "search_kind", "") or "").strip().lower()

        if search_kind == "dialogue":
            dialogue_message = str(getattr(self.worker, "dialogue_status_message", "") or "").strip()
            dialogue_keys = {
                "no dialogue index for active profile (build dialogue index first)": "search_dialogue_no_index",
                "no dialogue matches": "search_dialogue_no_matches",
                "empty query": "search_empty_dialogue",
            }
            if dialogue_message:
                key = dialogue_keys.get(dialogue_message)
                return str(texts.get(key, dialogue_message) if key else dialogue_message)
            return str(texts.get("search_dialogue_no_matches", status) or status)

        if search_kind == "tags":
            tags_message = str(getattr(self.worker, "dialogue_status_message", "") or "").strip()
            tags_keys = {
                "no tag index (generate VLM tags on Understanding page first)": "search_tags_no_index",
                "no tag matches": "search_tags_no_matches",
                "empty query": "search_empty_tags",
            }
            if tags_message:
                key = tags_keys.get(tags_message)
                return str(texts.get(key, tags_message) if key else tags_message)
            return str(texts.get("search_tags_no_matches", status) or status)

        try:
            from src.storage.config_store import get_local_model_asset_dirs
            from src.storage.lance_search_index import lance_search_is_ready
            from src.storage.video_id_migration import legacy_npy_vectors_present

            base_dir = get_local_model_asset_dirs()["base_dir"]
            if not lance_search_is_ready(base_dir):
                if legacy_npy_vectors_present():
                    return str(texts.get("search_index_not_ready_legacy_npy", status) or status)
                return str(texts.get("search_index_not_ready", status) or status)
        except Exception as exc:
            logger.debug("Empty-search readiness hint skipped: %s", exc)

        is_text = True
        precision = "fast"
        if worker_config is not None:
            is_text = bool(getattr(worker_config, "is_text", True))
            precision = str(getattr(worker_config, "search_precision_mode", "") or "fast").strip().lower()
            if bool(getattr(worker_config, "video_discovery_enabled", False)):
                precision = "video_discovery"

        tip = ""
        if is_text and search_kind not in {"dialogue", "tags"}:
            enhance_on = False
            try:
                from src.storage.config_store import get_text_search_enhance_enabled

                enhance_on = bool(get_text_search_enhance_enabled())
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/controllers/search_controller.py:346")
                enhance_on = False
            if not enhance_on:
                tip = str(texts.get("search_empty_try_text_enhance", "") or "").strip()
        elif not is_text:
            if precision == "precise":
                tip = str(texts.get("search_empty_try_clearer_image", "") or "").strip()
            else:
                tip = str(texts.get("search_empty_try_image_mode", "") or "").strip()

        if tip:
            return f"{status} · {tip}" if status else tip
        return status

    def _display_results(self, results):
        if self._is_shutdown or not self._is_current_worker():
            return
        leave_preview = getattr(self.parent_window, "_leave_search_preview_layer", None)
        if leave_preview is not None and getattr(self.parent_window, "_search_preview_embedded", False):
            leave_preview()
        is_locate_run = bool(getattr(self.worker, "preview_anchor_sec", None) is not None)
        if not is_locate_run:
            self._last_coarse_results = list(results or [])
        self.parent_window.push_inference_status()
        self._source_hits = list(results or [])
        vectors = getattr(self.worker, "hit_vectors", None)
        self._source_vectors = list(vectors) if isinstance(vectors, list) else None
        self._expanded_group_ids = set()
        self._grid_group_focus = None
        self._group_return = None
        self._all_results = list(self._source_hits)
        self._current_page = 0
        self._last_search_duration = max(0.0, time.time() - self.start_time)
        self._search_config = getattr(self.worker, "config", None)
        self._arm_result_window()

        result_view = self._result_view()
        if not self._all_results:
            self._visual_results_flat = False
            self._result_display_context = {}
            result_view.clear()
            self._set_group_return(None)
            self._sync_results_pager()
            status = self._resolve_empty_search_status()
            self.parent_window.search_page.lbl_status.setText(status)
            empty_message = status
            try:
                result_view.set_empty_message(empty_message)
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/controllers/search_controller.py:384")
                pass
            return

        worker_config = getattr(self.worker, "config", None)
        search_kind = str(getattr(worker_config, "search_kind", "") or "").strip().lower()
        clip_score_mode = False
        low_confidence_threshold = None
        # CLIP confidence is only meaningful for visual/image searches, never subtitle/tag search.
        if search_kind not in {"dialogue", "tags"}:
            image_path = str(getattr(self.parent_window, "current_img_path", "") or "").strip()
            if image_path:
                try:
                    from src.services.image_search_rerank import is_likely_cropped_query_image
                    from src.services.search_service import LOCATE_CROP_MIN_CLIP_SCORE

                    if is_likely_cropped_query_image(image_path):
                        clip_score_mode = True
                        low_confidence_threshold = LOCATE_CROP_MIN_CLIP_SCORE
                except Exception as exc:
                    logger.debug("Crop query clip-score UI hint skipped: %s", exc)

        highlight_query = ""
        dialogue_match_mode = ""
        if search_kind in {"dialogue", "tags"} and worker_config is not None:
            highlight_query = str(getattr(worker_config, "query", "") or "").strip()
            dialogue_match_mode = str(getattr(worker_config, "search_mode", "") or "").strip()
        self._result_display_context = {
            "search_kind": search_kind,
            "clip_score_mode": clip_score_mode,
            "low_confidence_score": low_confidence_threshold,
            "highlight_query": highlight_query,
            "dialogue_match_mode": dialogue_match_mode,
        }
        self._ensure_result_scroll_hooks()
        self._ensure_group_hooks()
        self.rebuild_grouped_results(pin_top=True)

    def rebuild_grouped_results(self, *, pin_top: bool = False) -> None:
        """Collapse the current hit list. Safe to call again when the grouping control changes."""
        from src.app.config import load_config
        from src.services.search_result_groups import (
            flatten_result_groups,
            focus_group_rows,
            group_search_hits,
        )

        self._ensure_group_hooks()
        hits = list(self._source_hits or [])
        kind = str((self._result_display_context or {}).get("search_kind") or "").strip().lower()
        config = load_config()
        enabled = bool(config.get("search_result_grouping_enabled", True)) and kind not in {"dialogue", "tags"}
        sensitivity = str(config.get("search_result_grouping_sensitivity") or "standard")
        vectors = self._source_vectors
        if not isinstance(vectors, list) or len(vectors) != len(hits):
            vectors = None
        groups = group_search_hits(hits, vectors, enabled=enabled, sensitivity=sensitivity)
        self._result_groups = groups
        self._visual_results_flat = False
        if kind not in {"dialogue", "tags"} and groups:
            from src.services.search_query import visual_results_lack_standout

            self._visual_results_flat = visual_results_lack_standout(
                [group.representative for group in groups]
            )
        self._expanded_group_ids = {
            group_id
            for group_id in self._expanded_group_ids
            if 0 <= int(group_id) < len(groups) and len(groups[int(group_id)].members) > 1
        }
        focus = self._grid_group_focus
        if focus is None or not (0 <= int(focus) < len(groups)):
            self._grid_group_focus = None
            self._all_results = flatten_result_groups(groups, expanded=self._expanded_group_ids)
            self._set_group_return(None)
        else:
            group = groups[int(focus)]
            self._all_results = focus_group_rows(group, group_id=int(focus))
            self._set_group_return(group)
        self._render_current_page(pin_top=pin_top)

    def _set_group_return(self, group) -> None:
        """Put group drill-in back on the status row. Never a bar above the list."""
        page = getattr(self.parent_window, "search_page", None)
        setter = getattr(page, "set_group_return", None)
        try:
            self._result_view().set_group_banner("", "")
        except Exception as exc:
            from src.app.logging_utils import note_swallowed

            note_swallowed(exc, "ui/controllers/search_controller.py:clear_group_banner")
        if not callable(setter):
            return
        if group is None:
            setter("")
            return
        texts = getattr(self.parent_window, "texts", {}) or {}
        from ui.widgets.search_result_table_model import group_badge_text, group_subtitle_text

        probe = type(
            "Hit",
            (),
            {
                "group_kind": str(group.kind or ""),
                "member_count": len(group.members),
                "unique_videos": group.unique_videos,
                "lead_name": group.lead_name,
            },
        )()
        badge = group_badge_text(probe, texts)
        subtitle = group_subtitle_text(probe, texts)
        back = str(texts.get("search_group_back") or "返回结果")
        setter(f"{back} · {badge}" if badge else back, subtitle)

    def _ensure_group_hooks(self) -> None:
        if self._group_hooks:
            return
        view = self._result_view()
        view.table.group_toggle_requested.connect(self._open_result_group)
        view.grid.group_open_requested.connect(self._open_result_group)
        view.group_back_clicked.connect(self._close_result_group)
        button = getattr(getattr(self.parent_window, "search_page", None), "btn_group_back", None)
        if button is not None:
            button.clicked.connect(self._close_result_group)
        self._group_hooks = True

    def _open_result_group(self, group_id: int) -> None:
        view = self._result_view()
        if view.view_mode == "grid":
            scroll = int(view.grid.verticalScrollBar().value())
        else:
            scroll = int(view.table.verticalScrollBar().value())
        self._group_return = {
            "scroll": scroll,
            "group_id": int(group_id),
            "mode": view.view_mode,
        }
        self._grid_group_focus = int(group_id)
        self.rebuild_grouped_results(pin_top=True)

    def _close_result_group(self) -> None:
        saved = self._group_return
        self._group_return = None
        self._grid_group_focus = None
        # Drop the "pin to top" follow-up from opening the group, or it lands after the restore.
        self._pin_top_on_resume = False
        self._pin_top_guard = False
        self.rebuild_grouped_results(pin_top=False)
        if not saved:
            return
        view = self._result_view()
        index = self._representative_index(int(saved["group_id"]))
        same_mode = str(saved.get("mode") or "") == view.view_mode
        scroll = int(saved["scroll"]) if same_mode else 0
        # populate() already queued the layout pass. Hand it the place to land.
        if view.view_mode == "grid":
            view.grid._pending_restore = (scroll, index)
        else:
            view.table._pending_restore = (scroll, index)

    def _representative_index(self, group_id: int) -> int | None:
        for index, hit in enumerate(self._all_results or []):
            stored = getattr(hit, "group_id", None)
            if stored is None or int(stored) != int(group_id):
                continue
            if bool(getattr(hit, "is_representative", True)):
                return index
        return None

    def _render_current_page(self, *, pin_top: bool = False) -> None:
        results = self._all_results
        if not results:
            self._result_view().clear()
            self._sync_results_pager()
            return
        self._suppress_window_growth = True
        self._pin_top_on_resume = bool(pin_top)
        if pin_top:
            self._pin_top_guard = True
        try:
            self._paint_current_page(results)
            if pin_top:
                self._reset_result_scroll()
        finally:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._resume_window_growth)

    def _resume_window_growth(self) -> None:
        pin = bool(self._pin_top_on_resume)
        self._pin_top_on_resume = False
        if pin:
            self._reset_result_scroll()
        self._suppress_window_growth = False
        if pin:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._release_pin_guard)

    def _release_pin_guard(self) -> None:
        # Only the group we just opened should stay pinned. Returning restores the old place.
        if self._grid_group_focus is not None:
            self._reset_result_scroll()
        self._pin_top_guard = False
        self._ensure_visible_thumbnails()

    def _paint_current_page(self, results) -> None:
        texts = self.parent_window.texts
        context = dict(self._result_display_context or {})
        page_size = self._results_page_size()
        page_results = slice_search_results_page(
            results,
            self._current_page,
            page_size,
        )
        rank_offset = self._current_page * page_size
        result_view = self._result_view()
        result_view.populate_local(
            page_results,
            self.parent_window.handle_play,
            self.parent_window.open_result_in_explorer,
            self.parent_window.handle_export_clip,
            texts,
            on_deep_locate=getattr(self.parent_window, "start_in_video_deep_search", None),
            on_add_to_shot_list=getattr(self.parent_window, "add_hit_to_shot_list", None),
            clip_score_mode=bool(context.get("clip_score_mode")),
            low_confidence_score=context.get("low_confidence_score"),
            rank_offset=rank_offset,
            highlight_query=str(context.get("highlight_query") or ""),
            dialogue_match_mode=str(context.get("dialogue_match_mode") or ""),
        )
        self._sync_results_pager()
        self._update_results_status_text(results, context)
        self._ensure_visible_thumbnails()
        self._sync_embedded_preview_strip()

    def _sync_embedded_preview_strip(self) -> None:
        window = self.parent_window
        if not getattr(window, "_search_preview_embedded", False):
            return
        filler = getattr(window, "_fill_search_preview_strip", None)
        dialog = getattr(window, "_preview_dialog", None)
        if filler is None or dialog is None:
            return
        filler(getattr(dialog, "video_path", ""), getattr(dialog, "start_sec", 0.0))

    def _update_results_status_text(self, results, context: dict) -> None:
        texts = self.parent_window.texts
        duration = float(self._last_search_duration or 0.0)
        total_count = len(results or [])
        search_kind = str(context.get("search_kind") or "").strip().lower()
        if not search_kind:
            worker_config = getattr(self.worker, "config", None)
            search_kind = str(getattr(worker_config, "search_kind", "") or "").strip().lower()

        # Keep the status chip short — one concise line per search type.
        if search_kind == "dialogue":
            dialogue_message = str(getattr(self.worker, "dialogue_status_message", "") or "").strip()
            dialogue_keys = {
                "no dialogue index for active profile (build dialogue index first)": "search_dialogue_no_index",
                "no dialogue matches": "search_dialogue_no_matches",
                "empty query": "search_empty_dialogue",
            }
            if dialogue_message and not results:
                key = dialogue_keys.get(dialogue_message)
                status_text = texts.get(key, dialogue_message) if key else dialogue_message
                self.parent_window.search_page.lbl_status.setText(status_text)
                return
            matched_by = str(getattr(self.worker, "dialogue_matched_by", "") or "").strip()
            if matched_by == "vector":
                mode_key = "search_dialogue_match_semantic"
            elif matched_by == "keyword_fuzzy":
                mode_key = "search_dialogue_match_fuzzy"
            else:
                mode_key = "search_dialogue_match_exact"
            mode_label = texts.get(mode_key, texts.get("search_tab_dialogue", "Subtitles"))
            status_text = texts.get(
                "search_done_dialogue",
                "{mode} · {duration:.2f}s · {count}",
            ).format(mode=mode_label, duration=duration, count=total_count)
            self.parent_window.search_page.lbl_status.setText(status_text)
            return

        if search_kind == "tags":
            tags_message = str(getattr(self.worker, "dialogue_status_message", "") or "").strip()
            tags_keys = {
                "no tag index (generate VLM tags on Understanding page first)": "search_tags_no_index",
                "no tag matches": "search_tags_no_matches",
                "empty query": "search_empty_tags",
            }
            if tags_message and not results:
                key = tags_keys.get(tags_message)
                status_text = texts.get(key, tags_message) if key else tags_message
                self.parent_window.search_page.lbl_status.setText(status_text)
                return
            matched_by = str(getattr(self.worker, "dialogue_matched_by", "") or "").strip()
            if matched_by == "keyword_fuzzy":
                mode_key = "search_tags_match_fuzzy"
            else:
                mode_key = "search_tags_match_exact"
            mode_label = texts.get(mode_key, texts.get("search_tab_tags", "Tags"))
            status_text = texts.get(
                "search_done_tags",
                "{mode} · {duration:.2f}s · {count}",
            ).format(mode=mode_label, duration=duration, count=total_count)
            self.parent_window.search_page.lbl_status.setText(status_text)
            return

        status_text = texts["search_done"].format(duration=duration, count=total_count)
        if getattr(self, "_visual_results_flat", False):
            flat_hint = str(texts.get("search_results_closest_only") or "").strip()
            if flat_hint:
                status_text = f"{status_text} · {flat_hint}"
        clip_score_mode = bool(context.get("clip_score_mode"))
        if clip_score_mode:
            try:
                from src.domain.search_hit import coerce_search_hit
                from src.services.search_service import (
                    format_clip_score_percent,
                    resolve_clip_confidence_label,
                    resolve_clip_confidence_tier_key,
                )
                from src.services.search_telemetry import record_crop_confidence

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
                # Compact: "完成 0.03s · 1 条 · CLIP 100%/很高"
                clip_bits = [f"CLIP {top_label}"]
                if tier_label:
                    clip_bits.append(str(tier_label))
                status_text = f"{status_text} · {'/'.join(clip_bits)}"
            except Exception as exc:
                logger.debug("Crop confidence status formatting skipped: %s", exc)
        warning_key = getattr(self.worker, "locate_warning_key", None)
        if warning_key:
            # Keep warnings short in the status chip; full text is available elsewhere if needed.
            if warning_key == "locate_crop_low_confidence":
                status_text = f"{status_text} · {texts.get('clip_confidence_low', '低')}"
            elif warning_key == "locate_crop_low_confidence_empty":
                status_text = f"{status_text} · {texts.get('locate_crop_low_confidence_empty', '')}"
        if results and search_kind not in {"dialogue", "tags"}:
            try:
                from src.domain.search_hit import coerce_search_hit

                has_video_hit = any(
                    str(getattr(coerce_search_hit(row), "match_kind", "") or "").strip().lower() == "video"
                    for row in results
                )
            except Exception as exc:
                from src.app.logging_utils import note_swallowed

                note_swallowed(exc, "ui/controllers/search_controller.py:571")
                has_video_hit = False
            if has_video_hit:
                deep_hint = str(texts.get("search_done_deep_locate_hint", "") or "").strip()
                if deep_hint:
                    status_text = f"{status_text} · {deep_hint}"
        self.parent_window.search_page.lbl_status.setText(status_text)

    def _viewport_thumb_slots(self) -> int:
        """How many result rows fit on one screen."""
        view = self._result_view()
        if view.view_mode == "grid":
            grid = view.grid
            cols = max(1, int(getattr(grid, "_cols", 1) or 1))
            cards = list(getattr(grid, "_cards", None) or [])
            card_h = int(cards[0].sizeHint().height()) if cards else 180
            row_h = max(1, card_h + 12)
            rows = max(1, int(grid.viewport().height()) // row_h)
            return max(1, cols * rows)
        header = view.table.verticalHeader()
        row_h = max(1, int(header.defaultSectionSize() or 88))
        return max(1, int(view.table.viewport().height()) // row_h)

    def _visible_thumb_indices(self, total: int, *, lookahead_screens: int = 1) -> list[int]:
        """Decode only the viewport plus one screen ahead. Hundreds of seeks make the fans scream."""
        count = max(0, int(total))
        if count <= 0:
            return []
        end = self._furthest_visible_index()
        if end < 0:
            end = min(count - 1, self._viewport_thumb_slots() - 1)
        slots = self._viewport_thumb_slots()
        start = max(0, int(end) - slots + 1)
        last = min(count - 1, int(end) + slots * max(0, int(lookahead_screens)))
        return list(range(start, last + 1))

    def _schedule_visible_thumbnails(self) -> None:
        from PySide6.QtCore import QTimer

        timer = self._thumb_scroll_timer
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(80)
            timer.timeout.connect(self._ensure_visible_thumbnails)
            self._thumb_scroll_timer = timer
        timer.start()

    def _ensure_visible_thumbnails(self) -> None:
        if self._pin_top_guard or self._resetting_scroll:
            return
        rows = list(self._all_results or [])
        if not rows:
            return
        jobs = [(index, rows[index]) for index in self._visible_thumb_indices(len(rows))]
        self._start_page_thumbnails(jobs)

    def _start_page_thumbnails(self, page_results) -> None:
        rows = list(page_results or [])
        if not rows:
            return
        from src.app.config import load_config
        from ui.thumb_cache import get_thumb_cache, result_thumb_key

        config = load_config()
        cfg_w = int(config.get("thumb_width", 130) or 130)
        cfg_h = int(config.get("thumb_height", 75) or 75)
        view = self._result_view()
        from ui.widgets.thumb_cell import screen_thumb_scale

        scale = screen_thumb_scale()
        percent = int(getattr(view, "display_scale_percent", 100) or 100)
        if view.view_mode == "grid":
            from ui.widgets.result_grid import grid_thumb_pixel_size

            disp_w, disp_h = grid_thumb_pixel_size(percent)
        else:
            from ui.widgets.result_view import table_display_metrics

            row_h, preview_w = table_display_metrics(percent)
            disp_w = int(round(preview_w * scale))
            disp_h = int(round(row_h * scale))
        thumb_width = max(cfg_w, disp_w)
        thumb_height = max(cfg_h, disp_h)
        cache = get_thumb_cache()
        misses = []
        for index, raw in enumerate(rows):
            if (
                isinstance(raw, (tuple, list))
                and len(raw) == 2
                and isinstance(raw[0], int)
                and not isinstance(raw[0], bool)
            ):
                index, raw = int(raw[0]), raw[1]
            hit = coerce_search_hit(raw)
            cached = cache.get(
                result_thumb_key(
                    hit.video_path,
                    hit.start_sec,
                    hit.end_sec,
                    thumb_width,
                    thumb_height,
                    peak_sec=getattr(hit, "peak_sec", None),
                )
            )
            pixmap = self._pixmap_from_cached_thumb(cached)
            if pixmap is not None:
                self._result_view().set_thumbnail(index, pixmap)
            else:
                misses.append((index, raw))
        if not misses:
            return
        miss_indices = {int(item[0]) for item in misses}
        active = self.thumb_thread
        if (
            active is not None
            and active.isRunning()
            and miss_indices
            and miss_indices.issubset(self._thumb_loading_indices)
            and int(getattr(active, "_thumb_width", 0) or 0) == int(thumb_width)
            and int(getattr(active, "_thumb_height", 0) or 0) == int(thumb_height)
        ):
            return
        self.stop_thumbnail_loading()
        self._thumb_loading_indices = miss_indices
        self.thumb_thread = ThumbLoader(
            misses,
            priority_rows=miss_indices,
            thumb_width=thumb_width,
            thumb_height=thumb_height,
        )
        self.thumb_thread.thumb_ready.connect(self._on_thumb_ready)
        self.thumb_thread.start()

    def _pixmap_from_cached_thumb(self, image):
        from PySide6.QtGui import QImage, QPixmap

        if isinstance(image, QImage) and not image.isNull():
            return QPixmap.fromImage(image)
        if isinstance(image, QPixmap) and not image.isNull():
            return image
        return None

    def _finish_search(self):
        if self._is_shutdown or not self._is_current_worker():
            return
        self.parent_window.search_page.btn_search.setEnabled(True)

    def _finish_warmup(self):
        if self._is_shutdown:
            return
        self.warmup_worker = None
        parent = self.parent_window
        # Prefer clip half of the bundled CLIP+VLC warmup gate.
        on_clip = getattr(type(parent), "_on_clip_warmup_finished", None)
        if callable(on_clip):
            on_clip(parent)
            return
        on_runtime = getattr(type(parent), "_on_runtime_warmup_finished", None)
        if callable(on_runtime):
            on_runtime(parent)
            return
        parent.push_inference_status()

    def _handle_search_error(self, error_text):
        if self._is_shutdown or not self._is_current_worker():
            return
        self.parent_window.push_inference_status()
        from src.services.team_client_search import is_team_search_busy_error

        if is_team_search_busy_error(error_text):
            busy_text = self.parent_window.texts.get(
                "search_team_busy",
                "服务机搜索繁忙，请稍后再试。",
            )
            self.parent_window.search_page.lbl_status.setText(busy_text)
            self.parent_window.show_info_dialog(
                self.parent_window.texts.get("info_title", self.parent_window.texts.get("warning_title", "Info")),
                busy_text,
                kind="warning",
            )
            return
        self.parent_window.search_page.lbl_status.setText(self.parent_window.texts["search_failed"])
        from src.core.clip_embedding import get_engine_runtime_status, get_engine_runtime_warning

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
