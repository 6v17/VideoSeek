"""Understanding evidence generation UI — dedicated sidebar page."""

from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QAbstractItemView, QScrollArea, QFileDialog

from src.app.config import load_config, save_config, DEFAULT_CONFIG
from src.app.indexing_progress import format_progress_text
from src.services.library_service import list_libraries
from src.services.understanding_resource_service import get_understanding_resource_status
from src.services.understanding_service import (
    clear_all_evidence,
    delete_evidence_for_videos,
    list_local_evidence_details,
    list_ready_video_entries,
    load_evidence_bundle,
    resolve_video_context,
)
from src.services.indexing_service import load_video_chunks_by_id
from src.utils import format_timecode_range, open_folder_in_explorer, open_in_explorer
from ui.dialogs import ResourceTableDialog
from ui.widgets.chunk_timeline import ChunkTimelineSegment
from ui.workers import UnderstandingResourceStatusWorker


class UnderstandingGuiMixin:
    """Sidebar page for manual understanding evidence generation."""

    def _understanding_config_widgets(self):
        page = getattr(self, "understanding_page", None)
        if page is None:
            return None
        return page

    def load_understanding_settings(self, *, refresh_status: bool = True):
        page = self._understanding_config_widgets()
        if page is None:
            return
        try:
            config = load_config()
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_config_load_failed", "Failed to load settings."), exc)
            return
        understanding = dict(config.get("understanding") or {})
        remote_vlm = dict(understanding.get("remote_vlm") or DEFAULT_CONFIG["understanding"]["remote_vlm"])
        page.input_remote_vlm_base_url.setText(str(remote_vlm.get("base_url", "") or ""))
        page.input_remote_vlm_model.setText(str(remote_vlm.get("model", "") or ""))
        self._populate_understanding_caption_language_options(remote_vlm.get("caption_language", "zh"))
        if refresh_status:
            self._refresh_understanding_settings_status()

    def _populate_understanding_caption_language_options(self, active_language=None):
        page = self._understanding_config_widgets()
        if page is None:
            return
        combo = page.input_caption_language
        active = str(active_language or "zh").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.texts.get("understanding_caption_language_zh", "中文"), "zh")
        combo.addItem(self.texts.get("understanding_caption_language_en", "English"), "en")
        index = combo.findData(active if active in {"zh", "en"} else "zh")
        combo.setCurrentIndex(0 if index < 0 else index)
        combo.blockSignals(False)

    def save_understanding_settings(self):
        if not self._ensure_startup_migration_idle("feature_understanding"):
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        page = self._understanding_config_widgets()
        if page is None:
            return
        try:
            config = load_config()
            understanding = config.get("understanding")
            if not isinstance(understanding, dict):
                understanding = {}
                config["understanding"] = understanding
            remote_vlm = dict(understanding.get("remote_vlm") or DEFAULT_CONFIG["understanding"]["remote_vlm"])
            remote_vlm["base_url"] = page.input_remote_vlm_base_url.text().strip()
            remote_vlm["model"] = page.input_remote_vlm_model.text().strip()
            from src.services.understanding_resource_service import (
                get_caption_prompt_for_language,
                normalize_caption_language,
            )

            language = normalize_caption_language(page.input_caption_language.currentData())
            remote_vlm["caption_language"] = language
            remote_vlm["prompt"] = get_caption_prompt_for_language(language)
            understanding["remote_vlm"] = remote_vlm
            config["understanding"] = understanding
            save_config(config)
            self._refresh_understanding_page_fast()
            self._schedule_understanding_status_refresh()
            message = self.texts.get("understanding_config_saved", "Understanding settings saved.")
            page.lbl_status.setText(message)
            self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_config_save_failed", "Failed to save settings."), exc)

    def _set_understanding_config_enabled(self, enabled: bool):
        page = self._understanding_config_widgets()
        if page is None:
            return
        page.input_remote_vlm_base_url.setEnabled(enabled)
        page.input_remote_vlm_model.setEnabled(enabled)
        page.input_caption_language.setEnabled(enabled)
        page.btn_import_understanding_model.setEnabled(enabled)
        page.btn_save_config.setEnabled(enabled)

    def _is_current_page(self, page_name: str) -> bool:
        return self.pages.currentIndex() == self._nav_page_index(page_name)

    def _refresh_understanding_scope_options(self):
        if not hasattr(self, "understanding_page"):
            return
        combo = self.understanding_page.scope_combo
        current = combo.currentData(Qt.ItemDataRole.UserRole)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.texts.get("understanding_scope_all", "All libraries"), "")
        for path in list_libraries().keys():
            path = str(path or "").strip()
            if not path:
                continue
            combo.addItem(path, path)
        restore_index = 0
        if current:
            for index in range(combo.count()):
                if combo.itemData(index, Qt.ItemDataRole.UserRole) == current:
                    restore_index = index
                    break
        combo.setCurrentIndex(restore_index)
        combo.blockSignals(False)
        self._refresh_understanding_video_options()

    def _refresh_understanding_video_options(self):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        combo = page.video_combo
        current = combo.currentData(Qt.ItemDataRole.UserRole)
        target_lib = self._selected_understanding_target_lib()
        combo.blockSignals(True)
        combo.clear()
        entries = list_ready_video_entries(library_path=target_lib, config=load_config())
        for entry in entries:
            video_id = str(entry.get("video_id", "") or "").strip()
            if not video_id:
                continue
            rel_path = str(entry.get("video_rel_path", "") or video_id).strip()
            library_path = str(entry.get("library_path", "") or "").strip()
            label = rel_path if not target_lib else f"{library_path} / {rel_path}" if library_path else rel_path
            combo.addItem(label, video_id)
        if combo.count() == 0:
            combo.addItem(self.texts.get("understanding_video_none", "No indexed videos"), "")
        restore_index = 0
        if current:
            found = combo.findData(current, Qt.ItemDataRole.UserRole)
            if found >= 0:
                restore_index = found
        combo.setCurrentIndex(restore_index)
        combo.blockSignals(False)
        self._load_understanding_video_timeline()

    def _selected_understanding_video_id(self):
        if not hasattr(self, "understanding_page"):
            return ""
        return str(self.understanding_page.video_combo.currentData(Qt.ItemDataRole.UserRole) or "").strip()

    def _on_understanding_scope_changed(self, *_args):
        self._refresh_understanding_video_options()

    def _on_understanding_video_changed(self, *_args):
        self._load_understanding_video_timeline()

    def _on_understanding_chunk_clicked(self, index: int):
        self._show_understanding_chunk_detail(int(index))

    def _understanding_chunk_playback_times(self, index: int) -> tuple[float, float, float] | None:
        index_chunks = getattr(self, "_understanding_index_chunks", []) or []
        chunk_index = int(index)
        if not (0 <= chunk_index < len(index_chunks)):
            return None
        chunk = index_chunks[chunk_index]
        start_sec = float(chunk.get("start", 0.0))
        end_sec = float(chunk.get("end", start_sec))
        if end_sec <= start_sec:
            end_sec = start_sec + 0.1

        payload = dict(getattr(self, "_understanding_chunk_payloads", {}).get(chunk_index) or {})
        sample = dict(payload.get("sample") or {})
        if sample.get("timestamp_sec") is not None:
            suggested_sec = float(sample.get("timestamp_sec"))
        else:
            suggested_sec = (start_sec + end_sec) / 2.0
        return start_sec, end_sec, suggested_sec

    def _on_understanding_chunk_double_clicked(self, index: int):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        playback_times = self._understanding_chunk_playback_times(index)
        if playback_times is None:
            return
        start_sec, end_sec, suggested_sec = playback_times

        context = dict(getattr(self, "_understanding_video_context", {}) or {})
        video_path = str(context.get("video_path", "") or "").strip()
        if not video_path or not bool(context.get("source_exists")):
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_chunk_preview_no_video", "Video file not found."),
                kind="warning",
            )
            return

        self._show_understanding_chunk_detail(int(index))
        opened = self.open_segment_preview_dialog(
            video_path,
            start_sec,
            end_sec,
            suggested_sec=suggested_sec,
            on_status=page.lbl_status.setText,
        )
        if opened:
            page.lbl_status.setText(
                self.texts.get(
                    "understanding_chunk_play_started",
                    "Playing segment {index}: {range}",
                ).format(
                    index=int(index) + 1,
                    range=format_timecode_range(start_sec, end_sec),
                )
            )

    def _set_understanding_readonly_text(self, widget, text: str):
        widget.setPlainText(str(text or ""))

    def _extract_video_summary_text(self, evidence: dict | None) -> str:
        if not isinstance(evidence, dict):
            return ""
        summary = dict(evidence.get("summary") or {})
        return str(summary.get("text", "") or "").strip()

    def _refresh_understanding_video_meta(self, evidence: dict | None = None):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        if evidence is None:
            video_id = self._selected_understanding_video_id()
            evidence = load_evidence_bundle(video_id, config=load_config()) if video_id else None
        if not isinstance(evidence, dict):
            page.video_summary_meta_label.setText("")
            return
        chunks = list(evidence.get("chunks") or [])
        generated_at = str((evidence.get("provenance") or {}).get("generated_at") or "").strip()
        parts = []
        if chunks:
            parts.append(
                self.texts.get("understanding_video_meta_chunks", "{count} segments").format(count=len(chunks))
            )
        if generated_at:
            parts.append(
                self.texts.get("understanding_video_meta_generated_at", "Generated: {time}").format(time=generated_at)
            )
        page.video_summary_meta_label.setText(" · ".join(parts))

    def _refresh_understanding_video_summary(self, evidence: dict | None = None):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        if evidence is None:
            video_id = self._selected_understanding_video_id()
            evidence = load_evidence_bundle(video_id, config=load_config()) if video_id else None
        summary_text = self._extract_video_summary_text(evidence)
        if summary_text:
            self._set_understanding_readonly_text(page.video_summary_text, summary_text)
            self._refresh_understanding_video_meta(evidence)
            return
        running = getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()
        if running:
            self._set_understanding_readonly_text(
                page.video_summary_text,
                self.texts.get(
                    "understanding_video_summary_generating",
                    "Generating video summary after all segments…",
                ),
            )
            self._refresh_understanding_video_meta(evidence)
            return
        self._set_understanding_readonly_text(
            page.video_summary_text,
            self.texts.get(
                "understanding_video_summary_empty",
                "Video summary will appear after generation.",
            ),
        )
        self._refresh_understanding_video_meta(evidence)

    def _chunk_payload_has_evidence(self, payload) -> bool:
        if not isinstance(payload, dict):
            return False
        evidence = dict(payload.get("evidence") or {})
        vision = dict(evidence.get("vision") or {})
        caption = str(dict(vision.get("image_caption") or {}).get("text", "") or "").strip()
        objects = list(dict(vision.get("object_detection") or {}).get("objects") or [])
        return bool(caption or objects)

    def _load_understanding_video_timeline(self):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        video_id = self._selected_understanding_video_id()
        self._understanding_chunk_payloads = {}
        if not video_id:
            page.chunk_timeline.set_segments([])
            page.chunk_time_label.setText("")
            self._set_understanding_readonly_text(
                page.chunk_caption_text,
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
            )
            page.chunk_objects_label.setText("")
            self._understanding_video_context = {}
            self._refresh_understanding_video_summary(None)
            self._refresh_understanding_video_meta(None)
            return

        config = load_config()
        try:
            self._understanding_video_context = resolve_video_context(video_id, config=config)
        except Exception:
            self._understanding_video_context = {}
        index_chunks = load_video_chunks_by_id(video_id, config)
        self._understanding_index_chunks = list(index_chunks)
        evidence = load_evidence_bundle(video_id, config=config) or {}
        evidence_chunks = {
            int(item.get("chunk_index", -1)): dict(item)
            for item in (evidence.get("chunks") or [])
            if isinstance(item, dict)
        }
        duration_sec = float((evidence.get("video") or {}).get("duration_sec") or 0.0)
        segments: list[ChunkTimelineSegment] = []
        for index, chunk in enumerate(index_chunks):
            payload = evidence_chunks.get(index)
            if payload is not None:
                self._understanding_chunk_payloads[index] = payload
            state = "ready" if payload is not None and self._chunk_payload_has_evidence(payload) else "pending"
            segments.append(
                ChunkTimelineSegment(
                    start_sec=float(chunk.get("start", 0.0)),
                    end_sec=float(chunk.get("end", chunk.get("start", 0.0))),
                    state=state,
                )
            )
            if duration_sec <= 0 and segments:
                duration_sec = max(float(segments[-1].end_sec), duration_sec)
        page.chunk_timeline.set_segments(segments, duration_sec=duration_sec)
        self._refresh_understanding_video_summary(evidence)
        if segments:
            page.chunk_timeline.set_selected_index(0)
            self._show_understanding_chunk_detail(0)
        else:
            page.chunk_time_label.setText("")
            self._set_understanding_readonly_text(
                page.chunk_caption_text,
                self.texts.get("understanding_video_no_chunks", "No semantic chunks for this video."),
            )
            page.chunk_objects_label.setText("")
            self._refresh_understanding_video_summary(evidence)

    def _show_understanding_chunk_detail(self, index: int, payload=None):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        page.chunk_timeline.set_selected_index(int(index))
        if payload is None:
            payload = dict(self._understanding_chunk_payloads.get(int(index)) or {})
        if not payload and int(index) >= 0:
            index_chunks = getattr(self, "_understanding_index_chunks", []) or []
            if int(index) < len(index_chunks):
                chunk = index_chunks[int(index)]
                page.chunk_time_label.setText(
                    self.texts.get("understanding_chunk_time", "Segment {index}: {range}").format(
                        index=int(index) + 1,
                        range=format_timecode_range(float(chunk.get("start", 0.0)), float(chunk.get("end", 0.0))),
                    )
                )
                self._set_understanding_readonly_text(
                    page.chunk_caption_text,
                    self.texts.get("understanding_chunk_pending", "Not generated yet."),
                )
                page.chunk_objects_label.setText("")
                return
        if not payload:
            return
        start_sec = float(payload.get("start_sec", 0.0))
        end_sec = float(payload.get("end_sec", start_sec))
        page.chunk_time_label.setText(
            self.texts.get("understanding_chunk_time", "Segment {index}: {range}").format(
                index=int(payload.get("chunk_index", index)) + 1,
                range=format_timecode_range(start_sec, end_sec),
            )
        )
        vision = dict(dict(payload.get("evidence") or {}).get("vision") or {})
        caption = str(dict(vision.get("image_caption") or {}).get("text", "") or "").strip()
        self._set_understanding_readonly_text(
            page.chunk_caption_text,
            caption or self.texts.get("understanding_chunk_no_caption", "No caption."),
        )
        objects = list(dict(vision.get("object_detection") or {}).get("objects") or [])
        if not objects:
            page.chunk_objects_label.setText(self.texts.get("understanding_chunk_no_objects", "Detection: none"))
        else:
            parts = []
            for obj in objects[:16]:
                label = str(obj.get("label", "") or "?")
                confidence = float(obj.get("confidence", 0.0) or 0.0)
                parts.append(f"{label} ({confidence:.0%})")
            page.chunk_objects_label.setText(
                self.texts.get("understanding_chunk_objects", "Detection: {items}").format(items=", ".join(parts))
            )

    def _handle_understanding_chunk_completed(self, index, total, payload):
        if not hasattr(self, "understanding_page"):
            return
        page = self.understanding_page
        chunk_index = int(index)
        self._understanding_chunk_payloads[chunk_index] = dict(payload or {})
        page.chunk_timeline.set_segment_state(chunk_index, "ready")
        next_index = chunk_index + 1
        page.chunk_timeline.set_generating_index(next_index if next_index < int(total) else -1)
        self._show_understanding_chunk_detail(chunk_index, payload)

    def _prepare_understanding_timeline_for_generation(self):
        page = self.understanding_page
        self._understanding_chunk_payloads = {}
        total = page.chunk_timeline.segment_count()
        for index in range(total):
            page.chunk_timeline.set_segment_state(index, "pending")
        page.chunk_timeline.set_generating_index(0 if total else -1)
        self._set_understanding_readonly_text(
            page.video_summary_text,
            self.texts.get("understanding_video_summary_generating", "Generating video summary after all segments…"),
        )

    def _selected_understanding_target_lib(self):
        if not hasattr(self, "understanding_page"):
            return None
        value = self.understanding_page.scope_combo.currentData(Qt.ItemDataRole.UserRole)
        path = str(value or "").strip()
        return path or None

    def _fetch_understanding_resource_status(self, *, probe_remote: bool = True) -> dict:
        try:
            return get_understanding_resource_status(
                config=load_config(),
                probe_remote=probe_remote,
                remote_probe_timeout_sec=2.0,
            )
        except Exception:
            return {"understanding_ready": False, "missing_components": []}

    def _refresh_understanding_page_fast(self):
        status = self._fetch_understanding_resource_status(probe_remote=False)
        self._refresh_understanding_ui(status=status)
        self._refresh_understanding_settings_status(status=status)

    def _schedule_understanding_status_refresh(self):
        if not self._is_current_page("understanding"):
            return
        timer = getattr(self, "_understanding_status_refresh_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._start_understanding_status_refresh)
            self._understanding_status_refresh_timer = timer
        timer.start(150)

    def _start_understanding_status_refresh(self):
        if not self._is_current_page("understanding"):
            return

        generation = int(getattr(self, "_understanding_status_generation", 0)) + 1
        self._understanding_status_generation = generation

        worker = UnderstandingResourceStatusWorker(self, remote_probe_timeout_sec=2.0)
        self._understanding_status_worker = worker
        worker.result_ready.connect(
            lambda status, gen=generation: self._finish_understanding_status_refresh(status, gen)
        )
        worker.error_signal.connect(
            lambda _message, gen=generation: self._fail_understanding_status_refresh(gen)
        )
        worker.finished.connect(lambda active_worker=worker: self._release_understanding_status_worker(active_worker))
        worker.start()

    def _finish_understanding_status_refresh(self, status, generation: int):
        if generation != int(getattr(self, "_understanding_status_generation", 0)):
            return
        if not self._is_current_page("understanding"):
            return
        self._understanding_cached_status = dict(status or {})
        self._refresh_understanding_ui(status=status)
        self._refresh_understanding_settings_status(status=status)

    def _fail_understanding_status_refresh(self, generation: int):
        if generation != int(getattr(self, "_understanding_status_generation", 0)):
            return
        if not self._is_current_page("understanding"):
            return
        page = self._understanding_config_widgets()
        if page is None:
            return
        hint = getattr(page, "hint_understanding_status", None)
        if hint is not None:
            hint.setText(
                self.texts.get(
                    "understanding_settings_remote_vlm_not_ready",
                    "Description service not ready: {error}",
                ).format(error="status check failed")
            )

    def _release_understanding_status_worker(self, worker):
        if getattr(self, "_understanding_status_worker", None) is worker:
            self._understanding_status_worker = None
        try:
            worker.deleteLater()
        except Exception:
            pass

    def _refresh_understanding_ui(self, status=None, *, probe_remote: bool = True):
        if not hasattr(self, "understanding_page"):
            return
        if status is None:
            status = self._fetch_understanding_resource_status(probe_remote=probe_remote)

        ready = bool(status.get("understanding_ready"))
        missing = ", ".join(status.get("missing_components") or [])
        understanding_running = getattr(self, "understanding_controller", None) and self.understanding_controller.is_running()
        indexing_running = self.indexing_controller.is_running()
        page = self.understanding_page

        show_notice = self._is_current_page("understanding") and not ready and not understanding_running
        page.understanding_notice.setVisible(show_notice)
        if show_notice:
            page.understanding_notice_text.setText(
                self.texts.get(
                    "understanding_not_ready_banner",
                    "Understanding models are not ready: {missing}. Import components and choose a profile in Settings.",
                ).format(missing=missing or self.texts.get("understanding_not_ready", "Not ready"))
            )

        page.btn_generate_evidence.setEnabled(
            ready and not understanding_running and not indexing_running and bool(self._selected_understanding_video_id())
        )
        page.btn_evidence_details.setEnabled(not understanding_running)
        page.btn_export_video_json.setEnabled(
            not understanding_running and self._current_video_has_exportable_evidence()
        )
        page.scope_combo.setEnabled(not understanding_running)
        page.video_combo.setEnabled(not understanding_running)
        self._set_understanding_config_enabled(not understanding_running)
        if ready:
            page.lbl_understanding_hint.setText(
                self.texts.get(
                    "understanding_library_ready_hint",
                    "YOLO and the description service are ready.",
                )
            )
        else:
            page.lbl_understanding_hint.setText(
                self.texts.get(
                    "understanding_library_not_ready_hint",
                    "Import YOLO and configure the description service below.",
                )
            )
        remote_vlm = dict(status.get("remote_vlm") or {})
        if remote_vlm.get("pending") and ready:
            page.lbl_understanding_hint.setText(
                self.texts.get(
                    "understanding_settings_status_checking",
                    "Checking description service…",
                )
            )
        if not ready:
            page.btn_generate_evidence.setToolTip(self.texts.get("understanding_not_ready", "Not ready"))
        else:
            page.btn_generate_evidence.setToolTip("")

    def open_understanding_settings(self):
        self.switch_page("understanding")
        if hasattr(self.understanding_page, "expand_config_panel"):
            self.understanding_page.expand_config_panel()
        scroll = self.pages.widget(self._nav_page_index("understanding"))
        if isinstance(scroll, QScrollArea):
            scroll.ensureWidgetVisible(self.understanding_page.config_card, 48)

    def _refresh_understanding_settings_status(self, status=None, *, probe_remote: bool = True):
        page = self._understanding_config_widgets()
        if page is None:
            return
        hint = getattr(page, "hint_understanding_status", None)
        if hint is None:
            return
        if status is None:
            try:
                status = self._fetch_understanding_resource_status(probe_remote=probe_remote)
            except Exception as exc:
                hint.setText(str(exc))
                return
        remote_vlm = dict(status.get("remote_vlm") or {})
        remote_line = ""
        if remote_vlm.get("pending"):
            remote_line = self.texts.get(
                "understanding_settings_remote_vlm_checking",
                "Connecting to description service…",
            )
        elif remote_vlm.get("reachable") and remote_vlm.get("model_available"):
            remote_line = self.texts.get(
                "understanding_settings_remote_vlm_ready",
                "Description service connected: {model}",
            ).format(model=str(load_config().get("understanding", {}).get("remote_vlm", {}).get("model", "")))
        elif remote_vlm:
            remote_line = self.texts.get(
                "understanding_settings_remote_vlm_not_ready",
                "Description service not ready: {error}",
            ).format(error=str(remote_vlm.get("error", "") or "unreachable"))

        if status.get("understanding_ready"):
            base = self.texts.get("understanding_settings_ready", "YOLO and the description service are ready.")
            hint.setText(f"{base}\n{remote_line}".strip() if remote_line else base)
            return
        missing = ", ".join(status.get("missing_components") or [])
        profile_error = str(status.get("profile_error", "") or "").strip()
        yolo_line = self._understanding_yolo_status_line(status)
        detail = profile_error or missing or self.texts.get("understanding_not_ready", "Not ready")
        base = self.texts.get("understanding_settings_not_ready", "Missing: {missing}").format(missing=detail)
        lines = [line for line in (yolo_line, base, remote_line) if line]
        hint.setText("\n".join(lines))

    def _understanding_yolo_status_line(self, status):
        components = list(status.get("components") or [])
        yolo_items = [
            item for item in components
            if str(item.get("task", "") or "").strip() == "object_detection"
        ]
        if not yolo_items:
            return self.texts.get(
                "understanding_yolo_status_missing",
                "YOLO: not imported yet. Use Import Model to add the YOLO package.",
            )
        item = yolo_items[0]
        name = str(item.get("display_name", "") or item.get("id", "") or "YOLO").strip()
        if item.get("installed"):
            return self.texts.get("understanding_yolo_status_ready", "YOLO: {name} (ready).").format(name=name)
        return self.texts.get("understanding_yolo_status_missing_named", "YOLO: {name} (not imported).").format(name=name)

    def start_generate_understanding_evidence(self, target_lib=None, video_id=None):
        if not self._ensure_startup_migration_idle("feature_understanding"):
            return
        if self.indexing_controller.is_running():
            return
        if getattr(self, "understanding_controller", None) and self.understanding_controller.is_running():
            return
        try:
            status = get_understanding_resource_status(config=load_config())
        except Exception as exc:
            self.show_error_dialog(self.texts.get("understanding_generation_failed", "Failed to generate evidence."), exc)
            return
        if not status.get("understanding_ready"):
            self._refresh_understanding_ui()
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_not_ready", "Understanding models are not ready."),
                kind="warning",
            )
            return

        video_id = str(video_id or self._selected_understanding_video_id() or "").strip()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        if self.understanding_page.chunk_timeline.segment_count() <= 0:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_no_chunks", "No semantic chunks for this video."),
                kind="warning",
            )
            return

        page = self.understanding_page
        self.switch_page("understanding")
        page.btn_generate_evidence.setEnabled(False)
        page.btn_evidence_details.setEnabled(False)
        page.btn_export_video_json.setEnabled(False)
        page.scope_combo.setEnabled(False)
        page.video_combo.setEnabled(False)
        self._set_understanding_config_enabled(False)
        page.btn_stop.setEnabled(True)
        page.btn_stop.setVisible(True)
        page.progress_bar.setVisible(True)
        page.lbl_status.setText(self.texts.get("understanding_generation_started", "Generating…"))
        page.understanding_notice.hide()
        self._prepare_understanding_timeline_for_generation()

        if self.understanding_controller.start_video(video_id):
            if hasattr(self, "_sync_tray_stop_action"):
                self._sync_tray_stop_action()

    def stop_understanding_generation(self):
        if not getattr(self, "understanding_controller", None) or not self.understanding_controller.is_running():
            return
        if self.understanding_controller.request_stop():
            self.understanding_page.lbl_status.setText(self.texts.get("understanding_stop_requested", "Stopping…"))
            self.understanding_page.btn_stop.setEnabled(False)

    def _update_understanding_progress(self, value, text):
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()
        self.understanding_page.progress_bar.setValue(value)
        self.understanding_page.lbl_status.setText(format_progress_text(text, self.texts))

    def _finish_understanding_generation(self, success, target, stopped=False, result=None):
        result = dict(result or {})
        page = self.understanding_page
        page.btn_generate_evidence.setEnabled(True)
        page.btn_evidence_details.setEnabled(True)
        page.btn_export_video_json.setEnabled(self._current_video_has_exportable_evidence())
        page.scope_combo.setEnabled(True)
        page.video_combo.setEnabled(True)
        self._set_understanding_config_enabled(True)
        page.btn_stop.setEnabled(False)
        page.btn_stop.setVisible(False)
        page.progress_bar.setVisible(False)
        page.chunk_timeline.set_generating_index(-1)

        if result.get("video_id"):
            chunk_count = int(result.get("chunk_count", 0) or 0)
            if stopped:
                status_text = self.texts.get("understanding_generation_stopped", "Stopped.")
            elif success:
                status_text = self.texts.get(
                    "understanding_video_generation_done",
                    "Finished: {count} segments.",
                ).format(count=chunk_count)
            else:
                status_text = self.texts.get("understanding_generation_failed", "Failed.")
            page.lbl_status.setText(status_text)
            if stopped:
                page.chunk_timeline.set_generating_index(-1)
            else:
                self._load_understanding_video_timeline()
        else:
            generated_count = int(result.get("generated_count", 0) or 0)
            error_count = len(result.get("errors") or [])
            requested_count = int(result.get("requested_count", 0) or 0)
            if stopped:
                status_text = self.texts.get("understanding_generation_stopped", "Stopped.")
            elif success or generated_count > 0:
                if requested_count == 0:
                    status_text = self.texts.get("understanding_generation_none", "No indexed videos are ready.")
                elif error_count:
                    status_text = self.texts.get(
                        "understanding_generation_done_with_errors",
                        "Finished: {count} videos, {errors} failed.",
                    ).format(count=generated_count, errors=error_count)
                else:
                    status_text = self.texts.get(
                        "understanding_generation_done",
                        "Finished: {count} videos.",
                    ).format(count=generated_count)
            else:
                status_text = self.texts.get("understanding_generation_failed", "Failed.")
            page.lbl_status.setText(status_text)

        self._refresh_understanding_ui()
        if hasattr(self, "_sync_tray_stop_action"):
            self._sync_tray_stop_action()
        if getattr(self, "_close_when_indexing_stops", False):
            self._close_when_indexing_stops = False
            self.close()

    def _handle_understanding_error(self, error_text):
        detail = str(error_text or "").strip()
        if not detail:
            return
        self.show_error_dialog(self.texts.get("understanding_generation_failed", "Failed."), detail)

    def _current_video_has_exportable_evidence(self) -> bool:
        video_id = self._selected_understanding_video_id()
        if not video_id:
            return False
        return load_evidence_bundle(video_id, config=load_config()) is not None

    def _default_understanding_export_name(self, evidence: dict) -> str:
        video = dict(evidence.get("video") or {})
        rel_path = str(video.get("video_rel_path") or video.get("video_id") or "video").strip()
        stem = os.path.splitext(os.path.basename(rel_path))[0] or "video"
        return f"{stem}_understanding.json"

    def export_current_video_understanding_json(self):
        video_id = self._selected_understanding_video_id()
        if not video_id:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_video_select_hint", "Select an indexed video."),
                kind="warning",
            )
            return
        evidence = load_evidence_bundle(video_id, config=load_config())
        if not evidence:
            self.show_info_dialog(
                self.texts.get("warning_title", "Warning"),
                self.texts.get("understanding_export_video_empty", "No understanding evidence for this video yet."),
                kind="warning",
            )
            return
        default_name = self._default_understanding_export_name(evidence)
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.texts.get("understanding_export_video_title", "Export Video Understanding JSON"),
            default_name,
            self.texts.get("details_export_filter", "JSON Files (*.json)"),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(evidence, handle, ensure_ascii=False, indent=2)
        except Exception as exc:
            self.show_error_dialog(self.texts.get("details_export_failed", "Export failed."), exc)
            return
        message = self.texts.get("details_export_done", "Exported: {path}").format(path=path)
        self.understanding_page.lbl_status.setText(message)
        self.show_info_dialog(self.texts.get("success_title", "Success"), message, kind="success")

    def show_local_evidence_details(self):
        try:
            dialog = self._create_evidence_detail_dialog(list_local_evidence_details())
            dialog.exec()
        except Exception as exc:
            self.show_error_dialog(self.texts["library_evidence_load_failed"], exc)

    def _create_evidence_detail_dialog(self, detail):
        yes_text = self.texts["details_yes"]
        no_text = self.texts["details_no"]
        rows, payloads = self._build_local_evidence_detail_rows(detail, yes_text=yes_text, no_text=no_text)
        subtitle = self.texts["library_evidence_subtitle"].format(
            total=detail["total_entries"],
            evidence_dir=detail["evidence_dir"],
        )
        invalid_state_text = self.texts.get("library_evidence_state_invalid", "Invalid")
        return ResourceTableDialog(
            parent=self,
            is_dark=self.is_dark_mode,
            language=self.language,
            title=self.texts["library_evidence_title"],
            subtitle=subtitle,
            headers=self.texts["library_evidence_headers"],
            rows=rows,
            row_payloads=payloads,
            export_default_name="local_evidence_details.json",
            stretch_column=2,
            allow_sorting=False,
            selection_mode=QAbstractItemView.ExtendedSelection,
            fixed_column_widths={
                0: 52,
                1: 200,
                2: 200,
                3: 120,
                4: 96,
                5: 140,
                6: 120,
                7: 180,
                8: 86,
                9: 86,
                10: 72,
                11: 148,
                12: 120,
            },
            issue_row_predicate=lambda row, invalid_text=invalid_state_text: row[12] == invalid_text,
            extra_actions=[
                {
                    "label": self.texts["details_open_selected"],
                    "object_name": "GhostButton",
                    "handler": self._open_selected_evidence_detail_path,
                },
                {
                    "label": self.texts["details_copy_selected"],
                    "object_name": "GhostButton",
                    "handler": self._copy_selected_evidence_detail_path,
                },
                {
                    "label": self.texts.get("library_evidence_open_dir", "Open Evidence Folder"),
                    "object_name": "GhostButton",
                    "handler": self._open_evidence_detail_folder,
                },
                {
                    "label": self.texts.get("library_evidence_delete_selected", "Delete Selected"),
                    "object_name": "DangerGhostButton",
                    "handler": self._delete_selected_evidence_records,
                },
                {
                    "label": self.texts.get("library_evidence_clear_all", "Clear All Evidence"),
                    "object_name": "DangerGhostButton",
                    "handler": self._clear_all_evidence_records,
                },
            ],
            row_double_click_handler=self._open_evidence_detail_payload,
        )

    def _reload_evidence_detail_dialog(self, dialog):
        detail = list_local_evidence_details()
        yes_text = self.texts["details_yes"]
        no_text = self.texts["details_no"]
        rows, payloads = self._build_local_evidence_detail_rows(detail, yes_text=yes_text, no_text=no_text)
        dialog.set_rows(rows, payloads)
        return detail

    def _delete_selected_evidence_records(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        if not self.show_confirm_dialog(
            self.texts["confirm_title"],
            self.texts["library_evidence_delete_confirm"].format(count=len(selected)),
            kind="warning",
        ):
            return
        video_ids = [str(item.get("video_id", "") or "").strip() for item in selected]
        result = delete_evidence_for_videos(video_ids)
        detail = self._reload_evidence_detail_dialog(dialog)
        deleted_count = int(result.get("deleted_count", 0) or 0)
        error_count = len(result.get("errors") or [])
        if error_count:
            dialog.status_hint.setText(
                self.texts["library_evidence_delete_done_with_errors"].format(
                    count=deleted_count,
                    errors=error_count,
                )
            )
        else:
            dialog.status_hint.setText(
                self.texts["library_evidence_delete_done"].format(
                    count=deleted_count,
                    total=detail["evidence_count"],
                )
            )

    def _clear_all_evidence_records(self, dialog):
        detail = list_local_evidence_details()
        if int(detail.get("total_entries", 0) or 0) <= 0:
            dialog.status_hint.setText(self.texts.get("library_evidence_clear_empty", "No evidence files to clear."))
            return
        if not self.show_confirm_dialog(
            self.texts.get("library_evidence_clear_confirm_title", self.texts["confirm_title"]),
            self.texts["library_evidence_clear_confirm"].format(count=detail["total_entries"]),
            kind="warning",
        ):
            return
        result = clear_all_evidence()
        detail = self._reload_evidence_detail_dialog(dialog)
        deleted_count = int(result.get("deleted_count", 0) or 0)
        error_count = len(result.get("errors") or [])
        if error_count:
            dialog.status_hint.setText(
                self.texts["library_evidence_clear_done_with_errors"].format(
                    count=deleted_count,
                    errors=error_count,
                )
            )
        else:
            dialog.status_hint.setText(
                self.texts["library_evidence_clear_done"].format(
                    count=deleted_count,
                    total=detail["evidence_count"],
                )
            )

    def _build_local_evidence_detail_rows(self, detail, *, yes_text, no_text):
        rows = []
        payloads = []
        for index, item in enumerate(detail.get("entries") or [], start=1):
            clip_label = str(item.get("clip_model", "") or "").strip()
            provider = str(item.get("search_provider", "") or "").strip()
            if clip_label and provider:
                clip_label = f"{provider}/{clip_label}"
            rows.append(
                [
                    index,
                    item.get("library_path", ""),
                    item.get("video_rel_path", ""),
                    clip_label,
                    item.get("yolo_model", "") or "",
                    item.get("caption_model", "") or "",
                    item.get("other_models", "") or "",
                    os.path.basename(item.get("evidence_file", "") or "") if item.get("evidence_file") else "",
                    yes_text if item.get("source_exists") else no_text,
                    yes_text,
                    int(item.get("chunk_count", 0) or 0),
                    item.get("generated_at", "") or "",
                    self._local_evidence_state_text(item.get("evidence_state", "")),
                ]
            )
            payloads.append(item)
        return rows, payloads

    def _local_evidence_state_text(self, evidence_state):
        state_key = str(evidence_state or "").strip().lower() or "missing"
        return self.texts.get(f"library_evidence_state_{state_key}", state_key)

    def _open_evidence_detail_payload(self, dialog, payload, item=None):
        column = item.column() if item is not None else 7
        library_path = str(payload.get("library_path", "") or "").strip()
        video_rel_path = str(payload.get("video_rel_path", "") or "").strip()
        evidence_file = str(payload.get("evidence_file", "") or "").strip()

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
            video_path = os.path.normpath(os.path.join(library_path, video_rel_path))
            if os.path.exists(video_path):
                open_in_explorer(video_path)
            else:
                open_folder_in_explorer(library_path)
            dialog.status_hint.setText(video_path)
            return

        if column == 7:
            if not evidence_file:
                dialog.status_hint.setText(self.texts.get("library_evidence_missing_file", "No evidence file yet."))
                return
            if os.path.exists(evidence_file):
                open_in_explorer(evidence_file)
            else:
                parent_dir = os.path.dirname(evidence_file)
                if parent_dir:
                    open_folder_in_explorer(parent_dir)
            dialog.status_hint.setText(evidence_file)
            return

        if not evidence_file:
            dialog.status_hint.setText(self.texts.get("library_evidence_missing_file", "No evidence file yet."))
            return
        if os.path.exists(evidence_file):
            open_in_explorer(evidence_file)
        else:
            parent_dir = os.path.dirname(evidence_file)
            if parent_dir:
                open_folder_in_explorer(parent_dir)
        dialog.status_hint.setText(evidence_file)

    def _open_selected_evidence_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        self._open_evidence_detail_payload(dialog, selected[0], dialog.table.currentItem())

    def _copy_selected_evidence_detail_path(self, dialog):
        selected = dialog.get_selected_payloads()
        if not selected:
            dialog.status_hint.setText(self.texts["details_nothing_selected"])
            return
        payload = selected[0]
        target_path = str(payload.get("evidence_file", "") or "").strip()
        if not target_path:
            dialog.status_hint.setText(self.texts.get("library_evidence_missing_file", "No evidence file yet."))
            return
        QApplication.clipboard().setText(target_path)
        dialog.status_hint.setText(self.texts["details_copy_done"])

    def _open_evidence_detail_folder(self, dialog):
        try:
            detail = list_local_evidence_details()
            evidence_dir = str(detail.get("evidence_dir", "") or "").strip()
            if evidence_dir:
                os.makedirs(evidence_dir, exist_ok=True)
                open_folder_in_explorer(evidence_dir)
                dialog.status_hint.setText(evidence_dir)
                return
        except Exception as exc:
            dialog.status_hint.setText(str(exc))
            return
        dialog.status_hint.setText(self.texts["details_nothing_selected"])
