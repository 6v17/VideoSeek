"""Video download page controller."""

from __future__ import annotations

import os

from PySide6.QtCore import QObject

from src.app.config import load_config, save_config
from src.services import video_download_errors as vde
from src.services.video_download_service import (
    get_browser_cookie_preflight_reason,
    get_download_cookie_file,
    get_download_default_dir,
    parse_links_from_text,
    resolve_download_output_dir,
)
from ui.threading_utils import shutdown_thread
from ui.workers import VideoDownloadBatchWorker, VideoDownloadProbeWorker


class VideoDownloadController(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.probe_worker = None
        self.download_worker = None
        self._last_probe_results = []
        self._row_for_job: dict[int, int] = {}

    def page(self):
        return self.parent_window.link_page

    def refresh_default_dir_label(self) -> None:
        self.page().set_default_dir_label(get_download_default_dir())

    def load_settings_from_config(self) -> None:
        config = load_config()
        texts = self.parent_window.texts
        self.page().set_download_texts(texts)
        self.page().set_cookie_file_path(get_download_cookie_file(config))
        self.refresh_cookie_admin_hint()

    def refresh_cookie_admin_hint(self) -> None:
        config = load_config()
        config["download_cookie_file"] = self.page().cookie_file_path()
        show_hint = get_browser_cookie_preflight_reason(config=config) is not None
        self.page().set_cookie_admin_hint_visible(show_hint)

    def save_settings_to_config(self) -> None:
        config = load_config()
        config["download_cookie_file"] = self.page().cookie_file_path()
        save_config(config)

    def start_probe(self, raw_text: str) -> None:
        links = parse_links_from_text(raw_text)
        if not links:
            self._notify(self.parent_window.texts.get("download_no_links", ""))
            return
        if self.probe_worker and self.probe_worker.isRunning():
            return
        self.save_settings_to_config()
        page = self.page()
        cookie_path = page.cookie_file_path()
        if cookie_path and not os.path.isfile(cookie_path):
            self._notify(self.parent_window.texts.get("download_cookie_missing", ""))
            return
        page.btn_probe.setEnabled(False)
        page.btn_download.setEnabled(False)
        page.prepare_probe_rows(links)
        self._wire_row_actions()
        self._last_probe_results = []

        self.probe_worker = VideoDownloadProbeWorker(links)
        self.probe_worker.result_ready.connect(self._on_probe_finished)
        self.probe_worker.error_signal.connect(self._on_probe_error)
        self.probe_worker.finished.connect(self._finish_probe)
        self.probe_worker.start()

    def start_download_all(self) -> None:
        page = self.page()
        rows = page.downloadable_rows()
        if not rows:
            self._notify(self.parent_window.texts.get("download_no_ready_rows", ""))
            return
        self._start_download_rows(rows)

    def start_download_row(self, row: int) -> None:
        page = self.page()
        if not page.row_can_download(row):
            return
        self._start_download_rows([int(row)])

    def _start_download_rows(self, rows: list[int]) -> None:
        if self.download_worker and self.download_worker.isRunning():
            return
        page = self.page()
        try:
            resolve_download_output_dir(mode="default_dir")
        except Exception:
            return

        jobs = []
        for row in rows:
            url = page.row_url(row)
            if not url:
                continue
            jobs.append(
                {
                    "row": int(row),
                    "url": url,
                    "quality": page.row_quality(row),
                    "title": page.download_table.item(row, 1).text() if page.download_table.item(row, 1) else url,
                }
            )
        if not jobs:
            return

        self.save_settings_to_config()
        page.btn_probe.setEnabled(False)
        page.btn_download.setEnabled(False)
        for row in rows:
            page.set_row_downloading(row)

        output_dir = resolve_download_output_dir(mode="default_dir")
        self._row_for_job = {index: job["row"] for index, job in enumerate(jobs)}
        self.download_worker = VideoDownloadBatchWorker(jobs, output_dir=output_dir)
        self.download_worker.task_started.connect(self._on_task_started)
        self.download_worker.task_progress.connect(self._on_task_progress)
        self.download_worker.task_finished.connect(self._on_task_finished)
        self.download_worker.batch_finished.connect(self._on_batch_finished)
        self.download_worker.error_signal.connect(self._on_download_error)
        self.download_worker.finished.connect(self._finish_download)
        self.download_worker.start()

    def shutdown(self) -> None:
        shutdown_thread(self.probe_worker)
        shutdown_thread(self.download_worker)
        self.probe_worker = None
        self.download_worker = None

    def reset_after_clear(self) -> None:
        self.shutdown()
        self._last_probe_results = []
        self._row_for_job = {}
        page = self.page()
        page.reset_links_input()
        page.clear_download_list()
        page.reset_action_state()

    def _wire_row_actions(self) -> None:
        page = self.page()
        for row in range(page.download_table.rowCount()):
            btn = page.row_action_button(row)
            if btn is None:
                continue
            try:
                btn.clicked.disconnect()
            except Exception:
                pass
            btn.clicked.connect(lambda _checked=False, r=row: self.start_download_row(r))

    def _notify(self, message: str) -> None:
        if not message:
            return
        self.parent_window.show_info_dialog(
            self.parent_window.texts.get("link_page_title", ""),
            message,
            kind="info",
        )

    def _on_probe_finished(self, results) -> None:
        texts = self.parent_window.texts
        page = self.page()
        self._last_probe_results = list(results or [])
        ready_count = 0
        for row, result in enumerate(self._last_probe_results):
            if result.ok:
                status = texts.get("download_probe_ok", "")
                ready_count += 1
            else:
                key = vde.I18N_KEY_BY_CODE.get(result.reason_code or "", "")
                status = texts.get(key, result.reason_code or texts.get("download_probe_failed", ""))
            title = result.title or result.url
            page.set_row_probe_result(
                row,
                title=title,
                ok=bool(result.ok),
                status=status,
                heights=list(result.video_heights or []),
            )
        self._wire_row_actions()
        page.btn_download.setEnabled(ready_count > 0)

    def _on_probe_error(self, error_text: str) -> None:
        self.parent_window.show_error_dialog(
            self.parent_window.texts.get("download_probe_failed_title", ""),
            error_text,
        )

    def _finish_probe(self) -> None:
        page = self.page()
        page.btn_probe.setEnabled(True)
        page.btn_download.setEnabled(bool(page.downloadable_rows()))

    def _on_task_started(self, index: int, title: str, _url: str) -> None:
        del title

    def _on_task_progress(self, index: int, percent: int, _text: str) -> None:
        row = self._row_for_job.get(index)
        if row is not None:
            self.page().update_row_progress(row, percent)

    def _on_task_finished(self, index: int, result_dict: dict) -> None:
        texts = self.parent_window.texts
        row = self._row_for_job.get(index)
        if row is None:
            return
        ok = bool(result_dict.get("ok"))
        if ok:
            status = texts.get("download_task_done", "")
            path = str(result_dict.get("file_path", "") or "")
        else:
            code = str(result_dict.get("reason_code", "") or "")
            key = vde.I18N_KEY_BY_CODE.get(code, "")
            status = texts.get(key, code or texts.get("download_task_failed", ""))
            path = ""
        self.page().set_row_download_result(row, ok=ok, status=status, path=path)

    def _on_batch_finished(self, summary: dict) -> None:
        del summary

    def _on_download_error(self, error_text: str) -> None:
        self.parent_window.show_error_dialog(
            self.parent_window.texts.get("download_failed_title", ""),
            error_text,
        )

    def _finish_download(self) -> None:
        page = self.page()
        page.btn_probe.setEnabled(True)
        page.btn_download.setEnabled(bool(page.downloadable_rows()))
        self._row_for_job = {}
        refresh = getattr(self.parent_window, "refresh_library_table", None)
        if callable(refresh):
            refresh()
