import cv2
import os
import traceback
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
from src.services.model_service import download_models
from src.services.notice_service import get_notice_payload
from src.services.remote_library_service import build_remote_library_from_links
from src.services.remote_search_service import run_remote_search
from src.services.search_service import warmup_search_runtime
from src.services.version_service import get_version_status
from ui.playback.vlc_player import warmup_vlc_runtime

logger = get_logger("workers")


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


class SearchWorker(QThread):
    result_ready = Signal(list)
    error_signal = Signal(str)
    progress_signal = Signal(str)
    finished = Signal()

    def __init__(
        self,
        query=None,
        is_text=True,
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
    ):
        super().__init__()
        self.query = query
        self.is_text = bool(is_text)
        self.scope_library_paths = list(scope_library_paths or [])
        self.scope_video_paths = list(scope_video_paths or [])
        self.query_vector = query_vector
        self.search_mode = search_mode
        self.top_k = top_k
        self.min_score = min_score
        self.search_precision_mode = search_precision_mode
        self.pixel_query_data = pixel_query_data
        self.preview_anchor_sec = preview_anchor_sec
        self.locate_anchor_score = locate_anchor_score
        self.locate_score_margin = locate_score_margin
        self.locate_warning_key = None

    def _emit_progress(self, phase: str, message: str = "") -> None:
        key = str(message or phase or "").strip()
        if key:
            self.progress_signal.emit(key)

    def run(self):
        try:
            from src.services.search_service import filter_hits_by_min_score, run_search

            mode = str(self.search_mode or "").strip().lower()
            base_kwargs = {
                "query_data": self.query,
                "is_text": self.is_text,
                "top_k": self.top_k,
                "scope_video_paths": self.scope_video_paths or None,
                "scope_library_paths": self.scope_library_paths or None,
                "query_vector": self.query_vector,
            }
            results = run_search(
                search_mode=mode or None,
                search_precision_mode=self.search_precision_mode,
                pixel_query_data=self.pixel_query_data,
                preview_anchor_sec=self.preview_anchor_sec,
                locate_anchor_score=self.locate_anchor_score,
                locate_score_margin=self.locate_score_margin,
                progress_callback=self._emit_progress,
                **base_kwargs,
            )
            results = filter_hits_by_min_score(results, self.min_score)
            from src.services.search_service import locate_crop_confidence_warning_key

            self.locate_warning_key = locate_crop_confidence_warning_key(
                list(results) if results is not None else [],
                self.query,
                preview_anchor_sec=self.preview_anchor_sec,
                pixel_query_data=self.pixel_query_data,
            )
            self.result_ready.emit(list(results) if results is not None else [])
        except Exception as exc:
            traceback.print_exc()
            error_text = str(exc).strip() or repr(exc)
            print(f"Search Error: {error_text}")
            self.error_signal.emit(error_text)
        finally:
            self.finished.emit()


class SearchWarmupWorker(QThread):
    finished = Signal()

    def run(self):
        try:
            warmup_search_runtime()
        except Exception as exc:
            print(f"Search Warmup Error: {exc}")
        finally:
            self.finished.emit()


class PreviewWarmupWorker(QThread):
    finished = Signal()

    def run(self):
        try:
            warmup_vlc_runtime()
        except Exception as exc:
            print(f"Preview Warmup Error: {exc}")
        finally:
            self.finished.emit()


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
    ):
        super().__init__()
        self.target_lib = target_lib
        self.force_cleanup_missing_files = force_cleanup_missing_files
        self.cleanup_missing_entries = list(cleanup_missing_entries or [])
        self.rebuild_global_assets = bool(rebuild_global_assets)
        self.index_from_vectors_only = bool(index_from_vectors_only)
        self.debug_failure = str(debug_failure or "").strip().lower()
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
            if self.index_from_vectors_only:
                from src.workflows.update_video import rebuild_indexes_from_vectors_flow

                logger.info(
                    "Index rebuild-from-vectors worker starting: target_lib=%s",
                    self.target_lib,
                )
                stats = rebuild_indexes_from_vectors_flow(
                    target_lib=self.target_lib,
                    progress_callback=lambda progress, text: self.progress_signal.emit(progress, text),
                    should_stop_callback=lambda: self._stop_requested or self.isInterruptionRequested(),
                    rebuild_global=self.rebuild_global_assets,
                )
                has_search_assets = bool(stats.get("global_built")) or int(stats.get("per_video_rebuilt", 0) or 0) > 0
                self.finished_signal.emit(True, False, has_search_assets, issues)
                return

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


def _iter_thumb_jobs(results):
    """Yield (table_row, hit_payload). Entries may be hits or (row, hit) pairs."""
    for default_row, entry in enumerate(results or []):
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            yield int(entry[0]), entry[1]
        else:
            yield default_row, entry


class ThumbLoader(QThread):
    thumb_ready = Signal(int, object)

    def __init__(self, results):
        super().__init__()
        self.results = results
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        from src.utils import get_single_thumbnail
        config = load_config()
        thumb_width = config.get("thumb_width", 130)
        thumb_height = config.get("thumb_height", 75)

        for table_row, raw in _iter_thumb_jobs(self.results):
            if not self._running or self.isInterruptionRequested():
                break

            hit = coerce_search_hit(raw)
            video_path = str(hit.video_path or "").strip()
            if not video_path:
                self.thumb_ready.emit(table_row, None)
                continue

            thumb_time = float(hit.start_sec)
            if float(hit.end_sec) > float(hit.start_sec):
                thumb_time = (float(hit.start_sec) + float(hit.end_sec)) / 2.0

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
            self.thumb_ready.emit(table_row, pixmap)


class VersionCheckWorker(QThread):
    result_ready = Signal(dict)

    def __init__(self, language):
        super().__init__()
        self.language = language

    def run(self):
        try:
            result = get_version_status(self.language)
            self.result_ready.emit(result)
        except Exception as exc:
            print(f"Version Check Error: {exc}")


class NoticeFetchWorker(QThread):
    result_ready = Signal(dict)

    def __init__(self, language):
        super().__init__()
        self.language = language

    def run(self):
        try:
            result = get_notice_payload(self.language)
            self.result_ready.emit(result)
        except Exception as exc:
            print(f"Notice Fetch Error: {exc}")


class AboutFetchWorker(QThread):
    result_ready = Signal(dict)

    def __init__(self, language):
        super().__init__()
        self.language = language

    def run(self):
        try:
            result = get_about_payload(self.language)
            self.result_ready.emit(result)
        except Exception as exc:
            print(f"About Fetch Error: {exc}")


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


class RemoteSearchWorker(QThread):
    result_ready = Signal(list)
    error_signal = Signal(str)
    finished = Signal()

    def __init__(self, query_data, is_text):
        super().__init__()
        self.query_data = query_data
        self.is_text = is_text

    def run(self):
        try:
            results = run_remote_search(self.query_data, is_text=self.is_text)
            self.result_ready.emit(results or [])
        except Exception as exc:
            self.error_signal.emit(str(exc))
        finally:
            self.finished.emit()


class RemoteLibraryBuildWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(dict)
    error_signal = Signal(str)

    def __init__(self, links, mode):
        super().__init__()
        self.links = links
        self.mode = mode

    def run(self):
        try:
            result = build_remote_library_from_links(
                self.links,
                mode=self.mode,
                incremental=True,
                progress_callback=lambda value, text: self.progress_signal.emit(value, text),
            )
            self.finished_signal.emit(result)
        except Exception as exc:
            self.error_signal.emit(str(exc))


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
                aggregate = {"imported": 0, "updated": 0, "errors": [], "checksum_verified_count": 0}
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
                    package_result = import_model_package_zip(self.model_root, zip_path, sha256_file=matching_sha)
                    aggregate["imported"] += int(package_result.get("imported", 0))
                    aggregate["updated"] += int(package_result.get("updated", 0))
                    aggregate["errors"].extend(package_result.get("errors", []))
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
