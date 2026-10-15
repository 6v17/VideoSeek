"""i18n apply_texts helpers for MainWindow (split out of gui.py)."""

from __future__ import annotations

from src.app.config import get_app_version, load_config
from src.app.plugins import get_registry
from ui.widgets.button_roles import set_button_role
from ui.widgets.list_find_bar import list_find_text_kwargs


class ApplyTextsGuiMixin:
    """Page-scoped text refresh helpers used by ``MainWindow.apply_texts``."""

    def _apply_texts_chrome(self, t):
        self.setWindowTitle(f"{t['app_name']} v{get_app_version()}")
        self.sidebar.title.setText(t["app_name"])
        self.sidebar.subtitle.setText(t["app_subtitle"])
        self.sidebar.hero_tag.setText(t["hero_tag"])
        self.sidebar.hero_title.setText(t["hero_title"])
        self.sidebar.hero_body.setText(t["hero_body"])
        self.sidebar.btn_page_search.setText(t["nav_search"])
        self.sidebar.btn_page_link.setText(t["nav_link"])
        self.sidebar.btn_page_library.setText(t["nav_library"])
        self.sidebar.btn_page_understanding.setText(t["nav_understanding"])
        self.sidebar.btn_page_settings.setText(t["nav_settings"])
        self.sidebar.btn_collapse.setToolTip(t.get("nav_sidebar_hide", "隐藏侧边栏 (Ctrl+B)"))
        restore = getattr(self, "btn_sidebar_restore", None)
        if restore is not None:
            restore.setToolTip(t.get("nav_sidebar_show", "显示侧边栏 (Ctrl+B)"))
        for page_id, spec in self._plugin_page_specs.items():
            button = self.sidebar.nav_button(page_id)
            if button is not None:
                button.setText(t.get(spec.label_key, page_id))
        for feature in get_registry().features:
            feature.apply_texts(self)
        self.sidebar.btn_notice.setText(
            t["notice_short_update"]
            if self.version_info and self.version_info.get("has_update")
            else t["notice_short"]
        )
        if self.version_info and self.version_info.get("has_update"):
            set_button_role(self.sidebar.btn_notice, "AccentGhostButton", chrome="update")
        else:
            set_button_role(self.sidebar.btn_notice, "GhostButton", chrome="sidebarFooter")
        self.sidebar.btn_notice.style().unpolish(self.sidebar.btn_notice)
        self.sidebar.btn_notice.style().polish(self.sidebar.btn_notice)
        self.sidebar.btn_notice.update()
        self.sidebar.btn_about.setText(t["about_short"])
        set_button_role(self.sidebar.btn_about, "GhostButton", chrome="sidebarFooter")
        self.sidebar.btn_about.style().unpolish(self.sidebar.btn_about)
        self.sidebar.btn_about.style().polish(self.sidebar.btn_about)
        self.sidebar.btn_about.update()
        self.sidebar.btn_language.setText(t["language_toggle"])
        self._refresh_sidebar_icon_buttons(t)
        self.sidebar.runtime_hint.hide()
        self.sidebar.runtime_hint.setToolTip("")

    def _apply_texts_search_page(self, t):
        self.search_page.header.title.setText(t["search_page_title"])
        self.search_page.header.subtitle.hide()
        self.search_page.indexing_notice_text.setText(t.get("search_during_indexing_hint", ""))
        self._refresh_search_panel_state()
        self.search_page.preview_title.setText(t["preview_panel"])
        detail_title = getattr(getattr(self.search_page, "preview_panel", None), "detail_title", None)
        if detail_title is not None:
            detail_title.setText(t.get("search_preview_detail", "当前视频"))
        if hasattr(self.search_page, "expanded_chrome"):
            self._ensure_preview_chrome()
        preview_dialog = getattr(self, "_preview_dialog", None)
        apply_preview = getattr(preview_dialog, "apply_texts", None)
        if callable(apply_preview):
            apply_preview(t)
        self.search_page.results_title.setText(t["results_panel"])
        self.search_page.btn_results_view_table.setText(t.get("results_view_table", "列表"))
        self.search_page.btn_results_view_grid.setText(t.get("results_view_grid", "网格"))
        self.search_page.btn_results_view_table.setToolTip(t.get("results_view_table_tip", ""))
        self.search_page.btn_results_view_grid.setToolTip(t.get("results_view_grid_tip", ""))
        self.search_page._apply_search_collapse_label()
        self.search_page.preview_panel.btn_collapse.setToolTip(t.get("preview_card_collapse", "收起预览"))
        self.search_page.btn_preview_restore.setToolTip(t.get("preview_card_expand", "展开预览"))
        self.search_page.results_size_label.setText(t.get("results_size_label", "大小"))
        size_tip = t.get("results_size_tip", "调整每条结果的展示尺寸")
        self.search_page.results_size_label.setToolTip(size_tip)
        self.search_page.results_size_slider.setToolTip(size_tip)
        self.search_page.results_size_value.setToolTip(size_tip)
        self.search_page.btn_preview_back.setText(t.get("search_preview_back", "返回结果"))
        self.search_page.preview_strip_label.setText(t.get("search_preview_strip", "同视频就近候选"))
        self.search_page.preview_strip_label.setToolTip(t.get("search_preview_strip_tip", "双击播放"))
        self.search_page.preview_detail_title.setText(t.get("search_preview_detail", "当前视频"))
        self.search_page.btn_export_tasks.setText(t.get("preview_export_tasks", "Export Tasks"))
        self._update_shot_list_button()
        self._update_preview_action_button_styles()
        self.search_page.text_search.setPlaceholderText(t["search_placeholder"])
        dialogue = getattr(self.search_page, "dialogue_search", None)
        if dialogue is not None:
            dialogue.setPlaceholderText(t.get("search_dialogue_placeholder", "输入字幕里出现过的词或短句..."))
        self._update_mobile_bridge_controls()
        self.search_page.btn_search.setText(t["search"])
        self.search_page.btn_clear.setText(t["clear"])
        filters = getattr(self.search_page, "btn_filters", None)
        if filters is not None:
            filters.setText(t.get("search_filters_toggle", "高级参数"))
            filters.setToolTip(t.get("search_filters_toggle_tip", ""))
        panel = self.search_page.search_panel
        score_hint = t.get("search_min_score_hint", "")
        panel.score_label.setText(t.get("search_min_score_label", "最低相关度"))
        panel.score_label.setToolTip(score_hint)
        panel.score_input.setToolTip(score_hint)
        panel.score_value.setToolTip(score_hint)
        self.search_page.search_scope_label.setText(t.get("search_scope_label", ""))
        self.search_page.skip_edges_label.setText(t.get("search_skip_edges_label", "跳过时段"))
        if hasattr(self, "_refresh_skip_edges_summary"):
            self._refresh_skip_edges_summary()
        panel = getattr(self.search_page, "search_panel", None)
        if panel is not None and hasattr(panel, "relayout_inline_fields"):
            panel.relayout_inline_fields()
        self.search_page.preview_placeholder.setText(t["preview_placeholder"])
        self.result_table.apply_header_labels(t)
        self.search_page.result_view.set_empty_message(t["no_results"])
        self.search_page.results_pager.set_texts(t)
        self.search_controller._sync_results_pager()

    def _apply_texts_link_page(self, t):
        self.link_page.header.title.setText(t["link_page_title"])
        self.link_page.header.subtitle.hide()
        self.link_page.links_input.setPlaceholderText(t["download_links_placeholder"])
        self.link_page.btn_change_dir.setText(t["download_change_dir"])
        cfg = load_config()
        self.link_page.set_download_texts(t)
        self.link_page.set_cookie_file_path(str(cfg.get("download_cookie_file", "") or ""))
        self.video_download_controller.refresh_cookie_admin_hint()
        self.link_page.list_title.setText(t["download_list_title"])
        self.link_page.set_list_headers(t["download_list_headers"])
        self.link_page.btn_probe.setText(t["download_btn_probe"])
        self.link_page.btn_download.setText(t["download_btn_start_all"])
        self.link_page.btn_clear.setText(t["clear"])
        self.link_page.btn_open_dir.setText(t["download_btn_open_dir"])
        self.link_page.btn_clear_legacy.setText(t["download_btn_clear_legacy"])
        self.video_download_controller.refresh_default_dir_label()

    def _apply_texts_library_page(self, t):
        self.library_page.header.title.setText(t["library_page_title"])
        self.library_page.header.subtitle.hide()
        self.library_page.btn_tab_visual.setText(t.get("library_tab_visual", "Videos"))
        self.library_page.btn_tab_dialogue.setText(t.get("library_tab_dialogue", "Dialogue"))
        if getattr(self.library_page, "lbl_mode_caption", None) is not None:
            self.library_page.lbl_mode_caption.setText(
                t.get("library_mode_caption", "Library type")
            )
        if getattr(self.library_page, "lbl_action_caption", None) is not None:
            self.library_page.lbl_action_caption.setText(
                t.get("library_action_caption", "Actions for current type")
            )
        self.library_page.table_title.setText(t["library_table_title"])
        self.library_page.dialogue_table_title.setText(
            t.get("dialogue_library_table_title", "Extracted dialogue")
        )
        if hasattr(self, "_refresh_library_action_hints"):
            self._refresh_library_action_hints()
        else:
            self.library_page.btn_add_lib.setText(t.get("add_folder", "Add Library"))
            self.library_page.btn_remove_lib.setText(t.get("remove_library", "Remove Library"))
            self.library_page.btn_remove_lib.setToolTip(t.get("remove_library_hint", ""))
            self.library_page.lbl_shared_library_hint.hide()
        if hasattr(self, "_refresh_team_client_library_chrome"):
            self._refresh_team_client_library_chrome()
        self.library_page.btn_sync_db.setText(
            t.get("sync_selected_videos", t.get("update_index", "Sync selected"))
        )
        self.library_page.btn_refresh_visual_library.setText(
            t.get("refresh_visual_library", "刷新选中库")
        )
        self.library_page.btn_refresh_visual_library.setToolTip(
            t.get(
                "refresh_visual_library_hint",
                "重新扫描勾选库文件夹，把新拖入的视频登记到列表（不会立刻建索；登记后请再点同步）。",
            )
        )
        self.library_page.visual_video_tree.set_action_texts(
            open_text=t.get("open_folder", "Open"),
            empty_text=t.get("library_list_empty", ""),
            status_template=t.get("library_sync_status", "{ready}/{total} synced"),
            offline_status_text=t.get(
                "library_path_missing_status",
                "Path missing (check then Remove)",
            ),
            header_video=t.get("library_col_video", t.get("search_scope_video_col", "Video")),
            header_count=t.get("library_col_count", "Count"),
            header_status=t.get("library_col_status", "Status"),
            header_action=t.get("library_col_action", "Action"),
            **list_find_text_kwargs(t),
        )
        self.library_page.subtitle_video_tree.set_action_texts(
            open_text=t.get("open_folder", "Open"),
            empty_text=t.get("dialogue_library_empty", ""),
            status_template=t.get("library_extract_status", "{ready}/{total} extracted"),
            offline_status_text=t.get(
                "library_path_missing_status",
                "Path missing (check then Remove)",
            ),
            header_video=t.get("library_col_video", t.get("search_scope_video_col", "Video")),
            header_count=t.get("library_col_count", "Count"),
            header_status=t.get("library_col_status", "Status"),
            header_action=t.get("library_col_action", "Action"),
            **list_find_text_kwargs(t),
        )
        self.library_page.btn_build_dialogue_index.setText(t.get("build_dialogue_index", "Build dialogue index"))
        self.library_page.btn_build_dialogue_index.setToolTip(
            t.get("build_dialogue_index_hint", "")
        )
        self.library_page.btn_reembed_dialogue.setText(
            t.get("reembed_dialogue_index", "Re-embed dialogue vectors")
        )
        self.library_page.btn_reembed_dialogue.setToolTip(
            t.get("reembed_dialogue_index_hint", "")
        )
        self.library_page.btn_clear_dialogue.setText(
            t.get("clear_dialogue_index", "Clear selected subtitles")
        )
        self.library_page.btn_clear_dialogue.setToolTip(
            t.get("clear_dialogue_index_hint", "")
        )
        self.library_page.lbl_subtitle_sample_interval.setText(
            t.get("subtitle_sample_interval", "Frame interval")
        )
        interval_tip = t.get(
            "subtitle_sample_interval_hint",
            "OCR frame sample interval inside speech segments (0.1–6.0s).",
        )
        self.library_page.lbl_subtitle_sample_interval.setToolTip(interval_tip)
        self.library_page.input_subtitle_sample_interval.setToolTip(interval_tip)
        if hasattr(self, "load_subtitle_sample_interval"):
            self.load_subtitle_sample_interval()
        self.library_page.lbl_subtitle_sample_strategy.setText(
            t.get("subtitle_sample_strategy", "Sample strategy")
        )
        strategy_tip = t.get("subtitle_sample_strategy_hint", "")
        self.library_page.lbl_subtitle_sample_strategy.setToolTip(strategy_tip)
        self.library_page.input_subtitle_sample_strategy.setToolTip(strategy_tip)
        if hasattr(self, "load_subtitle_sample_strategy"):
            self.load_subtitle_sample_strategy()
        self.library_page.lbl_subtitle_ocr_batch.setText(
            t.get("subtitle_ocr_batch", "OCR stack")
        )
        batch_tip = t.get(
            "subtitle_ocr_batch_hint",
            "Frames stacked per OCR pass (1–6). 1=per-frame; higher is usually faster, with automatic per-frame fallback if ambiguous.",
        )
        self.library_page.lbl_subtitle_ocr_batch.setToolTip(batch_tip)
        self.library_page.input_subtitle_ocr_batch.setToolTip(batch_tip)
        if hasattr(self, "load_subtitle_ocr_batch"):
            self.load_subtitle_ocr_batch()
        self.library_page.btn_import_subtitle_srt.setText(
            t.get("import_subtitle_srt", "Import")
        )
        self.library_page.btn_import_subtitle_srt.setToolTip(
            t.get("import_subtitle_srt_hint", "")
        )
        self.library_page.btn_export_dialogue.setText(
            t.get("export_dialogue_library", "Export dialogue")
        )
        self.library_page.btn_export_dialogue.setToolTip(
            t.get("export_dialogue_library_hint", "")
        )
        self.library_page.btn_subtitle_sample_advanced.setText(
            t.get("subtitle_sample_advanced", "Advanced")
        )
        self.library_page.btn_refresh_dialogue_library.setText(
            t.get("refresh_dialogue_library", "Refresh")
        )
        self.library_page.btn_refresh_dialogue_library.setToolTip(
            t.get("refresh_dialogue_library_hint", "")
        )
        self.library_page.btn_stop_index.setText(t["stop"])
        self.library_page.btn_stop_dialogue_index.setText(t["stop"])
        self.library_page.btn_index_issues.setText(t["index_issues_button"])
        self.library_page.btn_fix_missing_vectors.setText(t.get("fix_missing_vectors", "修复向量"))
        self.library_page.btn_fix_missing_vectors.setToolTip(
            t.get(
                "fix_missing_vectors_hint",
                "为「向量/索引缺失」且源文件仍在的视频重新嵌入（无需先勾选）。",
            )
        )
        self.library_page.btn_cleanup_missing.setText(t["cleanup_missing_vectors"])
        if hasattr(self, "_refresh_fix_missing_vectors_button"):
            self._refresh_fix_missing_vectors_button()
        self.library_page.btn_remove_selected_videos.setText(
            t.get("remove_selected_videos", "Remove selected videos")
        )
        self.library_page.btn_remove_selected_videos.setToolTip(
            t.get("remove_selected_videos_hint", "")
        )
        self.library_page.btn_vector_details.setText(t["library_vectors_detail"])
        self.library_page.btn_debug_gpu_oom.setText(t["debug_gpu_oom"])
        self.library_page.btn_debug_system_oom.setText(t["debug_system_oom"])
        self.library_page.btn_debug_gpu_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self.library_page.btn_debug_system_oom.setVisible(getattr(self, "_debug_tools_enabled", False))
        self._apply_index_issue_button_state(bool(self._last_index_issues))
        self._refresh_cleanup_missing_button_state(probe=True)

    def _apply_texts_understanding_page(self, t):
        self.understanding_page.header.title.setText(t["understanding_page_title"])
        self.understanding_page.header.set_badge(
            t.get("understanding_page_badge", "Beta"),
            visible=True,
        )
        self.understanding_page.header.badge.setToolTip(
            t.get(
                "understanding_page_badge_tip",
                "Test feature: APIs and storage may still change.",
            )
        )
        self.understanding_page.header.subtitle.hide()
        self.understanding_page.workspace_title.setText(t["understanding_workspace_title"])
        if hasattr(self.understanding_page, "apply_wizard_texts"):
            self.understanding_page.apply_wizard_texts(t)
        if hasattr(self.understanding_page, "select_hint"):
            self.understanding_page.select_hint.setText(
                t.get("understanding_step_select_hint_motion", t.get("understanding_step_select_hint", ""))
            )
        if hasattr(self.understanding_page, "generate_title"):
            self.understanding_page.generate_title.setText(
                t.get("understanding_step_generate_title_motion", "3. Visual understanding")
            )
        if hasattr(self.understanding_page, "export_title"):
            self.understanding_page.export_title.setText(
                t.get("understanding_step_export_title_motion", "4. Edit plan")
            )
        if hasattr(self.understanding_page, "export_hint"):
            self.understanding_page.export_hint.setText(
                t.get("understanding_step_export_hint_motion", t.get("understanding_step_export_hint", ""))
            )
        if hasattr(self.understanding_page, "dialogue_title"):
            self.understanding_page.dialogue_title.setText(
                t.get("understanding_step_dialogue_title_motion", "2. Extract lines")
            )
        if hasattr(self.understanding_page, "dialogue_hint"):
            self.understanding_page.dialogue_hint.setText(
                t.get("understanding_step_dialogue_hint", "")
            )
        if hasattr(self.understanding_page, "btn_open_subtitle_library"):
            self.understanding_page.btn_open_subtitle_library.setText(
                t.get("understanding_step_dialogue_open", "Extract subtitles")
            )
        if hasattr(self.understanding_page, "btn_dialogue_mode_ocr"):
            self.understanding_page.btn_dialogue_mode_ocr.setText(
                t.get("understanding_dialogue_mode_ocr", "Hard subs")
            )
            self.understanding_page.btn_dialogue_mode_ocr.setToolTip(
                t.get(
                    "understanding_dialogue_mode_ocr_tip",
                    "Read burned-in subtitles with local RapidOCR.",
                )
            )
        if hasattr(self.understanding_page, "btn_dialogue_mode_asr"):
            self.understanding_page.btn_dialogue_mode_asr.setText(
                t.get("understanding_dialogue_mode_asr", "No subs")
            )
            self.understanding_page.btn_dialogue_mode_asr.setToolTip(
                t.get(
                    "understanding_dialogue_mode_asr_tip",
                    "Use speech recognition when the picture has no subtitles.",
                )
            )
        if hasattr(self, "_sync_dialogue_extract_label"):
            self._sync_dialogue_extract_label()
        elif hasattr(self.understanding_page, "btn_extract_asr"):
            self.understanding_page.btn_extract_asr.setText(
                t.get("understanding_step_dialogue_extract_asr", "Extract speech")
            )
        if hasattr(self.understanding_page, "btn_cluster_speakers"):
            self.understanding_page.btn_cluster_speakers.setText(
                t.get("understanding_step_dialogue_cluster", "Cluster speakers")
            )
            self.understanding_page.btn_cluster_speakers.setToolTip(
                t.get(
                    "understanding_step_dialogue_cluster_tip",
                    "Fill empty Speaker cells from local CAM++ voice clusters. Manual names are kept.",
                )
            )
        if hasattr(self.understanding_page, "btn_rename_speakers"):
            self.understanding_page.btn_rename_speakers.setText(
                t.get("understanding_step_dialogue_rename", "Rename speakers")
            )
            self.understanding_page.btn_rename_speakers.setToolTip(
                t.get(
                    "understanding_step_dialogue_rename_tip",
                    "Rename every line that shares a speaker label, such as 声线1 → a character name.",
                )
            )
        if hasattr(self.understanding_page, "btn_reset_speakers"):
            self.understanding_page.btn_reset_speakers.setText(
                t.get("understanding_step_dialogue_reset_speakers", "Reset speakers")
            )
            self.understanding_page.btn_reset_speakers.setToolTip(
                t.get(
                    "understanding_step_dialogue_reset_speakers_tip",
                    "Clear every speaker label on this video (including manual names) so you can cluster again.",
                )
            )
        if hasattr(self.understanding_page, "btn_delete_selected_dialogue"):
            self.understanding_page.btn_delete_selected_dialogue.setText(
                t.get("understanding_step_dialogue_delete_selected", "Delete selected")
            )
            self.understanding_page.btn_delete_selected_dialogue.setToolTip(
                t.get(
                    "understanding_step_dialogue_delete_selected_tip",
                    "Delete the checked lines. Edits stay on this page.",
                )
            )
        if hasattr(self.understanding_page, "btn_export_dialogue_json"):
            self.understanding_page.btn_export_dialogue_json.setText(
                t.get("understanding_step_dialogue_export_json", "Export JSON")
            )
        if hasattr(self.understanding_page, "recap_prompt_label"):
            self.understanding_page.recap_prompt_label.setText(
                t.get("understanding_recap_prompt_label", "Recap prompts")
            )
        if hasattr(self.understanding_page, "recap_prompt_hint"):
            self.understanding_page.recap_prompt_hint.setText(
                t.get("understanding_recap_prompt_hint", "")
            )
        if hasattr(self.understanding_page, "btn_reset_recap_prompt"):
            self.understanding_page.btn_reset_recap_prompt.setText(
                t.get("understanding_recap_prompt_reset", "Restore")
            )
        if hasattr(self.understanding_page, "recap_prompt_tabs"):
            tabs = self.understanding_page.recap_prompt_tabs
            tabs.setTabText(0, t.get("understanding_recap_prompt_tab_plan", "1. Plan"))
            tabs.setTabText(1, t.get("understanding_recap_prompt_tab_match", "2. Match"))
            tabs.setTabText(2, t.get("understanding_recap_prompt_tab_captions", "3. Captions"))
            if tabs.count() > 3:
                tabs.setTabText(3, t.get("understanding_recap_prompt_tab_polish", "4. Polish"))
        if hasattr(self.understanding_page, "recap_start_hint"):
            self.understanding_page.recap_start_hint.setText(
                t.get(
                    "understanding_recap_start_hint",
                    "One-click runs all three steps. The step buttons generate or redo that step only.",
                )
            )
        if hasattr(self, "_ensure_recap_prompt_default"):
            self._ensure_recap_prompt_default()
        if hasattr(self.understanding_page, "dialogue_table"):
            self.understanding_page.dialogue_table.apply_header_labels(t)
        if hasattr(self.understanding_page, "recap_review_title"):
            self.understanding_page.recap_review_title.setText(
                t.get("understanding_recap_review_title", "Recap review")
            )
        if hasattr(self.understanding_page, "recap_review_hint"):
            self.understanding_page.recap_review_hint.setText(
                t.get("understanding_recap_review_hint", "")
            )
        stretch_tip = t.get("understanding_stretch_handle_tip", "Drag to resize height")
        for attr in (
            "_dialogue_table_stretch",
            "_recap_review_stretch",
            "_chunk_caption_stretch",
            "_vlm_prompt_stretch",
            "_recap_prompt_stretch",
        ):
            handle = getattr(self.understanding_page, attr, None)
            if handle is not None and hasattr(handle, "set_tooltip_text"):
                handle.set_tooltip_text(stretch_tip)
        if hasattr(self.understanding_page, "btn_edit_recap_unit_vo"):
            self.understanding_page.btn_edit_recap_unit_vo.setText(
                t.get("understanding_recap_review_edit_action", "Edit VO")
            )
            self.understanding_page.btn_edit_recap_unit_vo.setToolTip(
                t.get("understanding_recap_review_edit_tip", "")
            )
        if hasattr(self.understanding_page, "btn_recap_shot_up"):
            self.understanding_page.btn_recap_shot_up.setText(
                t.get("understanding_recap_review_shot_up", "Move up")
            )
        if hasattr(self.understanding_page, "btn_recap_shot_down"):
            self.understanding_page.btn_recap_shot_down.setText(
                t.get("understanding_recap_review_shot_down", "Move down")
            )
        if hasattr(self.understanding_page, "btn_add_recap_shot"):
            self.understanding_page.btn_add_recap_shot.setText(
                t.get("understanding_recap_review_add_shot", "Add shot")
            )
            self.understanding_page.btn_add_recap_shot.setToolTip(
                t.get("understanding_recap_review_add_shot_tip", "")
            )
        if hasattr(self.understanding_page, "btn_delete_recap"):
            self.understanding_page.btn_delete_recap.setText(
                t.get("understanding_recap_review_delete_action", "Delete")
            )
            self.understanding_page.btn_delete_recap.setToolTip(
                t.get("understanding_recap_review_delete_tip", "")
            )
        if hasattr(self.understanding_page, "recap_review_tree"):
            headers = t.get(
                "understanding_recap_review_headers",
                ["Unit", "Recap", "Source", "VO / role"],
            )
            if isinstance(headers, (list, tuple)) and len(headers) >= 4:
                self.understanding_page.recap_review_tree.setHeaderLabels(
                    [str(headers[0]), str(headers[1]), str(headers[2]), str(headers[3])]
                )
        cfg = self._understanding_config_widgets()
        dialog = getattr(self, "understanding_services_dialog", None)
        if dialog is not None:
            dialog.apply_texts(t)
        cfg.label_vlm_provider_mode.setText(t["understanding_vlm_provider_mode_label"])
        cfg.input_vlm_provider_mode.setToolTip(t["understanding_vlm_provider_mode_hint"])
        current_vlm_mode = cfg.input_vlm_provider_mode.currentData()
        self._populate_vlm_provider_mode_options(current_vlm_mode or "local")
        cfg.label_vlm_provider_preset.setText(t["understanding_vlm_provider_preset_label"])
        cfg.input_vlm_provider_preset.setToolTip(t["understanding_vlm_provider_preset_hint"])
        current_vlm_preset = cfg.input_vlm_provider_preset.currentData()
        self._populate_vlm_provider_preset_options(current_vlm_mode or "local", current_vlm_preset or "lm_studio")
        self._sync_vlm_provider_ui()
        cfg.label_remote_vlm_base_url.setText(t["setting_remote_vlm_base_url"])
        cfg.input_remote_vlm_base_url.setToolTip(t["setting_remote_vlm_base_url_hint"])
        cfg.label_remote_vlm_api_key.setText(t["setting_remote_vlm_api_key"])
        cfg.input_remote_vlm_api_key.setToolTip(t["setting_remote_vlm_api_key_hint"])
        cfg.label_remote_vlm_model.setText(t["setting_remote_vlm_model"])
        cfg.input_remote_vlm_model.setToolTip(t["setting_remote_vlm_model_hint"])
        self.understanding_page.label_caption_language.setText(t["understanding_caption_language_label"])
        current_language = self.understanding_page.input_caption_language.currentData()
        self._populate_understanding_caption_language_options(current_language or "zh")
        self.understanding_page.input_caption_language.setToolTip(t["understanding_caption_language_hint"])
        if hasattr(self.understanding_page, "mode_label"):
            self.understanding_page.mode_label.setText(t.get("understanding_mode_label", "Mode"))
        if hasattr(self.understanding_page, "mode_hint"):
            self.understanding_page.mode_hint.setText(t.get("understanding_mode_hint", ""))
        if hasattr(self.understanding_page, "input_understanding_mode"):
            current_mode = self.understanding_page.input_understanding_mode.currentData()
            self._populate_understanding_mode_options(current_mode or "tags")
        cfg.label_caption_concurrency.setText(t["understanding_caption_concurrency_label"])
        cfg.input_caption_concurrency.setToolTip(t["understanding_caption_concurrency_hint"])
        if hasattr(self.understanding_page, "vlm_prompt_label"):
            self.understanding_page.vlm_prompt_label.setText(
                t.get("understanding_vlm_prompt_label", t.get("understanding_use_custom_prompts", "Vision prompts"))
            )
        if hasattr(self.understanding_page, "vlm_prompt_hint"):
            self.understanding_page.vlm_prompt_hint.setText(
                t.get("understanding_vlm_prompt_hint", t.get("understanding_custom_prompts_hint", ""))
            )
        if hasattr(self.understanding_page, "btn_reset_custom_prompts"):
            self.understanding_page.btn_reset_custom_prompts.setText(
                t.get(
                    "understanding_vlm_prompt_reset",
                    t.get("understanding_reset_custom_prompts", "Restore"),
                )
            )
        if hasattr(self.understanding_page, "vlm_prompt_tabs"):
            tabs = self.understanding_page.vlm_prompt_tabs
            tabs.setTabText(
                0,
                t.get(
                    "understanding_vlm_prompt_tab_tag",
                    t.get("understanding_custom_tag_prompt_label", t["understanding_custom_caption_prompt_label"]),
                ),
            )
            tabs.setTabText(
                1,
                t.get(
                    "understanding_vlm_prompt_tab_motion",
                    t.get("understanding_custom_motion_prompt_label", "Segment change"),
                ),
            )
        if hasattr(self.understanding_page, "btn_open_services"):
            self.understanding_page.btn_open_services.setText(
                t.get("understanding_open_services", t.get("understanding_config_title", "Model services"))
            )
        self.understanding_page.scope_label.setText(t["understanding_scope_label"])
        self.understanding_page.video_label.setText(t["understanding_video_label"])
        self.understanding_page.timeline_label.setText(t["understanding_timeline_label"])
        self.understanding_page.timeline_hint.setText(t["understanding_timeline_hint"])
        self.understanding_page.chunk_preview_label.setText(
            t.get("understanding_chunk_preview_title", "This segment")
        )
        self.understanding_page.btn_chunk_preview_close.setText(
            t.get("understanding_chunk_preview_close", "Close preview")
        )
        layer = getattr(self.understanding_page, "embedded_preview", None)
        if layer is not None and hasattr(layer, "btn_preview_back"):
            layer.btn_preview_back.setText(t.get("understanding_preview_back", "Back to understanding"))
        if getattr(self, "_understanding_preview_embedded", False) or getattr(self, "_search_preview_embedded", False):
            self._sync_preview_layer_chrome()
        self.understanding_page.btn_evidence_details.setText(t["library_evidence_detail"])
        self.understanding_page.btn_export_video_json.setText(t["understanding_export_video_json"])
        self.understanding_page.btn_export_recap.setText(t.get("understanding_export_recap", "Recap"))
        self.understanding_page.btn_export_recap.setToolTip(
            t.get("understanding_export_recap_tip", "")
        )
        if hasattr(self.understanding_page, "btn_recap_step_plan"):
            self.understanding_page.btn_recap_step_plan.setText(
                t.get("understanding_recap_step_plan", "Plan")
            )
            self.understanding_page.btn_recap_step_plan.setToolTip(
                t.get("understanding_recap_step_plan_tip", "")
            )
        if hasattr(self.understanding_page, "btn_recap_step_match"):
            self.understanding_page.btn_recap_step_match.setText(
                t.get("understanding_recap_step_match", "Match")
            )
            self.understanding_page.btn_recap_step_match.setToolTip(
                t.get("understanding_recap_step_match_tip", "")
            )
        if hasattr(self.understanding_page, "btn_recap_step_captions"):
            self.understanding_page.btn_recap_step_captions.setText(
                t.get("understanding_recap_step_captions", "Captions")
            )
            self.understanding_page.btn_recap_step_captions.setToolTip(
                t.get("understanding_recap_step_captions_tip", "")
            )
        if hasattr(self.understanding_page, "btn_edit_recap_beats"):
            self.understanding_page.btn_edit_recap_beats.setText(
                t.get("understanding_recap_edit_beats", "Edit plan")
            )
            self.understanding_page.btn_edit_recap_beats.setToolTip(
                t.get("understanding_recap_edit_beats_tip", "")
            )
        if hasattr(self.understanding_page, "btn_recap_jianying"):
            self.understanding_page.btn_recap_jianying.setText(
                t.get("understanding_recap_jianying", "Jianying")
            )
            self.understanding_page.btn_recap_jianying.setToolTip(
                t.get("understanding_recap_jianying_tip", "")
            )
        if hasattr(self.understanding_page, "btn_recap_fcpxml"):
            self.understanding_page.btn_recap_fcpxml.setText(
                t.get("understanding_recap_fcpxml", "Export FCPXML")
            )
            self.understanding_page.btn_recap_fcpxml.setToolTip(
                t.get("understanding_recap_fcpxml_tip", "")
            )
        self.understanding_page.btn_understanding_setup.setText(t["understanding_setup_action"])
        self.understanding_page.btn_stop.setText(t["stop"])
        if hasattr(self.understanding_page, "btn_stop_asr"):
            self.understanding_page.btn_stop_asr.setText(t["stop"])
        self._sync_understanding_mode_ui(
            reload_dialogue=self._is_current_page("understanding")
        )
        if self._is_current_page("understanding"):
            if hasattr(self, "_refresh_understanding_page_fast"):
                self._refresh_understanding_page_fast()
        else:
            self._refresh_understanding_ui()
            if hasattr(self, "_refresh_understanding_settings_status"):
                self._refresh_understanding_settings_status()

    def _apply_texts_settings_and_finish(self, t, config):
        self.settings_page.header.title.setText(t["settings_page_title"])
        self.settings_page.header.subtitle.hide()
        self.settings_page.general_title.setText(t["settings_group_title"])
        self.settings_page.btn_save.setText(t["save_settings"])
        self.settings_page.btn_reset.setText(t["reset_settings"])
        self.settings_page.configure_form_labels(t)
        self.refresh_search_telemetry_panel()
        if hasattr(self, "_rebuild_tray_menu"):
            self._rebuild_tray_menu()
        self.push_inference_status()
        self._refresh_pending_cleanup_actions(config)

        if not self.current_img_path and not self.search_page.img_label.pixmap():
            self.search_page.img_label.setText(t["image_drop_hint"])
        if hasattr(self.search_page.img_label, "set_caption"):
            self.search_page.img_label.set_caption(t.get("image_upload_label", "选择图片 / 拖入图片"))
        if hasattr(self.search_page.img_label, "set_clear_tip"):
            self.search_page.img_label.set_clear_tip(t.get("image_query_clear", "移除图片"))

        self.search_page.lbl_status.setText(t["ready"])
        self.library_page.lbl_status.setText(t["ready"])
        if not (
            getattr(self, "understanding_controller", None)
            and self.understanding_controller.is_running()
        ):
            self.understanding_page.lbl_status.setText(t["ready"])
        self.settings_page.lbl_status.setText(t["settings_hint"])
        self._bind_sampling_preview_signals()
        self._update_sampling_preview()
        if hasattr(self, "push_resources_status"):
            self.push_resources_status()
        if self._startup_complete:
            self.refresh_library_table()
            self.refresh_search_presets_ui()

