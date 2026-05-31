"""Search panel tab state, visibility, and flow hints."""

from __future__ import annotations

from src.storage.config_store import get_search_scope_library_paths


class SearchPanelStateMixin:
    SEARCH_TAB_IMAGE = "image"
    SEARCH_TAB_TEXT = "text"
    SEARCH_TAB_COMPOSE = "compose"

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

    def _search_precision_mode_from_ui(self) -> str:
        toggle = self.search_page.search_precision_toggle
        return "precise" if toggle.isChecked() else "fast"

    def _set_search_precision_mode_ui(self, mode: str) -> None:
        self._set_search_query_tab(self.SEARCH_TAB_IMAGE)
        toggle = self.search_page.search_precision_toggle
        toggle.blockSignals(True)
        toggle.setChecked(str(mode or "").strip().lower() == "precise")
        toggle.blockSignals(False)
        self._refresh_search_panel_state()

    def _update_search_precision_toggle_ui(self) -> None:
        if not hasattr(self, "search_page"):
            return
        texts = getattr(self, "texts", {}) or {}
        toggle = self.search_page.search_precision_toggle
        is_on = toggle.isChecked()
        toggle.setProperty("precisionState", "on" if is_on else "off")
        toggle.setText(
            texts.get("search_precision_on" if is_on else "search_precision_off", "ON" if is_on else "OFF")
        )
        toggle.style().unpolish(toggle)
        toggle.style().polish(toggle)
        toggle.update()

    def _search_precision_effective(self, *, is_text: bool, has_image: bool) -> bool:
        if is_text:
            return False
        return bool(has_image)

    def _resolve_search_precision_mode(self, *, is_text: bool, has_image: bool) -> str:
        if not self._search_precision_effective(is_text=is_text, has_image=has_image):
            return "fast"
        return self._search_precision_mode_from_ui()

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

        show_image_precision = active_tab == self.SEARCH_TAB_IMAGE
        page.search_precision_cluster.setVisible(show_image_precision)

        is_on = page.search_precision_toggle.isChecked()
        image_hint = texts.get(
            "search_precision_hint_on" if is_on else "search_precision_hint_off",
            texts.get("search_precision_hint", ""),
        )
        page.search_precision_label.setToolTip(image_hint)
        page.search_precision_toggle.setToolTip(image_hint)
        self._update_search_precision_toggle_ui()

        chunk_hint = texts.get("search_mode_hint", "")
        page.search_mode_label.setToolTip(chunk_hint)
        page.search_mode.setToolTip(chunk_hint)

    def _refresh_search_precision_controls(self) -> None:
        self._refresh_search_panel_state()

    def _on_search_query_tab_changed(self, _index: int = 0) -> None:
        self._refresh_search_panel_state()

    def _on_search_precision_toggled(self, _checked=False) -> None:
        self._refresh_search_panel_state()

    def _on_search_mode_changed(self) -> None:
        self._save_search_mode()
        self._refresh_search_panel_state()

    def open_compose_search_tab(self) -> None:
        self.switch_page("search")
        self._set_search_query_tab(self.SEARCH_TAB_COMPOSE)
        self._refresh_search_panel_state()
