import os

from PySide6.QtCore import QUrl

from src.app.config import load_config
from src.app.logging_utils import get_logger
from ui.threading_utils import shutdown_thread
from src.utils import (
    _resolve_base_clip_window,
    build_preview_cache_path,
    create_preview_clip,
    export_original_clip,
    resolve_export_clip_window,
    start_export_original_clip_process,
)
from ui.playback.vlc_player import VlcPreviewPlayer
from ui.workers import PreviewWarmupWorker

logger = get_logger("preview_controller")


class PreviewController:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.current_preview_path = None
        self.current_preview_context = None
        self.vlc_player = None
        self._warmup_started = False
        self.warmup_worker = None

    def resolve_clip_window(self, video_path, start_sec, end_sec=None):
        return _resolve_base_clip_window(video_path, start_sec, end_sec=end_sec, config=load_config())

    def play(self, video_path, start_sec, end_sec=None):
        media_player = self.parent_window.media_player
        media_player.stop()
        media_player.setSource(QUrl())

        clip_start, clip_duration = self.resolve_clip_window(video_path, start_sec, end_sec=end_sec)
        clip_end = clip_start + clip_duration
        self.cleanup_previous_preview()
        self.current_preview_context = {
            "video_path": video_path,
            "start_sec": clip_start,
            "end_sec": clip_end,
            "suggested_sec": float(start_sec),
        }

        try:
            from src.services.search_telemetry import begin_playback_session

            begin_playback_session(
                video_path=video_path,
                suggested_sec=float(start_sec),
                playback_start_sec=float(clip_start),
            )
        except Exception as exc:
            logger.debug("Playback telemetry session start skipped: %s", exc)

        vlc_player = self._ensure_vlc_player()

        if vlc_player.play(video_path, clip_start, stop_sec=clip_end):
            return True

        cache_path = build_preview_cache_path(video_path, clip_start)
        result = create_preview_clip(video_path, clip_start, cache_path, duration_sec=clip_duration)
        if result.returncode == 0:
            self.current_preview_path = cache_path
            media_player.setSource(QUrl.fromLocalFile(cache_path))
            media_player.play()
            return True

        if os.path.exists(cache_path):
            os.remove(cache_path)
        return False

    def start_warmup(self):
        if self._warmup_started:
            return
        self._warmup_started = True
        self.warmup_worker = PreviewWarmupWorker()
        self.warmup_worker.finished.connect(self._finish_warmup)
        self.warmup_worker.start()

    def _ensure_vlc_player(self):
        if self.vlc_player is None:
            self.vlc_player = VlcPreviewPlayer(self.parent_window.video_widget)
        return self.vlc_player

    def _finish_warmup(self):
        self.warmup_worker = None

    def stop_preview(self, *, skip_telemetry: bool = False):
        if skip_telemetry:
            try:
                from src.services.search_telemetry import cancel_playback_session

                cancel_playback_session()
            except Exception as exc:
                logger.debug("Playback telemetry cancel skipped: %s", exc)
        else:
            self._record_playback_telemetry(source="inline")
        if self.vlc_player is not None:
            self.vlc_player.stop()
        self.parent_window.media_player.stop()
        self.parent_window.media_player.setSource(QUrl())
        self.cleanup_previous_preview()
        self.current_preview_context = None

    def record_playback_telemetry(self, *, source: str = "inline") -> None:
        self._record_playback_telemetry(source=source)

    def _record_playback_telemetry(self, *, source: str = "inline") -> None:
        actual_sec = None
        if self.vlc_player is not None and self.vlc_player.is_available():
            current_ms = self.vlc_player.get_time()
            if current_ms >= 0:
                actual_sec = float(current_ms) / 1000.0
        try:
            from src.services.search_telemetry import finish_playback_session

            finish_playback_session(actual_sec=actual_sec, source=source)
        except Exception as exc:
            logger.debug("Playback telemetry finish skipped: %s", exc)

    def get_current_preview_context(self):
        return dict(self.current_preview_context) if self.current_preview_context else None

    def export_clip(self, video_path, start_sec, output_path, end_sec=None, encode_mode=None):
        cfg = load_config()
        silent = bool(cfg.get("export_video_silent", False))
        mode = encode_mode if encode_mode is not None else cfg.get("export_encode_mode", "original")
        clip_start, clip_duration = resolve_export_clip_window(
            video_path,
            start_sec,
            end_sec=end_sec,
            encode_mode=mode,
            config=cfg,
        )
        return export_original_clip(
            video_path,
            clip_start,
            clip_duration,
            output_path,
            silent=silent,
            encode_mode=mode,
        )

    def start_export_process(self, video_path, start_sec, output_path, end_sec=None, encode_mode=None):
        cfg = load_config()
        silent = bool(cfg.get("export_video_silent", False))
        mode = encode_mode if encode_mode is not None else cfg.get("export_encode_mode", "original")
        clip_start, clip_duration = resolve_export_clip_window(
            video_path,
            start_sec,
            end_sec=end_sec,
            encode_mode=mode,
            config=cfg,
        )
        return start_export_original_clip_process(
            video_path,
            clip_start,
            clip_duration,
            output_path,
            silent=silent,
            encode_mode=mode,
        )

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
        shutdown_thread(self.warmup_worker)
        if self.vlc_player is not None:
            self.vlc_player.shutdown(fast=True)
            self.vlc_player = None
        self.parent_window.media_player.stop()
        self.parent_window.media_player.setSource(QUrl())
        self.cleanup_previous_preview()
        self.current_preview_context = None
