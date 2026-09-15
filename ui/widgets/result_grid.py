"""Search-result thumbnail grid (optional view alongside ResultTable)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.app.path_display import video_display_name
from src.domain.search_hit import coerce_search_hit
from src.services.search_locate import format_clip_score_percent, resolve_clip_confidence_label
from ui.views.table_views import _format_time_range
from ui.widgets.thumb_cell import make_thumb_label

# Wide enough for video-discovery actions: 预览 / 定位镜头 / 定位 / 导出 / 加入
_CARD_MIN_WIDTH = 312
_CARD_SPACING = 12
_GRID_BOTTOM_PAD = 20
_BTN_H = 30
_BTN_W = 54
_BTN_DEEP_W = 72
_BTN_ADD_W = 46


class ResultGridCard(QFrame):
    """One hit: thumb + title + meta + compact actions (same set/order as list)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultGridCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.setFixedWidth(_CARD_MIN_WIDTH)

        self._video_path = ""
        self._start_sec = 0.0
        self._end_sec = 0.0
        self._on_preview = None
        self._title_full = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        self.rank_label = QLabel()
        self.rank_label.setObjectName("ResultGridRank")
        self.rank_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.rank_label.setFixedSize(22, 22)
        head.addWidget(self.rank_label, 0)
        head.addStretch(1)
        root.addLayout(head)

        self.thumb_label = make_thumb_label(text="…")
        self.thumb_label.setMinimumHeight(84)
        self.thumb_label.setMaximumHeight(110)
        self.thumb_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root.addWidget(self.thumb_label)

        self.title_label = QLabel()
        self.title_label.setObjectName("ResultGridTitle")
        self.title_label.setWordWrap(False)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.title_label.setFixedHeight(self.title_label.fontMetrics().height() + 4)
        root.addWidget(self.title_label)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("ResultGridMeta")
        self.meta_label.setWordWrap(False)
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.meta_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.meta_label.setFixedHeight(self.meta_label.fontMetrics().height() + 2)
        root.addWidget(self.meta_label)

        self.actions_host = QWidget()
        self.actions_host.setObjectName("ResultGridActions")
        self.actions_host.setMinimumHeight(_BTN_H)
        actions_layout = QVBoxLayout(self.actions_host)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(0)
        root.addWidget(self.actions_host)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_title_elide()

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
            width = max(48, _CARD_MIN_WIDTH - 20)
        elided = self.title_label.fontMetrics().elidedText(
            full, Qt.TextElideMode.ElideMiddle, width
        )
        self.title_label.setText(elided)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._video_path and self._on_preview:
            self._on_preview(self._video_path, self._start_sec, self._end_sec)
        super().mouseDoubleClickEvent(event)

    def set_thumbnail(self, pixmap) -> None:
        if pixmap is None or (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            self.thumb_label.setPixmap(QPixmap())
            self.thumb_label.setText("—")
            return
        scaled = pixmap.scaled(
            max(160, self.thumb_label.width()),
            max(90, self.thumb_label.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setText("")
        self.thumb_label.setPixmap(scaled)

    def bind(
        self,
        *,
        rank: int,
        hit,
        texts: dict,
        on_preview,
        on_locate,
        on_export,
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
        score = float(coerced.score)
        match_kind = str(getattr(coerced, "match_kind", "frame") or "frame")
        matched_text = str(getattr(coerced, "matched_text", "") or "").strip()

        self.rank_label.setText(str(rank))
        self.thumb_label.setPixmap(QPixmap())
        self.thumb_label.setText(loading_text)

        base_name = video_display_name(self._video_path)
        if match_kind in {"dialogue", "tags"} and matched_text:
            self._set_title_text(matched_text, f"{self._video_path}\n\n{matched_text}")
        else:
            self._set_title_text(base_name, self._video_path)

        time_text = _format_time_range(
            self._start_sec, self._end_sec, texts, match_kind=match_kind
        )
        if clip_score_mode:
            pct = format_clip_score_percent(score)
            tier = resolve_clip_confidence_label(score, texts)
            score_text = f"{pct} · {tier}" if tier else pct
        else:
            score_text = f"{int(score * 100)}%"
        if low_confidence:
            score_text = f"{score_text} ⚠"
        meta = f"{time_text} · {score_text}"
        self.meta_label.setToolTip(meta)
        meta_width = max(48, self.meta_label.width() - 2) if self.meta_label.width() > 0 else (_CARD_MIN_WIDTH - 20)
        self.meta_label.setText(
            self.meta_label.fontMetrics().elidedText(meta, Qt.TextElideMode.ElideRight, meta_width)
        )

        layout = self.actions_host.layout()
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        row_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        def _action(text: str, tip: str, slot, *, width: int = _BTN_W, btn_class: str = "TableBtn") -> QPushButton:
            btn = QPushButton(text)
            btn.setProperty("class", btn_class)
            btn.setFixedSize(width, _BTN_H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if tip:
                btn.setToolTip(tip)
            btn.clicked.connect(slot)
            return btn

        # Same order / roles as list view ``_build_result_actions``.
        row_layout.addWidget(
            _action(
                texts.get("preview", "Preview"),
                texts.get("preview_tip", ""),
                lambda _=False, p=self._video_path, s=self._start_sec, e=self._end_sec: on_preview(p, s, e),
            )
        )
        if match_kind == "video" and on_deep_locate is not None:
            row_layout.addWidget(
                _action(
                    texts.get("deep_locate", "Find shot"),
                    texts.get("deep_locate_tip", ""),
                    lambda _=False, p=self._video_path, a=self._start_sec, sc=score: on_deep_locate(p, a, sc),
                    width=_BTN_DEEP_W,
                )
            )
        row_layout.addWidget(
            _action(
                texts.get("locate", "Locate"),
                texts.get("locate_tip", ""),
                lambda _=False, p=self._video_path: on_locate(p),
                btn_class="TableLocateBtn",
            )
        )
        if on_export is not None:
            row_layout.addWidget(
                _action(
                    texts.get("export_clip", "Export"),
                    texts.get("export_clip_tip", ""),
                    lambda _=False, p=self._video_path, s=self._start_sec, e=self._end_sec: on_export(p, s, e),
                )
            )
        if on_add_to_shot_list is not None:
            row_layout.addWidget(
                _action(
                    texts.get("shot_list_add", "Add"),
                    texts.get("shot_list_add_tip", ""),
                    lambda _=False, p=self._video_path, s=self._start_sec, e=self._end_sec, sc=score, k=match_kind: on_add_to_shot_list(
                        p, s, e, sc, k
                    ),
                    width=_BTN_ADD_W,
                )
            )
        layout.addWidget(row)

        self._on_preview = on_preview
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
        self._cols = 1
        self._side_pad = -1

    def count(self) -> int:
        return len(self._cards)

    def clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []
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
            self._cards.append(card)
        self._reflow(force=True)
        # Layout/QSS settle on the next tick; re-measure so the last action row is scrollable.
        QTimer.singleShot(0, self._sync_host_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self, *, force: bool = False) -> None:
        width = max(1, self.viewport().width())
        # Keep a little breathing room; leftover space is split as side padding so the block is centered.
        usable = max(1, width - 16)
        cols = max(1, (usable + _CARD_SPACING) // (_CARD_MIN_WIDTH + _CARD_SPACING))
        used = cols * _CARD_MIN_WIDTH + max(0, cols - 1) * _CARD_SPACING
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
        """Force scrollable height so the last card's action row is not clipped."""
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
        # Keep a little extra so the final action buttons clear the viewport edge.
        total = max(measured, layout_hint) + 8
        if self._host.minimumHeight() != total:
            self._host.setMinimumHeight(total)
            self._host.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(480, 280)
