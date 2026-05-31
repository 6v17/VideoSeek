"""Manage and edit shared search presets."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.app.i18n import get_texts
from src.services.search_preset_service import (
    create_preset,
    delete_preset,
    list_presets,
    resolve_preset_ref_paths,
    update_preset,
)
from ui.widgets.scaffold import VSCard
from ui.widgets.search_compose_form import SearchComposeFormWidget
from ui.widgets.styles import repolish_widget


class SearchPresetFormDialog(QDialog):
    """Create or edit a preset: tag name, description text, and helper images."""

    def __init__(
        self,
        parent=None,
        *,
        preset=None,
        draft=None,
        save_context=None,
        language="zh",
        is_dark=True,
    ):
        super().__init__(parent)
        self.texts = get_texts(language)
        self.preset = dict(preset or {})
        self.draft = dict(draft or {})
        self.save_context = dict(save_context or {})
        self._result_preset = None
        self._is_edit = bool(self.preset.get("id"))

        title_key = "search_presets_edit_title" if self._is_edit else "search_presets_save_title"
        self.setWindowTitle(self.texts.get(title_key, "Preset"))
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        card = VSCard(variant="dialog")
        form = QFormLayout()
        default_name = str(self.preset.get("name", "") or self.draft.get("name", "") or "")
        self.input_name = QLineEdit(default_name)
        form.addRow(self.texts.get("search_presets_field_name", "Name"), self.input_name)
        card.content_layout.addLayout(form)

        self.compose_form = SearchComposeFormWidget(texts=self.texts)
        card.content_layout.addWidget(self.compose_form)

        root.addWidget(card)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = QPushButton(self.texts.get("cancel", "Cancel"))
        btn_save = QPushButton(self.texts.get("search_presets_save", "Save"))
        btn_save.setObjectName("PrimaryButton")
        btn_cancel.clicked.connect(self.reject)
        btn_save.clicked.connect(self._save)
        buttons.addWidget(btn_cancel)
        buttons.addWidget(btn_save)
        root.addLayout(buttons)

        if self._is_edit:
            self.compose_form.load_preset(self.preset)
            self._initial_image_paths = resolve_preset_ref_paths(self.preset)
        else:
            self.compose_form.load_draft(self.draft)
            self._initial_image_paths = list(self.compose_form.image_paths())

    def _images_changed(self) -> bool:
        current = [os.path.normpath(path) for path in self.compose_form.image_paths()]
        initial = [os.path.normpath(path) for path in self._initial_image_paths]
        return current != initial

    def _save(self):
        name = self.input_name.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                self.texts.get("warning_title", "Warning"),
                self.texts.get("search_presets_name_required", ""),
            )
            return
        try:
            query = self.compose_form.normalized_query()
        except ValueError as exc:
            QMessageBox.warning(self, self.texts.get("warning_title", "Warning"), str(exc))
            return
        image_paths = self.compose_form.image_paths()
        if not query and not image_paths:
            QMessageBox.warning(
                self,
                self.texts.get("warning_title", "Warning"),
                self.texts.get("search_presets_save_empty", ""),
            )
            return
        try:
            fusion = self.compose_form.current_fusion()
            if self._is_edit:
                payload = {
                    "name": name,
                    "query": query,
                }
                if fusion is not None:
                    payload["fusion"] = fusion
                if self._images_changed():
                    payload["source_image_paths"] = list(image_paths)
                    payload["replace_reference_images"] = True
                self._result_preset = update_preset(self.preset["id"], **payload)
            else:
                payload = {
                    "name": name,
                    "query": query,
                    "source_image_paths": list(image_paths),
                }
                if fusion is not None:
                    payload["fusion"] = fusion
                self._result_preset = create_preset(**payload)
        except Exception as exc:
            QMessageBox.critical(self, self.texts.get("error_title", "Error"), str(exc))
            return
        self.accept()

    def result_preset(self):
        return self._result_preset


class SearchPresetEditorDialog(SearchPresetFormDialog):
    """Backward-compatible alias for edit-only callers."""

    def __init__(self, parent=None, *, preset=None, language="zh", is_dark=True):
        super().__init__(parent, preset=preset, language=language, is_dark=is_dark)


class SearchPresetManageRow(QFrame):
    def __init__(self, preset: dict, *, texts: dict, parent=None):
        super().__init__(parent)
        self.preset_id = str(preset.get("id", "") or "").strip()
        self.setObjectName("SearchPresetManageRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        accent = QWidget()
        accent.setObjectName("SearchPresetManageAccent")
        accent.setFixedSize(4, 44)
        color = str((preset.get("ui") or {}).get("color", "") or "").strip()
        if color:
            accent.setStyleSheet(f"background-color: {color}; border-radius: 2px;")

        text_wrap = QWidget()
        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(6)

        title = QLabel(str(preset.get("name", "") or ""))
        title.setObjectName("SearchPresetManageTitle")
        title.setWordWrap(True)

        query = str(preset.get("query", "") or "").strip()
        ref_count = len(resolve_preset_ref_paths(preset))
        if query:
            summary = query if len(query) <= 120 else f"{query[:117]}..."
        elif ref_count:
            summary = texts.get("search_presets_row_image_only", "Reference images only")
        else:
            summary = texts.get("search_presets_row_empty", "")

        desc = QLabel(summary)
        desc.setObjectName("SearchPresetManageDesc")
        desc.setWordWrap(True)

        badges_row = QHBoxLayout()
        badges_row.setContentsMargins(0, 0, 0, 0)
        badges_row.setSpacing(6)
        if query:
            text_badge = QLabel(texts.get("search_presets_badge_text", "Text"))
            text_badge.setObjectName("SearchPresetManageBadge")
            text_badge.setProperty("kind", "text")
            repolish_widget(text_badge)
            badges_row.addWidget(text_badge)
        if ref_count:
            image_badge = QLabel(
                texts.get("search_presets_badge_images", "{count} image(s)").format(count=ref_count)
            )
            image_badge.setObjectName("SearchPresetManageBadge")
            image_badge.setProperty("kind", "image")
            repolish_widget(image_badge)
            badges_row.addWidget(image_badge)
        if query and ref_count:
            fusion = dict(preset.get("fusion") or {})
            text_pct = int(round(float(fusion.get("text_weight", 0.5)) * 100))
            image_pct = 100 - text_pct
            fusion_badge = QLabel(
                texts.get("search_presets_fusion_value", "Text {text}% · Image {image}%").format(
                    text=text_pct,
                    image=image_pct,
                )
            )
            fusion_badge.setObjectName("SearchPresetManageBadge")
            fusion_badge.setProperty("kind", "fusion")
            repolish_widget(fusion_badge)
            badges_row.addWidget(fusion_badge)
        badges_row.addStretch(1)

        text_col.addWidget(title)
        text_col.addWidget(desc)
        text_col.addLayout(badges_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        self.btn_edit = QPushButton(texts.get("search_presets_edit", "Edit"))
        self.btn_edit.setObjectName("GhostButton")
        self.btn_delete = QPushButton(texts.get("delete", "Delete"))
        self.btn_delete.setObjectName("DangerGhostButton")
        actions.addWidget(self.btn_edit)
        actions.addWidget(self.btn_delete)

        layout.addWidget(accent, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(text_wrap, 1, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(actions, 0)


class SearchPresetManageDialog(QDialog):
    def __init__(self, parent=None, *, language="zh", is_dark=True):
        super().__init__(parent)
        self.texts = get_texts(language)
        self.language = language
        self.is_dark = is_dark
        self.setWindowTitle(self.texts.get("search_presets_manage_title", "Manage search presets"))
        self.setMinimumSize(760, 520)

        root = QVBoxLayout(self)
        card = VSCard(variant="dialog", margins=(22, 20, 22, 18), spacing=14)
        card_layout = card.content_layout

        hero = QLabel(self.texts.get("search_presets_manage_title", "Manage search presets"))
        hero.setObjectName("DialogHeroTitle")
        card_layout.addWidget(hero)

        hint = QLabel(self.texts.get("search_presets_manage_hint", ""))
        hint.setObjectName("DialogBodyLabel")
        hint.setWordWrap(True)
        card_layout.addWidget(hint)

        list_host = QWidget()
        list_host.setObjectName("SearchPresetManageList")
        self._list_host = list_host
        self._list_layout = QVBoxLayout(list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("SearchPresetManageScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidget(list_host)
        card_layout.addWidget(self._scroll, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.btn_add = QPushButton(self.texts.get("search_presets_add", "Add preset"))
        self.btn_add.setObjectName("PrimaryButton")
        self.btn_close = QPushButton(self.texts.get("close", "Close"))
        self.btn_close.setObjectName("GhostButton")
        toolbar.addWidget(self.btn_add)
        toolbar.addStretch(1)
        toolbar.addWidget(self.btn_close)
        card_layout.addLayout(toolbar)
        root.addWidget(card)

        self.btn_add.clicked.connect(self._create_preset)
        self.btn_close.clicked.connect(self.accept)
        self._presets = []
        self.reload()
        repolish_widget(self)

    def reload(self):
        self._presets = list_presets()
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not self._presets:
            empty = QLabel(self.texts.get("search_presets_manage_empty", ""))
            empty.setObjectName("DialogBodyLabel")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.addWidget(empty)
        else:
            for preset in self._presets:
                preset_id = str(preset.get("id", "") or "").strip()
                if not preset_id:
                    continue
                row = SearchPresetManageRow(preset, texts=self.texts, parent=self._list_host)
                row.btn_edit.clicked.connect(lambda _checked=False, pid=preset_id: self._edit_preset(pid))
                row.btn_delete.clicked.connect(lambda _checked=False, pid=preset_id: self._delete_preset(pid))
                self._list_layout.addWidget(row)
        self._list_layout.addStretch(1)

    def _create_preset(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "open_compose_search_tab"):
            self.accept()
            parent.open_compose_search_tab()
            return
        self.reload()

    def _refresh_parent_presets_bar(self):
        parent = self.parent()
        if parent is not None and hasattr(parent, "refresh_search_presets_ui"):
            parent.refresh_search_presets_ui()

    def _edit_preset(self, preset_id: str):
        preset = next((item for item in self._presets if item.get("id") == preset_id), None)
        if not preset:
            return
        dialog = SearchPresetFormDialog(self, preset=preset, language=self.language, is_dark=self.is_dark)
        if dialog.exec():
            self.reload()
            self._refresh_parent_presets_bar()

    def _delete_preset(self, preset_id: str):
        if (
            QMessageBox.question(
                self,
                self.texts.get("confirm_title", "Confirm"),
                self.texts.get("search_presets_delete_confirm", "Delete this preset?"),
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        delete_preset(preset_id)
        self.reload()
        self._refresh_parent_presets_bar()
