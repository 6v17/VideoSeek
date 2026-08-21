import os

from PySide6.QtCore import QTimer, QUrl

from src.app.config import load_config
from src.app.logging_utils import get_logger
from ui.playback.vlc_player import (
    VlcPreviewPlayer,
    create_vlc_preview_instance,
    is_http_media_url,
    warmup_vlc_runtime,
)

logger = get_logger("preview_controller")


class PreviewController:
    def __init__(self, parent_window):
        self.parent_window = parent_window
        self.current_preview_path = None
        self.current_preview_context = None
        self.vlc_player = None
        self._vlc_instance = None
        self._warmup_started = False

    def resolve_clip_window(self, video_path, start_sec, end_sec=None):
        from src.media.export_clip import _resolve_base_clip_window

        return _resolve_base_clip_window(
            video_path,
            start_sec,
            end_sec=end_sec,
            config=load_config(),
            skip_duration_probe=is_http_media_url(video_path),
        )

    def play(self, video_path, start_sec, end_sec=None):
        media_player = self.parent_window.media_player
        media_player.stop()
        media_player.setSource(QUrl())

        clip_start, clip_duration = self.resolve_clip_window(video_path, start_sec, end_sec=end_sec)
        clip_end = clip_start + clip_duration
        self.cleanup_previous_preview()

        from src.media.export_clip import ensure_seekable_preview_proxy

        playback_path = ensure_seekable_preview_proxy(video_path)
        self.current_preview_context = {
            "video_path": video_path,
            "playback_path": playback_path,
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
        # Keep main preview on the search-page surface (floating dialog uses another MediaPlayer).
        try:
            vlc_player.set_host_widget(self.parent_window.video_widget, force=True)
        except Exception as exc:
            logger.debug("Assert main preview host skipped: %s", exc)
        if vlc_player.play(playback_path, clip_start, stop_sec=clip_end):
            return True

        # Team play_url: never ffmpeg-remux remote HTTP on the UI thread (can hang / crash).
        if is_http_media_url(video_path):
            return False

        from src.media.export_clip import build_preview_cache_path, create_preview_clip

        cache_path = build_preview_cache_path(video_path, clip_start)
        result = create_preview_clip(playback_path, clip_start, cache_path, duration_sec=clip_duration)
        if result.returncode == 0:
            self.current_preview_path = cache_path
            media_player.setSource(QUrl.fromLocalFile(cache_path))
            media_player.play()
            return True

        if os.path.exists(cache_path):
            os.remove(cache_path)
        return False

    def start_warmup(self):
        """Warm libvlc on the UI thread (libvlc is not thread-safe for Instance create)."""
        if self._warmup_started:
            return
        self._warmup_started = True
        QTimer.singleShot(0, self._run_main_thread_warmup)

    def _run_main_thread_warmup(self):
        try:
            warmup_vlc_runtime()
        except Exception as exc:
            logger.warning("Preview warmup failed: %s", exc)

    def ensure_vlc_instance(self):
        """Shared libvlc Instance for main + floating preview MediaPlayers."""
        if self._vlc_instance is None:
            self._vlc_instance = create_vlc_preview_instance()
        return self._vlc_instance

    def _ensure_vlc_player(self):
        if self.vlc_player is None:
            instance = self.ensure_vlc_instance()
            if instance is not None:
                self.vlc_player = VlcPreviewPlayer(
                    self.parent_window.video_widget,
                    shared_instance=instance,
                )
            else:
                self.vlc_player = VlcPreviewPlayer(self.parent_window.video_widget)
        return self.vlc_player

    def suspend_for_dialog(self, *, skip_telemetry: bool = True):
        """Pause inline preview without libvlc stop()/set_media(None).

        Opening the large-preview dialog used to call ``stop_preview()`` on every
        click; repeated ``stop()`` on the UI thread freezes the app on Windows.
        Keep ``current_preview_context`` so 放大预览 can reopen the same clip.
        """
        if skip_telemetry:
            try:
                from src.services.search_telemetry import cancel_playback_session

                cancel_playback_session()
            except Exception as exc:
                logger.debug("Playback telemetry cancel skipped: %s", exc)
        else:
            self._record_playback_telemetry(source="inline")
        if self.vlc_player is not None:
            self.vlc_player.suspend()
        try:
            self.parent_window.media_player.pause()
        except Exception as exc:
            logger.debug("QMediaPlayer pause for dialog skipped: %s", exc)

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
            # End the clip session so Play cannot resume after 清空.
            self.vlc_player.clear_session()
        try:
            self.parent_window.media_player.pause()
        except Exception as exc:
            logger.debug("QMediaPlayer pause on stop_preview skipped: %s", exc)
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
        from src.media.export_clip import export_original_clip, resolve_export_clip_window

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
        from src.media.export_clip import resolve_export_clip_window, start_export_original_clip_process

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
        if self.vlc_player is not None:
            self.vlc_player.shutdown(fast=True)
            self.vlc_player = None
        if self._vlc_instance is not None:
            try:
                self._vlc_instance.release()
            except Exception as exc:
                logger.debug("Release shared VLC instance skipped: %s", exc)
            self._vlc_instance = None
        self.parent_window.media_player.stop()
        self.parent_window.media_player.setSource(QUrl())
        self.cleanup_previous_preview()
        self.current_preview_context = None
