# ui/workers.py
import numpy as np
import cv2
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QPixmap, QImage
from src.core import run_search

class SearchWorker(QThread):
    result_ready = Signal(list)
    finished = Signal()
    def __init__(self, query, is_text):
        super().__init__()
        self.query, self.is_text = query, is_text
    def run(self):
        try:
            results = run_search(self.query, self.is_text)
            self.result_ready.emit(list(results) if results is not None else [])
        except Exception as e: print(f"Search Error: {e}")
        finally: self.finished.emit()

class IndexUpdateWorker(QThread):
    progress_signal = Signal(int, str)
    finished_signal = Signal(bool)
    def __init__(self, target_lib=None):
        super().__init__()
        self.target_lib = target_lib
    def run(self):
        try:
            from src.update_video import update_videos_flow
            res = update_videos_flow(target_lib=self.target_lib,
                                   progress_callback=lambda p, t: self.progress_signal.emit(p, t))
            self.finished_signal.emit(res[0] is not None)
        except Exception as e: print(f"Update Error: {e}"); self.finished_signal.emit(False)

class ThumbLoader(QThread):
    """真正的后台搬运工：负责截图和缩放"""
    thumb_ready = Signal(int, QPixmap)
    def __init__(self, results):
        super().__init__()
        self.results = results
        self._running = True
    def stop(self): self._running = False
    def run(self):
        from src.utils import get_single_thumbnail
        for i, (ts, sec, score, v_path) in enumerate(self.results):
            if not self._running: break
            f = get_single_thumbnail(v_path, sec)
            if f is not None:
                rgb = cv2.cvtColor(f, cv2.COLOR_BGR2RGB)
                h, w, _ = rgb.shape
                qimg = QImage(rgb.data, w, h, w*3, QImage.Format_RGB888)
                pix = QPixmap.fromImage(qimg).scaled(130, 75, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.thumb_ready.emit(i, pix)
            self.msleep(15) # 稍微歇息，给视频播放留点CPU