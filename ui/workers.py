import cv2
import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from src.app.config import load_config
from src.app.i18n import get_texts
from src.app.logging_utils import get_logger
from src.domain.search_hit import SearchHit, coerce_search_hit
from src.services.about_service import get_about_payload
from src.services.ffmpeg_service import download_ffmpeg
from src.services.library_service import list_local_vector_details
from src.services.model_package_service import import_model_package_zip, import_model_packages
from src.services.understanding_import_service import classify_package_zip, import_understanding_component_zip
from src.services.understanding_resource_service import SEARCH_MODEL_MANIFEST_FILENAME, UNDERSTANDING_MANIFEST_FILENAME
from src.services.model_service import download_models
from src.services.notice_service import get_notice_payload
from src.services.video_download_service import download_video, probe_video_links
from src.services.search_service import warmup_search_runtime
from src.services.version_service import get_version_status
from ui.playback.vlc_player import warmup_vlc_runtime

logger = get_logger("workers")


@dataclass
class SearchConfig:
    query: Any = None
    is_text: bool = True
    scope_library_paths: List[str] = field(default_factory=list)
    scope_video_paths: List[str] = field(default_factory=list)
    query_vector: Any = None
    search_mode: Optional[str] = None
    search_kind: Optional[str] = None
    top_k: Optional[int] = None
    min_score: Optional[float] = None
    search_precision_mode: Optional[str] = None
    pixel_query_data: Any = None
    preview_anchor_sec: Optional[float] = None
    locate_anchor_score: Optional[float] = None
    locate_score_margin: Optional[float] = None
    video_discovery_enabled: Optional[bool] = None


class FetchWorkerBase(QThread):
    result_ready = Signal(dict)

    def __init__(self, language, parent=None):
        super().__init__(parent)
        self.language = language

    def run(self):
        try:
            result = self._fetch_data()
            self.result_ready.emit(result)
        except Exception as exc:
            logger.warning("%s failed: %s", self.__class__.__name__, exc)

    def _fetch_data(self):
        raise NotImplementedError


class StartupMigrationWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def run(self):
        from src.storage.migration_runner import run_startup_migration

        try:
            result = run_startup_migration(
                progress_callback=lambda value, text: self.progress_signal.emit(int(value), str(text)),
            )
            payload = dict(result or {})
            payload["needs_background"] = False
            self.finished_signal.emit(payload)
        except Exception as exc:
            logger.exception("Background startup migration failed")
            self.error_signal.emit(str(exc).strip() or repr(exc))


class StorageRootMigrateWorker(QThread):
    """Copy data_root or model_dir to a new location with progress updates."""

    progress_signal = Signal(int, str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, kind: str, target_root: str):
        super().__init__()
        self.kind = str(kind or "").strip().lower()
        self.target_root = str(target_root or "").strip()

    def run(self):
        from src.services.storage_service import migrate_app_data_root, migrate_model_root

        try:
            callback = lambda value, text: self.progress_signal.emit(int(value), str(text))
            if self.kind == "model":
                result = migrate_model_root(self.target_root, progress_callback=callback)
            else:
                result = migrate_app_data_root(self.target_root, progress_callback=callback)
            self.finished_signal.emit(dict(result or {}))
        except Exception as exc:
            logger.exception("Storage root migration failed (%s)", self.kind)
            self.error_signal.emit(str(exc).strip() or repr(exc))


class SearchWorker(QThread):
    result_ready = Signal(list)
    error_signal = Signal(str)
    progress_signal = Signal(str)
    finished = Signal()

    def __init__(self, config: SearchConfig):
        super().__init__()
        self.config = config
        self.locate_warning_key = None
        self.dialogue_status_message = ""
        self.dialogue_matched_by = ""

    def _emit_progress(self, phase: str, message: str = "") -> None:
        key = str(message or phase or "").strip()
        if key:
            self.progress_signal.emit(key)

    def run(self):
        config = self.config
        try:
            from src.services.search_service import filter_hits_by_min_score, run_dialogue_search, run_search

            kind = str(config.search_kind or "").strip().lower()
            if kind == "dialogue":
                match_mode = str(config.search_mode or "exact").strip().lower() or "exact"
                results, message, matched_by = run_dialogue_search(
                    str(config.query or ""),
                    top_k=config.top_k,
                    scope_video_paths=config.scope_video_paths or None,
                    scope_library_paths=config.scope_library_paths or None,
                    min_score=config.min_score,
                    query_vector=config.query_vector,
                    match_mode=match_mode,
                )
                self.dialogue_status_message = str(message or "").strip()
                self.dialogue_matched_by = str(matched_by or "").strip()
                self.result_ready.emit(results)
                return

            mode = str(config.search_mode or "").strip().lower()
            base_kwargs = {
                "query_data": config.query,
                "is_text": config.is_text,
                "top_k": config.top_k,
                "scope_video_paths": config.scope_video_paths or None,
                "scope_library_paths": config.scope_library_paths or None,
                "query_vector": config.query_vector,
            }
            results = run_search(
                search_mode=mode or None,
                search_precision_mode=config.search_precision_mode,
                pixel_query_data=config.pixel_query_data,
                preview_anchor_sec=config.preview_anchor_sec,
                locate_anchor_score=config.locate_anchor_score,
                locate_score_margin=config.locate_score_margin,
                video_discovery_enabled=config.video_discovery_enabled,
                progress_callback=self._emit_progress,
                **base_kwargs,
            )
            results = filter_hits_by_min_score(results, config.min_score)
            from src.services.search_service import locate_crop_confidence_warning_key

            self.locate_warning_key = locate_crop_confidence_warning_key(
                list(results) if results is not None else [],
                config.query,
                preview_anchor_sec=config.preview_anchor_sec,
                pixel_query_data=config.pixel_query_data,
            )
            self.result_ready.emit(list(results) if results is not None else [])
        except Exception as exc:
            logger.exception("Search worker failed")
            error_text = str(exc).strip() or repr(exc)
            self.error_signal.emit(error_text)
        finally:
            self.finished.emit()


class SearchWarmupWorker(QThread):
    finished = Signal()

    def run(self):
        try:
            warmup_search_runtime()
        except Exception as exc:
            logger.warning("Search warmup failed: %s", exc)
        finally:
            self.finished.emit()


class PreviewWarmupWorker(QThread):
    finished = Signal()

    def run(self):
        try:
            warmup_vlc_runtime()
        except Exception as exc:
            logger.warning("Preview warmup failed: %s", exc)
        finally:
            self.finished.emit()


class DialogueIndexWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, bool, dict)
    error_signal = Signal(str)

    def __init__(
        self,
        targets=None,
        mode: str = "auto",
        sample_interval_sec: float | None = None,
        ocr_batch_size: int | None = None,
    ):
        super().__init__()
        self.targets = list(targets or [])
        self.mode = str(mode or "auto").strip().lower() or "auto"
        self.sample_interval_sec = None if sample_interval_sec is None else float(sample_interval_sec)
        self.ocr_batch_size = None if ocr_batch_size is None else int(ocr_batch_size)
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        self.requestInterruption()

    def run(self):
        from src.services.dialogue_index_service import index_video_dialogue

        summary = {
            "ok": 0,
            "failed": 0,
            "segment_rows": 0,
            "errors": [],
            "mode": self.mode,
            "reused": 0,
        }
        total = max(1, len(self.targets))
        stopped = False
        success = False
        try:
            for index, item in enumerate(self.targets):
                if self._stop_requested or self.isInterruptionRequested():
                    stopped = True
                    break
                video_id = str((item or {}).get("video_id", "") or "").strip()
                video_path = str((item or {}).get("video_path", "") or "").strip()
                library_path = str((item or {}).get("library_path", "") or "").strip()
                self.progress_signal.emit(
                    int((index / total) * 100),
                    f"dialogue_index|{index + 1}|{total}|{video_id}",
                )

                def _progress(fraction, stage):
                    base = index / total
                    span = 1.0 / total
                    value = int(min(99, (base + max(0.0, min(1.0, float(fraction))) * span) * 100))
                    self.progress_signal.emit(value, f"dialogue_index|{index + 1}|{total}|{stage}")

                result = index_video_dialogue(
                    video_id,
                    video_path,
                    library_path=library_path,
                    progress_callback=_progress,
                    stop_callback=lambda: self._stop_requested or self.isInterruptionRequested(),
                    mode=self.mode,
                    sample_interval_sec=self.sample_interval_sec,
                    ocr_batch_size=self.ocr_batch_size,
                )
                if result.get("ok"):
                    summary["ok"] += 1
                    summary["segment_rows"] += int(result.get("segment_rows", 0) or 0)
                    if result.get("reused_transcripts"):
                        summary["reused"] += 1
                else:
                    summary["failed"] += 1
                    err = str(result.get("error", "") or "failed")
                    summary["errors"].append(f"{video_id}: {err}")
            if not stopped:
                self.progress_signal.emit(
                    100,
                    f"dialogue_index|{total}|{total}|dialogue_index_done",
                )
                success = True
        except Exception as exc:
            logger.exception("Dialogue index worker failed")
            self.error_signal.emit(str(exc).strip() or repr(exc))
            success = False
        finally:
            # Always release the UI (buttons stay disabled until this fires).
            # Copy summary: queued signal delivery must not share a mutable dict
            # with this thread while run() is unwinding.
            self.finished_signal.emit(success, stopped, dict(summary))


class RemoveLibraryWorker(QThread):
    """Delete one or more libraries off the UI thread.

    ``mode="visual"``: CLIP profile library + exclusive Lance data (keeps OCR).
    ``mode="subtitle"``: global subtitle registry + OCR transcripts (keeps Lance).
    """

    progress_signal = Signal(int, str)
    finished_signal = Signal(bool)
    error_signal = Signal(str)

    def __init__(self, library_paths, *, mode: str = "visual"):
        super().__init__()
        if isinstance(library_paths, (list, tuple, set)):
            paths = [str(p or "").strip() for p in library_paths if str(p or "").strip()]
        else:
            text = str(library_paths or "").strip()
            paths = [text] if text else []
        self.library_paths = paths
        self.mode = "subtitle" if str(mode or "").strip().lower() == "subtitle" else "visual"

    def run(self):
        ok = False
        try:
            paths = list(self.library_paths)
            if not paths:
                ok = False
            else:
                total = len(paths)
                ok = True
                for index, path in enumerate(paths):
                    base = int((index / max(total, 1)) * 100)
                    span = max(1, int(100 / max(total, 1)))

                    def _progress(value, text, *, _base=base, _span=span, _i=index, _t=total):
                        mapped = min(99, _base + int(max(0, min(100, int(value))) * _span / 100))
                        raw = str(text or "")
                        if raw.startswith("remove_library|"):
                            self.progress_signal.emit(mapped, raw)
                        else:
                            self.progress_signal.emit(
                                mapped,
                                f"remove_library|{_i + 1}|{_t}|{path}",
                            )

                    self.progress_signal.emit(
                        base,
                        f"remove_library|{index + 1}|{total}|{path}",
                    )
                    if self.mode == "subtitle":
                        from src.services.subtitle_library_service import remove_subtitle_library

                        removed = bool(
                            remove_subtitle_library(path, progress_callback=_progress)
                        )
                    else:
                        from src.services.library_service import remove_library
                        from src.workflows.update_video import delete_physical_video_data

                        removed = bool(
                            remove_library(
                                path,
                                delete_physical_video_data,
                                progress_callback=_progress,
                            )
                        )
                    if not removed:
                        ok = False
                        break
                if ok:
                    self.progress_signal.emit(100, f"remove_library|{total}|{total}|done")
        except Exception as exc:
            logger.exception("Remove library worker failed")
            self.error_signal.emit(str(exc).strip() or repr(exc))
            ok = False
        finally:
            self.finished_signal.emit(ok)


class IndexUpdateWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, bool, bool, object)
    runtime_status_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(
        self,
        target_lib=None,
        force_cleanup_missing_files=False,
        cleanup_missing_entries=None,
        rebuild_global_assets=True,
        debug_failure="",
        index_from_vectors_only=False,
        video_ids=None,
    ):
        super().__init__()
        self.target_lib = target_lib
        self.force_cleanup_missing_files = force_cleanup_missing_files
        self.cleanup_missing_entries = list(cleanup_missing_entries or [])
        self.rebuild_global_assets = bool(rebuild_global_assets)
        self.index_from_vectors_only = bool(index_from_vectors_only)
        self.debug_failure = str(debug_failure or "").strip().lower()
        self.video_ids = list(video_ids) if video_ids is not None else None
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        self.requestInterruption()

    def run(self):
        issues = []
        previous_gpu_debug = os.environ.get("VIDEOSEEK_DEBUG_FORCE_GPU_OOM")
        previous_system_debug = os.environ.get("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM")
        try:
            if self.debug_failure == "gpu_oom":
                os.environ["VIDEOSEEK_DEBUG_FORCE_GPU_OOM"] = "1"
                os.environ.pop("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM", None)
            elif self.debug_failure == "system_oom":
                os.environ["VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM"] = "1"
                os.environ.pop("VIDEOSEEK_DEBUG_FORCE_GPU_OOM", None)
            from src.core.clip_embedding import get_engine_runtime_status, prepare_inference_runtime
            from src.workflows.update_video import update_videos_flow

            logger.info(
                "Index update worker starting runtime preparation: target_lib=%s force_cleanup_missing_files=%s cleanup_missing_entries=%s rebuild_global_assets=%s debug_failure=%s",
                self.target_lib,
                self.force_cleanup_missing_files,
                len(self.cleanup_missing_entries),
                self.rebuild_global_assets,
                self.debug_failure,
            )
            runtime_status = prepare_inference_runtime()
            effective_runtime_status = get_engine_runtime_status()
            logger.info(
                "Index update worker runtime ready: backend=%s initialized=%s warning=%s issue=%s",
                effective_runtime_status.get("backend", ""),
                effective_runtime_status.get("initialized"),
                bool(effective_runtime_status.get("warning")),
                effective_runtime_status.get("issue", ""),
            )
            self.runtime_status_signal.emit(effective_runtime_status)
            if runtime_status.get("warning"):
                language = load_config().get("language", "zh")
                self.progress_signal.emit(1, get_texts(language).get("gpu_runtime_compact", "GPU runtime unavailable, using CPU"))

            result = update_videos_flow(
                target_lib=self.target_lib,
                progress_callback=lambda progress, text: self.progress_signal.emit(progress, text),
                force_cleanup_missing_files=self.force_cleanup_missing_files,
                should_stop_callback=lambda: self._stop_requested or self.isInterruptionRequested(),
                cleanup_missing_entries=self.cleanup_missing_entries,
                issue_callback=issues.append,
                rebuild_global_assets=self.rebuild_global_assets,
                video_ids=self.video_ids,
            )
            self.finished_signal.emit(True, False, result[0] is not None, issues)
        except InterruptedError:
            self.finished_signal.emit(False, True, False, issues)
        except Exception as exc:
            logger.exception("Index update worker failed")
            self.error_signal.emit(str(exc))
            self.finished_signal.emit(False, False, False, issues)
        finally:
            if previous_gpu_debug is None:
                os.environ.pop("VIDEOSEEK_DEBUG_FORCE_GPU_OOM", None)
            else:
                os.environ["VIDEOSEEK_DEBUG_FORCE_GPU_OOM"] = previous_gpu_debug
            if previous_system_debug is None:
                os.environ.pop("VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM", None)
            else:
                os.environ["VIDEOSEEK_DEBUG_FORCE_SYSTEM_OOM"] = previous_system_debug


class UnderstandingVideoWorker(QThread):
    progress_signal = Signal(int, str)
    chunk_completed = Signal(int, int, object)
    finished_signal = Signal(bool, bool, object)
    error_signal = Signal(str)

    def __init__(self, video_id, model_dir=None):
        super().__init__()
        self.video_id = str(video_id or "").strip()
        self.model_dir = model_dir
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        self.requestInterruption()

    def run(self):
        try:
            from src.app.config import load_config
            from src.app.i18n import get_texts
            from src.core.understanding.base import UnderstandingStoppedError
            from src.services.understanding_service import generate_evidence_for_video

            config = load_config()
            language = config.get("language", "zh")
            texts = get_texts(language)

            def _chunk_completed(index, total, payload):
                progress = int(((int(index) + 1) / max(int(total), 1)) * 100)
                message = texts.get(
                    "understanding_chunk_progress",
                    "Generating segment {current}/{total}",
                ).format(current=int(index) + 1, total=int(total))
                self.progress_signal.emit(progress, message)
                self.chunk_completed.emit(int(index), int(total), payload)

            result = generate_evidence_for_video(
                self.video_id,
                config=config,
                model_dir=self.model_dir,
                chunk_completed_callback=_chunk_completed,
                should_stop_callback=lambda: self._stop_requested or self.isInterruptionRequested(),
            )
            stopped = bool(result.get("stopped")) or bool(getattr(self, "_stop_requested", False))
            self.finished_signal.emit(not stopped, stopped, result)
        except Exception as exc:
            from src.core.understanding.base import UnderstandingStoppedError

            if isinstance(exc, UnderstandingStoppedError):
                self.finished_signal.emit(False, True, {"video_id": self.video_id, "stopped": True})
                return
            logger.exception("Understanding video worker failed")
            self.error_signal.emit(str(exc))
            self.finished_signal.emit(False, False, {})


class UnderstandingWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, bool, object)
    error_signal = Signal(str)

    def __init__(self, target_lib=None, model_dir=None):
        super().__init__()
        self.target_lib = target_lib
        self.model_dir = model_dir
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        self.requestInterruption()

    def run(self):
        try:
            from src.app.config import load_config
            from src.app.i18n import get_texts
            from src.services.understanding_service import generate_evidence_batch

            config = load_config()
            language = config.get("language", "zh")
            texts = get_texts(language)

            def _progress_callback(progress, video_id, current, total):
                if total <= 0:
                    message = texts.get("understanding_generation_started", "Generating understanding evidence…")
                elif not video_id:
                    message = texts.get("understanding_generation_done", "Understanding evidence generation finished.")
                else:
                    message = texts.get(
                        "understanding_progress",
                        "Generating evidence ({current}/{total}): {video_id}",
                    ).format(current=current, total=total, video_id=video_id)
                self.progress_signal.emit(int(progress), message)

            result = generate_evidence_batch(
                target_lib=self.target_lib,
                config=config,
                model_dir=self.model_dir,
                progress_callback=_progress_callback,
                should_stop_callback=lambda: self._stop_requested or self.isInterruptionRequested(),
            )
            stopped = bool(result.get("stopped"))
            success = not stopped
            self.finished_signal.emit(success, stopped, result)
        except Exception as exc:
            logger.exception("Understanding evidence worker failed")
            self.error_signal.emit(str(exc))
            self.finished_signal.emit(False, False, {})


def _iter_thumb_jobs(results):
    """Yield (table_row, hit_payload). Entries may be hits or (row, hit) pairs."""
    for default_row, entry in enumerate(results or []):
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            yield int(entry[0]), entry[1]
        else:
            yield default_row, entry


class ThumbLoader(QThread):
    thumb_ready = Signal(int, object)

    def __init__(self, results, priority_rows=None):
        super().__init__()
        self.results = results
        self.priority_rows = set(priority_rows or [])
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        from src.utils import get_single_thumbnail
        from ui.thumb_cache import get_thumb_cache

        config = load_config()
        thumb_width = config.get("thumb_width", 130)
        thumb_height = config.get("thumb_height", 75)
        cache = get_thumb_cache()

        jobs = list(_iter_thumb_jobs(self.results))
        if self.priority_rows:
            jobs.sort(key=lambda item: (0 if item[0] in self.priority_rows else 1, item[0]))

        for table_row, raw in jobs:
            if not self._running or self.isInterruptionRequested():
                break

            hit = coerce_search_hit(raw)
            video_path = str(hit.video_path or "").strip()
            if not video_path or not os.path.isfile(video_path):
                self.thumb_ready.emit(table_row, None)
                continue

            thumb_time = float(hit.start_sec)
            if float(hit.end_sec) > float(hit.start_sec):
                thumb_time = (float(hit.start_sec) + float(hit.end_sec)) / 2.0

            cache_key = cache.make_key(video_path, thumb_time, thumb_width, thumb_height)
            cached = cache.get(cache_key)
            if cached is not None:
                self.thumb_ready.emit(table_row, cached)
                continue

            frame = get_single_thumbnail(video_path, thumb_time)
            if not self._running or self.isInterruptionRequested():
                break
            if frame is None:
                self.thumb_ready.emit(table_row, None)
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb_frame.shape
            image = QImage(rgb_frame.data, width, height, width * 3, QImage.Format_RGB888).copy()
            pixmap = QPixmap.fromImage(image).scaled(
                thumb_width,
                thumb_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            cache.put(cache_key, pixmap)
            self.thumb_ready.emit(table_row, pixmap)


class VersionCheckWorker(FetchWorkerBase):
    def _fetch_data(self):
        return get_version_status(self.language)


class NoticeFetchWorker(FetchWorkerBase):
    def _fetch_data(self):
        return get_notice_payload(self.language)


class AboutFetchWorker(FetchWorkerBase):
    def _fetch_data(self):
        return get_about_payload(self.language)


class ResourceDownloadWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, need_models=True, need_ffmpeg=True):
        super().__init__()
        self.need_models = need_models
        self.need_ffmpeg = need_ffmpeg

    def run(self):
        try:
            result = {"model_dir": "", "ffmpeg_path": ""}
            if self.need_models and self.need_ffmpeg:
                self.progress_signal.emit(0, "Preparing runtime resources")

            if self.need_models:
                model_result = download_models(
                    progress_callback=lambda progress, text: self.progress_signal.emit(
                        min(69, progress),
                        text,
                    )
                )
                result["model_dir"] = model_result.get("model_dir", "")

            if self.need_ffmpeg:
                ffmpeg_result = download_ffmpeg(
                    progress_callback=lambda current, total, label: self.progress_signal.emit(
                        70 + min(29, _ffmpeg_progress(current, total) // 3),
                        _ffmpeg_progress_text(current, total, label),
                    )
                )
                result["ffmpeg_path"] = ffmpeg_result.get("path", "")

            self.progress_signal.emit(100, "Runtime resources ready")
            self.finished_signal.emit(result)
        except Exception as exc:
            self.error_signal.emit(str(exc))


class VideoDownloadProbeWorker(QThread):
    result_ready = Signal(list)
    error_signal = Signal(str)
    finished = Signal()

    def __init__(self, links):
        super().__init__()
        self.links = list(links or [])

    def run(self):
        try:
            results = probe_video_links(self.links)
            self.result_ready.emit(results)
        except Exception as exc:
            self.error_signal.emit(str(exc))
        finally:
            self.finished.emit()


class VideoDownloadBatchWorker(QThread):
    task_started = Signal(int, str, str)
    task_progress = Signal(int, int, str)
    task_finished = Signal(int, dict)
    batch_finished = Signal(dict)
    error_signal = Signal(str)
    finished = Signal()

    def __init__(self, jobs, *, output_dir):
        super().__init__()
        self.jobs = list(jobs or [])
        self.output_dir = str(output_dir or "")

    def run(self):
        import time

        from src.app.config import load_config
        from src.services.video_download_service import download_video

        started = time.time()
        success_count = 0
        failed_count = 0
        try:
            base_config = load_config()
            for index, job in enumerate(self.jobs):
                url = str(job.get("url", "") or "")
                title = str(job.get("title", "") or url)
                quality = str(job.get("quality", "best") or "best")
                self.task_started.emit(index, title, url)

                def _progress(percent, text, idx=index):
                    self.task_progress.emit(idx, int(percent), str(text))

                config = dict(base_config)
                config["download_quality"] = quality
                result = download_video(
                    url,
                    output_dir=self.output_dir,
                    progress_callback=_progress,
                    config=config,
                )
                payload = {
                    "ok": result.ok,
                    "url": result.url,
                    "title": result.title,
                    "file_path": result.file_path,
                    "reason_code": result.reason_code,
                    "strategy_used": result.strategy_used,
                }
                if result.ok:
                    success_count += 1
                else:
                    failed_count += 1
                self.task_finished.emit(index, payload)
            summary = {
                "success_count": success_count,
                "failed_count": failed_count,
                "duration_sec": round(time.time() - started, 3),
            }
            self.batch_finished.emit(summary)
        except Exception as exc:
            self.error_signal.emit(str(exc))
        finally:
            self.finished.emit()


class LocalVectorDetailsWorker(QThread):
    result_ready = Signal(dict)
    error_signal = Signal(str)
    finished = Signal()

    def run(self):
        try:
            self.result_ready.emit(list_local_vector_details(validate_contents=True))
        except Exception as exc:
            logger.warning("local_vector_details_worker_failed: %s", exc)
            self.error_signal.emit(str(exc))
        finally:
            self.finished.emit()


class RemoteVlmConnectionTestWorker(QThread):
    result_ready = Signal(dict)
    error_signal = Signal(str)
    finished = Signal()

    def __init__(self, remote_vlm: dict, *, timeout_sec: float = 8.0, parent=None):
        super().__init__(parent)
        self.remote_vlm = dict(remote_vlm or {})
        self.timeout_sec = float(timeout_sec)

    def run(self):
        try:
            from src.services.understanding_resource_service import probe_remote_vlm_draft

            result = probe_remote_vlm_draft(self.remote_vlm, timeout_sec=self.timeout_sec)
            self.result_ready.emit(dict(result or {}))
        except Exception as exc:
            logger.warning("remote_vlm_connection_test_failed: %s", exc)
            self.error_signal.emit(str(exc))
        finally:
            self.finished.emit()


class ModelPackageImportWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, model_root, selected_files=None, scan_only=False):
        super().__init__()
        self.model_root = str(model_root or "").strip()
        self.selected_files = [str(path or "").strip() for path in (selected_files or []) if str(path or "").strip()]
        self.scan_only = bool(scan_only)

    def run(self):
        try:
            zip_files = [path for path in self.selected_files if path.lower().endswith(".zip")]
            sha256_files = [path for path in self.selected_files if path.lower().endswith(".sha256")]
            if zip_files and not self.scan_only:
                aggregate = {
                    "imported": 0,
                    "updated": 0,
                    "understanding_imported": [],
                    "understanding_updated": [],
                    "errors": [],
                    "checksum_verified_count": 0,
                }
                total = max(1, len(zip_files))
                for index, zip_path in enumerate(zip_files, start=1):
                    progress_before = int(((index - 1) / total) * 90)
                    self.progress_signal.emit(progress_before, f"Importing {os.path.basename(zip_path)}")
                    matching_sha = ""
                    expected_name = f"{os.path.basename(zip_path)}.sha256".lower()
                    for candidate in sha256_files:
                        if os.path.basename(candidate).lower() == expected_name:
                            matching_sha = candidate
                            break
                    package_kind = classify_package_zip(zip_path)
                    if package_kind == "understanding":
                        package_result = import_understanding_component_zip(
                            self.model_root,
                            zip_path,
                            sha256_file=matching_sha or None,
                        )
                        component_id = str(package_result.get("component_id", "") or "").strip()
                        if package_result.get("updated"):
                            aggregate["updated"] += 1
                            aggregate["understanding_updated"].append(component_id)
                        else:
                            aggregate["imported"] += 1
                            aggregate["understanding_imported"].append(component_id)
                    elif package_kind == "search":
                        package_result = import_model_package_zip(
                            self.model_root,
                            zip_path,
                            sha256_file=matching_sha,
                        )
                        aggregate["imported"] += int(package_result.get("imported", 0))
                        aggregate["updated"] += int(package_result.get("updated", 0))
                        aggregate["errors"].extend(package_result.get("errors", []))
                    else:
                        aggregate["errors"].append(
                            f"{os.path.basename(zip_path)}: unrecognized package "
                            f"(expected root {UNDERSTANDING_MANIFEST_FILENAME} or nested {SEARCH_MODEL_MANIFEST_FILENAME})"
                        )
                        continue
                    if package_result.get("checksum_verified"):
                        aggregate["checksum_verified_count"] += 1
                    progress_after = int((index / total) * 95)
                    self.progress_signal.emit(progress_after, f"Imported {index}/{total}")
                self.progress_signal.emit(100, "Model package import finished")
                self.finished_signal.emit(aggregate)
                return

            self.progress_signal.emit(20, "Scanning model directory")
            result = import_model_packages(self.model_root)
            self.progress_signal.emit(100, "Model directory scan finished")
            self.finished_signal.emit(result)
        except Exception as exc:
            self.error_signal.emit(str(exc))


def _ffmpeg_progress(current, total):
    if total <= 0:
        return 50
    return min(100, int((current / total) * 100))


def _ffmpeg_progress_text(current, total, label):
    source_text = f" via {label}" if label else ""
    if total > 0:
        return f"Downloading FFmpeg{source_text} ({current // 1024 // 1024}MB/{total // 1024 // 1024}MB)"
    return f"Downloading FFmpeg{source_text}"


class ShotListBatchExportWorker(QThread):
    finished_payload = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, items, output_dir, encode_mode, *, continue_on_error=True):
        super().__init__()
        self.items = list(items or [])
        self.output_dir = str(output_dir or "")
        self.encode_mode = str(encode_mode or "copy")
        self.continue_on_error = bool(continue_on_error)

    def run(self):
        from src.services.shot_list_export_service import export_shot_list_clips

        try:
            payload = export_shot_list_clips(
                self.items,
                output_dir=self.output_dir,
                encode_mode=self.encode_mode,
                continue_on_error=self.continue_on_error,
            )
            self.finished_payload.emit(dict(payload or {}))
        except Exception as exc:
            logger.exception("Shot list batch export failed")
            self.error_signal.emit(str(exc).strip() or repr(exc))
