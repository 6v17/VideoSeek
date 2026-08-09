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
    list_library_video_entries,
    list_local_vector_details,
    register_library_videos,
)
from src.services.subtitle_library_service import (
    add_subtitle_library,
    list_subtitle_libraries,
    list_subtitle_library_video_entries,
    register_subtitle_library_videos,
)
from src.storage.asset_store import load_model_metadata
from src.storage.lance_store import format_byte_size
from src.utils import open_folder_in_explorer, open_in_explorer
from ui.dialogs import ResourceTableDialog
from ui.workers import LocalVectorDetailsWorker


class LibraryIndexingGuiMixin:
    """Library paths, index runs, progress, and index-issue dialogs; mixed into `MainWindow`."""

    def _ensure_library_tree_hooks(self):
        if getattr(self, "_library_tree_hooks_ready", False):
            return
        visual = self.library_page.visual_video_tree
        subtitle = self.library_page.subtitle_video_tree
        visual.open_library_requested.connect(self.open_library_folder)
        subtitle.open_library_requested.connect(self.open_library_folder)
        visual.selection_changed.connect(self._refresh_remove_library_button)
        subtitle.selection_changed.connect(self._refresh_remove_library_button)
        self._library_tree_hooks_ready = True

    def _asset_state_label(self, asset_state: str) -> str:
        state = str(asset_state or "").strip().lower() or "missing_asset"
        key = f"library_asset_state_{state}"
        return self.texts.get(key, state)

    def _build_visual_tree_entries(self, *, register: bool = False) -> tuple[list[dict], list[str]]:
        from src.services.team_mode_service import is_team_client_mode

        if is_team_client_mode():
            from src.app.config import load_config
            from src.services.team_client_search import list_team_client_library_tree

            cfg = load_config()
            entries, library_paths = list_team_client_library_tree(
                str(cfg.get("team_server_url") or ""),
                api_port_default=int(cfg.get("team_api_port", 8765) or 8765),
            )
            rows = []
            for item in entries:
                state = str(item.get("asset_state") or "ready").strip().lower() or "ready"
                rows.append(
                    {
                        **item,
                        "status_text": self._asset_state_label(state),
                        "status_tone": "ready" if state == "ready" else "pending",
                    }
                )
            return rows, library_paths

        libraries = list_libraries()
        # Avoid hashing/walking the whole tree on every UI refresh (10k+ videos).
        entries = list_library_video_entries(register=register)
        rows = []
        for item in entries:
            state = str(item.get("asset_state") or "").strip().lower()
            ready = state == "ready"
            rows.append(
                {
                    **item,
                    "status_text": self._asset_state_label(state),
                    "status_tone": "ready" if ready else "pending",
                }
            )
        return rows, list(libraries.keys())

    def _build_subtitle_tree_entries(self, *, register: bool = False) -> tuple[list[dict], list[str]]:
        from src.services.team_mode_service import is_team_client_mode
        from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

        if is_team_client_mode():
            from src.app.config import load_config
            from src.services.team_client_search import list_team_client_subtitle_library_tree

            cfg = load_config()
            entries, library_paths = list_team_client_subtitle_library_tree(
                str(cfg.get("team_server_url") or ""),
                api_port_default=int(cfg.get("team_api_port", 8765) or 8765),
            )
            rows = []
            for item in entries:
                has_transcript = bool(item.get("has_transcript"))
                segment_count = int(item.get("segment_count") or 0)
                if has_transcript:
                    status = self.texts.get(
                        "dialogue_library_row_meta",
                        "{segments} cues",
                    ).format(segments=segment_count if segment_count else "✓")
                else:
                    status = self.texts.get("subtitle_library_status_missing", "Not extracted")
                rows.append(
                    {
                        **item,
                        "has_transcript": has_transcript,
                        "segment_count": segment_count,
                        "status_text": status,
                        "status_tone": "ready" if has_transcript else "pending",
                    }
                )
            return rows, library_paths

        # Global subtitle registry — independent of the active CLIP profile.
        libraries = list_subtitle_libraries()
        entries = list_subtitle_library_video_entries(register=register)
        # Recover empty shells (library folder exists but file rows were never scanned).
        if not entries and libraries and not register:
            try:
                register_subtitle_library_videos()
            except Exception:
                pass
            entries = list_subtitle_library_video_entries(register=False)
            libraries = list_subtitle_libraries()
        transcript_by_id = {
            str(row.get("video_id") or "").strip(): row
            for row in list_dialogue_transcript_summaries()
            if str(row.get("video_id") or "").strip()
        }
        rows = []
        for item in entries:
            video_id = str(item.get("video_id") or "").strip()
            record = transcript_by_id.get(video_id) or {}
            segment_count = int(record.get("segment_count") or 0)
            has_transcript = bool(record)
            if has_transcript:
                status = self.texts.get(
                    "dialogue_library_row_meta",
                    "{segments} cues",
                ).format(segments=segment_count)
            else:
                status = self.texts.get("subtitle_library_status_missing", "Not extracted")
            rows.append(
                {
                    **item,
                    "has_transcript": has_transcript,
                    "segment_count": segment_count,
                    "status_text": status,
                    "status_tone": "ready" if has_transcript else "pending",
                }
            )
        return rows, list(libraries.keys())

    def apply_team_client_library_payload(self, payload=None) -> None:
        """Apply prefetched shared visual/subtitle trees after a team-client connect."""
        from src.services.team_mode_service import is_team_client_mode

        payload = payload or {}
        if not is_team_client_mode():
            self.refresh_library_table()
            self.refresh_dialogue_library_table()
            return
        try:
            self._ensure_library_tree_hooks()
            open_text = self.texts.get("open_folder", self.texts.get("open", "Open"))
            empty_text = self.texts.get("library_list_empty", "No library folders yet.")
            status_template = self.texts.get("library_sync_status", "{ready}/{total} synced")
            tree = self.library_page.visual_video_tree
            tree.set_action_texts(
                open_text=open_text,
                empty_text=empty_text,
                status_template=status_template,
                header_video=self.texts.get(
                    "library_col_video", self.texts.get("search_scope_video_col", "Video")
                ),
                header_count=self.texts.get("library_col_count", "Count"),
                header_status=self.texts.get("library_col_status", "Status"),
                header_action=self.texts.get("library_col_action", "Action"),
            )
            visual_entries = list(payload.get("visual_entries") or [])
            visual_paths = list(payload.get("visual_library_paths") or [])
            rows = []
            for item in visual_entries:
                state = str(item.get("asset_state") or "ready").strip().lower() or "ready"
                rows.append(
                    {
                        **item,
                        "status_text": self._asset_state_label(state),
                        "status_tone": "ready" if state == "ready" else "pending",
                    }
                )
            tree.refresh_from_entries(rows, library_paths=visual_paths)
            self._refresh_library_action_hints()
            self._refresh_team_client_library_chrome()
            self._refresh_remove_library_button()
            if hasattr(self, "invalidate_search_scope_entries_cache"):
                self.invalidate_search_scope_entries_cache()
            if hasattr(self, "_refresh_search_scope_ui"):
                self._refresh_search_scope_ui(force_entries=True)

            subtitle_entries = list(payload.get("subtitle_entries") or [])
            subtitle_paths = list(payload.get("subtitle_library_paths") or [])
            empty_sub = self.texts.get(
                "dialogue_library_empty",
                "No subtitles yet. Add a video library, then Extract subtitles.",
            )
            status_sub = self.texts.get("library_extract_status", "{ready}/{total} extracted")
            sub_tree = self.library_page.subtitle_video_tree
            sub_tree.set_action_texts(
                open_text=open_text,
                empty_text=empty_sub,
                status_template=status_sub,
                header_video=self.texts.get(
                    "library_col_video", self.texts.get("search_scope_video_col", "Video")
                ),
                header_count=self.texts.get("library_col_count", "Count"),
                header_status=self.texts.get("library_col_status", "Status"),
                header_action=self.texts.get("library_col_action", "Action"),
            )
            sub_rows = []
            for item in subtitle_entries:
                has_transcript = bool(item.get("has_transcript"))
                segment_count = int(item.get("segment_count") or 0)
                if has_transcript:
                    status = self.texts.get(
                        "dialogue_library_row_meta",
                        "{segments} cues",
                    ).format(segments=segment_count if segment_count else "✓")
                else:
                    status = self.texts.get("subtitle_library_status_missing", "Not extracted")
                sub_rows.append(
                    {
                        **item,
                        "source_exists": True,
                        "has_transcript": has_transcript,
                        "segment_count": segment_count,
                        "status_text": status,
                        "status_tone": "ready" if has_transcript else "pending",
                    }
                )
            sub_tree.refresh_from_entries(sub_rows, library_paths=subtitle_paths)
            if hasattr(self, "invalidate_dialogue_search_scope_entries_cache"):
                self.invalidate_dialogue_search_scope_entries_cache()
            if hasattr(self, "_refresh_search_scope_ui") and hasattr(self, "_search_scope_is_dialogue"):
                try:
                    if self._search_scope_is_dialogue():
                        self._refresh_search_scope_ui(force_entries=True)
                except Exception:
                    pass
        except Exception as exc:
            self.show_error_dialog(self.texts.get("library_load_failed", "Library load failed"), exc)

    def _is_subtitle_library_mode(self) -> bool:
        return int(self.library_page.library_mode()) == 1

    def _refresh_library_action_hints(self):
        btn = getattr(self.library_page, "btn_remove_lib", None)
        if btn is None:
            return
        if self._is_subtitle_library_mode():
            btn.setToolTip(
                self.texts.get(
                    "remove_subtitle_library_hint",
                    self.texts.get("remove_library_hint", ""),
                )
            )
        else:
            btn.setToolTip(
                self.texts.get(
                    "remove_visual_library_hint",
                    self.texts.get("remove_library_hint", ""),
                )
            )

    def _active_library_tree(self):
        page = self.library_page
        if int(page.library_mode()) == 1:
            return page.subtitle_video_tree
        return page.visual_video_tree

    def _refresh_remove_library_button(self):
        btn = getattr(self.library_page, "btn_remove_lib", None)
        if btn is None:
            return
        if (
            getattr(self, "_remove_library_running", False)
            or self._remove_library_worker_running()
            or self.indexing_controller.is_running()
            or self._dialogue_index_running()
        ):
            btn.setEnabled(False)
            return
        tree = self._active_library_tree()
        btn.setEnabled(bool(tree.collect_checked_library_paths()))

    def refresh_library_table(self):
        from src.services.team_mode_service import is_team_client_mode

        tree = None
        try:
            self._ensure_library_tree_hooks()
            open_text = self.texts.get("open_folder", self.texts.get("open", "Open"))
            empty_text = self.texts.get("library_list_empty", "No library folders yet.")
            status_template = self.texts.get("library_sync_status", "{ready}/{total} synced")
            tree = self.library_page.visual_video_tree
            tree.set_action_texts(
                open_text=open_text,
                empty_text=empty_text,
                status_template=status_template,
                header_video=self.texts.get(
                    "library_col_video", self.texts.get("search_scope_video_col", "Video")
                ),
                header_count=self.texts.get("library_col_count", "Count"),
                header_status=self.texts.get("library_col_status", "Status"),
                header_action=self.texts.get("library_col_action", "Action"),
            )
            # Drop stale local rows before remote fetch when switching to 用户机.
            if is_team_client_mode():
                tree.refresh_from_entries([], library_paths=[])
            entries, library_paths = self._build_visual_tree_entries(register=False)
            tree.refresh_from_entries(entries, library_paths=library_paths)
            self._refresh_library_action_hints()
            self._refresh_team_client_library_chrome()
            self._refresh_remove_library_button()
            if hasattr(self, "invalidate_search_scope_entries_cache"):
                self.invalidate_search_scope_entries_cache()
            if hasattr(self, "_refresh_search_scope_ui"):
                self._refresh_search_scope_ui(force_entries=True)
            if hasattr(self, "_refresh_understanding_scope_options"):
                self._refresh_understanding_scope_options()
        except Exception as exc:
            # Never keep the previous local tree visible under client mode.
            if tree is not None and is_team_client_mode():
                try:
                    tree.refresh_from_entries([], library_paths=[])
                    self._refresh_team_client_library_chrome()
                except Exception:
                    pass
            self.show_error_dialog(self.texts["library_load_failed"], exc)
            return

    def _refresh_team_client_library_chrome(self) -> None:
        """Hide local indexing / mutate actions when browsing a shared team library."""
        from src.services.team_mode_service import is_team_client_mode

        client = is_team_client_mode()
        page = self.library_page
        debug_enabled = bool(getattr(self, "_debug_tools_enabled", False))
        visual_indexing = False
        dialogue_indexing = False
        try:
            visual_indexing = bool(self.indexing_controller.is_running())
        except Exception:
            visual_indexing = False
        try:
            dialogue_indexing = bool(self._dialogue_index_running())
        except Exception:
            dialogue_indexing = False

        visibility = {
            "btn_add_lib": not client,
            "btn_remove_lib": not client,
            "btn_sync_db": not client,
            "btn_refresh_visual_library": not client,
            "btn_index_issues": not client,
            "btn_cleanup_missing": not client,
            "btn_vector_details": not client,
            "btn_build_dialogue_index": not client,
            "btn_reembed_dialogue": not client,
            "btn_clear_dialogue": not client,
            "btn_export_dialogue": not client,
            "btn_refresh_dialogue_library": not client,
            "input_subtitle_sample_interval": not client,
            "input_subtitle_ocr_batch": not client,
            "lbl_subtitle_sample_interval": not client,
            "lbl_subtitle_ocr_batch": not client,
            # Stop / debug must never be force-shown just because we left client mode.
            "btn_stop_index": (not client) and visual_indexing,
            "btn_stop_dialogue_index": (not client) and dialogue_indexing,
            "btn_debug_gpu_oom": (not client) and debug_enabled,
            "btn_debug_system_oom": (not client) and debug_enabled,
        }
        for name, visible in visibility.items():
            widget = getattr(page, name, None)
            if widget is not None:
                widget.setVisible(bool(visible))
        # Subtitle tab stays available on 用户机 (read-only shared view).
        if getattr(page, "btn_tab_dialogue", None) is not None:
            page.btn_tab_dialogue.setEnabled(True)
        hint = getattr(page, "lbl_shared_library_hint", None)
        if hint is None:
            return
        if client:
            hint.setText(
                self.texts.get(
                    "library_team_shared_hint",
                    "用户机：显示服务机共享库与字幕库（只读）。索引请在服务机完成；可用范围搜索限定片源。",
                )
            )
        else:
            hint.setText(
                self.texts.get(
                    "library_shared_add_hint",
                    "Add a folder once; then sync visuals or extract subtitles from the tabs below.",
                )
            )

    def refresh_selected_visual_libraries(self):
        """Rescan checked libraries so newly dropped files appear in the tree."""
        from src.services.team_mode_service import is_team_client_mode
        from src.services.library_service import register_library_videos

        if is_team_client_mode():
            self.show_info_dialog(
                self.texts.get("info_title", self.texts.get("success_title", "Info")),
                self.texts.get(
                    "library_team_readonly",
                    "用户机为只读：不能添加库或建索引，请在服务机操作。",
                ),
                kind="warning",
            )
            return
        if self.indexing_controller.is_running() or self._dialogue_index_running():
            self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
            return

        paths = self.library_page.visual_video_tree.collect_checked_library_paths()
        if not paths:
            self.show_info_dialog(
                self.texts.get("refresh_visual_library", "刷新选中库"),
                self.texts.get("library_select_libraries_first", "请先勾选一个或多个视频库。"),
                kind="info",
            )
            return

        registered = 0
        try:
            for path in paths:
                result = register_library_videos(library_path=path)
                registered += int(result.get("registered") or 0)
        except Exception as exc:
            self.show_error_dialog(self.texts.get("library_load_failed", "Failed"), exc)
            return

        self.refresh_library_table()
        message = self.texts.get(
            "refresh_visual_library_done",
            "已刷新 {libraries} 个库：新登记 {registered} 个视频。",
        ).format(libraries=len(paths), registered=registered)
        self.library_page.lbl_status.setText(message)
        self.show_info_dialog(
            self.texts.get("success_title", "Success"),
            message,
            kind="success",
        )

    def sync_library(self, path):
        from src.services.team_mode_service import is_team_client_mode
        from src.services.library_service import register_library_videos

        if is_team_client_mode():
            return
        # Full-library sync: discover newly dropped files first, then scan the
        # whole folder. Passing only already-registered video_ids skips anything
        # added after the library was first created.
        try:
            register_library_videos(library_path=path)
        except Exception:
            pass
        self.start_update_index(
            target_lib=path,
            rebuild_global_assets=False,
            video_ids=None,
        )

    def open_library_folder(self, path):
        from src.services.team_mode_service import is_team_client_mode

        if is_team_client_mode():
            # Shared mode: open the library folder via nginx autoindex in the browser.
            if hasattr(self, "_open_team_result_in_browser"):
                self._open_team_result_in_browser(path)
            else:
                self.show_info_dialog(
                    self.texts.get("info_title", self.texts.get("success_title", "Info")),
                    self.texts.get(
                        "library_team_open_remote_hint",
                        "共享库文件在服务机上，用户机无法直接打开本地文件夹。请用搜索结果预览播放。",
                    ),
                    kind="info",
                )
            return
        open_folder_in_explorer(path)

    def select_video_folder(self):
        from src.services.team_mode_service import is_team_client_mode

        if is_team_client_mode():
            self.show_info_dialog(
                self.texts.get("info_title", self.texts.get("success_title", "Info")),
                self.texts.get(
                    "library_team_readonly",
                    "用户机不能添加本地库。请在服务机添加并索引。",
                ),
                kind="warning",
            )
            return
        path = QFileDialog.getExistingDirectory(self, self.texts["select_folder"])
        if not path:
            return
        subtitle_mode = self._is_subtitle_library_mode()
        try:
            if subtitle_mode:
                result = add_subtitle_library(path)
            else:
                result = add_library(path)
            if result.get("added"):
                try:
                    if subtitle_mode:
                        register_subtitle_library_videos(
                            library_path=result.get("path") or path
                        )
                    else:
                        register_library_videos(library_path=result.get("path") or path)
                except Exception:
                    pass
                if subtitle_mode:
                    self.refresh_dialogue_library_table()
                else:
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

    def remove_selected_libraries(self):
        tree = self._active_library_tree()
        paths = tree.collect_checked_library_paths()
        if not paths:
            self._refresh_remove_library_button()
            return
        self.remove_library_entry(paths)

    def remove_library_entry(self, path):
        if getattr(self, "_remove_library_running", False) or self._remove_library_worker_running():
            self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
            return
        if self.indexing_controller.is_running() or self._dialogue_index_running():
            self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
            return
        if isinstance(path, (list, tuple, set)):
            paths = [str(p or "").strip() for p in path if str(p or "").strip()]
        else:
            paths = [str(path or "").strip()] if str(path or "").strip() else []
        if not paths:
            return
        subtitle_mode = self._is_subtitle_library_mode()
        if subtitle_mode:
            single_key = "remove_subtitle_library_confirm"
            multi_key = "remove_subtitle_libraries_confirm"
            single_default = "Remove this subtitle library and its OCR data?\n{path}"
            multi_default = (
                "Remove {count} selected subtitle libraries and their OCR data?\n\n{paths}"
            )
        else:
            single_key = "remove_visual_library_confirm"
            multi_key = "remove_visual_libraries_confirm"
            single_default = (
                "Remove this visual library and its CLIP index from the current model?\n{path}"
            )
            multi_default = (
                "Remove {count} selected visual libraries and their CLIP indexes "
                "from the current model?\n\n{paths}"
            )
        if len(paths) == 1:
            confirm = self.texts.get(single_key, single_default).format(path=paths[0])
        else:
            confirm = self.texts.get(multi_key, multi_default).format(
                count=len(paths), paths="\n".join(paths)
            )
        if not self.show_confirm_dialog(self.texts["confirm_title"], confirm):
            return

        from ui.workers import RemoveLibraryWorker

        self._remove_library_running = True
        self._remove_library_mode = "subtitle" if subtitle_mode else "visual"
        self.library_page.btn_sync_db.setEnabled(False)
        self.library_page.btn_refresh_visual_library.setEnabled(False)
        self.library_page.btn_build_dialogue_index.setEnabled(False)
        self.library_page.btn_reembed_dialogue.setEnabled(False)
        self.library_page.btn_clear_dialogue.setEnabled(False)
        self.library_page.btn_export_dialogue.setEnabled(False)
        self.library_page.btn_refresh_dialogue_library.setEnabled(False)
        self.library_page.input_subtitle_sample_interval.setEnabled(False)
        self.library_page.input_subtitle_ocr_batch.setEnabled(False)
        self.library_page.btn_add_lib.setEnabled(False)
        self.library_page.btn_remove_lib.setEnabled(False)
        self.library_page.btn_cleanup_missing.setEnabled(False)
        self.library_page.progress_bar.setVisible(True)
        self.library_page.progress_bar.setValue(0)
        self.library_page.lbl_status.setText(
            self.texts.get("library_removing", "Removing library...")
        )

        worker = RemoveLibraryWorker(
            paths,
            mode="subtitle" if subtitle_mode else "visual",
        )
        self.remove_library_worker = worker
        worker.progress_signal.connect(self._update_remove_library_progress)
        worker.error_signal.connect(self._handle_remove_library_error)
        worker.finished_signal.connect(self._finish_remove_library)
        worker.finished.connect(lambda w=worker: self._cleanup_remove_library_worker(w))
        worker.start()

    def _remove_library_worker_running(self) -> bool:
        worker = getattr(self, "remove_library_worker", None)
        return bool(worker is not None and worker.isRunning())

    def _cleanup_remove_library_worker(self, worker) -> None:
        if getattr(self, "remove_library_worker", None) is worker:
            self.remove_library_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    def _update_remove_library_progress(self, value, text):
        self.library_page.progress_bar.setValue(int(value))
        raw = str(text or "")
        if raw.startswith("remove_library|"):
            parts = raw.split("|")
            if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
                self.library_page.lbl_status.setText(
                    self.texts.get(
                        "library_removing_progress",
                        "Removing library {current}/{total}...",
                    ).format(current=parts[1], total=parts[2])
                )
                return
            stage = parts[1] if len(parts) > 1 else ""
            if stage == "compact":
                self.library_page.lbl_status.setText(
                    self.texts.get("library_removing_compact", "Compacting index storage...")
                )
                return
            if stage == "transcripts":
                self.library_page.lbl_status.setText(
                    self.texts.get("library_removing_transcripts", "Cleaning subtitle data...")
                )
                return
        self.library_page.lbl_status.setText(
            self.texts.get("library_removing", "Removing library...")
        )

    def _handle_remove_library_error(self, message):
        self.show_error_dialog(self.texts["library_remove_failed"], message)

    def _finish_remove_library(self, success):
        try:
            self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_refresh_visual_library.setEnabled(True)
            self.library_page.btn_build_dialogue_index.setEnabled(True)
            self.library_page.btn_reembed_dialogue.setEnabled(True)
            self.library_page.btn_clear_dialogue.setEnabled(True)
            self.library_page.btn_export_dialogue.setEnabled(True)
            self.library_page.btn_refresh_dialogue_library.setEnabled(True)
            self.library_page.input_subtitle_sample_interval.setEnabled(True)
            self.library_page.input_subtitle_ocr_batch.setEnabled(True)
            self.library_page.btn_add_lib.setEnabled(True)
            self.library_page.btn_cleanup_missing.setEnabled(True)
            self.library_page.progress_bar.setVisible(False)
            if success:
                # Defer tree rebuilds so the finished signal returns quickly.
                from PySide6.QtCore import QTimer

                mode = str(getattr(self, "_remove_library_mode", "visual") or "visual")
                if mode == "subtitle":
                    QTimer.singleShot(0, self.refresh_dialogue_library_table)
                else:
                    QTimer.singleShot(0, self.refresh_library_table)
                status_text = self.texts["library_removed"]
                self.library_page.lbl_status.setText(status_text)
                self.show_info_dialog(self.texts["success_title"], status_text, kind="success")
            else:
                self.library_page.lbl_status.setText(self.texts["library_remove_failed"])
        finally:
            self._remove_library_running = False
            self._remove_library_mode = ""
            self._refresh_remove_library_button()

    def start_update_index(
        self,
        target_lib=None,
        rebuild_global_assets=True,
        video_ids=None,
        *,
        checked_only: bool = False,
    ):
        from src.services.team_mode_service import is_team_client_mode

        if is_team_client_mode():
            self.show_info_dialog(
                self.texts.get("info_title", self.texts.get("success_title", "Info")),
                self.texts.get(
                    "library_team_readonly",
                    "用户机不能添加本地库。请在服务机添加并索引。",
                ),
                kind="warning",
            )
            return
        if not self._ensure_startup_migration_idle("feature_indexing"):
            return
        selected_ids = video_ids
        if checked_only:
            selected_ids = self.library_page.visual_video_tree.collect_checked_video_ids()
            if not selected_ids:
                self.show_info_dialog(
                    self.texts.get("sync_selected_videos", self.texts.get("update_index", "Sync")),
                    self.texts.get("library_select_videos_first", "Select one or more videos first."),
                    kind="info",
                )
                return
        self._start_index_update(
            target_lib=target_lib,
            force_cleanup_missing_files=False,
            rebuild_global_assets=rebuild_global_assets,
            video_ids=selected_ids,
        )

    def start_dialogue_index(self):
        self._start_dialogue_index_job(mode="auto")

    def start_dialogue_reembed(self):
        # Force OCR rebuild (button label: re-extract subtitles).
        self._start_dialogue_index_job(mode="ocr")

    def clear_selected_dialogue_transcripts(self):
        from src.services.subtitle_library_service import clear_subtitle_transcripts
        from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

        title = self.texts.get("clear_dialogue_index", "Clear selected subtitles")
        if self._dialogue_index_running() or self._remove_library_worker_running():
            self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
            return

        selected_ids = [
            str(vid).strip()
            for vid in self.library_page.subtitle_video_tree.collect_checked_video_ids()
            if str(vid).strip()
        ]
        if not selected_ids:
            self.show_info_dialog(
                title,
                self.texts.get("library_select_videos_first", "Select one or more videos first."),
                kind="info",
            )
            return

        existing = list_dialogue_transcript_summaries(video_ids=selected_ids)
        if not existing:
            self.show_info_dialog(
                title,
                self.texts.get(
                    "clear_dialogue_index_no_targets",
                    "None of the checked videos have subtitles to clear.",
                ),
                kind="info",
            )
            return

        confirm = self.texts.get(
            "clear_dialogue_index_confirm",
            "Clear OCR subtitle data for {count} checked videos?",
        ).format(count=len(existing))
        if not self.show_confirm_dialog(self.texts.get("confirm_title", "Confirm"), confirm):
            return

        try:
            result = clear_subtitle_transcripts([row["video_id"] for row in existing])
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("clear_dialogue_index_failed", "Failed to clear subtitles"),
                str(exc).strip() or repr(exc),
            )
            return

        self.refresh_dialogue_library_table()
        self.library_page.lbl_status.setText(
            self.texts.get(
                "clear_dialogue_index_done",
                "Cleared subtitles for {cleared} video(s) (requested {requested}).",
            ).format(
                cleared=int(result.get("cleared_count") or 0),
                requested=int(result.get("requested_count") or 0),
            )
        )

    def load_subtitle_sample_interval(self):
        from src.app.config import DEFAULT_CONFIG, load_config

        try:
            config = load_config()
            value = float(
                config.get(
                    "subtitle_sample_interval_sec",
                    DEFAULT_CONFIG["subtitle_sample_interval_sec"],
                )
            )
        except Exception:
            value = float(DEFAULT_CONFIG["subtitle_sample_interval_sec"])
        value = max(0.1, min(6.0, value))
        spin = self.library_page.input_subtitle_sample_interval
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)

    def _read_subtitle_sample_interval(self) -> float:
        from src.app.config import load_config, save_config

        spin = self.library_page.input_subtitle_sample_interval
        value = max(0.1, min(6.0, float(spin.value())))
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)
        try:
            config = load_config()
            previous = config.get("subtitle_sample_interval_sec")
            if previous is None or abs(float(previous) - value) > 1e-6:
                config["subtitle_sample_interval_sec"] = value
                save_config(config)
        except Exception:
            pass
        return value

    def _on_subtitle_sample_interval_changed(self, _value=None):
        self._read_subtitle_sample_interval()

    def load_subtitle_ocr_batch(self):
        from src.app.config import DEFAULT_CONFIG, load_config

        try:
            config = load_config()
            value = int(
                config.get(
                    "subtitle_ocr_batch_size",
                    DEFAULT_CONFIG["subtitle_ocr_batch_size"],
                )
            )
        except Exception:
            value = int(DEFAULT_CONFIG["subtitle_ocr_batch_size"])
        value = max(1, min(6, value))
        spin = self.library_page.input_subtitle_ocr_batch
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)

    def _read_subtitle_ocr_batch(self) -> int:
        from src.app.config import load_config, save_config

        spin = self.library_page.input_subtitle_ocr_batch
        value = max(1, min(6, int(spin.value())))
        spin.blockSignals(True)
        spin.setValue(value)
        spin.blockSignals(False)
        try:
            config = load_config()
            previous = config.get("subtitle_ocr_batch_size")
            if previous is None or int(previous) != value:
                config["subtitle_ocr_batch_size"] = value
                save_config(config)
        except Exception:
            pass
        return value

    def _on_subtitle_ocr_batch_changed(self, _value=None):
        self._read_subtitle_ocr_batch()

    def _on_library_tab_changed(self, index: int):
        self._refresh_library_action_hints()
        if int(index) == 1:
            self.refresh_dialogue_library_table()
        else:
            self._refresh_remove_library_button()

    def refresh_dialogue_library_table(self):
        from src.services.team_mode_service import is_team_client_mode

        try:
            if not is_team_client_mode():
                from src.services.subtitle_library_service import prune_missing_subtitle_sources

                try:
                    # Never auto-delete OCR here. Offline/removable drives must not wipe transcripts.
                    prune_missing_subtitle_sources(clear_orphan_transcripts=False)
                except Exception:
                    pass
            self._ensure_library_tree_hooks()
            open_text = self.texts.get("open_folder", self.texts.get("open", "Open"))
            empty_text = self.texts.get(
                "dialogue_library_empty",
                "No subtitles yet. Add a video library, then Extract subtitles.",
            )
            status_template = self.texts.get("library_extract_status", "{ready}/{total} extracted")
            tree = self.library_page.subtitle_video_tree
            tree.set_action_texts(
                open_text=open_text,
                empty_text=empty_text,
                status_template=status_template,
                header_video=self.texts.get(
                    "library_col_video", self.texts.get("search_scope_video_col", "Video")
                ),
                header_count=self.texts.get("library_col_count", "Count"),
                header_status=self.texts.get("library_col_status", "Status"),
                header_action=self.texts.get("library_col_action", "Action"),
            )
            if is_team_client_mode():
                tree.refresh_from_entries([], library_paths=[])
            entries, library_paths = self._build_subtitle_tree_entries(register=False)
            tree.refresh_from_entries(entries, library_paths=library_paths)
            self._refresh_team_client_library_chrome()
            self._refresh_remove_library_button()
            if hasattr(self, "invalidate_dialogue_search_scope_entries_cache"):
                self.invalidate_dialogue_search_scope_entries_cache()
            if hasattr(self, "_refresh_search_scope_ui") and hasattr(self, "_search_scope_is_dialogue"):
                try:
                    if self._search_scope_is_dialogue():
                        self._refresh_search_scope_ui(force_entries=True)
                except Exception:
                    pass
        except Exception as exc:
            if is_team_client_mode():
                try:
                    self.library_page.subtitle_video_tree.refresh_from_entries([], library_paths=[])
                    self._refresh_team_client_library_chrome()
                except Exception:
                    pass
            self.show_error_dialog(self.texts.get("library_load_failed", "Library load failed"), exc)

    def export_dialogue_library(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        from src.services.dialogue_export_service import export_dialogue_transcripts
        from src.storage.dialogue_transcript_store import list_dialogue_transcript_summaries

        title = self.texts.get("export_dialogue_library_title", "Export dialogue")
        selected_ids = [
            str(vid).strip()
            for vid in self.library_page.subtitle_video_tree.collect_checked_video_ids()
            if str(vid).strip()
        ]
        if not selected_ids:
            self.show_info_dialog(
                title,
                self.texts.get("library_select_videos_first", "Select one or more videos first."),
                kind="info",
            )
            return

        # Metadata only — do not parse full segment payloads for the empty check.
        if not list_dialogue_transcript_summaries(video_ids=selected_ids):
            self.show_info_dialog(
                title,
                self.texts.get("export_dialogue_library_empty", "No shared dialogue to export."),
                kind="info",
            )
            return

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
            video_ids=selected_ids,
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
        if token.startswith("dialogue_embed|") or token.startswith("subtitle_ocr|"):
            parts = token.split("|")
            if len(parts) >= 3:
                detail = f"{parts[1]}/{parts[2]}"
            head = "dialogue_embed" if token.startswith("dialogue_embed|") else "subtitle_ocr"
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
            "subtitle_ocr": "dialogue_stage_ocr",
            "subtitle_merge": "dialogue_stage_merge",
            "subtitle_reuse": "dialogue_stage_reuse",
            "subtitle_done": "dialogue_stage_done",
        }
        key = mapping.get(head, "")
        if not key:
            return token
        template = self.texts.get(key, token)
        try:
            return template.format(detail=detail or "…")
        except Exception:
            return template

    def _start_dialogue_index_job(self, *, mode: str = "auto"):
        if not self._ensure_startup_migration_idle("feature_indexing"):
            return
        title_key = "build_dialogue_index"
        mode_value = str(mode or "auto").strip().lower() or "auto"
        reembed = mode_value == "reembed"
        if reembed:
            title_key = "reembed_dialogue_index"
        elif mode_value == "ocr":
            title_key = "build_dialogue_index"
        title = self.texts.get(title_key, title_key)

        if (
            self.indexing_controller.is_running()
            or self._dialogue_index_running()
            or self._remove_library_worker_running()
        ):
            message = self.texts.get("index_already_running", "An indexing job is already running.")
            self.library_page.lbl_status.setText(message)
            self.show_info_dialog(title, message, kind="warning")
            return

        # Subtitle OCR needs FFmpeg + RapidOCR, not CLIP visual models.
        from src.utils import has_ffmpeg

        if not has_ffmpeg():
            message = self.texts.get(
                "build_dialogue_index_missing_ffmpeg",
                "FFmpeg is required for subtitle extraction. Configure it in Settings.",
            )
            self.library_page.lbl_status.setText(message)
            self.show_info_dialog(title, message, kind="warning")
            return

        try:
            self._run_dialogue_index_job(mode=mode_value, title=title, reembed=reembed)
        except Exception as exc:
            from src.app.logging_utils import get_logger

            get_logger("gui").exception("Subtitle extract UI failed before worker start")
            self.show_error_dialog(
                self.texts.get("build_dialogue_index_failed", "Dialogue index failed"),
                str(exc).strip() or repr(exc),
            )

    def _resolve_dialogue_index_targets(self, selected_ids: set[str]) -> list[dict]:
        """Build extract targets from the tree / registry without rescanning disks."""
        import os

        from src.services.dialogue_index_service import list_dialogue_index_targets

        targets: list[dict] = []
        seen: set[str] = set()
        tree = self.library_page.subtitle_video_tree
        for ent in tree.collect_checked_entries():
            video_id = str((ent or {}).get("video_id") or "").strip()
            if not video_id or video_id in seen:
                continue
            if selected_ids and video_id not in selected_ids:
                continue
            video_path = str((ent or {}).get("video_path") or "").strip()
            if not video_path:
                continue
            if (ent or {}).get("source_exists") is False:
                continue
            if not os.path.isfile(video_path):
                continue
            seen.add(video_id)
            targets.append(
                {
                    "video_id": video_id,
                    "video_path": video_path,
                    "library_path": str((ent or {}).get("library_path") or ""),
                }
            )

        missing_ids = selected_ids - seen if selected_ids else set()
        if missing_ids:
            for item in list_dialogue_index_targets(register=False):
                video_id = str((item or {}).get("video_id") or "").strip()
                if video_id not in missing_ids or video_id in seen:
                    continue
                seen.add(video_id)
                targets.append(dict(item))
        return targets

    def _run_dialogue_index_job(self, *, mode: str, title: str, reembed: bool):
        from src.services.dialogue_index_service import (
            ensure_dialogue_asr_ready,
            list_dialogue_reembed_targets,
        )
        from src.storage.dialogue_transcript_store import (
            ensure_shared_transcripts,
            list_dialogue_transcript_summaries,
        )

        self.library_page.set_library_mode(1)
        mode_value = str(mode or "auto").strip().lower() or "auto"

        selected_ids = {
            str(vid).strip()
            for vid in self.library_page.subtitle_video_tree.collect_checked_video_ids()
            if str(vid).strip()
        }
        if not selected_ids:
            self.show_info_dialog(
                title,
                self.texts.get("library_select_videos_first", "Select one or more videos first."),
                kind="info",
            )
            return

        self.library_page.lbl_status.setText(
            self.texts.get("build_dialogue_index_preparing", "Preparing subtitle extraction…")
        )

        if reembed:
            targets = [
                item
                for item in list_dialogue_reembed_targets()
                if str((item or {}).get("video_id") or "").strip() in selected_ids
            ]
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
            targets = self._resolve_dialogue_index_targets(selected_ids)
            if not targets:
                self.show_info_dialog(
                    title,
                    self.texts.get(
                        "build_dialogue_index_no_targets",
                        "No ready videos to index. Selected files may be missing on disk, "
                        "or are not registered in the subtitle library — refresh the list and retry.",
                    ),
                    kind="info",
                )
                return
            existing_ids = {
                str(row.get("video_id") or "").strip()
                for row in list_dialogue_transcript_summaries()
            }
            needs_asr = any(
                str((item or {}).get("video_id") or "").strip() not in existing_ids for item in targets
            )
            # Lightweight check only (no RapidOCR/ORT import on UI thread).
            # mode=ocr is "re-extract" and always runs OCR.
            if mode_value == "ocr" or needs_asr:
                asr_ready, asr_error = ensure_dialogue_asr_ready(import_engine=False)
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

        # Show confirm immediately — do not import OCR engines before the dialog.
        if not self.show_confirm_dialog(
            self.texts.get("confirm_title", "Confirm"),
            confirm,
            kind="info",
        ):
            return

        try:
            ensure_shared_transcripts()
        except Exception as exc:
            self.show_error_dialog(
                self.texts.get("build_dialogue_index_failed", "Dialogue index failed"),
                str(exc).strip() or repr(exc),
            )
            return

        from ui.workers import DialogueIndexWorker

        sample_interval_sec = self._read_subtitle_sample_interval()
        ocr_batch_size = self._read_subtitle_ocr_batch()

        self.library_page.btn_sync_db.setEnabled(False)
        self.library_page.btn_refresh_visual_library.setEnabled(False)
        self.library_page.btn_build_dialogue_index.setEnabled(False)
        self.library_page.btn_reembed_dialogue.setEnabled(False)
        self.library_page.btn_clear_dialogue.setEnabled(False)
        self.library_page.btn_export_dialogue.setEnabled(False)
        self.library_page.btn_refresh_dialogue_library.setEnabled(False)
        self.library_page.input_subtitle_sample_interval.setEnabled(False)
        self.library_page.input_subtitle_ocr_batch.setEnabled(False)
        self.library_page.btn_add_lib.setEnabled(False)
        self.library_page.btn_remove_lib.setEnabled(False)
        self.library_page.btn_cleanup_missing.setEnabled(False)
        self.library_page.btn_stop_dialogue_index.setEnabled(True)
        self.library_page.btn_stop_dialogue_index.setVisible(True)
        self.library_page.progress_bar.setVisible(True)
        self.library_page.progress_bar.setValue(0)
        self.library_page.lbl_status.setText(running)
        self._dialogue_index_ui_mode = mode_value

        worker = DialogueIndexWorker(
            targets=targets,
            mode=mode_value,
            sample_interval_sec=sample_interval_sec,
            ocr_batch_size=ocr_batch_size,
        )
        self.dialogue_index_worker = worker
        worker.progress_signal.connect(self._update_dialogue_index_progress)
        worker.error_signal.connect(self._handle_dialogue_index_error)
        worker.finished_signal.connect(self._finish_dialogue_index)
        # Keep the QThread alive until Qt reports it has fully stopped; clearing the
        # Python ref from finished_signal (emitted inside run()) can native-crash.
        worker.finished.connect(lambda w=worker: self._cleanup_dialogue_index_worker(w))
        worker.start()

    def _dialogue_index_running(self) -> bool:
        worker = getattr(self, "dialogue_index_worker", None)
        return bool(worker is not None and worker.isRunning())

    def _cleanup_dialogue_index_worker(self, worker) -> None:
        if getattr(self, "dialogue_index_worker", None) is worker:
            self.dialogue_index_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

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
        try:
            self.library_page.btn_sync_db.setEnabled(True)
        self.library_page.btn_refresh_visual_library.setEnabled(True)
            self.library_page.btn_build_dialogue_index.setEnabled(True)
            self.library_page.btn_reembed_dialogue.setEnabled(True)
            self.library_page.btn_clear_dialogue.setEnabled(True)
            self.library_page.btn_export_dialogue.setEnabled(True)
            self.library_page.btn_refresh_dialogue_library.setEnabled(True)
            self.library_page.input_subtitle_sample_interval.setEnabled(True)
            self.library_page.input_subtitle_ocr_batch.setEnabled(True)
            self.library_page.btn_add_lib.setEnabled(True)
            self.library_page.btn_cleanup_missing.setEnabled(True)
            self.library_page.btn_stop_dialogue_index.setEnabled(False)
            self.library_page.btn_stop_dialogue_index.setVisible(False)
            self.library_page.progress_bar.setVisible(False)
            self._refresh_remove_library_button()
            payload = dict(summary or {})
            reembed = str(payload.get("mode") or getattr(self, "_dialogue_index_ui_mode", "") or "") == "reembed"
            self._dialogue_index_ui_mode = ""
            failed_count = int(payload.get("failed", 0) or 0)
            errors = [str(item).strip() for item in list(payload.get("errors") or []) if str(item).strip()]
            if stopped:
                status = self.texts.get("build_dialogue_index_stopped", "Dialogue index stopped.")
            elif success:
                done_key = "reembed_dialogue_index_done" if reembed else "build_dialogue_index_done"
                status = self.texts.get(
                    done_key,
                    "Dialogue index done: {ok} ok, {failed} failed, {segments} segments.",
                ).format(
                    ok=int(payload.get("ok", 0) or 0),
                    failed=failed_count,
                    segments=int(payload.get("segment_rows", 0) or 0),
                    reused=int(payload.get("reused", 0) or 0),
                )
            else:
                status = self.texts.get("build_dialogue_index_failed", "Dialogue index failed")
            self.library_page.lbl_status.setText(status)
            # Per-video OCR failures used to finish "successfully" with only a status
            # line — packaged installs missing RapidOCR config.yaml looked like no UI reaction.
            if (not stopped) and failed_count > 0:
                detail_lines = errors[:5]
                if len(errors) > 5:
                    detail_lines.append(f"… (+{len(errors) - 5})")
                detail = "\n".join(detail_lines)
                self.show_error_dialog(
                    self.texts.get("build_dialogue_index_failed", "Dialogue index failed"),
                    status + (f"\n\n{detail}" if detail else ""),
                )
        finally:
            # Defer tree rebuild so this slot returns before touching heavy UI/SQLite,
            # and so the worker thread can fully exit first.
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, self._refresh_after_dialogue_index)

    def _refresh_after_dialogue_index(self) -> None:
        try:
            self.refresh_library_table()
        except Exception:
            pass
        try:
            self.refresh_dialogue_library_table()
        except Exception:
            pass
        if hasattr(self, "_sync_tray_stop_action"):
            try:
                self._sync_tray_stop_action()
            except Exception:
                pass

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
            self.texts.get("cleanup_missing_vectors_confirm_title", self.texts["confirm_title"]),
            self.texts["cleanup_missing_vectors_confirm"].format(count=len(reviewed_entries)),
            kind="warning",
            confirm_text=self.texts.get(
                "cleanup_missing_vectors_confirm_action",
                self.texts.get("cleanup_missing_vectors_action", "清理失效索引"),
            ),
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

        subtitle = self.texts["cleanup_missing_vectors_preview_summary"].format(
            count=len(missing_entries),
            libraries=len({entry["library_path"] for entry in missing_entries}),
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
            confirm_text=self.texts.get(
                "cleanup_missing_vectors_action",
                "清理失效索引",
            ),
            summary_text=self.texts["cleanup_missing_vectors_preview_continue"],
            row_payloads=missing_entries,
            show_utility_actions=False,
            extra_actions=[
                {
                    "label": self.texts.get(
                        "cleanup_missing_vectors_exclude",
                        self.texts.get("details_exclude_selected", "从列表排除"),
                    ),
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
        video_ids=None,
    ):
        try:
            if not self.check_runtime_resources():
                self.library_page.lbl_status.setText(self.texts["model_features_disabled"])
                return
            self.switch_page("library")
            if (
                self.indexing_controller.is_running()
                or self._dialogue_index_running()
                or self._remove_library_worker_running()
            ):
                self.library_page.lbl_status.setText(self.texts.get("index_already_running", ""))
                return
            self.library_page.btn_sync_db.setEnabled(False)
        self.library_page.btn_refresh_visual_library.setEnabled(False)
            self.library_page.btn_build_dialogue_index.setEnabled(False)
            self.library_page.btn_reembed_dialogue.setEnabled(False)
            self.library_page.btn_clear_dialogue.setEnabled(False)
            self.library_page.btn_export_dialogue.setEnabled(False)
            self.library_page.input_subtitle_sample_interval.setEnabled(False)
            self.library_page.input_subtitle_ocr_batch.setEnabled(False)
            self.library_page.btn_stop_index.setEnabled(True)
            self.library_page.btn_stop_index.setVisible(True)
            self.library_page.btn_add_lib.setEnabled(False)
            self.library_page.btn_remove_lib.setEnabled(False)
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
            self._indexing_tree_refresh_at = 0.0
            # Do not rebuild the video tree here — expensive for huge libraries.
            start_kwargs = {
                "target_lib": target_lib,
                "force_cleanup_missing_files": force_cleanup_missing_files,
                "cleanup_missing_entries": cleanup_missing_entries,
                "rebuild_global_assets": rebuild_global_assets,
                "index_from_vectors_only": index_from_vectors_only,
                "video_ids": video_ids,
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

        # Tree rebuild is O(libraries) header work + meta load; never do it per file
        # when users have 10k+ videos. Refresh at most every few seconds, or on finish.
        if file_changed or stage == "file":
            last_tree = float(getattr(self, "_indexing_tree_refresh_at", 0.0) or 0.0)
            if now - last_tree >= 4.0:
                self._indexing_tree_refresh_at = now
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
        self.library_page.btn_refresh_visual_library.setEnabled(True)
        self.library_page.btn_build_dialogue_index.setEnabled(True)
        self.library_page.btn_reembed_dialogue.setEnabled(True)
        self.library_page.btn_clear_dialogue.setEnabled(True)
        self.library_page.btn_export_dialogue.setEnabled(True)
        self.library_page.input_subtitle_sample_interval.setEnabled(True)
        self.library_page.input_subtitle_ocr_batch.setEnabled(True)
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
        self._refresh_remove_library_button()
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
            if not has_search_assets and not stopped:
                self.show_info_dialog(
                    self.texts.get("warning_title", self.texts.get("success_title", "Warning")),
                    self.texts.get(
                        "index_updated_empty_dialog",
                        status_text,
                    ),
                    kind="warning",
                )
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
            subtitle = self._format_local_vector_subtitle(detail)
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
                    {
                        "label": self.texts["library_vectors_legacy_cleanup"],
                        "object_name": "Ghost",
                        "handler": self._cleanup_legacy_vector_sidecars,
                    },
                ],
                row_double_click_handler=self._open_vector_detail_payload,
            )
            dialog.set_summary_text(self.texts["library_vectors_validation_loading"])
            self._start_local_vector_detail_validation(dialog)
            dialog.exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_vectors_load_failed"], exc)

    def _format_local_vector_subtitle(self, detail):
        storage_summary = detail.get("storage_summary") or {}
        return self.texts["library_vectors_subtitle"].format(
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

    def _cleanup_legacy_vector_sidecars(self, dialog):
        if not self.show_confirm_dialog(
            self.texts.get("confirm_title", "Confirm"),
            self.texts.get(
                "library_vectors_legacy_cleanup_confirm",
                "When Lance is ready, migration leftover npy/faiss files can be deleted safely. "
                "Search no longer reads them. Free disk space?",
            ),
            kind="warning",
        ):
            return
        try:
            from src.storage.lance_migration_runner import cleanup_safe_legacy_vector_sidecars

            result = cleanup_safe_legacy_vector_sidecars()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_vectors_load_failed"], exc)
            return

        message_key = str(result.get("message_key") or "library_vectors_legacy_cleanup_done")
        message = self.texts.get(message_key, message_key)
        if "{removed}" in message or "{bytes}" in message:
            message = message.format(
                removed=int(result.get("removed", 0) or 0),
                bytes=format_byte_size(int(result.get("bytes_freed_estimate", 0) or 0)),
            )
        if dialog is not None and dialog.isVisible():
            dialog.status_hint.setText(message)
            try:
                detail = list_local_vector_details(validate_contents=False)
                rows, payloads = self._build_local_vector_detail_rows(detail)
                dialog.set_rows(rows, payloads)
                dialog.set_subtitle(self._format_local_vector_subtitle(detail))
            except Exception:
                pass
        else:
            self.show_info_dialog(
                self.texts.get("library_vectors_legacy_cleanup", "Cleanup legacy npy/faiss"),
                message,
                kind="info",
            )

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
