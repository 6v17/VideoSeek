"""Local search library scope UI."""

from __future__ import annotations

from src.services.library_service import list_search_scope_library_options, needs_search_index_schema_upgrade
from src.storage.config_store import (
    get_search_scope_library_paths,
    get_search_scope_mode,
    save_search_scope,
)
from ui.dialogs.search_scope_editor import SearchScopeEditorDialog


class SearchScopeGuiMixin:
    def _init_search_scope_state(self) -> None:
        self._search_scope_mode = get_search_scope_mode()
        self._search_scope_library_paths = get_search_scope_library_paths()

    def _scoped_library_search_available(self) -> bool:
        if needs_search_index_schema_upgrade():
            return False
        return len(list_search_scope_library_options()) >= 2

    def _refresh_search_scope_ui(self) -> None:
        if not hasattr(self, "search_page"):
            return
        options = list_search_scope_library_options()
        show_scope = self._scoped_library_search_available()
        self.search_page.search_scope_cluster.setVisible(show_scope)

        known_paths = {str(item.get("path", "") or "") for item in options}
        pruned_paths = [path for path in self._search_scope_library_paths if path in known_paths]
        if pruned_paths != self._search_scope_library_paths:
            self._search_scope_library_paths = pruned_paths
            if self._search_scope_mode == "selected":
                save_search_scope(self._search_scope_mode, self._search_scope_library_paths)

        if self._search_scope_mode == "selected" and not self._search_scope_library_paths:
            self._search_scope_mode = "all"
            save_search_scope("all", [])

        self.search_page.search_scope_select.setEnabled(show_scope)
        self._render_search_scope_picker(options)

    def _render_search_scope_picker(self, options=None) -> None:
        texts = self.texts
        if options is None:
            options = list_search_scope_library_options()
        if self._search_scope_mode == "selected":
            summary = texts.get("search_scope_picker_partial", "{count}").format(
                count=len(self._search_scope_library_paths)
            )
        else:
            summary = texts.get("search_scope_all", "")
        self.search_page.search_scope_select.set_display_text(summary)

    def open_search_scope_editor(self) -> None:
        options = list_search_scope_library_options()
        if not options:
            return
        dialog = SearchScopeEditorDialog(
            self,
            texts=self.texts,
            options=options,
            mode=self._search_scope_mode,
            selected_paths=self._search_scope_library_paths,
            is_dark=getattr(self, "is_dark_mode", True),
            language=getattr(self, "language", "zh"),
        )
        if dialog.exec():
            self._search_scope_mode, self._search_scope_library_paths = dialog.result_scope()
            save_search_scope(self._search_scope_mode, self._search_scope_library_paths)
            self._refresh_search_scope_ui()

    def _resolve_active_search_library_scope(self):
        from src.services.search_scope import resolve_active_search_library_scope

        return resolve_active_search_library_scope()

    def _validate_search_scope(self) -> bool:
        if not self._scoped_library_search_available():
            return True
        if self._search_scope_mode != "selected":
            return True
        return bool(self._search_scope_library_paths)
