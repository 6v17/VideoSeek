import os

from PySide6.QtCore import QUrl

from src.app.config import load_config
from src.utils import build_preview_cache_path, create_preview_clip, export_original_clip, get_video_duration_seconds


class PreviewController:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.current_preview_path = None

    def resolve_clip_window(self, video_path, start_sec, end_sec=None):
        start_sec = float(start_sec)
        video_duration = get_video_duration_seconds(video_path)
        if video_duration is not None:
            video_duration = max(0.0, float(video_duration))

        if end_sec is not None and float(end_sec) > start_sec + 1e-3:
            clip_start = max(0.0, start_sec)
            clip_end = float(end_sec)
            if video_duration is not None:
                clip_end = min(clip_end, video_duration)
            clip_duration = max(0.1, clip_end - clip_start)
            return clip_start, clip_duration

        preview_seconds = float(load_config().get("preview_seconds", 6))
        clip_duration = max(0.1, preview_seconds)
        half = clip_duration / 2.0
        center = max(0.0, start_sec)
        if video_duration is not None:
            center = min(center, video_duration)

        clip_start = center - half
        clip_end = center + half
        if clip_start < 0.0:
            clip_end -= clip_start
            clip_start = 0.0
        if video_duration is not None and clip_end > video_duration:
            shift = clip_end - video_duration
            clip_start = max(0.0, clip_start - shift)
            clip_end = video_duration
        clip_duration = max(0.1, clip_end - clip_start)
        return clip_start, clip_duration

    def play(self, video_path, start_sec, end_sec=None):
        media_player = self.parent_window.media_player
        media_player.stop()
        media_player.setSource(QUrl())

        clip_start, clip_duration = self.resolve_clip_window(video_path, start_sec, end_sec=end_sec)

        cache_path = build_preview_cache_path(video_path, clip_start)
        result = create_preview_clip(video_path, clip_start, cache_path, duration_sec=clip_duration)
        if result.returncode == 0:
            self.cleanup_previous_preview()
            self.current_preview_path = cache_path
            media_player.setSource(QUrl.fromLocalFile(cache_path))
            media_player.play()
            return True

        if os.path.exists(cache_path):
            os.remove(cache_path)
        return False

    def export_clip(self, video_path, start_sec, output_path, end_sec=None):
        clip_start, clip_duration = self.resolve_clip_window(video_path, start_sec, end_sec=end_sec)
        return export_original_clip(video_path, clip_start, clip_duration, output_path)

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
