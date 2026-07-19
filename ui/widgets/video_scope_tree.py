"""Video search scope: per-library cards with lazy, virtualized checkable lists.

Designed for large libraries (10k+ ready videos): headers stay cheap; rows use
QTableView + model so only visible items are realized. Bodies populate on expand.
Selection keys are normalized absolute paths (search-scope contract).
"""
from __future__ import annotations

import os
from collections import defaultdict
from typing import Any, Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from src.services.search_scope import normalize_scope_path

_LIST_VIEW_HEIGHT = 280


class _ClickLabel(QLabel):
    """Label that emits clicked on left-button release (expand/collapse library card)."""

    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ScopeVideoTableModel(QAbstractTableModel):
    """Virtualized ready-video rows; check state keyed by normalized abs path."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._checked: set[str] = set()
        self._video_icon = QIcon()

    def set_video_icon(self, icon: QIcon) -> None:
        self._video_icon = icon

    @staticmethod
    def _row_abs_path(ent: dict[str, Any]) -> str:
        raw = str(ent.get("abs_path") or ent.get("video_path") or "").strip()
        return normalize_scope_path(raw) if raw else ""

    def set_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        checked_paths: set[str] | None = None,
        default_on: bool = False,
        preserve_checked: bool = True,
    ) -> None:
        previous = set(self._checked) if preserve_checked else set()
        self.beginResetModel()
        self._rows = list(rows or [])
        valid = {self._row_abs_path(r) for r in self._rows}
        valid.discard("")
        if checked_paths is not None:
            self._checked = {p for p in checked_paths if p and p in valid}
        elif default_on:
            self._checked = set(valid)
        else:
            self._checked = {p for p in previous if p in valid}
        self.endResetModel()

    def clear_rows(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 1

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsUserCheckable
        )

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.column() != 0:
            return None
        row = index.row()
        if row < 0 or row >= len(self._rows):
            return None
        ent = self._rows[row]
        abs_path = self._row_abs_path(ent)
        rel = str(ent.get("video_rel_path") or "").strip().replace("\\", "/")
        name = os.path.basename(rel) if rel else os.path.basename(abs_path)
        if role == Qt.ItemDataRole.DisplayRole:
            return name or abs_path or "?"
        if role == Qt.ItemDataRole.ToolTipRole:
            tip_rel = rel or name
            return f"{tip_rel}\n{abs_path}" if abs_path else tip_rel
        if role == Qt.ItemDataRole.DecorationRole:
            return self._video_icon
        if role == Qt.ItemDataRole.CheckStateRole:
            return Qt.CheckState.Checked if abs_path in self._checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.UserRole:
            return abs_path
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        abs_path = self._row_abs_path(self._rows[index.row()])
        if not abs_path:
            return False
        if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
            self._checked.add(abs_path)
        else:
            self._checked.discard(abs_path)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def checked_paths(self) -> list[str]:
        order: list[str] = []
        seen: set[str] = set()
        for ent in self._rows:
            p = self._row_abs_path(ent)
            if p and p in self._checked and p not in seen:
                order.append(p)
                seen.add(p)
        return order

    def set_all_checked(self, checked: bool) -> None:
        self.beginResetModel()
        if checked:
            self._checked = {self._row_abs_path(r) for r in self._rows if self._row_abs_path(r)}
        else:
            self._checked.clear()
        self.endResetModel()

    def check_stats(self) -> tuple[int, int]:
        tot = sum(1 for r in self._rows if self._row_abs_path(r))
        n = sum(1 for r in self._rows if self._row_abs_path(r) in self._checked)
        return n, tot


class _LibBlock:
    __slots__ = (
        "lib_path",
        "lib_cb",
        "model",
        "view",
        "body",
        "collapse",
        "entries",
        "populated",
        "expanded",
        "default_on",
        "wanted_paths",
    )

    def __init__(self) -> None:
        self.lib_path = ""
        self.lib_cb: QCheckBox | None = None
        self.model: ScopeVideoTableModel | None = None
        self.view: QTableView | None = None
        self.body: QWidget | None = None
        self.collapse: QToolButton | None = None
        self.entries: list[dict] = []
        self.populated = False
        self.expanded = False
        self.default_on = False
        self.wanted_paths: set[str] = set()


class VideoScopeTreeWidget(QWidget):
    """Card list of libraries; each card contains a virtualized ready-video checklist."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("VideoScopeTree")
        self._silent = False
        self._blocks: list[_LibBlock] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("VideoScopeScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_host = QWidget()
        self._list_host.setObjectName("VideoScopeList")
        self._vbox = QVBoxLayout(self._list_host)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(0)

        self._scroll.setWidget(self._list_host)
        root.addWidget(self._scroll, 1)

    def total_video_items(self) -> int:
        return sum(len(b.entries) for b in self._blocks)

    def collect_expanded_library_paths(self) -> list[str]:
        """Normalized library root paths whose card body is currently visible."""
        return [os.path.normpath(b.lib_path) for b in self._blocks if b.expanded]

    def set_header_labels(self, _name_col: str, _unused_second: str | None = None) -> None:
        """Kept for API compatibility with MainWindow.apply_texts."""

    def reflow_all_lib_trees(self) -> None:
        """No-op for virtualized tables; kept for search-scope editor polish hooks."""

    @staticmethod
    def _entry_abs_path(ent: dict) -> str:
        lib = str(ent.get("library_path", "") or "").strip()
        rel = str(ent.get("video_rel_path", "") or "").strip().replace("\\", "/")
        explicit = str(ent.get("video_path") or ent.get("abs_path") or "").strip()
        if explicit:
            return normalize_scope_path(explicit)
        if lib and rel:
            return normalize_scope_path(os.path.join(os.path.normpath(lib), rel.replace("/", os.sep)))
        return ""

    def _prepare_entry(self, ent: dict) -> dict:
        row = dict(ent)
        abs_path = self._entry_abs_path(row)
        row["abs_path"] = abs_path
        return row

    def refresh_from_entries(
        self,
        entries: Iterable[dict],
        *,
        default_checked: bool = False,
        checked_abs_paths: Iterable[str] | None = None,
        expanded_lib_paths: Iterable[str] | None = None,
    ) -> None:
        prev_expanded = set(self.collect_expanded_library_paths())
        self._clear_cards()
        ready: list[dict] = []
        for ent in entries:
            if not ent.get("source_exists"):
                continue
            if str(ent.get("asset_state", "")).strip().lower() != "ready":
                continue
            prepared = self._prepare_entry(ent)
            if not prepared.get("abs_path"):
                continue
            ready.append(prepared)

        by_lib: dict[str, list[dict]] = defaultdict(list)
        for ent in ready:
            lib_path = str(ent.get("library_path", "") or "").strip()
            if not lib_path:
                continue
            by_lib[lib_path].append(ent)

        if expanded_lib_paths is not None:
            exp_norm = {os.path.normpath(p) for p in expanded_lib_paths if str(p).strip()}
        else:
            exp_norm = prev_expanded

        if checked_abs_paths is not None:
            wanted_global = {normalize_scope_path(p) for p in checked_abs_paths if str(p).strip()}
            default_on = False
        else:
            wanted_global = set()
            default_on = default_checked

        sorted_libs = sorted(by_lib.keys(), key=lambda p: p.lower())
        for row_index, lib_path in enumerate(sorted_libs):
            vids = sorted(
                by_lib[lib_path],
                key=lambda e: str(e.get("video_rel_path", "")).lower(),
            )
            lib_key = os.path.normpath(lib_path)
            lib_wanted = {
                str(e.get("abs_path") or "")
                for e in vids
                if str(e.get("abs_path") or "") in wanted_global
            }
            # Default collapsed; only restore paths the user already expanded.
            body_exp = bool(exp_norm) and lib_key in exp_norm
            block, card = self._build_library_card(
                lib_path,
                vids,
                default_on=default_on,
                wanted_paths=lib_wanted,
                body_expanded=body_exp,
                row_index=row_index,
            )
            self._blocks.append(block)
            self._vbox.addWidget(card)

        self._vbox.addStretch(1)

    def _clear_cards(self) -> None:
        self._blocks.clear()
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def apply_checked_paths(self, wanted_abs_paths: Iterable[str]) -> None:
        """Update checks from absolute paths without rebuilding the scope UI."""
        wanted_norm = {normalize_scope_path(str(p)) for p in wanted_abs_paths if str(p).strip()}
        self._apply_abs_path_checks(wanted_norm)

    def _apply_abs_path_checks(self, wanted_norm: set[str]) -> None:
        self._silent = True
        try:
            for block in self._blocks:
                block.wanted_paths = {
                    str(e.get("abs_path") or "")
                    for e in block.entries
                    if str(e.get("abs_path") or "") in wanted_norm
                }
                block.default_on = False
                if block.populated and block.model is not None:
                    block.model.set_rows(
                        block.entries,
                        checked_paths=block.wanted_paths,
                        default_on=False,
                        preserve_checked=False,
                    )
                self._sync_lib_checkbox(block)
        finally:
            self._silent = False

    @staticmethod
    def _video_icon(view: QWidget) -> QIcon:
        st = view.style()
        generic = st.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        return QIcon.fromTheme("video-x-generic", QIcon.fromTheme("video-mp4", generic))

    def _build_library_card(
        self,
        lib_path: str,
        vids: list[dict],
        *,
        default_on: bool,
        wanted_paths: set[str],
        body_expanded: bool,
        row_index: int = 0,
    ) -> tuple[_LibBlock, QFrame]:
        block = _LibBlock()
        block.lib_path = lib_path
        block.entries = vids
        block.default_on = default_on
        block.wanted_paths = set(wanted_paths)
        block.expanded = bool(body_expanded)

        card = QFrame()
        card.setObjectName("VideoScopeLibCard")
        card.setProperty("rowStripe", "odd" if row_index % 2 else "even")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("VideoScopeLibHeader")
        top = QHBoxLayout(header)
        top.setContentsMargins(10, 0, 10, 0)
        top.setSpacing(8)

        lib_cb = QCheckBox()
        lib_cb.setObjectName("VideoScopeLibCheck")
        lib_cb.setTristate(True)
        lib_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        block.lib_cb = lib_cb

        title = _ClickLabel(os.path.basename(os.path.normpath(lib_path)) or lib_path)
        lib_cb.setAccessibleName(title.text())
        title.setObjectName("VideoScopeLibTitle")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setToolTip(lib_path)
        title.setCursor(Qt.CursorShape.PointingHandCursor)

        collapse = QToolButton()
        collapse.setObjectName("VideoScopeCollapseBtn")
        collapse.setAutoRaise(True)
        collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse.setArrowType(Qt.ArrowType.DownArrow if body_expanded else Qt.ArrowType.RightArrow)
        collapse.setFixedSize(24, 24)
        block.collapse = collapse

        body = QWidget()
        body.setObjectName("VideoScopeLibBody")
        block.body = body
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)

        model = ScopeVideoTableModel(body)
        model.set_video_icon(self._video_icon(body))
        block.model = model

        view = QTableView(body)
        view.setObjectName("VideoScopeLibTree")
        view.setModel(model)
        view.setShowGrid(False)
        view.setFrameShape(QFrame.Shape.NoFrame)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        view.setAlternatingRowColors(True)
        view.verticalHeader().setVisible(False)
        view.horizontalHeader().setVisible(False)
        view.verticalHeader().setDefaultSectionSize(30)
        view.setIconSize(QSize(16, 16))
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.setFixedHeight(_LIST_VIEW_HEIGHT)
        view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        hh = view.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        block.view = view
        body_l.addWidget(view)

        model.dataChanged.connect(lambda *_args, b=block: self._on_model_checks_changed(b))

        def set_expanded(on: bool) -> None:
            block.expanded = bool(on)
            body.setVisible(block.expanded)
            card.setProperty("expanded", "true" if block.expanded else "false")
            for widget in (card, header):
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
            collapse.setArrowType(
                Qt.ArrowType.DownArrow if block.expanded else Qt.ArrowType.RightArrow
            )
            if block.expanded:
                self._ensure_populated(block)

        collapse.clicked.connect(lambda: set_expanded(not block.expanded))
        title.clicked.connect(lambda: set_expanded(not block.expanded))

        top.addWidget(collapse, 0)
        top.addWidget(lib_cb, 0)
        top.addWidget(title, 1)
        outer.addWidget(header)
        outer.addWidget(body)
        body.setVisible(block.expanded)
        card.setProperty("expanded", "true" if block.expanded else "false")

        lib_cb.stateChanged.connect(lambda st, blk=block: self._on_library_state_changed(blk, st))

        if block.expanded:
            self._ensure_populated(block)
        else:
            self._sync_lib_checkbox(block)

        return block, card

    def _ensure_populated(self, block: _LibBlock) -> None:
        if block.populated or block.model is None:
            return
        block.model.set_rows(
            block.entries,
            checked_paths=block.wanted_paths or None,
            default_on=block.default_on and not block.wanted_paths,
            preserve_checked=False,
        )
        block.populated = True
        self._sync_lib_checkbox(block)

    def _on_model_checks_changed(self, block: _LibBlock) -> None:
        if self._silent:
            return
        if block.model is not None:
            block.wanted_paths = set(block.model.checked_paths())
            block.default_on = False
        self._sync_lib_checkbox(block)

    def _block_checked_paths(self, block: _LibBlock) -> list[str]:
        if block.populated and block.model is not None:
            return block.model.checked_paths()
        if block.default_on and not block.wanted_paths:
            return [str(e.get("abs_path") or "") for e in block.entries if e.get("abs_path")]
        return [p for p in block.wanted_paths if p]

    def _on_library_state_changed(self, block: _LibBlock, state: int) -> None:
        if self._silent:
            return
        cs = Qt.CheckState(state)
        checked = cs != Qt.CheckState.Unchecked
        if cs == Qt.CheckState.PartiallyChecked:
            checked = True
            self._silent = True
            try:
                block.lib_cb.blockSignals(True)
                block.lib_cb.setCheckState(Qt.CheckState.Checked)
                block.lib_cb.blockSignals(False)
            finally:
                self._silent = False

        if not block.populated:
            if checked:
                block.wanted_paths = {
                    str(e.get("abs_path") or "")
                    for e in block.entries
                    if e.get("abs_path")
                }
                block.default_on = True
            else:
                block.wanted_paths.clear()
                block.default_on = False
            self._sync_lib_checkbox(block)
            return

        if block.model is not None:
            block.model.set_all_checked(checked)
            block.wanted_paths = set(block.model.checked_paths())
            block.default_on = False
        self._sync_lib_checkbox(block)

    def _sync_lib_checkbox(self, block: _LibBlock) -> None:
        tot = sum(1 for e in block.entries if e.get("abs_path"))
        if block.populated and block.model is not None:
            n, tot = block.model.check_stats()
            block.wanted_paths = set(block.model.checked_paths())
        elif block.default_on and not block.wanted_paths:
            n = tot
        else:
            n = len(block.wanted_paths)
        prev_silent = self._silent
        self._silent = True
        try:
            block.lib_cb.blockSignals(True)
            if tot == 0 or n == 0:
                block.lib_cb.setCheckState(Qt.CheckState.Unchecked)
            elif n >= tot:
                block.lib_cb.setCheckState(Qt.CheckState.Checked)
            else:
                block.lib_cb.setCheckState(Qt.CheckState.PartiallyChecked)
            block.lib_cb.blockSignals(False)
        finally:
            self._silent = prev_silent

    def select_all_videos(self) -> None:
        self._silent = True
        try:
            for block in self._blocks:
                block.default_on = True
                block.wanted_paths = {
                    str(e.get("abs_path") or "")
                    for e in block.entries
                    if e.get("abs_path")
                }
                if block.populated and block.model is not None:
                    block.model.set_all_checked(True)
                self._sync_lib_checkbox(block)
        finally:
            self._silent = False

    def select_no_videos(self) -> None:
        self._silent = True
        try:
            for block in self._blocks:
                block.default_on = False
                block.wanted_paths.clear()
                if block.populated and block.model is not None:
                    block.model.set_all_checked(False)
                self._sync_lib_checkbox(block)
        finally:
            self._silent = False

    def collect_checked_video_paths(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for block in self._blocks:
            for p in self._block_checked_paths(block):
                if p and p not in seen:
                    out.append(p)
                    seen.add(p)
        return out

    def scope_selection_counts(self) -> tuple[int, int]:
        """(checked_video_count, libraries_with_at_least_one_checked_video)."""
        n_videos = 0
        n_libs = 0
        for block in self._blocks:
            c = len(self._block_checked_paths(block))
            if c:
                n_libs += 1
                n_videos += c
        return n_videos, n_libs
