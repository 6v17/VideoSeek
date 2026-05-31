"""Local search scope UI (per-video selection)."""

from __future__ import annotations

import os

from src.services.library_service import list_local_vector_details, needs_search_index_schema_upgrade
from src.services.search_scope import count_indexed_ready_videos, normalize_scope_path
from src.services.search_scope import list_ready_video_paths_for_libraries
from src.storage.config_store import (
    get_search_scope_library_paths,
    get_search_scope_mode,
    get_search_scope_video_paths,
    save_search_scope,
)
from ui.dialogs.search_scope_editor import SearchScopeEditorDialog


class SearchScopeGuiMixin:
    def _init_search_scope_state(self) -> None:
        self._search_scope_mode = get_search_scope_mode()
        self._search_scope_video_paths = get_search_scope_video_paths()
        self._search_scope_entries_cache: list = []

    def _search_scope_picker_available(self) -> bool:
        if needs_search_index_schema_upgrade():
            return False
        return count_indexed_ready_videos() >= 2

    def _refresh_search_scope_entries(self) -> None:
        try:
            detail = list_local_vector_details(validate_contents=False)
            self._search_scope_entries_cache = list(detail.get("entries", []))
        except Exception:
            self._search_scope_entries_cache = []

    def _refresh_search_scope_ui(self) -> None:
        if not hasattr(self, "search_page"):
            return
        self._refresh_search_scope_entries()
        show_scope = self._search_scope_picker_available()
        self.search_page.search_scope_cluster.setVisible(show_scope)

        known_paths = set()
        for ent in self._search_scope_entries_cache:
            if str(ent.get("asset_state", "")).strip().lower() != "ready":
                continue
            lib_path = str(ent.get("library_path", "") or "").strip()
            rel_path = str(ent.get("video_rel_path", "") or "").strip()
            if lib_path and rel_path:
                known_paths.add(normalize_scope_path(os.path.join(lib_path, rel_path)))
        pruned_paths = [path for path in self._search_scope_video_paths if path in known_paths]
        if pruned_paths != self._search_scope_video_paths:
            self._search_scope_video_paths = pruned_paths
            if self._search_scope_mode == "selected":
                save_search_scope(self._search_scope_mode, video_paths=self._search_scope_video_paths)

        if (
            self._search_scope_mode == "selected"
            and not self._search_scope_video_paths
            and not get_search_scope_library_paths()
        ):
            self._search_scope_mode = "all"
            save_search_scope("all", video_paths=[])

        self.search_page.search_scope_select.setEnabled(show_scope)
        self._render_search_scope_picker()

    def _render_search_scope_picker(self) -> None:
        texts = self.texts
        if self._search_scope_mode == "selected":
            if self._search_scope_video_paths:
                count = len(self._search_scope_video_paths)
            else:
                count = len(list_ready_video_paths_for_libraries(get_search_scope_library_paths()))
            summary = texts.get("search_scope_picker_partial", "{count}").format(count=count)
        else:
            summary = texts.get("search_scope_all", "")
        self.search_page.search_scope_select.set_display_text(summary)

    def open_search_scope_editor(self) -> None:
        self._refresh_search_scope_entries()
        if not self._search_scope_entries_cache:
            return
        dialog = SearchScopeEditorDialog(
            self,
            texts=self.texts,
            entries=self._search_scope_entries_cache,
            mode=self._search_scope_mode,
            selected_video_paths=self._search_scope_video_paths,
            is_dark=getattr(self, "is_dark_mode", True),
            language=getattr(self, "language", "zh"),
        )
        if dialog.exec():
            self._search_scope_mode, self._search_scope_video_paths = dialog.result_scope()
            save_search_scope(self._search_scope_mode, video_paths=self._search_scope_video_paths)
            self._refresh_search_panel_state()

    def _resolve_active_search_video_scope(self):
        from src.services.search_scope import resolve_active_search_video_scope

        return resolve_active_search_video_scope()

    def _validate_search_scope(self) -> bool:
        if not self._search_scope_picker_available():
            return True
        if self._search_scope_mode != "selected":
            return True
        if self._search_scope_video_paths:
            return True
        return bool(get_search_scope_library_paths())
