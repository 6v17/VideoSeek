"""Search-result thumbnail grid (optional view alongside ResultTable)."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from shiboken6 import isValid
from PySide6.QtGui import QCursor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.button_roles import set_button_role
from ui.widgets.styles import repolish_widget
from src.app.path_display import video_display_name
from src.domain.search_hit import coerce_search_hit
from src.services.search_locate import format_clip_score_percent, resolve_clip_confidence_label
from ui.views.table_views import format_time_range as _format_time_range
from ui.widgets.thumb_cell import fit_thumb_pixmap, make_thumb_label

_OVERLAY_HIDE_DELAY_MS = 120

# Preferred card at 100%. Narrower panes shrink toward the scaled minimum, and
# the column count steps through 2 before it jumps to 3.
_CARD_WIDTH = 240
_CARD_MIN = 232
_CARD_SPACING = 12
_GRID_BOTTOM_PAD = 20
_THUMB_HEIGHT = 168
RESULT_SCALE_MIN = 70
RESULT_SCALE_MAX = 160
RESULT_SCALE_DEFAULT = 100


def clamp_result_scale_percent(value, *, snap: bool = False) -> int:
    """Keep a result-card size inside 70–160%. Persisted values snap to 10% steps."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        number = RESULT_SCALE_DEFAULT
    number = max(RESULT_SCALE_MIN, min(RESULT_SCALE_MAX, number))
    if snap:
        number = int(round(number / 10.0) * 10)
        number = max(RESULT_SCALE_MIN, min(RESULT_SCALE_MAX, number))
    return number


def grid_metrics(scale_percent: int = RESULT_SCALE_DEFAULT) -> tuple[int, int, int]:
    """Preferred card width, minimum card width, and thumb height at this size."""
    factor = clamp_result_scale_percent(scale_percent) / 100.0
    card_w = max(160, int(round(_CARD_WIDTH * factor)))
    card_min = max(148, int(round(_CARD_MIN * factor)))
    thumb_h = max(int(round(120 * factor)), int(round(card_w * 9 / 16)))
    return card_w, card_min, thumb_h


def grid_column_plan(viewport_width: int, scale_percent: int = RESULT_SCALE_DEFAULT) -> tuple[int, int, int]:
    """Return column count, card width, and thumb height for the results pane."""
    card_pref, card_min, _preferred_thumb = grid_metrics(scale_percent)
    factor = clamp_result_scale_percent(scale_percent) / 100.0
    usable = max(1, int(viewport_width) - 16)
    natural = max(1, (usable + _CARD_SPACING) // (card_pref + _CARD_SPACING))
    cols = natural
    # Preferred width alone skips 2 columns (476–611px used to stay at 1).
    if usable >= card_min * 2 + _CARD_SPACING:
        cols = max(cols, 2)
    if usable >= card_min * 3 + _CARD_SPACING * 2:
        cols = max(cols, 3)
    max_cols = max(1, (usable + _CARD_SPACING) // (card_min + _CARD_SPACING))
    cols = min(cols, max_cols)
    gaps = max(0, cols - 1) * _CARD_SPACING
    card_w = min(card_pref, max(card_min, (usable - gaps) // cols))
    while cols > 1 and card_w * cols + gaps > usable:
        cols -= 1
        gaps = max(0, cols - 1) * _CARD_SPACING
        card_w = min(card_pref, max(card_min, (usable - gaps) // max(1, cols)))
    thumb_h = max(int(round(120 * factor)), int(round(card_w * 9 / 16)))
    return cols, card_w, thumb_h


def grid_thumb_pixel_size(scale_percent: int = RESULT_SCALE_DEFAULT) -> tuple[int, int]:
    """Decode size for a grid card, in physical pixels so 150% scaling stays sharp."""
    from ui.widgets.thumb_cell import screen_thumb_scale

    factor = clamp_result_scale_percent(scale_percent) / 100.0
    scale = screen_thumb_scale()
    return (
        int(round((_CARD_WIDTH - 16) * factor * scale)),
        int(round(_THUMB_HEIGHT * factor * scale)),
    )


def _fallback_text(texts: dict, key: str, zh_text: str, en_text: str) -> str:
    if key in texts:
        return str(texts[key])
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


def _overlay_action_button(text: str, *, role: str, table_class: str) -> QPushButton:
    """Match result-table action roles (Ghost+TableBtn / Success+Locate)."""
    button = QPushButton(text)
    set_button_role(button, role, chrome="gridOverlay")
    button.setProperty("class", table_class)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setAutoDefault(False)
    button.setDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedHeight(27)
    return button


class ResultGridCard(QFrame):
    """One hit: thumbnail, name, time, score. Hover shows the action buttons."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultGridCard")
        self.setProperty("selected", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        self.setFixedWidth(_CARD_WIDTH)

        self._video_path = ""
        self._start_sec = 0.0
        self._end_sec = 0.0
        self._match_kind = "frame"
        self._score = 0.0
        self._on_preview = None
        self._on_locate = None
        self._on_export = None
        self._on_deep_locate = None
        self._on_add_to_shot_list = None
        self._source_pixmap = None
        self._on_select = None
        self._title_full = ""
        self._overlay_wanted = False
        self._logical_index: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self.thumb_wrap = QFrame()
        self.thumb_wrap.setObjectName("ResultGridThumb")
        self.thumb_wrap.setFixedHeight(_THUMB_HEIGHT)
        self.thumb_wrap.setMouseTracking(True)
        # Hover is tracked on thumb_wrap only. Overlay is a child, so moving onto
        # buttons does not leave the wrap (unlike opacity effects on the overlay).
        self.thumb_wrap.installEventFilter(self)
        thumb_grid = QGridLayout(self.thumb_wrap)
        thumb_grid.setContentsMargins(0, 0, 0, 0)
        thumb_grid.setSpacing(0)

        self.thumb_label = make_thumb_label(text="…")
        self.thumb_label.setMinimumHeight(_THUMB_HEIGHT)
        self.thumb_label.setMaximumHeight(_THUMB_HEIGHT)
        self.thumb_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.thumb_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.rank_label = QLabel(self.thumb_wrap)
        self.rank_label.setObjectName("ResultGridRank")
        self.rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rank_label.setFixedSize(22, 22)
        self.rank_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Absolute overlay (not layout-managed) so show/hide always covers the thumb.
        # No opacity effect on this frame — effects here steal hover and flicker buttons away.
        self.action_overlay = QFrame(self.thumb_wrap)
        self.action_overlay.setObjectName("ResultGridActionOverlay")
        self.action_overlay.hide()
        overlay_root = QGridLayout(self.action_overlay)
        overlay_root.setContentsMargins(0, 0, 0, 0)
        overlay_root.setSpacing(0)

        self.action_buttons = QWidget()
        self.action_buttons.setObjectName("ResultGridActions")
        self._actions_layout = QGridLayout(self.action_buttons)
        self._actions_layout.setContentsMargins(6, 6, 6, 6)
        self._actions_layout.setHorizontalSpacing(6)
        self._actions_layout.setVerticalSpacing(6)
        self._actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        overlay_root.addWidget(self.action_buttons, 0, 0, Qt.AlignmentFlag.AlignCenter)
        self.action_buttons.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Maximum)
        self._overlay_buttons: list[QPushButton] = []
        self._actions_ready = False
        self._pending_action_texts: dict | None = None

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_overlay_now)

        thumb_grid.addWidget(self.thumb_label, 0, 0)
        root.addWidget(self.thumb_wrap)

        self.title_label = QLabel()
        self.title_label.setObjectName("ResultGridTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label.setFixedHeight(self.title_label.fontMetrics().height() + 4)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        root.addWidget(self.title_label)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("ResultGridMeta")
        self.meta_label.setWordWrap(False)
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.meta_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.meta_label.setFixedHeight(self.meta_label.fontMetrics().height() + 2)
        self.meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        root.addWidget(self.meta_label)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_title_elide()
        self._layout_thumb_chrome()

    def eventFilter(self, watched, event):
        thumb_wrap = getattr(self, "thumb_wrap", None)
        if thumb_wrap is not None and watched is thumb_wrap:
            et = event.type()
            if et == QEvent.Type.Enter:
                self._request_overlay(True)
            elif et == QEvent.Type.Leave:
                self._request_overlay(False)
        return super().eventFilter(watched, event)

    def _layout_thumb_chrome(self) -> None:
        rect = self.thumb_wrap.rect()
        if rect.width() <= 1 or rect.height() <= 1:
            return
        self.action_overlay.setGeometry(rect)
        self.rank_label.move(6, 6)
        self.rank_label.raise_()
        if self.action_overlay.isVisible():
            self.action_overlay.raise_()
            self.action_buttons.raise_()
            self.rank_label.raise_()

    def _set_title_text(self, text: str, tooltip: str) -> None:
        self._title_full = str(text or "")
        self.title_label.setToolTip(tooltip or self._title_full)
        self._refresh_title_elide()

    def _refresh_title_elide(self) -> None:
        full = self._title_full
        if not full:
            self.title_label.setText("")
            return
        width = max(48, self.title_label.width() - 2)
        if self.title_label.width() <= 0:
            width = max(48, self.width() - 20, _CARD_WIDTH - 20)
        elided = self.title_label.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideMiddle, width
        )
        self.title_label.setText(elided)

    def set_selected(self, selected: bool) -> None:
        selected = bool(selected)
        if bool(self.property("selected")) == selected:
            return
        self.setProperty("selected", selected)
        repolish_widget(self)

    def _thumb_contains_cursor(self) -> bool:
        pos = self.thumb_wrap.mapFromGlobal(QCursor.pos())
        return self.thumb_wrap.rect().contains(pos)

    def _request_overlay(self, wanted: bool) -> None:
        if wanted:
            self._hide_timer.stop()
            self._show_overlay_now()
            return
        # Delay hide so moving onto buttons never collapses the overlay.
        self._hide_timer.start(_OVERLAY_HIDE_DELAY_MS)

    def _show_overlay_now(self) -> None:
        self._overlay_wanted = True
        # Defer QPushButton creation until the first hover so populate stays cheap.
        if not self._actions_ready and self._pending_action_texts is not None:
            self._rebuild_action_buttons(self._pending_action_texts)
            self._pending_action_texts = None
            self._fit_overlay_actions()
        self._layout_thumb_chrome()
        self.action_overlay.show()
        self.action_overlay.raise_()
        self.action_buttons.raise_()
        self.rank_label.raise_()

    def _hide_overlay_now(self) -> None:
        if self._thumb_contains_cursor():
            self._overlay_wanted = True
            return
        self._overlay_wanted = False
        self.action_overlay.hide()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_select is not None:
            self._on_select(self)
        super().mousePressEvent(event)

    def _emit_preview(self) -> None:
        if self._on_select is not None:
            self._on_select(self)
        if self._video_path and self._on_preview:
            self._on_preview(self._video_path, self._start_sec, self._end_sec)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._video_path and self._on_preview:
            if self._on_select is not None:
                self._on_select(self)
            self._on_preview(self._video_path, self._start_sec, self._end_sec)
        super().mouseDoubleClickEvent(event)

    def apply_slot(self, width: int, thumb_h: int) -> None:
        self.setFixedWidth(int(width))
        self.thumb_wrap.setFixedHeight(int(thumb_h))
        self.thumb_label.setMinimumHeight(int(thumb_h))
        self.thumb_label.setMaximumHeight(int(thumb_h))
        self._layout_thumb_chrome()
        self._fit_overlay_actions(int(width))
        self._refresh_title_elide()
        self._refresh_meta_elide()
        if self._source_pixmap is not None:
            self._paint_thumbnail(self._source_pixmap)

    def _refresh_meta_elide(self) -> None:
        full = str(getattr(self, "_meta_full", "") or self.meta_label.toolTip() or "")
        if not full:
            return
        width = self.meta_label.width()
        if width <= 0:
            width = max(48, self.width() - 20)
        else:
            width = max(48, width - 2)
        self.meta_label.setText(
            self.meta_label.fontMetrics().elidedText(full, Qt.TextElideMode.ElideRight, width)
        )

    def set_thumbnail(self, pixmap) -> None:
        if pixmap is None or (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            self._source_pixmap = None
            self.thumb_label.setPixmap(QPixmap())
            self.thumb_label.setText("—")
            return
        self._source_pixmap = pixmap
        self._paint_thumbnail(pixmap)

    def _paint_thumbnail(self, pixmap) -> None:
        logical_w = max(160, self.thumb_label.width(), self.width() - 16)
        logical_h = max(90, self.thumb_label.height())
        scaled = fit_thumb_pixmap(pixmap, logical_w, logical_h)
        self.thumb_label.setText("")
        self.thumb_label.setPixmap(scaled)

    def _clear_action_buttons(self) -> None:
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _place_action_button(self, button: QPushButton, index: int) -> None:
        del index
        self._overlay_buttons.append(button)

    def _fit_overlay_actions(self, card_width: int | None = None) -> None:
        """Keep hover actions in two columns. Small cards use shorter buttons, not a stacked wall."""
        buttons = [button for button in self._overlay_buttons if isValid(button)]
        self._overlay_buttons = buttons
        while self._actions_layout.count():
            self._actions_layout.takeAt(0)
        if card_width is None:
            card_width = self.width()
        width = max(0, int(card_width) - 16)
        narrow = width < 240
        columns = 2
        gap = 4 if narrow else 6
        self._actions_layout.setHorizontalSpacing(gap)
        self._actions_layout.setVerticalSpacing(gap)
        self._actions_layout.setContentsMargins(4, 4, 4, 4)
        usable = max(96, width - 8 - gap)
        each = max(52, min(84, usable // columns))
        for button in buttons:
            button.setProperty("compact", narrow)
            button.setMinimumWidth(0)
            button.setFixedWidth(each)
            button.setFixedHeight(22 if narrow else 27)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            repolish_widget(button)
        for index, button in enumerate(buttons):
            row, col = divmod(index, columns)
            self._actions_layout.addWidget(button, row, col, Qt.AlignmentFlag.AlignCenter)

    def _rebuild_action_buttons(self, texts: dict) -> None:
        self._clear_action_buttons()
        buttons: list[QPushButton] = []

        # Same order / roles as table_views._build_result_actions.
        preview = _overlay_action_button(
            _fallback_text(texts, "preview", "预览", "Preview"),
            role="GhostButton",
            table_class="TableBtn",
        )
        preview.setToolTip(_fallback_text(texts, "preview_tip", "", ""))
        preview.clicked.connect(self._emit_preview)
        buttons.append(preview)

        if str(self._match_kind or "") == "video" and self._on_deep_locate is not None:
            deep = _overlay_action_button(
                _fallback_text(texts, "deep_locate", "定位镜头", "Find shot"),
                role="GhostButton",
                table_class="TableBtn",
            )
            deep.setToolTip(_fallback_text(texts, "deep_locate_tip", "", ""))
            deep.clicked.connect(
                lambda: self._on_deep_locate
                and self._on_deep_locate(self._video_path, self._start_sec, float(self._score))
            )
            buttons.append(deep)

        locate = _overlay_action_button(
            _fallback_text(texts, "locate", "定位", "Locate"),
            role="SuccessGhostButton",
            table_class="TableLocateBtn",
        )
        locate.setToolTip(_fallback_text(texts, "locate_tip", "", ""))
        locate.clicked.connect(
            lambda: self._on_locate and self._on_locate(self._video_path)
        )
        buttons.append(locate)

        export = _overlay_action_button(
            _fallback_text(texts, "export_clip", "导出", "Export"),
            role="GhostButton",
            table_class="TableBtn",
        )
        export.setToolTip(
            _fallback_text(texts, "export_clip_tip", "导出原画质片段", "Export original-quality clip")
        )
        export.clicked.connect(
            lambda: self._on_export
            and self._on_export(self._video_path, self._start_sec, self._end_sec)
        )
        buttons.append(export)

        if self._on_add_to_shot_list is not None:
            add = _overlay_action_button(
                _fallback_text(texts, "shot_list_add", "加入", "Add"),
                role="SuccessGhostButton",
                table_class="TableBtn",
            )
            add.setToolTip(
                _fallback_text(texts, "shot_list_add_tip", "加入素材篮", "Add to shot list")
            )
            add.clicked.connect(
                lambda: self._on_add_to_shot_list
                and self._on_add_to_shot_list(
                    self._video_path,
                    self._start_sec,
                    self._end_sec,
                    float(self._score),
                    str(self._match_kind or "frame"),
                )
            )
            buttons.append(add)

        self._overlay_buttons = []
        for index, button in enumerate(buttons):
            self._place_action_button(button, index)
        self._actions_ready = True
        self._fit_overlay_actions()

    def bind(
        self,
        *,
        rank: int,
        hit,
        texts: dict,
        on_preview,
        on_locate=None,
        on_export=None,
        on_deep_locate=None,
        on_add_to_shot_list=None,
        clip_score_mode: bool = False,
        low_confidence: bool = False,
        loading_text: str = "…",
    ) -> None:
        coerced = coerce_search_hit(hit)
        self._video_path = str(coerced.video_path or "")
        self._start_sec = float(coerced.start_sec)
        self._end_sec = float(coerced.end_sec)
        self._score = float(coerced.score)
        self._match_kind = str(getattr(coerced, "match_kind", "frame") or "frame")
        matched_text = str(getattr(coerced, "matched_text", "") or "").strip()

        self._on_preview = on_preview
        self._on_locate = on_locate
        self._on_export = on_export
        self._on_deep_locate = on_deep_locate
        self._on_add_to_shot_list = on_add_to_shot_list

        self.rank_label.setText(str(rank))
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(loading_text)

        base_name = video_display_name(self._video_path)
        if self._match_kind in {"dialogue", "tags"} and matched_text:
            self._set_title_text(matched_text, f"{self._video_path}\n\n{matched_text}")
        else:
            self._set_title_text(base_name, self._video_path)

        time_text = _format_time_range(
            self._start_sec, self._end_sec, texts, match_kind=self._match_kind
        )
        if clip_score_mode:
            pct = format_clip_score_percent(self._score)
            tier = resolve_clip_confidence_label(self._score, texts)
            score_text = f"{pct} · {tier}" if tier else pct
        else:
            score_text = f"{int(self._score * 100)}%"
        if low_confidence:
            score_text = f"{score_text} ⚠"
        meta = f"{time_text} · {score_text}"
        self._meta_full = meta
        self.meta_label.setToolTip(meta)
        self._refresh_meta_elide()

        # Build overlay buttons lazily on first hover (table virtualization companion).
        self._clear_action_buttons()
        self._overlay_buttons = []
        self._actions_ready = False
        self._pending_action_texts = dict(texts or {})
        self._hide_timer.stop()
        self._overlay_wanted = False
        self.action_overlay.hide()
        self.set_selected(False)
        self.updateGeometry()


class ResultGrid(QScrollArea):
    """Wrapping card grid for local search hits (viewport card pool / recycle)."""

    _ROW_BUFFER = 2
    # First search used to build the pool on the hot path (~300ms). Warm a
    # handful of hidden cards after the first paint instead.
    _POOL_PREWARM = 10

    def __init__(self, parent=None, *, min_height: int | None = None):
        super().__init__(parent)
        # setWidget() installs this object as an event filter before the rest of init.
        self._pool_prewarm_done = False
        self.setObjectName("ResultGrid")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if min_height is not None:
            self.setMinimumHeight(min_height)

        self._host = QWidget()
        self._host.setObjectName("ResultGridHost")
        self._host.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        # Absolute card geometry (not QGridLayout rows) so off-screen logical rows
        # still reserve scroll height without creating widgets.
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(8, 8, 8, _GRID_BOTTOM_PAD)
        self._grid.setHorizontalSpacing(_CARD_SPACING)
        self._grid.setVerticalSpacing(_CARD_SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._host)

        # Authoritative hit list. Each entry holds bind kwargs + optional pixmap.
        self._items: list[dict] = []
        # Recycled ResultGridCard pool (≈ visible rows × cols, not len(items)).
        self._cards: list[ResultGridCard] = []
        self._bound: dict[int, ResultGridCard] = {}
        self._selected_index: int | None = None
        self._selected: ResultGridCard | None = None
        self._cols = 1
        self._side_pad = 8
        self._card_w = _CARD_WIDTH
        self._thumb_h = _THUMB_HEIGHT
        self._row_pitch = 0
        self._scale_percent = RESULT_SCALE_DEFAULT
        self._syncing = False

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def set_display_scale(self, scale_percent: int) -> None:
        """Resize every card. Existing thumbnails are refit from the source frame."""
        self._scale_percent = clamp_result_scale_percent(scale_percent)
        self._reflow(force=True)

    def _card_slot_width(self) -> int:
        card_w, _card_min, _thumb_h = grid_metrics(self._scale_percent)
        return card_w

    def count(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items = []
        self._bound.clear()
        self._selected_index = None
        self._selected = None
        for card in self._cards:
            if not isValid(card):
                continue
            card._logical_index = None
            card.set_selected(False)
            card.hide()
            self._grid.removeWidget(card)
        self._host.setMinimumHeight(0)

    def set_thumbnail(self, row: int, pixmap) -> None:
        if row < 0 or row >= len(self._items):
            return
        # Own a copy so callers can drop their temporary QPixmap.
        if pixmap is not None and not (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            pixmap = QPixmap(pixmap)
        self._items[row]["pixmap"] = pixmap
        card = self._bound.get(row)
        if card is not None and isValid(card):
            card.set_thumbnail(pixmap)

    def populate(
        self,
        results,
        on_preview,
        on_locate,
        on_export,
        texts,
        on_deep_locate=None,
        on_add_to_shot_list=None,
        *,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
        rank_offset: int = 0,
        highlight_query: str = "",
        dialogue_match_mode: str = "",
    ) -> None:
        del highlight_query, dialogue_match_mode
        self.clear()
        self._extend_items(
            results,
            on_preview,
            on_locate,
            on_export,
            texts,
            on_deep_locate=on_deep_locate,
            on_add_to_shot_list=on_add_to_shot_list,
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_score,
            rank_offset=rank_offset,
        )
        self._selected_index = None
        self._selected = None
        self._reflow(force=True)
        QTimer.singleShot(0, self._after_layout)

    def append(
        self,
        results,
        on_preview,
        on_locate,
        on_export,
        texts,
        on_deep_locate=None,
        on_add_to_shot_list=None,
        *,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
        rank_offset: int = 0,
        highlight_query: str = "",
        dialogue_match_mode: str = "",
    ) -> None:
        """Add hits under the current list without moving the scroll position."""
        del highlight_query, dialogue_match_mode
        rows = list(results or [])
        if not rows:
            return
        bar = self.verticalScrollBar()
        scroll_pos = int(bar.value())
        self._extend_items(
            rows,
            on_preview,
            on_locate,
            on_export,
            texts,
            on_deep_locate=on_deep_locate,
            on_add_to_shot_list=on_add_to_shot_list,
            clip_score_mode=clip_score_mode,
            low_confidence_score=low_confidence_score,
            rank_offset=rank_offset,
        )
        self._reflow(force=True)
        bar.setValue(scroll_pos)
        QTimer.singleShot(0, lambda: self._restore_scroll(scroll_pos))

    def _extend_items(
        self,
        results,
        on_preview,
        on_locate,
        on_export,
        texts,
        *,
        on_deep_locate=None,
        on_add_to_shot_list=None,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
        rank_offset: int = 0,
    ) -> None:
        loading = (texts or {}).get("thumb_loading", "…")
        for index, raw in enumerate(results or []):
            low_confidence = (
                low_confidence_score is not None
                and rank_offset + index == 0
                and float(coerce_search_hit(raw).score) < float(low_confidence_score)
            )
            self._items.append(
                {
                    "hit": raw,
                    "rank": rank_offset + index + 1,
                    "texts": texts,
                    "on_preview": on_preview,
                    "on_locate": on_locate,
                    "on_export": on_export,
                    "on_deep_locate": on_deep_locate,
                    "on_add_to_shot_list": on_add_to_shot_list,
                    "clip_score_mode": clip_score_mode,
                    "low_confidence": low_confidence,
                    "loading_text": loading,
                    "pixmap": None,
                }
            )

    def _select_card(self, card: ResultGridCard) -> None:
        idx = getattr(card, "_logical_index", None)
        self._selected_index = idx if isinstance(idx, int) else None
        self._selected = card if self._selected_index is not None else None
        for other in self._cards:
            if not isValid(other):
                continue
            other.set_selected(getattr(other, "_logical_index", None) == self._selected_index)

    def select_match(self, video_path: str, start_sec: float) -> bool:
        """Mark the hit that is playing and scroll it into the grid."""
        target = str(video_path or "").strip().replace("/", "\\").lower()
        best_index = None
        best_delta = 0.51
        for index, item in enumerate(self._items):
            coerced = coerce_search_hit(item["hit"])
            card_path = str(coerced.video_path or "").strip().replace("/", "\\").lower()
            if card_path != target:
                continue
            delta = abs(float(coerced.start_sec) - float(start_sec or 0.0))
            if delta < best_delta:
                best_index = index
                best_delta = delta
        if best_index is None:
            return False
        self._selected_index = best_index
        self._ensure_index_visible(best_index)
        self._sync_visible(force_rebind=False)
        card = self._bound.get(best_index)
        if card is not None and isValid(card):
            self._selected = card
            for other in self._cards:
                if isValid(other):
                    other.set_selected(getattr(other, "_logical_index", None) == best_index)
            self.ensureWidgetVisible(card, 24, 24)
        return True

    def card_at(self, logical_index: int) -> ResultGridCard | None:
        """Return the live pool card currently bound to a logical hit, if any."""
        card = self._bound.get(int(logical_index))
        if card is not None and isValid(card):
            return card
        return None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def eventFilter(self, watched, event):  # noqa: N802
        # QScrollArea already filters its viewport. Hook that path; do not remove the filter.
        if not self._pool_prewarm_done and event.type() == QEvent.Type.Paint:
            viewport = self.viewport()
            if viewport is not None and viewport.width() >= 40 and viewport.height() >= 40:
                self._pool_prewarm_done = True
                # After this paint returns, so the first frame is not waiting on the pool.
                QTimer.singleShot(0, self._prewarm_pool)
        return super().eventFilter(watched, event)

    def _prewarm_pool(self) -> None:
        """Build a few hidden cards so the first populate does not construct them."""
        if not isValid(self) or not isValid(self._host):
            return
        self._ensure_pool(self._POOL_PREWARM)
        for card in self._cards:
            if not isValid(card):
                continue
            card.ensurePolished()
            for child in card.findChildren(QWidget):
                if isValid(child):
                    child.ensurePolished()

    def _on_scroll(self, _value: int = 0) -> None:
        if self._syncing:
            return
        self._sync_visible()

    def _after_layout(self) -> None:
        self._sync_host_height()
        self._sync_visible(force_rebind=True)

    def _restore_scroll(self, scroll_pos: int) -> None:
        self._sync_host_height()
        self.verticalScrollBar().setValue(int(scroll_pos))
        self._sync_visible(force_rebind=True)

    def _reflow(self, *, force: bool = False) -> None:
        width = max(1, self.viewport().width())
        cols, card_w, thumb_h = grid_column_plan(width, self._scale_percent)
        used = cols * card_w + max(0, cols - 1) * _CARD_SPACING
        side = max(8, (width - used) // 2)
        geometry_changed = (
            force
            or cols != self._cols
            or side != self._side_pad
            or card_w != self._card_w
            or thumb_h != self._thumb_h
        )
        self._cols = cols
        self._side_pad = side
        self._card_w = card_w
        self._thumb_h = thumb_h
        self._grid.setContentsMargins(side, 8, side, _GRID_BOTTOM_PAD)
        # Measure row pitch from one pool card (or a throwaway) after apply_slot.
        probe = self._cards[0] if self._cards and isValid(self._cards[0]) else None
        if probe is None:
            probe = ResultGridCard(self._host)
            probe.hide()
            self._cards.append(probe)
            probe._on_select = self._select_card
        probe.apply_slot(card_w, thumb_h)
        card_h = max(
            int(probe.sizeHint().height()),
            int(probe.minimumSizeHint().height()),
            int(thumb_h) + 48,
        )
        self._row_pitch = card_h + _CARD_SPACING
        for card in self._cards:
            if isValid(card):
                card.apply_slot(card_w, thumb_h)
        self._sync_host_height()
        self._sync_visible(force_rebind=geometry_changed)

    def _logical_rows(self) -> int:
        cols = max(1, int(self._cols))
        n = len(self._items)
        if n <= 0:
            return 0
        return (n + cols - 1) // cols

    def _sync_host_height(self) -> None:
        """Host height = full logical grid so the scrollbar range stays correct."""
        if not isValid(self) or not isValid(self._host):
            return
        if not self._items:
            self._host.setMinimumHeight(0)
            return
        margins = self._grid.contentsMargins()
        rows = self._logical_rows()
        pitch = self._row_pitch_px()
        # pitch includes inter-row spacing; last row has no trailing gap below cards
        # but bottom margin still applies.
        body = rows * pitch - _CARD_SPACING if rows > 0 else 0
        total = int(margins.top()) + int(margins.bottom()) + max(0, body) + 8
        if self._host.minimumHeight() != total:
            self._host.setMinimumHeight(total)
            self._host.updateGeometry()

    def _row_pitch_px(self) -> int:
        """Never use a 1px pitch — that would treat the whole list as "visible"."""
        measured = int(self._row_pitch or 0)
        floor = int(self._thumb_h or _THUMB_HEIGHT) + 48 + _CARD_SPACING
        return max(measured, floor, 120)

    def _visible_index_range(self) -> tuple[int, int]:
        n = len(self._items)
        if n <= 0:
            return 0, -1
        cols = max(1, int(self._cols))
        pitch = self._row_pitch_px()
        margins = self._grid.contentsMargins()
        top_margin = int(margins.top())
        scroll = int(self.verticalScrollBar().value())
        view_h = max(1, int(self.viewport().height()))
        first_row = max(0, (scroll - top_margin) // pitch - self._ROW_BUFFER)
        last_row = ((scroll + view_h - top_margin) // pitch) + self._ROW_BUFFER
        max_row = self._logical_rows() - 1
        first_row = max(0, min(first_row, max_row))
        last_row = max(0, min(last_row, max_row))
        first = first_row * cols
        last = min(n - 1, (last_row + 1) * cols - 1)
        return first, last

    def _ensure_pool(self, need: int) -> None:
        # Cap growth so a bad pitch cannot spawn one widget per hit.
        cols = max(1, int(self._cols))
        view_h = max(1, int(self.viewport().height()))
        pitch = self._row_pitch_px()
        view_rows = max(1, (view_h + pitch - 1) // pitch)
        soft_cap = cols * (view_rows + self._ROW_BUFFER * 2 + 2)
        need = max(0, min(int(need), soft_cap, 64))
        while len(self._cards) < need:
            if not isValid(self._host):
                break
            card = ResultGridCard(self._host)
            card.hide()
            card._on_select = self._select_card
            card._logical_index = None
            self._cards.append(card)
        # Drop invalid entries (deleteLater leftovers).
        self._cards = [c for c in self._cards if isValid(c)]

    def _unbind_card(self, card: ResultGridCard) -> None:
        idx = getattr(card, "_logical_index", None)
        if isinstance(idx, int) and self._bound.get(idx) is card:
            self._bound.pop(idx, None)
        card._logical_index = None
        card.hide()
        self._grid.removeWidget(card)

    def _bind_card(self, card: ResultGridCard, index: int) -> None:
        item = self._items[index]
        card.bind(
            rank=int(item["rank"]),
            hit=item["hit"],
            texts=item["texts"],
            on_preview=item["on_preview"],
            on_locate=item["on_locate"],
            on_export=item["on_export"],
            on_deep_locate=item["on_deep_locate"],
            on_add_to_shot_list=item["on_add_to_shot_list"],
            clip_score_mode=bool(item["clip_score_mode"]),
            low_confidence=bool(item["low_confidence"]),
            loading_text=str(item["loading_text"]),
        )
        card._on_select = self._select_card
        card._logical_index = index
        card.apply_slot(self._card_w, self._thumb_h)
        pix = item.get("pixmap")
        if pix is not None:
            card.set_thumbnail(pix)
        card.set_selected(index == self._selected_index)
        self._bound[index] = card
        self._place_card(card, index)
        card.show()

    def _place_card(self, card: ResultGridCard, index: int) -> None:
        cols = max(1, int(self._cols))
        row, col = divmod(int(index), cols)
        margins = self._grid.contentsMargins()
        x = int(margins.left()) + col * (self._card_w + _CARD_SPACING)
        y = int(margins.top()) + row * max(1, int(self._row_pitch))
        # Prefer absolute geometry so empty logical rows still scroll correctly.
        card.setFixedWidth(int(self._card_w))
        card_h = max(
            int(card.sizeHint().height()),
            int(card.minimumSizeHint().height()),
            int(self._thumb_h) + 48,
            max(0, int(self._row_pitch) - _CARD_SPACING),
        )
        card.setGeometry(x, y, int(self._card_w), card_h)
        card.raise_()
        # Not managed by QGridLayout — geometry is absolute on the host.
        self._grid.removeWidget(card)

    def _ensure_index_visible(self, index: int) -> None:
        cols = max(1, int(self._cols))
        pitch = self._row_pitch_px()
        margins = self._grid.contentsMargins()
        row = int(index) // cols
        y = int(margins.top()) + row * pitch
        bar = self.verticalScrollBar()
        view_h = max(1, int(self.viewport().height()))
        value = int(bar.value())
        if y < value:
            bar.setValue(y)
        elif y + pitch > value + view_h:
            bar.setValue(max(0, y + pitch - view_h))

    def _sync_visible(self, *, force_rebind: bool = False) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            if not self._items:
                for card in self._cards:
                    if isValid(card):
                        self._unbind_card(card)
                self._bound.clear()
                return
            first, last = self._visible_index_range()
            if last < first:
                for card in self._cards:
                    if isValid(card):
                        self._unbind_card(card)
                self._bound.clear()
                return
            need = last - first + 1
            self._ensure_pool(need)

            # Release cards whose logical index left the window.
            for idx in list(self._bound.keys()):
                if idx < first or idx > last:
                    card = self._bound.pop(idx)
                    if isValid(card):
                        self._unbind_card(card)

            free: list[ResultGridCard] = []
            for card in self._cards:
                if not isValid(card):
                    continue
                idx = getattr(card, "_logical_index", None)
                if idx is None:
                    free.append(card)
                elif force_rebind and first <= idx <= last:
                    # Geometry/scale changed: reposition; rebinding same hit is wasteful
                    # unless we force a full data refresh.
                    self._place_card(card, idx)
                    card.apply_slot(self._card_w, self._thumb_h)
                    card.set_selected(idx == self._selected_index)
                    card.show()

            for idx in range(first, last + 1):
                if idx in self._bound and isValid(self._bound[idx]):
                    card = self._bound[idx]
                    self._place_card(card, idx)
                    card.show()
                    continue
                if not free:
                    self._ensure_pool(len(self._cards) + 1)
                    free = [
                        c
                        for c in self._cards
                        if isValid(c) and getattr(c, "_logical_index", None) is None
                    ]
                if not free:
                    break
                card = free.pop()
                self._bind_card(card, idx)

            if self._selected_index is not None:
                bound = self._bound.get(self._selected_index)
                self._selected = bound if bound is not None and isValid(bound) else None
        finally:
            self._syncing = False

    def sizeHint(self) -> QSize:
        return QSize(480, 280)
