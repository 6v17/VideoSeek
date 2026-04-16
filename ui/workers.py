import cv2
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from src.app.config import load_config
from src.app.i18n import get_texts
from src.app.logging_utils import get_logger
from src.core.core import run_search
from src.services.about_service import get_about_payload
from src.services.ffmpeg_service import download_ffmpeg
from src.services.model_service import download_models
from src.services.notice_service import get_notice_payload
from src.services.remote_library_service import build_remote_library_from_links
from src.services.search_service import warmup_search_runtime
from src.services.remote_search_service import run_remote_search
from src.services.version_service import get_version_status

logger = get_logger("workers")


class SearchWorker(QThread):
    result_ready = Signal(list)
    error_signal = Signal(str)
    finished = Signal()

    def __init__(self, query, is_text):
        super().__init__()
        self.query = query
        self.is_text = is_text

    def run(self):
        try:
            results = run_search(self.query, self.is_text)
            self.result_ready.emit(list(results) if results is not None else [])
        except Exception as exc:
            print(f"Search Error: {exc}")
            self.error_signal.emit(str(exc))
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


class IndexUpdateWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool, bool)
    runtime_status_signal = Signal(dict)

    def __init__(self, target_lib=None, force_cleanup_missing_files=False):
        super().__init__()
        self.target_lib = target_lib
        self.force_cleanup_missing_files = force_cleanup_missing_files
        self._stop_requested = False

    def stop(self):
        self._stop_requested = True
        self.requestInterruption()

    def run(self):
        try:
            from src.core.clip_embedding import get_engine_runtime_status, prepare_inference_runtime
            from src.workflows.update_video import update_videos_flow

            logger.info(
                "Index update worker starting runtime preparation: target_lib=%s force_cleanup_missing_files=%s",
                self.target_lib,
                self.force_cleanup_missing_files,
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
            )
            self.finished_signal.emit(result[0] is not None, False)
        except InterruptedError:
            self.finished_signal.emit(False, True)
        except Exception as exc:
            print(f"Update Error: {exc}")
            self.finished_signal.emit(False, False)


class ThumbLoader(QThread):
    thumb_ready = Signal(int, QPixmap)

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

        for row, (start_sec, _, _, video_path) in enumerate(self.results):
            if not self._running:
                break

            frame = get_single_thumbnail(video_path, start_sec)
            if frame is None:
                self.msleep(15)
                continue

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, _ = rgb_frame.shape
            image = QImage(rgb_frame.data, width, height, width * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(image).scaled(
                thumb_width,
                thumb_height,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.thumb_ready.emit(row, pixmap)
            self.msleep(15)


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


def _ffmpeg_progress(current, total):
    if total <= 0:
        return 50
    return min(100, int((current / total) * 100))


def _ffmpeg_progress_text(current, total, label):
    source_text = f" via {label}" if label else ""
    if total > 0:
        return f"Downloading FFmpeg{source_text} ({current // 1024 // 1024}MB/{total // 1024 // 1024}MB)"
    return f"Downloading FFmpeg{source_text}"
