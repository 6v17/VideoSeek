"""Library page video trees: collapsible per-library cards with virtualized lists.

Designed for large libraries (10k+ videos): library headers are cheap; video rows
use QTableView + model (only visible rows are realized). Bodies populate lazily
on expand.
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
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_LIST_VIEW_HEIGHT = 280


class _ClickLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class LibraryVideoTableModel(QAbstractTableModel):
    """Virtualized video rows: name + status, with check state by video_id."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._checked: set[str] = set()
        self._video_icon = QIcon()

    def set_video_icon(self, icon: QIcon) -> None:
        self._video_icon = icon

    def set_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        checked_ids: set[str] | None = None,
        default_on: bool = False,
        preserve_checked: bool = True,
    ) -> None:
        previous = set(self._checked) if preserve_checked else set()
        self.beginResetModel()
        self._rows = list(rows or [])
        if checked_ids is not None:
            valid = {str(r.get("video_id") or "").strip() for r in self._rows}
            self._checked = {vid for vid in checked_ids if vid and vid in valid}
        elif default_on:
            self._checked = {
                str(r.get("video_id") or "").strip()
                for r in self._rows
                if str(r.get("video_id") or "").strip()
            }
        else:
            valid = {str(r.get("video_id") or "").strip() for r in self._rows}
            self._checked = {vid for vid in previous if vid in valid}
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
        return 2

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._rows):
            return None
        ent = self._rows[row]
        col = index.column()
        video_id = str(ent.get("video_id") or "").strip()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                rel = str(ent.get("video_rel_path") or "").strip().replace("\\", "/")
                name = os.path.basename(rel) if rel else os.path.basename(str(ent.get("video_path") or ""))
                return name or video_id or "?"
            if col == 1:
                return str(ent.get("status_text") or "").strip()
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == 0:
                return str(ent.get("video_path") or "")
            return str(ent.get("status_text") or "").strip()
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            return self._video_icon
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            return Qt.CheckState.Checked if video_id in self._checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.UserRole:
            return dict(ent)
        if role == Qt.ItemDataRole.UserRole + 1:
            return video_id
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole or index.column() != 0:
            return False
        ent = self._rows[index.row()]
        video_id = str(ent.get("video_id") or "").strip()
        if not video_id:
            return False
        if value == Qt.CheckState.Checked or value == Qt.CheckState.Checked.value:
            self._checked.add(video_id)
        else:
            self._checked.discard(video_id)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        return True

    def checked_video_ids(self) -> list[str]:
        order = []
        seen = set()
        for ent in self._rows:
            vid = str(ent.get("video_id") or "").strip()
            if vid and vid in self._checked and vid not in seen:
                order.append(vid)
                seen.add(vid)
        return order

    def checked_entries(self) -> list[dict]:
        wanted = set(self._checked)
        return [dict(ent) for ent in self._rows if str(ent.get("video_id") or "").strip() in wanted]

    def set_all_checked(self, checked: bool) -> None:
        self.beginResetModel()
        if checked:
            self._checked = {
                str(r.get("video_id") or "").strip()
                for r in self._rows
                if str(r.get("video_id") or "").strip()
            }
        else:
            self._checked.clear()
        self.endResetModel()

    def check_stats(self) -> tuple[int, int]:
        tot = sum(1 for r in self._rows if str(r.get("video_id") or "").strip())
        n = sum(1 for r in self._rows if str(r.get("video_id") or "").strip() in self._checked)
        return n, tot

    def update_status_texts(self, by_video_id: dict[str, str]) -> None:
        if not by_video_id or not self._rows:
            return
        first = last = None
        for i, ent in enumerate(self._rows):
            vid = str(ent.get("video_id") or "").strip()
            if not vid or vid not in by_video_id:
                continue
            ent["status_text"] = by_video_id[vid]
            first = i if first is None else first
            last = i
        if first is not None and last is not None:
            self.dataChanged.emit(
                self.index(first, 1),
                self.index(last, 1),
                [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole],
            )


class _LibBlock:
    __slots__ = (
        "lib_path",
        "lib_cb",
        "model",
        "view",
        "card",
        "body",
        "collapse",
        "count_label",
        "entries",
        "populated",
        "expanded",
        "default_on",
        "wanted_ids",
    )

    def __init__(self) -> None:
        self.lib_path = ""
        self.lib_cb: QCheckBox | None = None
        self.model: LibraryVideoTableModel | None = None
        self.view: QTableView | None = None
        self.card: QFrame | None = None
        self.body: QWidget | None = None
        self.collapse: QToolButton | None = None
        self.count_label: QLabel | None = None
        self.entries: list[dict] = []
        self.populated = False
        self.expanded = False
        self.default_on = False
        self.wanted_ids: set[str] = set()


class LibraryGroupedVideoTree(QWidget):
    """Per-library collapsible cards; virtualized checkable video rows."""

    open_library_requested = Signal(str)
    remove_library_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LibraryGroupedVideoTree")
        self._silent = False
        self._blocks: list[_LibBlock] = []
        self._empty_text = ""
        self._open_text = "Open"
        self._remove_text = "Delete"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("LibraryGroupedScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._list_host = QWidget()
        self._list_host.setObjectName("LibraryGroupedList")
        self._vbox = QVBoxLayout(self._list_host)
        self._vbox.setContentsMargins(0, 0, 0, 0)
        self._vbox.setSpacing(0)

        self._empty_label = QLabel()
        self._empty_label.setObjectName("CardHint")
        self._empty_label.setWordWrap(True)
        self._empty_label.setVisible(False)

        self._scroll.setWidget(self._list_host)
        root.addWidget(self._empty_label)
        root.addWidget(self._scroll, 1)

    def set_action_texts(self, *, open_text: str = "", remove_text: str = "", empty_text: str = "") -> None:
        if open_text:
            self._open_text = open_text
        if remove_text:
            self._remove_text = remove_text
        if empty_text:
            self._empty_text = empty_text
            self._empty_label.setText(empty_text)

    def collect_expanded_library_paths(self) -> list[str]:
        return [os.path.normpath(b.lib_path) for b in self._blocks if b.expanded]

    def _block_checked_ids(self, block: _LibBlock) -> list[str]:
        if block.populated and block.model is not None:
            return block.model.checked_video_ids()
        if block.default_on and not block.wanted_ids:
            return [
                str(e.get("video_id") or "").strip()
                for e in block.entries
                if str(e.get("video_id") or "").strip()
            ]
        return [vid for vid in block.wanted_ids if vid]

    def collect_checked_video_ids(self) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for block in self._blocks:
            for vid in self._block_checked_ids(block):
                if vid not in seen:
                    out.append(vid)
                    seen.add(vid)
        return out

    def collect_checked_entries(self) -> list[dict]:
        out: list[dict] = []
        for block in self._blocks:
            if block.populated and block.model is not None:
                out.extend(block.model.checked_entries())
                continue
            wanted = set(self._block_checked_ids(block))
            if not wanted:
                continue
            for ent in block.entries:
                vid = str(ent.get("video_id") or "").strip()
                if vid in wanted:
                    out.append(dict(ent))
        return out

    def refresh_from_entries(
        self,
        entries: Iterable[dict],
        *,
        library_paths: Iterable[str] | None = None,
        default_checked: bool = False,
        checked_video_ids: Iterable[str] | None = None,
        expanded_lib_paths: Iterable[str] | None = None,
    ) -> None:
        prev_checked = set(self.collect_checked_video_ids())
        prev_expanded = set(self.collect_expanded_library_paths())
        self._clear_cards()

        by_lib: dict[str, list[dict]] = defaultdict(list)
        for ent in entries:
            if not ent.get("source_exists", True):
                continue
            lib_path = str(ent.get("library_path", "") or "").strip()
            if not lib_path:
                continue
            by_lib[lib_path].append(ent)

        all_libs: set[str] = set(by_lib.keys())
        for path in library_paths or []:
            text = str(path or "").strip()
            if text:
                all_libs.add(text)

        if not all_libs:
            self._empty_label.setVisible(True)
            self._empty_label.setText(self._empty_text or "")
            self._scroll.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._scroll.setVisible(True)

        if expanded_lib_paths is not None:
            exp_norm = {os.path.normpath(p) for p in expanded_lib_paths if str(p).strip()}
        else:
            exp_norm = prev_expanded

        if checked_video_ids is not None:
            wanted_global = {str(v).strip() for v in checked_video_ids if str(v).strip()}
            default_on = False
        else:
            wanted_global = prev_checked
            default_on = default_checked if not wanted_global else False

        sorted_libs = sorted(all_libs, key=lambda p: p.lower())
        for row_index, lib_path in enumerate(sorted_libs):
            vids = sorted(
                by_lib.get(lib_path, []),
                key=lambda e: str(e.get("video_rel_path") or e.get("video_path") or "").lower(),
            )
            lib_key = os.path.normpath(lib_path)
            lib_wanted = {
                str(e.get("video_id") or "").strip()
                for e in vids
                if str(e.get("video_id") or "").strip() in wanted_global
            }
            # Default collapsed; only restore paths the user already expanded.
            body_exp = bool(exp_norm) and lib_key in exp_norm
            block, card = self._build_library_card(
                lib_path,
                vids,
                default_on=default_on,
                wanted_ids=lib_wanted,
                body_expanded=body_exp,
                row_index=row_index,
            )
            self._blocks.append(block)
            self._vbox.addWidget(card)

        self._vbox.addStretch(1)

    def patch_status_texts(self, by_video_id: dict[str, str]) -> None:
        """Cheap in-place status update without rebuilding cards."""
        if not by_video_id:
            return
        for block in self._blocks:
            for ent in block.entries:
                vid = str(ent.get("video_id") or "").strip()
                if vid in by_video_id:
                    ent["status_text"] = by_video_id[vid]
            if block.populated and block.model is not None:
                block.model.update_status_texts(by_video_id)

    def _clear_cards(self) -> None:
        self._blocks.clear()
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

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
        wanted_ids: set[str],
        body_expanded: bool,
        row_index: int = 0,
    ) -> tuple[_LibBlock, QFrame]:
        block = _LibBlock()
        block.lib_path = lib_path
        block.entries = vids
        block.default_on = default_on
        block.wanted_ids = set(wanted_ids)
        block.expanded = bool(body_expanded)

        card = QFrame()
        card.setObjectName("LibraryLibCard")
        card.setProperty("rowStripe", "odd" if row_index % 2 else "even")
        block.card = card
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("LibraryLibHeader")
        top = QHBoxLayout(header)
        top.setContentsMargins(10, 0, 10, 0)
        top.setSpacing(8)

        collapse = QToolButton()
        collapse.setObjectName("LibraryLibCollapseBtn")
        collapse.setAutoRaise(True)
        collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse.setArrowType(Qt.ArrowType.DownArrow if body_expanded else Qt.ArrowType.RightArrow)
        collapse.setFixedSize(24, 24)
        block.collapse = collapse

        lib_cb = QCheckBox()
        lib_cb.setObjectName("LibraryLibCheck")
        lib_cb.setTristate(True)
        lib_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        block.lib_cb = lib_cb

        title = _ClickLabel(os.path.basename(os.path.normpath(lib_path)) or lib_path)
        title.setObjectName("LibraryLibTitle")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setToolTip(lib_path)
        title.setCursor(Qt.CursorShape.PointingHandCursor)
        lib_cb.setAccessibleName(title.text())

        count_label = QLabel(str(len(vids)))
        count_label.setObjectName("LibraryLibCount")
        count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        count_label.setMinimumWidth(28)
        block.count_label = count_label

        btn_open = QPushButton(self._open_text)
        btn_open.setObjectName("LibraryLibAction")
        btn_open.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_open.clicked.connect(lambda _=False, p=lib_path: self.open_library_requested.emit(p))

        btn_remove = QPushButton(self._remove_text)
        btn_remove.setObjectName("LibraryLibRemove")
        btn_remove.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_remove.clicked.connect(lambda _=False, p=lib_path: self.remove_library_requested.emit(p))

        body = QWidget()
        body.setObjectName("LibraryLibBody")
        block.body = body
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)

        model = LibraryVideoTableModel(body)
        model.set_video_icon(self._video_icon(body))
        block.model = model

        view = QTableView(body)
        view.setObjectName("LibraryGroupedLibTree")
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
        hh = view.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        block.view = view
        body_l.addWidget(view)

        model.dataChanged.connect(lambda *_args, b=block: self._sync_lib_checkbox_from_videos(b, force=True))

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
        top.addWidget(count_label, 0)
        top.addWidget(btn_open, 0)
        top.addWidget(btn_remove, 0)
        outer.addWidget(header)
        outer.addWidget(body)
        body.setVisible(block.expanded)
        card.setProperty("expanded", "true" if block.expanded else "false")

        lib_cb.stateChanged.connect(lambda st, blk=block: self._on_library_state_changed(blk, st))

        if block.expanded:
            self._ensure_populated(block)
        else:
            # Reflect sticky checks on header without loading rows.
            self._sync_lib_checkbox_from_sticky(block)

        return block, card

    def _ensure_populated(self, block: _LibBlock) -> None:
        if block.populated or block.model is None:
            return
        block.model.set_rows(
            block.entries,
            checked_ids=block.wanted_ids or None,
            default_on=block.default_on and not block.wanted_ids,
            preserve_checked=False,
        )
        block.populated = True
        self._sync_lib_checkbox_from_videos(block, force=True)

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
            # Selecting a large collapsed library: mark all ids without building widgets.
            if checked:
                block.wanted_ids = {
                    str(e.get("video_id") or "").strip()
                    for e in block.entries
                    if str(e.get("video_id") or "").strip()
                }
                block.default_on = True
            else:
                block.wanted_ids.clear()
                block.default_on = False
            self._sync_lib_checkbox_from_sticky(block)
            return

        if block.model is not None:
            block.model.set_all_checked(checked)
            block.wanted_ids = set(block.model.checked_video_ids())
        self._sync_lib_checkbox_from_videos(block, force=True)

    def _sync_lib_checkbox_from_sticky(self, block: _LibBlock) -> None:
        tot = sum(1 for e in block.entries if str(e.get("video_id") or "").strip())
        n = len(block.wanted_ids) if not block.default_on else (tot if block.wanted_ids or block.default_on else 0)
        if block.default_on and not block.wanted_ids:
            n = tot
        elif block.wanted_ids:
            n = len(block.wanted_ids)
        else:
            n = 0
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
            self._silent = False

    def _sync_lib_checkbox_from_videos(self, block: _LibBlock, *, force: bool = False) -> None:
        if self._silent and not force:
            return
        if block.model is None:
            return
        n, tot = block.model.check_stats()
        block.wanted_ids = set(block.model.checked_video_ids())
        self._silent = True
        try:
            block.lib_cb.blockSignals(True)
            if tot == 0 or n == 0:
                block.lib_cb.setCheckState(Qt.CheckState.Unchecked)
            elif n == tot:
                block.lib_cb.setCheckState(Qt.CheckState.Checked)
            else:
                block.lib_cb.setCheckState(Qt.CheckState.PartiallyChecked)
            block.lib_cb.blockSignals(False)
        finally:
            self._silent = False
