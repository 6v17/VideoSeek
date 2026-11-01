"""Image gallery: same library chrome as the video page, search on the Pictures tab."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.button_roles import set_button_role
from ui.widgets.flow_layout import FlowLayout
from ui.widgets.library_video_tree import LibraryGroupedVideoTree, LibraryIconButton
from ui.widgets.list_find_bar import list_find_text_kwargs
from ui.widgets.scaffold import PageScaffold, VSCard, VSProgressStatusRow

class ImageGalleryBoard(VSCard):
    """Still board for the Pictures tab. The video player stays on the other tabs."""

    def __init__(self, parent=None):
        super().__init__(margins=(14, 12, 14, 12), spacing=8, parent=parent)
        self._texts: dict = {}
        self._pixmap = QPixmap()
        self._path = ""
        self._score: float | None = None
        self._missing = False
        self._well_height = -1
        layout = self.content_layout

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self.title_label = QLabel()
        self.title_label.setObjectName("CardTitle")
        self.btn_copy = QPushButton()
        set_button_role(self.btn_copy, "GhostButton")
        self.btn_copy.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_copy.setFixedHeight(28)
        self.btn_copy.setEnabled(False)
        self.btn_copy.clicked.connect(self._copy_path)
        self.btn_collapse = QToolButton()
        self.btn_collapse.setObjectName("SidebarIconButton")
        self.btn_collapse.setText("»")
        self.btn_collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_collapse.setFixedSize(28, 28)
        self.btn_collapse.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_collapse.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        header.addWidget(self.title_label, 1)
        header.addWidget(self.btn_copy, 0, Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.btn_collapse, 0, Qt.AlignmentFlag.AlignTop)

        self.well = QFrame()
        self.well.setObjectName("GalleryBoardWell")
        self.well.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        well_layout = QVBoxLayout(self.well)
        well_layout.setContentsMargins(12, 12, 12, 12)
        well_layout.setSpacing(0)
        self.image_label = QLabel()
        self.image_label.setObjectName("GalleryBoardImage")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setWordWrap(True)
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        well_layout.addWidget(self.image_label, 1)

        self.info_wrap = QFrame()
        self.info_wrap.setObjectName("PreviewDetail")
        self.info_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_layout = QVBoxLayout(self.info_wrap)
        info_layout.setContentsMargins(0, 8, 0, 0)
        info_layout.setSpacing(4)
        self.name_label = QLabel()
        self.name_label.setObjectName("SectionTitle")
        self.name_label.setWordWrap(True)
        self.name_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_layout.addWidget(self.name_label)
        self._rows: dict[str, tuple[QLabel, QLabel]] = {}
        for key in ("location", "dimensions", "bytes", "modified", "score"):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            caption = QLabel()
            caption.setObjectName("InlineFieldLabel")
            caption.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            caption.setMinimumWidth(72)
            value = QLabel()
            value.setObjectName("DialogMetaLabel")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            row.addWidget(caption, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(value, 1)
            info_layout.addLayout(row)
            self._rows[key] = (caption, value)
        self.info_wrap.hide()

        layout.addLayout(header)
        layout.addWidget(self.well, 0)
        layout.addWidget(self.info_wrap, 0)
        layout.addStretch(1)
        self.show_empty()

    def set_texts(self, texts: dict) -> None:
        self._texts = dict(texts or {})
        self.title_label.setText(self._texts.get("gallery_board_title", ""))
        self.btn_collapse.setToolTip(self._texts.get("preview_card_collapse", ""))
        copy_text = self._texts.get("details_copy_selected", self._texts.get("copy", ""))
        self.btn_copy.setText(copy_text)
        self.btn_copy.setToolTip(copy_text)
        captions = {
            "location": "gallery_info_location",
            "dimensions": "gallery_info_dimensions",
            "bytes": "gallery_info_bytes",
            "modified": "gallery_info_modified",
            "score": "gallery_info_score",
        }
        for key, text_key in captions.items():
            self._rows[key][0].setText(self._texts.get(text_key, ""))
        if self._path:
            self._fill_info()
        else:
            self.image_label.setText(self._texts.get("gallery_preview_empty", ""))

    def show_empty(self, texts: dict | None = None) -> None:
        if texts:
            self._texts = dict(texts)
            self.title_label.setText(self._texts.get("gallery_board_title", ""))
        self._path = ""
        self._score = None
        self._missing = False
        self._pixmap = QPixmap()
        self.image_label.setPixmap(QPixmap())
        self.image_label.setText(self._texts.get("gallery_preview_empty", ""))
        self.name_label.clear()
        for _caption, value in self._rows.values():
            value.clear()
        self.info_wrap.hide()
        self.btn_copy.setEnabled(False)
        self._fit_pixmap()

    def show_still(self, image, path: str, score: float | None, texts: dict) -> None:
        self._path = str(path or "")
        self._score = None if score is None else float(score)
        self._missing = image is None or image.isNull()
        self._pixmap = QPixmap() if self._missing else QPixmap.fromImage(image)
        if self._missing:
            self.image_label.setPixmap(QPixmap())
        self.info_wrap.show()
        self.btn_copy.setEnabled(bool(self._path))
        self.set_texts(texts)
        if self._missing:
            self.image_label.setText(self._texts.get("gallery_file_missing", ""))
        self._fit_pixmap()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._fit_pixmap()

    def refit(self) -> None:
        self._fit_pixmap()

    def _copy_path(self) -> None:
        path = str(self._path or "").strip()
        if not path:
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
        self.btn_copy.setText(self._texts.get("copied", ""))
        QTimer.singleShot(1200, self, self._restore_copy_text)

    def _restore_copy_text(self) -> None:
        copy_text = self._texts.get("details_copy_selected", self._texts.get("copy", ""))
        self.btn_copy.setText(copy_text)

    def _frame_width(self) -> int:
        width = self.well.width()
        if width < 80:
            margins = self.content_layout.contentsMargins()
            width = self.width() - margins.left() - margins.right()
        return max(160, width)

    def _apply_well_height(self, height: int) -> None:
        height = max(1, int(height))
        if height == self._well_height and self.well.maximumHeight() == height and self.well.minimumHeight() == height:
            return
        self._well_height = height
        self.well.setMinimumHeight(height)
        self.well.setMaximumHeight(height)

    def _landscape_well_height(self) -> int:
        """A 16:9 frame, the same proportion as a landscape still. Info stays underneath."""
        aspect = max(1, int(round(self._frame_width() * 9 / 16)))
        info_h = self.info_wrap.sizeHint().height() if self.info_wrap.isVisible() else 0
        header_h = max(28, self.title_label.sizeHint().height(), self.btn_copy.sizeHint().height())
        margins = self.content_layout.contentsMargins()
        spacing = self.content_layout.spacing()
        gaps = spacing * (2 if info_h else 1)
        fixed = margins.top() + margins.bottom() + gaps + header_h + info_h
        if self.height() < 120:
            return aspect
        budget = max(1, self.height() - fixed)
        if budget > aspect + 36:
            height = aspect
        elif budget > 120:
            height = budget
        else:
            height = budget
        return max(1, min(aspect, height, budget))

    def _fit_pixmap(self) -> None:
        self._apply_well_height(self._landscape_well_height())
        if self._pixmap.isNull():
            return
        inner_w = max(8, self.well.width() - 24)
        inner_h = max(8, self.well.height() - 24)
        scaled = self._pixmap.scaled(
            inner_w,
            inner_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setText("")
        self.image_label.setPixmap(scaled)

    def _fill_info(self) -> None:
        path = self._path
        self.name_label.setText(_basename(path))
        self.name_label.setToolTip(path)
        location, value = self._rows["location"]
        del location
        value.setText(path)
        value.setToolTip(path)
        width, height = _pixel_size(path)
        dimensions = "" if width <= 0 or height <= 0 else f"{width} × {height}"
        self._rows["dimensions"][1].setText(dimensions)
        size_text, modified = _file_stat_text(path)
        self._rows["bytes"][1].setText(size_text)
        self._rows["modified"][1].setText(modified)
        score_caption, score_value = self._rows["score"]
        if self._score is None:
            score_caption.hide()
            score_value.hide()
            score_value.clear()
        else:
            score_caption.show()
            score_value.show()
            score_value.setText(f"{self._score:.3f}")


def _pixel_size(path: str) -> tuple[int, int]:
    try:
        from src.core.image_io import image_pixel_size
    except Exception:
        return 0, 0
    size = image_pixel_size(path)
    if not size:
        return 0, 0
    return size


def _file_stat_text(path: str) -> tuple[str, str]:
    try:
        stat = os.stat(path)
    except OSError:
        return "", ""
    return _format_bytes(int(stat.st_size)), datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")


def _format_bytes(size: int) -> str:
    value = float(max(0, int(size)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)} B"
            text = f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
        value /= 1024.0
    return f"{int(size)} B"


class ImageGalleryPage(QWidget):
    add_folder_clicked = Signal()
    remove_folder_clicked = Signal()
    sync_clicked = Signal()
    refresh_clicked = Signal()
    open_folder_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._busy = False
        self._sync_text = ""
        self._stop_text = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scaffold = PageScaffold()
        root.addWidget(self.scaffold)
        self.header = self.scaffold.header
        page_body = self.scaffold.content_layout

        self.shared_toolbar_card = VSCard(
            variant="sub",
            margins=(12, 8, 12, 8),
            spacing=6,
            object_name="LibrarySharedStrip",
        )
        shared_outer = self.shared_toolbar_card.content_layout
        chrome_row = QHBoxLayout()
        chrome_row.setContentsMargins(0, 0, 0, 0)
        chrome_row.setSpacing(10)
        chrome_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        action_block = QVBoxLayout()
        action_block.setContentsMargins(0, 0, 0, 0)
        action_block.setSpacing(2)
        self.lbl_action_caption = QLabel()
        self.lbl_action_caption.setObjectName("LibraryChromeCaption")
        action_block.addWidget(self.lbl_action_caption)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self.btn_add_folder = QPushButton()
        set_button_role(self.btn_add_folder, "SuccessGhostButton")
        self.btn_remove_folder = QPushButton()
        set_button_role(self.btn_remove_folder, "DangerGhostButton")
        self.btn_remove_folder.setEnabled(False)
        for button in (self.btn_add_folder, self.btn_remove_folder):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            action_row.addWidget(button)
        action_block.addLayout(action_row)
        chrome_row.addLayout(action_block, 0)
        chrome_row.addStretch(1)
        shared_outer.addLayout(chrome_row)

        self.lbl_search_hint = QLabel()
        self.lbl_search_hint.setObjectName("LibraryChromeHint")
        self.lbl_search_hint.setWordWrap(True)
        shared_outer.addWidget(self.lbl_search_hint)
        page_body.addWidget(self.shared_toolbar_card)

        self.table_card = VSCard(margins=(16, 14, 16, 14), spacing=12)
        table_layout = self.table_card.content_layout
        self.table_title = QLabel()
        self.table_title.setObjectName("CardTitle")
        table_layout.addWidget(self.table_title)

        toolbar_host = QWidget()
        toolbar_host.setObjectName("LibraryToolbarFlow")
        toolbar = FlowLayout(toolbar_host, spacing=8)
        self.btn_sync = QPushButton()
        set_button_role(self.btn_sync, "PrimaryButton")
        self.btn_sync.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh = LibraryIconButton("refresh")
        set_button_role(self.btn_refresh, "GhostButton")
        self.folder_tree = LibraryGroupedVideoTree()
        self.folder_tree.setMinimumHeight(280)
        self.folder_tree.set_row_icon(_image_file_icon(self))
        toolbar.addWidget(self.btn_sync)
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.folder_tree.find_bar)
        table_layout.addWidget(toolbar_host)
        table_layout.addWidget(self.folder_tree, 1)
        self.folder_tree.find_bar.install_shortcuts(self.table_card)
        page_body.addWidget(self.table_card, 1)

        self.progress = VSProgressStatusRow()
        self.progress.set_progress_visible(False)
        page_body.addWidget(self.progress)

        self.btn_add_folder.clicked.connect(self.add_folder_clicked.emit)
        self.btn_remove_folder.clicked.connect(self.remove_folder_clicked.emit)
        self.btn_sync.clicked.connect(self.sync_clicked.emit)
        self.btn_refresh.clicked.connect(self.refresh_clicked.emit)
        self.folder_tree.open_library_requested.connect(self.open_folder_requested.emit)
        self.folder_tree.selection_changed.connect(self._sync_remove_enabled)

    def apply_texts(self, texts: dict) -> None:
        self.header.title.setText(texts.get("gallery_page_title", "Gallery"))
        self.header.subtitle.hide()
        self.lbl_action_caption.setText(texts.get("library_action_caption", ""))
        self.btn_add_folder.setText(texts.get("gallery_add_folder", ""))
        self.btn_remove_folder.setText(texts.get("gallery_remove_folder", ""))
        self.table_title.setText(texts.get("gallery_folders_title", ""))
        self._sync_text = texts.get("gallery_sync", "")
        self._stop_text = texts.get("gallery_stop", "")
        self.btn_sync.setText(self._stop_text if self._busy else self._sync_text)
        self.btn_refresh.setText("")
        self.btn_refresh.setAccessibleName(texts.get("gallery_refresh", ""))
        self.btn_refresh.setToolTip(texts.get("gallery_refresh_hint", ""))
        self.lbl_search_hint.setText(texts.get("gallery_search_elsewhere", ""))
        find = list_find_text_kwargs(texts)
        find["find_placeholder"] = texts.get("gallery_find_placeholder", find.get("find_placeholder", ""))
        self.folder_tree.set_action_texts(
            open_text=texts.get("open_folder", "Open"),
            empty_text=texts.get("gallery_list_empty", ""),
            status_template=texts.get("gallery_folder_status", "{ready}/{total}"),
            offline_status_text=texts.get("library_path_missing_status", ""),
            header_video=texts.get("gallery_col_file", ""),
            header_count=texts.get("library_col_count", ""),
            header_status=texts.get("library_col_status", ""),
            header_action=texts.get("library_col_action", ""),
            **find,
        )

    def selected_folders(self) -> list[str]:
        return list(self.folder_tree.collect_checked_library_paths())

    def show_libraries(self, entries: list[dict], library_paths: list[str]) -> None:
        self.folder_tree.refresh_from_entries(entries, library_paths=library_paths)
        self._sync_remove_enabled()

    def set_status(self, text: str) -> None:
        self.progress.set_status_text(text)

    def set_progress(self, value: int | None, text: str) -> None:
        visible = value is not None
        self.progress.set_progress_visible(visible)
        if visible:
            self.progress.set_progress_value(max(0, min(100, int(value))))
        self.progress.set_status_text(text)

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.btn_add_folder.setEnabled(not self._busy)
        self.btn_refresh.setEnabled(not self._busy)
        self.btn_sync.setEnabled(True)
        self.btn_sync.setText(self._stop_text if self._busy else self._sync_text)
        self._sync_remove_enabled()

    def _sync_remove_enabled(self) -> None:
        self.btn_remove_folder.setEnabled((not self._busy) and bool(self.selected_folders()))


def _image_file_icon(widget: QWidget) -> QIcon:
    style = widget.style()
    generic = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon) if style is not None else QIcon()
    return QIcon.fromTheme("image-x-generic", generic)


def _basename(path: str) -> str:
    text = str(path or "").replace("\\", "/").rstrip("/")
    if "/" not in text:
        return text
    return text.rsplit("/", 1)[-1]
