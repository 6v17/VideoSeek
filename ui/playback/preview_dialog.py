import os
import time
from types import SimpleNamespace

from PySide6.QtCore import QThread, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.app.logging_utils import get_logger
from ui.playback.expanded_preview_chrome import ExpandedPreviewChrome
from ui.playback.vlc_player import VlcPreviewPlayer

logger = get_logger("preview_dialog")


class _OutlinedCaptionLabel(QLabel):
    """Yellow caption with a black outline so it stays readable on any theme."""

    _FILL = QColor("#FFE566")
    _STROKE = QColor("#000000")
    _STROKE_RADIUS = 2

    def paintEvent(self, event):  # noqa: N802
        from PySide6.QtWidgets import QStyle, QStyleOption

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, option, painter, self)

        text = self.text()
        if not text:
            painter.end()
            return

        flags = int(self.alignment()) | int(Qt.TextFlag.TextWordWrap)
        rect = self.contentsRect()
        radius = self._STROKE_RADIUS
        painter.setPen(QPen(self._STROKE))
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0:
                    continue
                painter.drawText(rect.adjusted(dx, dy, dx, dy), flags, text)
        painter.setPen(QPen(self._FILL))
        painter.drawText(rect, flags, text)
        painter.end()


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
        self._follow_embed(rebind=True)

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self._follow_embed(rebind=False)

    def _follow_embed(self, *, rebind: bool) -> None:
        window = self.window()
        schedule = getattr(window, "_schedule_preview_video_frame", None)
        if callable(schedule):
            schedule()
        if not rebind:
            return
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
            from src.app.logging_utils import note_swallowed
            note_swallowed(exc, 'ui/playback/preview_dialog.py:119')
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


def _chrome_field(name, default):
    """Read/write a transport field on the embedded chrome once it exists."""
    stash = f"_stash_{name}"

    def getter(self):
        chrome = getattr(self, "chrome", None)
        if chrome is not None:
            return getattr(chrome, name)
        return getattr(self, stash, default)

    def setter(self, value):
        chrome = getattr(self, "chrome", None)
        if chrome is not None:
            setattr(chrome, name, value)
            return
        setattr(self, stash, value)

    return property(getter, setter)


class PreviewDialog(QDialog):
    export_requested = Signal(str, float, float, str, str)
    export_status_changed = Signal(str, str)
    add_to_shot_list_requested = Signal(str, float, float, str)
    # Emitted when the user dismisses the floating preview (close hides; event is ignored).
    dismissed = Signal()

    _known_total_ms = _chrome_field("_known_total_ms", 0)
    _pending_ui_seek_ms = _chrome_field("_pending_ui_seek_ms", None)
    _slider_dragging = _chrome_field("_slider_dragging", False)
    segment_start_sec = _chrome_field("segment_start_sec", None)
    segment_end_sec = _chrome_field("segment_end_sec", None)
    _segment_line_override = _chrome_field("_segment_line_override", None)

    @property
    def update_timer(self):
        return self.chrome.update_timer

    @property
    def _frame_export_thread(self):
        return self.chrome._frame_export_thread

    @_frame_export_thread.setter
    def _frame_export_thread(self, value):
        self.chrome._frame_export_thread = value

    def __init__(
        self,
        parent,
        video_path,
        start_sec,
        end_sec,
        texts,
        suggested_sec=None,
        *,
        caption_text=None,
        shared_player=None,
        shared_instance=None,
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
        self._caption_text = ""
        self._play_token = 0
        self._duration_cache = {}
        self._window_geometry_before_fullscreen = None
        # Prefer shared_instance + dedicated MediaPlayer (no HWND thrash with main preview).
        # shared_player is legacy: one player hop between hosts (kept for compat).
        self._shared_instance = shared_instance
        self._shared_player = shared_player
        self._owns_player = shared_player is None
        self._on_release_shared_player = on_release_shared_player

        self.setObjectName("PreviewDialog")
        self.setWindowTitle(self.texts.get("preview_dialog_title", "Large Preview"))
        self.resize(1000, 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 6)
        layout.setSpacing(6)

        self.video_host = _PreviewVideoHost()
        self.video_host.setMinimumHeight(480)
        layout.addWidget(self.video_host, 1)

        self.caption_label = _OutlinedCaptionLabel("")
        self.caption_label.setObjectName("PreviewCaption")
        self.caption_label.setWordWrap(True)
        self.caption_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.caption_label.setVisible(False)
        layout.addWidget(self.caption_label)

        self.detail_label = QLabel("")
        self.detail_label.setObjectName("Hint")
        self.detail_label.setWordWrap(True)
        self.detail_label.setVisible(False)
        layout.addWidget(self.detail_label)

        self.chrome = ExpandedPreviewChrome(self)
        self.chrome.apply_texts(self.texts or {})
        self.chrome.collapse_button.hide()
        self.chrome.export_requested.connect(self.export_requested)
        self.chrome.export_status_changed.connect(self.export_status_changed)
        self.chrome.add_to_shot_list_requested.connect(self.add_to_shot_list_requested)
        self.chrome.maximize_button.clicked.disconnect(self.chrome._toggle_maximize)
        self.chrome.maximize_button.clicked.connect(self._toggle_fullscreen)
        self.chrome.show_chrome()
        self.chrome.setMinimumHeight(max(72, self.chrome.sizeHint().height()))
        layout.addWidget(self.chrome)

        self.play_button = self.chrome.play_button
        self.fullscreen_button = self.chrome.maximize_button
        self.slider = self.chrome.slider
        self.set_start_button = self.chrome.set_start_button
        self.set_end_button = self.chrome.set_end_button
        self.clear_segment_button = self.chrome.clear_segment_button
        self.export_button = self.chrome.export_button
        self.frame_export_button = self.chrome.frame_export_button
        self.add_to_shot_list_button = self.chrome.add_to_shot_list_button
        self.time_label = self.chrome.time_label
        self.segment_queue_hint = self.chrome.segment_queue_hint
        self.label_segment_start = self.chrome.label_segment_start
        self.label_segment_end = self.chrome.label_segment_end

        self.player = self._shared_player
        if self.player is not None and hasattr(self.video_host, "set_player"):
            self.video_host.set_player(self.player)
        if self.player is not None:
            self.chrome.bind_player(self.player)

        self.load_preview(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
            caption_text=caption_text,
        )

    def apply_texts(self, texts):
        """Refresh the shared transport when the app language changes."""
        self.texts = texts or {}
        self.setWindowTitle(self.texts.get("preview_dialog_title", "Large Preview"))
        self.chrome.apply_texts(self.texts)
        self._sync_add_to_shot_list_button()

    def reject(self) -> None:  # noqa: N802 — Qt API
        """Embedded preview uses Esc to return to the result list, not to hide the player in place."""
        leave = getattr(self, "_on_embedded_escape", None)
        if callable(leave):
            leave()
            return
        super().reject()

    def closeEvent(self, event):
        # Always hide immediately so the user is never trapped behind a busy/frozen dialog.
        if self._close_requested:
            self.hide()
            event.ignore()
            self.dismissed.emit()
            return
        self._begin_close()
        self.hide()
        self._finalize_close()
        event.ignore()
        self.dismissed.emit()

    def is_export_running(self):
        return False

    def load_preview(self, video_path, start_sec, end_sec, suggested_sec=None, *, caption_text=None):
        self._closing = False
        self._close_requested = False
        self._close_after_export = False
        self._pending_close = False
        self._extend_close_guard(0.35)
        self._playback_ready = False
        self._detail_error = None
        self._detail_notice = None
        self._segment_line_override = None
        self._set_caption_text(caption_text)
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
            self._exit_fullscreen()
        self.chrome.set_maximized_state(False)
        self.video_path = str(video_path)
        self.chrome.video_path = self.video_path
        self.start_sec = float(start_sec)
        self.end_sec = float(end_sec)
        self.suggested_sec = float(suggested_sec if suggested_sec is not None else start_sec)
        self.chrome.start_sec = self.start_sec
        self.chrome.end_sec = self.end_sec
        self.chrome.suggested_sec = self.suggested_sec
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
        self.frame_export_button.setEnabled(bool(self.video_path))
        self._sync_add_to_shot_list_button()
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
        self._cancel_prepare_worker()
        self.update_timer.stop()
        self.play_button.setEnabled(False)
        self.slider.setEnabled(False)
        self.set_start_button.setEnabled(False)
        self.set_end_button.setEnabled(False)
        self.clear_segment_button.setEnabled(False)
        self.fullscreen_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self.frame_export_button.setEnabled(False)
        self._sync_add_to_shot_list_button(enabled=False)

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
        self.chrome.set_maximized_state(False)
        self._detail_notice = None
        self.hide()
        if self.player is not None:
            self.player.suspend()
        self._release_shared_player_host()

    def _ensure_player(self):
        if self._shared_player is not None:
            self.player = self._shared_player
            if getattr(self.player, "host_widget", None) is not self.video_host:
                if hasattr(self.player, "set_host_widget"):
                    self.player.set_host_widget(self.video_host, force=True)
                elif hasattr(self.video_host, "set_player"):
                    self.video_host.set_player(self.player)
        elif self.player is None:
            if self._shared_instance is not None:
                self.player = VlcPreviewPlayer(
                    self.video_host,
                    shared_instance=self._shared_instance,
                )
            else:
                self.player = VlcPreviewPlayer(self.video_host)
            if hasattr(self.video_host, "set_player"):
                self.video_host.set_player(self.player)
        elif getattr(self.player, "host_widget", None) is not self.video_host:
            if hasattr(self.player, "set_host_widget"):
                self.player.set_host_widget(self.video_host, force=True)
        if self.player is not None:
            self.chrome.bind_player(self.player)
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

    def _start_playback_if(self, token):
        if token != self._play_token or self._closing or self._close_requested:
            return
        self._start_playback()

    def _start_playback(self):
        if self._closing or self._close_requested:
            return
        self.update_timer.stop()
        player = self._ensure_player()
        from src.media.export_clip import get_seekable_preview_proxy_if_ready

        ready_path = get_seekable_preview_proxy_if_ready(self.video_path)
        if ready_path is None:
            self._start_proxy_prepare(player)
            return
        self._finish_playback_with_path(player, ready_path)

    def _finish_playback_with_path(self, player, playback_path):
        if self._closing or self._close_requested:
            return
        if not player.play(playback_path, self.start_sec, stop_sec=self.end_sec):
            self._detail_error = self.texts.get("preview_failed", "Preview failed")
            self._apply_detail_label()
            self.play_button.setEnabled(False)
            self.slider.setEnabled(False)
            self.set_start_button.setEnabled(False)
            self.set_end_button.setEnabled(False)
            self.clear_segment_button.setEnabled(False)
            self.export_button.setEnabled(False)
            self.frame_export_button.setEnabled(False)
            self._sync_add_to_shot_list_button(enabled=False)
            return

        self._playback_ready = True
        self._detail_error = None
        self.update_timer.start()
        self._update_segment_ui()
        self._sync_ui()

    def _start_proxy_prepare(self, player):
        from ui.playback.preview_prepare_worker import PreviewPrepareWorker

        self._cancel_prepare_worker()
        token = self._prepare_token + 1
        self._prepare_token = token
        worker = PreviewPrepareWorker(mode="proxy", video_path=self.video_path)
        self._prepare_worker = worker
        worker.finished_prepare.connect(
            lambda result, t=token, p=player: self._on_proxy_prepared(t, p, result)
        )
        worker.start()

    def _on_proxy_prepared(self, token, player, result):
        if token != self._prepare_token or self._closing or self._close_requested:
            return
        self._prepare_worker = None
        if not isinstance(result, dict) or result.get("cancelled") or result.get("error"):
            self._detail_error = self.texts.get("preview_failed", "Preview failed")
            self._apply_detail_label()
            return
        playback_path = result.get("playback_path") or self.video_path
        self._finish_playback_with_path(player, playback_path)

    def _cancel_prepare_worker(self):
        self._prepare_token += 1
        worker = self._prepare_worker
        self._prepare_worker = None
        if worker is None:
            return
        try:
            worker.cancel()
        except Exception as exc:
            logger.debug("Preview dialog prepare cancel skipped: %s", exc)
        try:
            worker.finished_prepare.disconnect()
        except Exception:
            pass
        if worker.isRunning():
            worker.wait(100)
        try:
            worker.deleteLater()
        except Exception as exc:
            logger.debug("Preview dialog prepare worker deleteLater failed: %s", exc)

    def _on_slider_released(self):
        if self._closing:
            return
        self.chrome._on_slider_released()
        self._extend_close_guard(1.0)

    def _sync_ui(self):
        if self._closing:
            return
        self.chrome._sync_ui()

    def _update_segment_ui(self):
        self.chrome._update_segment_ui()

    def _normalized_segment(self):
        return self.chrome._normalized_segment()

    def current_segment_range(self):
        """Public: marked export/review segment, or None."""
        return self.chrome._normalized_segment()

    def _current_time_seconds(self):
        return self.chrome._current_time_seconds()

    def _capture_window_geometry(self):
        if self.isFullScreen():
            return
        geo = self.geometry()
        if geo.isValid() and not geo.isEmpty():
            self._window_geometry_before_fullscreen = geo

    def _apply_restored_geometry(self, geo):
        if self._closing or geo is None:
            return
        if self.isFullScreen():
            self.showNormal()
        self.setGeometry(geo)

    def _exit_fullscreen(self):
        """Leave fullscreen and put the window back to the size it had before."""
        geo = self._window_geometry_before_fullscreen
        self.showNormal()
        if geo is None:
            self._schedule_rebind()
            return
        self.setGeometry(geo)
        QTimer.singleShot(0, lambda g=geo: self._apply_restored_geometry(g))
        self._schedule_rebind()

    def _toggle_fullscreen(self):
        if self._closing:
            return
        if self.isFullScreen():
            self._exit_fullscreen()
            self.chrome.set_maximized_state(False)
            return
        self._capture_window_geometry()
        self.showFullScreen()
        self.chrome.set_maximized_state(True)
        self._schedule_rebind()

    def _set_caption_text(self, caption_text=None):
        text = str(caption_text or "").strip()
        self._caption_text = text
        self.caption_label.setText(text)
        self.caption_label.setVisible(bool(text))

    def _apply_detail_label(self):
        if self._detail_notice:
            self.detail_label.setText(self._detail_notice)
            self.detail_label.setVisible(True)
            return
        if self._detail_error:
            self.detail_label.setText(self._detail_error)
            self.detail_label.setVisible(True)
            return
        self.detail_label.clear()
        self.detail_label.setVisible(False)

    def _handle_export_finished(self, result, save_path):
        state, status_text = self._resolve_export_status(result, save_path)
        if not self._closing:
            self._segment_line_override = status_text
            self.chrome._refresh_segment_queue_hint()
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
        self._sync_add_to_shot_list_button(enabled=(not busy) and bool(self.video_path) and not self._closing)

    def _sync_add_to_shot_list_button(self, *, enabled: bool | None = None) -> None:
        button = getattr(self, "add_to_shot_list_button", None)
        if button is None:
            return
        button.setText(
            self.texts.get(
                "preview_dialog_add_to_shot_list",
                self.texts.get("shot_list_add", "加入素材篮"),
            )
        )
        button.setToolTip(self.texts.get("shot_list_add_tip", ""))
        if enabled is None:
            enabled = bool(self.video_path) and not self._closing
        button.setEnabled(bool(enabled))
