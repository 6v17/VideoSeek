import os
import time
from types import SimpleNamespace

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from ui.vlc_player import VlcPreviewPlayer


class ExportCancelledError(Exception):
    pass


class ExportClipWorker(QThread):
    finished_export = Signal(object, str)

    def __init__(self, preview_controller, video_path, start_sec, end_sec, save_path):
        super().__init__()
        self.preview_controller = preview_controller
        self.video_path = video_path
        self.start_sec = float(start_sec)
        self.end_sec = float(end_sec)
        self.save_path = save_path
        self._process = None
        self._cancel_requested = False

    def run(self):
        try:
            self._process = self.preview_controller.start_export_process(
                self.video_path,
                self.start_sec,
                self.save_path,
                end_sec=self.end_sec,
            )
            stdout, stderr = self._process.communicate()
        except Exception as exc:
            self._process = None
            self.finished_export.emit(exc, self.save_path)
            return
        process = self._process
        self._process = None
        if self._cancel_requested:
            self._remove_partial_output()
            self.finished_export.emit(ExportCancelledError(), self.save_path)
            return
        result = SimpleNamespace(
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        self.finished_export.emit(result, self.save_path)

    def cancel(self):
        self._cancel_requested = True
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _remove_partial_output(self):
        if not self.save_path:
            return
        if not os.path.exists(self.save_path):
            return
        try:
            os.remove(self.save_path)
        except OSError:
            pass


class PreviewDialog(QDialog):
    export_requested = Signal(str, float, float, str)
    export_status_changed = Signal(str, str)

    def __init__(self, parent, video_path, start_sec, end_sec, texts):
        super().__init__(parent)
        self.texts = texts
        self.video_path = ""
        self.start_sec = 0.0
        self.end_sec = 0.0
        self._slider_dragging = False
        self._closing = False
        self._close_requested = False
        self._close_after_export = False
        self._pending_close = False
        self._min_close_at = 0.0
        self.segment_start_sec = None
        self.segment_end_sec = None
        self.export_worker = None

        self.setWindowTitle(self.texts.get("preview_dialog_title", "Large Preview"))
        self.resize(1200, 760)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.video_host = QWidget()
        self.video_host.setMinimumHeight(620)
        self.video_host.setStyleSheet("background-color: black;")
        layout.addWidget(self.video_host, 1)

        info_row = QHBoxLayout()
        self.status_label = QLabel("")
        info_row.addWidget(self.status_label, 1)
        self.time_label = QLabel("00:00 / 00:00")
        info_row.addWidget(self.time_label)
        layout.addLayout(info_row)

        self.segment_label = QLabel(self.texts.get("preview_dialog_segment_empty", "No segment selected"))
        layout.addWidget(self.segment_label)

        control_row = QHBoxLayout()
        control_row.setSpacing(10)
        self.play_button = QPushButton(self.texts.get("preview_dialog_pause", "Pause"))
        self.fullscreen_button = QPushButton(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        control_row.addWidget(self.play_button)
        control_row.addWidget(self.fullscreen_button)
        control_row.addWidget(self.slider, 1)
        layout.addLayout(control_row)

        segment_row = QHBoxLayout()
        segment_row.setSpacing(10)
        self.set_start_button = QPushButton(self.texts.get("preview_dialog_set_start", "Set Start"))
        self.set_end_button = QPushButton(self.texts.get("preview_dialog_set_end", "Set End"))
        self.clear_segment_button = QPushButton(self.texts.get("preview_dialog_clear_segment", "Clear Segment"))
        self.export_button = QPushButton(self.texts.get("preview_dialog_export", "Export Segment"))
        self.export_button.setEnabled(False)
        segment_row.addWidget(self.set_start_button)
        segment_row.addWidget(self.set_end_button)
        segment_row.addWidget(self.clear_segment_button)
        segment_row.addWidget(self.export_button)
        layout.addLayout(segment_row)

        self.player = None
        self.update_timer = QTimer(self)
        self.update_timer.setInterval(120)
        self.update_timer.timeout.connect(self._sync_ui)

        self.play_button.clicked.connect(self._toggle_play)
        self.fullscreen_button.clicked.connect(self._toggle_fullscreen)
        self.set_start_button.clicked.connect(self._mark_start)
        self.set_end_button.clicked.connect(self._mark_end)
        self.clear_segment_button.clicked.connect(self._clear_segment)
        self.export_button.clicked.connect(self._export_segment)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)

        self.load_preview(video_path, start_sec, end_sec)

    def closeEvent(self, event):
        if self._close_requested:
            event.ignore()
            return
        self._begin_close()
        now = time.monotonic()
        if now < self._min_close_at:
            self._pending_close = True
            self.status_label.setText(
                self.texts.get("preview_dialog_busy", "Preview is still switching. Try again in a moment.")
            )
            QTimer.singleShot(max(1, int((self._min_close_at - now) * 1000)), self._complete_deferred_close)
            event.ignore()
            return
        self._finalize_close()
        event.ignore()

    def is_export_running(self):
        return False

    def load_preview(self, video_path, start_sec, end_sec):
        self._closing = False
        self._close_requested = False
        self._close_after_export = False
        self._pending_close = False
        self._extend_close_guard(1.0)
        self.update_timer.stop()
        self._ensure_player()
        self.player.stop()
        if self.isFullScreen():
            self.showNormal()
        self.fullscreen_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
        self.video_path = str(video_path)
        self.start_sec = float(start_sec)
        self.end_sec = float(end_sec)
        self._slider_dragging = False
        self.segment_start_sec = None
        self.segment_end_sec = None
        self.slider.setValue(0)
        self.play_button.setEnabled(True)
        self.slider.setEnabled(True)
        self.set_start_button.setEnabled(True)
        self.set_end_button.setEnabled(True)
        self.clear_segment_button.setEnabled(True)
        self.fullscreen_button.setEnabled(True)
        self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))
        self._update_segment_ui()
        self._start_playback()

    def shutdown_player(self, fast=False):
        self._begin_close()
        self._close_after_export = False
        self._dispose_player(fast=fast)

    def cancel_export_and_wait(self, timeout_ms=3000):
        return True

    def _complete_deferred_close(self):
        if not self._pending_close or self.export_worker is not None and self.export_worker.isRunning():
            return
        if time.monotonic() < self._min_close_at:
            QTimer.singleShot(max(1, int((self._min_close_at - time.monotonic()) * 1000)), self._complete_deferred_close)
            return
        self._finalize_close()

    def _extend_close_guard(self, seconds):
        self._min_close_at = max(self._min_close_at, time.monotonic() + float(seconds))

    def _begin_close(self):
        self._closing = True
        self._close_requested = True
        self.update_timer.stop()
        self.play_button.setEnabled(False)
        self.slider.setEnabled(False)
        self.set_start_button.setEnabled(False)
        self.set_end_button.setEnabled(False)
        self.clear_segment_button.setEnabled(False)
        self.fullscreen_button.setEnabled(False)

    def _finalize_close(self):
        self._pending_close = False
        if self.export_worker is None or not self.export_worker.isRunning():
            self._close_after_export = False
        self._dispose_player()
        if self.isFullScreen():
            self.showNormal()
        self.fullscreen_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
        self.hide()

    def _ensure_player(self):
        if self.player is None:
            self.player = VlcPreviewPlayer(self.video_host)
        return self.player

    def _dispose_player(self, fast=False):
        if self.player is None:
            return
        try:
            self.player.stop()
        finally:
            self.player.shutdown(fast=fast)
            self.player = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_playback(self):
        self.update_timer.stop()
        player = self._ensure_player()
        if not player.play(self.video_path, self.start_sec, stop_sec=self.end_sec):
            self.status_label.setText(self.texts.get("preview_failed", "Preview failed"))
            self.play_button.setEnabled(False)
            self.slider.setEnabled(False)
            self.set_start_button.setEnabled(False)
            self.set_end_button.setEnabled(False)
            self.clear_segment_button.setEnabled(False)
            self.export_button.setEnabled(False)
            return

        self.update_timer.start()
        self._update_status_label()
        self._update_segment_ui()
        self._sync_ui()

    def _toggle_play(self):
        if self._closing:
            return
        player = self._ensure_player()
        if player.is_playing():
            player.pause()
            self.play_button.setText(self.texts.get("preview_dialog_play", "Play"))
            return

        if player.has_locked_window():
            self._unlock_full_playback()
        if player.resume():
            self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))

    def _unlock_full_playback(self):
        if self._closing:
            return
        player = self._ensure_player()
        player.unlock_full_playback()
        self._update_status_label()
        player.resume()
        self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))

    def _on_slider_pressed(self):
        if self._closing:
            return
        self._slider_dragging = True
        self._extend_close_guard(0.8)
        player = self._ensure_player()
        if player.has_locked_window():
            player.unlock_full_playback()
            self._update_status_label()

    def _on_slider_released(self):
        if self._closing:
            return
        player = self._ensure_player()
        length = player.get_length()
        if length > 0:
            new_time = int((self.slider.value() / 1000.0) * length)
            player.set_time(new_time, unlock=True)
            self._extend_close_guard(1.0)
            player.resume()
            self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))
        self._slider_dragging = False

    def _sync_ui(self):
        if self._closing:
            return
        player = self.player
        if player is None:
            return
        current_ms = max(0, player.get_time())
        total_ms = max(0, player.get_length())

        if not self._slider_dragging and total_ms > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int((current_ms / total_ms) * 1000))
            self.slider.blockSignals(False)

        self.time_label.setText(f"{_format_ms(current_ms)} / {_format_ms(total_ms)}")
        if player.is_playing():
            self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))
        else:
            self.play_button.setText(self.texts.get("preview_dialog_play", "Play"))

    def _toggle_fullscreen(self):
        if self._closing:
            return
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
            return
        self.showFullScreen()
        self.fullscreen_button.setText(self.texts.get("preview_dialog_exit_fullscreen", "Exit Fullscreen"))

    def _update_status_label(self):
        if self._closing:
            return
        player = self.player
        if player is not None and player.has_locked_window():
            self.status_label.setText(
                self.texts.get(
                    "preview_dialog_locked",
                    "Matched segment preview is locked and will pause automatically at the end point.",
                )
            )
            return
        self.status_label.setText(
            self.texts.get(
                "preview_dialog_unlocked",
                "Full video unlocked. You can scrub and continue playback freely.",
            )
        )

    def _mark_start(self):
        if self._closing:
            return
        self.segment_start_sec = self._current_time_seconds()
        self._update_segment_ui()

    def _mark_end(self):
        if self._closing:
            return
        self.segment_end_sec = self._current_time_seconds()
        if self.segment_start_sec is not None and self.segment_end_sec is not None:
            if self.segment_end_sec < self.segment_start_sec:
                self.segment_start_sec, self.segment_end_sec = self.segment_end_sec, self.segment_start_sec
        self._update_segment_ui()

    def _clear_segment(self):
        if self._closing:
            return
        self.segment_start_sec = None
        self.segment_end_sec = None
        self._update_segment_ui()

    def _export_segment(self):
        if self._closing:
            return
        segment = self._normalized_segment()
        if segment is None:
            return

        start_sec, end_sec = segment
        base_name = os.path.splitext(os.path.basename(self.video_path))[0]
        suggested_name = f"{base_name}_segment_{int(start_sec):06d}.mp4"
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("export_clip_title", "Export Preview Clip"),
            suggested_name,
            self.texts.get("export_clip_filter", "Video Files (*.mp4 *.mkv *.mov)"),
        )
        if not save_path:
            return

        self._set_export_busy(True)
        queued_text = self.texts.get(
            "preview_dialog_export_queued",
            "Export added to queue.",
        )
        self.segment_label.setText(queued_text)
        self.export_status_changed.emit("queued", queued_text)
        self.export_requested.emit(
            self.video_path,
            start_sec,
            end_sec,
            save_path,
        )
        self._set_export_busy(False)

    def _update_segment_ui(self):
        segment = self._normalized_segment()
        if self.segment_start_sec is None and self.segment_end_sec is None:
            self.segment_label.setText(self.texts.get("preview_dialog_segment_empty", "No segment selected"))
            self.export_button.setEnabled(False)
            return

        if self.segment_start_sec is not None and self.segment_end_sec is None:
            self.segment_label.setText(
                self.texts.get("preview_dialog_segment_start_only", "Start: {start}").format(
                    start=_format_seconds(self.segment_start_sec)
                )
            )
            self.export_button.setEnabled(False)
            return

        if segment is None:
            self.segment_label.setText(self.texts.get("preview_dialog_segment_empty", "No segment selected"))
            self.export_button.setEnabled(False)
            return

        start_sec, end_sec = segment
        duration = end_sec - start_sec
        self.segment_label.setText(
            self.texts.get("preview_dialog_segment_range", "Segment: {start} -> {end} ({duration})").format(
                start=_format_seconds(start_sec),
                end=_format_seconds(end_sec),
                duration=_format_seconds(duration),
            )
        )
        self.export_button.setEnabled(duration > 0.1)

    def _normalized_segment(self):
        if self.segment_start_sec is None or self.segment_end_sec is None:
            return None
        start_sec = float(self.segment_start_sec)
        end_sec = float(self.segment_end_sec)
        if end_sec < start_sec:
            start_sec, end_sec = end_sec, start_sec
        if end_sec - start_sec <= 0.1:
            return None
        return start_sec, end_sec

    def _current_time_seconds(self):
        player = self.player
        if player is None:
            return 0.0
        return max(0.0, player.get_time() / 1000.0)

    def _handle_export_finished(self, result, save_path):
        state, status_text = self._resolve_export_status(result, save_path)
        if not self._closing:
            self.segment_label.setText(status_text)
        self.export_status_changed.emit(state, status_text)

    def _handle_export_thread_finished(self):
        closing_after_export = self._close_after_export
        if not self._closing:
            self._set_export_busy(False)
        self._clear_export_worker()
        if closing_after_export:
            self._finalize_close()

    def _clear_export_worker(self):
        worker = self.export_worker
        self.export_worker = None
        if worker is None:
            return
        try:
            worker.deleteLater()
        except Exception:
            pass

    def _resolve_export_status(self, result, save_path):
        if isinstance(result, ExportCancelledError):
            return "cancelled", self.texts.get("preview_dialog_export_cancelled", "Export cancelled.")
        if isinstance(result, Exception):
            return "failed", self.texts.get("export_clip_failed", "Failed to export clip.")
        if getattr(result, "returncode", 1) != 0:
            return "failed", self.texts.get("export_clip_failed", "Failed to export clip.")
        return "succeeded", self.texts.get("export_clip_success", "Clip exported: {path}").format(path=save_path)

    def _set_export_busy(self, busy):
        self.export_button.setEnabled(False if busy else self._normalized_segment() is not None)
        self.set_start_button.setEnabled(not busy)
        self.set_end_button.setEnabled(not busy)
        self.clear_segment_button.setEnabled(not busy)
        self.play_button.setEnabled(not busy)
        self.fullscreen_button.setEnabled(not busy)
        self.slider.setEnabled(not busy)


def _format_ms(ms):
    total_seconds = max(0, int(ms / 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


def _format_seconds(value):
    return f"{float(value):.1f}s"
