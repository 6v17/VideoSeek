"""Wire gallery folders to sync, and the Pictures search tab to still results."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFileDialog

from src.app.logging_utils import get_logger
from src.services.image_gallery_service import (
    add_image_folder,
    gallery_status,
    open_original_image,
    remove_image_folder,
)
from ui.threading_utils import bind_thread_release
from ui.workers import ImageGalleryPreviewWorker, ImageGallerySearchWorker, ImageGallerySyncWorker

logger = get_logger("image_gallery_controller")


class ImageGalleryController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self._sync_worker = None
        self._search_worker = None
        self._preview_worker = None
        self._preview_path = ""
        self._search_generation = 0
        self._hit_scores: dict[str, float] = {}
        page = self.page
        page.add_folder_clicked.connect(self.add_folder)
        page.remove_folder_clicked.connect(self.remove_folder)
        page.sync_clicked.connect(self.start_sync)
        page.refresh_clicked.connect(self.refresh_folders)
        page.open_folder_requested.connect(self.open_folder)

    @property
    def page(self):
        return self.parent_window.gallery_page

    def is_busy(self) -> bool:
        return self._is_running(self._sync_worker) or self._is_running(self._search_worker)

    def refresh(self, *, status_text: str | None = None) -> None:
        texts = self.parent_window.texts
        page = self.page
        try:
            status = gallery_status()
        except Exception as exc:
            logger.warning("Image gallery status unavailable: %s", exc)
            page.show_libraries([], [])
            page.set_status(texts.get("gallery_profile_unavailable", ""))
            return
        page.show_libraries(
            self._library_entries(status, texts),
            [str(folder.get("path") or "") for folder in (status.get("folders") or []) if str(folder.get("path") or "")],
        )
        summary = texts.get("gallery_summary", "").format(
            indexed=int(status.get("indexed") or 0),
            failed=int(status.get("failed") or 0),
        )
        if status.get("stale"):
            summary = f"{summary} {texts.get('gallery_stale', '')}".strip()
        page.set_status(status_text if status_text is not None else summary)

    def _result_grid(self):
        page = getattr(self.parent_window, "search_page", None)
        return getattr(page, "gallery_results", None)

    def _reject_if_busy(self) -> bool:
        texts = self.parent_window.texts
        if self._is_running(self._sync_worker):
            self.page.set_status(texts.get("gallery_sync_busy", ""))
            return True
        if self._is_running(self._search_worker):
            self.page.set_status(texts.get("gallery_searching", ""))
            return True
        return False

    def add_folder(self) -> None:
        if self._reject_if_busy():
            return
        texts = self.parent_window.texts
        path = QFileDialog.getExistingDirectory(
            self.parent_window,
            texts.get("gallery_select_folder", ""),
        )
        if not str(path or "").strip():
            return
        try:
            add_image_folder(path)
        except ValueError as exc:
            code = str(exc)
            if code == "folder_exists":
                self.page.set_status(texts.get("gallery_folder_exists", ""))
            else:
                self.page.set_status(texts.get("gallery_folder_invalid", ""))
            return
        except Exception as exc:
            self.parent_window.show_error_dialog(texts.get("gallery_folder_invalid", ""), exc)
            return
        self.refresh()
        self.start_sync(embed=False)

    def remove_folder(self) -> None:
        if self._reject_if_busy():
            return
        texts = self.parent_window.texts
        folders = self.page.selected_folders()
        if not folders:
            self.page.set_status(texts.get("gallery_no_folder_selected", ""))
            return
        if len(folders) == 1:
            message = texts.get("gallery_remove_confirm", "")
        else:
            message = texts.get("gallery_remove_confirm_many", "").format(count=len(folders))
        if not self.parent_window.show_confirm_dialog(texts.get("confirm_title", ""), message):
            return
        try:
            for folder in folders:
                remove_image_folder(folder)
        except Exception as exc:
            self.parent_window.show_error_dialog(texts.get("gallery_remove_folder", ""), exc)
            self.refresh()
            return
        self.refresh()

    def open_folder(self, path: str) -> None:
        from src.utils import open_folder_in_explorer

        target = str(path or "").strip()
        if not target:
            return
        open_folder_in_explorer(target)

    def refresh_folders(self) -> None:
        """Rescan checked folders and update the list. Indexing stays on Sync."""
        texts = self.parent_window.texts
        if self._is_running(self._sync_worker) or self._is_running(self._search_worker):
            self.page.set_status(texts.get("gallery_sync_busy", ""))
            return
        folders = self.page.selected_folders()
        if not folders:
            self.page.set_status(texts.get("gallery_refresh_need_selection", ""))
            return
        self.start_sync(embed=False, folders=folders)

    def start_sync(self, *, embed: bool = True, folders=None) -> None:
        texts = self.parent_window.texts
        if self._is_running(self._sync_worker):
            self._sync_worker.stop()
            self.page.set_status(texts.get("gallery_stopping", ""))
            return
        if self._is_running(self._search_worker):
            self.page.set_status(texts.get("gallery_searching", ""))
            return
        worker = ImageGallerySyncWorker(embed=embed, folders=None if embed else folders)
        worker.progress_signal.connect(self._on_sync_progress)
        worker.error_signal.connect(self._on_sync_error)
        worker.finished_signal.connect(self._on_sync_finished)
        bind_thread_release(self, "_sync_worker", worker)
        self._sync_worker = worker
        self.page.set_busy(True)
        self.page.set_progress(0, texts.get("gallery_sync_scan", ""))
        worker.start()

    def start_composed_search(self, text: str, image_paths, fusion, min_score: float) -> None:
        texts = self.parent_window.texts
        query = str(text or "").strip()
        paths = [str(path or "").strip() for path in (image_paths or []) if str(path or "").strip()]
        status = self.parent_window.search_page.lbl_status
        grid = self._result_grid()
        if not query and not paths:
            status.setText(texts.get("gallery_empty_query", ""))
            if grid is not None:
                grid.clear()
            self.clear_still()
            return
        if self._is_running(self._sync_worker):
            status.setText(texts.get("gallery_sync_busy", ""))
            return
        previous = self._search_worker
        if previous is not None and previous.isRunning():
            previous.stop()
        self._search_generation += 1
        worker = ImageGallerySearchWorker(
            query,
            self._search_generation,
            image_paths=paths,
            fusion=fusion,
            min_score=float(min_score or 0.0),
        )
        worker.hits_ready.connect(self._on_hits)
        worker.thumb_ready.connect(self._on_thumb)
        worker.finished_signal.connect(self._on_search_finished)
        bind_thread_release(self, "_search_worker", worker)
        self._search_worker = worker
        if grid is not None:
            grid.set_busy(True)
            grid.clear()
        status.setText(texts.get("gallery_searching", ""))
        worker.start()

    def clear_results(self) -> None:
        grid = self._result_grid()
        if grid is not None:
            grid.clear()
        self._hit_scores = {}
        self.clear_still()

    def preview_selected(self, path: str) -> None:
        target = str(path or "").strip()
        if not target:
            return
        self._preview_path = target
        preview = getattr(self.parent_window, "preview_controller", None)
        if preview is not None:
            preview.stop_preview()
        previous = self._preview_worker
        if previous is not None and previous.isRunning():
            previous.stop()
        worker = ImageGalleryPreviewWorker(target)
        worker.preview_ready.connect(self._on_preview)
        bind_thread_release(self, "_preview_worker", worker)
        self._preview_worker = worker
        worker.start()

    def locate_path(self, path: str) -> None:
        target = str(path or "").strip()
        if not target:
            return
        opener = getattr(self.parent_window, "open_result_in_explorer", None)
        if callable(opener):
            opener(target)
            return
        from src.utils import open_in_explorer

        open_in_explorer(target)

    def open_path(self, path: str, *_ignored) -> None:
        target = str(path or "").strip()
        if not target:
            return
        if open_original_image(target):
            return
        self.parent_window.show_info_dialog(
            self.parent_window.texts.get("gallery_page_title", ""),
            self.parent_window.texts.get("gallery_file_missing", ""),
        )

    def _on_sync_progress(self, phase: str, current: int, total: int) -> None:
        texts = self.parent_window.texts
        if phase == "listed":
            self.refresh()
            if total > 0:
                self.page.set_progress(
                    0,
                    texts.get("gallery_sync_progress", "").format(current=0, total=total),
                )
            else:
                self.page.set_progress(0, texts.get("gallery_sync_scan", ""))
            return
        if phase == "scan" or total <= 0:
            if phase == "scan" and current > 0:
                label = texts.get("gallery_sync_scan_count", "").format(count=current)
            else:
                label = texts.get("gallery_sync_scan", "")
            self.page.set_progress(0, label)
            return
        percent = max(0, min(99, int(current * 100 / total)))
        self.page.set_progress(
            percent,
            texts.get("gallery_sync_progress", "").format(current=current, total=total),
        )

    def _on_sync_error(self, message: str) -> None:
        self.parent_window.show_error_dialog(self.parent_window.texts.get("gallery_sync", ""), message)

    def _on_sync_finished(self, ok: bool, payload) -> None:
        self.page.set_busy(False)
        self.page.set_progress(None, "")
        texts = self.parent_window.texts
        summary = payload if isinstance(payload, dict) else {}
        if not ok:
            self.refresh()
            return
        if summary.get("mode") == "discover":
            template = "gallery_scan_stopped" if summary.get("stopped") else "gallery_scan_done"
            done = texts.get(template, "").format(count=int(summary.get("found") or 0))
            self.refresh(status_text=done)
            return
        template = "gallery_sync_stopped" if summary.get("stopped") else "gallery_sync_done"
        done = texts.get(template, "").format(
            embedded=int(summary.get("embedded") or 0),
            deleted=int(summary.get("deleted") or 0),
            failed=int(summary.get("failed") or 0),
        )
        self.refresh(status_text=done)

    def _on_hits(self, generation: int, hits) -> None:
        if generation != self._search_generation:
            return
        rows = list(hits or [])
        grid = self._result_grid()
        texts = self.parent_window.texts
        scored: dict[str, float] = {}
        packed = []
        for row in rows:
            path = str((row or {}).get("path") or "")
            score = float((row or {}).get("score") or 0.0)
            if path:
                scored[path] = score
            packed.append(self._still_hit(path, score))
        self._hit_scores = scored
        if grid is not None:
            grid.set_busy(False)
            grid.set_empty_message(texts.get("gallery_no_results", ""))
            grid.populate_local(packed, self._preview_from_result, self.locate_path, self.open_path, texts)
        self.clear_still()
        if rows:
            self.parent_window.search_page.lbl_status.setText(
                texts.get("gallery_results_count", "").format(count=len(rows))
            )
        else:
            self.parent_window.search_page.lbl_status.setText(texts.get("gallery_no_results", ""))

    def _on_thumb(self, generation: int, index: int, image) -> None:
        if generation != self._search_generation:
            return
        grid = self._result_grid()
        if grid is None or image is None or image.isNull():
            return
        grid.set_thumbnail(index, QPixmap.fromImage(image))

    def _on_search_finished(self, generation: int, ok: bool, message: str) -> None:
        if generation != self._search_generation:
            return
        if ok:
            return
        grid = self._result_grid()
        if grid is not None:
            grid.set_busy(False)
            grid.clear()
        self.clear_still()
        texts = self.parent_window.texts
        if str(message or "") == "model_mismatch":
            self.parent_window.search_page.lbl_status.setText(texts.get("gallery_model_mismatch", ""))
            return
        self.parent_window.show_error_dialog(texts.get("gallery_search_failed", ""), message)

    def _on_preview(self, path: str, image) -> None:
        if str(path or "") != self._preview_path:
            return
        grid = self._result_grid()
        score = self._hit_scores.get(path)
        self._show_still(image, path, score)

    def _preview_from_result(self, path: str, _start: float = 0.0, _end: float = 0.0) -> None:
        self.preview_selected(str(path or ""))

    @staticmethod
    def _still_hit(path: str, score: float):
        from src.domain.search_hit import SearchHit

        return SearchHit(0.0, 0.0, float(score), str(path), match_kind="image")

    def clear_still(self) -> None:
        self._preview_path = ""
        page = getattr(self.parent_window, "search_page", None)
        board = getattr(page, "gallery_board", None) if page is not None else None
        if board is not None:
            board.show_empty()

    def _show_still(self, image, path: str, score: float | None) -> None:
        page = self.parent_window.search_page
        board = getattr(page, "gallery_board", None)
        if board is None:
            return
        board.show_still(image, path, score, self.parent_window.texts)

    @staticmethod
    def _library_entries(status: dict, texts: dict) -> list[dict]:
        ready_text = texts.get("gallery_file_ready", "")
        failed_text = texts.get("gallery_file_failed", "")
        stale_text = texts.get("gallery_file_stale", "")
        pending_text = texts.get("gallery_file_pending", "")
        entries = []
        for row in status.get("files") or []:
            path = str(row.get("path") or "")
            folder = str(row.get("folder") or "")
            if not path or not folder:
                continue
            if row.get("failed"):
                status_text, tone, state = failed_text, "fix", "missing_asset"
            elif row.get("pending"):
                status_text, tone, state = pending_text, "pending", "pending"
            elif row.get("stale"):
                status_text, tone, state = stale_text, "pending", "pending"
            else:
                status_text, tone, state = ready_text, "ready", "ready"
            try:
                rel = os.path.relpath(path, folder)
            except ValueError:
                rel = os.path.basename(path)
            entries.append(
                {
                    "library_path": folder,
                    "video_id": path,
                    "video_path": path,
                    "video_rel_path": rel,
                    "status_text": status_text,
                    "status_tone": tone,
                    "asset_state": state,
                    "source_exists": True,
                }
            )
        return entries

    @staticmethod
    def _is_running(worker) -> bool:
        return worker is not None and worker.isRunning()
