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

    def _search_video_discovery_from_ui(self) -> bool:
        toggle = self.search_page.search_video_discovery_toggle
        return bool(toggle.isChecked())

    def _resolve_video_discovery_enabled(self, *, is_text: bool, has_image: bool) -> bool:
        if is_text or not has_image:
            return False
        if self._resolve_search_precision_mode(is_text=is_text, has_image=has_image) == "precise":
            return False
        if not self._search_scope_is_global():
            return False
        return self._search_video_discovery_from_ui()

    def _update_search_video_discovery_toggle_ui(self) -> None:
        if not hasattr(self, "search_page"):
            return
        texts = getattr(self, "texts", {}) or {}
        toggle = self.search_page.search_video_discovery_toggle
        is_on = toggle.isChecked()
        toggle.setProperty("videoDiscoveryState", "on" if is_on else "off")
        toggle.setText(
            texts.get("search_video_discovery_on" if is_on else "search_video_discovery_off", "ON" if is_on else "OFF")
        )
        toggle.style().unpolish(toggle)
        toggle.style().polish(toggle)
        toggle.update()

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

        show_video_discovery = active_tab in (self.SEARCH_TAB_IMAGE, self.SEARCH_TAB_COMPOSE)
        show_video_discovery = show_video_discovery and not page.search_precision_toggle.isChecked()
        page.search_video_discovery_cluster.setVisible(show_video_discovery)
        page.search_image_options_group.setVisible(show_image_precision or show_video_discovery)

        precision_hint = texts.get("search_precision_hint", "")
        page.search_precision_label.setToolTip(precision_hint)
        page.search_precision_toggle.setToolTip("")
        self._update_search_precision_toggle_ui()

        page.search_video_discovery_label.setText(texts.get("search_video_discovery_label", ""))
        page.search_video_discovery_label.setToolTip(texts.get("search_video_discovery_hint", ""))
        page.search_video_discovery_toggle.setToolTip("")
        self._update_search_video_discovery_toggle_ui()

        chunk_hint = texts.get("search_mode_hint", "")
        page.search_mode_label.setToolTip(chunk_hint)
        page.search_mode.setToolTip(chunk_hint)
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
            page.lbl_text_model_hint.setVisible(bool(hint))
        except Exception:
            page.lbl_active_model.setText("")
            page.lbl_text_model_hint.setVisible(False)

    def _refresh_search_precision_controls(self) -> None:
        self._refresh_search_panel_state()

    def _on_search_query_tab_changed(self, _index: int = 0) -> None:
        self._refresh_search_panel_state()

    def _on_search_precision_toggled(self, _checked=False) -> None:
        self._refresh_search_panel_state()

    def _on_search_video_discovery_toggled(self, _checked=False) -> None:
        self._save_search_video_discovery_enabled()
        self._refresh_search_panel_state()

    def _on_search_mode_changed(self) -> None:
        self._save_search_mode()
        self._refresh_search_panel_state()

    def open_compose_search_tab(self) -> None:
        self.switch_page("search")
        self._set_search_query_tab(self.SEARCH_TAB_COMPOSE)
        self._refresh_search_panel_state()
