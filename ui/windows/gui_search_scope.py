"""Local search scope UI (per-video selection).

Visual / compose / image tabs use the CLIP library registry.
Dialogue (subtitle) tab uses the global subtitle library registry.
"""

from __future__ import annotations

import os

from src.services.library_service import list_local_vector_details, needs_search_index_schema_upgrade
from src.services.search_scope import list_ready_video_paths_for_libraries, normalize_scope_path
from src.services.subtitle_library_service import list_subtitle_search_scope_entries
from src.storage.config_store import (
    get_dialogue_search_scope_library_paths,
    get_dialogue_search_scope_mode,
    get_dialogue_search_scope_video_paths,
    get_search_scope_library_paths,
    get_search_scope_mode,
    get_search_scope_video_paths,
    save_dialogue_search_scope,
    save_search_scope,
)
from ui.dialogs.search_scope_editor import SearchScopeEditorDialog


class SearchScopeGuiMixin:
    def _init_search_scope_state(self) -> None:
        self._search_scope_mode = get_search_scope_mode()
        self._search_scope_video_paths = get_search_scope_video_paths()
        self._dialogue_search_scope_mode = get_dialogue_search_scope_mode()
        self._dialogue_search_scope_video_paths = get_dialogue_search_scope_video_paths()
        self._search_scope_entries_cache: list = []
        self._dialogue_search_scope_entries_cache: list = []
        self._search_scope_entries_dirty = True
        self._dialogue_search_scope_entries_dirty = True

    def _search_scope_is_dialogue(self) -> bool:
        active = ""
        if hasattr(self, "_search_active_tab"):
            try:
                active = str(self._search_active_tab() or "")
            except Exception:
                active = ""
        return active == getattr(self, "SEARCH_TAB_DIALOGUE", "dialogue")

    def _search_scope_ready_count(self) -> int:
        cache = (
            self._dialogue_search_scope_entries_cache
            if self._search_scope_is_dialogue()
            else self._search_scope_entries_cache
        )
        return sum(
            1
            for ent in cache
            if str(ent.get("asset_state", "")).strip().lower() == "ready"
            and bool(ent.get("source_exists", True))
        )

    def _search_scope_picker_available(self) -> bool:
        if self._search_scope_is_dialogue():
            return self._search_scope_ready_count() >= 2
        if needs_search_index_schema_upgrade():
            return False
        return self._search_scope_ready_count() >= 2

    def _refresh_search_scope_entries(self, *, force: bool = False) -> None:
        if self._search_scope_is_dialogue():
            if (
                not force
                and not getattr(self, "_dialogue_search_scope_entries_dirty", True)
                and self._dialogue_search_scope_entries_cache
            ):
                return
            try:
                self._dialogue_search_scope_entries_cache = list_subtitle_search_scope_entries()
                self._dialogue_search_scope_entries_dirty = False
            except Exception:
                self._dialogue_search_scope_entries_cache = []
                self._dialogue_search_scope_entries_dirty = True
            return

        if not force and not getattr(self, "_search_scope_entries_dirty", True) and self._search_scope_entries_cache:
            return
        try:
            detail = list_local_vector_details(validate_contents=False, include_storage_stats=False)
            self._search_scope_entries_cache = list(detail.get("entries", []))
            self._search_scope_entries_dirty = False
        except Exception:
            self._search_scope_entries_cache = []
            self._search_scope_entries_dirty = True

    def invalidate_search_scope_entries_cache(self) -> None:
        self._search_scope_entries_dirty = True

    def invalidate_dialogue_search_scope_entries_cache(self) -> None:
        self._dialogue_search_scope_entries_dirty = True

    def _active_scope_mode(self) -> str:
        if self._search_scope_is_dialogue():
            return str(getattr(self, "_dialogue_search_scope_mode", "all") or "all")
        return str(getattr(self, "_search_scope_mode", "all") or "all")

    def _active_scope_video_paths(self) -> list[str]:
        if self._search_scope_is_dialogue():
            return list(getattr(self, "_dialogue_search_scope_video_paths", []) or [])
        return list(getattr(self, "_search_scope_video_paths", []) or [])

    def _set_active_scope(self, mode: str, video_paths: list[str]) -> None:
        normalized_mode = "selected" if str(mode or "").strip().lower() == "selected" else "all"
        paths = [normalize_scope_path(path) for path in (video_paths or []) if str(path or "").strip()]
        if self._search_scope_is_dialogue():
            self._dialogue_search_scope_mode = normalized_mode
            self._dialogue_search_scope_video_paths = paths
            save_dialogue_search_scope(normalized_mode, video_paths=paths)
            self._dialogue_search_scope_mode = get_dialogue_search_scope_mode()
            self._dialogue_search_scope_video_paths = get_dialogue_search_scope_video_paths()
        else:
            self._search_scope_mode = normalized_mode
            self._search_scope_video_paths = paths
            save_search_scope(normalized_mode, video_paths=paths)
            self._search_scope_mode = get_search_scope_mode()
            self._search_scope_video_paths = get_search_scope_video_paths()

    def _refresh_search_scope_ui(self, *, force_entries: bool = False) -> None:
        if not hasattr(self, "search_page"):
            return
        self._refresh_search_scope_entries(force=force_entries)
        show_scope = self._search_scope_picker_available()
        # Keep the cluster in layout so tab switches do not jump the panel.
        self.search_page.search_scope_cluster.setVisible(True)

        cache = (
            self._dialogue_search_scope_entries_cache
            if self._search_scope_is_dialogue()
            else self._search_scope_entries_cache
        )
        known_paths = set()
        for ent in cache:
            if str(ent.get("asset_state", "")).strip().lower() != "ready":
                continue
            lib_path = str(ent.get("library_path", "") or "").strip()
            rel_path = str(ent.get("video_rel_path", "") or "").strip()
            if lib_path and rel_path:
                known_paths.add(normalize_scope_path(os.path.join(lib_path, rel_path)))

        current_paths = [
            normalize_scope_path(path)
            for path in self._active_scope_video_paths()
            if str(path or "").strip()
        ]
        pruned_paths = [path for path in current_paths if path in known_paths]
        mode = self._active_scope_mode()
        if pruned_paths != current_paths:
            self._set_active_scope(mode, pruned_paths)
            mode = self._active_scope_mode()

        library_paths = (
            get_dialogue_search_scope_library_paths()
            if self._search_scope_is_dialogue()
            else get_search_scope_library_paths()
        )
        if mode == "selected" and not self._active_scope_video_paths() and not library_paths:
            self._set_active_scope("all", [])

        self.search_page.search_scope_select.setEnabled(show_scope)
        self._render_search_scope_picker()

    def _render_search_scope_picker(self) -> None:
        texts = self.texts
        mode = self._active_scope_mode()
        video_paths = self._active_scope_video_paths()
        if mode == "selected":
            if video_paths:
                count = len(video_paths)
            elif self._search_scope_is_dialogue():
                from src.services.search_scope import resolve_active_dialogue_search_video_scope

                expanded = resolve_active_dialogue_search_video_scope() or []
                count = len(expanded)
            else:
                count = len(list_ready_video_paths_for_libraries(get_search_scope_library_paths()))
            summary = texts.get("search_scope_picker_partial", "{count}").format(count=count)
            display = texts.get("search_scope_picker_short", "{count}").format(count=count)
        else:
            summary = texts.get("search_scope_all", "")
            display = texts.get("search_scope_all_short", summary)
        self.search_page.search_scope_select.set_display_text(display, tooltip=summary)

    def open_search_scope_editor(self) -> None:
        self._refresh_search_scope_entries(force=True)
        cache = (
            self._dialogue_search_scope_entries_cache
            if self._search_scope_is_dialogue()
            else self._search_scope_entries_cache
        )
        if not cache:
            return
        dialog = SearchScopeEditorDialog(
            self,
            texts=self.texts,
            entries=cache,
            mode=self._active_scope_mode(),
            selected_video_paths=self._active_scope_video_paths(),
            is_dark=getattr(self, "is_dark_mode", True),
            language=getattr(self, "language", "zh"),
        )
        if dialog.exec():
            mode, video_paths = dialog.result_scope()
            self._set_active_scope(mode, video_paths)
            self._refresh_search_panel_state()

    def _resolve_active_search_video_scope(self):
        from src.services.search_scope import resolve_active_search_video_scope

        return resolve_active_search_video_scope()

    def _validate_search_scope(self) -> bool:
        if not self._search_scope_picker_available():
            return True
        if self._active_scope_mode() != "selected":
            return True
        if self._active_scope_video_paths():
            return True
        if self._search_scope_is_dialogue():
            return bool(get_dialogue_search_scope_library_paths())
        return bool(get_search_scope_library_paths())
