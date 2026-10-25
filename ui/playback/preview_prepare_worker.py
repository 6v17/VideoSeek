"""Background prepare for preview: seekable remux and clip encode off the UI thread."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QThread, Signal


class PreviewPrepareWorker(QThread):
    """Run ffmpeg preview prep without blocking the Qt main thread.

    Modes:
    - ``proxy``: ``ensure_seekable_preview_proxy`` only
    - ``clip``: ``create_preview_clip`` for the VLC-failure fallback
    """

    finished_prepare = Signal(object)

    def __init__(
        self,
        *,
        mode: str,
        video_path: str,
        clip_start: float | None = None,
        clip_duration: float | None = None,
        cache_path: str | None = None,
        playback_path: str | None = None,
    ):
        super().__init__()
        self.mode = mode
        self.video_path = video_path
        self.clip_start = clip_start
        self.clip_duration = clip_duration
        self.cache_path = cache_path
        self.playback_path = playback_path
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            if self._cancel_requested:
                self.finished_prepare.emit({"cancelled": True, "mode": self.mode})
                return
            if self.mode == "proxy":
                from src.media.export_clip import ensure_seekable_preview_proxy

                playback_path = ensure_seekable_preview_proxy(self.video_path)
                if self._cancel_requested:
                    self.finished_prepare.emit({"cancelled": True, "mode": self.mode})
                    return
                self.finished_prepare.emit(
                    {
                        "cancelled": False,
                        "mode": "proxy",
                        "playback_path": playback_path,
                    }
                )
                return

            if self.mode == "clip":
                from src.media.export_clip import create_preview_clip

                input_path = self.playback_path or self.video_path
                result = create_preview_clip(
                    input_path,
                    self.clip_start,
                    self.cache_path,
                    duration_sec=self.clip_duration,
                )
                if self._cancel_requested:
                    self.finished_prepare.emit({"cancelled": True, "mode": self.mode})
                    return
                self.finished_prepare.emit(
                    {
                        "cancelled": False,
                        "mode": "clip",
                        "cache_path": self.cache_path,
                        "result": result,
                    }
                )
                return

            self.finished_prepare.emit(
                {
                    "cancelled": False,
                    "mode": self.mode,
                    "error": ValueError(f"unknown prepare mode: {self.mode}"),
                }
            )
        except Exception as exc:
            self.finished_prepare.emit(
                {
                    "cancelled": False,
                    "mode": self.mode,
                    "error": exc,
                }
            )
