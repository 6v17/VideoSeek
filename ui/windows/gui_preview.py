"""Preview panel, export queue, and preview dialog — extracted from MainWindow to shrink gui.py."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from src.app.logging_utils import get_logger
from src.utils import format_timecode_seconds, open_folder_in_explorer, open_in_explorer
from ui.dialogs.export_clip_mode_dialog import prompt_export_encode_mode
from ui.dialogs import ResourceTableDialog
from ui.playback.preview_dialog import ExportCancelledError, ExportClipWorker, PreviewDialog

logger = get_logger("gui_preview")


class PreviewGuiMixin:
    """Preview playback, expand dialog, and clip export tasks; mixed into `MainWindow`."""

    def handle_play(self, path, sec, end_sec=None):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            self._update_expand_preview_button()
            return
        if not self.preview_controller.play(path, sec, end_sec=end_sec):
            self.search_page.lbl_status.setText(self.texts["preview_failed"])
        self._update_expand_preview_button()

    def open_segment_preview_dialog(
        self,
        video_path,
        start_sec,
        end_sec,
        *,
        suggested_sec=None,
        on_status=None,
    ) -> bool:
        def set_status(message: str) -> None:
            if callable(on_status):
                on_status(message)
            else:
                self.search_page.lbl_status.setText(message)

        if not self.check_runtime_resources():
            set_status(self.texts["model_features_disabled"])
            return False

        video_path = str(video_path or "").strip()
        if not video_path:
            return False

        now = time.monotonic()
        if self._preview_dialog_opening or now < self._preview_dialog_cooldown_until:
            set_status(self.texts.get("preview_dialog_busy", "Preview is still switching. Try again in a moment."))
            return False

        start_sec = float(start_sec)
        end_sec = float(end_sec)
        if end_sec <= start_sec:
            end_sec = start_sec + 0.1
        suggested = float(suggested_sec if suggested_sec is not None else (start_sec + end_sec) / 2.0)

        self.preview_controller.stop_preview(skip_telemetry=True)
        self._update_expand_preview_button()
        self._preview_dialog_opening = True
        self._preview_dialog_cooldown_until = now + 0.8

        try:
            if not hasattr(self, "_preview_dialog") or self._preview_dialog is None:
                self._preview_dialog = PreviewDialog(
                    self, video_path, start_sec, end_sec, self.texts, suggested_sec=suggested
                )
                self._preview_dialog.export_requested.connect(self._queue_preview_export)
                self._preview_dialog.export_status_changed.connect(self._handle_preview_export_status)
            else:
                self._preview_dialog.load_preview(
                    video_path, start_sec, end_sec, suggested_sec=suggested
                )
            self._preview_dialog.show()
            self._preview_dialog.raise_()
            self._preview_dialog.activateWindow()
        finally:
            QTimer.singleShot(800, self._release_preview_dialog_gate)
        return True

    def open_current_preview_dialog(self, _event=None):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return

        payload = self.preview_controller.get_current_preview_context()
        if not payload:
            return
        video_path = str(payload.get("video_path", "")).strip()
        if not video_path:
            return

        start_sec = float(payload.get("start_sec", 0.0))
        end_sec = float(payload.get("end_sec", start_sec))
        suggested_sec = float(payload.get("suggested_sec", start_sec))
        self.open_segment_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
        )

    def _release_preview_dialog_gate(self):
        self._preview_dialog_opening = False

    def _update_expand_preview_button(self):
        controller = getattr(self, "preview_controller", None)
        has_preview = controller is not None and controller.get_current_preview_context() is not None
        self.search_page.btn_expand_preview.setEnabled(has_preview)
        self._update_preview_action_button_styles()

    def _update_preview_action_button_styles(self):
        controller = getattr(self, "preview_controller", None)
        has_preview = controller is not None and controller.get_current_preview_context() is not None
        has_export_tasks = bool(self._preview_export_tasks)
        self._set_button_object_name(
            self.search_page.btn_expand_preview,
            "PrimaryButton" if has_preview else "GhostButton",
        )
        for btn in (self.search_page.btn_export_tasks,):
            self._set_button_object_name(
                btn,
                "PrimaryButton" if has_export_tasks else "GhostButton",
            )

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
            worker.finished_export.connect(
                lambda result, path, task_id=task["id"]: self._handle_preview_export_result(task_id, result, path)
            )
            worker.finished.connect(lambda task_id=task["id"]: self._handle_preview_export_finished(task_id))
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
            extra_actions=[
                {
                    "label": self.texts["details_open_selected"],
                    "object_name": "Ghost",
                    "handler": self._open_selected_preview_export_path,
                },
                {
                    "label": self.texts["details_copy_selected"],
                    "object_name": "Ghost",
                    "handler": self._copy_selected_preview_export_path,
                },
            ],
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
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("export_clip_title", "\u5bfc\u51fa\u9884\u89c8\u7247\u6bb5"),
            suggested_name,
            self.texts.get("export_clip_filter", "\u89c6\u9891\u6587\u4ef6 (*.mp4 *.mkv *.mov)"),
        )
        if not save_path:
            return
        self._queue_preview_export(
            path,
            float(sec),
            float(end_sec if end_sec is not None else sec),
            save_path,
            encode_mode=encode_mode,
        )
