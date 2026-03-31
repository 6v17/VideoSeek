from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from ui.layout import COMPONENT_SIZES


class NavigationSidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavSidebar")
        self.setFixedWidth(COMPONENT_SIZES["sidebar_width"])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 18)
        layout.setSpacing(14)

        self.title = QLabel("VideoSeek")
        self.title.setObjectName("BrandTitle")
        self.subtitle = QLabel("Local video search workspace")
        self.subtitle.setObjectName("BrandSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(self.hero_card)
        hero_layout.setContentsMargins(14, 14, 14, 14)
        hero_layout.setSpacing(6)
        self.hero_tag = QLabel("WORKSPACE")
        self.hero_tag.setObjectName("HeroTag")
        self.hero_title = QLabel("Operate search, indexing, and settings separately")
        self.hero_title.setObjectName("HeroTitle")
        self.hero_title.setWordWrap(True)
        self.hero_body = QLabel("A cleaner shell for search, libraries, and runtime controls.")
        self.hero_body.setObjectName("HeroBody")
        self.hero_body.setWordWrap(True)
        hero_layout.addWidget(self.hero_tag)
        hero_layout.addWidget(self.hero_title)
        hero_layout.addWidget(self.hero_body)
        layout.addWidget(self.hero_card)

        self.btn_page_search = self._build_nav_button("Search", checked=True)
        self.btn_page_library = self._build_nav_button("Libraries")
        self.btn_page_settings = self._build_nav_button("Settings")
        layout.addWidget(self.btn_page_search)
        layout.addWidget(self.btn_page_library)
        layout.addWidget(self.btn_page_settings)
        self.runtime_hint = QLabel("")
        self.runtime_hint.setObjectName("StatusLabel")
        self.runtime_hint.setWordWrap(True)
        self.runtime_hint.hide()
        layout.addWidget(self.runtime_hint)
        layout.addStretch()

        self.btn_notice = QPushButton("Notes")
        self.btn_notice.setObjectName("SecondaryButton")
        self.btn_about = QPushButton("About")
        self.btn_about.setObjectName("SecondaryButton")
        self.btn_language = QPushButton("EN")
        self.btn_language.setObjectName("GhostButton")
        self.btn_theme = QPushButton("Dark")
        self.btn_theme.setObjectName("PrimaryButton")

        for button in [self.btn_notice, self.btn_about, self.btn_language, self.btn_theme]:
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(COMPONENT_SIZES["sidebar_action_height"])
            layout.addWidget(button)

    def _build_nav_button(self, text, checked=False):
        button = QPushButton(text)
        button.setObjectName("NavButton")
        button.setCheckable(True)
        button.setChecked(checked)
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(COMPONENT_SIZES["nav_button_height"])
        return button

    def set_current_page(self, page_name):
        mapping = {
            "search": self.btn_page_search,
            "library": self.btn_page_library,
            "settings": self.btn_page_settings,
        }
        for name, button in mapping.items():
            button.setChecked(name == page_name)


class PageHeader(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(4)
        self.title = QLabel()
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("PageSubtitle")
        self.subtitle.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.subtitle)


class SearchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.session_card = QFrame()
        self.session_card.setObjectName("PanelCard")
        session_layout = QHBoxLayout(self.session_card)
        session_layout.setContentsMargins(18, 12, 18, 12)
        session_layout.setSpacing(12)
        self.session_title = QLabel()
        self.session_title.setObjectName("CardTitle")
        self.session_hint = QLabel()
        self.session_hint.setObjectName("CardHint")
        self.session_hint.setWordWrap(True)
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        session_layout.addWidget(self.session_title, 0)
        session_layout.addWidget(self.session_hint, 1)
        session_layout.addWidget(self.lbl_status, 1)
        root.addWidget(self.session_card)

        compare_row = QHBoxLayout()
        compare_row.setSpacing(12)

        self.query_card = QFrame()
        self.query_card.setObjectName("PanelCard")
        query_layout = QVBoxLayout(self.query_card)
        query_layout.setContentsMargins(18, 18, 18, 18)
        query_layout.setSpacing(10)

        self.controls_title = QLabel()
        self.controls_title.setObjectName("CardTitle")
        self.controls_hint = QLabel()
        self.controls_hint.setObjectName("CardHint")
        self.controls_hint.setWordWrap(True)
        self.img_label = QLabel()
        self.img_label.setObjectName("ImageDropZone")
        self.img_label.setAlignment(Qt.AlignCenter)
        self.img_label.setWordWrap(True)
        self.img_label.setMinimumHeight(COMPONENT_SIZES["image_drop_min_height"])
        self.btn_browse = QPushButton()
        self.btn_browse.setObjectName("SecondaryButton")
        self.text_search = QLineEdit()
        self.text_search.setObjectName("SearchInput")

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_search = QPushButton()
        self.btn_search.setObjectName("SearchButton")
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("GhostButton")
        action_row.addWidget(self.btn_search, 1)
        action_row.addWidget(self.btn_clear)

        query_layout.addWidget(self.controls_title)
        query_layout.addWidget(self.controls_hint)
        query_layout.addWidget(self.img_label)
        query_layout.addWidget(self.btn_browse)
        query_layout.addWidget(self.text_search)
        query_layout.addLayout(action_row)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("PanelCard")
        preview_layout = QVBoxLayout(self.preview_card)
        preview_layout.setContentsMargins(18, 18, 18, 18)
        preview_layout.setSpacing(10)
        self.preview_title = QLabel()
        self.preview_title.setObjectName("CardTitle")
        self.preview_host = QFrame()
        self.preview_host.setObjectName("VideoContainer")
        self.preview_host.setMinimumHeight(COMPONENT_SIZES["preview_host_min_height"])
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(6, 6, 6, 6)
        self.preview_placeholder = QLabel()
        self.preview_placeholder.setObjectName("PreviewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_host_layout.addWidget(self.preview_placeholder)
        preview_layout.addWidget(self.preview_title)
        preview_layout.addWidget(self.preview_host, 1)
        compare_row.addWidget(self.query_card, 5)
        compare_row.addWidget(self.preview_card, 7)
        root.addLayout(compare_row, 3)

        self.results_card = QFrame()
        self.results_card.setObjectName("PanelCard")
        results_layout = QVBoxLayout(self.results_card)
        results_layout.setContentsMargins(18, 18, 18, 18)
        results_layout.setSpacing(10)
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.result_table = ResultTable()
        self.result_table.setMinimumHeight(COMPONENT_SIZES["result_table_min_height"])
        results_layout.addWidget(self.results_title)
        results_layout.addWidget(self.result_table)
        root.addWidget(self.results_card, 4)


class LibraryPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.toolbar_card = QFrame()
        self.toolbar_card.setObjectName("PanelCard")
        toolbar_card_layout = QVBoxLayout(self.toolbar_card)
        toolbar_card_layout.setContentsMargins(18, 16, 18, 16)
        toolbar_card_layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.btn_add_lib = QPushButton()
        self.btn_add_lib.setObjectName("SecondaryButton")
        self.btn_sync_db = QPushButton()
        self.btn_sync_db.setObjectName("PrimaryButton")
        toolbar.addWidget(self.btn_add_lib)
        toolbar.addWidget(self.btn_sync_db)
        toolbar.addStretch()

        progress_row = QHBoxLayout()
        progress_row.setSpacing(12)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(COMPONENT_SIZES["progress_bar_height"])
        self.progress_bar.setMinimumWidth(COMPONENT_SIZES["progress_bar_min_width"])
        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.lbl_status, 1)

        toolbar_card_layout.addLayout(toolbar)
        toolbar_card_layout.addLayout(progress_row)
        root.addWidget(self.toolbar_card)

        self.table_card = QFrame()
        self.table_card.setObjectName("PanelCard")
        table_layout = QVBoxLayout(self.table_card)
        table_layout.setContentsMargins(18, 18, 18, 18)
        table_layout.setSpacing(10)
        self.table_title = QLabel()
        self.table_title.setObjectName("CardTitle")
        self.lib_table = QTableWidget(0, 4)
        self.lib_table.setObjectName("LibTable")
        self.lib_table.verticalHeader().setVisible(False)
        self.lib_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.lib_table.setFocusPolicy(Qt.NoFocus)
        self.lib_table.setColumnWidth(0, 42)
        self.lib_table.setColumnWidth(2, 90)
        self.lib_table.setColumnWidth(3, 206)
        self.lib_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.lib_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.lib_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.lib_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.lib_table.verticalHeader().setDefaultSectionSize(42)
        table_layout.addWidget(self.table_title)
        table_layout.addWidget(self.lib_table)
        root.addWidget(self.table_card, 1)



class SettingsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.form_card = QFrame()
        self.form_card.setObjectName("PanelCard")
        form_layout = QVBoxLayout(self.form_card)
        form_layout.setContentsMargins(18, 18, 18, 18)
        form_layout.setSpacing(14)

        self.general_title = QLabel()
        self.general_title.setObjectName("CardTitle")
        form_layout.addWidget(self.general_title)

        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setFormAlignment(Qt.AlignTop)
        self.form.setHorizontalSpacing(18)
        self.form.setVerticalSpacing(12)

        self.input_fps = QSpinBox()
        self.input_fps.setRange(1, 24)
        self.input_top_k = QSpinBox()
        self.input_top_k.setRange(1, 200)
        self.input_preview_seconds = QSpinBox()
        self.input_preview_seconds.setRange(2, 20)
        self.input_preview_width = QSpinBox()
        self.input_preview_width.setRange(160, 1920)
        self.input_preview_height = QSpinBox()
        self.input_preview_height.setRange(90, 1080)
        self.input_thumb_width = QSpinBox()
        self.input_thumb_width.setRange(80, 480)
        self.input_thumb_height = QSpinBox()
        self.input_thumb_height.setRange(45, 320)
        self.input_prefer_gpu = QComboBox()
        self.input_ffmpeg_path = QLineEdit()
        self.input_model_dir = QLineEdit()
        self.label_fps = QLabel()
        self.label_top_k = QLabel()
        self.label_preview_seconds = QLabel()
        self.label_preview_width = QLabel()
        self.label_preview_height = QLabel()
        self.label_thumb_width = QLabel()
        self.label_thumb_height = QLabel()
        self.label_prefer_gpu = QLabel()
        self.label_ffmpeg_path = QLabel()
        self.label_model_dir = QLabel()
        self.hint_fps = QLabel()
        self.hint_top_k = QLabel()
        self.hint_preview_seconds = QLabel()
        self.hint_preview_width = QLabel()
        self.hint_preview_height = QLabel()
        self.hint_thumb_width = QLabel()
        self.hint_thumb_height = QLabel()
        self.hint_prefer_gpu = QLabel()
        self.hint_ffmpeg_path = QLabel()
        self.hint_ffmpeg_active = QLabel()
        self.hint_inference_backend = QLabel()
        self.hint_gpu_runtime = QLabel()
        self.hint_model_dir = QLabel()

        self._configure_setting_input(self.input_fps, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_top_k, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_preview_seconds, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_preview_width, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_preview_height, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_thumb_width, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_thumb_height, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_prefer_gpu, width=COMPONENT_SIZES["settings_input_width"] + 36)
        self._configure_setting_input(self.input_ffmpeg_path, width=COMPONENT_SIZES["settings_path_input_width"])
        self._configure_setting_input(self.input_model_dir, width=COMPONENT_SIZES["settings_path_input_width"])

        self.form.addRow(self.label_fps, self._build_setting_row(self.input_fps, self.hint_fps))
        self.form.addRow(self.label_top_k, self._build_setting_row(self.input_top_k, self.hint_top_k))
        self.form.addRow(
            self.label_preview_seconds,
            self._build_setting_row(self.input_preview_seconds, self.hint_preview_seconds),
        )
        self.form.addRow(
            self.label_preview_width,
            self._build_setting_row(self.input_preview_width, self.hint_preview_width),
        )
        self.form.addRow(
            self.label_preview_height,
            self._build_setting_row(self.input_preview_height, self.hint_preview_height),
        )
        self.form.addRow(
            self.label_thumb_width,
            self._build_setting_row(self.input_thumb_width, self.hint_thumb_width),
        )
        self.form.addRow(
            self.label_thumb_height,
            self._build_setting_row(self.input_thumb_height, self.hint_thumb_height),
        )
        self.form.addRow(
            self.label_prefer_gpu,
            self._build_setting_row(
                self.input_prefer_gpu,
                self.hint_prefer_gpu,
                self.hint_inference_backend,
                self.hint_gpu_runtime,
            ),
        )
        self.form.addRow(
            self.label_ffmpeg_path,
            self._build_setting_row(
                self.input_ffmpeg_path,
                self.hint_ffmpeg_path,
                self.hint_ffmpeg_active,
            ),
        )
        self.form.addRow(
            self.label_model_dir,
            self._build_setting_row(self.input_model_dir, self.hint_model_dir),
        )
        form_layout.addLayout(self.form)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.btn_save = QPushButton()
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_reset = QPushButton()
        self.btn_reset.setObjectName("GhostButton")
        action_row.addWidget(self.btn_save)
        action_row.addWidget(self.btn_reset)
        action_row.addStretch()
        form_layout.addLayout(action_row)

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusLabel")
        self.lbl_status.setWordWrap(True)
        form_layout.addWidget(self.lbl_status)
        root.addWidget(self.form_card)
        root.addStretch()

    def _configure_setting_input(self, widget, width):
        widget.setFixedWidth(width)
        widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def _build_setting_row(self, field, hint_label, extra_hint_label=None, extra_hint_label_2=None, extra_hint_label_3=None):
        hint_label.setObjectName("CardHint")
        hint_label.setWordWrap(True)
        for extra_hint in [extra_hint_label, extra_hint_label_2, extra_hint_label_3]:
            if extra_hint is not None:
                if extra_hint in (self.hint_inference_backend, self.hint_gpu_runtime):
                    extra_hint.setObjectName("StatusHint")
                else:
                    extra_hint.setObjectName("CardHint")
                extra_hint.setWordWrap(True)
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        top.addWidget(field, 0)
        top.addWidget(hint_label, 1)
        layout.addLayout(top)
        for extra_hint in [extra_hint_label, extra_hint_label_2, extra_hint_label_3]:
            if extra_hint is not None:
                layout.addWidget(extra_hint)
        return row

    def configure_form_labels(self, texts):
        self.label_fps.setText(texts["setting_fps"])
        self.label_top_k.setText(texts["setting_top_k"])
        self.label_preview_seconds.setText(texts["setting_preview_seconds"])
        self.label_preview_width.setText(texts["setting_preview_width"])
        self.label_preview_height.setText(texts["setting_preview_height"])
        self.label_thumb_width.setText(texts["setting_thumb_width"])
        self.label_thumb_height.setText(texts["setting_thumb_height"])
        self.label_prefer_gpu.setText(texts["setting_prefer_gpu"])
        self.input_prefer_gpu.blockSignals(True)
        self.input_prefer_gpu.clear()
        self.input_prefer_gpu.addItem(texts["setting_prefer_gpu_option_gpu"], True)
        self.input_prefer_gpu.addItem(texts["setting_prefer_gpu_option_cpu"], False)
        self.input_prefer_gpu.blockSignals(False)
        self.label_ffmpeg_path.setText(texts["setting_ffmpeg_path"])
        self.label_model_dir.setText(texts["setting_model_dir"])
        self.hint_fps.setText(texts["setting_fps_hint"])
        self.hint_top_k.setText(texts["setting_top_k_hint"])
        self.hint_preview_seconds.setText(texts["setting_preview_seconds_hint"])
        self.hint_preview_width.setText(texts["setting_preview_width_hint"])
        self.hint_preview_height.setText(texts["setting_preview_height_hint"])
        self.hint_thumb_width.setText(texts["setting_thumb_width_hint"])
        self.hint_thumb_height.setText(texts["setting_thumb_height_hint"])
        self.hint_prefer_gpu.setText(texts["setting_prefer_gpu_hint"])
        self.hint_ffmpeg_path.setText(texts["setting_ffmpeg_path_hint"])
        self.hint_ffmpeg_active.setText(texts["setting_ffmpeg_active"].format(path=texts["setting_ffmpeg_unknown"]))
        self.hint_inference_backend.setText(
            texts["setting_inference_backend"].format(backend=texts["setting_inference_uninitialized"])
        )
        self.hint_inference_backend.setProperty("state", "neutral")
        self.hint_gpu_runtime.setText(texts["setting_gpu_runtime_link_only"])
        self.hint_gpu_runtime.setOpenExternalLinks(True)
        self.hint_gpu_runtime.setTextFormat(Qt.RichText)
        self.hint_gpu_runtime.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.hint_gpu_runtime.setVisible(False)
        self.hint_model_dir.setText(texts["setting_model_dir_hint"])


class ResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setObjectName("ResultTable")
        self.setHorizontalHeaderLabels(["#", "Preview", "Video", "Time", "Score", "Actions"])
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(88)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(0, 46)
        self.setColumnWidth(1, 164)
        self.setColumnWidth(3, 74)
        self.setColumnWidth(4, 74)
        self.setColumnWidth(5, 156)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
