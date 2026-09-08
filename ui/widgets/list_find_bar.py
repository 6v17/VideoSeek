"""Lightweight Ctrl+F style find bar for grouped library / scope lists.

Does not filter or hide rows — only matches and scrolls the current hit into view
(like a text editor find), with next/previous navigation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from PySide6.QtCore import QModelIndex, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QWidget,
)


@dataclass(frozen=True)
class ListFindHit:
    block_index: int
    entry_index: int  # -1 = library header / path match


def text_matches(haystack: str, needle: str) -> bool:
    q = (needle or "").strip()
    if not q:
        return False
    return q.casefold() in (haystack or "").casefold()


def library_display_name(lib_path: str) -> str:
    text = str(lib_path or "").strip()
    if not text:
        return ""
    return os.path.basename(os.path.normpath(text)) or text


def entry_video_label(ent: dict[str, Any]) -> str:
    rel = str(ent.get("video_rel_path") or "").strip().replace("\\", "/")
    if rel:
        return os.path.basename(rel) or rel
    for key in ("video_path", "abs_path"):
        raw = str(ent.get(key) or "").strip()
        if raw:
            return os.path.basename(raw.replace("\\", "/")) or raw
    return ""


def collect_grouped_find_hits(blocks: Sequence[Any], query: str) -> list[ListFindHit]:
    q = (query or "").strip()
    if not q:
        return []
    # Prefer library-name hits first so typing a folder name jumps to the lib
    # card before any video whose path happens to contain the same substring.
    lib_hits: list[ListFindHit] = []
    video_hits: list[ListFindHit] = []
    for bi, block in enumerate(blocks):
        lib_path = str(getattr(block, "lib_path", "") or "")
        if text_matches(library_display_name(lib_path), q) or text_matches(lib_path, q):
            lib_hits.append(ListFindHit(bi, -1))
        for ei, ent in enumerate(getattr(block, "entries", None) or []):
            if not isinstance(ent, dict):
                continue
            rel = str(ent.get("video_rel_path") or "").strip()
            label = entry_video_label(ent)
            if text_matches(label, q) or text_matches(rel, q):
                video_hits.append(ListFindHit(bi, ei))
    return lib_hits + video_hits


def _repolish(widget: QWidget | None) -> None:
    if widget is None:
        return
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def clear_find_hit_highlights(blocks: Sequence[Any]) -> None:
    for block in blocks:
        card = getattr(block, "card", None)
        if card is not None:
            changed = False
            if str(card.property("findHit") or "") != "false":
                card.setProperty("findHit", "false")
                changed = True
            if str(card.property("findHitKind") or ""):
                card.setProperty("findHitKind", "")
                changed = True
            if changed:
                _repolish(card)
        view = getattr(block, "view", None)
        if view is None:
            continue
        try:
            view.clearSelection()
            view.setCurrentIndex(QModelIndex())
            # Find temporarily enables SingleSelection; restore idle mode so the
            # old hit row cannot keep glowing after the user clicks away.
            view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        except Exception:
            pass


def set_find_hit_highlight(block: Any, *, kind: str = "library") -> None:
    card = getattr(block, "card", None)
    if card is None:
        return
    card.setProperty("findHit", "true")
    card.setProperty("findHitKind", "video" if kind == "video" else "library")
    _repolish(card)


def scroll_widget_into_view(target: QWidget | None, *, x_margin: int = 0, y_margin: int = 48) -> None:
    """Scroll every ancestor QScrollArea so ``target`` is visible.

    Library page nests the tree inside an outer page scroll; scrolling only the
    inner list scroll often does nothing when the outer area is the real scroller.
    """
    if target is None:
        return
    parent = target.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            parent.ensureWidgetVisible(target, x_margin, y_margin)
            # Fallback: some layouts report stale geometry until after polish.
            host = parent.widget()
            bar = parent.verticalScrollBar()
            if host is not None and bar is not None and bar.maximum() > 0:
                try:
                    pos = target.mapTo(host, QPoint(0, 0))
                    desired = max(0, int(pos.y()) - int(y_margin))
                    if abs(bar.value() - desired) > 4:
                        bar.setValue(min(desired, bar.maximum()))
                except Exception:
                    pass
        parent = parent.parentWidget()


def reveal_grouped_find_hit(
    *,
    blocks: Sequence[Any],
    block: Any,
    entry_index: int,
    ensure_populated: Callable[[Any], None],
    set_expanded: Callable[[Any, bool], None],
    still_current: Callable[[], bool] | None = None,
) -> None:
    clear_find_hit_highlights(blocks)
    is_video_hit = entry_index >= 0
    set_find_hit_highlight(block, kind="video" if is_video_hit else "library")

    # Keep only the focused library expanded so find feels auto-tidied.
    # Library-name hits stay collapsed (header highlight); video hits open that body.
    for other in blocks:
        set_expanded(other, bool(is_video_hit and other is block))
    if is_video_hit:
        ensure_populated(block)

    def _finish() -> None:
        if still_current is not None and not still_current():
            return
        card = getattr(block, "card", None)
        scroll_widget_into_view(card)
        if not is_video_hit:
            return
        view = getattr(block, "view", None)
        model = getattr(block, "model", None)
        if view is None or model is None:
            return
        if entry_index >= model.rowCount():
            return
        index = model.index(entry_index, 0)
        if view.selectionMode() == QAbstractItemView.SelectionMode.NoSelection:
            view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setCurrentIndex(index)
        view.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtCenter)
        # Nested table may still sit below the outer viewport after expand.
        scroll_widget_into_view(view)

    # Expand/layout first, then scroll on the next event-loop tick.
    QTimer.singleShot(0, _finish)


def list_find_text_kwargs(texts: dict | None) -> dict[str, str]:
    t = texts or {}
    return {
        "find_placeholder": t.get("list_find_placeholder", "Find library or video name…"),
        "find_prev": t.get("list_find_prev", "↑"),
        "find_next": t.get("list_find_next", "↓"),
        "find_status": t.get("list_find_status", "{current}/{total}"),
        "find_none": t.get("list_find_none", "No match"),
        "find_prev_tip": t.get("list_find_prev_tip", "Previous (Shift+Enter / Shift+F3)"),
        "find_next_tip": t.get("list_find_next_tip", "Next (Enter / F3)"),
    }


class ListFindBar(QWidget):
    """Compact find row: query + prev/next + status."""

    query_changed = Signal(str)
    next_requested = Signal()
    prev_requested = Signal()

    def __init__(self, parent=None, *, compact: bool = False, input_width: int = 200):
        super().__init__(parent)
        self.setObjectName("ListFindBar")
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(6)

        self._input = QLineEdit()
        self._input.setObjectName("SearchInput")
        self._input.setClearButtonEnabled(True)
        self._input.setPlaceholderText("Find library or video name…")
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._on_return_pressed)

        self._btn_prev = QPushButton("↑")
        self._btn_prev.setObjectName("GhostButton")
        self._btn_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_prev.setFixedWidth(32)
        self._btn_prev.setToolTip("Previous (Shift+Enter / Shift+F3)")
        self._btn_prev.clicked.connect(self.prev_requested.emit)

        self._btn_next = QPushButton("↓")
        self._btn_next.setObjectName("GhostButton")
        self._btn_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_next.setFixedWidth(32)
        self._btn_next.setToolTip("Next (Enter / F3)")
        self._btn_next.clicked.connect(self.next_requested.emit)

        self._status = QLabel()
        self._status.setObjectName("ListFindStatus")
        self._status.setMinimumWidth(52)
        self._status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._row.addWidget(self._input, 1)
        self._row.addWidget(self._btn_prev, 0)
        self._row.addWidget(self._btn_next, 0)
        self._row.addWidget(self._status, 0)

        self._status_template = "{current}/{total}"
        self._none_text = "No match"
        self._compact_input_width = max(120, int(input_width))
        self._update_nav_enabled(0)
        if compact:
            self.set_compact(True)

    def set_compact(self, enabled: bool = True, *, input_width: int | None = None) -> None:
        """Keep the find field short so it can sit on a toolbar row."""
        if input_width is not None:
            self._compact_input_width = max(120, int(input_width))
        if enabled:
            self._input.setFixedWidth(self._compact_input_width)
            self._row.setStretch(0, 0)
            self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            return
        self._input.setMinimumWidth(0)
        self._input.setMaximumWidth(16777215)
        self._input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._row.setStretch(0, 1)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)


    def set_texts(
        self,
        *,
        placeholder: str = "",
        prev_text: str = "",
        next_text: str = "",
        status_template: str = "",
        none_text: str = "",
        prev_tip: str = "",
        next_tip: str = "",
    ) -> None:
        if placeholder:
            self._input.setPlaceholderText(placeholder)
        if prev_text:
            self._btn_prev.setText(prev_text)
        if next_text:
            self._btn_next.setText(next_text)
        if status_template:
            self._status_template = status_template
        if none_text:
            self._none_text = none_text
        if prev_tip:
            self._btn_prev.setToolTip(prev_tip)
        if next_tip:
            self._btn_next.setToolTip(next_tip)

    def query(self) -> str:
        return str(self._input.text() or "").strip()

    def focus_input(self) -> None:
        self._input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._input.selectAll()

    def set_match_status(self, current: int, total: int) -> None:
        if total <= 0:
            self._status.setText(self._none_text if self.query() else "")
            self._status.setProperty("hasMatches", "false")
            _repolish(self._status)
            self._update_nav_enabled(0)
            return
        try:
            self._status.setText(
                self._status_template.format(current=max(1, current), total=total)
            )
        except Exception:
            self._status.setText(f"{max(1, current)}/{total}")
        self._status.setProperty("hasMatches", "true")
        _repolish(self._status)
        self._update_nav_enabled(total)

    def install_shortcuts(self, host: QWidget) -> None:
        for old in getattr(self, "_hosted_shortcuts", []):
            try:
                old.setParent(None)
                old.deleteLater()
            except Exception:
                pass
        self._hosted_shortcuts = []

        find_sc = QShortcut(QKeySequence.StandardKey.Find, host)
        find_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        find_sc.activated.connect(self.focus_input)

        next_sc = QShortcut(QKeySequence.StandardKey.FindNext, host)
        next_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        next_sc.activated.connect(self.next_requested.emit)

        prev_sc = QShortcut(QKeySequence.StandardKey.FindPrevious, host)
        prev_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        prev_sc.activated.connect(self.prev_requested.emit)

        esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self._input)
        esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        esc.activated.connect(self._clear_if_focused)

        self._hosted_shortcuts = [find_sc, next_sc, prev_sc, esc]

    def _update_nav_enabled(self, total: int) -> None:
        on = total > 0
        self._btn_prev.setEnabled(on)
        self._btn_next.setEnabled(on)

    def _on_text_changed(self, _text: str) -> None:
        self.query_changed.emit(self.query())

    def _on_return_pressed(self) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            self.prev_requested.emit()
        else:
            self.next_requested.emit()

    def _clear_if_focused(self) -> None:
        if self._input.hasFocus():
            self._input.clear()
