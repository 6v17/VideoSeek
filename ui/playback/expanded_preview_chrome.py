"""Transport / segment chrome for in-place expanded preview (single shared VLC player)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.app.logging_utils import get_logger
from src.utils import format_timecode_seconds

logger = get_logger("expanded_preview_chrome")


class ExpandedPreviewChrome(QWidget):
    """Controls for the main-window preview when enlarged. Does not own a VLC player."""

    export_requested = Signal(str, float, float, str, str)
    export_status_changed = Signal(str, str)
    collapse_requested = Signal()
    maximize_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.texts = {}
        self.player = None
        self.video_path = ""
        self.start_sec = 0.0
        self.end_sec = 0.0
        self.suggested_sec = 0.0
        self._slider_dragging = False
        self._pending_ui_seek_ms = None
        self._known_total_ms = 0
        self._duration_cache = {}
        self._playback_ready = False
        self._segment_line_override = None
        self.segment_start_sec = None
        self.segment_end_sec = None
        self._maximized = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        root.setSpacing(4)

        transport = QHBoxLayout()
        transport.setSpacing(6)
        self.play_button = QPushButton()
        self.maximize_button = QPushButton()
        self.maximize_button.setObjectName("NeutralToolButton")
        self.collapse_button = QPushButton()
        self.collapse_button.setObjectName("GhostButton")

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
        transport.addWidget(self.maximize_button, 0)
        transport.addWidget(self.collapse_button, 0)
        transport.addStretch(1)
        transport.addWidget(segment_fields, 0, Qt.AlignVCenter)
        transport.addStretch(1)
        transport.addWidget(self.time_label, 0)
        root.addLayout(transport)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.slider)

        segment_row = QHBoxLayout()
        segment_row.setSpacing(6)
        self.set_start_button = QPushButton()
        self.set_end_button = QPushButton()
        self.clear_segment_button = QPushButton()
        self.clear_segment_button.setObjectName("GhostButton")
        self.export_button = QPushButton()
        self.export_button.setObjectName("PrimaryButton")
        self.export_button.setEnabled(False)
        segment_row.addWidget(self.set_start_button)
        segment_row.addWidget(self.set_end_button)
        segment_row.addStretch(1)
        segment_row.addWidget(self.clear_segment_button)
        segment_row.addWidget(self.export_button)
        root.addLayout(segment_row)

        self.update_timer = QTimer(self)
        self.update_timer.setInterval(120)
        self.update_timer.timeout.connect(self._sync_ui)

        self.play_button.clicked.connect(self._toggle_play)
        self.maximize_button.clicked.connect(self._toggle_maximize)
        self.collapse_button.clicked.connect(self.collapse_requested.emit)
        self.set_start_button.clicked.connect(self._mark_start)
        self.set_end_button.clicked.connect(self._mark_end)
        self.clear_segment_button.clicked.connect(self._clear_segment)
        self.export_button.clicked.connect(self._export_segment)
        self.slider.sliderPressed.connect(self._on_slider_pressed)
        self.slider.sliderReleased.connect(self._on_slider_released)

        self.setVisible(False)

    def apply_texts(self, texts: dict):
        self.texts = texts or {}
        self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))
        self.maximize_button.setText(
            self.texts.get("preview_dialog_exit_fullscreen", "Exit Fullscreen")
            if self._maximized
            else self.texts.get("preview_dialog_fullscreen", "Fullscreen")
        )
        self.collapse_button.setText(self.texts.get("preview_collapse", "收起预览"))
        self.set_start_button.setText(self.texts.get("preview_dialog_set_start", "Set Start"))
        self.set_end_button.setText(self.texts.get("preview_dialog_set_end", "Set End"))
        self.clear_segment_button.setText(self.texts.get("preview_dialog_clear_segment", "Clear Segment"))
        self.export_button.setText(self.texts.get("preview_dialog_export", "Export Segment"))

    def bind_player(self, player):
        self.player = player

    def attach_clip(self, video_path, start_sec, end_sec, suggested_sec=None, *, restart=False):
        """Bind chrome to the current clip. Does not create a player or call play()."""
        self.video_path = str(video_path)
        self.start_sec = float(start_sec)
        self.end_sec = float(end_sec)
        self.suggested_sec = float(suggested_sec if suggested_sec is not None else start_sec)
        self._known_total_ms = int(self._duration_cache.get(self.video_path, 0) or 0)
        self._pending_ui_seek_ms = None
        self._slider_dragging = False
        self.segment_start_sec = None
        self.segment_end_sec = None
        self._segment_line_override = None
        self._playback_ready = self.player is not None and self.player.is_available()
        self.slider.setValue(0)
        self.play_button.setEnabled(True)
        self.slider.setEnabled(True)
        self.set_start_button.setEnabled(True)
        self.set_end_button.setEnabled(True)
        self.clear_segment_button.setEnabled(True)
        self.maximize_button.setEnabled(True)
        self._update_segment_ui()
        if self._playback_ready:
            self.update_timer.start()
            self._sync_ui()
        else:
            self.update_timer.stop()
        _ = restart  # play is owned by PreviewController

    def show_chrome(self):
        self.setVisible(True)
        if self._playback_ready:
            self.update_timer.start()
            self._sync_ui()

    def hide_chrome(self):
        self.update_timer.stop()
        self.setVisible(False)
        if self._maximized:
            self._maximized = False
            self.maximize_toggled.emit(False)
            self.maximize_button.setText(self.texts.get("preview_dialog_fullscreen", "Fullscreen"))

    def set_maximized_state(self, maximized: bool):
        self._maximized = bool(maximized)
        self.maximize_button.setText(
            self.texts.get("preview_dialog_exit_fullscreen", "Exit Fullscreen")
            if self._maximized
            else self.texts.get("preview_dialog_fullscreen", "Fullscreen")
        )

    def _toggle_maximize(self):
        self._maximized = not self._maximized
        self.set_maximized_state(self._maximized)
        self.maximize_toggled.emit(self._maximized)

    def _toggle_play(self):
        player = self.player
        if player is None or not player.is_available():
            return
        if player.is_playing():
            player.pause()
            self.play_button.setText(self.texts.get("preview_dialog_play", "Play"))
            return
        if player.has_locked_window():
            self._unlock_full_playback()
        if player.resume():
            self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))

    def _unlock_full_playback(self):
        try:
            from src.services.search_telemetry import mark_playback_user_adjusted

            mark_playback_user_adjusted()
        except Exception as exc:
            logger.debug("Expanded preview user-adjust telemetry skipped: %s", exc)
        player = self.player
        if player is None:
            return
        player.unlock_full_playback()
        player.resume()
        self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))

    def _on_slider_pressed(self):
        self._slider_dragging = True
        player = self.player
        if player is not None and player.has_locked_window():
            player.unlock_full_playback()

    def _on_slider_released(self):
        try:
            from src.services.search_telemetry import mark_playback_user_adjusted

            mark_playback_user_adjusted()
        except Exception as exc:
            logger.debug("Expanded preview slider telemetry skipped: %s", exc)
        player = self.player
        if player is None:
            self._slider_dragging = False
            return
        length = self._effective_total_ms(player)
        if length > 0:
            new_time = int((self.slider.value() / 1000.0) * length)
            self._pending_ui_seek_ms = new_time
            player.set_time(new_time, unlock=True)
            player.resume()
            self.play_button.setText(self.texts.get("preview_dialog_pause", "Pause"))
        self._slider_dragging = False

    def _sync_ui(self):
        player = self.player
        if player is None or not player.is_available():
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

    def reset(self):
        """Clear chrome after stop/clear — keep widget layout, drop active clip UI."""
        self.update_timer.stop()
        self.player = None
        self.video_path = ""
        self.start_sec = 0.0
        self.end_sec = 0.0
        self.suggested_sec = 0.0
        self._playback_ready = False
        self._segment_line_override = None
        self.segment_start_sec = None
        self.segment_end_sec = None
        self._pending_ui_seek_ms = None
        self._slider_dragging = False
        self._known_total_ms = 0
        self.slider.setValue(0)
        self.time_label.setText("00:00 / 00:00")
        self.play_button.setText(self.texts.get("preview_dialog_play", "Play"))
        self.play_button.setEnabled(False)
        self.slider.setEnabled(False)
        self.set_start_button.setEnabled(False)
        self.set_end_button.setEnabled(False)
        self.clear_segment_button.setEnabled(False)
        self.maximize_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self._refresh_segment_bounds_labels()
        self._refresh_segment_queue_hint()

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
        self._segment_line_override = None
        t = self._current_time_seconds()
        if self.segment_end_sec is not None and t > float(self.segment_end_sec):
            self.segment_end_sec = None
        self.segment_start_sec = t
        self._update_segment_ui()

    def _mark_end(self):
        self._segment_line_override = None
        t = self._current_time_seconds()
        if self.segment_start_sec is not None and t < float(self.segment_start_sec):
            self.segment_start_sec = None
        self.segment_end_sec = t
        self._update_segment_ui()

    def _clear_segment(self):
        self._segment_line_override = None
        self.segment_start_sec = None
        self.segment_end_sec = None
        self._update_segment_ui()

    def _export_segment(self):
        segment = self._normalized_segment()
        if segment is None:
            return
        start_sec, end_sec = segment
        segment_duration = max(0.1, float(end_sec) - float(start_sec))
        encode_mode = None
        parent = self.window()
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

        queued_text = self.texts.get("preview_dialog_export_queued", "Export added to queue.")
        self._segment_line_override = queued_text
        self._refresh_segment_queue_hint()
        self.export_status_changed.emit("queued", queued_text)
        self.export_requested.emit(self.video_path, start_sec, end_sec, save_path, encode_mode)

    def _update_segment_ui(self):
        if self.segment_start_sec is not None and self.segment_end_sec is not None:
            if float(self.segment_end_sec) < float(self.segment_start_sec):
                self.segment_start_sec, self.segment_end_sec = self.segment_end_sec, self.segment_start_sec
        segment = self._normalized_segment()
        self.export_button.setEnabled(segment is not None)
        self._refresh_segment_bounds_labels()
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


def _format_segment_display_sec(value):
    if value is None:
        return "—"
    return format_timecode_seconds(value)


def _format_ms(ms):
    total_seconds = max(0, int(ms / 1000))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"
