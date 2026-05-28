"""Modal library scope picker for local search."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.app_message import AppMessageDialog
from ui.widgets.layout import WINDOW_SIZES, message_dialog_min_width
from ui.widgets.scaffold import VSCard
from ui.widgets.styles import repolish_widget, theme_color_map


class _ScopeLibCheckBox(QCheckBox):
    """Paint a theme-aware box + checkmark; avoids brittle stylesheet data URIs."""

    def __init__(self, is_dark: bool, parent=None):
        super().__init__(parent)
        self._is_dark = bool(is_dark)
        self.setFixedSize(18, 18)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colors = theme_color_map(self._is_dark)
        rect = self.rect().adjusted(0, 0, -1, -1)
        checked = self.isChecked()

        border_color = QColor(colors["ACCENT"] if checked else colors["LINE_STRONG"])
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QColor(colors["PANEL"]))
        painter.drawRoundedRect(rect, 4, 4)

        if checked:
            check_pen = QPen(QColor(colors["ACCENT"]), 2)
            check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(check_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
            painter.drawLine(x + 4, y + h // 2 + 1, x + w // 2 - 1, y + h - 5)
            painter.drawLine(x + w // 2 - 1, y + h - 5, x + w - 4, y + 4)
        painter.end()


class SearchScopeEditorDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        texts: dict,
        options: list[dict],
        mode: str,
        selected_paths: list[str],
        is_dark: bool,
        language: str = "zh",
    ):
        super().__init__(parent)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowTitle(str(texts.get("search_scope_dialog_title", "")))
        self.setMinimumWidth(
            message_dialog_min_width(680, WINDOW_SIZES["message_dialog"]["screen_margin"])
        )
        self.resize(760, 560)
        self._texts = texts
        self._language = str(language or "zh")
        self._is_dark = bool(is_dark)
        self._entries: list[tuple[str, QFrame, QCheckBox]] = []

        self.setObjectName("SearchScopeEditorDialog")
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)

        shell = VSCard(variant="dialog", margins=(22, 20, 22, 18), spacing=14)
        inner = shell.content_layout

        hero = QLabel(str(texts.get("search_scope_dialog_title", "")))
        hero.setObjectName("DialogHeroTitle")
        inner.addWidget(hero)

        hint = QLabel(str(texts.get("search_scope_dialog_hint", "")))
        hint.setObjectName("DialogBodyLabel")
        hint.setWordWrap(True)
        inner.addWidget(hint)

        toolbar = QHBoxLayout()
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
        inner.addLayout(toolbar)

        list_host = QWidget()
        list_host.setObjectName("SearchScopeList")
        self._list_layout = QVBoxLayout(list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(10)

        normalized_mode = "selected" if str(mode or "").strip().lower() == "selected" else "all"
        selected_set = {str(path) for path in (selected_paths or []) if str(path).strip()}

        if not options:
            empty = QLabel(str(texts.get("search_scope_no_libraries", "")))
            empty.setObjectName("DialogBodyLabel")
            empty.setWordWrap(True)
            self._list_layout.addWidget(empty)
        else:
            for index, option in enumerate(options, start=1):
                path = str(option.get("path", "") or "").strip()
                if not path:
                    continue
                display_name = str(option.get("display_name", "") or path)
                ready_count = int(option.get("ready_count", 0) or 0)
                checked = path in selected_set if normalized_mode == "selected" else True
                row, checkbox = self._build_library_row(index, path, display_name, ready_count, checked)
                self._list_layout.addWidget(row)
                self._entries.append((path, row, checkbox))

        self._list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setObjectName("SearchScopeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(list_host)
        inner.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton(str(texts.get("cancel", "Cancel")))
        cancel.setObjectName("GhostButton")
        cancel.clicked.connect(self.reject)
        ok = QPushButton(str(texts.get("confirm_action", "OK")))
        ok.setObjectName("PrimaryButton")
        ok.clicked.connect(self._accept_scope)
        btn_row.addWidget(cancel, 0)
        btn_row.addWidget(ok, 0)
        inner.addLayout(btn_row)
        root.addWidget(shell, 1)

        btn_select_all.setEnabled(bool(self._entries))
        btn_clear_all.setEnabled(bool(self._entries))
        self._refresh_summary()
        repolish_widget(self)

    def _build_library_row(self, index: int, path: str, display_name: str, ready_count: int, checked: bool):
        row = QFrame()
        row.setObjectName("SearchScopeLibRow")
        row.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignVCenter)

        index_label = QLabel(str(index))
        index_label.setObjectName("LibraryCardIndex")
        index_label.setAlignment(Qt.AlignCenter)
        index_label.setFixedSize(36, 36)
        index_label.setMinimumHeight(36)

        checkbox = _ScopeLibCheckBox(self._is_dark)
        checkbox.setChecked(checked)
        checkbox.stateChanged.connect(lambda _state, cb=checkbox: cb.update())
        checkbox.stateChanged.connect(lambda _state, r=row, cb=checkbox: self._sync_row_selected(r, cb))

        text_wrap = QWidget()
        text_col = QVBoxLayout(text_wrap)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(3)
        title = QLabel(display_name)
        title.setObjectName("SearchScopeLibTitle")
        title.setWordWrap(True)
        path_label = QLabel(path)
        path_label.setObjectName("SearchScopeLibPath")
        path_label.setWordWrap(True)
        path_label.setToolTip(path)
        text_col.addWidget(title)
        text_col.addWidget(path_label)

        badge = QLabel(
            self._texts.get("search_scope_ready_badge", "{count}").format(count=ready_count)
        )
        badge.setObjectName("SearchScopeLibBadge")
        badge.setProperty("libState", "ready" if ready_count > 0 else "offline")
        repolish_widget(badge)
        badge.setAlignment(Qt.AlignCenter)
        badge.setMinimumWidth(72)

        layout.addWidget(index_label, 0, Qt.AlignVCenter)
        layout.addWidget(checkbox, 0, Qt.AlignVCenter)
        layout.addWidget(text_wrap, 1, Qt.AlignVCenter)
        layout.addWidget(badge, 0, Qt.AlignVCenter)

        row.mousePressEvent = self._make_row_press_handler(row, checkbox)
        self._sync_row_selected(row, checkbox)
        return row, checkbox

    def _make_row_press_handler(self, row: QFrame, checkbox: QCheckBox):
        def _on_press(event):
            if event.button() != Qt.LeftButton:
                return QFrame.mousePressEvent(row, event)
            if checkbox.isChecked() and self._checked_count() <= 1:
                return QFrame.mousePressEvent(row, event)
            checkbox.setChecked(not checkbox.isChecked())
            event.accept()

        return _on_press

    def _sync_row_selected(self, row: QFrame, checkbox: QCheckBox) -> None:
        row.setProperty("selectedRow", "true" if checkbox.isChecked() else "false")
        repolish_widget(row)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        total = len(self._entries)
        checked = self._checked_count()
        self._summary_label.setText(
            self._texts.get("search_scope_dialog_summary", "{checked}/{total}").format(
                checked=checked,
                total=total,
            )
        )

    def _checked_count(self) -> int:
        return sum(1 for _, _row, checkbox in self._entries if checkbox.isChecked())

    def _select_all(self) -> None:
        for _, _row, checkbox in self._entries:
            checkbox.setChecked(True)

    def _clear_all(self) -> None:
        for _, _row, checkbox in self._entries:
            checkbox.setChecked(False)

    def _accept_scope(self) -> None:
        checked = [path for path, _row, checkbox in self._entries if checkbox.isChecked()]
        if self._entries and not checked:
            AppMessageDialog(
                self._texts.get("warning_title", ""),
                self._texts.get("search_scope_none_selected", ""),
                kind="warning",
                parent=self,
                is_dark=self._is_dark,
                language=self._language,
            ).exec()
            return
        self.accept()

    def result_scope(self) -> tuple[str, list[str]]:
        checked = [path for path, _row, checkbox in self._entries if checkbox.isChecked()]
        if not self._entries or len(checked) == len(self._entries):
            return "all", []
        return "selected", checked
