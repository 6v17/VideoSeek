"""Search preset UI wiring for MainWindow."""

from __future__ import annotations

from src.services.search_preset_service import list_presets, resolve_preset_ref_paths
from ui.dialogs.search_preset_dialog import SearchPresetManageDialog


class SearchPresetsGuiMixin:
    def _init_search_presets_ui(self):
        bar = getattr(self.search_page, "search_presets_bar", None)
        if bar is None:
            return
        bar.preset_clicked.connect(self.run_search_preset)
        btn_manage = getattr(self.search_page, "btn_manage_presets", None)
        if btn_manage is not None:
            btn_manage.clicked.connect(self.open_search_preset_manager)

    def refresh_search_presets_ui(self):
        bar = getattr(self.search_page, "search_presets_bar", None)
        if bar is None:
            return
        bar.set_texts(self.texts)
        bar.set_presets(list_presets())
        btn_manage = getattr(self.search_page, "btn_manage_presets", None)
        if btn_manage is not None:
            btn_manage.setText(self.texts.get("search_presets_manage", "Manage presets"))

    def build_search_preset_draft(self) -> tuple[dict, dict]:
        text_query = self.search_page.text_search.text().strip()
        image_path = str(getattr(self, "current_img_path", "") or "").strip()
        default_name = text_query[:24] if text_query else self.texts.get("search_presets_default_image_name", "Preset")
        if not default_name:
            default_name = self.texts.get("search_presets_save_prompt", "Preset")

        return (
            {
                "name": default_name,
                "query": text_query,
                "source_image_paths": [image_path] if image_path else [],
            },
            {},
        )

    def apply_search_preset_to_ui(self, preset):
        preset = dict(preset or {})
        query = str(preset.get("query", "") or "").strip()
        ref_paths = resolve_preset_ref_paths(preset)
        if query:
            self.search_page.text_search.setText(query)
        else:
            self.search_page.text_search.clear()
        if ref_paths:
            self._set_image_query(ref_paths[0], clear_text=not query)
        else:
            self.current_img_path = None
            self.search_page.img_label.clear()
            self._refresh_search_precision_controls()

    def run_search_preset(self, preset_id: str):
        if not self._ensure_startup_migration_idle("feature_search"):
            return
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        if not self._validate_search_scope():
            self.search_page.lbl_status.setText(self.texts.get("search_scope_none_selected", ""))
            return
        self.switch_page("search")
        self.search_controller.start_preset_search(preset_id)

    def open_search_preset_manager(self):
        if not self.check_runtime_resources():
            self.search_page.lbl_status.setText(self.texts["model_features_disabled"])
            return
        dialog = SearchPresetManageDialog(self, language=self.language, is_dark=self.is_dark_mode)
        dialog.exec()
        self.refresh_search_presets_ui()
