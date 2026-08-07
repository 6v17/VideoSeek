"""Shot list (material basket) UI wiring for MainWindow."""

from __future__ import annotations

import os

from PySide6.QtWidgets import QFileDialog

from src.domain.search_hit import SearchHit
from src.services.agent_clip_service import _MAX_BATCH_EXPORT_CLIPS
from src.services.shot_list_export_service import export_shot_list_fcpxml, export_shot_list_manifest
from src.utils import has_ffmpeg, open_folder_in_explorer
from ui.dialogs.shot_list_dialog import ShotListDialog
from ui.threading_utils import shutdown_thread
from ui.workers import ShotListBatchExportWorker


class ShotListGuiMixin:
    def _init_shot_list_ui(self) -> None:
        from src.services.shot_list_service import ShotListStore

        self.shot_list = ShotListStore()
        self._shot_list_export_worker = None
        self.search_page.btn_shot_list.clicked.connect(self.show_shot_list_dialog)
        self._update_shot_list_button()

    def _current_search_query_hint(self) -> str:
        page = getattr(self, "search_page", None)
        if page is None:
            return ""
        tabs = getattr(page, "search_query_tabs", None)
        if tabs is None:
            return ""
        index = int(tabs.currentIndex())
        if index == 1:
            return page.text_search.toPlainText().strip()[:200]
        if index == 2:
            compose = getattr(page, "compose_form", None)
            if compose is not None and hasattr(compose, "input_description"):
                return str(compose.input_description.toPlainText()).strip()[:200]
        if index == 0:
            image_path = str(getattr(self, "current_img_path", "") or "").strip()
            if image_path:
                return image_path
        return ""

    def add_hit_to_shot_list(
        self,
        video_path,
        start_sec,
        end_sec,
        score=None,
        match_kind="frame",
    ) -> None:
        hit = SearchHit(
            float(start_sec),
            float(end_sec if end_sec is not None else start_sec),
            float(score or 0.0),
            str(video_path),
            match_kind=str(match_kind or "frame"),
        )
        added = self.shot_list.add_from_hit(hit, source_query=self._current_search_query_hint())
        if added:
            self.search_page.lbl_status.setText(
                self.texts.get("shot_list_added", "Added to shot list.")
            )
        else:
            self.search_page.lbl_status.setText(
                self.texts.get("shot_list_duplicate", "This clip is already in the shot list.")
            )
        self._update_shot_list_button()

    def show_shot_list_dialog(self) -> None:
        if self.shot_list.count() == 0:
            self.show_info_dialog(
                self.texts.get("shot_list_title", "Shot list"),
                self.texts.get("shot_list_empty", "No clips in the shot list yet."),
                kind="info",
            )
            return
        dialog = ShotListDialog(
            self,
            store=self.shot_list,
            language=self.language,
            is_dark=self.is_dark_mode,
            on_preview=self.handle_play,
            on_locate=self.open_result_in_explorer,
            on_export_manifest=lambda: self._export_shot_list_manifest(),
            on_export_fcpxml=lambda: self._export_shot_list_fcpxml(),
            on_batch_export=lambda: self._export_shot_list_clips(),
            ffmpeg_available=has_ffmpeg(),
        )
        dialog.exec()
        self._update_shot_list_button()

    def _export_shot_list_manifest(self) -> None:
        items = self.shot_list.list_items()
        if not items:
            return
        default_name = self.texts.get("shot_list_manifest_default_name", "shot_list_manifest.json")
        save_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("shot_list_export_manifest_title", "Export shot list manifest"),
            default_name,
            self.texts.get("shot_list_manifest_filter", "JSON (*.json)"),
        )
        if not save_path:
            return
        try:
            payload = export_shot_list_manifest(items, write_path=save_path)
            written = (payload.get("meta") or {}).get("write_path") or save_path
            self.search_page.lbl_status.setText(
                self.texts.get("shot_list_export_manifest_success", "Manifest exported: {path}").format(path=written)
            )
            self.show_info_dialog(
                self.texts.get("shot_list_export_manifest_title", "Export shot list manifest"),
                self.texts.get("shot_list_export_manifest_success", "Manifest exported: {path}").format(path=written),
                kind="info",
            )
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("shot_list_export_manifest_title", "Export shot list manifest"),
                str(exc),
            )

    def _export_shot_list_fcpxml(self) -> None:
        items = self.shot_list.list_items()
        if not items:
            return
        default_name = self.texts.get("shot_list_fcpxml_default_name", "shot_list.xml")
        save_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            self.texts.get("shot_list_export_fcpxml_title", "Export edit XML"),
            default_name,
            self.texts.get(
                "shot_list_fcpxml_filter",
                "Premiere / Resolve XML (*.xml);;Resolve FCPXML (*.fcpxml)",
            ),
        )
        if not save_path:
            return
        lower = str(save_path).lower()
        wants_fcpxml = "fcpxml" in str(selected_filter or "").lower() or lower.endswith(".fcpxml")
        if wants_fcpxml:
            if not lower.endswith(".fcpxml"):
                save_path = f"{save_path}.fcpxml"
        elif not lower.endswith(".xml"):
            save_path = f"{save_path}.xml"
        try:
            payload = export_shot_list_fcpxml(items, write_path=save_path)
            written = payload.get("write_path") or save_path
            clip_count = int(payload.get("exported_count") or payload.get("clip_count") or 0)
            if str(payload.get("format") or "") == "fcp7_xml":
                message = self.texts.get(
                    "shot_list_export_premiere_xml_success",
                    "Premiere XML exported ({count} clips): {path}",
                ).format(count=clip_count, path=written)
            else:
                message = self.texts.get(
                    "shot_list_export_fcpxml_success",
                    "FCPXML exported ({count} clips): {path}",
                ).format(count=clip_count, path=written)
            self.search_page.lbl_status.setText(message)
            self.show_info_dialog(
                self.texts.get("shot_list_export_fcpxml_title", "Export edit XML"),
                message,
                kind="info",
            )
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("shot_list_export_fcpxml_title", "Export edit XML"),
                str(exc),
            )

    def _export_shot_list_clips(self) -> None:
        items = self.shot_list.list_items()
        if not items:
            return
        if len(items) > _MAX_BATCH_EXPORT_CLIPS:
            self.show_error_dialog(
                self.texts.get("shot_list_batch_export", "Batch export clips"),
                self.texts.get("shot_list_batch_export_limit", "Too many clips (max {limit}).").format(
                    limit=_MAX_BATCH_EXPORT_CLIPS
                ),
            )
            return
        if not has_ffmpeg():
            self.show_info_dialog(
                self.texts.get("shot_list_batch_export", "Batch export clips"),
                self.texts.get("shot_list_batch_export_ffmpeg_required", "FFmpeg is required for clip export."),
                kind="warning",
            )
            return
        if self._shot_list_export_worker is not None and self._shot_list_export_worker.isRunning():
            self.search_page.lbl_status.setText(
                self.texts.get("shot_list_batch_export_running", "Batch export is already running.")
            )
            return

        encode_mode = self._prompt_export_encode_mode()
        if encode_mode is None:
            return

        output_dir = QFileDialog.getExistingDirectory(
            self,
            self.texts.get("shot_list_batch_export_title", "Choose output folder"),
        )
        if not output_dir:
            return

        self._start_shot_list_batch_export(items, output_dir, encode_mode)

    def _start_shot_list_batch_export(self, items, output_dir, encode_mode) -> None:
        worker = self._shot_list_export_worker
        if worker is not None:
            shutdown_thread(worker, allow_terminate=False)

        worker = ShotListBatchExportWorker(items, output_dir, encode_mode)
        worker.finished_payload.connect(self._handle_shot_list_batch_export_done)
        worker.error_signal.connect(self._handle_shot_list_batch_export_error)
        worker.finished.connect(self._clear_shot_list_batch_export_worker)
        self._shot_list_export_worker = worker
        self.search_page.lbl_status.setText(
            self.texts.get("shot_list_batch_export_started", "Exporting {count} clips…").format(count=len(items))
        )
        worker.start()

    def _clear_shot_list_batch_export_worker(self) -> None:
        self._shot_list_export_worker = None

    def _handle_shot_list_batch_export_done(self, payload: dict) -> None:
        meta = dict(payload.get("meta") or {})
        succeeded = int(meta.get("succeeded") or 0)
        failed = int(meta.get("failed") or 0)
        total = int(meta.get("total") or succeeded + failed)
        results = list(payload.get("results") or [])
        ok = bool(payload.get("ok"))
        if ok:
            message = self.texts.get(
                "shot_list_batch_export_success",
                "Exported {succeeded}/{total} clips.",
            ).format(succeeded=succeeded, total=total)
            kind = "info"
        elif succeeded <= 0:
            detail = self._format_shot_list_batch_export_failure(results)
            message = self.texts.get(
                "shot_list_batch_export_failed_detail",
                "Batch export failed: {detail}",
            ).format(detail=detail)
            kind = "error"
            self.search_page.lbl_status.setText(message)
            self.show_error_dialog(
                self.texts.get("shot_list_batch_export", "Batch export clips"),
                message,
            )
            return
        else:
            message = self.texts.get(
                "shot_list_batch_export_partial",
                "Exported {succeeded}/{total} clips; {failed} failed.",
            ).format(succeeded=succeeded, total=total, failed=failed)
            kind = "warning"

        self.search_page.lbl_status.setText(message)
        self.show_info_dialog(
            self.texts.get("shot_list_batch_export", "Batch export clips"),
            message,
            kind=kind,
        )

        output_dir = ""
        for entry in results:
            if entry.get("ok") and entry.get("output_path"):
                output_dir = os.path.dirname(str(entry["output_path"]))
                break
        if output_dir and os.path.isdir(output_dir):
            open_folder_in_explorer(output_dir)

    @staticmethod
    def _format_shot_list_batch_export_failure(results) -> str:
        for entry in results or []:
            if entry.get("ok"):
                continue
            error = entry.get("error") or {}
            message = str(error.get("message") or entry.get("message") or "").strip()
            if message:
                return message
        return "Unknown export error."

    def _handle_shot_list_batch_export_error(self, error_text: str) -> None:
        self.search_page.lbl_status.setText(
            self.texts.get("shot_list_batch_export_failed", "Batch export failed.")
        )
        self.show_error_dialog(
            self.texts.get("shot_list_batch_export", "Batch export clips"),
            error_text,
        )

    def _update_shot_list_button(self) -> None:
        button = getattr(self.search_page, "btn_shot_list", None)
        if button is None:
            return
        count = self.shot_list.count()
        label = self.texts.get("shot_list", "Shot list")
        button.setText(f"{label} ({count})" if count else label)
        self._set_button_object_name(button, "PrimaryButton" if count else "GhostButton")
