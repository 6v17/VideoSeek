"""Video search scope: per-library cards; inside each, a tree mirroring indexed video_rel_path segments."""
from __future__ import annotations

import os
from collections import defaultdict

from src.services.search_scope import normalize_scope_path
from dataclasses import dataclass, field
from typing import Iterable

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QHeaderView,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

_KIND = Qt.UserRole + 40
_FULL = Qt.UserRole + 41


@dataclass
class _DirTrie:
    subdirs: dict[str, _DirTrie] = field(default_factory=dict)
    files: list[tuple[str, str]] = field(default_factory=list)  # (abs_path, filename)


class _ClickLabel(QLabel):
    """Label that emits clicked on left-button release (expand/collapse library card)."""

    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _LibBlock:
    __slots__ = ("lib_path", "lib_cb", "tree", "video_items")

    def __init__(self, lib_path: str, lib_cb: QCheckBox, tree: QTreeWidget, video_items: list[QTreeWidgetItem]) -> None:
        self.lib_path = lib_path
        self.lib_cb = lib_cb
        self.tree = tree
        self.video_items = video_items


class VideoScopeTreeWidget(QWidget):
    """Card list of libraries; each card contains a path tree aligned with vector index video_rel_path."""

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
        self._vbox.setContentsMargins(0, 0, 4, 0)
        self._vbox.setSpacing(10)

        self._scroll.setWidget(self._list_host)
        root.addWidget(self._scroll, 1)

    def total_video_items(self) -> int:
        return sum(len(b.video_items) for b in self._blocks)

    def collect_expanded_library_paths(self) -> list[str]:
        """Normalized library root paths whose card body (tree) is currently visible."""
        out: list[str] = []
        for block in self._blocks:
            host = block.tree.parent()
            if isinstance(host, QWidget) and host.isVisible():
                out.append(os.path.normpath(block.lib_path))
        return out

    def set_header_labels(self, _name_col: str, _unused_second: str | None = None) -> None:
        """Kept for API compatibility with `MainWindow.apply_texts`; the tree header row is not shown."""

    def refresh_from_entries(
        self,
        entries: Iterable[dict],
        *,
        default_checked: bool = False,
        checked_abs_paths: Iterable[str] | None = None,
        expanded_lib_paths: Iterable[str] | None = None,
    ) -> None:
        self._clear_cards()
        ready: list[dict] = []
        for ent in entries:
            if not ent.get("source_exists"):
                continue
            if str(ent.get("asset_state", "")).strip().lower() != "ready":
                continue
            ready.append(ent)
        by_lib: dict[str, list[dict]] = defaultdict(list)
        for ent in ready:
            lib_path = str(ent.get("library_path", "") or "").strip()
            if not lib_path:
                continue
            by_lib[lib_path].append(ent)

        exp_norm: set[str] | None = None
        if expanded_lib_paths is not None:
            exp_norm = {os.path.normpath(p) for p in expanded_lib_paths if str(p).strip()}

        if checked_abs_paths is not None:
            default_on = False
        else:
            default_on = default_checked
        for lib_path in sorted(by_lib.keys(), key=lambda p: p.lower()):
            vids = sorted(by_lib[lib_path], key=lambda e: str(e.get("video_rel_path", "")).lower())
            lib_key = os.path.normpath(lib_path)
            body_exp = bool(exp_norm is not None and lib_key in exp_norm)
            block, card = self._build_library_card(lib_path, vids, default_on, body_expanded=body_exp)
            self._blocks.append(block)
            self._vbox.addWidget(card)

        self._vbox.addStretch(1)

        if checked_abs_paths is not None:
            wanted = {normalize_scope_path(p) for p in checked_abs_paths if str(p).strip()}
            self._apply_abs_path_checks(wanted)

    def _clear_cards(self) -> None:
        self._blocks.clear()
        while self._vbox.count():
            item = self._vbox.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def apply_checked_paths(self, wanted_abs_paths: Iterable[str]) -> None:
        """Update checkboxes from absolute paths without rebuilding the scope UI."""
        wanted_norm = {normalize_scope_path(str(p)) for p in wanted_abs_paths if str(p).strip()}
        self._apply_abs_path_checks(wanted_norm)

    def _apply_abs_path_checks(self, wanted_norm: set[str]) -> None:
        """Set each video row checked iff its absolute path is in wanted_norm; sync folder tri-state and library checkboxes."""
        self._silent = True
        try:
            for block in self._blocks:
                tree = block.tree
                tree.blockSignals(True)
                try:
                    for it in block.video_items:
                        ap = it.data(0, _FULL)
                        p = normalize_scope_path(str(ap)) if ap else ""
                        it.setCheckState(0, Qt.CheckState.Checked if p in wanted_norm else Qt.CheckState.Unchecked)
                    self._post_sync_folder_checks(tree)
                finally:
                    tree.blockSignals(False)
                self._sync_lib_checkbox_from_videos(block, force=True)
        finally:
            self._silent = False

    @staticmethod
    def _scope_tree_icons(tree: QTreeWidget) -> tuple[QIcon, QIcon]:
        st = tree.style()
        folder = st.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        generic = st.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        video = QIcon.fromTheme("video-x-generic", QIcon.fromTheme("video-mp4", generic))
        return folder, video

    @staticmethod
    def _build_trie(vids: list[dict], lib_norm: str) -> _DirTrie:
        root = _DirTrie()
        for ent in vids:
            rel = str(ent.get("video_rel_path", "") or "").strip().replace("\\", "/")
            if not rel:
                continue
            parts = [p for p in rel.split("/") if p and p not in (".",)]
            if not parts:
                continue
            full = normalize_scope_path(os.path.join(lib_norm, rel.replace("/", os.sep)))
            node = root
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    node.files.append((full, part))
                else:
                    node = node.subdirs.setdefault(part, _DirTrie())
        return root

    def _folder_item_flags(self) -> Qt.ItemFlags:
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        if hasattr(Qt.ItemFlag, "ItemIsTristate"):
            flags |= Qt.ItemFlag.ItemIsTristate
        return flags

    @staticmethod
    def _video_item_flags() -> Qt.ItemFlags:
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable

    def _fill_trie_into_tree(
        self,
        tree: QTreeWidget,
        parent_item: QTreeWidgetItem | None,
        trie: _DirTrie,
        rel_prefix: str,
        default_on: bool,
        video_items: list[QTreeWidgetItem],
    ) -> None:
        folder_ic, video_ic = self._scope_tree_icons(tree)
        state = Qt.CheckState.Checked if default_on else Qt.CheckState.Unchecked
        for name in sorted(trie.subdirs.keys(), key=lambda s: s.lower()):
            child_rel = f"{rel_prefix}/{name}" if rel_prefix else name
            rel_disp = child_rel.replace("\\", "/")
            it = QTreeWidgetItem([name])
            it.setIcon(0, folder_ic)
            it.setToolTip(0, rel_disp)
            it.setData(0, _KIND, "folder")
            it.setFlags(self._folder_item_flags())
            it.setCheckState(0, state)
            if parent_item is None:
                tree.addTopLevelItem(it)
            else:
                parent_item.addChild(it)
            self._fill_trie_into_tree(tree, it, trie.subdirs[name], child_rel, default_on, video_items)

        for full, base in sorted(trie.files, key=lambda x: x[1].lower()):
            rel_display = f"{rel_prefix}/{base}".replace("\\", "/") if rel_prefix else base.replace("\\", "/")
            it = QTreeWidgetItem([base])
            it.setIcon(0, video_ic)
            it.setToolTip(0, f"{rel_display}\n{full}")
            it.setData(0, _KIND, "video")
            it.setData(0, _FULL, full)
            it.setFlags(self._video_item_flags())
            it.setCheckState(0, state)
            video_items.append(it)
            if parent_item is None:
                tree.addTopLevelItem(it)
            else:
                parent_item.addChild(it)

    def _sync_folder_checkbox_from_children(self, folder: QTreeWidgetItem) -> None:
        n = folder.childCount()
        if n == 0:
            return
        checked = sum(1 for i in range(n) if folder.child(i).checkState(0) == Qt.CheckState.Checked)
        unchecked = sum(1 for i in range(n) if folder.child(i).checkState(0) == Qt.CheckState.Unchecked)
        if checked == n:
            folder.setCheckState(0, Qt.CheckState.Checked)
        elif unchecked == n:
            folder.setCheckState(0, Qt.CheckState.Unchecked)
        else:
            folder.setCheckState(0, Qt.CheckState.PartiallyChecked)

    def _post_sync_folder_checks(self, tree: QTreeWidget) -> None:
        def visit(item: QTreeWidgetItem) -> None:
            for i in range(item.childCount()):
                visit(item.child(i))
            if item.data(0, _KIND) == "folder":
                self._sync_folder_checkbox_from_children(item)

        for ti in range(tree.topLevelItemCount()):
            visit(tree.topLevelItem(ti))

    def _apply_check_to_subtree(self, item: QTreeWidgetItem, state: Qt.CheckState) -> None:
        eff = Qt.CheckState.Checked if state == Qt.CheckState.PartiallyChecked else state
        for i in range(item.childCount()):
            self._apply_check_to_subtree(item.child(i), eff)
        kind = item.data(0, _KIND)
        if kind in ("video", "folder"):
            item.setCheckState(0, eff)

    def _reflow_lib_tree(self, tree: QTreeWidget) -> None:
        """Tree is first laid out while its card body may still be hidden; column width stays wrong until a relayout. Fix after show."""
        if not tree.isVisibleTo(tree.window() if tree.window() else tree):
            return
        vw = tree.viewport().width()
        if vw < 8:
            return
        hh = tree.header()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        tree.doItemsLayout()
        tree.header().updateGeometries()
        tree.viewport().update()

    def reflow_all_lib_trees(self) -> None:
        """After the outer scope panel is shown, trees may need a second layout pass."""
        for block in self._blocks:
            self._reflow_lib_tree(block.tree)

    def _on_lib_tree_changed(self, block: _LibBlock, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or self._silent:
            return
        tree = block.tree
        kind = item.data(0, _KIND)
        state = item.checkState(0)
        self._silent = True
        tree.blockSignals(True)
        try:
            if kind == "folder":
                eff = Qt.CheckState.Checked if state == Qt.CheckState.PartiallyChecked else state
                self._apply_check_to_subtree(item, eff)
                p = item.parent()
                while p is not None:
                    self._sync_folder_checkbox_from_children(p)
                    p = p.parent()
            elif kind == "video":
                p = item.parent()
                while p is not None:
                    self._sync_folder_checkbox_from_children(p)
                    p = p.parent()
        finally:
            tree.blockSignals(False)
            self._silent = False
        self._sync_lib_checkbox_from_videos(block, force=True)

    def _build_library_card(self, lib_path: str, vids: list[dict], default_on: bool, *, body_expanded: bool = False) -> tuple[_LibBlock, QFrame]:
        card = QFrame()
        card.setObjectName("VideoScopeLibCard")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(10)
        lib_cb = QCheckBox()
        lib_cb.setObjectName("VideoScopeLibCheck")
        lib_cb.setTristate(True)
        lib_cb.setCursor(Qt.CursorShape.PointingHandCursor)
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

        body = QWidget()
        body.setObjectName("VideoScopeLibBody")
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 0, 0)
        body_l.setSpacing(0)

        lib_norm = os.path.normpath(lib_path)
        trie = self._build_trie(vids, lib_norm)

        tree = QTreeWidget()
        tree.setObjectName("VideoScopeLibTree")
        tree.setColumnCount(1)
        tree.setHeaderLabels([""])
        tree.setRootIsDecorated(True)
        tree.setAnimated(True)
        tree.setIndentation(22)
        tree.setIconSize(QSize(18, 18))
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(False)
        tree.setFrameShape(QFrame.Shape.NoFrame)
        tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        tree.setMinimumHeight(300)
        tree.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        hh = tree.header()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        tree.setHeaderHidden(True)

        video_items: list[QTreeWidgetItem] = []
        self._fill_trie_into_tree(tree, None, trie, "", default_on, video_items)
        tree.blockSignals(True)
        try:
            self._post_sync_folder_checks(tree)
        finally:
            tree.blockSignals(False)

        body_l.addWidget(tree)

        block = _LibBlock(lib_path, lib_cb, tree, video_items)
        tree.itemChanged.connect(lambda it, col, b=block: self._on_lib_tree_changed(b, it, col))

        expanded = bool(body_expanded)

        def set_expanded(on: bool) -> None:
            nonlocal expanded
            expanded = bool(on)
            body.setVisible(expanded)
            collapse.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            if expanded:

                def polish() -> None:
                    self._reflow_lib_tree(tree)
                    if tree.viewport().width() < 8:
                        QTimer.singleShot(50, lambda: self._reflow_lib_tree(tree))

                QTimer.singleShot(0, polish)

        def toggle_expand() -> None:
            set_expanded(not expanded)

        collapse.clicked.connect(toggle_expand)
        title.clicked.connect(toggle_expand)

        top.addWidget(lib_cb, 0)
        top.addWidget(title, 1)
        top.addWidget(collapse, 0)
        outer.addLayout(top)
        outer.addWidget(body)
        body.setVisible(expanded)
        if expanded:

            def _initial_polish() -> None:
                self._reflow_lib_tree(tree)
                if tree.viewport().width() < 8:
                    QTimer.singleShot(50, lambda: self._reflow_lib_tree(tree))

            QTimer.singleShot(0, _initial_polish)

        tree.collapseAll()

        self._sync_lib_checkbox_from_videos(block, force=True)
        lib_cb.stateChanged.connect(lambda st, blk=block: self._on_library_state_changed(blk, st))
        return block, card

    def _on_library_state_changed(self, block: _LibBlock, state: int) -> None:
        if self._silent:
            return
        cs = Qt.CheckState(state)
        self._silent = True
        tree = block.tree
        tree.blockSignals(True)
        try:
            if cs == Qt.CheckState.Checked:
                vs = Qt.CheckState.Checked
            elif cs == Qt.CheckState.Unchecked:
                vs = Qt.CheckState.Unchecked
            else:
                vs = Qt.CheckState.Checked
                block.lib_cb.blockSignals(True)
                block.lib_cb.setCheckState(Qt.CheckState.Checked)
                block.lib_cb.blockSignals(False)
            for it in block.video_items:
                it.setCheckState(0, vs)
            self._post_sync_folder_checks(tree)
        finally:
            tree.blockSignals(False)
            self._silent = False
        self._reflow_lib_tree(tree)
        self._sync_lib_checkbox_from_videos(block, force=True)

    def _sync_lib_checkbox_from_videos(self, block: _LibBlock, *, force: bool = False) -> None:
        if self._silent and not force:
            return
        n = sum(1 for it in block.video_items if it.checkState(0) == Qt.CheckState.Checked)
        tot = len(block.video_items)
        self._silent = True
        try:
            block.lib_cb.blockSignals(True)
            if tot == 0:
                block.lib_cb.setCheckState(Qt.CheckState.Unchecked)
            elif n == 0:
                block.lib_cb.setCheckState(Qt.CheckState.Unchecked)
            elif n == tot:
                block.lib_cb.setCheckState(Qt.CheckState.Checked)
            else:
                block.lib_cb.setCheckState(Qt.CheckState.PartiallyChecked)
            block.lib_cb.blockSignals(False)
        finally:
            self._silent = False

    def select_all_videos(self) -> None:
        self._silent = True
        try:
            for block in self._blocks:
                block.lib_cb.blockSignals(True)
                tree = block.tree
                tree.blockSignals(True)
                try:
                    for it in block.video_items:
                        it.setCheckState(0, Qt.CheckState.Checked)
                    self._post_sync_folder_checks(tree)
                    block.lib_cb.setCheckState(Qt.CheckState.Checked)
                finally:
                    tree.blockSignals(False)
                    block.lib_cb.blockSignals(False)
        finally:
            self._silent = False

    def select_no_videos(self) -> None:
        self._silent = True
        try:
            for block in self._blocks:
                block.lib_cb.blockSignals(True)
                tree = block.tree
                tree.blockSignals(True)
                try:
                    for it in block.video_items:
                        it.setCheckState(0, Qt.CheckState.Unchecked)
                    self._post_sync_folder_checks(tree)
                    block.lib_cb.setCheckState(Qt.CheckState.Unchecked)
                finally:
                    tree.blockSignals(False)
                    block.lib_cb.blockSignals(False)
        finally:
            self._silent = False

    def collect_checked_video_paths(self) -> list[str]:
        out: list[str] = []
        for block in self._blocks:
            for it in block.video_items:
                if it.checkState(0) == Qt.CheckState.Checked:
                    p = it.data(0, _FULL)
                    if p:
                        out.append(normalize_scope_path(str(p)))
        return out

    def scope_selection_counts(self) -> tuple[int, int]:
        """(checked_video_count, libraries_with_at_least_one_checked_video)."""
        n_videos = 0
        n_libs = 0
        for block in self._blocks:
            c = sum(1 for it in block.video_items if it.checkState(0) == Qt.CheckState.Checked)
            if c:
                n_libs += 1
                n_videos += c
        return n_videos, n_libs
