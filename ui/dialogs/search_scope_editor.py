"""Modal video scope picker for local search."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ui.dialogs.app_message import AppMessageDialog
from ui.dialogs.shell import VSDialogShell
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width
from ui.widgets.styles import repolish_widget
from ui.widgets.video_scope_tree import VideoScopeTreeWidget


class SearchScopeEditorDialog(VSDialogShell):
    def __init__(
        self,
        parent,
        *,
        texts: dict,
        entries: list[dict],
        mode: str,
        selected_video_paths: list[str],
        is_dark: bool,
        language: str = "zh",
    ):
        super().__init__(
            parent,
            title=str(texts.get("search_scope_dialog_title", "")),
            body=str(texts.get("search_scope_dialog_hint", "")),
            minimum_width=message_dialog_min_width(
                760, WINDOW_SIZES["message_dialog"]["screen_margin"]
            ),
            card_margins=(18, 16, 18, 16),
            card_spacing=12,
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(820, 560)
        self._texts = texts
        self._language = str(language or "zh")
        self._is_dark = bool(is_dark)
        self._entries = list(entries or [])
        self._mode = "selected" if str(mode or "").strip().lower() == "selected" else "all"
        self._selected_paths = [
            str(path) for path in (selected_video_paths or []) if str(path or "").strip()
        ]
        self._result_mode = "all"
        self._result_video_paths: list[str] = []

        toolbar_host = QWidget()
        toolbar = QHBoxLayout(toolbar_host)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(10)
        self._summary_label = QLabel()
        self._summary_label.setObjectName("DialogMetaLabel")
        btn_select_all = QPushButton(str(texts.get("search_scope_select_all", "")))
        btn_select_all.setObjectName("GhostButton")
        btn_select_all.clicked.connect(self._select_all)
        btn_clear_all = QPushButton(str(texts.get("search_scope_clear_all", "")))
        btn_clear_all.setObjectName("GhostButton")
        btn_clear_all.clicked.connect(self._clear_all)
        toolbar.addWidget(self._summary_label, 1)
        toolbar.addWidget(btn_select_all, 0)
        toolbar.addWidget(btn_clear_all, 0)
        self.content_layout.addWidget(toolbar_host)

        self.scope_tree = VideoScopeTreeWidget(self)
        self.scope_tree.set_header_labels(
            str(texts.get("search_scope_video_col", "Video")),
            "",
        )
        self.content_layout.addWidget(self.scope_tree, 1)

        self.add_footer_button(
            str(texts.get("cancel", "Cancel")),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(texts.get("confirm_action", "OK")),
            object_name="PrimaryButton",
            on_click=self._accept_scope,
            default=True,
        )

        self._load_tree()
        btn_select_all.setEnabled(self.scope_tree.total_video_items() > 0)
        btn_clear_all.setEnabled(self.scope_tree.total_video_items() > 0)
        repolish_widget(self)

    def _load_tree(self) -> None:
        if not self._entries:
            self._refresh_summary()
            return
        default_checked = self._mode != "selected"
        checked = None if default_checked else self._selected_paths
        self.scope_tree.refresh_from_entries(
            self._entries,
            default_checked=default_checked,
            checked_abs_paths=checked,
        )
        QTimer.singleShot(0, self.scope_tree.reflow_all_lib_trees)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = self.scope_tree.total_video_items()
        checked = len(self.scope_tree.collect_checked_video_paths())
        self._summary_label.setText(
            self._texts.get("search_scope_dialog_summary", "{checked}/{total}").format(
                checked=checked,
                total=total,
            )
        )

    def _select_all(self) -> None:
        self.scope_tree.select_all_videos()
        self._refresh_summary()

    def _clear_all(self) -> None:
        self.scope_tree.select_no_videos()
        self._refresh_summary()

    def _accept_scope(self) -> None:
        checked = self.scope_tree.collect_checked_video_paths()
        total = self.scope_tree.total_video_items()
        if total > 0 and not checked:
            AppMessageDialog(
                self._texts.get("warning_title", ""),
                self._texts.get("search_scope_none_selected", ""),
                kind="warning",
                parent=self,
                is_dark=self._is_dark,
                language=self._language,
            ).exec()
            return
        if not total or len(checked) >= total:
            self._result_mode = "all"
            self._result_video_paths = []
        else:
            self._result_mode = "selected"
            self._result_video_paths = list(checked)
        self.accept()

    def result_scope(self) -> tuple[str, list[str]]:
        return self._result_mode, list(self._result_video_paths)
