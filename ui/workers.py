import cv2
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QImage, QPixmap

from src.app.config import load_config
from src.core.core import run_search
from src.services.notice_service import get_notice_payload
from src.services.version_service import get_version_status


class SearchWorker(QThread):
    result_ready = Signal(list)
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
        finally:
            self.finished.emit()


class IndexUpdateWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool)

    def __init__(self, target_lib=None):
        super().__init__()
        self.target_lib = target_lib

    def run(self):
        try:
            from src.workflows.update_video import update_videos_flow

            result = update_videos_flow(
                target_lib=self.target_lib,
                progress_callback=lambda progress, text: self.progress_signal.emit(progress, text),
            )
            self.finished_signal.emit(result[0] is not None)
        except Exception as exc:
            print(f"Update Error: {exc}")
            self.finished_signal.emit(False)


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

        for row, (_, sec, _, video_path) in enumerate(self.results):
            if not self._running:
                break

            frame = get_single_thumbnail(video_path, sec)
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
