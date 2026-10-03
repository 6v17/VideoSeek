"""Save-dialog + background thread for exporting the current preview frame."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog

from src.app.path_display import video_display_name
from src.services.clip_export_service import export_save_dialog_start, remember_export_path


class FrameExportThread(QThread):
    succeeded = Signal(str)
    failed = Signal()

    def __init__(
        self,
        video_path: str,
        time_sec: float,
        output_path: str,
        parent=None,
        snapshot_path: str = "",
    ):
        super().__init__(parent)
        self._video_path = video_path
        self._time_sec = float(time_sec)
        self._output_path = output_path
        self._snapshot_path = str(snapshot_path or "").strip()

    def run(self) -> None:
        try:
            from src.media.export_frame import publish_still, save_video_frame, wait_for_written_file

            if self._snapshot_path and wait_for_written_file(self._snapshot_path):
                publish_still(self._snapshot_path, self._output_path)
            else:
                self._discard_snapshot()
                save_video_frame(self._video_path, self._time_sec, self._output_path)
        except Exception:
            self._discard_snapshot()
            self.failed.emit()
            return
        self.succeeded.emit(self._output_path)

    def _discard_snapshot(self) -> None:
        path = self._snapshot_path
        if not path or os.path.normcase(path) == os.path.normcase(self._output_path):
            return
        try:
            os.remove(path)
        except OSError:
            pass


def begin_displayed_frame_capture(player, output_path: str) -> str:
    """Ask VLC for the on-screen picture. Empty string means the caller should use ffmpeg."""
    capture = getattr(type(player), "capture_displayed_frame", None) if player is not None else None
    if not callable(capture):
        return ""
    ext = os.path.splitext(str(output_path or ""))[1].lower()
    if ext == ".png":
        snapshot_path = output_path
    else:
        folder = os.path.dirname(os.path.abspath(output_path)) or "."
        snapshot_path = os.path.join(folder, f".vsframe-{os.getpid()}-{time.time_ns()}.png")
    try:
        if not player.capture_displayed_frame(snapshot_path):
            return ""
    except Exception:
        return ""
    return snapshot_path


def prompt_frame_save_path(parent, *, video_path: str, time_sec: float, texts: dict) -> str:
    """Ask where to save the still. Empty string means the user cancelled."""
    base = os.path.splitext(video_display_name(video_path))[0] or "frame"
    suggested = f"{base}_{int(max(0.0, float(time_sec))):06d}.png"
    texts = texts or {}
    save_path, _selected = QFileDialog.getSaveFileName(
        parent,
        texts.get("preview_frame_export_title", "存帧"),
        export_save_dialog_start(suggested),
        texts.get("preview_frame_export_filter", "PNG (*.png);;JPG (*.jpg *.jpeg)"),
    )
    save_path = str(save_path or "").strip()
    if not save_path:
        return ""
    ext = os.path.splitext(save_path)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg"}:
        save_path = save_path + ".png"
    remember_export_path(save_path)
    return save_path
