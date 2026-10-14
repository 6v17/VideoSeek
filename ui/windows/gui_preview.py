"""Preview panel, export queue, and in-panel preview chrome — extracted from MainWindow."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.app.logging_utils import get_logger
from src.app.path_display import video_display_name
from src.domain.search_hit import coerce_search_hit
from src.utils import format_timecode_range, format_timecode_seconds, open_folder_in_explorer, open_in_explorer
from ui.dialogs.export_clip_mode_dialog import prompt_export_encode_mode
from ui.dialogs import ResourceTableDialog
from ui.playback.preview_dialog import ExportCancelledError, ExportClipWorker, PreviewDialog
from ui.views.table_views import result_mode_label as _result_mode_label
from ui.widgets.styles import repolish_widget

logger = get_logger("gui_preview")

_FLOATING_PREVIEW_SIZE = (1000, 660)
_FLOATING_PREVIEW_MIN = (720, 480)


def floating_preview_top_left(
    dialog_width: int,
    dialog_height: int,
    frame_x: int,
    frame_y: int,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int]:
    """Screen position that centers a floating preview on the main window."""
    x = int(frame_x + max(0, (int(frame_width) - int(dialog_width)) // 2))
    y = int(frame_y + max(0, (int(frame_height) - int(dialog_height)) // 2))
    return x, y


class _NearbyCandidateButton(QPushButton):
    def __init__(self, on_activate):
        super().__init__()
        self._on_activate = on_activate

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and callable(self._on_activate):
            self._on_activate()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _NearbyCandidateTile(QWidget):
    """Same-video candidate. Double-click plays; a single click does not."""

    def __init__(self, on_activate):
        super().__init__()
        self._on_activate = on_activate
        self._hit_path = ""
        self._hit_start = 0.0
        self.setFixedSize(112, 84)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        self.thumb = _NearbyCandidateButton(on_activate)
        self.thumb.setObjectName("SearchPreviewStripThumb")
        self.thumb.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.thumb.setFixedSize(112, 64)
        self.caption = QLabel()
        self.caption.setObjectName("SearchPreviewStripCaption")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        column.addWidget(self.thumb)
        column.addWidget(self.caption)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and callable(self._on_activate):
            self._on_activate()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _SameVideoThumbLoader(QThread):
    """Decode one video's candidate frames with a single open file, in time order."""

    thumb_ready = Signal(int, str, float, object)

    def __init__(self, generation: int, jobs: list):
        super().__init__()
        self.generation = int(generation)
        self.jobs = list(jobs)
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        from src.app.config import load_config
        from src.media.thumbnail import (
            ffmpeg_capture_frame as _ffmpeg_capture_frame,
            is_blank_preview_frame,
            load_cv2 as _cv2,
            nudge_off_blank_frame,
            preview_max_drift_sec,
            read_captured_frame,
        )
        from ui.thumb_cache import get_thumb_cache

        if not self._running:
            return
        config = load_config()
        thumb_width = int(config.get("thumb_width", 130) or 130)
        thumb_height = int(config.get("thumb_height", 75) or 75)
        cache = get_thumb_cache()
        grouped: dict[str, list] = {}
        for path, start, end in self.jobs:
            grouped.setdefault(str(path), []).append((float(start), float(end)))

        cv2 = _cv2()
        for path, spans in grouped.items():
            if not self._running or self.isInterruptionRequested():
                return
            spans.sort(key=lambda item: _thumb_sample_time(item[0], item[1]))
            if str(path).lower().startswith(("http://", "https://")):
                from src.media.thumbnail import get_single_thumbnail

                for start, end in spans:
                    if not self._running or self.isInterruptionRequested():
                        return
                    sample = _thumb_sample_time(start, end)
                    frame = get_single_thumbnail(
                        path,
                        sample,
                        max_drift_sec=preview_max_drift_sec(start, end),
                        segment_start=float(start),
                        segment_end=float(end),
                    )
                    if frame is None:
                        continue
                    image = _scaled_thumb_image(cv2, frame, thumb_width, thumb_height)
                    if image is None:
                        continue
                    cache.put(cache.make_key(path, sample, thumb_width, thumb_height), image)
                    self.thumb_ready.emit(self.generation, path, float(start), image)
                continue
            capture = cv2.VideoCapture(path)
            try:
                opened = capture.isOpened()
                for start, end in spans:
                    if not self._running or self.isInterruptionRequested():
                        return
                    sample = _thumb_sample_time(start, end)
                    frame = None
                    landed = None
                    if opened:
                        frame, landed = read_captured_frame(capture, cv2, sample)
                    drift = preview_max_drift_sec(start, end)
                    # Keep the fast keyframe when it is already near the clip middle.
                    if (
                        frame is not None
                        and drift is not None
                        and landed is not None
                        and abs(float(landed) - sample) > drift
                    ):
                        frame = None
                    elif frame is not None and drift is not None:
                        frame = nudge_off_blank_frame(
                            capture,
                            cv2,
                            frame,
                            sample,
                            start_sec=float(start),
                            end_sec=float(end),
                        )
                    elif frame is not None and drift is None and is_blank_preview_frame(frame):
                        frame = None
                    if frame is None:
                        frame = _ffmpeg_capture_frame(path, sample, timeout_sec=3.0)
                    if frame is None:
                        continue
                    image = _scaled_thumb_image(cv2, frame, thumb_width, thumb_height)
                    if image is None:
                        continue
                    cache.put(cache.make_key(path, sample, thumb_width, thumb_height), image)
                    self.thumb_ready.emit(self.generation, path, float(start), image)
            finally:
                capture.release()


def _thumb_sample_time(start: float, end: float) -> float:
    from src.media.thumbnail import preview_sample_time

    return preview_sample_time(start, end)


def _scaled_thumb_image(cv2, frame, width: int, height: int):
    from PySide6.QtGui import QImage

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame_h, frame_w, _ = rgb.shape
    image = QImage(rgb.data, frame_w, frame_h, frame_w * 3, QImage.Format.Format_RGB888).copy()
    return image.scaled(
        int(width),
        int(height),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.FastTransformation,
    )


class PreviewGuiMixin:
    """Preview playback and clip export tasks; mixed into `MainWindow`."""

    def handle_play(self, path, sec, end_sec=None):
        """Open the on-demand preview. Search results play in the fixed player."""
        start = float(sec or 0.0)
        end = float(end_sec) if end_sec is not None else start

        def set_status(message: str) -> None:
            self.search_page.lbl_status.setText(message)

        if self._search_preview_layer_available():
            self._play_fixed_search_preview(path, start, end, set_status)
            return
        self.open_floating_preview_dialog(
            path,
            start,
            end,
            suggested_sec=start,
            on_status=set_status,
        )

    def _play_fixed_search_preview(self, path, start, end, set_status) -> bool:
        """Play in the side column on the fixed player. The embedded preview stays separate."""
        if getattr(self, "_search_preview_embedded", False):
            self._leave_search_preview_layer()
        self._set_docked_preview_visible(True)
        try:
            played = bool(self.preview_controller.play(path, start, end))
        except Exception as exc:
            logger.exception("Fixed preview failed: %s", exc)
            set_status(self.texts.get("preview_failed", "Preview failed"))
            return False
        if not played:
            set_status(self.texts.get("preview_failed", "Preview failed"))
            return False
        ctx = self.preview_controller.get_current_preview_context() or {}
        self._sync_preview_chrome(
            path,
            float(ctx.get("start_sec", start)),
            float(ctx.get("end_sec", end)),
            float(ctx.get("suggested_sec", start)),
        )
        self._fill_search_preview_detail(path, float(ctx.get("suggested_sec", start)))
        self._reveal_playing_result(path, start)
        return True

    def _reveal_current_playing_result(self) -> None:
        ctx = {}
        controller = getattr(self, "preview_controller", None)
        if controller is not None and hasattr(controller, "get_current_preview_context"):
            ctx = controller.get_current_preview_context() or {}
        path = str(ctx.get("video_path") or "").strip()
        if not path:
            return
        suggested = ctx.get("suggested_sec")
        start = float(suggested if suggested is not None else ctx.get("start_sec") or 0.0)
        self._reveal_playing_result(path, start)

    def _set_docked_preview_visible(self, visible: bool) -> None:
        panel = getattr(getattr(self, "search_page", None), "preview_panel", None)
        if panel is None:
            return
        panel.setVisible(bool(visible))

    def _reveal_playing_result(self, path, start) -> None:
        page = getattr(self, "search_page", None)
        view = getattr(page, "result_view", None)
        if view is None:
            return
        if getattr(view, "view_mode", "") == "grid":
            grid = getattr(view, "grid", None)
            if grid is not None and hasattr(grid, "select_match"):
                grid.select_match(path, start)
            return
        table = getattr(view, "table", None)
        if table is None:
            return
        target = str(path or "").strip().replace("/", "\\").lower()
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if not isinstance(payload, dict):
                continue
            row_path = str(payload.get("video_path") or "").strip().replace("/", "\\").lower()
            if row_path != target:
                continue
            try:
                delta = abs(float(payload.get("start_sec") or 0.0) - float(start or 0.0))
            except (TypeError, ValueError):
                continue
            if delta > 0.5:
                continue
            table.selectRow(row)
            table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
            return

    def _sync_docked_preview_button(self) -> None:
        chrome = getattr(getattr(self, "search_page", None), "expanded_chrome", None)
        panel = getattr(getattr(self, "search_page", None), "preview_panel", None)
        if chrome is None or panel is None or not getattr(panel, "_docked", False):
            return
        if getattr(chrome, "_maximized", False):
            return
        label = self.texts.get("preview_expand", "放大预览")
        chrome.maximize_button.setText(label)
        chrome.maximize_button.setToolTip(label)

    def _open_result_table_preview(self, row: int, _column: int) -> None:
        table = getattr(self, "result_table", None)
        if table is None:
            return
        item = table.item(int(row), 0)
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict):
            return
        path = str(payload.get("video_path") or "").strip()
        if not path:
            return
        self.handle_play(path, payload.get("start_sec"), payload.get("end_sec"))

    def _preview_playback_bounds(self, video_path, start_sec, end_sec) -> tuple[float, float]:
        """Point hits (frame search) play ``preview_seconds`` around the hit.

        A real range, such as a subtitle or chunk, stays that range.
        """
        start = float(start_sec or 0.0)
        end = None if end_sec is None else float(end_sec)
        controller = getattr(self, "preview_controller", None)
        if controller is not None and hasattr(controller, "resolve_clip_window"):
            clip_start, clip_duration = controller.resolve_clip_window(
                video_path, start, end_sec=end
            )
        else:
            from src.app.config import load_config
            from src.media.export_clip import resolve_base_clip_window as _resolve_base_clip_window

            clip_start, clip_duration = _resolve_base_clip_window(
                video_path,
                start,
                end_sec=end,
                config=load_config(),
            )
        clip_end = float(clip_start) + float(clip_duration)
        if clip_end <= clip_start:
            clip_end = clip_start + 0.1
        return float(clip_start), clip_end

    def _search_preview_layer_available(self) -> bool:
        if QApplication.activeModalWidget() is not None:
            return False
        page = getattr(self, "search_page", None)
        if page is None or not hasattr(page, "browse_stack"):
            return False
        if not hasattr(self, "_is_current_page"):
            return False
        return bool(self._is_current_page("search"))

    def _preview_chrome(self):
        """Widget that currently owns the embedded player host and strip."""
        surface = getattr(self, "_preview_surface", None)
        if surface is not None:
            return surface
        return getattr(self, "search_page", None)

    def _enter_search_preview_layer(
        self,
        video_path,
        start_sec,
        end_sec,
        *,
        suggested_sec=None,
        on_status=None,
    ) -> bool:
        if not getattr(self, "_preview_back_wired", False):
            self.search_page.btn_preview_back.clicked.connect(self._leave_search_preview_layer)
            self._preview_back_wired = True
        self._preview_surface = self.search_page
        return self.open_floating_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
            on_status=on_status,
            embedded=True,
        )

    def _enter_understanding_preview_layer(
        self,
        video_path,
        start_sec,
        end_sec,
        *,
        suggested_sec=None,
        on_status=None,
    ) -> bool:
        """Play on the understanding page's own copy of the embedded preview."""
        page = getattr(self, "understanding_page", None)
        layer = getattr(page, "embedded_preview", None) if page is not None else None
        if page is None or layer is None:
            return False
        if not getattr(self, "_understanding_preview_back_wired", False):
            layer.btn_preview_back.clicked.connect(self._leave_understanding_embedded_preview)
            self._understanding_preview_back_wired = True
        page._embedded_preview_dismiss = self._leave_understanding_embedded_preview
        self._preview_surface = layer
        self._preview_return_page = ""
        page.show_embedded_preview()
        scroller = getattr(self, "_understanding_outer_scroll", None)
        scroll = scroller() if callable(scroller) else None
        bar = scroll.verticalScrollBar() if scroll is not None else None
        if bar is not None:
            bar.setValue(0)
        return self.open_floating_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
            on_status=on_status,
            embedded=True,
        )

    def _pause_embedded_preview(self) -> None:
        """Leave the in-page player mounted. Only stop the picture from playing."""
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is None or getattr(dialog, "_closing", False):
            return
        player = getattr(dialog, "player", None)
        if player is None or not hasattr(player, "is_playing"):
            return
        try:
            if player.is_playing():
                player.pause()
                button = getattr(dialog, "play_button", None)
                if button is not None:
                    button.setText(self.texts.get("preview_dialog_play", "Play"))
        except Exception as exc:
            logger.debug("Pause embedded preview on page leave skipped: %s", exc)

    def _restore_embedded_preview_surface(self) -> None:
        """Show the same in-page player again after another page hid its parent."""
        if not getattr(self, "_search_preview_embedded", False):
            return
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is None:
            return
        if getattr(dialog, "_closing", False):
            dialog._closing = False
            dialog._close_requested = False
            for name in (
                "play_button",
                "slider",
                "set_start_button",
                "set_end_button",
                "clear_segment_button",
                "fullscreen_button",
                "export_button",
                "frame_export_button",
            ):
                widget = getattr(dialog, name, None)
                if widget is not None:
                    widget.setEnabled(True)
            if hasattr(dialog, "_sync_add_to_shot_list_button"):
                dialog._sync_add_to_shot_list_button()
            timer = getattr(dialog, "update_timer", None)
            if timer is not None:
                timer.start()
        self._present_embedded_preview(dialog)
        self._rebind_preview_output(dialog)
        player = getattr(dialog, "player", None)
        if player is not None and hasattr(player, "rebind_output_window"):
            QTimer.singleShot(80, player.rebind_output_window)

    def _restore_understanding_preview_surface(self) -> None:
        if not getattr(self, "_understanding_preview_embedded", False):
            return
        page = getattr(self, "understanding_page", None)
        layer = getattr(page, "embedded_preview", None) if page is not None else None
        dialog = getattr(self, "_preview_dialog", None)
        if page is None or layer is None or dialog is None:
            return
        if getattr(dialog, "_closing", False):
            dialog._closing = False
            dialog._close_requested = False
        self._preview_surface = layer
        page.show_embedded_preview()
        self._present_embedded_preview(dialog)
        self._rebind_preview_output(dialog)

    def _detach_understanding_embedded_host(self, dialog) -> None:
        page = getattr(self, "understanding_page", None)
        layer = getattr(page, "embedded_preview", None) if page is not None else None
        layout = getattr(layer, "preview_layer_host_layout", None)
        if layout is not None and dialog is not None and layout.indexOf(dialog) >= 0:
            layout.removeWidget(dialog)
        if page is not None:
            page.hide_embedded_preview()
        self._understanding_preview_embedded = False

    def _leave_understanding_embedded_preview(self) -> None:
        self._understanding_preview_embedded = False
        self._preview_strip_kind = ""
        if getattr(self, "_preview_surface", None) is getattr(
            getattr(self, "understanding_page", None), "embedded_preview", None
        ):
            self._preview_surface = None
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is not None:
            dialog._on_embedded_escape = None
            player = getattr(dialog, "player", None)
            try:
                if player is not None and hasattr(player, "pause"):
                    player.pause()
            except Exception as exc:
                logger.debug("Pause understanding preview skipped: %s", exc)
            dialog.hide()
        page = getattr(self, "understanding_page", None)
        if page is not None:
            page.hide_embedded_preview()
        thread = getattr(self, "_same_video_thumb_thread", None)
        if thread is not None:
            thread.stop()

    def _detach_search_preview_host(self, dialog) -> None:
        page = getattr(self, "search_page", None)
        layout = getattr(page, "preview_layer_host_layout", None)
        if layout is not None and dialog is not None and layout.indexOf(dialog) >= 0:
            layout.removeWidget(dialog)
        if not getattr(self, "_search_preview_embedded", False):
            return
        self._search_preview_embedded = False
        stack = getattr(page, "browse_stack", None)
        if stack is not None:
            stack.setCurrentIndex(0)
        self._set_docked_preview_visible(True)

    def _detach_understanding_preview_host(self, dialog) -> None:
        page = getattr(self, "understanding_page", None)
        layout = getattr(page, "chunk_preview_host_layout", None)
        if layout is not None and dialog is not None and layout.indexOf(dialog) >= 0:
            layout.removeWidget(dialog)
            removed = True
        else:
            removed = False
        wrap = getattr(page, "chunk_preview_wrap", None)
        if wrap is not None and (removed or not wrap.isVisible()):
            wrap.setVisible(False)
        if dialog is not None and getattr(dialog, "_on_embedded_escape", None) is self._leave_understanding_preview:
            dialog._on_embedded_escape = None
        if removed:
            self._understanding_preview_embedded = False

    def _leave_search_preview_layer(self) -> None:
        return_page = str(getattr(self, "_preview_return_page", "") or "")
        self._preview_return_page = ""
        self._preview_strip_kind = ""
        self._search_preview_embedded = False
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is not None:
            dialog._on_embedded_escape = None
        page = getattr(self, "search_page", None)
        stack = getattr(page, "browse_stack", None)
        if stack is not None:
            stack.setCurrentIndex(0)
        self._set_docked_preview_visible(True)
        self._reveal_current_playing_result()
        if dialog is not None:
            player = getattr(dialog, "player", None)
            try:
                if player is not None and hasattr(player, "pause"):
                    player.pause()
            except Exception as exc:
                logger.debug("Pause in-page preview skipped: %s", exc)
            dialog.hide()
        thread = getattr(self, "_same_video_thumb_thread", None)
        if thread is not None:
            thread.stop()
        self._sync_preview_layer_chrome()
        if return_page and return_page != "search" and hasattr(self, "switch_page"):
            self.switch_page(return_page)

    def _sync_preview_layer_chrome(self) -> None:
        page = self._preview_chrome()
        if page is None:
            return
        kind = str(getattr(self, "_preview_strip_kind", "") or "")
        dialogue = kind == "dialogue"
        chunks = kind == "chunks"
        if hasattr(page, "btn_preview_back"):
            if dialogue or chunks:
                page.btn_preview_back.setText(
                    self.texts.get("understanding_preview_back", "Back to understanding")
                )
            else:
                page.btn_preview_back.setText(self.texts.get("search_preview_back", "返回结果"))
        label = getattr(page, "preview_strip_label", None)
        if label is None:
            return
        if dialogue:
            label.setText(self.texts.get("understanding_preview_strip", "本片对白"))
            label.setToolTip(self.texts.get("understanding_preview_strip_tip", "双击播放这一句"))
        elif chunks:
            label.setText(self.texts.get("understanding_chunk_preview_strip", "本片片段"))
            label.setToolTip(self.texts.get("understanding_chunk_preview_strip_tip", "双击播放这一段"))
        else:
            label.setText(self.texts.get("search_preview_strip", "同视频就近候选"))
            label.setToolTip(self.texts.get("search_preview_strip_tip", "双击播放"))

    def _present_embedded_preview(self, dialog) -> None:
        self._detach_understanding_preview_host(dialog)
        surface = self._preview_chrome()
        search = getattr(self, "search_page", None)
        on_understanding = surface is not None and surface is not search
        if on_understanding:
            self._detach_search_preview_host(dialog)
        else:
            self._detach_understanding_embedded_host(dialog)
        if surface is None:
            self._present_floating_preview(dialog)
            return
        host = surface.preview_layer_host
        layout = surface.preview_layer_host_layout
        already = (
            dialog.parentWidget() is host
            and layout.indexOf(dialog) >= 0
            and not dialog.isWindow()
        )
        if not already:
            dialog.hide()
            dialog.setWindowFlags(Qt.WindowType.Widget)
            dialog.setParent(host)
            dialog.setMinimumSize(0, 0)
            dialog.setMaximumSize(16777215, 16777215)
            dialog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
            if hasattr(dialog, "video_host"):
                dialog.video_host.setMinimumHeight(0)
                dialog.video_host.setMaximumHeight(16777215)
                dialog.video_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
            if layout.indexOf(dialog) < 0:
                layout.addWidget(dialog, 1)
            dialog.show()
            self._rebind_preview_output(dialog)
        elif not dialog.isVisible():
            dialog.show()
            self._rebind_preview_output(dialog)
        dialog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        if hasattr(dialog, "video_host"):
            dialog.video_host.setMinimumHeight(0)
            dialog.video_host.setMaximumHeight(16777215)
            dialog.video_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self._set_preview_fullscreen_button(dialog, visible=False)
        if on_understanding:
            dialog._on_embedded_escape = self._leave_understanding_embedded_preview
            self._understanding_preview_embedded = True
            self._search_preview_embedded = False
            page = getattr(self, "understanding_page", None)
            if page is not None:
                page.show_embedded_preview()
            stack = getattr(search, "browse_stack", None)
            if stack is not None:
                stack.setCurrentIndex(0)
        else:
            dialog._on_embedded_escape = self._leave_search_preview_layer
            self._search_preview_embedded = True
            self._understanding_preview_embedded = False
            search.browse_stack.setCurrentWidget(search.preview_layer)
            self._set_docked_preview_visible(False)

    def _present_understanding_preview(self, dialog) -> None:
        page = getattr(self, "understanding_page", None)
        host = getattr(page, "chunk_preview_host", None)
        layout = getattr(page, "chunk_preview_host_layout", None)
        wrap = getattr(page, "chunk_preview_wrap", None)
        if page is None or host is None or layout is None or wrap is None:
            self._present_floating_preview(dialog)
            return
        self._detach_search_preview_host(dialog)
        already = (
            dialog.parentWidget() is host
            and layout.indexOf(dialog) >= 0
            and not dialog.isWindow()
        )
        if not already:
            dialog.hide()
            dialog.setWindowFlags(Qt.WindowType.Widget)
            dialog.setParent(host)
            dialog.setMinimumSize(0, 0)
            dialog.setMaximumHeight(420)
            dialog.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            if hasattr(dialog, "video_host"):
                dialog.video_host.setMinimumHeight(0)
                dialog.video_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            if layout.indexOf(dialog) < 0:
                layout.addWidget(dialog, 1)
            dialog.show()
            self._rebind_preview_output(dialog)
        elif not dialog.isVisible():
            dialog.show()
            self._rebind_preview_output(dialog)
        wrap.setVisible(True)
        self._set_preview_fullscreen_button(dialog, visible=False)
        dialog._on_embedded_escape = self._leave_understanding_preview
        self._understanding_preview_embedded = True
        self._search_preview_embedded = False
        QTimer.singleShot(0, self._reveal_understanding_chunk_preview)

    def _reveal_understanding_chunk_preview(self) -> None:
        page = getattr(self, "understanding_page", None)
        wrap = getattr(page, "chunk_preview_wrap", None)
        if wrap is None or not wrap.isVisible():
            return
        scroll = wrap.parentWidget()
        while scroll is not None and not isinstance(scroll, QScrollArea):
            scroll = scroll.parentWidget()
        if isinstance(scroll, QScrollArea):
            scroll.ensureWidgetVisible(wrap, 0, 24)

    def _leave_understanding_preview(self) -> None:
        self._understanding_preview_embedded = False
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is not None:
            dialog._on_embedded_escape = None
            player = getattr(dialog, "player", None)
            try:
                if player is not None and hasattr(player, "pause"):
                    player.pause()
            except Exception as exc:
                logger.debug("Pause understanding preview skipped: %s", exc)
            dialog.hide()
        page = getattr(self, "understanding_page", None)
        wrap = getattr(page, "chunk_preview_wrap", None)
        if wrap is not None:
            wrap.setVisible(False)

    def _present_floating_preview(self, dialog) -> None:
        self._detach_understanding_preview_host(dialog)
        page = getattr(self, "search_page", None)
        layout = getattr(page, "preview_layer_host_layout", None)
        embedded = layout is not None and layout.indexOf(dialog) >= 0
        if embedded or not dialog.isWindow():
            if embedded:
                layout.removeWidget(dialog)
            dialog.hide()
            dialog.setParent(
                self,
                Qt.WindowType.Dialog
                | Qt.WindowType.WindowTitleHint
                | Qt.WindowType.WindowSystemMenuHint
                | Qt.WindowType.WindowCloseButtonHint
                | Qt.WindowType.WindowMinMaxButtonsHint,
            )
        self._restore_floating_preview_chrome(dialog)
        self._search_preview_embedded = False
        dialog._on_embedded_escape = None
        stack = getattr(page, "browse_stack", None)
        if stack is not None:
            stack.setCurrentIndex(0)
        self._set_docked_preview_visible(True)
        self._set_preview_fullscreen_button(dialog, visible=True)
        self._attach_preview_dialog_host(dialog)
        # setParent/setWindowFlags recreates the native window at (0, 0).
        # Place it after that, and again after show(), or Windows keeps the origin.
        self._center_floating_preview(dialog)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self._center_floating_preview(dialog)
        # First open and the embedded→window switch both need a post-show hwnd.
        # Binding before the window exists leaves a white surface and a top-left popup.
        self._rebind_preview_output(dialog)

    def _restore_floating_preview_chrome(self, dialog) -> None:
        dialog.setMaximumSize(16777215, 16777215)
        dialog.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        dialog.setMinimumSize(*_FLOATING_PREVIEW_MIN)
        if dialog.width() < _FLOATING_PREVIEW_MIN[0] or dialog.height() < _FLOATING_PREVIEW_MIN[1]:
            dialog.resize(*_FLOATING_PREVIEW_SIZE)
        if hasattr(dialog, "video_host"):
            dialog.video_host.setMinimumHeight(480)
            dialog.video_host.setMaximumHeight(16777215)
            dialog.video_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _center_floating_preview(self, dialog) -> None:
        anchor = self.frameGeometry()
        if anchor.width() < 2 or anchor.height() < 2:
            screen = QGuiApplication.primaryScreen()
            anchor = screen.availableGeometry() if screen is not None else None
        if anchor is None or anchor.width() < 2 or anchor.height() < 2:
            return
        x, y = floating_preview_top_left(
            dialog.width(),
            dialog.height(),
            anchor.x(),
            anchor.y(),
            anchor.width(),
            anchor.height(),
        )
        dialog.move(x, y)

    def _rebind_preview_output(self, dialog) -> None:
        player = getattr(dialog, "player", None)
        if player is None or not hasattr(player, "rebind_output_window"):
            return
        QTimer.singleShot(0, player.rebind_output_window)
        QTimer.singleShot(80, player.rebind_output_window)

    def _set_preview_fullscreen_button(self, dialog, *, visible: bool) -> None:
        button = getattr(dialog, "fullscreen_button", None)
        if button is not None:
            button.setVisible(visible)

    def _wire_layered_preview(self, dialog) -> None:
        if getattr(dialog, "_layer_dismiss_wired", False):
            return
        dialog.dismissed.connect(self._on_embedded_preview_dismissed)
        dialog._layer_dismiss_wired = True

    def _on_embedded_preview_dismissed(self) -> None:
        if getattr(self, "_understanding_preview_embedded", False):
            self._leave_understanding_embedded_preview()
            return
        if not getattr(self, "_search_preview_embedded", False):
            return
        self._search_preview_embedded = False
        page = getattr(self, "search_page", None)
        stack = getattr(page, "browse_stack", None)
        if stack is not None:
            stack.setCurrentIndex(0)
        self._set_docked_preview_visible(True)
        self._reveal_current_playing_result()

    def _preview_strip_signature_matches(self, page, signature) -> bool:
        if getattr(page, "_strip_signature", None) != signature:
            return False
        row = getattr(page, "preview_strip_row", None)
        return row is not None and row.count() > 0

    def _focus_preview_strip_selection(self, page, current_path: str, current_start: float) -> bool:
        """Move the highlight. Keep the tiles that are already on the strip."""
        if not self._select_search_preview_strip_hit(current_path, current_start):
            return False
        row = page.preview_strip_row
        for index in range(row.count()):
            item = row.itemAt(index)
            tile = item.widget() if item is not None else None
            thumb = getattr(tile, "thumb", None)
            if thumb is not None and bool(thumb.property("selected")):
                page.preview_strip.ensureWidgetVisible(tile)
                break
        return True

    def _fill_search_preview_context(self, current_path: str, current_start: float) -> None:
        self._fill_search_preview_strip(current_path, current_start)
        if self._preview_chrome() is getattr(self, "search_page", None):
            self._fill_search_preview_detail(current_path, current_start)

    def _fill_dialogue_preview_strip(self, current_path: str, current_start: float) -> None:
        """Same embedded player. The strip lists this video's dialogue lines."""
        page = self._preview_chrome()
        if page is None:
            return
        self._sync_preview_layer_chrome()
        from src.app.config import load_config
        from src.services.understanding_dialogue import list_understanding_dialogue_cues

        video_id = str(getattr(self, "_preview_dialogue_video_id", "") or "")
        cues = (
            list_understanding_dialogue_cues(video_id, video_path=current_path, config=load_config())
            if video_id
            else []
        )
        signature = (
            "dialogue",
            video_id,
            tuple(
                (
                    round(float(cue.get("start") or 0.0), 3),
                    round(float(cue.get("end") or 0.0), 3),
                    str(cue.get("text") or ""),
                )
                for cue in cues
            ),
        )
        if self._preview_strip_signature_matches(page, signature):
            self._focus_preview_strip_selection(page, current_path, current_start)
            return
        row = page.preview_strip_row
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        page.preview_strip_wrap.setVisible(bool(cues))
        path = str(current_path or "")
        nearest = sorted(
            cues,
            key=lambda cue: abs(float(cue.get("start") or 0.0) - float(current_start or 0.0)),
        )
        thumb_starts = {round(float(cue.get("start") or 0.0), 3) for cue in nearest[:36]}
        selected_button = None
        pixmaps = self._page_preview_pixmaps()
        thumb_size = self._candidate_thumb_size()
        missing = []
        for cue in cues:
            start = float(cue.get("start") or 0.0)
            end = float(cue.get("end") or start)
            text = str(cue.get("text") or "").strip()
            pix = self._pixmap_for_hit(pixmaps, path, start)
            if pix is None or pix.isNull():
                pix = self._cached_candidate_thumb(path, start, end, thumb_size)
            if (pix is None or pix.isNull()) and round(start, 3) in thumb_starts:
                missing.append((path, start, end))
                pix = None

            def activate(p=path, s=start, e=end):
                self._switch_search_preview(p, s, e)

            tile = _NearbyCandidateTile(activate)
            tile._hit_path = path
            tile._hit_start = start
            tile.caption.setText(format_timecode_seconds(start))
            tile.thumb.setToolTip(f"{format_timecode_range(start, end)}\n{text}")
            if pix is not None and not pix.isNull():
                tile.thumb.setIcon(QIcon(pix))
                tile.thumb.setIconSize(QSize(108, 60))
            selected = self._same_preview_hit(path, start, current_path, current_start)
            tile.thumb.setProperty("selected", selected)
            repolish_widget(tile.thumb)
            row.addWidget(tile, 0)
            if selected:
                selected_button = tile
        host = page.preview_strip_host
        width = max(host.width(), 8 + len(cues) * 120)
        host.setMinimumWidth(width)
        host.resize(width, 86)
        if selected_button is not None:
            page.preview_strip.ensureWidgetVisible(selected_button)
        page._strip_signature = signature
        self._start_same_video_thumb_loader(missing)

    def _fill_chunk_preview_strip(self, current_path: str, current_start: float) -> None:
        """Same embedded player. The strip lists this video's understanding chunks."""
        page = self._preview_chrome()
        if page is None:
            return
        self._sync_preview_layer_chrome()
        chunks = list(getattr(self, "_understanding_index_chunks", []) or [])
        payloads = dict(getattr(self, "_understanding_chunk_payloads", {}) or {})
        signature = (
            "chunks",
            self._norm_media_path(current_path),
            tuple(
                (
                    round(float(chunk.get("start") or 0.0), 3),
                    round(float(chunk.get("end") or 0.0), 3),
                    str((payloads.get(index) or {}).get("visible") or (payloads.get(index) or {}).get("change") or ""),
                )
                for index, chunk in enumerate(chunks)
            ),
        )
        if self._preview_strip_signature_matches(page, signature):
            self._focus_preview_strip_selection(page, current_path, current_start)
            return
        row = page.preview_strip_row
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        page.preview_strip_wrap.setVisible(bool(chunks))
        path = str(current_path or "")
        nearest = sorted(
            range(len(chunks)),
            key=lambda index: abs(float(chunks[index].get("start") or 0.0) - float(current_start or 0.0)),
        )
        thumb_starts = {
            round(float(chunks[index].get("start") or 0.0), 3) for index in nearest[:36]
        }
        selected_button = None
        pixmaps = self._page_preview_pixmaps()
        thumb_size = self._candidate_thumb_size()
        missing = []
        for index, chunk in enumerate(chunks):
            start = float(chunk.get("start") or 0.0)
            end = float(chunk.get("end") or start)
            if end <= start:
                end = start + 0.1
            payload = dict(payloads.get(index) or {})
            text = str(payload.get("visible") or payload.get("change") or "").strip()
            pix = self._pixmap_for_hit(pixmaps, path, start)
            if pix is None or pix.isNull():
                pix = self._cached_candidate_thumb(path, start, end, thumb_size)
            if (pix is None or pix.isNull()) and round(start, 3) in thumb_starts:
                missing.append((path, start, end))
                pix = None

            def activate(p=path, s=start, e=end):
                self._switch_search_preview(p, s, e)

            tile = _NearbyCandidateTile(activate)
            tile._hit_path = path
            tile._hit_start = start
            tile.caption.setText(str(index + 1))
            tip = format_timecode_range(start, end)
            if text:
                tip = f"{tip}\n{text}"
            tile.thumb.setToolTip(tip)
            if pix is not None and not pix.isNull():
                tile.thumb.setIcon(QIcon(pix))
                tile.thumb.setIconSize(QSize(108, 60))
            selected = self._same_preview_hit(path, start, current_path, current_start)
            tile.thumb.setProperty("selected", selected)
            repolish_widget(tile.thumb)
            row.addWidget(tile, 0)
            if selected:
                selected_button = tile
        host = page.preview_strip_host
        width = max(host.width(), 8 + len(chunks) * 120)
        host.setMinimumWidth(width)
        host.resize(width, 86)
        if selected_button is not None:
            page.preview_strip.ensureWidgetVisible(selected_button)
        page._strip_signature = signature
        self._start_same_video_thumb_loader(missing)

    def _fill_search_preview_strip(self, current_path: str, current_start: float) -> None:
        if str(getattr(self, "_preview_strip_kind", "") or "") == "dialogue":
            self._fill_dialogue_preview_strip(current_path, current_start)
            return
        if str(getattr(self, "_preview_strip_kind", "") or "") == "chunks":
            self._fill_chunk_preview_strip(current_path, current_start)
            return
        page = self._preview_chrome()
        if page is None:
            return
        hits = self._same_video_candidates(current_path)
        signature = (
            "search",
            tuple(
                (
                    self._norm_media_path(path),
                    round(float(start), 3),
                    round(float(end), 3),
                )
                for path, start, end, _score, _kind, _text in hits
            ),
        )
        if self._preview_strip_signature_matches(page, signature):
            self._focus_preview_strip_selection(page, current_path, current_start)
            return
        row = page.preview_strip_row
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        page.preview_strip_wrap.setVisible(True)
        selected_button = None
        pixmaps = self._page_preview_pixmaps()
        thumb_size = self._candidate_thumb_size()
        missing = []
        for path, start, end, score, _kind, _text in hits:
            pix = self._pixmap_for_hit(pixmaps, path, start)
            if pix is None or pix.isNull():
                pix = self._cached_candidate_thumb(path, start, end, thumb_size)
            if pix is None or pix.isNull():
                missing.append((path, start, end))
                pix = None

            def activate(p=path, s=start, e=end):
                self._switch_search_preview(p, s, e)

            tile = _NearbyCandidateTile(activate)
            tile._hit_path = path
            tile._hit_start = float(start)
            tile.caption.setText(format_timecode_seconds(float(start)))
            tile.thumb.setToolTip(
                f"{format_timecode_range(start, end)}\n{int(float(score) * 100)}%"
            )
            if pix is not None and not pix.isNull():
                tile.thumb.setIcon(QIcon(pix))
                tile.thumb.setIconSize(QSize(108, 60))
            selected = self._same_preview_hit(path, start, current_path, current_start)
            tile.thumb.setProperty("selected", selected)
            repolish_widget(tile.thumb)
            row.addWidget(tile, 0)
            if selected:
                selected_button = tile
        host = page.preview_strip_host
        width = max(host.width(), 8 + len(hits) * 120)
        host.setMinimumWidth(width)
        host.resize(width, 86)
        if selected_button is not None:
            page.preview_strip.ensureWidgetVisible(selected_button)
        page._strip_signature = signature
        self._start_same_video_thumb_loader(missing)

    def _select_search_preview_strip_hit(self, current_path: str, current_start: float) -> bool:
        """Highlight the playing candidate without rebuilding the strip."""
        page = self._preview_chrome()
        if page is None:
            return False
        row = page.preview_strip_row
        found = False
        for index in range(row.count()):
            item = row.itemAt(index)
            tile = item.widget() if item is not None else None
            if tile is None or not hasattr(tile, "thumb"):
                continue
            selected = self._same_preview_hit(
                getattr(tile, "_hit_path", ""),
                getattr(tile, "_hit_start", 0.0),
                current_path,
                current_start,
            )
            found = found or selected
            if bool(tile.thumb.property("selected")) == selected:
                continue
            tile.thumb.setProperty("selected", selected)
            repolish_widget(tile.thumb)
        return found

    def _candidate_thumb_size(self) -> tuple[int, int]:
        cached = getattr(self, "_candidate_thumb_size_cached", None)
        if cached is not None:
            return cached
        from src.app.config import load_config

        config = load_config()
        size = (
            int(config.get("thumb_width", 130) or 130),
            int(config.get("thumb_height", 75) or 75),
        )
        self._candidate_thumb_size_cached = size
        return size

    def _cached_candidate_thumb(self, path: str, start: float, end: float, thumb_size=None):
        from ui.thumb_cache import get_thumb_cache

        if thumb_size is None:
            thumb_size = self._candidate_thumb_size()
        width, height = thumb_size
        cache = get_thumb_cache()
        key = cache.make_key(
            path,
            _thumb_sample_time(start, end),
            width,
            height,
        )
        image = cache.get(key)
        if image is None:
            return None
        from PySide6.QtGui import QImage

        if isinstance(image, QImage):
            if image.isNull():
                return None
            return QPixmap.fromImage(image)
        if isinstance(image, QPixmap):
            return None if image.isNull() else image
        return None

    def _start_same_video_thumb_loader(self, jobs: list) -> None:
        previous = getattr(self, "_same_video_thumb_thread", None)
        if previous is not None:
            previous.stop()
            try:
                previous.thumb_ready.disconnect(self._on_same_video_thumb)
            except (RuntimeError, TypeError):
                pass
        if not jobs:
            self._same_video_thumb_thread = None
            return
        self._strip_thumb_generation = int(getattr(self, "_strip_thumb_generation", 0) or 0) + 1
        thread = _SameVideoThumbLoader(self._strip_thumb_generation, jobs)
        thread.thumb_ready.connect(self._on_same_video_thumb)
        self._same_video_thumb_thread = thread
        thread.start()

    def _on_same_video_thumb(self, generation: int, path: str, start: float, image) -> None:
        if int(generation) != int(getattr(self, "_strip_thumb_generation", 0) or 0):
            return
        page = self._preview_chrome()
        if page is None or image is None:
            return
        from PySide6.QtGui import QImage

        pixmap = QPixmap.fromImage(image) if isinstance(image, QImage) else image
        if pixmap is None or getattr(pixmap, "isNull", lambda: True)():
            return
        strip = page.preview_strip_row
        for index in range(strip.count()):
            tile = strip.itemAt(index).widget()
            if tile is None:
                continue
            if not self._same_preview_hit(getattr(tile, "_hit_path", ""), getattr(tile, "_hit_start", 0.0), path, start):
                continue
            thumb = getattr(tile, "thumb", None)
            if thumb is None:
                continue
            thumb.setIcon(QIcon(pixmap))
            thumb.setIconSize(QSize(108, 60))
            thumb.setText("")
            return

    def _fill_search_preview_detail(self, current_path: str, current_start: float) -> None:
        page = getattr(self, "search_page", None)
        if page is None:
            return
        hit = self._candidate_hit(current_path, current_start)
        path = str(current_path or "")
        start = float(current_start or 0.0)
        end = start
        score = 0.0
        kind = "frame"
        matched = ""
        if hit is not None:
            path = str(hit.video_path or path)
            start = float(hit.start_sec)
            end = float(hit.end_sec)
            score = float(hit.score)
            kind = str(hit.match_kind or "frame")
            matched = str(hit.matched_text or "").strip()
        texts = dict(getattr(self, "texts", None) or {})
        texts.setdefault("result_mode_frame", "帧级")
        texts.setdefault("result_mode_chunk", "片段")
        texts.setdefault("result_mode_video", "视频")
        texts.setdefault("result_mode_dialogue", "字幕")
        texts.setdefault("result_mode_tags", "标签")
        lines = [path] if path else []
        lines.append(f"{texts.get('search_preview_detail_hit', '命中')}  {format_timecode_range(start, end)}")
        lines.append(f"{texts.get('search_preview_detail_score', '相似度')}  {int(score * 100)}%")
        lines.append(
            f"{texts.get('search_preview_detail_kind', '类型')}  {_result_mode_label(start, end, texts, match_kind=kind)}"
        )
        size_text = self._file_size_text(path)
        if size_text:
            lines.append(f"{texts.get('search_preview_detail_size', '大小')}  {size_text}")
        duration_text = self._playing_duration_text()
        if duration_text:
            lines.append(f"{texts.get('search_preview_detail_duration', '时长')}  {duration_text}")
        if matched:
            lines.append(f"{texts.get('search_preview_detail_match', '匹配')}  {matched}")
        body = "\n".join(lines)
        name = video_display_name(path) if path else ""
        self._write_preview_detail(name, path, body)
        token = (path, round(float(start), 3))
        self._preview_detail_token = token
        if duration_text:
            return
        QTimer.singleShot(700, lambda marker=token: self._refresh_preview_detail_duration(marker, 1))

    def _write_preview_detail(self, name: str, path: str, body: str) -> None:
        page = getattr(self, "search_page", None)
        panel = getattr(page, "preview_panel", None) if page is not None else None
        pairs = (
            (getattr(page, "preview_detail_name", None), getattr(page, "preview_detail_body", None)),
            (getattr(panel, "detail_name", None), getattr(panel, "detail_body", None)),
        )
        for name_label, body_label in pairs:
            if name_label is None or body_label is None:
                continue
            name_label.setText(name)
            name_label.setToolTip(path)
            body_label.setText(body)

    def _refresh_preview_detail_duration(self, token, attempt: int) -> None:
        if token != getattr(self, "_preview_detail_token", None):
            return
        if self._playing_duration_text():
            self._fill_search_preview_detail(token[0], token[1])
            return
        if attempt >= 4:
            return
        QTimer.singleShot(700, lambda marker=token, n=attempt + 1: self._refresh_preview_detail_duration(marker, n))

    def _playing_duration_text(self) -> str:
        dialog = getattr(self, "_preview_dialog", None)
        player = getattr(dialog, "player", None)
        if player is None or not hasattr(player, "get_length"):
            return ""
        try:
            length_ms = int(player.get_length() or 0)
        except Exception as exc:
            from src.app.logging_utils import note_swallowed

            note_swallowed(exc, "ui/windows/gui_preview.py:playing_duration")
            return ""
        if length_ms <= 0:
            return ""
        return format_timecode_seconds(length_ms / 1000.0)

    def _file_size_text(self, path: str) -> str:
        try:
            size = os.path.getsize(path)
        except OSError:
            return ""
        value = float(size)
        unit = "B"
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024.0 or unit == "GB":
                break
            value /= 1024.0
        if unit == "B":
            return f"{int(value)} {unit}"
        return f"{value:.1f} {unit}"

    def _update_search_preview_strip_thumb(self, row: int, pixmap) -> None:
        if not getattr(self, "_search_preview_embedded", False):
            return
        page = getattr(self, "search_page", None)
        if page is None or pixmap is None or pixmap.isNull():
            return
        identity = self._page_hit_identity(row)
        if identity is None:
            return
        path, start = identity
        strip = page.preview_strip_row
        for index in range(strip.count()):
            tile = strip.itemAt(index).widget()
            if tile is None:
                continue
            if not self._same_preview_hit(getattr(tile, "_hit_path", ""), getattr(tile, "_hit_start", 0.0), path, start):
                continue
            thumb = getattr(tile, "thumb", None)
            if thumb is None:
                continue
            thumb.setIcon(QIcon(pixmap))
            thumb.setIconSize(QSize(108, 60))
            thumb.setText("")
            return

    def _same_video_candidates(self, current_path: str) -> list:
        hits = []
        for raw in self._preview_candidate_rows():
            try:
                hit = coerce_search_hit(raw)
            except TypeError:
                continue
            path = str(hit.video_path or "").strip()
            if not path or not self._paths_match(path, current_path):
                continue
            hits.append(
                (
                    path,
                    float(hit.start_sec),
                    float(hit.end_sec),
                    float(hit.score),
                    str(hit.match_kind or "frame"),
                    str(hit.matched_text or ""),
                )
            )
        hits.sort(key=lambda item: (item[1], item[2]))
        return hits

    def _candidate_hit(self, current_path: str, current_start: float):
        best = None
        best_gap = None
        for raw in self._preview_candidate_rows():
            try:
                hit = coerce_search_hit(raw)
            except TypeError:
                continue
            if not self._paths_match(hit.video_path, current_path):
                continue
            gap = abs(float(hit.start_sec) - float(current_start))
            if best_gap is None or gap < best_gap:
                best = hit
                best_gap = gap
        if best is not None and best_gap is not None and best_gap < 0.05:
            return best
        return best if best_gap is not None and best_gap < 0.05 else None

    def _preview_candidate_rows(self) -> list:
        controller = getattr(self, "search_controller", None)
        rows = list(getattr(controller, "_all_results", []) or [])
        if rows:
            return rows
        page_rows = []
        view = getattr(getattr(self, "search_page", None), "result_view", None)
        cards = list(getattr(getattr(view, "grid", None), "_cards", []) or [])
        for card in cards:
            path = str(getattr(card, "_video_path", "") or "").strip()
            if not path:
                continue
            page_rows.append(
                (
                    float(card._start_sec),
                    float(card._end_sec),
                    0.0,
                    path,
                    "frame",
                )
            )
        if page_rows:
            return page_rows
        table = getattr(self, "result_table", None)
        if table is None:
            return []
        for index in range(table.rowCount()):
            item = table.item(index, 0)
            payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if not isinstance(payload, dict):
                continue
            path = str(payload.get("video_path") or "").strip()
            if not path:
                continue
            page_rows.append(
                (
                    float(payload.get("start_sec") or 0.0),
                    float(payload.get("end_sec") or 0.0),
                    float(payload.get("score") or 0.0),
                    path,
                    str(payload.get("match_kind") or "frame"),
                )
            )
        return page_rows

    def _page_preview_pixmaps(self) -> dict:
        found = {}
        view = getattr(getattr(self, "search_page", None), "result_view", None)
        cards = list(getattr(getattr(view, "grid", None), "_cards", []) or [])
        for card in cards:
            path = str(getattr(card, "_video_path", "") or "").strip()
            thumb = getattr(card, "thumb_label", None)
            pix = thumb.pixmap() if thumb is not None else None
            if path and pix is not None and not pix.isNull():
                found[(self._norm_media_path(path), round(float(card._start_sec), 3))] = pix
        table = getattr(self, "result_table", None)
        if table is None:
            return found
        for index in range(table.rowCount()):
            item = table.item(index, 0)
            payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
            if not isinstance(payload, dict):
                continue
            path = str(payload.get("video_path") or "").strip()
            pix = self._table_result_thumb(table, index)
            if path and pix is not None and not pix.isNull():
                found[(self._norm_media_path(path), round(float(payload.get("start_sec") or 0.0), 3))] = pix
        return found

    def _pixmap_for_hit(self, pixmaps: dict, path: str, start: float):
        key = (self._norm_media_path(path), round(float(start), 3))
        if key in pixmaps:
            return pixmaps[key]
        for (candidate_path, candidate_start), pix in pixmaps.items():
            if candidate_path == key[0] and abs(candidate_start - key[1]) < 0.05:
                return pix
        return None

    def _page_hit_identity(self, row: int):
        view = getattr(getattr(self, "search_page", None), "result_view", None)
        cards = list(getattr(getattr(view, "grid", None), "_cards", []) or [])
        if cards and 0 <= int(row) < len(cards):
            card = cards[int(row)]
            path = str(getattr(card, "_video_path", "") or "").strip()
            if path:
                return path, float(card._start_sec)
        table = getattr(self, "result_table", None)
        if table is None or int(row) < 0 or int(row) >= table.rowCount():
            return None
        item = table.item(int(row), 0)
        payload = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(payload, dict):
            return None
        path = str(payload.get("video_path") or "").strip()
        if not path:
            return None
        return path, float(payload.get("start_sec") or 0.0)

    def _same_preview_hit(self, left_path, left_start, right_path, right_start) -> bool:
        return self._norm_media_path(left_path) == self._norm_media_path(right_path) and abs(
            float(left_start) - float(right_start)
        ) < 0.05

    def _paths_match(self, left, right) -> bool:
        left_text = str(left or "").strip()
        right_text = str(right or "").strip()
        if not left_text or not right_text:
            return False
        left_norm = self._norm_media_path(left_text)
        right_norm = self._norm_media_path(right_text)
        if left_norm and left_norm == right_norm:
            return True
        if left_norm and right_norm and (left_norm.endswith(right_norm) or right_norm.endswith(left_norm)):
            return True
        try:
            return os.path.samefile(left_text, right_text)
        except OSError:
            return False

    def _norm_media_path(self, path) -> str:
        text = str(path or "").strip()
        if not text:
            return ""
        try:
            text = os.path.abspath(text)
        except (OSError, ValueError):
            pass
        return os.path.normcase(os.path.normpath(text))

    def _table_result_thumb(self, table, row: int):
        for column in range(table.columnCount()):
            cell = table.cellWidget(row, column)
            pix = cell.pixmap() if cell is not None and hasattr(cell, "pixmap") else None
            if pix is not None and not pix.isNull():
                return pix
        return None

    def _switch_search_preview(self, path: str, start: float, end: float) -> None:
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is None:
            return
        start = float(start or 0.0)
        end = float(end) if end is not None else start
        play_start, play_end = self._preview_playback_bounds(path, start, end)
        dialog.load_preview(path, play_start, play_end, suggested_sec=start)
        self._fill_search_preview_detail(path, start)
        if not self._select_search_preview_strip_hit(path, start):
            self._fill_search_preview_strip(path, start)

    def open_segment_preview_dialog(
        self,
        video_path,
        start_sec,
        end_sec,
        *,
        suggested_sec=None,
        on_status=None,
    ) -> bool:
        """Open the on-demand preview dialog. Name kept for call sites."""
        return self.open_floating_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
            on_status=on_status,
        )

    def open_floating_preview_dialog(
        self,
        video_path,
        start_sec,
        end_sec,
        *,
        suggested_sec=None,
        caption_text=None,
        on_status=None,
        embedded=False,
        understanding=False,
    ) -> bool:
        """Open a floating PreviewDialog without leaving the current page."""

        def set_status(message: str) -> None:
            if callable(on_status):
                on_status(message)

        video_path = str(video_path or "").strip()
        if not video_path:
            return False

        now = time.monotonic()
        if self._preview_dialog_opening or now < self._preview_dialog_cooldown_until:
            set_status(
                self.texts.get(
                    "preview_dialog_busy",
                    "Preview is still switching. Try again in a moment.",
                )
            )
            return False

        hit_start = float(start_sec or 0.0)
        hit_end = float(end_sec) if end_sec is not None else hit_start
        suggested = float(
            suggested_sec if suggested_sec is not None else (hit_start + max(hit_end, hit_start)) / 2.0
        )
        start_sec, end_sec = self._preview_playback_bounds(video_path, hit_start, hit_end)
        caption = str(caption_text or "").strip() or None

        self._preview_dialog_opening = True
        self._preview_dialog_cooldown_until = now + 0.35
        try:
            # Soft-pause main preview. Floating dialog uses a second MediaPlayer on the
            # same libvlc Instance — never steal the main HWND (that caused black video).
            try:
                if hasattr(self, "_collapse_preview_maximize"):
                    self._collapse_preview_maximize()
                self.preview_controller.suspend_for_dialog()
                if hasattr(self, "_reset_preview_chrome"):
                    self._reset_preview_chrome()
            except Exception as exc:
                logger.debug("Pause main preview before floating dialog skipped: %s", exc)

            shared_instance = self.preview_controller.ensure_vlc_instance()
            # Ensure main player exists on the shared instance before dialog borrows it.
            self.preview_controller._ensure_vlc_player()
            dialog = getattr(self, "_preview_dialog", None)
            if dialog is not None:
                self._clear_floating_preview_stay_on_top()
            if dialog is None:
                dialog = PreviewDialog(
                    self,
                    video_path,
                    start_sec,
                    end_sec,
                    self.texts,
                    suggested_sec=suggested,
                    caption_text=caption,
                    shared_instance=shared_instance,
                )
                dialog.export_requested.connect(self._queue_preview_export)
                dialog.export_status_changed.connect(self._handle_preview_export_status)
                dialog.destroyed.connect(self._forget_preview_dialog)
                self._preview_dialog = dialog
            else:
                dialog.texts = self.texts
                self._migrate_floating_preview_off_shared_player(dialog, shared_instance)
                dialog.load_preview(
                    video_path,
                    start_sec,
                    end_sec,
                    suggested_sec=suggested,
                    caption_text=caption,
                )
            self._wire_preview_dialog_shot_list(dialog)
            self._wire_layered_preview(dialog)
            if understanding:
                self._present_understanding_preview(dialog)
            elif embedded:
                self._present_embedded_preview(dialog)
                self._fill_search_preview_context(video_path, suggested)
            else:
                self._present_floating_preview(dialog)
            return True
        except Exception as exc:
            logger.exception("Floating preview dialog failed: %s", exc)
            set_status(self.texts.get("preview_failed", "Preview failed"))
            return False
        finally:
            QTimer.singleShot(350, self._release_preview_dialog_gate)

    def _forget_preview_dialog(self, *_args) -> None:
        self._preview_dialog = None

    def _attach_preview_dialog_host(self, dialog) -> None:
        """Keep the preview above a modal shot list without trapping it behind that dialog."""
        host = QApplication.activeModalWidget()
        if host is None or host is dialog:
            host = self
        if dialog.parentWidget() is host:
            return
        dialog.setParent(host, dialog.windowFlags())

    def _wire_preview_dialog_shot_list(self, dialog) -> None:
        if getattr(dialog, "_shot_list_wired", False):
            return
        dialog.add_to_shot_list_requested.connect(self._add_preview_clip_to_shot_list)
        dialog._shot_list_wired = True

    def _clear_floating_preview_stay_on_top(self) -> None:
        """Drop any stuck WindowStaysOnTopHint from older modal+preview stacking."""
        from PySide6.QtCore import Qt

        self._preview_force_on_top = False
        dialog = getattr(self, "_preview_dialog", None)
        if dialog is None:
            return
        flag = Qt.WindowType.WindowStaysOnTopHint
        if not bool(dialog.windowFlags() & flag):
            return
        dialog.setWindowFlag(flag, False)
        if dialog.isVisible():
            dialog.show()

    def _migrate_floating_preview_off_shared_player(self, dialog, shared_instance) -> None:
        """Drop legacy one-player host hopping if this dialog was created before the fix."""
        main_player = getattr(getattr(self, "preview_controller", None), "vlc_player", None)
        legacy_shared = getattr(dialog, "_shared_player", None)
        if legacy_shared is not None:
            # Do not shutdown — that object is (or was) the main search preview player.
            if dialog.player is legacy_shared or dialog.player is main_player:
                dialog.player = None
            dialog._shared_player = None
            dialog._owns_player = True
            dialog._on_release_shared_player = None
            if hasattr(dialog, "video_host") and hasattr(dialog.video_host, "set_player"):
                try:
                    dialog.video_host.set_player(None)
                except Exception as exc:
                    logger.debug("Clear legacy floating host player skipped: %s", exc)
        dialog._shared_instance = shared_instance

    def _restore_shared_preview_player_host(self, player=None) -> None:
        """Legacy no-op keeper: floating preview no longer steals the main HWND."""
        shared = player or getattr(getattr(self, "preview_controller", None), "vlc_player", None)
        host = getattr(self, "video_widget", None)
        if shared is None or host is None:
            return
        try:
            if hasattr(shared, "set_host_widget"):
                shared.set_host_widget(host, force=True)
            shared.suspend()
        except Exception as exc:
            logger.debug("Restore shared preview host skipped: %s", exc)

    def _ensure_preview_chrome(self):
        chrome = self.search_page.expanded_chrome
        if getattr(self, "_expanded_chrome_wired", False):
            chrome.apply_texts(self.texts)
            self._sync_docked_preview_button()
            return
        chrome.apply_texts(self.texts)
        chrome.export_requested.connect(self._queue_preview_export)
        chrome.export_status_changed.connect(self._handle_preview_export_status)
        chrome.add_to_shot_list_requested.connect(self._add_preview_clip_to_shot_list)
        chrome.maximize_toggled.connect(self._on_preview_maximize_toggled)
        self._expanded_chrome_wired = True
        self._sync_docked_preview_button()

    def _add_preview_clip_to_shot_list(self, video_path, start_sec, end_sec, match_kind="clip"):
        if not hasattr(self, "add_hit_to_shot_list"):
            return
        self.add_hit_to_shot_list(
            video_path,
            start_sec,
            end_sec,
            score=None,
            match_kind=str(match_kind or "clip"),
        )

    def _sync_preview_chrome(self, video_path, start_sec, end_sec, suggested_sec):
        self._ensure_preview_chrome()
        chrome = self.search_page.expanded_chrome
        player = self.preview_controller._ensure_vlc_player()
        chrome.bind_player(player)
        chrome.attach_clip(video_path, start_sec, end_sec, suggested_sec=suggested_sec)
        chrome.show_chrome()
        chrome.claim_keyboard_focus()
        if player is not None and player.is_available():
            QTimer.singleShot(0, player.rebind_output_window)
            QTimer.singleShot(80, player.rebind_output_window)

    def _reset_preview_chrome(self):
        chrome = getattr(self.search_page, "expanded_chrome", None)
        if chrome is None:
            return
        chrome.reset()

    def _on_preview_maximize_toggled(self, maximized: bool):
        """Docked player: this button opens the full-page layer instead of covering the list."""
        panel = getattr(self.search_page, "preview_panel", None)
        if panel is not None and getattr(panel, "_docked", False):
            chrome = self.search_page.expanded_chrome
            chrome.set_maximized_state(False)
            self._sync_docked_preview_button()
            if not maximized:
                return
            ctx = self.preview_controller.get_current_preview_context() or {}
            video_path = str(ctx.get("video_path") or "").strip()
            if not video_path:
                return
            self._preview_strip_kind = ""
            self._preview_return_page = ""
            self._preview_surface = self.search_page
            self._enter_search_preview_layer(
                video_path,
                float(ctx.get("start_sec") or 0.0),
                float(ctx.get("end_sec") or 0.0),
                suggested_sec=ctx.get("suggested_sec"),
            )
            return
        self.search_page.set_preview_maximized(bool(maximized))
        player = getattr(self.preview_controller, "vlc_player", None)
        if player is not None and player.is_available():
            QTimer.singleShot(0, player.rebind_output_window)
            QTimer.singleShot(80, player.rebind_output_window)

    def _collapse_preview_maximize(self):
        if self.search_page.is_preview_maximized():
            self.search_page.set_preview_maximized(False)
            player = getattr(self.preview_controller, "vlc_player", None)
            if player is not None and player.is_available():
                QTimer.singleShot(0, player.rebind_output_window)

    def _release_preview_dialog_gate(self):
        self._preview_dialog_opening = False

    def _update_preview_action_button_styles(self):
        has_export_tasks = bool(self._preview_export_tasks)
        for btn in (self.search_page.btn_export_tasks,):
            self._set_button_object_name(
                btn,
                "AccentGhostButton" if has_export_tasks else "GhostButton",
            )
        self._sync_preview_layer_actions()

    def _sync_preview_layer_actions(self) -> None:
        page = getattr(self, "search_page", None)
        if page is None:
            return
        pairs = (
            (getattr(page, "btn_shot_list", None), getattr(page, "btn_preview_shot_list", None)),
            (getattr(page, "btn_export_tasks", None), getattr(page, "btn_preview_export_tasks", None)),
        )
        for source, mirror in pairs:
            if source is None or mirror is None:
                continue
            mirror.setText(source.text())
            mirror.setToolTip(source.toolTip())
            self._set_button_object_name(mirror, source.objectName())

    @staticmethod
    def _set_button_object_name(button, object_name):
        if button.objectName() == object_name:
            return
        button.setObjectName(object_name)
        style = button.style()
        style.unpolish(button)
        style.polish(button)
        button.update()

    def _handle_preview_export_status(self, state, text):
        if state in {"queued", "running", "succeeded", "failed", "cancelled"}:
            self.search_page.lbl_status.setText(text)

    def _queue_preview_export(self, video_path, start_sec, end_sec, save_path, encode_mode=None):
        self._preview_export_seq += 1
        task = {
            "id": self._preview_export_seq,
            "video_path": str(video_path),
            "start_sec": float(start_sec),
            "end_sec": float(end_sec),
            "save_path": str(save_path),
            "encode_mode": encode_mode,
            "status": "queued",
            "worker": None,
            "result": None,
        }
        self._preview_export_queue.append(task)
        self._preview_export_tasks.append(task)
        running_count = len(self._preview_export_active)
        queued_count = len(self._preview_export_queue)
        self.search_page.lbl_status.setText(
            self.texts.get(
                "preview_dialog_export_queue_status",
                "Export queued. Running: {running} | Waiting: {queued}",
            ).format(running=running_count, queued=queued_count)
        )
        self._update_preview_action_button_styles()
        self._start_next_preview_exports()

    def _start_next_preview_exports(self):
        while len(self._preview_export_active) < 2 and self._preview_export_queue:
            task = self._preview_export_queue.popleft()
            worker = ExportClipWorker(
                self.preview_controller,
                task["video_path"],
                task["start_sec"],
                task["end_sec"],
                task["save_path"],
                encode_mode=task.get("encode_mode"),
            )
            task["worker"] = worker
            task["status"] = "running"
            self._preview_export_active[task["id"]] = task
            from ui.threading_utils import connect_on_receiver

            connect_on_receiver(
                worker,
                "finished_export(PyObject,QString)",
                self,
                lambda result, path, task_id=task["id"]: self._handle_preview_export_result(task_id, result, path),
            )
            connect_on_receiver(
                worker,
                "finished()",
                self,
                lambda task_id=task["id"]: self._handle_preview_export_finished(task_id),
            )
            worker.start()
            running_count = len(self._preview_export_active)
            queued_count = len(self._preview_export_queue)
            self.search_page.lbl_status.setText(
                self.texts.get(
                    "preview_dialog_export_running_status",
                    "Export started. Running: {running} | Waiting: {queued}",
                ).format(running=running_count, queued=queued_count)
            )

    def _handle_preview_export_result(self, task_id, result, save_path):
        task = self._preview_export_active.get(task_id)
        if task is None:
            return
        task["result"] = result
        if isinstance(result, ExportCancelledError):
            task["status"] = "cancelled"
            text = self.texts.get("preview_dialog_export_cancelled", "Export cancelled.")
        elif isinstance(result, Exception) or getattr(result, "returncode", 1) != 0:
            task["status"] = "failed"
            text = self.texts.get("export_clip_failed", "Failed to export clip.")
        else:
            task["status"] = "succeeded"
            text = self.texts.get("export_clip_success", "Clip exported: {path}").format(path=save_path)
        self.search_page.lbl_status.setText(text)

    def _handle_preview_export_finished(self, task_id):
        task = self._preview_export_active.pop(task_id, None)
        if task is None:
            self._start_next_preview_exports()
            return
        worker = task.get("worker")
        if worker is not None:
            try:
                worker.deleteLater()
            except Exception as exc:
                logger.debug("Preview export worker deleteLater failed: %s", exc)
        self._start_next_preview_exports()
        if self._preview_export_active or self._preview_export_queue:
            self.search_page.lbl_status.setText(
                self.texts.get(
                    "preview_dialog_export_queue_status",
                    "Export queued. Running: {running} | Waiting: {queued}",
                ).format(
                    running=len(self._preview_export_active),
                    queued=len(self._preview_export_queue),
                )
            )
        self._update_preview_action_button_styles()

    def _cancel_all_preview_exports(self, timeout_ms=3000):
        self._preview_export_queue.clear()
        for task in list(self._preview_export_active.values()):
            worker = task.get("worker")
            if worker is None:
                continue
            task["status"] = "cancelled"
            worker.cancel()
        for task in list(self._preview_export_active.values()):
            worker = task.get("worker")
            if worker is None:
                continue
            if not worker.wait(timeout_ms):
                return False
            try:
                worker.deleteLater()
            except Exception as exc:
                logger.debug("Preview export worker deleteLater failed during cancel: %s", exc)
        self._preview_export_active.clear()
        self._update_preview_action_button_styles()
        return True

    def show_preview_export_tasks(self):
        total = len(self._preview_export_tasks)
        if total == 0:
            self.show_info_dialog(
                self.texts.get("preview_export_tasks_title", "Preview Export Tasks"),
                self.texts.get("preview_export_tasks_empty", "No export tasks yet."),
                kind="info",
            )
            return
        headers = self.texts.get(
            "preview_export_tasks_headers",
            ["#", "Status", "Source Video", "Start", "End", "Output File"],
        )
        rows = []
        for index, task in enumerate(self._preview_export_tasks, start=1):
            rows.append(
                [
                    index,
                    self._format_preview_export_status(task.get("status")),
                    os.path.basename(task.get("video_path", "")) or task.get("video_path", ""),
                    format_timecode_seconds(task.get("start_sec", 0.0)),
                    format_timecode_seconds(task.get("end_sec", 0.0)),
                    task.get("save_path", ""),
                ]
            )
        subtitle = self.texts.get(
            "preview_export_tasks_subtitle",
            "{total} tasks | running {running} | waiting {queued}",
        ).format(
            total=total,
            running=sum(1 for task in self._preview_export_tasks if task.get("status") == "running"),
            queued=sum(1 for task in self._preview_export_tasks if task.get("status") == "queued"),
        )
        ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts.get("preview_export_tasks_title", "Preview Export Tasks"),
            subtitle=subtitle,
            headers=headers,
            rows=rows,
            row_payloads=self._preview_export_tasks,
            export_default_name="preview_export_tasks.json",
            stretch_column=5,
            allow_sorting=False,
            fixed_column_widths={
                0: 52,
                1: 100,
                3: 92,
                4: 92,
            },
            row_double_click_handler=self._open_preview_export_payload,
        ).exec()

    def _format_preview_export_status(self, status):
        key = f"preview_export_status_{status or 'queued'}"
        return self.texts.get(key, str(status or "queued"))

    def _open_preview_export_payload(self, dialog, payload, item=None):
        output_path = str(payload.get("save_path", "")).strip()
        if not output_path:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        if os.path.exists(output_path):
            open_in_explorer(output_path)
        else:
            open_folder_in_explorer(os.path.dirname(output_path))
        dialog.status_hint.setText(output_path)

    def _open_selected_preview_export_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_preview_export_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_preview_export_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        output_path = str(selected[0].get("save_path", "")).strip()
        if not output_path:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(output_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def _prompt_export_encode_mode(self, *, segment_duration_sec: float | None = None) -> str | None:
        return prompt_export_encode_mode(
            self.texts,
            parent=self,
            segment_duration_sec=segment_duration_sec,
        )

    def handle_export_clip(self, path, sec, end_sec=None):
        segment_duration = None
        if end_sec is not None and float(end_sec) > float(sec) + 1e-3:
            segment_duration = float(end_sec) - float(sec)
        encode_mode = self._prompt_export_encode_mode(segment_duration_sec=segment_duration)
        if encode_mode is None:
            return
        base_name = os.path.splitext(os.path.basename(path))[0]
        suggested_name = f"{base_name}_clip_{int(float(sec)):06d}.mp4"
        from src.services.clip_export_service import export_save_dialog_start, remember_export_path

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("export_clip_title", "\u5bfc\u51fa\u9884\u89c8\u7247\u6bb5"),
            export_save_dialog_start(suggested_name),
            self.texts.get("export_clip_filter", "\u89c6\u9891\u6587\u4ef6 (*.mp4 *.mkv *.mov)"),
        )
        if not save_path:
            return
        remember_export_path(save_path)
        self._queue_preview_export(
            path,
            float(sec),
            float(end_sec if end_sec is not None else sec),
            save_path,
            encode_mode=encode_mode,
        )
