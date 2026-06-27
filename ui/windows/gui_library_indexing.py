"""Media library table, index updates, and index-issue UI — extracted from MainWindow to shrink gui.py."""

from __future__ import annotations

import os

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QApplication, QFileDialog, QGraphicsOpacityEffect, QAbstractItemView

from src.app.config import load_config
from src.app.indexing_progress import format_progress_text
from src.services.indexing_service import list_missing_library_files
from src.services.library_service import (
    GLOBAL_INDEX_STATE_STALE,
    add_library,
    get_global_index_state,
    list_libraries,
    remove_library as remove_library_entry,
)
from src.storage.asset_store import load_model_metadata
from src.workflows.update_video import delete_physical_video_data
from src.utils import open_folder_in_explorer, open_in_explorer
from ui.dialogs import ResourceTableDialog
from ui.views.table_views import populate_library_table


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
            self._refresh_global_index_ui()
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
                status_text = self._with_global_index_notice(self.texts["library_added"])
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
                status_text = self._with_global_index_notice(self.texts["library_removed"])
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

    def rebuild_index_from_vectors(self, target_lib=None):
        if not self._ensure_startup_migration_idle("feature_indexing"):
            return
        if not self.show_confirm_dialog(
            self.texts["rebuild_index_vectors_confirm_title"],
            self.texts["rebuild_index_vectors_confirm_body"],
        ):
            return
        self._start_index_update(
            target_lib=target_lib,
            force_cleanup_missing_files=False,
            rebuild_global_assets=True,
            index_from_vectors_only=True,
        )

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
            if self.indexing_controller.is_running():
                return
            self.library_page.btn_sync_db.setEnabled(False)
            self.library_page.btn_stop_index.setEnabled(True)
            self.library_page.btn_stop_index.setVisible(True)
            self.library_page.btn_add_lib.setEnabled(False)
            self._apply_index_issue_button_state(False)
            self.library_page.btn_cleanup_missing.setEnabled(False)
            self.library_page.btn_rebuild_index_vectors.setEnabled(False)
            if getattr(self, "_debug_tools_enabled", False):
                self.library_page.btn_debug_gpu_oom.setEnabled(False)
                self.library_page.btn_debug_system_oom.setEnabled(False)
            self.library_page.progress_bar.setVisible(True)
            self._last_index_issues = []
            self._last_index_issue_target = target_lib
            self._last_index_from_vectors_only = bool(index_from_vectors_only)
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
        if not self.indexing_controller.is_running():
            return
        if self.indexing_controller.request_stop():
            self.library_page.lbl_status.setText(self.texts["index_stop_requested"])
            self.library_page.btn_stop_index.setEnabled(False)

    def _update_indexing_progress(self, value, text):
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()
        self.library_page.progress_bar.setValue(value)
        self.library_page.lbl_status.setText(format_progress_text(text, self.texts))

    def _finish_indexing(self, success, target_lib, stopped=False, has_search_assets=False, issues=None, rebuild_global_assets=True):
        self.ui_state.set_indexing_running(False)
        self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_stop_index.setEnabled(False)
        self.library_page.btn_stop_index.setVisible(False)
        self.library_page.btn_add_lib.setEnabled(True)
        self.library_page.btn_cleanup_missing.setEnabled(True)
        self.library_page.btn_rebuild_index_vectors.setEnabled(True)
        if getattr(self, "_debug_tools_enabled", False):
            self.library_page.btn_debug_gpu_oom.setEnabled(True)
            self.library_page.btn_debug_system_oom.setEnabled(True)
        self.library_page.progress_bar.setVisible(False)
        self.push_inference_status()
        self.refresh_library_table()
        issue_count = len(issues or [])
        self._last_index_issues = list(issues or [])
        self._last_index_issue_target = target_lib
        self._apply_index_issue_button_state(issue_count > 0)
        if stopped:
            status_text = self.texts["index_stopped"]
        elif success:
            if getattr(self, "_last_index_from_vectors_only", False):
                status_text = (
                    self.texts["index_rebuild_vectors_done_single"]
                    if target_lib
                    else self.texts["index_rebuild_vectors_done"]
                )
            elif has_search_assets:
                status_text = self.texts["index_updated_single"] if target_lib else self.texts["index_updated"]
            else:
                status_text = self.texts["index_updated_empty_single"] if target_lib else self.texts["index_updated_empty"]
            if issue_count:
                status_text = f"{status_text} {self.texts['index_issue_summary'].format(count=issue_count)}"
        else:
            status_text = self.texts["index_failed"]
        if not rebuild_global_assets:
            status_text = self._with_global_index_notice(status_text)
        self.library_page.lbl_status.setText(status_text)
        self._refresh_search_session_hint()
        if hasattr(self, "_refresh_understanding_ui"):
            self._refresh_understanding_ui()
        self._show_index_issue_guidance(issues or [])
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

    def _get_global_index_state(self):
        try:
            return get_global_index_state()
        except Exception:
            return ""

    def _is_global_index_stale(self):
        return self._get_global_index_state() == GLOBAL_INDEX_STATE_STALE

    def _with_global_index_notice(self, status_text):
        base_text = str(status_text or "").strip()
        stale_text = self.texts.get("global_index_stale_status", "").strip()
        if not stale_text or not self._is_global_index_stale():
            return base_text
        if stale_text in base_text:
            return base_text
        if not base_text:
            return stale_text
        return f"{base_text} {stale_text}"

    def _refresh_global_index_ui(self):
        is_stale = self._is_global_index_stale()
        update_button = self.library_page.btn_sync_db
        update_button.setText(self.texts["update_index_pending"] if is_stale else self.texts["update_index"])
        update_button.setToolTip(self.texts["global_index_stale_status"] if is_stale else "")
        if not self.indexing_controller.is_running():
            update_button.setObjectName("WarningButton" if is_stale else "PrimaryButton")
            update_button.style().unpolish(update_button)
            update_button.style().polish(update_button)
            update_button.update()
            current_status = self.library_page.lbl_status.text().strip()
            stale_status = self.texts["global_index_stale_status"]
            if is_stale and current_status in {"", self.texts["ready"], stale_status}:
                self.library_page.lbl_status.setText(stale_status)
            elif not is_stale and current_status == stale_status:
                self.library_page.lbl_status.setText(self.texts["ready"])

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
