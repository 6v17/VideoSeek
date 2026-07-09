"""Search panel tab state, visibility, and flow hints."""

from __future__ import annotations

from src.storage.config_store import get_search_scope_library_paths


class SearchPanelStateMixin:
    SEARCH_TAB_IMAGE = "image"
    SEARCH_TAB_TEXT = "text"
    SEARCH_TAB_COMPOSE = "compose"

    IMAGE_SEARCH_MODES = ("chunk", "frame", "video_discovery", "precise")

    def _search_has_image_query(self) -> bool:
        return bool(str(getattr(self, "current_img_path", "") or "").strip())

    def _search_has_text_query(self) -> bool:
        if not hasattr(self, "search_page"):
            return False
        return bool(self.search_page.search_panel.text_query())

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
        return "image" if self._search_has_image_query() else "empty"

    def _search_scope_is_global(self) -> bool:
        if not self._search_scope_picker_available():
            return True
        if getattr(self, "_search_scope_mode", "all") != "selected":
            return True
        if getattr(self, "_search_scope_video_paths", None):
            return False
        return not bool(get_search_scope_library_paths())

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
        if self._image_search_mode_from_ui() != "video_discovery":
            return False
        if not self._search_scope_is_global():
            return False
        return True

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

    def _refresh_search_panel_state(self) -> None:
        if not hasattr(self, "search_page"):
            return

        self._refresh_search_scope_ui()

        page = self.search_page
        texts = getattr(self, "texts", {}) or {}
        tabs = getattr(page, "search_query_tabs", None)
        active_tab = self._search_active_tab()
        if tabs is not None:
            tabs.setTabText(0, texts.get("search_tab_image", "Image"))
            tabs.setTabText(1, texts.get("search_tab_text", "Text"))
            tabs.setTabText(2, texts.get("search_tab_compose", "Compose"))

        compose_form = getattr(page.search_panel, "compose_form", None)
        if compose_form is not None:
            compose_form.set_texts(texts)

        btn_save_preset = getattr(page.search_panel, "btn_save_preset", None)
        if btn_save_preset is not None:
            btn_save_preset.setText(texts.get("search_compose_save_preset", "Save as preset"))
            btn_save_preset.setVisible(active_tab == self.SEARCH_TAB_COMPOSE)

        mode_stack = getattr(page, "search_mode_options_stack", None)
        if mode_stack is not None:
            if active_tab == self.SEARCH_TAB_TEXT:
                mode_stack.setCurrentIndex(0)
            elif active_tab == self.SEARCH_TAB_IMAGE:
                mode_stack.setCurrentIndex(1)
            else:
                mode_stack.setCurrentIndex(2)

        if active_tab == self.SEARCH_TAB_TEXT:
            page.search_mode_label.setText(texts.get("setting_search_mode", ""))
            self._populate_text_search_mode_combo()
            hint = texts.get("search_text_mode_hint", texts.get("search_mode_hint", ""))
            page.search_mode_label.setToolTip(hint)
            page.search_mode.setToolTip(hint)

        if active_tab == self.SEARCH_TAB_IMAGE:
            page.image_search_mode_label.setText(texts.get("search_image_mode_label", texts.get("setting_search_mode", "")))
            self._populate_image_search_mode_combo()
            hint = texts.get("search_image_mode_hint", "")
            page.image_search_mode_label.setToolTip(hint)
            page.image_search_mode.setToolTip(hint)

        self._refresh_search_model_display()

    def _refresh_search_model_display(self) -> None:
        if not hasattr(self, "search_page"):
            return
        texts = getattr(self, "texts", {}) or {}
        page = self.search_page
        try:
            from src.app.config import load_config
            from src.services.model_profile_display import (
                format_active_model_search_label,
                format_text_search_model_hint,
            )

            config = load_config()
            model_label = format_active_model_search_label(config)
            page.lbl_active_model.setText(
                texts.get("search_active_model", "Active model: {model}").format(model=model_label)
            )
            hint = format_text_search_model_hint(texts, config=config)
            page.lbl_text_model_hint.setText(hint)
            page.lbl_text_model_hint.setVisible(bool(hint) and self._search_active_tab() == self.SEARCH_TAB_TEXT)
        except Exception:
            page.lbl_active_model.setText("")
            page.lbl_text_model_hint.setVisible(False)

    def _refresh_search_precision_controls(self) -> None:
        self._refresh_search_panel_state()

    def _on_search_query_tab_changed(self, _index: int = 0) -> None:
        self._refresh_search_panel_state()

    def _on_search_mode_changed(self) -> None:
        self._save_search_mode()
        self._refresh_search_panel_state()

    def _on_image_search_mode_changed(self) -> None:
        self._save_image_search_mode()
        self._refresh_search_panel_state()

    def open_compose_search_tab(self) -> None:
        self.switch_page("search")
        self._set_search_query_tab(self.SEARCH_TAB_COMPOSE)
        self._refresh_search_panel_state()
