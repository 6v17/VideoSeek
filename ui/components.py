from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
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
        self.btn_page_link = self._build_nav_button("Link Match")
        self.btn_page_library = self._build_nav_button("Libraries")
        self.btn_page_settings = self._build_nav_button("Settings")
        layout.addWidget(self.btn_page_search)
        layout.addWidget(self.btn_page_link)
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
            "link": self.btn_page_link,
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
        self.search_mode = QComboBox()
        self.search_mode.setObjectName("SearchModeSelect")
        self.search_mode.setFixedWidth(COMPONENT_SIZES["settings_input_width"] + 36)
        self.search_mode_label = QLabel()
        self.search_mode_label.setObjectName("CardHint")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_row.addWidget(self.search_mode_label)
        mode_row.addWidget(self.search_mode)
        mode_row.addStretch()

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
        query_layout.addLayout(mode_row)
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
        self.btn_vector_details = QPushButton()
        self.btn_vector_details.setObjectName("GhostButton")
        toolbar.addWidget(self.btn_add_lib)
        toolbar.addWidget(self.btn_sync_db)
        toolbar.addWidget(self.btn_vector_details)
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



class LinkSearchPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.header = PageHeader()
        root.addWidget(self.header)

        self.control_card = QFrame()
        self.control_card.setObjectName("PanelCard")
        control_layout = QVBoxLayout(self.control_card)
        control_layout.setContentsMargins(18, 18, 18, 18)
        control_layout.setSpacing(12)

        self.input_link = QLineEdit()
        self.input_link.setObjectName("SearchInput")
        self.btn_browse = QPushButton()
        self.btn_browse.setObjectName("SecondaryButton")
        self.query_image_label = QLabel()
        self.query_image_label.setObjectName("ImageDropZone")
        self.query_image_label.setAlignment(Qt.AlignCenter)
        self.query_image_label.setWordWrap(True)
        self.query_image_label.setMinimumHeight(140)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.mode_label = QLabel()
        self.mode_label.setObjectName("CardHint")
        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("SearchModeSelect")
        self.mode_combo.setFixedWidth(COMPONENT_SIZES["settings_input_width"] + 72)
        self.build_links_input = QTextEdit()
        self.build_links_input.setObjectName("SearchInput")
        self.build_links_input.setMinimumHeight(140)
        mode_row.addWidget(self.mode_label)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch()

        self.btn_build = QPushButton()
        self.btn_build.setObjectName("PrimaryButton")
        self.btn_build.setMinimumWidth(126)
        self.btn_run = QPushButton()
        self.btn_run.setObjectName("SearchButton")
        self.btn_run.setMinimumWidth(156)
        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("DangerGhostButton")
        self.btn_clear.setMinimumWidth(98)
        self.btn_import = QPushButton()
        self.btn_import.setObjectName("SecondaryButton")
        self.btn_import.setMinimumWidth(126)
        self.btn_export = QPushButton()
        self.btn_export.setObjectName("SecondaryButton")
        self.btn_export.setMinimumWidth(126)
        self.btn_link_details = QPushButton()
        self.btn_link_details.setObjectName("GhostButton")
        self.btn_link_details.setMinimumWidth(126)
        self.btn_open_cache = QPushButton()
        self.btn_open_cache.setObjectName("GhostButton")
        self.btn_open_cache.setMinimumWidth(126)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(COMPONENT_SIZES["progress_bar_height"])
        self.progress_bar.setVisible(False)

        self.build_title = QLabel()
        self.build_title.setObjectName("CardTitle")
        self.build_hint = QLabel()
        self.build_hint.setObjectName("CardHint")
        self.build_hint.setWordWrap(True)
        self.search_title = QLabel()
        self.search_title.setObjectName("CardTitle")
        self.search_hint = QLabel()
        self.search_hint.setObjectName("CardHint")
        self.search_hint.setWordWrap(True)
        self.lbl_build_status = QLabel()
        self.lbl_build_status.setObjectName("StatusLabel")
        self.lbl_build_status.setWordWrap(True)
        self.lbl_search_status = QLabel()
        self.lbl_search_status.setObjectName("StatusLabel")
        self.lbl_search_status.setWordWrap(True)

        build_utility_row = QGridLayout()
        build_utility_row.setHorizontalSpacing(8)
        build_utility_row.setVerticalSpacing(8)
        build_utility_row.addWidget(self.btn_build, 0, 0)
        build_utility_row.addWidget(self.btn_import, 0, 1)
        build_utility_row.addWidget(self.btn_export, 0, 2)
        build_utility_row.addWidget(self.btn_link_details, 1, 0)
        build_utility_row.addWidget(self.btn_open_cache, 1, 1)
        build_utility_row.setColumnStretch(0, 1)
        build_utility_row.setColumnStretch(1, 1)
        build_utility_row.setColumnStretch(2, 1)

        build_status_row = QHBoxLayout()
        build_status_row.setSpacing(12)
        build_status_row.addWidget(self.progress_bar, 2)
        build_status_row.addWidget(self.lbl_build_status, 3)

        build_panel = QWidget()
        build_layout = QVBoxLayout(build_panel)
        build_layout.setContentsMargins(0, 0, 0, 0)
        build_layout.setSpacing(10)
        build_layout.addWidget(self.build_title)
        build_layout.addWidget(self.build_hint)
        build_layout.addWidget(self.build_links_input)
        build_layout.addLayout(mode_row)
        build_layout.addLayout(build_utility_row)
        build_layout.addLayout(build_status_row)

        search_action_row = QHBoxLayout()
        search_action_row.setSpacing(8)
        search_action_row.addWidget(self.btn_run, 1)
        search_action_row.addWidget(self.btn_clear)

        search_panel = QWidget()
        search_layout = QVBoxLayout(search_panel)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(10)
        search_layout.addWidget(self.search_title)
        search_layout.addWidget(self.search_hint)
        search_layout.addWidget(self.input_link)
        search_layout.addWidget(self.btn_browse)
        search_layout.addWidget(self.query_image_label)
        search_layout.addLayout(search_action_row)
        search_layout.addWidget(self.lbl_search_status)

        section_row = QHBoxLayout()
        section_row.setSpacing(16)
        section_row.addWidget(build_panel, 1)
        section_row.addWidget(search_panel, 1)

        control_layout.addLayout(section_row)
        self.controls_title = self.build_title
        self.controls_hint = self.build_hint
        self.lbl_status = self.lbl_search_status
        root.addWidget(self.control_card)

        self.results_card = QFrame()
        self.results_card.setObjectName("PanelCard")
        results_layout = QVBoxLayout(self.results_card)
        results_layout.setContentsMargins(18, 18, 18, 18)
        results_layout.setSpacing(10)
        self.results_title = QLabel()
        self.results_title.setObjectName("CardTitle")
        self.result_table = LinkResultTable()
        self.result_table.setMinimumHeight(COMPONENT_SIZES["result_table_min_height"])
        results_layout.addWidget(self.results_title)
        results_layout.addWidget(self.result_table)
        root.addWidget(self.results_card, 1)


class LinkResultTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setObjectName("ResultTable")
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(72)
        self.setAlternatingRowColors(False)
        self.setFocusPolicy(Qt.NoFocus)
        self.setShowGrid(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.setColumnWidth(0, 46)
        self.setColumnWidth(2, 90)
        self.setColumnWidth(3, 74)
        self.setColumnWidth(4, 300)
        self.setColumnWidth(5, 116)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)


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
        self.input_remote_max_frames = QSpinBox()
        self.input_remote_max_frames.setRange(200, 20000)
        self.input_similarity_threshold = QDoubleSpinBox()
        self.input_similarity_threshold.setRange(0.1, 1.0)
        self.input_similarity_threshold.setSingleStep(0.01)
        self.input_similarity_threshold.setDecimals(2)
        self.input_max_chunk_duration = QDoubleSpinBox()
        self.input_max_chunk_duration.setRange(1.0, 60.0)
        self.input_max_chunk_duration.setSingleStep(0.5)
        self.input_max_chunk_duration.setDecimals(1)
        self.input_min_chunk_size = QSpinBox()
        self.input_min_chunk_size.setRange(1, 50)
        self.input_chunk_similarity_mode = QComboBox()
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
        self.label_remote_max_frames = QLabel()
        self.label_similarity_threshold = QLabel()
        self.label_max_chunk_duration = QLabel()
        self.label_min_chunk_size = QLabel()
        self.label_chunk_similarity_mode = QLabel()
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
        self.hint_remote_max_frames = QLabel()
        self.hint_similarity_threshold = QLabel()
        self.hint_max_chunk_duration = QLabel()
        self.hint_min_chunk_size = QLabel()
        self.hint_chunk_similarity_mode = QLabel()
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
        self._configure_setting_input(self.input_remote_max_frames, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_similarity_threshold, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_max_chunk_duration, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_min_chunk_size, width=COMPONENT_SIZES["settings_input_width"])
        self._configure_setting_input(self.input_chunk_similarity_mode, width=COMPONENT_SIZES["settings_input_width"] + 36)
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
            self.label_remote_max_frames,
            self._build_setting_row(self.input_remote_max_frames, self.hint_remote_max_frames),
        )
        self.form.addRow(
            self.label_similarity_threshold,
            self._build_setting_row(self.input_similarity_threshold, self.hint_similarity_threshold),
        )
        self.form.addRow(
            self.label_max_chunk_duration,
            self._build_setting_row(self.input_max_chunk_duration, self.hint_max_chunk_duration),
        )
        self.form.addRow(
            self.label_min_chunk_size,
            self._build_setting_row(self.input_min_chunk_size, self.hint_min_chunk_size),
        )
        self.form.addRow(
            self.label_chunk_similarity_mode,
            self._build_setting_row(self.input_chunk_similarity_mode, self.hint_chunk_similarity_mode),
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
        self.label_remote_max_frames.setText(texts["setting_remote_max_frames"])
        self.label_similarity_threshold.setText(texts["setting_similarity_threshold"])
        self.label_max_chunk_duration.setText(texts["setting_max_chunk_duration"])
        self.label_min_chunk_size.setText(texts["setting_min_chunk_size"])
        self.label_chunk_similarity_mode.setText(texts["setting_chunk_similarity_mode"])
        self.label_prefer_gpu.setText(texts["setting_prefer_gpu"])
        self.input_chunk_similarity_mode.blockSignals(True)
        self.input_chunk_similarity_mode.clear()
        self.input_chunk_similarity_mode.addItem(texts["setting_chunk_similarity_mode_chunk"], "chunk")
        self.input_chunk_similarity_mode.addItem(texts["setting_chunk_similarity_mode_frame"], "frame")
        self.input_chunk_similarity_mode.blockSignals(False)
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
        self.hint_remote_max_frames.setText(texts["setting_remote_max_frames_hint"])
        self.hint_similarity_threshold.setText(texts["setting_similarity_threshold_hint"])
        self.hint_max_chunk_duration.setText(texts["setting_max_chunk_duration_hint"])
        self.hint_min_chunk_size.setText(texts["setting_min_chunk_size_hint"])
        self.hint_chunk_similarity_mode.setText(texts["setting_chunk_similarity_mode_hint"])
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
        super().__init__(0, 7, parent)
        self.setObjectName("ResultTable")
        self.setHorizontalHeaderLabels(["#", "Preview", "Video", "Range", "Mode", "Score", "Actions"])
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
        self.setColumnWidth(3, 108)
        self.setColumnWidth(4, 74)
        self.setColumnWidth(5, 74)
        self.setColumnWidth(6, 156)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(4, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(5, QHeaderView.Fixed)
        self.horizontalHeader().setSectionResizeMode(6, QHeaderView.Fixed)
