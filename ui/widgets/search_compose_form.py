"""Inline compose search form: text + reference images + fusion weights."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.services.query_text_service import prepare_text_query
from src.services.search_preset_storage import resolve_preset_ref_paths
from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.styles import repolish_widget


class PresetImageChip(QWidget):
    selection_changed = Signal()

    def __init__(self, image_path: str, parent=None, *, compact: bool = False):
        super().__init__(parent)
        self.image_path = str(image_path or "").strip()
        self._compact = bool(compact)
        wrap_size = 82 if self._compact else 96
        thumb_size = 78 if self._compact else 88
        pixmap_size = 72 if self._compact else 84

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2 if self._compact else 4)

        self.thumb_wrap = QWidget()
        self.thumb_wrap.setObjectName("PresetImageThumb")
        if self._compact:
            self.thumb_wrap.setProperty("compact", True)
            repolish_widget(self.thumb_wrap)
        self.thumb_wrap.setFixedSize(wrap_size, wrap_size)
        self.thumb_wrap.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb_grid = QGridLayout(self.thumb_wrap)
        thumb_grid.setContentsMargins(0, 0, 0, 0)

        self.thumb = QLabel(self.thumb_wrap)
        self.thumb.setObjectName("PresetImagePreview")
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setFixedSize(thumb_size, thumb_size)
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull():
            self.thumb.setPixmap(
                pixmap.scaled(
                    pixmap_size,
                    pixmap_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.thumb.setText(os.path.basename(self.image_path))

        self.checkbox = QCheckBox(self.thumb_wrap)
        self.checkbox.stateChanged.connect(lambda _state: self._on_selection_changed())

        thumb_grid.addWidget(self.thumb, 0, 0, Qt.AlignmentFlag.AlignCenter)
        thumb_grid.addWidget(self.checkbox, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(self.thumb_wrap, 0, Qt.AlignmentFlag.AlignHCenter)
        if not self._compact:
            caption = QLabel(os.path.basename(self.image_path))
            caption.setObjectName("CardHint")
            caption.setWordWrap(True)
            caption.setFixedWidth(wrap_size)
            caption.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(caption, 0, Qt.AlignmentFlag.AlignHCenter)

        self.thumb_wrap.setToolTip(self.image_path)
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


class SearchComposeFormWidget(QWidget):
    """Search-time mixed query editor (no preset name / save actions)."""

    def __init__(self, parent=None, *, texts: dict | None = None, fill_text: bool = False):
        super().__init__(parent)
        self.texts = dict(texts or {})
        self._fill_text = bool(fill_text)
        self._image_paths: list[str] = []
        self._image_chips: list[PresetImageChip] = []
        strip_height = int(COMPONENT_SIZES.get("compose_image_strip_height", 118))

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.input_description = QTextEdit()
        self.input_description.setObjectName("SearchInput")
        self.input_description.setPlaceholderText("")
        self.input_description.setAcceptRichText(False)
        if self._fill_text:
            self.input_description.setMinimumHeight(72)
            self.input_description.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            root.addWidget(self.input_description, 1)
        else:
            self.input_description.setFixedHeight(88)
            root.addWidget(self.input_description)

        self.images_scroll = QScrollArea()
        self.images_scroll.setWidgetResizable(True)
        self.images_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.images_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.images_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.images_scroll.setFixedHeight(strip_height)
        self.images_host = QWidget()
        self.images_layout = QHBoxLayout(self.images_host)
        self.images_layout.setContentsMargins(0, 0, 0, 0)
        self.images_layout.setSpacing(6 if self._fill_text else 10)
        self.images_layout.addStretch(1)
        self.images_scroll.setWidget(self.images_host)
        root.addWidget(self.images_scroll)

        image_actions = QHBoxLayout()
        image_actions.setSpacing(8)
        self.btn_add_images = QPushButton()
        self.btn_remove_selected = QPushButton()
        self.btn_remove_selected.setObjectName("DangerGhostButton")
        self.btn_remove_selected.setEnabled(False)
        self.btn_add_images.clicked.connect(self._add_images)
        self.btn_remove_selected.clicked.connect(self._remove_selected_images)
        image_actions.addWidget(self.btn_add_images)
        image_actions.addWidget(self.btn_remove_selected)
        image_actions.addStretch(1)
        root.addLayout(image_actions)

        self.fusion_block = QWidget()
        fusion_layout = QHBoxLayout(self.fusion_block)
        fusion_layout.setContentsMargins(0, 0, 0, 0)
        fusion_layout.setSpacing(10)
        self.lbl_fusion_text = QLabel()
        self.lbl_fusion_text.setObjectName("CardHint")
        self.slider_fusion = QSlider(Qt.Orientation.Horizontal)
        self.slider_fusion.setRange(0, 100)
        self.slider_fusion.setSingleStep(5)
        self.slider_fusion.setPageStep(10)
        self.lbl_fusion_image = QLabel()
        self.lbl_fusion_image.setObjectName("CardHint")
        self.lbl_fusion_value = QLabel()
        self.lbl_fusion_value.setObjectName("CardHint")
        self.lbl_fusion_value.setMinimumWidth(108)
        self.lbl_fusion_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        fusion_layout.addWidget(self.lbl_fusion_text)
        fusion_layout.addWidget(self.slider_fusion, 1)
        fusion_layout.addWidget(self.lbl_fusion_image)
        fusion_layout.addWidget(self.lbl_fusion_value)
        root.addWidget(self.fusion_block)

        if self._fill_text:
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.input_description.textChanged.connect(self._refresh_fusion_controls)
        self.slider_fusion.valueChanged.connect(self._update_fusion_value_label)
        self.slider_fusion.setValue(50)
        self._rebuild_image_strip()
        self.set_texts(self.texts)

    def set_texts(self, texts: dict) -> None:
        self.texts = dict(texts or {})
        self.input_description.setPlaceholderText(
            self.texts.get("search_presets_field_description_hint", "")
        )
        self.btn_add_images.setText(self.texts.get("search_presets_add_images", "Add images"))
        self.lbl_fusion_text.setText(self.texts.get("search_presets_fusion_text", "Text"))
        self.lbl_fusion_image.setText(self.texts.get("search_presets_fusion_image", "Image"))
        self._update_remove_selected_state()
        self._refresh_fusion_controls()

    def has_content(self) -> bool:
        return bool(self.input_description.toPlainText().strip() or self._image_paths)

    def image_paths(self) -> list[str]:
        return list(self._image_paths)

    def to_draft(self) -> dict:
        return {
            "query": self.input_description.toPlainText().strip(),
            "source_image_paths": list(self._image_paths),
            "fusion": self.current_fusion(),
        }

    def load_draft(self, draft: dict | None) -> None:
        draft = dict(draft or {})
        self.input_description.setPlainText(str(draft.get("query", "") or ""))
        self._image_paths = [
            str(path or "").strip()
            for path in (draft.get("source_image_paths") or [])
            if str(path or "").strip()
        ]
        fusion = dict(draft.get("fusion") or {})
        text_pct = int(round(float(fusion.get("text_weight", 0.5)) * 100))
        self.slider_fusion.blockSignals(True)
        self.slider_fusion.setValue(max(0, min(100, text_pct)))
        self.slider_fusion.blockSignals(False)
        self._rebuild_image_strip()

    def load_preset(self, preset: dict | None) -> None:
        preset = dict(preset or {})
        self.input_description.setPlainText(str(preset.get("query", "") or ""))
        self._image_paths = resolve_preset_ref_paths(preset)
        fusion = dict(preset.get("fusion") or {})
        text_pct = int(round(float(fusion.get("text_weight", 0.5)) * 100))
        self.slider_fusion.blockSignals(True)
        self.slider_fusion.setValue(max(0, min(100, text_pct)))
        self.slider_fusion.blockSignals(False)
        self._rebuild_image_strip()

    def clear(self) -> None:
        self.input_description.clear()
        self._image_paths = []
        self.slider_fusion.blockSignals(True)
        self.slider_fusion.setValue(50)
        self.slider_fusion.blockSignals(False)
        self._rebuild_image_strip()

    def add_image(self, path: str) -> None:
        cleaned = str(path or "").strip()
        if cleaned and cleaned not in self._image_paths:
            self._image_paths.append(cleaned)
            self._rebuild_image_strip()

    def normalized_query(self) -> str:
        query = self.input_description.toPlainText().strip()
        if not query:
            return ""
        query_info = prepare_text_query(query)
        if query_info["too_short"]:
            raise ValueError(self.texts.get("query_too_short", "Query is too short"))
        return str(query_info["normalized"] or "").strip()

    def current_fusion(self) -> dict | None:
        if not self._has_mixed_content():
            return None
        text_weight = float(self.slider_fusion.value()) / 100.0
        return {
            "text_weight": text_weight,
            "image_weight": 1.0 - text_weight,
        }

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

    def _rebuild_image_strip(self):
        while self.images_layout.count():
            item = self.images_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._image_chips = []
        for image_path in self._image_paths:
            chip = PresetImageChip(image_path, parent=self.images_host, compact=True)
            chip.selection_changed.connect(self._update_remove_selected_state)
            self._image_chips.append(chip)
            self.images_layout.addWidget(chip)
        self.images_layout.addStretch(1)
        has_images = bool(self._image_paths)
        self.images_scroll.setVisible(has_images)
        self._update_remove_selected_state()
        self._refresh_fusion_controls()

    def _update_remove_selected_state(self):
        selected_count = sum(1 for chip in self._image_chips if chip.is_selected())
        self.btn_remove_selected.setEnabled(selected_count > 0)
        label = self.texts.get("search_presets_remove_selected", "Delete selected")
        if selected_count:
            self.btn_remove_selected.setText(f"{label} ({selected_count})")
        else:
            self.btn_remove_selected.setText(label)

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
            self.add_image(path)
