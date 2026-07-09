"""Embedded video preview card for the local search page."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from ui.widgets.layout import COMPONENT_SIZES
from ui.widgets.scaffold import VSCard


class PreviewPanel(VSCard):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = self.content_layout
        baseline = int(COMPONENT_SIZES["search_compare_baseline_height"])
        compare_extra = 22

        preview_header = QHBoxLayout()
        preview_header.setContentsMargins(0, 0, 0, 0)
        preview_header.setSpacing(10)
        self.preview_title = QLabel()
        self.preview_title.setObjectName("CardTitle")
        preview_header.addWidget(self.preview_title, 1)

        self.preview_host = QFrame()
        self.preview_host.setObjectName("VideoContainer")
        self.preview_host.setMinimumHeight(int(COMPONENT_SIZES["preview_host_min_height"]))
        self.preview_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.preview_host_layout = QVBoxLayout(self.preview_host)
        self.preview_host_layout.setContentsMargins(6, 6, 6, 6)
        self.preview_placeholder = QLabel()
        self.preview_placeholder.setObjectName("PreviewPlaceholder")
        self.preview_placeholder.setAlignment(Qt.AlignCenter)
        self.preview_placeholder.setWordWrap(True)
        self.preview_host_layout.addWidget(self.preview_placeholder)

        layout.addLayout(preview_header)
        layout.addWidget(self.preview_host, 1)
        self.setFixedHeight(baseline + compare_extra)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
