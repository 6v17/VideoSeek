"""Search precision toggle for image search."""

from __future__ import annotations

from src.app.config import DEFAULT_CONFIG


class SearchPrecisionGuiMixin:
    def _search_has_image_query(self) -> bool:
        return bool(str(getattr(self, "current_img_path", "") or "").strip())

    def _search_has_text_query(self) -> bool:
        if not hasattr(self, "search_page"):
            return False
        return bool(self.search_page.text_search.text().strip())

    def _search_precision_mode_from_ui(self) -> str:
        toggle = self.search_page.search_precision_toggle
        return "precise" if toggle.isChecked() else "fast"

    def _set_search_precision_mode_ui(self, mode: str) -> None:
        toggle = self.search_page.search_precision_toggle
        toggle.blockSignals(True)
        toggle.setChecked(str(mode or "").strip().lower() == "precise")
        toggle.blockSignals(False)
        self._update_search_precision_toggle_ui()

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
        if is_text and not has_image:
            return False
        return bool(has_image)

    def _resolve_search_precision_mode(self, *, is_text: bool, has_image: bool) -> str:
        if not self._search_precision_effective(is_text=is_text, has_image=has_image):
            return "fast"
        return self._search_precision_mode_from_ui()

    def _refresh_search_precision_controls(self) -> None:
        if not hasattr(self, "search_page"):
            return
        texts = getattr(self, "texts", {}) or {}
        is_text = self._search_has_text_query()
        has_image = self._search_has_image_query()

        if is_text and not has_image:
            hint = texts.get("search_precision_disabled_text", texts.get("search_precision_hint", ""))
        else:
            hint = texts.get("search_precision_hint", "")

        self.search_page.search_precision_label.setToolTip(hint)
        self.search_page.search_precision_toggle.setToolTip(hint)
        self._update_search_precision_toggle_ui()

    def _on_search_mode_changed(self) -> None:
        self._save_search_mode()
        self._refresh_search_precision_controls()
