"""Search panel tab state, visibility, and flow hints."""

from __future__ import annotations

from src.storage.config_store import get_search_scope_library_paths


class SearchPanelStateMixin:
    SEARCH_TAB_IMAGE = "image"
    SEARCH_TAB_TEXT = "text"
    SEARCH_TAB_COMPOSE = "compose"
    SEARCH_TAB_DIALOGUE = "dialogue"

    IMAGE_SEARCH_MODES = ("chunk", "frame", "video_discovery", "precise")

    def _search_has_image_query(self) -> bool:
        return bool(str(getattr(self, "current_img_path", "") or "").strip())

    def _search_has_text_query(self) -> bool:
        if not hasattr(self, "search_page"):
            return False
        return bool(self.search_page.search_panel.text_query())

    def _search_has_dialogue_query(self) -> bool:
        if not hasattr(self, "search_page"):
            return False
        return bool(self.search_page.search_panel.dialogue_query())

    def _search_has_compose_query(self) -> bool:
        if not hasattr(self, "search_page"):
            return False
        compose_form = getattr(self.search_page.search_panel, "compose_form", None)
        if compose_form is None:
            return False
        return compose_form.has_content()

    def _search_active_tab(self) -> str:
        if not hasattr(self, "search_page"):
            return self.SEARCH_TAB_IMAGE
        tabs = getattr(self.search_page, "search_query_tabs", None)
        if tabs is None:
            return self.SEARCH_TAB_IMAGE
        index = int(tabs.currentIndex())
        if index == 1:
            return self.SEARCH_TAB_TEXT
        if index == 2:
            return self.SEARCH_TAB_COMPOSE
        if index == 3:
            return self.SEARCH_TAB_DIALOGUE
        return self.SEARCH_TAB_IMAGE

    def _set_search_query_tab(self, tab: str) -> None:
        if not hasattr(self, "search_page"):
            return
        tabs = getattr(self.search_page, "search_query_tabs", None)
        if tabs is None:
            return
        normalized = str(tab or "").strip().lower()
        if normalized == self.SEARCH_TAB_TEXT:
            target = 1
        elif normalized == self.SEARCH_TAB_COMPOSE:
            target = 2
        elif normalized == self.SEARCH_TAB_DIALOGUE:
            target = 3
        else:
            target = 0
        if tabs.currentIndex() != target:
            tabs.setCurrentIndex(target)

    def _search_input_world(self) -> str:
        tab = self._search_active_tab()
        if tab == self.SEARCH_TAB_TEXT:
            return "text" if self._search_has_text_query() else "empty"
        if tab == self.SEARCH_TAB_COMPOSE:
            return "compose" if self._search_has_compose_query() else "empty"
        if tab == self.SEARCH_TAB_DIALOGUE:
            return "dialogue" if self._search_has_dialogue_query() else "empty"
        return "image" if self._search_has_image_query() else "empty"

    def _search_scope_is_global(self) -> bool:
        if not self._search_scope_picker_available():
            return True
        if getattr(self, "_search_scope_mode", "all") != "selected":
            return True
        if getattr(self, "_search_scope_video_paths", None):
            return False
        return not bool(get_search_scope_library_paths())

    def _text_search_mode_from_ui(self) -> str:
        if hasattr(self, "search_page"):
            mode = str(self.search_page.search_mode.currentData() or "").strip().lower()
            if mode == "chunk":
                return "chunk"
            if mode == "frame":
                return "frame"
        from src.storage.config_store import get_search_mode

        resolved = str(get_search_mode() or "frame").strip().lower()
        return "chunk" if resolved == "chunk" else "frame"

    def _image_search_mode_from_ui(self) -> str:
        if hasattr(self, "search_page"):
            mode = str(self.search_page.image_search_mode.currentData() or "").strip().lower()
            if mode in self.IMAGE_SEARCH_MODES:
                return mode
        from src.storage.config_store import get_image_search_mode

        return get_image_search_mode()

    def _set_image_search_mode_ui(self, mode: str) -> None:
        normalized = str(mode or "frame").strip().lower()
        if normalized not in self.IMAGE_SEARCH_MODES:
            normalized = "frame"
        combo = self.search_page.image_search_mode
        combo.blockSignals(True)
        index = combo.findData(normalized)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _set_search_precision_mode_ui(self, mode: str) -> None:
        self._set_search_query_tab(self.SEARCH_TAB_IMAGE)
        if str(mode or "").strip().lower() == "precise":
            self._set_image_search_mode_ui("precise")
        else:
            self._set_image_search_mode_ui("frame")
        self._refresh_search_panel_state()

    def _search_precision_effective(self, *, is_text: bool, has_image: bool) -> bool:
        if is_text and not has_image:
            return False
        return bool(has_image)

    def _resolve_search_precision_mode(self, *, is_text: bool, has_image: bool) -> str:
        if not self._search_precision_effective(is_text=is_text, has_image=has_image):
            return "fast"
        return "precise" if self._image_search_mode_from_ui() == "precise" else "fast"

    def _resolve_video_discovery_enabled(self, *, is_text: bool, has_image: bool) -> bool:
        if is_text or not has_image:
            return False
        return self._image_search_mode_from_ui() == "video_discovery"

    def _resolve_effective_search_mode(
        self,
        *,
        is_text: bool,
        has_image: bool,
        search_precision_mode: str | None = None,
    ) -> str:
        if is_text and not has_image:
            from src.services.search_scope import resolve_active_search_mode

            return resolve_active_search_mode()
        image_mode = self._image_search_mode_from_ui()
        if image_mode in {"video_discovery", "precise"}:
            return "frame"
        return image_mode

    def _populate_text_search_mode_combo(self) -> None:
        if not hasattr(self, "search_page"):
            return
        page = self.search_page
        texts = getattr(self, "texts", {}) or {}
        current_mode = page.search_mode.currentData()
        page.search_mode.blockSignals(True)
        page.search_mode.clear()
        page.search_mode.addItem(texts.get("setting_search_mode_frame", "Frame"), "frame")
        page.search_mode.addItem(texts.get("setting_search_mode_chunk", "Chunk"), "chunk")
        target = "chunk" if current_mode == "chunk" else "frame"
        target_index = page.search_mode.findData(target)
        if target_index >= 0:
            page.search_mode.setCurrentIndex(target_index)
        page.search_mode.blockSignals(False)

    def _populate_text_search_enhance_combo(self) -> None:
        if not hasattr(self, "search_page"):
            return
        page = self.search_page
        combo = getattr(page, "text_search_enhance", None)
        label = getattr(page, "text_search_enhance_label", None)
        if combo is None:
            return
        texts = getattr(self, "texts", {}) or {}
        from src.storage.config_store import get_text_search_enhance_enabled

        enabled = bool(get_text_search_enhance_enabled())
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(
            texts.get("setting_text_search_enhance_enabled_option_off", "Off"),
            False,
        )
        combo.addItem(
            texts.get("setting_text_search_enhance_enabled_option_on", "On"),
            True,
        )
        restore = combo.findData(enabled)
        combo.setCurrentIndex(0 if restore < 0 else restore)
        combo.blockSignals(False)
        if label is not None:
            label.setText(
                texts.get(
                    "search_text_enhance_label",
                    texts.get("setting_text_search_enhance_enabled", ""),
                )
            )
        hint = texts.get(
            "search_text_enhance_hint",
            texts.get("setting_text_search_enhance_enabled_hint", ""),
        )
        if label is not None:
            label.setToolTip(hint)
        combo.setToolTip(hint)

    def _set_text_search_enhance_ui(self, enabled: bool) -> None:
        if not hasattr(self, "search_page"):
            return
        combo = getattr(self.search_page, "text_search_enhance", None)
        if combo is None:
            return
        if combo.count() <= 0:
            self._populate_text_search_enhance_combo()
        combo.blockSignals(True)
        index = combo.findData(bool(enabled))
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def _populate_image_search_mode_combo(self) -> None:
        if not hasattr(self, "search_page"):
            return
        page = self.search_page
        texts = getattr(self, "texts", {}) or {}
        current_mode = page.image_search_mode.currentData()
        page.image_search_mode.blockSignals(True)
        page.image_search_mode.clear()
        labels = {
            "chunk": texts.get("search_image_mode_chunk", texts.get("setting_search_mode_chunk", "Chunk")),
            "frame": texts.get("search_image_mode_frame", texts.get("setting_search_mode_frame", "Frame")),
            "video_discovery": texts.get("search_image_mode_video_discovery", texts.get("search_video_discovery_label", "Best per video")),
            "precise": texts.get("search_image_mode_precise", texts.get("search_precision_label", "Deep search")),
        }
        for mode in self.IMAGE_SEARCH_MODES:
            page.image_search_mode.addItem(labels[mode], mode)
        normalized = str(current_mode or "frame").strip().lower()
        if normalized not in self.IMAGE_SEARCH_MODES:
            normalized = "frame"
        target_index = page.image_search_mode.findData(normalized)
        if target_index >= 0:
            page.image_search_mode.setCurrentIndex(target_index)
        page.image_search_mode.blockSignals(False)

    def _populate_dialogue_search_mode_combo(self) -> None:
        if not hasattr(self, "search_page"):
            return
        page = self.search_page
        combo = getattr(page, "dialogue_search_mode", None)
        if combo is None:
            return
        texts = getattr(self, "texts", {}) or {}
        current_mode = str(combo.currentData() or "").strip().lower()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(texts.get("search_dialogue_match_exact", "Exact"), "exact")
        combo.addItem(texts.get("search_dialogue_match_fuzzy", "Fuzzy"), "fuzzy")
        # Prefer preserved selection; migrate legacy "segment" → exact.
        if current_mode in {"fuzzy", "tolerant", "approx"}:
            target = "fuzzy"
        else:
            target = "exact"
        target_index = combo.findData(target)
        if target_index >= 0:
            combo.setCurrentIndex(target_index)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
        cluster = getattr(page, "dialogue_search_mode_cluster", None)
        if cluster is not None:
            cluster.setVisible(True)
        label = getattr(page, "dialogue_search_mode_label", None)
        if label is not None:
            label.setText(texts.get("search_dialogue_match_label", "Match mode"))

    def _dialogue_match_mode_from_ui(self) -> str:
        if not hasattr(self, "search_page"):
            return "exact"
        combo = getattr(self.search_page, "dialogue_search_mode", None)
        if combo is None:
            return "exact"
        mode = str(combo.currentData() or "exact").strip().lower()
        if mode in {"fuzzy", "tolerant", "approx"}:
            return "fuzzy"
        return "exact"

    def _refresh_search_panel_state(self, *, refresh_scope: bool = True) -> None:
        if not hasattr(self, "search_page"):
            return

        if refresh_scope:
            self._refresh_search_scope_ui()

        page = self.search_page
        texts = getattr(self, "texts", {}) or {}
        tabs = getattr(page, "search_query_tabs", None)
        active_tab = self._search_active_tab()
        if tabs is not None:
            tabs.setTabText(0, texts.get("search_tab_image", "Image"))
            tabs.setTabText(1, texts.get("search_tab_text", "Text"))
            tabs.setTabText(2, texts.get("search_tab_compose", "Compose"))
            if tabs.count() > 3:
                tabs.setTabText(3, texts.get("search_tab_dialogue", "Dialogue"))

        compose_form = getattr(page.search_panel, "compose_form", None)
        if compose_form is not None:
            compose_form.set_texts(texts)

        btn_save_preset = getattr(page.search_panel, "btn_save_preset", None)
        if btn_save_preset is not None:
            btn_save_preset.setText(texts.get("search_compose_save_preset", "Save as preset"))
            btn_save_preset.setVisible(active_tab == self.SEARCH_TAB_COMPOSE)

        mode_stack = getattr(page, "search_mode_options_stack", None)
        if mode_stack is not None:
            if active_tab in {self.SEARCH_TAB_TEXT, self.SEARCH_TAB_COMPOSE}:
                # Compose only needs frame/chunk granularity (same control as text).
                mode_stack.setCurrentIndex(0)
            elif active_tab == self.SEARCH_TAB_IMAGE:
                mode_stack.setCurrentIndex(1)
            elif active_tab == self.SEARCH_TAB_DIALOGUE:
                mode_stack.setCurrentIndex(3)
            else:
                mode_stack.setCurrentIndex(2)

        if active_tab in {self.SEARCH_TAB_TEXT, self.SEARCH_TAB_COMPOSE}:
            page.search_mode_label.setText(texts.get("setting_search_mode", ""))
            self._populate_text_search_mode_combo()
            hint = texts.get("search_text_mode_hint", texts.get("search_mode_hint", ""))
            page.search_mode_label.setToolTip(hint)
            page.search_mode.setToolTip(hint)
            enhance_combo = getattr(page, "text_search_enhance", None)
            enhance_label = getattr(page, "text_search_enhance_label", None)
            show_enhance = active_tab in {self.SEARCH_TAB_TEXT, self.SEARCH_TAB_COMPOSE}
            if enhance_combo is not None:
                enhance_combo.setVisible(show_enhance)
            if enhance_label is not None:
                enhance_label.setVisible(show_enhance)
            cluster = getattr(page, "text_granularity_cluster", None)
            panel = getattr(page, "search_panel", None)
            if cluster is not None and panel is not None:
                width = (
                    getattr(panel, "_text_options_width_with_enhance", None)
                    if show_enhance
                    else getattr(panel, "_text_options_width_mode_only", None)
                )
                if width:
                    cluster.setFixedWidth(int(width))
            if show_enhance:
                self._populate_text_search_enhance_combo()

        if active_tab == self.SEARCH_TAB_IMAGE:
            page.image_search_mode_label.setText(texts.get("search_image_mode_label", texts.get("setting_search_mode", "")))
            self._populate_image_search_mode_combo()
            hint = texts.get("search_image_mode_hint", "")
            page.image_search_mode_label.setToolTip(hint)
            page.image_search_mode.setToolTip(hint)

        if active_tab == self.SEARCH_TAB_DIALOGUE:
            self._populate_dialogue_search_mode_combo()
            dialogue_mode = getattr(page, "dialogue_search_mode", None)
            mode = self._dialogue_match_mode_from_ui()
            hint_key = (
                "search_dialogue_match_fuzzy_hint"
                if mode == "fuzzy"
                else "search_dialogue_match_exact_hint"
            )
            tip = texts.get(
                hint_key,
                texts.get("search_dialogue_match_segment_hint", ""),
            )
            if dialogue_mode is not None:
                dialogue_mode.setToolTip(tip)
            label = getattr(page, "dialogue_search_mode_label", None)
            if label is not None:
                label.setToolTip(tip)

        dialogue_hint = getattr(page, "lbl_dialogue_hint", None)
        if dialogue_hint is not None:
            dialogue_hint.setText(self._dialogue_search_hint_text(texts))
            dialogue_hint.setVisible(active_tab == self.SEARCH_TAB_DIALOGUE)

        self._refresh_search_model_display()

    def _dialogue_search_hint_text(self, texts) -> str:
        mode = self._dialogue_match_mode_from_ui()
        if mode == "fuzzy":
            fallback = texts.get(
                "search_dialogue_match_fuzzy_hint",
                "Fuzzy match: complete query spans first, then single-char hit rate.",
            )
            ready_key = "search_dialogue_match_fuzzy_hint_ready"
        else:
            fallback = texts.get(
                "search_dialogue_match_exact_hint",
                texts.get(
                    "search_dialogue_match_segment_hint",
                    "Exact substring match on OCR subtitle text.",
                ),
            )
            ready_key = "search_dialogue_match_exact_hint_ready"
        try:
            import time

            from src.storage.lance_dialogue_search import get_dialogue_index_stats

            # Typing/tab switches must not re-walk all transcript files.
            now = time.monotonic()
            cached = getattr(self, "_dialogue_stats_cache", None)
            if cached and (now - float(cached.get("at", 0.0))) < 30.0:
                indexed = int(cached.get("indexed") or 0)
            else:
                stats = get_dialogue_index_stats()
                indexed = int(stats.get("dialogue_indexed_videos") or 0)
                self._dialogue_stats_cache = {"at": now, "indexed": indexed}
            if indexed > 0:
                return texts.get(ready_key, fallback).format(count=indexed)
        except Exception:
            pass
        return fallback

    def _refresh_search_model_display(self) -> None:
        if not hasattr(self, "search_page"):
            return
        texts = getattr(self, "texts", {}) or {}
        page = self.search_page
        active_tab = self._search_active_tab()
        try:
            from src.app.config import load_config
            from src.services.model_profile_display import (
                format_active_model_search_label,
                format_text_search_model_hint,
            )

            # Always keep this label visible with stable text so tab switches
            # do not resize the search panel.
            page.lbl_active_model.setVisible(True)
            if active_tab == self.SEARCH_TAB_DIALOGUE:
                page.lbl_active_model.setText(
                    texts.get(
                        "search_dialogue_runtime_label",
                        "Subtitle search (global library, no CLIP required)",
                    )
                )
                page.lbl_text_model_hint.setVisible(False)
                return

            config = load_config()
            model_label = format_active_model_search_label(config)
            page.lbl_active_model.setText(
                texts.get("search_active_model", "Active model: {model}").format(model=model_label)
            )
            hint = format_text_search_model_hint(texts, config=config)
            page.lbl_text_model_hint.setText(hint)
            page.lbl_text_model_hint.setVisible(bool(hint) and active_tab == self.SEARCH_TAB_TEXT)
        except Exception:
            page.lbl_active_model.setText(
                texts.get(
                    "search_dialogue_runtime_label",
                    "Subtitle search (global library, no CLIP required)",
                )
                if active_tab == self.SEARCH_TAB_DIALOGUE
                else ""
            )
            page.lbl_active_model.setVisible(True)
            page.lbl_text_model_hint.setVisible(False)

    def _refresh_search_precision_controls(self) -> None:
        self._refresh_search_panel_state()

    def _on_search_query_tab_changed(self, _index: int = 0) -> None:
        self._refresh_search_panel_state()
        if hasattr(self, "_refresh_search_scope_ui"):
            self._refresh_search_scope_ui(force_entries=True)

    def _on_search_mode_changed(self) -> None:
        self._save_search_mode()
        self._refresh_search_panel_state()

    def _on_text_search_enhance_changed(self) -> None:
        self._save_text_search_enhance()
        self._refresh_search_panel_state()

    def _on_image_search_mode_changed(self) -> None:
        self._save_image_search_mode()
        self._refresh_search_panel_state()

    def _on_dialogue_search_mode_changed(self) -> None:
        self._refresh_search_panel_state()

    def open_compose_search_tab(self) -> None:
        self.switch_page("search")
        self._set_search_query_tab(self.SEARCH_TAB_COMPOSE)
        self._refresh_search_panel_state()
