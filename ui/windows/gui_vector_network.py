"""Local vector details, remote link tables, and link-search page actions — extracted from MainWindow."""

from __future__ import annotations

import os
import re
import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog

from src.app.config import get_data_storage_paths
from src.services.library_service import list_local_vector_details
from src.services.query_text_service import prepare_text_query
from src.services.remote_library_service import list_remote_link_details
from src.services.remote_link_precheck_service import precheck_remote_links
from src.utils import open_folder_in_explorer, open_in_explorer
from ui.dialogs import ResourceTableDialog
from ui.workers import LocalVectorDetailsWorker


class VectorNetworkGuiMixin:
    """Link page search/build/import/export, vector detail dialog, remote link details; mixed into `MainWindow`."""

    def upload_network_file_path(self, path):
        self._set_network_image_query(path)
        self.switch_page("link")

    def start_network_search(self):
        if not self._ensure_startup_migration_idle("feature_network_search"):
            return
        if not self.check_runtime_resources():
            self.link_page.lbl_search_status.setText(self.texts["model_features_disabled"])
            return
        query_text = self.link_page.input_link.text().strip()
        query_data = query_text
        is_text = True
        if query_text:
            query_info = prepare_text_query(query_text)
            if query_info["too_short"]:
                self.link_page.lbl_search_status.setText(self.texts["query_too_short"])
                return
            if query_info["changed"]:
                self.link_page.input_link.setText(query_info["normalized"])
            if query_info["generic"]:
                self.show_info_dialog(
                    self.texts["query_generic_title"],
                    self.texts["query_generic_hint"],
                    kind="info",
                )
            query_data = query_info["normalized"]
        if not query_data:
            query_data = self.network_query_img_path
            is_text = False
        if not query_data:
            self.link_page.lbl_search_status.setText(self.texts["empty_query"])
            return
        self.switch_page("link")
        self.network_search_controller.start_search(query_data, is_text)

    def upload_network_query_image(self):
        path, _ = QFileDialog.getOpenFileName(self, self.texts["select_image"], "", self.texts["image_filter"])
        if not path:
            return
        self._set_network_image_query(path)

    def _set_network_image_query(self, path):
        from src.core.image_io import pixmap_from_image_path

        self.network_query_img_path = path
        pixmap = pixmap_from_image_path(path, 420, 180)
        if not pixmap.isNull():
            self.link_page.query_image_label.setPixmap(pixmap)
        self.link_page.lbl_search_status.setText(self.texts["image_loaded"])

    def start_network_build(self):
        if not self._ensure_startup_migration_idle("feature_network_build"):
            return
        raw_text = self.link_page.build_links_input.toPlainText().strip()
        links = re.findall(r"https?://[^\s,]+", raw_text)
        if not links:
            self.link_page.lbl_build_status.setText(self.texts["network_link_editor_empty"])
            return
        precheck = precheck_remote_links(links)
        accepted_links = precheck.get("accepted_links", [])
        blocked_count = int(precheck.get("blocked_count", 0))
        risky_count = int(precheck.get("risky_count", 0))
        if not accepted_links:
            self.link_page.lbl_build_status.setText(
                f"{self.texts['network_precheck_all_blocked']} "
                f"({self.texts['network_precheck_summary'].format(accepted=0, blocked=blocked_count, risky=risky_count)})"
            )
            return
        mode = str(self.link_page.mode_combo.currentData() or "download")
        if blocked_count > 0 or risky_count > 0:
            self.link_page.lbl_build_status.setText(
                self.texts["network_precheck_summary"].format(
                    accepted=int(precheck.get("accepted_count", 0)),
                    blocked=blocked_count,
                    risky=risky_count,
                )
            )
        self.switch_page("link")
        self.network_search_controller.start_build(accepted_links, mode)

    def import_network_library(self):
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            self.texts["network_import_title"],
            "",
            self.texts["network_zip_filter"],
        )
        if not zip_path:
            return
        self.switch_page("link")
        try:
            self.network_search_controller.import_zip(zip_path)
        except Exception as exc:
            self.show_error_dialog(self.texts["network_import_failed"], exc)

    def export_network_library(self):
        zip_path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts["network_export_title"],
            "remote_library.zip",
            self.texts["network_zip_filter"],
        )
        if not zip_path:
            return
        self.switch_page("link")
        try:
            self.network_search_controller.export_zip(zip_path)
        except Exception as exc:
            self.show_error_dialog(self.texts["network_export_failed"], exc)

    def show_local_vector_details(self):
        try:
            detail = list_local_vector_details(validate_contents=False)
            headers = self.texts["library_vectors_headers"]
            ready_state_text = self._local_vector_asset_state_text("ready")
            rows, payloads = self._build_local_vector_detail_rows(detail)
            subtitle = self.texts["library_vectors_subtitle"].format(
                total=detail["total_entries"],
                vector_dir=detail["vector_dir"],
                index_dir=detail["index_dir"],
            )
            library_summary = self._format_library_search_index_summary(detail.get("library_summaries") or [])
            if library_summary:
                subtitle = (
                    f"{subtitle}\n"
                    f"{self.texts['library_vectors_library_index_line'].format(root=detail.get('library_index_root') or '-', summary=library_summary)}"
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
                export_default_name="local_vector_details.json",
                stretch_column=3,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    1: 220,
                    2: 220,
                    5: 86,
                    6: 86,
                    7: 86,
                    8: 132,
                    9: 200,
                },
                issue_row_predicate=lambda row, ready_text=ready_state_text: row[8] != ready_text,
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
        for index, item in enumerate(detail["entries"], start=1):
            rows.append(
                [
                    index,
                    item["library_path"],
                    item["video_rel_path"],
                    os.path.basename(item["vector_file"]) if item.get("vector_file") else "",
                    os.path.basename(item["index_file"]) if item.get("index_file") else "",
                    self.texts["details_yes"] if item.get("source_exists") else self.texts["details_no"],
                    self.texts["details_yes"] if item["vector_exists"] else self.texts["details_no"],
                    self.texts["details_yes"] if item["index_exists"] else self.texts["details_no"],
                    self._local_vector_asset_state_text(item.get("asset_state", "")),
                    self._local_vector_failure_reason_text(item.get("sync_failure_reason", "")),
                ]
            )
            payloads.append(item)
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

    def _format_library_search_index_summary(self, summaries):
        if not summaries:
            return ""
        status_keys = (
            ("ready", "library_search_index_summary_ready"),
            ("stale", "library_search_index_summary_stale"),
            ("needs_upgrade", "library_search_index_summary_needs_upgrade"),
            ("not_applicable", "library_search_index_summary_not_applicable"),
        )
        parts = []
        for status, text_key in status_keys:
            count = sum(1 for item in summaries if str(item.get("status", "")).strip().lower() == status)
            if count:
                parts.append(self.texts.get(text_key, f"{status} {count}").format(count=count))
        return ", ".join(parts)

    def _open_vector_detail_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 3
        library_path = str(payload.get("library_path", "")).strip()
        video_rel_path = str(payload.get("video_rel_path", "")).strip()
        vector_file = str(payload.get("vector_file", "")).strip()
        index_file = str(payload.get("index_file", "")).strip()

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
            if not vector_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_in_explorer(vector_file) if os.path.exists(vector_file) else open_folder_in_explorer(os.path.dirname(vector_file))
            dialog.status_hint.setText(vector_file)
            return

        if column == 4:
            if not index_file:
                dialog.status_hint.setText(self.texts["details_nothing_selected"])
                return
            open_in_explorer(index_file) if os.path.exists(index_file) else open_folder_in_explorer(os.path.dirname(index_file))
            dialog.status_hint.setText(index_file)

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
        target_path = payload["vector_file"] if payload.get("vector_exists") else payload["index_file"]
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def show_network_link_details(self):
        try:
            detail = list_remote_link_details()
            headers = self.texts["network_links_headers"]
            rows = []
            payloads = []
            for index, item in enumerate(detail["entries"], start=1):
                rows.append(
                    [
                        index,
                        item.get("title", ""),
                        item.get("source_link", "") or item.get("source_id", ""),
                        int(item.get("frames", 0)),
                        f"{float(item.get('min_time', 0.0)):.2f}",
                        f"{float(item.get('max_time', 0.0)):.2f}",
                    ]
                )
                payloads.append(item)
            subtitle = self.texts["network_links_subtitle"].format(
                links=detail["total_links"],
                vectors=detail["total_vectors"],
                vector_file=detail["vector_file"],
            )
            ResourceTableDialog(
                parent=self,
                is_dark=self.is_dark_mode,
                language=self.language,
                title=self.texts["network_links_title"],
                subtitle=subtitle,
                headers=headers,
                rows=rows,
                row_payloads=payloads,
                export_default_name="remote_link_details.json",
                stretch_column=2,
                allow_sorting=False,
                fixed_column_widths={
                    0: 52,
                    3: 86,
                    4: 116,
                    5: 116,
                },
                extra_actions=[
                    {
                        "label": self.texts["details_open_selected_link"],
                        "object_name": "Ghost",
                        "handler": self._open_selected_network_link,
                    },
                    {
                        "label": self.texts["details_copy_selected_link"],
                        "object_name": "Ghost",
                        "handler": self._copy_selected_network_link,
                    },
                ],
                row_double_click_handler=self._open_network_link_payload,
            ).exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["network_links_load_failed"], exc)

    def _open_network_link_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 2
        if column not in {1, 2}:
            return
        link = str(payload.get("source_link", "") or payload.get("source_id", "")).strip()
        if not link:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        webbrowser.open(link)
        dialog.status_hint.setText(link)

    def _open_selected_network_link(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_network_link_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_network_link(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        link = str(selected[0].get("source_link", "") or selected[0].get("source_id", "")).strip()
        if not link:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        QApplication.clipboard().setText(link)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def open_network_download_cache_folder(self):
        storage_paths = get_data_storage_paths()
        cache_dirs = [
            storage_paths["remote_build_cache_dir"],
            storage_paths["link_cache_dir"],
        ]
        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
                open_folder_in_explorer(cache_dir)
                return
        os.makedirs(cache_dirs[0], exist_ok=True)
        open_folder_in_explorer(cache_dirs[0])
