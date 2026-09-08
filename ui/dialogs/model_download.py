from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

import os

from src.app.app_meta import get_app_meta
from src.app.i18n import get_texts
from ui.dialogs.html_links import open_html_link
from ui.widgets.layout import WINDOW_SIZES, apply_dialog_size
from ui.widgets.scaffold import VSCard
from ui.widgets.sidebar_icons import github_toolbar_icon, package_toolbar_icon
from ui.widgets.styles import THEME_COLORS_DARK, THEME_COLORS_LIGHT, repolish_widget


def _format_bytes(size: int) -> str:
    value = float(max(0, int(size or 0)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


class ModelDropZone(QFrame):
    clicked = Signal()

    def __init__(self, texts: dict, *, is_dark: bool, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelUploadArea")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(88)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        self.icon_label = QLabel()
        self.icon_label.setObjectName("ModelUploadIcon")
        self.icon_label.setFixedSize(40, 40)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(package_toolbar_icon(is_dark=is_dark, size=36).pixmap(36, 36))

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.title_label = QLabel(texts.get("model_upload_area_title", "Import model package"))
        self.title_label.setObjectName("ModelUploadTitle")
        self.formats_label = QLabel(
            texts.get("model_upload_area_formats", "Supports zip / sha256 / ffmpeg.exe")
        )
        self.formats_label.setObjectName("ModelUploadMeta")
        self.action_label = QLabel(texts.get("model_upload_area_action", "Click or drop files here"))
        self.action_label.setObjectName("ModelUploadAction")
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.formats_label)
        text_col.addWidget(self.action_label)

        row.addWidget(self.icon_label, 0, Qt.AlignVCenter)
        row.addLayout(text_col, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def setEnabled(self, enabled):
        super().setEnabled(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)


class ModelPendingRow(QFrame):
    def __init__(self, path: str, texts: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("ModelPendingRow")
        self.setProperty("selected", False)
        self.path = path
        name = os.path.basename(path) or path
        lower = name.lower()
        if lower.endswith(".zip"):
            kind = texts.get("model_pending_kind_zip", "Model package")
        elif lower.endswith(".sha256"):
            kind = texts.get("model_pending_kind_sha256", "Checksum")
        elif lower.endswith("ffmpeg.exe") or lower.endswith(".exe"):
            kind = texts.get("model_pending_kind_ffmpeg", "FFmpeg")
        else:
            kind = texts.get("model_pending_kind_file", "File")
        try:
            size_text = _format_bytes(os.path.getsize(path))
        except OSError:
            size_text = texts.get("model_pending_size_unknown", "Size unknown")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("ModelPendingRowName")
        self.name_label.setWordWrap(False)
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.meta_label = QLabel(f"{kind} · {size_text}")
        self.meta_label.setObjectName("ModelPendingRowMeta")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.meta_label)
        layout.addLayout(text_col, 1)
        self.setToolTip(path)
        self.setMinimumHeight(44)

    def set_selected(self, selected: bool):
        self.setProperty("selected", bool(selected))
        repolish_widget(self)


class ModelDownloadDialog(QDialog):
    upload_requested = Signal()
    import_requested = Signal(list)
    go_download_requested = Signal()
    go_github_download_requested = Signal()

    def __init__(self, parent=None, is_dark=True, language="zh"):
        super().__init__(parent)
        self.texts = get_texts(language)
        self._is_dark = bool(is_dark)
        self._downloading = False
        self._selected_files = []
        self._mode = "manage"

        self.setObjectName("ModelImportDialog")
        self.setWindowTitle(self.texts.get("model_import_dialog_title", self.texts["models_missing_title"]))
        self.setModal(True)
        self.setAcceptDrops(True)
        self.setWindowFlag(Qt.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        apply_dialog_size(
            self,
            QSize(560, 500),
            QSize(520, 440),
            WINDOW_SIZES["notice_dialog"]["screen_margin"],
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        self._card = VSCard(variant="dialog", margins=(12, 10, 12, 8), spacing=5, parent=self)
        layout = self._card.content_layout

        self.title_label = QLabel(self.texts.get("model_import_dialog_title", self.texts["models_missing_title"]))
        self.title_label.setObjectName("DialogInlineTitle")

        meta_row = QHBoxLayout()
        meta_row.setSpacing(8)
        self.status_caption = QLabel(self.texts.get("model_runtime_status_caption", "Runtime"))
        self.status_caption.setObjectName("Hint")
        self.status_inline = QLabel()
        self.status_inline.setObjectName("ModelResourceStatusInline")
        meta_row.addWidget(self.status_caption, 0)
        meta_row.addWidget(self.status_inline, 0)
        meta_row.addStretch(1)

        self.subtitle_label = QLabel()
        self.subtitle_label.setObjectName("Hint")
        self.subtitle_label.setWordWrap(True)

        self.guide_section = QFrame(self._card)
        self.guide_section.setObjectName("ModelImportGuide")
        guide_layout = QVBoxLayout(self.guide_section)
        guide_layout.setContentsMargins(12, 10, 12, 10)
        guide_layout.setSpacing(4)
        guide_header = QHBoxLayout()
        guide_header.setSpacing(8)
        self.guide_title = QLabel(self.texts.get("model_import_guide_title", "What you need"))
        self.guide_title.setObjectName("SectionLabel")
        self.guide_link_button = QPushButton(self.texts.get("model_import_guide_link", "Feishu guide"))
        self.guide_link_button.setObjectName("AccentGhostButton")
        self.guide_link_button.setMinimumHeight(26)
        self.guide_link_button.setCursor(Qt.PointingHandCursor)
        guide_header.addWidget(self.guide_title, 0)
        guide_header.addStretch(1)
        guide_header.addWidget(self.guide_link_button, 0)
        self.guide_need_ffmpeg = QLabel(self.texts.get("model_import_guide_ffmpeg", ""))
        self.guide_need_ffmpeg.setObjectName("ModelImportGuideLine")
        self.guide_need_ffmpeg.setWordWrap(True)
        self.guide_need_model = QLabel(self.texts.get("model_import_guide_model", ""))
        self.guide_need_model.setObjectName("ModelImportGuideLine")
        self.guide_need_model.setWordWrap(True)
        self.guide_need_ocr = QLabel(self.texts.get("model_import_guide_ocr", ""))
        self.guide_need_ocr.setObjectName("ModelImportGuideLine")
        self.guide_need_ocr.setWordWrap(True)
        self.guide_pick_title = QLabel(self.texts.get("model_import_guide_pick_title", ""))
        self.guide_pick_title.setObjectName("ModelImportGuideSubTitle")
        self.guide_pick_cnclip = QLabel(self.texts.get("model_import_guide_pick_cnclip", ""))
        self.guide_pick_cnclip.setObjectName("ModelImportGuideLine")
        self.guide_pick_cnclip.setWordWrap(True)
        self.guide_pick_siglip = QLabel(self.texts.get("model_import_guide_pick_siglip", ""))
        self.guide_pick_siglip.setObjectName("ModelImportGuideLine")
        self.guide_pick_siglip.setWordWrap(True)
        self.guide_pick_clip = QLabel(self.texts.get("model_import_guide_pick_clip", ""))
        self.guide_pick_clip.setObjectName("ModelImportGuideLine")
        self.guide_pick_clip.setWordWrap(True)
        guide_layout.addLayout(guide_header)
        guide_layout.addWidget(self.guide_need_ffmpeg)
        guide_layout.addWidget(self.guide_need_model)
        guide_layout.addWidget(self.guide_need_ocr)
        guide_layout.addWidget(self.guide_pick_title)
        guide_layout.addWidget(self.guide_pick_cnclip)
        guide_layout.addWidget(self.guide_pick_siglip)
        guide_layout.addWidget(self.guide_pick_clip)

        self.upload_area = ModelDropZone(self.texts, is_dark=self._is_dark, parent=self._card)

        download_row = QHBoxLayout()
        download_row.setSpacing(8)
        download_row.setContentsMargins(0, 0, 0, 0)
        self.go_github_download_button = QPushButton(
            self.texts.get("model_go_github_download", "GitHub 下载")
        )
        self.go_github_download_button.setObjectName("GhostButton")
        self.go_github_download_button.setCursor(Qt.PointingHandCursor)
        self.go_github_download_button.setIcon(github_toolbar_icon(is_dark=self._is_dark, size=16))
        self.go_github_download_button.setIconSize(QSize(16, 16))
        self.go_github_download_button.setMinimumHeight(36)
        self.go_download_button = QPushButton(self.texts.get("model_go_download_page", "123盘下载"))
        self.go_download_button.setObjectName("GhostButton")
        self.go_download_button.setCursor(Qt.PointingHandCursor)
        self.go_download_button.setMinimumHeight(36)
        download_row.addWidget(self.go_github_download_button, 1)
        download_row.addWidget(self.go_download_button, 1)

        self.pending_section = QFrame(self._card)
        self.pending_section.setObjectName("ModelPendingPanel")
        pending_layout = QVBoxLayout(self.pending_section)
        pending_layout.setContentsMargins(10, 10, 10, 10)
        pending_layout.setSpacing(6)
        pending_header = QHBoxLayout()
        pending_header.setSpacing(6)
        self.pending_title = QLabel(self.texts.get("model_pending_section", "Ready to import"))
        self.pending_title.setObjectName("SectionLabel")
        self.pending_count = QLabel()
        self.pending_count.setObjectName("ModelPendingCount")
        self.add_more_button = QPushButton(self.texts.get("model_upload_area_add_more", "Add"))
        self.add_more_button.setObjectName("AccentGhostButton")
        self.add_more_button.setMinimumHeight(28)
        self.remove_files_button = QPushButton(self.texts.get("model_upload_remove_selected", "Remove"))
        self.remove_files_button.setObjectName("DangerGhostButton")
        self.remove_files_button.setMinimumHeight(28)
        self.clear_files_button = QPushButton(self.texts.get("model_upload_clear_files", "Clear"))
        self.clear_files_button.setObjectName("GhostButton")
        self.clear_files_button.setMinimumHeight(28)
        pending_header.addWidget(self.pending_title, 0)
        pending_header.addWidget(self.pending_count, 0)
        pending_header.addStretch(1)
        pending_header.addWidget(self.add_more_button, 0)
        pending_header.addWidget(self.remove_files_button, 0)
        pending_header.addWidget(self.clear_files_button, 0)
        self.upload_file_list = QListWidget()
        self.upload_file_list.setObjectName("ModelFileList")
        self.upload_file_list.setMinimumHeight(72)
        self.upload_file_list.setMaximumHeight(160)
        self.upload_file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.upload_file_list.setAlternatingRowColors(False)
        self.upload_file_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        pending_layout.addLayout(pending_header)
        pending_layout.addWidget(self.upload_file_list)

        self.progress_title = QLabel(self.texts["model_download_waiting"])
        self.progress_title.setObjectName("Hint")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label = QLabel()
        self.progress_label.setObjectName("DialogBodyLabel")
        self.progress_label.setWordWrap(True)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.import_button = QPushButton()
        self.import_button.setObjectName("PrimaryButton")
        self.import_button.setMinimumHeight(40)
        self.done_button = QPushButton(self.texts["model_ready_action"])
        self.done_button.setObjectName("PrimaryButton")
        self.done_button.setMinimumHeight(40)
        self.done_button.hide()
        action_row.addWidget(self.import_button, 1)
        action_row.addWidget(self.done_button, 1)

        # Compatibility aliases for older chrome helpers.
        self.body_label = QLabel(self)
        self.body_label.hide()
        self.status_bar = self.status_inline
        self.add_files_button = self.upload_area
        self.sources_label = QLabel(self)
        self.sources_label.hide()
        self.sources_section = QWidget(self)
        self.installed_section = QWidget(self)
        self.installed_section.hide()

        layout.addWidget(self.title_label)
        layout.addLayout(meta_row)
        layout.addWidget(self.subtitle_label)
        layout.addWidget(self.guide_section)
        layout.addWidget(self.pending_section)
        layout.addWidget(self.upload_area)
        layout.addWidget(self.progress_title)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.progress_label)
        layout.addLayout(download_row)
        layout.addLayout(action_row)
        outer.addWidget(self._card)

        self.remove_files_button.clicked.connect(self._remove_selected_files)
        self.clear_files_button.clicked.connect(self._clear_files)
        self.add_more_button.clicked.connect(self._select_files)
        self.upload_area.clicked.connect(self._select_files)
        self.import_button.clicked.connect(self._on_primary_clicked)
        self.go_github_download_button.clicked.connect(self.go_github_download_requested.emit)
        self.go_download_button.clicked.connect(self.go_download_requested.emit)
        self.guide_link_button.clicked.connect(self._open_model_guide)
        self.done_button.clicked.connect(self.accept)
        self.upload_file_list.itemSelectionChanged.connect(self._sync_pending_actions)
        self._refresh_file_list()

    def showEvent(self, event):
        super().showEvent(event)
        for delay_ms in (0, 16, 50, 120, 200):
            QTimer.singleShot(delay_ms, self._center_over_parent_or_screen)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(0, self._center_over_parent_or_screen)

    def _center_over_parent_or_screen(self):
        if not self.isVisible():
            return
        center_point = None
        parent = self.parentWidget()
        if parent is not None:
            top = parent.window()
            if top is not None and top.isVisible():
                frame_top = top.frameGeometry()
                if frame_top.width() >= 200 and frame_top.height() >= 200:
                    center_point = frame_top.center()
        if center_point is None:
            screen = None
            if parent is not None:
                ref = parent.mapToGlobal(parent.rect().center())
                screen = QGuiApplication.screenAt(ref)
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            center_point = screen.availableGeometry().center()
        frame = self.frameGeometry()
        frame.moveCenter(center_point)
        self.move(frame.topLeft())

    def _open_model_guide(self):
        url = str(get_app_meta().get("model_guide_url", "") or "").strip()
        if url:
            open_html_link(url)

    def _refresh_upload_area_text(self):
        # Drop zone labels are set at construction; keep for API compatibility.
        return

    def _set_status_chips(self, *, has_model_missing: bool, has_ffmpeg_missing: bool):
        c = THEME_COLORS_DARK if self._is_dark else THEME_COLORS_LIGHT
        ok = c["SUCCESS"]
        bad = c["DANGER"]
        parts = []
        if has_model_missing:
            parts.append(
                f"<span style='color:{bad};'>{self.texts.get('resource_status_model_bad_short', '模型 ✗')}</span>"
            )
        else:
            parts.append(
                f"<span style='color:{ok};'>{self.texts.get('resource_status_model_ok_short', '模型 ✓')}</span>"
            )
        if has_ffmpeg_missing:
            parts.append(
                f"<span style='color:{bad};'>{self.texts.get('resource_status_ffmpeg_bad_short', 'FFmpeg ✗')}</span>"
            )
        else:
            parts.append(
                f"<span style='color:{ok};'>{self.texts.get('resource_status_ffmpeg_ok_short', 'FFmpeg ✓')}</span>"
            )
        self.status_inline.setTextFormat(Qt.RichText)
        self.status_inline.setText("   ".join(parts))

    def refresh_installed_models(self, *, ffmpeg_ready: bool | None = None):
        return

    def _sync_primary_cta(self):
        has_files = bool(self._selected_files)
        if self._downloading:
            self.import_button.setEnabled(False)
            return
        if has_files:
            self.import_button.setText(self.texts.get("model_upload_package", "Import"))
            self.import_button.setObjectName("SearchButton")
            self.import_button.setEnabled(True)
        else:
            self.import_button.setText(self.texts.get("model_upload_choose_cta", "Choose package"))
            self.import_button.setObjectName("PrimaryButton")
            self.import_button.setEnabled(True)
        repolish_widget(self.import_button)

    def _on_primary_clicked(self):
        if self._selected_files:
            self._emit_import_requested()
        else:
            self._select_files()

    def _show_import_chrome(self, *, download_enabled: bool = True):
        self.status_caption.show()
        self.status_inline.show()
        self.progress_title.hide()
        self.progress_bar.hide()
        self.progress_label.hide()
        self.import_button.show()
        self.go_download_button.show()
        self.go_download_button.setEnabled(download_enabled)
        self.go_github_download_button.show()
        self.go_github_download_button.setEnabled(True)
        self.done_button.hide()
        self._refresh_file_list()

    def _set_busy_chrome(self):
        self.status_caption.hide()
        self.status_inline.hide()
        self.subtitle_label.hide()
        self.guide_section.hide()
        self.upload_area.hide()
        self.pending_section.hide()
        self.go_download_button.hide()
        self.go_github_download_button.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.import_button.setEnabled(False)
        self.done_button.hide()

    def set_missing_state(self, missing_files, folder, download_enabled=True):
        self._downloading = False
        self._mode = "missing"
        has_model_missing = any(str(item).lower() != "ffmpeg.exe" for item in (missing_files or []))
        has_ffmpeg_missing = any(str(item).lower() == "ffmpeg.exe" for item in (missing_files or []))
        if has_model_missing and has_ffmpeg_missing:
            subtitle = self.texts.get("models_missing_generic_both", "Model and FFmpeg are not ready.")
        elif has_model_missing:
            subtitle = self.texts.get("models_missing_generic_model", "Model resources are missing.")
        elif has_ffmpeg_missing:
            subtitle = self.texts.get("models_missing_generic_ffmpeg", "FFmpeg is missing.")
        else:
            subtitle = self.texts.get(
                "model_import_dialog_subtitle_missing",
                "Import a model package or FFmpeg to continue.",
            )
        self.title_label.setText(self.texts.get("model_import_dialog_title", self.texts["models_missing_title"]))
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.setText(subtitle)
        self.subtitle_label.show()
        self._set_status_chips(has_model_missing=has_model_missing, has_ffmpeg_missing=has_ffmpeg_missing)
        self._show_import_chrome(download_enabled=download_enabled)

    def set_progress_state(self, value, text):
        self._downloading = True
        self.title_label.setText(self.texts["download_models"])
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.hide()
        self.progress_title.setText(self.texts["model_download_in_progress"])
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)
        self._set_busy_chrome()

    def set_import_progress_state(self, value, text):
        self._downloading = True
        self.title_label.setText(self.texts.get("model_upload_package", "Import"))
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.hide()
        self.progress_title.setText(self.texts.get("model_import_in_progress", "Importing model package"))
        self.progress_bar.setValue(value)
        self.progress_label.setText(text)
        self._set_busy_chrome()

    def set_error_state(self, error_text, missing_files, folder, download_enabled=True):
        self._downloading = False
        self._mode = "error"
        has_model_missing = any(str(item).lower() != "ffmpeg.exe" for item in (missing_files or []))
        has_ffmpeg_missing = any(str(item).lower() == "ffmpeg.exe" for item in (missing_files or []))
        self.title_label.setText(self.texts["model_download_failed"])
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.setText(error_text or "")
        self.subtitle_label.setVisible(bool(error_text))
        self._set_status_chips(has_model_missing=has_model_missing, has_ffmpeg_missing=has_ffmpeg_missing)
        self._show_import_chrome(download_enabled=download_enabled)
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["warning_title"])
        self.progress_bar.setValue(0)
        self.progress_label.setText(error_text)

    def set_success_state(self, folder):
        self._downloading = False
        self._mode = "success"
        self.title_label.setText(self.texts["success_title"])
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.setText(self.texts["model_download_done"])
        self.subtitle_label.show()
        self.status_caption.hide()
        self.status_inline.hide()
        self.upload_area.hide()
        self.guide_section.hide()
        self.pending_section.hide()
        self.go_download_button.hide()
        self.go_github_download_button.hide()
        self.progress_title.show()
        self.progress_bar.show()
        self.progress_label.show()
        self.progress_title.setText(self.texts["model_download_in_progress"])
        self.progress_bar.setValue(100)
        self.progress_label.setText(self.texts["model_ready_hint"])
        self.import_button.hide()
        self.done_button.show()

    def set_import_success_state(self, message=""):
        self._downloading = False
        self._mode = "import_success"
        self.title_label.setText(self.texts["success_title"])
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.setText(
            message or self.texts.get("model_import_success", "Model package imported successfully.")
        )
        self.subtitle_label.show()
        self.status_caption.hide()
        self.status_inline.hide()
        self.upload_area.hide()
        self.guide_section.hide()
        self.pending_section.hide()
        self.go_download_button.hide()
        self.go_github_download_button.hide()
        self.progress_title.hide()
        self.progress_bar.hide()
        self.progress_label.hide()
        self.import_button.hide()
        self.done_button.show()

    def set_manage_state(self):
        self._downloading = False
        self._mode = "manage"
        self.title_label.setText(self.texts.get("model_import_dialog_title", self.texts["models_missing_title"]))
        self.setWindowTitle(self.title_label.text())
        self.subtitle_label.clear()
        self.subtitle_label.hide()
        self._set_status_chips(has_model_missing=False, has_ffmpeg_missing=False)
        self._show_import_chrome(download_enabled=True)

    def _select_files(self):
        selected_files, _ = QFileDialog.getOpenFileNames(
            self,
            self.texts.get("model_upload_choose_cta", "Choose package"),
            "",
            "Runtime Package (*.zip *.sha256 *.exe);;All Files (*.*)",
        )
        self._append_files(selected_files)

    def _append_files(self, paths):
        changed = False
        for raw_path in paths or []:
            path = str(raw_path or "").strip()
            if not path:
                continue
            lower = path.lower()
            if not (lower.endswith(".zip") or lower.endswith(".sha256") or lower.endswith(".exe")):
                continue
            if path in self._selected_files:
                continue
            self._selected_files.append(path)
            changed = True
        if changed:
            self._refresh_file_list()

    def _sync_pending_actions(self):
        has_files = bool(self._selected_files)
        has_selection = bool(self.upload_file_list.selectedIndexes())
        self.remove_files_button.setEnabled(has_selection and not self._downloading)
        self.clear_files_button.setEnabled(has_files and not self._downloading)
        self.upload_area.setEnabled(not self._downloading)
        self.add_more_button.setEnabled(not self._downloading)
        selected_rows = {index.row() for index in self.upload_file_list.selectedIndexes()}
        for row in range(self.upload_file_list.count()):
            item = self.upload_file_list.item(row)
            widget = self.upload_file_list.itemWidget(item)
            if isinstance(widget, ModelPendingRow):
                widget.set_selected(row in selected_rows)
        self._sync_primary_cta()

    def _refresh_file_list(self):
        self.upload_file_list.clear()
        for path in self._selected_files:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, path)
            item.setToolTip(path)
            row = ModelPendingRow(path, self.texts)
            item.setSizeHint(row.sizeHint().expandedTo(QSize(0, 48)))
            self.upload_file_list.addItem(item)
            self.upload_file_list.setItemWidget(item, row)
        has_files = bool(self._selected_files)
        count = len(self._selected_files)
        self.pending_count.setText(
            self.texts.get("model_pending_count", "{count}").format(count=count) if has_files else ""
        )
        self.pending_section.setVisible(has_files and not self._downloading)
        show_choose = (not has_files) and not self._downloading
        self.upload_area.setVisible(show_choose)
        self.go_github_download_button.setVisible(not self._downloading)
        self.go_download_button.setVisible(not self._downloading)
        self.guide_section.setVisible(show_choose)
        self._sync_pending_actions()

    def _remove_selected_files(self):
        selected_rows = sorted(
            {index.row() for index in self.upload_file_list.selectedIndexes()},
            reverse=True,
        )
        if not selected_rows:
            return
        for row in selected_rows:
            if 0 <= row < len(self._selected_files):
                self._selected_files.pop(row)
        self._refresh_file_list()

    def _clear_files(self):
        if not self._selected_files:
            return
        self._selected_files.clear()
        self._refresh_file_list()

    def _emit_import_requested(self):
        if not self._selected_files:
            return
        self.import_requested.emit(list(self._selected_files))
        self.upload_requested.emit()
        self._clear_files()

    def dragEnterEvent(self, event):
        mime_data = event.mimeData()
        if mime_data and mime_data.hasUrls():
            for url in mime_data.urls():
                local = str(url.toLocalFile() or "").strip().lower()
                if local.endswith(".zip") or local.endswith(".sha256") or local.endswith(".exe"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        mime_data = event.mimeData()
        if not (mime_data and mime_data.hasUrls()):
            event.ignore()
            return
        dropped = [str(url.toLocalFile() or "").strip() for url in mime_data.urls()]
        self._append_files(dropped)
        event.acceptProposedAction()
