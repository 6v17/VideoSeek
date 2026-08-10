import os
import time
from types import SimpleNamespace

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.app.logging_utils import get_logger
from src.utils import format_timecode_seconds
from ui.playback.vlc_player import VlcPreviewPlayer

logger = get_logger("preview_dialog")


class _PreviewVideoHost(QWidget):
    """Native embed host that rebinds VLC after resize / fullscreen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None
        self.setObjectName("VideoContainer")
        self.setAttribute(Qt.WA_NativeWindow, True)
        dont_native_ancestors = getattr(Qt.WidgetAttribute, "WA_DontCreateNativeAncestors", None)
        if dont_native_ancestors is not None:
            self.setAttribute(dont_native_ancestors, True)

    def set_player(self, player):
        self._player = player

    def resizeEvent(self, event):
        super().resizeEvent(event)
        player = self._player
        if player is not None and getattr(player, "is_available", lambda: False)():
            QTimer.singleShot(0, player.rebind_output_window)


class ExportCancelledError(Exception):
    pass


class ExportClipWorker(QThread):
    finished_export = Signal(object, str)

    def __init__(self, preview_controller, video_path, start_sec, end_sec, save_path, encode_mode=None):
        super().__init__()
        self.preview_controller = preview_controller
        self.video_path = video_path
        self.start_sec = float(start_sec)
        self.end_sec = float(end_sec)
        self.save_path = save_path
        self.encode_mode = encode_mode
        self._process = None
        self._cancel_requested = False

    def run(self):
        try:
            self._process = self.preview_controller.start_export_process(
                self.video_path,
                self.start_sec,
                self.save_path,
                end_sec=self.end_sec,
                encode_mode=self.encode_mode,
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
        except Exception as exc:
            logger.debug("Export process terminate failed, trying kill: %s", exc)
            try:
                process.kill()
            except Exception as kill_exc:
                logger.debug("Export process kill failed: %s", kill_exc)

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
    export_requested = Signal(str, float, float, str, str)
    export_status_changed = Signal(str, str)

    def __init__(
        self,
        parent,
        video_path,
        start_sec,
        end_sec,
        texts,
        suggested_sec=None,
        *,
        shared_player=None,
        on_release_shared_player=None,
    ):
        super().__init__(parent)
        self.texts = texts
        self.video_path = ""
        self.start_sec = 0.0
        self.end_sec = 0.0
        self.suggested_sec = 0.0
        self._slider_dragging = False
        self._closing = False
        self._close_requested = False
        self._close_after_export = False
        self._pending_close = False
        self._min_close_at = 0.0
        self._pending_ui_seek_ms = None
        self.segment_start_sec = None
        self.segment_end_sec = None
        self._known_total_ms = 0
        self.export_worker = None
        self._playback_ready = False
        self._detail_error = None
        self._detail_notice = None
        self._segment_line_override = None
        self._play_token = 0
        self._duration_cache = {}
        self._shared_player = shared_player
        self._owns_player = shared_player is None
        self._on_release_shared_player = on_release_shared_player

        self.setWindowTitle(self.texts.get("preview_dialog_title", "Large Preview"))
        self.resize(1000, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        self.video_host = _PreviewVideoHost()
        self.video_host.setMinimumHeight(480)
        layout.addWidget(self.video_host, 1)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("Hint")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.detail_label)

        transport = QHBoxLayout()
        transport.setSpacing(8)
        self.play_button = QPushButton(self.texts.get("preview_dialog_pause", "Pause"))
        self.fullscreen_button = QPushButton(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
        self.fullscreen_button.setObjectName("NeutralToolButton")
        segment_fields = QWidget()
        segment_fields.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        seg_outer = QVBoxLayout(segment_fields)
        seg_outer.setContentsMargins(0, 0, 0, 0)
        seg_outer.setSpacing(3)
        self.segment_queue_hint = QLabel("")
        self.segment_queue_hint.setObjectName("PreviewSegmentQueueHint")
        self.segment_queue_hint.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        self.segment_queue_hint.setWordWrap(False)
        self.segment_queue_hint.setVisible(False)
        self.segment_queue_hint.setMaximumWidth(280)
        seg_layout = QHBoxLayout()
        seg_layout.setContentsMargins(0, 0, 0, 0)
        seg_layout.setSpacing(6)
        dash = QLabel("—")
        dash.setObjectName("Hint")
        self.label_segment_start = QLabel("—")
        self.label_segment_start.setObjectName("DialogMetaLabel")
        self.label_segment_start.setAlignment(Qt.AlignCenter)
        self.label_segment_start.setMinimumWidth(92)
        self.label_segment_end = QLabel("—")
        self.label_segment_end.setObjectName("DialogMetaLabel")
        self.label_segment_end.setAlignment(Qt.AlignCenter)
        self.label_segment_end.setMinimumWidth(92)
        seg_layout.addWidget(self.label_segment_start)
        seg_layout.addWidget(dash, 0, Qt.AlignVCenter)
        seg_layout.addWidget(self.label_segment_end)
        seg_outer.addWidget(self.segment_queue_hint)
        seg_outer.addLayout(seg_layout)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setObjectName("PreviewTimeLabel")
        self.time_label.setAlignment(Qt.AlignCenter)
        transport.addWidget(self.play_button, 0)
        transport.addWidget(self.fullscreen_button, 0)
        transport.addStretch(1)
        transport.addWidget(segment_fields, 0, Qt.AlignVCenter)
        transport.addStretch(1)
        transport.addWidget(self.time_label, 0)
        layout.addLayout(transport)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.slider)

        segment_row = QHBoxLayout()
        segment_row.setSpacing(8)
        self.set_start_button = QPushButton(self.texts.get("preview_dialog_set_start", "Set Start"))
        self.set_end_button = QPushButton(self.texts.get("preview_dialog_set_end", "Set End"))
        self.clear_segment_button = QPushButton(self.texts.get("preview_dialog_clear_segment", "Clear Segment"))
        self.clear_segment_button.setObjectName("GhostButton")
        self.export_button = QPushButton(self.texts.get("preview_dialog_export", "Export Segment"))
        self.export_button.setObjectName("PrimaryButton")
        self.export_button.setEnabled(False)
        segment_row.addWidget(self.set_start_button)
        segment_row.addWidget(self.set_end_button)
        segment_row.addStretch(1)
        segment_row.addWidget(self.clear_segment_button)
        segment_row.addWidget(self.export_button)
        layout.addLayout(segment_row)

        self.player = self._shared_player
        if self.player is not None and hasattr(self.video_host, "set_player"):
            self.video_host.set_player(self.player)
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

        self.load_preview(video_path, start_sec, end_sec, suggested_sec=suggested_sec)

    def closeEvent(self, event):
        # Always hide immediately so the user is never trapped behind a busy/frozen dialog.
        if self._close_requested:
            self.hide()
            event.ignore()
            return
        self._begin_close()
        self.hide()
        self._finalize_close()
        event.ignore()

    def is_export_running(self):
        return False

    def load_preview(self, video_path, start_sec, end_sec, suggested_sec=None):
        self._closing = False
        self._close_requested = False
        self._close_after_export = False
        self._pending_close = False
        self._extend_close_guard(0.35)
        self._playback_ready = False
        self._detail_error = None
        self._detail_notice = None
        self._segment_line_override = None
        self.update_timer.stop()
        self._play_token += 1
        play_token = self._play_token
        # Soft reload: reuse the same player. Full dispose/recreate calls libvlc stop/release
        # on the UI thread and can freeze the whole app ("Python 未响应").
        player = self._ensure_player()
        if not player.is_available() and self._owns_player:
            # Only owned players may be torn down/recreated; shared app player must stay.
            self._dispose_player(fast=True)
            player = self._ensure_player()
        # Pause immediately so stacked enlarge clicks don't pile up play() calls.
        if player is not None and player.is_available():
            player.suspend()
        if self.isFullScreen():
            self.showNormal()
            self._schedule_rebind()
        self.fullscreen_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
        self.video_path = str(video_path)
        self.start_sec = float(start_sec)
        self.end_sec = float(end_sec)
        self.suggested_sec = float(suggested_sec if suggested_sec is not None else start_sec)
        # Avoid ffprobe/OpenCV on the UI thread (can block for seconds → "Python 未响应").
        self._known_total_ms = int(self._duration_cache.get(self.video_path, 0) or 0)
        self._pending_ui_seek_ms = None
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
        try:
            from src.services.search_telemetry import begin_playback_session

            begin_playback_session(
                video_path=self.video_path,
                suggested_sec=self.suggested_sec,
                playback_start_sec=float(self.start_sec),
            )
        except Exception as exc:
            logger.debug("Preview dialog playback telemetry start skipped: %s", exc)
        # Defer libvlc play() so the dialog can show/hide without freezing.
        QTimer.singleShot(50, lambda token=play_token: self._start_playback_if(token))

    def shutdown_player(self, fast=False):
        self._begin_close()
        self._close_after_export = False
        self._dispose_player(fast=fast)

    def dismiss_for_page_switch(self):
        """Fully stop playback and hide when leaving search while this dialog is open."""
        if self.export_worker is not None and self.export_worker.isRunning():
            return
        if not self.isVisible():
            return
        self._begin_close()
        self._finalize_close()

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
        self._play_token += 1  # cancel any deferred play()
        self.update_timer.stop()
        self.play_button.setEnabled(False)
        self.slider.setEnabled(False)
        self.set_start_button.setEnabled(False)
        self.set_end_button.setEnabled(False)
        self.clear_segment_button.setEnabled(False)
        self.fullscreen_button.setEnabled(False)
        self.export_button.setEnabled(False)

    def _finalize_close(self):
        self._pending_close = False
        if self.export_worker is None or not self.export_worker.isRunning():
            self._close_after_export = False
        try:
            from src.services.search_telemetry import finish_playback_session

            finish_playback_session(actual_sec=self._current_time_seconds(), source="dialog")
        except Exception as exc:
            logger.debug("Preview dialog playback telemetry finish skipped: %s", exc)
        # Hide first; keep the embedded player alive (pause+mute only).
        # Disposing/detaching hwnd here is what triggers the second-open D3D popup.
        if self.isFullScreen():
            self.showNormal()
        self.fullscreen_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
        self._detail_notice = None
        self.hide()
        if self.player is not None:
            self.player.suspend()
        self._release_shared_player_host()

    def _ensure_player(self):
        if self._shared_player is not None:
            self.player = self._shared_player
            if hasattr(self.player, "set_host_widget"):
                self.player.set_host_widget(self.video_host)
            elif hasattr(self.video_host, "set_player"):
                self.video_host.set_player(self.player)
            return self.player
        if self.player is None:
            self.player = VlcPreviewPlayer(self.video_host)
            if hasattr(self.video_host, "set_player"):
                self.video_host.set_player(self.player)
        return self.player

    def _release_shared_player_host(self) -> None:
        if self._owns_player or self._shared_player is None:
            return
        if callable(self._on_release_shared_player):
            try:
                self._on_release_shared_player(self._shared_player)
            except Exception as exc:
                logger.debug("Release shared preview player host skipped: %s", exc)

    def _dispose_player(self, fast=False):
        if self.player is None:
            return
        if not self._owns_player:
            # Shared app player: never shutdown/release here.
            self.player.suspend()
            self._release_shared_player_host()
            return
        # shutdown() already stops/releases; do not call stop() first (double hang risk).
        self.player.shutdown(fast=fast)
        self.player = None
        if hasattr(self.video_host, "set_player"):
            self.video_host.set_player(None)

    def _schedule_rebind(self):
        player = self.player
        if player is None or not player.is_available():
            return
        QTimer.singleShot(0, player.rebind_output_window)
        QTimer.singleShot(50, player.rebind_output_window)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            self._toggle_play()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_playback_if(self, token):
        if token != self._play_token or self._closing or self._close_requested:
            return
        self._start_playback()

    def _start_playback(self):
        if self._closing or self._close_requested:
            return
        self.update_timer.stop()
        player = self._ensure_player()
        if not player.play(self.video_path, self.start_sec, stop_sec=self.end_sec):
            self._detail_error = self.texts.get("preview_failed", "Preview failed")
            self._apply_detail_label()
            self.play_button.setEnabled(False)
            self.slider.setEnabled(False)
            self.set_start_button.setEnabled(False)
            self.set_end_button.setEnabled(False)
            self.clear_segment_button.setEnabled(False)
            self.export_button.setEnabled(False)
            return

        self._playback_ready = True
        self._detail_error = None
        self.update_timer.start()
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
        try:
            from src.services.search_telemetry import mark_playback_user_adjusted

            mark_playback_user_adjusted()
        except Exception as exc:
            logger.debug("Preview dialog playback user-adjust telemetry skipped: %s", exc)
        player = self._ensure_player()
        player.unlock_full_playback()
        self._apply_detail_label()
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
            self._apply_detail_label()

    def _on_slider_released(self):
        if self._closing:
            return
        try:
            from src.services.search_telemetry import mark_playback_user_adjusted

            mark_playback_user_adjusted()
        except Exception as exc:
            logger.debug("Preview dialog slider telemetry skipped: %s", exc)
        player = self._ensure_player()
        length = self._effective_total_ms(player)
        if length > 0:
            new_time = int((self.slider.value() / 1000.0) * length)
            self._pending_ui_seek_ms = new_time
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
        total_ms = self._effective_total_ms(player)
        current_ms = self._resolve_display_time_ms(current_ms)

        if not self._slider_dragging and total_ms > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int((current_ms / total_ms) * 1000))
            self.slider.blockSignals(False)

        self.time_label.setText(f"{_format_ms(current_ms)} / {_format_ms(total_ms)}")
        if player.is_playing():
            self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))
        else:
            self.play_button.setText(self.texts.get("preview_dialog_play", "Play"))

    def _effective_total_ms(self, player):
        total_ms = max(0, player.get_length())
        if total_ms > 0:
            self._known_total_ms = total_ms
            if self.video_path:
                self._duration_cache[self.video_path] = total_ms
            return total_ms
        return self._known_total_ms

    def _resolve_display_time_ms(self, current_ms):
        pending_seek_ms = self._pending_ui_seek_ms
        if pending_seek_ms is None:
            return current_ms
        if abs(current_ms - pending_seek_ms) <= 800 or current_ms > pending_seek_ms:
            self._pending_ui_seek_ms = None
            return current_ms
        if current_ms <= 250 and pending_seek_ms > 250:
            return pending_seek_ms
        return current_ms

    def _toggle_fullscreen(self):
        if self._closing:
            return
        if self.isFullScreen():
            self.showNormal()
            self.fullscreen_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))
            self._schedule_rebind()
            return
        self.showFullScreen()
        self.fullscreen_button.setText(self.texts.get("preview_dialog_exit_fullscreen", "Exit Fullscreen"))
        self._schedule_rebind()

    def _lock_status_line(self):
        if not self._playback_ready or self._closing:
            return ""
        player = self.player
        if player is None:
            return ""
        if player.has_locked_window():
            return self.texts.get(
                "preview_dialog_locked",
                "Matched segment preview is locked and will pause automatically at the end point.",
            )
        return self.texts.get(
            "preview_dialog_unlocked",
            "Full video unlocked. You can scrub and continue playback freely.",
        )

    def _apply_detail_label(self):
        if self._detail_notice:
            self.detail_label.setText(self._detail_notice)
            self.detail_label.setVisible(True)
            return
        if self._detail_error:
            self.detail_label.setText(self._detail_error)
            self.detail_label.setVisible(True)
            return
        lock = self._lock_status_line()
        self.detail_label.setText(lock)
        self.detail_label.setVisible(bool(lock))

    def _refresh_segment_queue_hint(self):
        text = (self._segment_line_override or "").strip()
        if not text:
            self.segment_queue_hint.clear()
            self.segment_queue_hint.setToolTip("")
            self.segment_queue_hint.setVisible(False)
            return
        hint = self.segment_queue_hint
        max_w = hint.maximumWidth()
        fm = QFontMetrics(hint.font())
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, max_w)
        hint.setText(elided)
        hint.setToolTip(text if elided != text else "")
        hint.setVisible(True)

    def _refresh_segment_bounds_labels(self):
        self.label_segment_start.setText(_format_segment_display_sec(self.segment_start_sec))
        self.label_segment_end.setText(_format_segment_display_sec(self.segment_end_sec))

    def _mark_start(self):
        if self._closing:
            return
        self._segment_line_override = None
        t = self._current_time_seconds()
        if self.segment_end_sec is not None and t > float(self.segment_end_sec):
            self.segment_end_sec = None
        self.segment_start_sec = t
        self._update_segment_ui()

    def _mark_end(self):
        if self._closing:
            return
        self._segment_line_override = None
        t = self._current_time_seconds()
        if self.segment_start_sec is not None and t < float(self.segment_start_sec):
            self.segment_start_sec = None
        self.segment_end_sec = t
        self._update_segment_ui()

    def _clear_segment(self):
        if self._closing:
            return
        self._segment_line_override = None
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
        segment_duration = max(0.1, float(end_sec) - float(start_sec))
        encode_mode = None
        parent = self.parent()
        if parent is not None and hasattr(parent, "_prompt_export_encode_mode"):
            encode_mode = parent._prompt_export_encode_mode(segment_duration_sec=segment_duration)
        else:
            from ui.dialogs.export_clip_mode_dialog import prompt_export_encode_mode

            encode_mode = prompt_export_encode_mode(
                self.texts,
                parent=self,
                segment_duration_sec=segment_duration,
            )
        if encode_mode is None:
            return
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
        self._segment_line_override = queued_text
        self._refresh_segment_queue_hint()
        self._apply_detail_label()
        self.export_status_changed.emit("queued", queued_text)
        self.export_requested.emit(
            self.video_path,
            start_sec,
            end_sec,
            save_path,
            encode_mode,
        )
        self._set_export_busy(False)

    def _update_segment_ui(self):
        if self.segment_start_sec is not None and self.segment_end_sec is not None:
            if float(self.segment_end_sec) < float(self.segment_start_sec):
                self.segment_start_sec, self.segment_end_sec = self.segment_end_sec, self.segment_start_sec
        segment = self._normalized_segment()
        self.export_button.setEnabled(segment is not None)
        self.export_button.setToolTip("")
        self._refresh_segment_bounds_labels()
        self._apply_detail_label()
        self._refresh_segment_queue_hint()

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
            self._segment_line_override = status_text
            self._refresh_segment_queue_hint()
            self._apply_detail_label()
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
        except Exception as exc:
            logger.debug("Preview dialog export worker deleteLater failed: %s", exc)

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


def _format_segment_display_sec(value):
    if value is None:
        return "—"
    return format_timecode_seconds(value)


def _format_ms(ms):
    total_seconds = max(0, int(ms / 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"
