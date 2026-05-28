"""Manage and edit shared search presets."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.app.i18n import get_texts
from src.services.query_text_service import prepare_text_query
from src.services.search_preset_service import (
    create_preset,
    delete_preset,
    list_presets,
    resolve_preset_ref_paths,
    update_preset,
)
from ui.widgets.scaffold import VSCard
from ui.widgets.styles import repolish_widget


class PresetImageChip(QWidget):
    selection_changed = Signal()

    def __init__(self, image_path: str, parent=None):
        super().__init__(parent)
        self.image_path = str(image_path or "").strip()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.thumb_wrap = QWidget()
        self.thumb_wrap.setObjectName("PresetImageThumb")
        self.thumb_wrap.setFixedSize(96, 96)
        self.thumb_wrap.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb_grid = QGridLayout(self.thumb_wrap)
        thumb_grid.setContentsMargins(0, 0, 0, 0)

        self.thumb = QLabel(self.thumb_wrap)
        self.thumb.setObjectName("PresetImagePreview")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedSize(88, 88)
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull():
            self.thumb.setPixmap(
                pixmap.scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self.thumb.setText(os.path.basename(self.image_path))

        self.checkbox = QCheckBox(self.thumb_wrap)
        self.checkbox.stateChanged.connect(lambda _state: self._on_selection_changed())

        thumb_grid.addWidget(self.thumb, 0, 0, Qt.AlignmentFlag.AlignCenter)
        thumb_grid.addWidget(self.checkbox, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        caption = QLabel(os.path.basename(self.image_path))
        caption.setObjectName("CardHint")
        caption.setWordWrap(True)
        caption.setFixedWidth(96)
        caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        layout.addWidget(self.thumb_wrap, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignHCenter)
        self.thumb_wrap.mousePressEvent = self._handle_thumb_press
        self.thumb.mousePressEvent = self._handle_thumb_press
        self._on_selection_changed()

    def _handle_thumb_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.checkbox.setChecked(not self.checkbox.isChecked())
            event.accept()
            return
        event.ignore()

    def _on_selection_changed(self):
        selected = self.checkbox.isChecked()
        self.thumb_wrap.setProperty("selected", selected)
        self.style().unpolish(self.thumb_wrap)
        self.style().polish(self.thumb_wrap)
        self.thumb_wrap.update()
        self.selection_changed.emit()

    def is_selected(self) -> bool:
        return self.checkbox.isChecked()


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
        self._image_paths: list[str] = []
        self._initial_image_paths: list[str] = []
        self._image_chips: list[PresetImageChip] = []
        self._is_edit = bool(self.preset.get("id"))

        title_key = "search_presets_edit_title" if self._is_edit else "search_presets_save_title"
        self.setWindowTitle(self.texts.get(title_key, "Preset"))
        self.setMinimumWidth(620)

        root = QVBoxLayout(self)
        card = VSCard(variant="dialog")
        form = QFormLayout()
        default_name = str(self.preset.get("name", "") or self.draft.get("name", "") or "")
        default_query = str(self.preset.get("query", "") or self.draft.get("query", "") or "")
        self.input_name = QLineEdit(default_name)
        self.input_description = QTextEdit()
        self.input_description.setPlaceholderText(self.texts.get("search_presets_field_description_hint", ""))
        self.input_description.setPlainText(default_query)
        self.input_description.setFixedHeight(96)
        form.addRow(self.texts.get("search_presets_field_name", "Name"), self.input_name)
        form.addRow(self.texts.get("search_presets_field_description", "Description"), self.input_description)
        card.content_layout.addLayout(form)

        images_title = QLabel(self.texts.get("search_presets_field_images", "Reference images"))
        images_title.setObjectName("CardTitle")
        card.content_layout.addWidget(images_title)

        self.images_hint = QLabel(self.texts.get("search_presets_images_hint", ""))
        self.images_hint.setObjectName("CardHint")
        self.images_hint.setWordWrap(True)
        card.content_layout.addWidget(self.images_hint)

        self.images_scroll = QScrollArea()
        self.images_scroll.setWidgetResizable(True)
        self.images_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.images_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.images_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.images_scroll.setFixedHeight(138)
        self.images_host = QWidget()
        self.images_layout = QHBoxLayout(self.images_host)
        self.images_layout.setContentsMargins(0, 0, 0, 0)
        self.images_layout.setSpacing(10)
        self.images_layout.addStretch(1)
        self.images_scroll.setWidget(self.images_host)
        card.content_layout.addWidget(self.images_scroll)

        image_actions = QHBoxLayout()
        self.btn_add_images = QPushButton(self.texts.get("search_presets_add_images", "Add images"))
        self.btn_remove_selected = QPushButton(self.texts.get("search_presets_remove_selected", "Delete selected"))
        self.btn_remove_selected.setObjectName("DangerGhostButton")
        self.btn_remove_selected.setEnabled(False)
        self.btn_add_images.clicked.connect(self._add_images)
        self.btn_remove_selected.clicked.connect(self._remove_selected_images)
        image_actions.addWidget(self.btn_add_images)
        image_actions.addWidget(self.btn_remove_selected)
        image_actions.addStretch(1)
        card.content_layout.addLayout(image_actions)

        self.fusion_block = QWidget()
        fusion_layout = QVBoxLayout(self.fusion_block)
        fusion_layout.setContentsMargins(0, 8, 0, 0)
        fusion_layout.setSpacing(6)
        self.fusion_title = QLabel(self.texts.get("search_presets_fusion_title", "Text / image balance"))
        self.fusion_title.setObjectName("CardTitle")
        self.fusion_hint = QLabel(self.texts.get("search_presets_fusion_hint", ""))
        self.fusion_hint.setObjectName("CardHint")
        self.fusion_hint.setWordWrap(True)
        fusion_slider_row = QHBoxLayout()
        fusion_slider_row.setSpacing(10)
        self.lbl_fusion_text = QLabel(self.texts.get("search_presets_fusion_text", "Text"))
        self.lbl_fusion_text.setObjectName("CardHint")
        self.slider_fusion = QSlider(Qt.Orientation.Horizontal)
        self.slider_fusion.setRange(0, 100)
        self.slider_fusion.setSingleStep(5)
        self.slider_fusion.setPageStep(10)
        self.lbl_fusion_image = QLabel(self.texts.get("search_presets_fusion_image", "Image"))
        self.lbl_fusion_image.setObjectName("CardHint")
        self.lbl_fusion_value = QLabel()
        self.lbl_fusion_value.setObjectName("CardHint")
        self.lbl_fusion_value.setMinimumWidth(120)
        self.lbl_fusion_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fusion_slider_row.addWidget(self.lbl_fusion_text)
        fusion_slider_row.addWidget(self.slider_fusion, 1)
        fusion_slider_row.addWidget(self.lbl_fusion_image)
        fusion_slider_row.addWidget(self.lbl_fusion_value)
        fusion_layout.addWidget(self.fusion_title)
        fusion_layout.addWidget(self.fusion_hint)
        fusion_layout.addLayout(fusion_slider_row)
        card.content_layout.addWidget(self.fusion_block)

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
            self._image_paths = resolve_preset_ref_paths(self.preset)
        else:
            self._image_paths = [
                str(path or "").strip()
                for path in (self.draft.get("source_image_paths") or [])
                if str(path or "").strip()
            ]
        self._initial_image_paths = list(self._image_paths)
        fusion = dict(self.preset.get("fusion") or self.draft.get("fusion") or {})
        text_pct = int(round(float(fusion.get("text_weight", 0.5)) * 100))
        self.slider_fusion.blockSignals(True)
        self.slider_fusion.setValue(max(0, min(100, text_pct)))
        self.slider_fusion.blockSignals(False)
        self.input_description.textChanged.connect(self._refresh_fusion_controls)
        self.slider_fusion.valueChanged.connect(self._update_fusion_value_label)
        self._rebuild_image_strip()

    def _has_mixed_content(self) -> bool:
        return bool(self.input_description.toPlainText().strip() and self._image_paths)

    def _refresh_fusion_controls(self):
        mixed = self._has_mixed_content()
        self.fusion_block.setVisible(mixed)
        if mixed:
            self._update_fusion_value_label(self.slider_fusion.value())

    def _update_fusion_value_label(self, text_pct: int):
        text_pct = max(0, min(100, int(text_pct)))
        image_pct = 100 - text_pct
        self.lbl_fusion_value.setText(
            self.texts.get("search_presets_fusion_value", "Text {text}% · Image {image}%").format(
                text=text_pct,
                image=image_pct,
            )
        )

    def _current_fusion(self) -> dict | None:
        if not self._has_mixed_content():
            return None
        text_weight = float(self.slider_fusion.value()) / 100.0
        return {
            "text_weight": text_weight,
            "image_weight": 1.0 - text_weight,
        }

    def _rebuild_image_strip(self):
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._image_chips = []
        for image_path in self._image_paths:
            chip = PresetImageChip(image_path, parent=self.images_host)
            chip.selection_changed.connect(self._update_remove_selected_state)
            self._image_chips.append(chip)
            self.images_layout.addWidget(chip)
        self.images_layout.addStretch(1)
        self.images_scroll.setVisible(bool(self._image_paths))
        self._update_remove_selected_state()
        self._refresh_fusion_controls()

    def _update_remove_selected_state(self):
        selected_count = sum(1 for chip in self._image_chips if chip.is_selected())
        self.btn_remove_selected.setEnabled(selected_count > 0)
        if selected_count:
            label = self.texts.get("search_presets_remove_selected", "Delete selected")
            self.btn_remove_selected.setText(f"{label} ({selected_count})")
        else:
            self.btn_remove_selected.setText(self.texts.get("search_presets_remove_selected", "Delete selected"))

    def _selected_image_paths(self) -> list[str]:
        return [chip.image_path for chip in self._image_chips if chip.is_selected()]

    def _remove_selected_images(self):
        selected = set(self._selected_image_paths())
        if not selected:
            QMessageBox.information(
                self,
                self.texts.get("warning_title", "Warning"),
                self.texts.get("search_presets_remove_selected_empty", ""),
            )
            return
        self._image_paths = [path for path in self._image_paths if path not in selected]
        self._rebuild_image_strip()

    def _add_images(self):
        paths, _selected = QFileDialog.getOpenFileNames(
            self,
            self.texts.get("search_presets_add_images", "Add images"),
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        for path in paths:
            cleaned = str(path or "").strip()
            if cleaned and cleaned not in self._image_paths:
                self._image_paths.append(cleaned)
        self._rebuild_image_strip()

    def _images_changed(self) -> bool:
        current = [os.path.normpath(path) for path in self._image_paths]
        initial = [os.path.normpath(path) for path in self._initial_image_paths]
        return current != initial

    def _normalized_query(self) -> str:
        query = self.input_description.toPlainText().strip()
        if not query:
            return ""
        query_info = prepare_text_query(query)
        if query_info["too_short"]:
            raise ValueError(self.texts.get("query_too_short", "Query is too short"))
        return str(query_info["normalized"] or "").strip()

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
            query = self._normalized_query()
        except ValueError as exc:
            QMessageBox.warning(self, self.texts.get("warning_title", "Warning"), str(exc))
            return
        if not query and not self._image_paths:
            QMessageBox.warning(
                self,
                self.texts.get("warning_title", "Warning"),
                self.texts.get("search_presets_save_empty", ""),
            )
            return
        try:
            fusion = self._current_fusion()
            if self._is_edit:
                payload = {
                    "name": name,
                    "query": query,
                }
                if fusion is not None:
                    payload["fusion"] = fusion
                if self._images_changed():
                    payload["source_image_paths"] = list(self._image_paths)
                    payload["replace_reference_images"] = True
                self._result_preset = update_preset(self.preset["id"], **payload)
            else:
                payload = {
                    "name": name,
                    "query": query,
                    "source_image_paths": list(self._image_paths),
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
        draft = {}
        save_context = {}
        parent = self.parent()
        if parent is not None and hasattr(parent, "build_search_preset_draft"):
            draft, save_context = parent.build_search_preset_draft()
        dialog = SearchPresetFormDialog(
            self,
            draft=draft,
            save_context=save_context,
            language=self.language,
            is_dark=self.is_dark,
        )
        if dialog.exec():
            self.reload()
            self._refresh_parent_presets_bar()

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
