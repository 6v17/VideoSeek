"""Pager controls for local search result tables."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget

from src.app.search_results_paging import SEARCH_RESULTS_PAGE_SIZE, search_results_page_count

_PAGER_ROW_HEIGHT = 24


class SearchResultsPager(QWidget):
    page_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SearchResultsPager")
        self._texts: dict = {}
        self._page_size = SEARCH_RESULTS_PAGE_SIZE
        self._total_count = 0
        self._current_page = 0
        self.setFixedHeight(_PAGER_ROW_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        button_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.btn_prev = QPushButton()
        self.btn_prev.setObjectName("SearchResultsPagerButton")
        self.btn_prev.setFixedSize(64, _PAGER_ROW_HEIGHT)
        self.btn_prev.setSizePolicy(button_policy)
        self.btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)

        self.lbl_page = QLabel()
        self.lbl_page.setObjectName("SearchResultsPagerInfo")
        self.lbl_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_page.setFixedHeight(_PAGER_ROW_HEIGHT)
        self.lbl_page.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        self.btn_next = QPushButton()
        self.btn_next.setObjectName("SearchResultsPagerButton")
        self.btn_next.setFixedSize(64, _PAGER_ROW_HEIGHT)
        self.btn_next.setSizePolicy(button_policy)
        self.btn_next.setCursor(Qt.CursorShape.PointingHandCursor)

        layout.addWidget(self.btn_prev, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.lbl_page, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.btn_next, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_prev.clicked.connect(self._go_prev)
        self.btn_next.clicked.connect(self._go_next)
        self.setVisible(False)
        self._sync_controls()

    def set_texts(self, texts: dict) -> None:
        self._texts = dict(texts or {})
        self.btn_prev.setText(self._texts.get("search_results_prev_page", "Previous"))
        self.btn_next.setText(self._texts.get("search_results_next_page", "Next"))
        self._sync_controls()

    def configure(
        self,
        *,
        total_count: int,
        current_page: int = 0,
        page_size: int = SEARCH_RESULTS_PAGE_SIZE,
    ) -> None:
        self._page_size = max(1, int(page_size))
        self._total_count = max(0, int(total_count))
        pages = search_results_page_count(self._total_count, self._page_size)
        if pages <= 0:
            self._current_page = 0
        else:
            self._current_page = max(0, min(int(current_page), pages - 1))
        self.setVisible(self._total_count > 0)
        self._sync_controls()

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def page_size(self) -> int:
        return self._page_size

    @property
    def total_count(self) -> int:
        return self._total_count

    def _go_prev(self) -> None:
        if self._current_page <= 0:
            return
        self.page_changed.emit(self._current_page - 1)

    def _go_next(self) -> None:
        pages = search_results_page_count(self._total_count, self._page_size)
        if self._current_page >= pages - 1:
            return
        self.page_changed.emit(self._current_page + 1)

    def _sync_controls(self) -> None:
        pages = search_results_page_count(self._total_count, self._page_size)
        page_number = self._current_page + 1 if pages > 0 else 0
        template = self._texts.get(
            "search_results_page_info",
            "{page}/{pages} · {total}",
        )
        self.lbl_page.setText(
            template.format(
                page=page_number,
                pages=pages,
                total=self._total_count,
            )
        )
        self.btn_prev.setEnabled(self._current_page > 0)
        self.btn_next.setEnabled(pages > 0 and self._current_page < pages - 1)
