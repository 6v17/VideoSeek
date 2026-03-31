import os

from PySide6.QtCore import QUrl

from src.utils import build_preview_cache_path, create_preview_clip


class PreviewController:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.current_preview_path = None

    def play(self, video_path, start_sec):
        media_player = self.parent_window.media_player
        media_player.stop()
        media_player.setSource(QUrl())

        cache_path = build_preview_cache_path(video_path, start_sec)
        result = create_preview_clip(video_path, start_sec, cache_path)
        if result.returncode == 0:
            self.cleanup_previous_preview()
            self.current_preview_path = cache_path
            media_player.setSource(QUrl.fromLocalFile(cache_path))
            media_player.play()
            return True

        if os.path.exists(cache_path):
            os.remove(cache_path)
        return False

    def cleanup_previous_preview(self):
        if not self.current_preview_path:
            return
        if os.path.exists(self.current_preview_path):
            try:
                os.remove(self.current_preview_path)
            except OSError:
                pass
        self.current_preview_path = None

    def shutdown(self):
        self.parent_window.media_player.stop()
        self.parent_window.media_player.setSource(QUrl())
        self.cleanup_previous_preview()
