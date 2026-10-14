"""Search-result thumbnail grid (optional view alongside ResultTable)."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt, QSize, QTimer
from shiboken6 import isValid
from PySide6.QtGui import QColor, QCursor, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
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
from ui.widgets.thumb_cell import make_thumb_label

_OVERLAY_FADE_MS = 140
_OVERLAY_HIDE_DELAY_MS = 120

# Thumbnail-first card. ~200px lets five columns fit the content area beside the sidebar.
_CARD_WIDTH = 196
_CARD_SPACING = 12
_GRID_BOTTOM_PAD = 20
_THUMB_HEIGHT = 110


def _fallback_text(texts: dict, key: str, zh_text: str, en_text: str) -> str:
    if key in texts:
        return str(texts[key])
    return en_text if str(texts.get("delete", "")).lower() == "delete" else zh_text


def _frosted_thumb_pixmap(source: QPixmap, size: QSize, *, wash: QColor | None = None) -> QPixmap:
    """Theme-aware frost: downscale → upscale, then wash with panel/accent soft."""
    target_w = max(1, int(size.width()))
    target_h = max(1, int(size.height()))
    wash_color = QColor(wash) if wash is not None else QColor(40, 44, 52, 150)
    if source is None or source.isNull():
        blank = QPixmap(target_w, target_h)
        blank.fill(wash_color)
        return blank
    scaled = source.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - target_w) // 2)
    y = max(0, (scaled.height() - target_h) // 2)
    cropped = scaled.copy(x, y, target_w, target_h)
    tiny = cropped.scaled(
        max(8, target_w // 10),
        max(6, target_h // 10),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    frosted = tiny.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    out = QPixmap(target_w, target_h)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.drawPixmap(0, 0, frosted)
    painter.fillRect(out.rect(), wash_color)
    painter.end()
    return out


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
    """One hit: thumbnail, name, time, score. Hover → frosted table-aligned actions."""

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
        self._on_select = None
        self._title_full = ""
        self._source_pixmap = QPixmap()
        self._overlay_wanted = False
        self._backdrop_dirty = True

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

        self.action_backdrop = QLabel()
        self.action_backdrop.setObjectName("ResultGridActionBackdrop")
        self.action_backdrop.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.action_backdrop.setScaledContents(True)
        self.action_backdrop.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._backdrop_effect = QGraphicsOpacityEffect(self.action_backdrop)
        self._backdrop_effect.setOpacity(0.0)
        self.action_backdrop.setGraphicsEffect(self._backdrop_effect)
        self._backdrop_fade = QPropertyAnimation(self._backdrop_effect, b"opacity", self)
        self._backdrop_fade.setDuration(_OVERLAY_FADE_MS)
        self._backdrop_fade.finished.connect(self._on_backdrop_fade_finished)

        self.action_buttons = QWidget()
        self.action_buttons.setObjectName("ResultGridActions")
        self._actions_layout = QGridLayout(self.action_buttons)
        self._actions_layout.setContentsMargins(8, 10, 8, 10)
        self._actions_layout.setHorizontalSpacing(6)
        self._actions_layout.setVerticalSpacing(6)
        self._actions_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        overlay_root.addWidget(self.action_backdrop, 0, 0)
        overlay_root.addWidget(self.action_buttons, 0, 0, Qt.AlignmentFlag.AlignCenter)

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
        self._backdrop_dirty = True
        self._layout_thumb_chrome()
        if self.action_overlay.isVisible():
            self._refresh_overlay_backdrop()

    def eventFilter(self, watched, event):
        if watched is self.thumb_wrap:
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
            width = max(48, _CARD_WIDTH - 20)
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
        already_up = self._overlay_wanted and self.action_overlay.isVisible()
        self._overlay_wanted = True
        self._layout_thumb_chrome()
        if self._backdrop_dirty or self.action_backdrop.pixmap() is None or self.action_backdrop.pixmap().isNull():
            self._refresh_overlay_backdrop()
        if already_up:
            self._backdrop_fade.stop()
            self._backdrop_effect.setOpacity(1.0)
            return
        self.action_overlay.show()
        self.action_overlay.raise_()
        self.action_buttons.raise_()
        self.rank_label.raise_()
        self._backdrop_fade.stop()
        self._backdrop_fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._backdrop_fade.setStartValue(float(self._backdrop_effect.opacity()))
        self._backdrop_fade.setEndValue(1.0)
        self._backdrop_fade.start()

    def _hide_overlay_now(self) -> None:
        if self._thumb_contains_cursor():
            self._overlay_wanted = True
            return
        self._overlay_wanted = False
        self._backdrop_fade.stop()
        self._backdrop_fade.setEasingCurve(QEasingCurve.Type.InCubic)
        self._backdrop_fade.setStartValue(float(self._backdrop_effect.opacity()))
        self._backdrop_fade.setEndValue(0.0)
        self._backdrop_fade.start()

    def _on_backdrop_fade_finished(self) -> None:
        if self._overlay_wanted:
            return
        if float(self._backdrop_effect.opacity()) <= 0.02:
            self.action_overlay.hide()
            self._backdrop_effect.setOpacity(0.0)

    def _overlay_wash_color(self) -> QColor:
        # Soft panel wash so frost follows light/dark theme instead of flat black.
        base = self.palette().color(QPalette.ColorRole.Base)
        if not base.isValid() or base.alpha() <= 0:
            base = self.palette().color(QPalette.ColorRole.Window)
        wash = QColor(base)
        wash.setAlpha(168)
        return wash

    def _refresh_overlay_backdrop(self) -> None:
        size = self.thumb_wrap.size()
        if size.width() <= 1 or size.height() <= 1:
            size = QSize(_CARD_WIDTH - 16, _THUMB_HEIGHT)
        self.action_backdrop.setPixmap(
            _frosted_thumb_pixmap(self._source_pixmap, size, wash=self._overlay_wash_color())
        )
        self._backdrop_dirty = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._on_select is not None:
            self._on_select(self)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._video_path and self._on_preview:
            if self._on_select is not None:
                self._on_select(self)
            self._on_preview(self._video_path, self._start_sec, self._end_sec)
        super().mouseDoubleClickEvent(event)

    def set_thumbnail(self, pixmap) -> None:
        if pixmap is None or (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            self._source_pixmap = QPixmap()
            self.thumb_label.setPixmap(QPixmap())
            self.thumb_label.setText("—")
            self._backdrop_dirty = True
            if self.action_overlay.isVisible():
                self._refresh_overlay_backdrop()
            return
        self._source_pixmap = QPixmap(pixmap)
        scaled = pixmap.scaled(
            max(160, self.thumb_label.width()),
            max(90, self.thumb_label.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setText("")
        self.thumb_label.setPixmap(scaled)
        self._backdrop_dirty = True
        if self.action_overlay.isVisible():
            self._refresh_overlay_backdrop()

    def _clear_action_buttons(self) -> None:
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _place_action_button(self, button: QPushButton, index: int) -> None:
        row, col = divmod(index, 2)
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
        preview.clicked.connect(
            lambda: self._on_preview
            and self._on_preview(self._video_path, self._start_sec, self._end_sec)
        )
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

        for index, button in enumerate(buttons):
            self._place_action_button(button, index)
            repolish_widget(button)

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
        self._source_pixmap = QPixmap()
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
        self.meta_label.setToolTip(meta)
        meta_width = max(48, self.meta_label.width() - 2) if self.meta_label.width() > 0 else (_CARD_WIDTH - 20)
        self.meta_label.setText(
            self.meta_label.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideRight, meta_width)
        )

        self._rebuild_action_buttons(texts or {})
        self._hide_timer.stop()
        self._backdrop_fade.stop()
        self._overlay_wanted = False
        self._backdrop_dirty = True
        self._backdrop_effect.setOpacity(0.0)
        self.action_overlay.hide()
        self.set_selected(False)
        self.updateGeometry()


class ResultGrid(QScrollArea):
    """Wrapping card grid for local search hits."""

    def __init__(self, parent=None, *, min_height: int | None = None):
        super().__init__(parent)
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
        self._grid = QGridLayout(self._host)
        self._grid.setContentsMargins(8, 8, 8, _GRID_BOTTOM_PAD)
        self._grid.setHorizontalSpacing(_CARD_SPACING)
        self._grid.setVerticalSpacing(_CARD_SPACING)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._host)

        self._cards: list[ResultGridCard] = []
        self._selected: ResultGridCard | None = None
        self._cols = 1
        self._side_pad = -1

    def _card_slot_width(self) -> int:
        return _CARD_WIDTH

    def count(self) -> int:
        return len(self._cards)

    def clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []
        self._selected = None
        self._host.setMinimumHeight(0)

    def set_thumbnail(self, row: int, pixmap) -> None:
        if row < 0 or row >= len(self._cards):
            return
        self._cards[row].set_thumbnail(pixmap)

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
        loading = texts.get("thumb_loading", "…")
        for index, raw in enumerate(results or []):
            card = ResultGridCard(self._host)
            low_confidence = (
                low_confidence_score is not None
                and rank_offset + index == 0
                and float(coerce_search_hit(raw).score) < float(low_confidence_score)
            )
            card.bind(
                rank=rank_offset + index + 1,
                hit=raw,
                texts=texts,
                on_preview=on_preview,
                on_locate=on_locate,
                on_export=on_export,
                on_deep_locate=on_deep_locate,
                on_add_to_shot_list=on_add_to_shot_list,
                clip_score_mode=clip_score_mode,
                low_confidence=low_confidence,
                loading_text=loading,
            )
            card._on_select = self._select_card
            self._cards.append(card)
        self._selected = None
        self._reflow(force=True)
        QTimer.singleShot(0, self._sync_host_height)

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
        loading = texts.get("thumb_loading", "…")
        for index, raw in enumerate(rows):
            card = ResultGridCard(self._host)
            low_confidence = (
                low_confidence_score is not None
                and rank_offset + index == 0
                and float(coerce_search_hit(raw).score) < float(low_confidence_score)
            )
            card.bind(
                rank=rank_offset + index + 1,
                hit=raw,
                texts=texts,
                on_preview=on_preview,
                on_locate=on_locate,
                on_export=on_export,
                on_deep_locate=on_deep_locate,
                on_add_to_shot_list=on_add_to_shot_list,
                clip_score_mode=clip_score_mode,
                low_confidence=low_confidence,
                loading_text=loading,
            )
            card._on_select = self._select_card
            self._cards.append(card)
        self._reflow(force=True)
        bar.setValue(scroll_pos)
        QTimer.singleShot(0, self._sync_host_height)

    def _select_card(self, card: ResultGridCard) -> None:
        self._selected = card
        for other in self._cards:
            other.set_selected(other is card)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, *, force: bool = False) -> None:
        width = max(1, self.viewport().width())
        # Keep a little breathing room; leftover space is split as side padding so the block is centered.
        card_w = self._card_slot_width()
        usable = max(1, width - 16)
        cols = max(1, (usable + _CARD_SPACING) // (card_w + _CARD_SPACING))
        used = cols * card_w + max(0, cols - 1) * _CARD_SPACING
        side = max(8, (width - used) // 2)
        if (
            not force
            and cols == self._cols
            and side == self._side_pad
            and self._grid.count() == len(self._cards)
        ):
            self._sync_host_height()
            return
        self._cols = cols
        self._side_pad = side
        self._grid.setContentsMargins(side, 8, side, _GRID_BOTTOM_PAD)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        for card in self._cards:
            self._grid.removeWidget(card)
        for index, card in enumerate(self._cards):
            row, col = divmod(index, cols)
            self._grid.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop)
        for col in range(max(cols, 1) + 1):
            self._grid.setColumnStretch(col, 0)
            self._grid.setColumnMinimumWidth(col, 0)
        self._sync_host_height()

    def _sync_host_height(self) -> None:
        """Force scrollable height so the last card is not clipped."""
        if not isValid(self) or not isValid(self._host):
            return
        if not self._cards:
            self._host.setMinimumHeight(0)
            return
        self._grid.activate()
        margins = self._grid.contentsMargins()
        cols = max(1, int(self._cols))
        rows = (len(self._cards) + cols - 1) // cols
        row_heights: list[int] = []
        for row in range(rows):
            chunk = self._cards[row * cols : (row + 1) * cols]
            height = 0
            for card in chunk:
                height = max(
                    height,
                    int(card.sizeHint().height()),
                    int(card.minimumSizeHint().height()),
                    int(card.height()) if card.height() > 0 else 0,
                )
            row_heights.append(height)
        spacing = max(0, int(self._grid.verticalSpacing()))
        measured = (
            int(margins.top())
            + int(margins.bottom())
            + sum(row_heights)
            + max(0, rows - 1) * spacing
        )
        layout_hint = int(self._grid.sizeHint().height())
        total = max(measured, layout_hint) + 8
        if self._host.minimumHeight() != total:
            self._host.setMinimumHeight(total)
            self._host.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(480, 280)
