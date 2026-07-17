"""Media library table, index updates, and index-issue UI — extracted from MainWindow to shrink gui.py."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsOpacityEffect, QAbstractItemView

from src.app.config import load_config
from src.app.indexing_progress import format_progress_text
from src.services.indexing_service import filter_index_problem_issues, list_missing_library_files
from src.services.library_service import (
    add_library,
    list_libraries,
    list_local_vector_details,
    remove_library as remove_library_entry,
)
from src.storage.asset_store import load_model_metadata
from src.workflows.update_video import delete_physical_video_data
from src.storage.lance_store import format_byte_size
from src.utils import open_folder_in_explorer, open_in_explorer
from ui.dialogs import ResourceTableDialog
from ui.views.table_views import populate_library_table
from ui.workers import LocalVectorDetailsWorker


class LibraryIndexingGuiMixin:
    """Library paths, index runs, progress, and index-issue dialogs; mixed into `MainWindow`."""

    def refresh_library_table(self):
        try:
            is_indexing = self.indexing_controller.is_running()
            populate_library_table(
                self.library_page.library_list,
                list_libraries(),
                is_indexing,
                self.sync_library,
                self.remove_library_entry,
                self.open_library_folder,
                self.texts,
            )
            if hasattr(self, "_refresh_search_scope_ui"):
                self._refresh_search_scope_ui()
            if hasattr(self, "_refresh_understanding_scope_options"):
                self._refresh_understanding_scope_options()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_load_failed"], exc)
            return

    def sync_library(self, path):
        self.start_update_index(target_lib=path, rebuild_global_assets=False)

    def open_library_folder(self, path):
        open_folder_in_explorer(path)

    def select_video_folder(self):
        path = QFileDialog.getExistingDirectory(self, self.texts["select_folder"])
        if not path:
            return
        try:
            result = add_library(path)
            if result.get("added"):
                self.refresh_library_table()
                status_text = self.texts["library_added"]
                self.library_page.lbl_status.setText(status_text)
                self.show_info_dialog(self.texts["success_title"], status_text, kind="success")
            elif result.get("reason") == "overlap":
                message = self.texts["library_overlap"].format(path=result.get("conflict_path", ""))
                self.library_page.lbl_status.setText(message)
                self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
            else:
                self.library_page.lbl_status.setText(self.texts["library_exists"])
                self.show_info_dialog(self.texts["warning_title"], self.texts["library_exists"], kind="warning")
        except Exception as exc:
            self.show_error_dialog(self.texts["library_add_failed"], exc)

    def remove_library_entry(self, path):
        if not self.show_confirm_dialog(self.texts["confirm_title"], self.texts["remove_library_confirm"].format(path=path)):
            return
        try:
            if remove_library_entry(path, delete_physical_video_data):
                self.refresh_library_table()
                status_text = self.texts["library_removed"]
                self.library_page.lbl_status.setText(status_text)
                self.show_info_dialog(self.texts["success_title"], status_text, kind="success")
            else:
                self.library_page.lbl_status.setText(self.texts["library_remove_failed"])
        except Exception as exc:
            self.show_error_dialog(self.texts["library_remove_failed"], exc)

    def start_update_index(self, target_lib=None, rebuild_global_assets=True):
        if not self._ensure_startup_migration_idle("feature_indexing"):
            return
        self._start_index_update(
            target_lib=target_lib,
            force_cleanup_missing_files=False,
            rebuild_global_assets=rebuild_global_assets,
        )

    def start_dialogue_index(self):
        self._start_dialogue_index_job(mode="auto")

    def start_dialogue_reembed(self):
        # Force OCR rebuild (button label: re-extract subtitles).
        self._start_dialogue_index_job(mode="ocr")

    def _on_library_tab_changed(self, index: int):
        if int(index) == 1:
            self.refresh_dialogue_library_table()

    def refresh_dialogue_library_table(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem

        from src.services.dialogue_index_service import list_shared_dialogue_library
        from ui.widgets.components import DialogueLibraryRow

        list_widget = self.library_page.dialogue_list
        if not getattr(self, "_dialogue_library_selection_hooked", False):
            list_widget.itemSelectionChanged.connect(self._sync_dialogue_library_row_selection)
            self._dialogue_library_selection_hooked = True
        list_widget.clear()
        try:
            rows = list_shared_dialogue_library()
        except Exception as exc:
            list_widget.addItem(str(exc))
            return
        if not rows:
            list_widget.addItem(
                self.texts.get("dialogue_library_empty", "No shared dialogue yet.")
            )
            return
        for item in rows:
            name = os.path.basename(str(item.get("video_path") or "")) or str(item.get("video_id") or "")
            vector_ok = bool(item.get("has_current_vectors"))
            vector_label = self.texts.get(
                "dialogue_library_vector_yes" if vector_ok else "dialogue_library_vector_no",
                "yes" if vector_ok else "no",
            )
            meta = self.texts.get(
                "dialogue_library_row_meta",
                "{segments} lines",
            ).format(segments=int(item.get("segment_count") or 0))
            row_item = QListWidgetItem()
            row_item.setData(Qt.ItemDataRole.UserRole, str(item.get("video_id") or ""))
            row_widget = DialogueLibraryRow(name, meta, vector_label, ready=vector_ok)
            row_item.setSizeHint(row_widget.sizeHint())
            list_widget.addItem(row_item)
            list_widget.setItemWidget(row_item, row_widget)
        self._sync_dialogue_library_row_selection()

    def _sync_dialogue_library_row_selection(self):
        from ui.widgets.components import DialogueLibraryRow

        list_widget = self.library_page.dialogue_list
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            if item is None:
                continue
            widget = list_widget.itemWidget(item)
            if isinstance(widget, DialogueLibraryRow):
                widget.set_selected(bool(item.isSelected()))

    def export_dialogue_library(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        from src.services.dialogue_export_service import export_dialogue_transcripts
        from src.storage.dialogue_transcript_store import list_dialogue_transcript_records

        title = self.texts.get("export_dialogue_library_title", "Export dialogue")
        records = list_dialogue_transcript_records()
        if not records:
            self.show_info_dialog(
                title,
                self.texts.get("export_dialogue_library_empty", "No shared dialogue to export."),
                kind="info",
            )
            return

        selected_ids: list[str] = []
        for item in self.library_page.dialogue_list.selectedItems():
            video_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if video_id:
                selected_ids.append(video_id)

        format_labels = [
            self.texts.get("export_dialogue_format_srt", "SRT (.srt)"),
            self.texts.get("export_dialogue_format_txt", "TXT (.txt)"),
            self.texts.get("export_dialogue_format_json", "JSON (.json)"),
        ]
        format_keys = ["srt", "txt", "json"]
        chosen, ok = QInputDialog.getItem(
            self,
            title,
            self.texts.get("export_dialogue_library_pick_format", "Choose export format"),
            format_labels,
            0,
            False,
        )
        if not ok:
            return
        try:
            fmt = format_keys[format_labels.index(chosen)]
        except ValueError:
            fmt = "srt"

        out_dir = QFileDialog.getExistingDirectory(
            self,
            self.texts.get("export_dialogue_library_pick_dir", "Choose export folder"),
        )
        if not out_dir:
            return

        result = export_dialogue_transcripts(
            out_dir,
            format=fmt,
            video_ids=selected_ids or None,
        )
        if not result.get("ok") and int(result.get("exported") or 0) <= 0:
            self.show_error_dialog(
                self.texts.get("export_dialogue_library_failed", "Dialogue export failed"),
                str(result.get("error") or "export failed"),
            )
            return
        self.show_info_dialog(
            self.texts.get("success_title", "Success"),
            self.texts.get(
                "export_dialogue_library_done",
                "Exported {count} file(s) to:\n{path}",
            ).format(count=int(result.get("exported") or 0), path=result.get("output_dir") or out_dir),
            kind="success",
        )
        self.library_page.lbl_status.setText(
            self.texts.get(
                "export_dialogue_library_done",
                "Exported {count} file(s).",
            ).format(count=int(result.get("exported") or 0), path=result.get("output_dir") or out_dir)
        )

    def _format_dialogue_stage(self, stage_token: str) -> str:
        token = str(stage_token or "").strip()
        if not token:
            return ""
        head = token.split("|", 1)[0]
        detail = ""
        if token.startswith("dialogue_embed|"):
            parts = token.split("|")
            if len(parts) >= 3:
                detail = f"{parts[1]}/{parts[2]}"
            head = "dialogue_embed"
        mapping = {
            "dialogue_extract": "dialogue_stage_extract",
            "dialogue_asr": "dialogue_stage_asr",
            "dialogue_merge": "dialogue_stage_merge",
            "dialogue_save_transcript": "dialogue_stage_save_transcript",
            "dialogue_reuse_transcripts": "dialogue_stage_reuse",
            "dialogue_embed": "dialogue_stage_embed",
            "dialogue_upsert": "dialogue_stage_upsert",
            "dialogue_done": "dialogue_stage_done",
            "dialogue_index_done": "dialogue_stage_done",
            "subtitle_extract_audio": "dialogue_stage_extract",
            "subtitle_probe": "dialogue_stage_extract",
            "subtitle_vad": "dialogue_stage_asr",
            "subtitle_ocr": "dialogue_stage_asr",
            "subtitle_merge": "dialogue_stage_merge",
            "subtitle_reuse": "dialogue_stage_reuse",
            "subtitle_done": "dialogue_stage_done",
        }
        if head.startswith("subtitle_ocr"):
            head = "subtitle_ocr"
        key = mapping.get(head, "")
        if not key:
            return token
        template = self.texts.get(key, token)
        try:
            return template.format(detail=detail)
        except Exception:
            return template

    def _start_dialogue_index_job(self, *, mode: str = "auto"):
        if not self._ensure_startup_migration_idle("feature_indexing"):
            return
        if self.indexing_controller.is_running() or self._dialogue_index_running():
            self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
            return
        if not self.check_runtime_resources():
            self.library_page.lbl_status.setText(self.texts["model_features_disabled"])
            return

        from src.services.dialogue_index_service import (
            ensure_dialogue_asr_ready,
            list_dialogue_index_targets,
            list_dialogue_reembed_targets,
        )
        from src.storage.dialogue_transcript_store import (
            ensure_shared_transcripts,
            list_dialogue_transcript_records,
        )

        self.library_page.library_tabs.setCurrentIndex(1)
        mode_value = str(mode or "auto").strip().lower() or "auto"
        reembed = mode_value == "reembed"
        title_key = "reembed_dialogue_index" if reembed else "build_dialogue_index"
        title = self.texts.get(title_key, title_key)

        if reembed:
            targets = list_dialogue_reembed_targets()
            if not targets:
                self.show_info_dialog(
                    title,
                    self.texts.get(
                        "reembed_dialogue_index_no_targets",
                        "No dialogue transcripts to re-embed.",
                    ),
                    kind="info",
                )
                return
            confirm = self.texts.get(
                "reembed_dialogue_index_confirm",
                "Re-embed dialogue vectors for {count} videos?",
            ).format(count=len(targets))
            running = self.texts.get(
                "reembed_dialogue_index_running",
                "Re-embedding dialogue vectors...",
            )
        else:
            targets = list_dialogue_index_targets()
            if not targets:
                self.show_info_dialog(
                    title,
                    self.texts.get("build_dialogue_index_no_targets", "No ready videos to index."),
                    kind="info",
                )
                return
            ensure_shared_transcripts()
            existing_ids = {
                str(row.get("video_id") or "").strip()
                for row in list_dialogue_transcript_records()
            }
            needs_asr = any(
                str((item or {}).get("video_id") or "").strip() not in existing_ids for item in targets
            )
            if needs_asr:
                asr_ready, asr_error = ensure_dialogue_asr_ready()
                if not asr_ready:
                    self.show_info_dialog(
                        title,
                        self.texts.get(
                            "build_dialogue_index_missing_asr",
                            "Import RapidOCR first (Understanding / Settings → Import Model).",
                        )
                        + (f"\n\n{asr_error}" if asr_error else ""),
                        kind="warning",
                    )
                    return
            confirm = self.texts.get(
                "build_dialogue_index_confirm",
                "Build dialogue index for {count} videos?",
            ).format(count=len(targets))
            running = self.texts.get("build_dialogue_index_running", "Building dialogue index...")

        if not self.show_confirm_dialog(self.texts["confirm_title"], confirm, kind="info"):
            return

        from ui.workers import DialogueIndexWorker

        self.library_page.btn_sync_db.setEnabled(False)
        self.library_page.btn_build_dialogue_index.setEnabled(False)
        self.library_page.btn_reembed_dialogue.setEnabled(False)
        self.library_page.btn_export_dialogue.setEnabled(False)
        self.library_page.btn_refresh_dialogue_library.setEnabled(False)
        self.library_page.btn_add_lib.setEnabled(False)
        self.library_page.btn_cleanup_missing.setEnabled(False)
        self.library_page.btn_stop_dialogue_index.setEnabled(True)
        self.library_page.btn_stop_dialogue_index.setVisible(True)
        self.library_page.progress_bar.setVisible(True)
        self.library_page.progress_bar.setValue(0)
        self.library_page.lbl_status.setText(running)
        self._dialogue_index_ui_mode = mode_value

        worker = DialogueIndexWorker(targets=targets, mode=mode_value)
        self.dialogue_index_worker = worker
        worker.progress_signal.connect(self._update_dialogue_index_progress)
        worker.error_signal.connect(self._handle_dialogue_index_error)
        worker.finished_signal.connect(self._finish_dialogue_index)
        worker.start()

    def _dialogue_index_running(self) -> bool:
        worker = getattr(self, "dialogue_index_worker", None)
        return bool(worker is not None and worker.isRunning())

    def _update_dialogue_index_progress(self, value, text):
        self.library_page.progress_bar.setValue(int(value))
        raw = str(text or "")
        reembed = str(getattr(self, "_dialogue_index_ui_mode", "") or "") == "reembed"
        if raw.startswith("dialogue_index|"):
            parts = raw.split("|")
            if len(parts) >= 3:
                stage_token = "|".join(parts[3:]) if len(parts) > 3 else ""
                stage = self._format_dialogue_stage(stage_token) or stage_token or "…"
                self.library_page.lbl_status.setText(
                    self.texts.get(
                        "build_dialogue_index_progress",
                        "Dialogue {current}/{total}: {stage}",
                    ).format(current=parts[1], total=parts[2], stage=stage)
                )
                return
        self.library_page.lbl_status.setText(
            self.texts.get(
                "reembed_dialogue_index_running" if reembed else "build_dialogue_index_running",
                "Building dialogue index...",
            )
        )

    def _handle_dialogue_index_error(self, message):
        self.show_error_dialog(
            self.texts.get("build_dialogue_index_failed", "Dialogue index failed"),
            message,
        )

    def _finish_dialogue_index(self, success, stopped, summary):
        self.dialogue_index_worker = None
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_build_dialogue_index.setEnabled(True)
        self.library_page.btn_reembed_dialogue.setEnabled(True)
        self.library_page.btn_export_dialogue.setEnabled(True)
        self.library_page.btn_refresh_dialogue_library.setEnabled(True)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.btn_cleanup_missing.setEnabled(True)
        self.library_page.btn_stop_dialogue_index.setEnabled(False)
        self.library_page.btn_stop_dialogue_index.setVisible(False)
        self.library_page.progress_bar.setVisible(False)
        payload = dict(summary or {})
        reembed = str(payload.get("mode") or getattr(self, "_dialogue_index_ui_mode", "") or "") == "reembed"
        self._dialogue_index_ui_mode = ""
        if stopped:
            status = self.texts.get("build_dialogue_index_stopped", "Dialogue index stopped.")
        elif success:
            done_key = "reembed_dialogue_index_done" if reembed else "build_dialogue_index_done"
            status = self.texts.get(
                done_key,
                "Dialogue index done: {ok} ok, {failed} failed, {segments} segments.",
            ).format(
                ok=int(payload.get("ok", 0) or 0),
                failed=int(payload.get("failed", 0) or 0),
                segments=int(payload.get("segment_rows", 0) or 0),
                reused=int(payload.get("reused", 0) or 0),
            )
        else:
            status = self.texts.get("build_dialogue_index_failed", "Dialogue index failed")
        self.library_page.lbl_status.setText(status)
        self.refresh_library_table()
        self.refresh_dialogue_library_table()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()

    def start_debug_gpu_oom(self):
        self._start_index_update(debug_failure="gpu_oom")

    def start_debug_system_oom(self):
        self._start_index_update(debug_failure="system_oom")

    def cleanup_missing_library_vectors(self):
        try:
            config = load_config()
            meta = load_model_metadata(config=config)
            missing_entries = list(list_missing_library_files(meta, config))
        except Exception as exc:
            self.show_error_dialog(self.texts["library_load_failed"], exc)
            return

        if not missing_entries:
            self.show_info_dialog(
                self.texts["cleanup_missing_vectors_preview_title"],
                self.texts["cleanup_missing_vectors_preview_empty"],
                kind="info",
            )
            return

        reviewed_entries = self._show_cleanup_preview_dialog(missing_entries)
        if reviewed_entries is None:
            return
        if not reviewed_entries:
            self.show_info_dialog(
                self.texts["cleanup_missing_vectors_preview_title"],
                self.texts["cleanup_missing_vectors_preview_empty"],
                kind="info",
            )
            return

        if not self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["cleanup_missing_vectors_confirm"].format(count=len(reviewed_entries)),
            kind="warning",
        ):
            return
        self._start_index_update(
            target_lib=None,
            force_cleanup_missing_files=True,
            cleanup_missing_entries=reviewed_entries,
        )

    def _show_cleanup_preview_dialog(self, missing_entries):
        rows = []
        for index, entry in enumerate(missing_entries, start=1):
            rows.append(
                [
                    index,
                    entry["library_path"],
                    entry["video_rel_path"],
                    entry.get("video_id", "") or "",
                    entry["abs_path"],
                ]
            )

        subtitle = "\n".join(
            [
                self.texts["cleanup_missing_vectors_preview_summary"].format(
                    count=len(missing_entries),
                    libraries=len({entry["library_path"] for entry in missing_entries}),
                ),
                self.texts["cleanup_missing_vectors_preview_continue"],
            ]
        )
        dialog = ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts["cleanup_missing_vectors_preview_title"],
            subtitle=subtitle,
            headers=self.texts["cleanup_missing_vectors_headers"],
            rows=rows,
            export_default_name=self.texts["cleanup_missing_vectors_export_name"],
            stretch_column=4,
            fixed_column_widths={
                0: 52,
                2: 220,
                3: 140,
            },
            confirm_mode=True,
            confirm_text=self.texts["confirm_action"],
            issue_row_predicate=lambda row: True,
            summary_text=self.texts["cleanup_missing_vectors_preview_continue"],
            row_payloads=missing_entries,
            extra_actions=[
                {
                    "label": self.texts["details_exclude_selected"],
                    "object_name": "Ghost",
                    "handler": self._exclude_cleanup_preview_selection,
                }
            ],
            selection_mode=QAbstractItemView.ExtendedSelection,
        )
        if not dialog.exec():
            return None
        return dialog.row_payloads

    def _exclude_cleanup_preview_selection(self, dialog):
        removed = dialog.remove_selected_payloads()
        if not removed:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        dialog.status_hint.setText(self.texts["details_excluded_count"].format(count=removed))
        if not dialog.row_payloads:
            dialog.reject()

    def _start_index_update(
        self,
        target_lib=None,
        force_cleanup_missing_files=False,
        cleanup_missing_entries=None,
        rebuild_global_assets=True,
        debug_failure="",
        index_from_vectors_only=False,
    ):
        try:
            if not self.check_runtime_resources():
                self.library_page.lbl_status.setText(self.texts["model_features_disabled"])
                return
            self.switch_page("library")
            if self.indexing_controller.is_running() or self._dialogue_index_running():
                self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
                return
            self.library_page.btn_sync_db.setEnabled(False)
            self.library_page.btn_build_dialogue_index.setEnabled(False)
            self.library_page.btn_reembed_dialogue.setEnabled(False)
            self.library_page.btn_export_dialogue.setEnabled(False)
            self.library_page.btn_stop_index.setEnabled(True)
            self.library_page.btn_stop_index.setVisible(True)
            self.library_page.btn_add_lib.setEnabled(False)
            self._apply_index_issue_button_state(False)
            self.library_page.btn_cleanup_missing.setEnabled(False)
            if getattr(self, "_debug_tools_enabled", False):
                self.library_page.btn_debug_gpu_oom.setEnabled(False)
                self.library_page.btn_debug_system_oom.setEnabled(False)
            self.library_page.progress_bar.setVisible(True)
            self._last_index_issues = []
            self._last_index_issue_target = target_lib
            self._indexing_progress_file_index = 0
            self._indexing_progress_ui_at = 0.0
            self.refresh_library_table()
            start_kwargs = {
                "target_lib": target_lib,
                "force_cleanup_missing_files": force_cleanup_missing_files,
                "cleanup_missing_entries": cleanup_missing_entries,
                "rebuild_global_assets": rebuild_global_assets,
                "index_from_vectors_only": index_from_vectors_only,
            }
            if debug_failure:
                start_kwargs["debug_failure"] = debug_failure
            if self.indexing_controller.start(**start_kwargs):
                self.ui_state.set_indexing_running(True)
                if hasattr(self, "_sync_tray_stop_action"):
                    self._sync_tray_stop_action()
            self._refresh_search_session_hint()
            if hasattr(self, "_refresh_understanding_ui"):
                self._refresh_understanding_ui()
        except Exception as exc:
            self.show_error_dialog(self.texts["index_start_failed"], exc)

    def stop_update_index(self):
        if self._dialogue_index_running():
            worker = getattr(self, "dialogue_index_worker", None)
            if worker is not None and hasattr(worker, "stop"):
                worker.stop()
                self.library_page.lbl_status.setText(self.texts["index_stop_requested"])
                self.library_page.btn_stop_index.setEnabled(False)
            return
        if not self.indexing_controller.is_running():
            return
        if self.indexing_controller.request_stop():
            self.library_page.lbl_status.setText(self.texts["index_stop_requested"])
            self.library_page.btn_stop_index.setEnabled(False)

    def _update_indexing_progress(self, value, text):
        from src.app.indexing_progress import parse_progress_token

        now = time.monotonic()
        raw = str(text or "")
        payload = parse_progress_token(raw) or {}
        file_index = int(payload.get("file_index") or 0)
        stage = str(payload.get("stage") or "").strip().lower()
        last_file = int(getattr(self, "_indexing_progress_file_index", 0) or 0)
        file_changed = bool(file_index and file_index != last_file)
        if file_changed:
            self._indexing_progress_file_index = file_index

        # Full library rebuild is expensive (destroy/recreate cards + reload meta).
        # Only do it when the active video changes — not on every decode tick.
        if file_changed or stage == "file":
            self.refresh_library_table()
            if hasattr(self, "_sync_tray_stop_action"):
                self._sync_tray_stop_action()

        last_ui = float(getattr(self, "_indexing_progress_ui_at", 0.0) or 0.0)
        if not file_changed and now - last_ui < 0.2:
            return
        self._indexing_progress_ui_at = now
        self.library_page.progress_bar.setValue(int(value))
        self.library_page.lbl_status.setText(format_progress_text(raw, self.texts))

    def _finish_indexing(self, success, target_lib, stopped=False, has_search_assets=False, issues=None, rebuild_global_assets=True):
        self.ui_state.set_indexing_running(False)
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_build_dialogue_index.setEnabled(True)
        self.library_page.btn_reembed_dialogue.setEnabled(True)
        self.library_page.btn_export_dialogue.setEnabled(True)
        self.library_page.btn_stop_index.setEnabled(False)
        self.library_page.btn_stop_index.setVisible(False)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.btn_cleanup_missing.setEnabled(True)
        if getattr(self, "_debug_tools_enabled", False):
            self.library_page.btn_debug_gpu_oom.setEnabled(True)
            self.library_page.btn_debug_system_oom.setEnabled(True)
        self.library_page.progress_bar.setVisible(False)
        self.push_inference_status()
        self.refresh_library_table()
        issue_list = filter_index_problem_issues(issues)
        issue_count = len(issue_list)
        self._last_index_issues = issue_list
        self._last_index_issue_target = target_lib
        self._apply_index_issue_button_state(issue_count > 0)
        if stopped:
            status_text = self.texts["index_stopped"]
        elif success:
            if has_search_assets:
                status_text = self.texts["index_updated_single"] if target_lib else self.texts["index_updated"]
            else:
                status_text = self.texts["index_updated_empty_single"] if target_lib else self.texts["index_updated_empty"]
            if issue_count:
                status_text = f"{status_text} {self.texts['index_issue_summary'].format(count=issue_count)}"
        else:
            status_text = self.texts["index_failed"]
        self.library_page.lbl_status.setText(status_text)
        self._refresh_search_session_hint()
        if hasattr(self, "_refresh_understanding_ui"):
            self._refresh_understanding_ui()
        self._show_index_issue_guidance(issue_list)
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()
        if self._close_when_indexing_stops:
            self._close_when_indexing_stops = False
            self.close()

    def _refresh_search_session_hint(self):
        if hasattr(self, "_refresh_search_panel_state"):
            self._refresh_search_panel_state()
        indexing_running = self.ui_state.indexing_running
        self.search_page.indexing_notice.setVisible(indexing_running)
        if indexing_running:
            self._start_search_indexing_notice_animation()
        else:
            self._stop_search_indexing_notice_animation()

    def _start_search_indexing_notice_animation(self):
        if self._search_indexing_notice_effect is None:
            effect = QGraphicsOpacityEffect(self.search_page.indexing_notice)
            effect.setOpacity(1.0)
            self.search_page.indexing_notice.setGraphicsEffect(effect)
            self._search_indexing_notice_effect = effect
        if self._search_indexing_notice_animation is None:
            animation = QPropertyAnimation(self._search_indexing_notice_effect, b"opacity", self)
            animation.setStartValue(1.0)
            animation.setEndValue(0.55)
            animation.setDuration(900)
            animation.setEasingCurve(QEasingCurve.InOutSine)
            animation.setLoopCount(-1)
            self._search_indexing_notice_animation = animation
        if self._search_indexing_notice_animation.state() != QPropertyAnimation.Running:
            self._search_indexing_notice_animation.start()

    def _stop_search_indexing_notice_animation(self):
        animation = self._search_indexing_notice_animation
        if animation is not None and animation.state() == QPropertyAnimation.Running:
            animation.stop()
        if self._search_indexing_notice_effect is not None:
            self._search_indexing_notice_effect.setOpacity(1.0)

    def _handle_indexing_error(self, error_text):
        detail = str(error_text or "").strip()
        if not detail:
            return
        self.show_error_dialog(self.texts["index_failed"], detail)

    def _show_index_issue_guidance(self, issues):
        issue_list = list(issues or [])
        if not issue_list:
            return
        timestamp_issue_count = sum(1 for item in issue_list if item.get("reason") == "timestamp_drift")
        if timestamp_issue_count > 0:
            message = self.texts["index_issues_timestamp_guidance"].format(
                count=timestamp_issue_count,
                button=self.texts["index_issues_button"],
            )
            self.show_info_dialog(self.texts["warning_title"], message, kind="warning")
            return

        gpu_issue_count = sum(1 for item in issue_list if item.get("reason") == "gpu_out_of_memory")
        system_issue_count = sum(1 for item in issue_list if item.get("reason") == "system_out_of_memory")
        if gpu_issue_count <= 0 and system_issue_count <= 0:
            return
        if gpu_issue_count >= system_issue_count:
            resource_text = self.texts["index_issues_memory_resource_gpu"]
            issue_count = gpu_issue_count
        else:
            resource_text = self.texts["index_issues_memory_resource_system"]
            issue_count = system_issue_count
        message = self.texts["index_issues_memory_guidance"].format(
            count=issue_count,
            resource=resource_text,
            button=self.texts["index_issues_button"],
        )
        self.show_info_dialog(self.texts["warning_title"], message, kind="warning")

    def _apply_index_issue_button_state(self, has_issues):
        button = self.library_page.btn_index_issues
        button.setEnabled(bool(has_issues))
        button.setObjectName("WarningButton" if has_issues else "GhostButton")
        button.style().unpolish(button)
        button.style().polish(button)
        button.update()

    def show_last_index_issue_details(self):
        if not self._last_index_issues:
            self.show_info_dialog(
                self.texts["index_issues_title"],
                self.texts["index_issues_empty"],
                kind="info",
            )
            return
        self.show_index_issue_details(self._last_index_issues, target_lib=self._last_index_issue_target)

    def show_index_issue_details(self, issues, target_lib=None):
        issue_list = list(issues or [])
        if not issue_list:
            return

        rows = []
        payloads = []
        for index, item in enumerate(issue_list, start=1):
            rows.append(
                [
                    index,
                    item.get("library_path", ""),
                    item.get("video_rel_path", ""),
                    self._format_index_issue_action(item.get("action")),
                    self._format_index_issue_reason(item.get("reason")),
                ]
            )
            payloads.append(item)

        subtitle = self.texts["index_issues_subtitle"].format(
            count=len(issue_list),
            scope=self.texts["index_issues_scope_single"] if target_lib else self.texts["index_issues_scope_all"],
        )
        ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts["index_issues_title"],
            subtitle=subtitle,
            headers=self.texts["index_issues_headers"],
            rows=rows,
            row_payloads=payloads,
            export_default_name="index_issues.json",
            stretch_column=2,
            allow_sorting=False,
            fixed_column_widths={
                0: 52,
                3: 120,
                4: 180,
            },
            issue_row_predicate=lambda _row: True,
            extra_actions=[
                {
                    "label": self.texts["details_open_selected"],
                    "object_name": "Ghost",
                    "handler": self._open_selected_index_issue_path,
                },
                {
                    "label": self.texts["details_copy_selected"],
                    "object_name": "Ghost",
                    "handler": self._copy_selected_index_issue_path,
                },
            ],
            row_double_click_handler=self._open_index_issue_payload,
        ).exec()

    def _format_index_issue_action(self, action):
        action_key = str(action or "").strip().lower() or "skipped"
        return self.texts.get(f"index_issue_action_{action_key}", action_key)

    def _format_index_issue_reason(self, reason):
        reason_key = str(reason or "").strip().lower()
        if not reason_key:
            return ""
        return self.texts.get(
            f"index_issue_reason_{reason_key}",
            self.texts.get(f"library_sync_failure_reason_{reason_key}", reason_key),
        )

    def _open_index_issue_payload(self, dialog, payload, item=None):
        target_path = str(payload.get("abs_path", "")).strip()
        library_path = str(payload.get("library_path", "")).strip()
        detail = str(payload.get("detail", "")).strip()
        if not target_path and library_path:
            target_path = library_path
        if not target_path:
            dialog.status_hint.setText(detail or self.texts["details_nothing_selected"])
            return
        if os.path.exists(target_path):
            open_in_explorer(target_path)
        else:
            fallback_dir = os.path.dirname(target_path) or library_path
            if fallback_dir:
                open_folder_in_explorer(fallback_dir)
        dialog.status_hint.setText(f"{target_path} | {detail}" if detail else target_path)

    def _open_selected_index_issue_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_index_issue_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_index_issue_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = str(payload.get("abs_path", "")).strip() or str(payload.get("library_path", "")).strip()
        if not target_path:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def show_local_vector_details(self):
        try:
            detail = list_local_vector_details(validate_contents=False)
            headers = self.texts["library_vectors_headers"]
            ready_state_text = self._local_vector_asset_state_text("ready")
            rows, payloads = self._build_local_vector_detail_rows(detail)
            storage_summary = detail.get("storage_summary") or {}
            subtitle = self.texts["library_vectors_subtitle"].format(
                total=detail["total_entries"],
                lance_dir=detail.get("lance_dir", ""),
                frame_rows=int((detail.get("lance_summary") or {}).get("frame_rows", 0) or 0),
                chunk_rows=int((detail.get("lance_summary") or {}).get("chunk_rows", 0) or 0),
                video_count=int((detail.get("lance_summary") or {}).get("indexed_video_count", 0) or 0),
                total_storage=format_byte_size(storage_summary.get("total_storage_bytes", 0)),
                lance_storage=format_byte_size(
                    storage_summary.get("lance_active_bytes", storage_summary.get("lance_dir_bytes", 0))
                ),
                legacy_storage=format_byte_size(storage_summary.get("legacy_vector_dir_bytes", 0)),
            )
            dialog = ResourceTableDialog(
                parent=self,
                is_dark=self.is_dark_mode,
                language=self.language,
                title=self.texts["library_vectors_title"],
                subtitle=subtitle,
                headers=headers,
                rows=rows,
                row_payloads=payloads,
                export_default_name="local_vector_index_details.json",
                stretch_column=2,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    1: 220,
                    3: 280,
                    4: 96,
                    5: 72,
                    6: 72,
                    7: 88,
                    8: 86,
                    9: 86,
                    10: 132,
                    11: 200,
                },
                issue_row_predicate=lambda row, ready_text=ready_state_text: row[10] != ready_text,
                extra_actions=[
                    {
                        "label": self.texts["details_open_selected"],
                        "object_name": "Ghost",
                        "handler": self._open_selected_vector_detail_path,
                    },
                    {
                        "label": self.texts["details_copy_selected"],
                        "object_name": "Ghost",
                        "handler": self._copy_selected_vector_detail_path,
                    },
                ],
                row_double_click_handler=self._open_vector_detail_payload,
            )
            dialog.set_summary_text(self.texts["library_vectors_validation_loading"])
            self._start_local_vector_detail_validation(dialog)
            dialog.exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_vectors_load_failed"], exc)

    def _build_local_vector_detail_rows(self, detail):
        rows = []
        payloads = []
        lance_dir = str(detail.get("lance_dir", "") or "")
        for index, item in enumerate(detail["entries"], start=1):
            payload = dict(item)
            payload["lance_dir"] = lance_dir
            frame_count = int(item.get("lance_frame_count", 0) or 0)
            chunk_count = int(item.get("lance_chunk_count", 0) or 0)
            storage_bytes = int(item.get("storage_bytes", 0) or 0)
            rows.append(
                [
                    index,
                    item["library_path"],
                    item["video_rel_path"],
                    item.get("video_id", ""),
                    self.texts["details_yes"] if item.get("lance_ready") else self.texts["details_no"],
                    str(frame_count) if item.get("lance_ready") else "-",
                    str(chunk_count) if item.get("lance_ready") else "-",
                    format_byte_size(storage_bytes) if storage_bytes > 0 else "-",
                    self.texts["details_yes"] if item.get("legacy_npy_exists") else self.texts["details_no"],
                    self.texts["details_yes"] if item.get("source_exists") else self.texts["details_no"],
                    self._local_vector_asset_state_text(item.get("asset_state", "")),
                    self._local_vector_failure_reason_text(item.get("sync_failure_reason", "")),
                ]
            )
            payloads.append(payload)
        return rows, payloads

    def _start_local_vector_detail_validation(self, dialog):
        worker = LocalVectorDetailsWorker()
        self._local_vector_detail_worker = worker
        worker.result_ready.connect(
            lambda detail, dlg=dialog: self._finish_local_vector_detail_validation(
                dlg,
                detail,
            )
        )
        worker.error_signal.connect(
            lambda _message, dlg=dialog: self._fail_local_vector_detail_validation(dlg)
        )
        worker.finished.connect(lambda active_worker=worker: self._cleanup_local_vector_detail_worker(active_worker))
        worker.start()

    def _finish_local_vector_detail_validation(self, dialog, detail):
        if dialog is None or not dialog.isVisible():
            return
        rows, payloads = self._build_local_vector_detail_rows(detail)
        dialog.set_rows(rows, payloads)
        dialog.set_summary_text(self.texts["library_vectors_validation_done"])

    def _fail_local_vector_detail_validation(self, dialog):
        if dialog is None or not dialog.isVisible():
            return
        dialog.set_summary_text(self.texts["library_vectors_validation_failed"])

    def _cleanup_local_vector_detail_worker(self, worker):
        if self._local_vector_detail_worker is worker:
            self._local_vector_detail_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    def _local_vector_asset_state_text(self, asset_state):
        state_key = str(asset_state or "").strip().lower() or "ready"
        return self.texts.get(f"library_asset_state_{state_key}", state_key)

    def _local_vector_failure_reason_text(self, reason):
        reason_key = str(reason or "").strip().lower()
        if not reason_key:
            return ""
        return self.texts.get(f"library_sync_failure_reason_{reason_key}", reason_key)

    def _open_vector_detail_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 1
        library_path = str(payload.get("library_path", "")).strip()
        video_rel_path = str(payload.get("video_rel_path", "")).strip()
        video_id = str(payload.get("video_id", "")).strip()
        legacy_npy_file = str(payload.get("legacy_npy_file") or payload.get("vector_file", "")).strip()
        lance_dir = str(payload.get("lance_dir", "")).strip()

        if column == 1:
            if not library_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_folder_in_explorer(library_path)
            dialog.status_hint.setText(library_path)
            return

        if column == 2:
            if not library_path or not video_rel_path:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            video_path = os.path.join(library_path, video_rel_path)
            if os.path.exists(video_path):
                open_in_explorer(video_path)
                dialog.status_hint.setText(video_path)
            else:
                open_folder_in_explorer(library_path)
                dialog.status_hint.setText(video_path)
            return

        if column == 3:
            if not video_id:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            QApplication.clipboard().setText(video_id)
            dialog.status_hint.setText(self.texts["details_copy_done"])
            return

        if column == 4:
            target_dir = lance_dir
            if not target_dir:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_folder_in_explorer(target_dir) if os.path.isdir(target_dir) else open_in_explorer(target_dir)
            dialog.status_hint.setText(target_dir)
            return

        if column == 7:
            lance_bytes = int(payload.get("lance_storage_bytes", 0) or 0)
            legacy_bytes = int(payload.get("legacy_npy_bytes", 0) or 0)
            dialog.status_hint.setText(
                f"Lance {format_byte_size(lance_bytes)} + legacy {format_byte_size(legacy_bytes)}"
            )
            return

        if column == 8:
            if not legacy_npy_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            if os.path.exists(legacy_npy_file):
                open_in_explorer(legacy_npy_file)
            else:
                open_folder_in_explorer(os.path.dirname(legacy_npy_file))
            hint = self.texts.get("library_vectors_legacy_npy_hint", "").format(path=legacy_npy_file)
            dialog.status_hint.setText(hint or legacy_npy_file)

    def _open_selected_vector_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_vector_detail_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_vector_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = (
            payload.get("video_id")
            or payload.get("lance_dir")
            or payload.get("legacy_npy_file")
            or payload.get("vector_file")
            or ""
        )
        QApplication.clipboard().setText(str(target_path))
        dialog.status_hint.setText(self.texts["details_copy_done"])
