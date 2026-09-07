"""Compact chunk-axis picker for adding a shot to a recap narration unit."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QWidget,
)

from src.services.recap_service import (
    classify_chunk_usage_for_clips,
    format_recap_clock_range,
    owned_chunk_indices_for_clips,
)
from ui.dialogs.shell import VSDialogShell
from ui.widgets.chunk_timeline import ChunkTimelineSegment, ChunkTimelineWidget

# Re-export for callers that import from this dialog module.
__all__ = [
    "RecapChunkPickDialog",
    "classify_chunk_usage_for_clips",
    "owned_chunk_indices_for_clips",
]


class RecapChunkPickDialog(VSDialogShell):
    """Pick one index chunk to insert into the current narration unit."""

    def __init__(
        self,
        parent=None,
        *,
        texts: Mapping[str, Any],
        chunks: Sequence[Mapping[str, Any]] | None,
        usage_by_index: Mapping[int, str] | None = None,
        owned_indices: Sequence[int] | None = None,
        duration_sec: float = 0.0,
        focus_sec: float | None = None,
        on_preview: Callable[[float, float], None] | None = None,
    ):
        _ = on_preview  # Kept for call-site compat; never open nested preview from this dialog.
        self.texts = dict(texts or {})
        self._chunks = [dict(row) for row in chunks or [] if isinstance(row, Mapping)]
        usage = {int(k): str(v) for k, v in dict(usage_by_index or {}).items()}
        # Back-compat: owned_indices → unit usage.
        for index in owned_indices or []:
            usage.setdefault(int(index), "unit")
        self._usage = usage
        self._blocked = {i for i, kind in usage.items() if kind in {"unit", "used"}}
        self._result: dict[str, Any] | None = None
        self._want_custom = False

        super().__init__(
            parent,
            title=str(
                self.texts.get(
                    "understanding_recap_review_chunk_pick_title",
                    "Add shot from chunks",
                )
            ),
            body=str(
                self.texts.get(
                    "understanding_recap_review_chunk_pick_hint",
                    "Green = this unit. Amber = used elsewhere. Gray = free. Click to select, then Add.",
                )
            ),
            minimum_width=580,
            card_margins=(16, 14, 16, 12),
            card_spacing=10,
        )

        legend = QWidget()
        legend_row = QHBoxLayout(legend)
        legend_row.setContentsMargins(0, 0, 0, 0)
        legend_row.setSpacing(12)
        legend_row.addWidget(
            self._swatch(
                "owned",
                self.texts.get("understanding_recap_review_chunk_pick_owned", "In this unit"),
            )
        )
        legend_row.addWidget(
            self._swatch(
                "used",
                self.texts.get("understanding_recap_review_chunk_pick_used", "Used elsewhere"),
            )
        )
        legend_row.addWidget(
            self._swatch(
                "free",
                self.texts.get("understanding_recap_review_chunk_pick_free", "Available"),
            )
        )
        legend_row.addWidget(
            self._swatch(
                "pick",
                self.texts.get("understanding_recap_review_chunk_pick_selected", "Selected"),
            )
        )
        legend_row.addStretch(1)
        self.content_layout.addWidget(legend)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("RecapChunkPickScroll")
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(52)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.timeline = ChunkTimelineWidget()
        self.timeline.setMinimumHeight(36)
        self.timeline.setFixedHeight(36)
        segments: list[ChunkTimelineSegment] = []
        for index, chunk in enumerate(self._chunks):
            start = float(chunk.get("start") or chunk.get("src_in") or 0.0)
            end = float(chunk.get("end") or chunk.get("src_out") or start)
            kind = self._usage.get(index, "")
            if kind == "unit":
                state = "owned"
            elif kind == "used":
                state = "used"
            else:
                state = "free"
            segments.append(ChunkTimelineSegment(start_sec=start, end_sec=end, state=state))
        self.timeline.set_segments(segments, duration_sec=float(duration_sec or 0.0))
        self._scroll.setWidget(self.timeline)
        self.content_layout.addWidget(self._scroll)

        self.status = QLabel()
        self.status.setObjectName("StatusHint")
        self.status.setWordWrap(True)
        self.content_layout.addWidget(self.status)

        self.timeline.chunk_clicked.connect(self._on_chunk_clicked)
        # Double-click only re-selects — never open a nested preview while this modal is up.
        self.timeline.chunk_double_clicked.connect(self._on_chunk_clicked)

        self.add_footer_button(
            str(self.texts.get("cancel", "Cancel")),
            object_name="GhostButton",
            on_click=self.reject,
        )
        self.add_footer_button(
            str(
                self.texts.get(
                    "understanding_recap_review_add_shot_custom",
                    "Custom in/out…",
                )
            ),
            object_name="GhostButton",
            on_click=self._choose_custom,
        )
        self._add_btn = self.add_footer_button(
            str(
                self.texts.get(
                    "understanding_recap_review_chunk_pick_add",
                    "Add to unit",
                )
            ),
            object_name="PrimaryButton",
            on_click=self._accept_pick,
            default=True,
        )

        focus = float(focus_sec) if focus_sec is not None else None
        # Prefer scrolling the unit's first shot chunk into view; select nearest free for Add.
        self._anchor_index = self._first_unit_chunk_index(focus)
        start_index = self._default_index(focus)
        if start_index >= 0:
            self.timeline.set_selected_index(start_index)
            self._on_chunk_clicked(start_index)
        else:
            self._sync_status(-1)
        scroll_to = self._anchor_index if self._anchor_index >= 0 else start_index
        if scroll_to >= 0:
            # Viewport width is often 0 during __init__; scroll after the dialog is shown.
            QTimer.singleShot(0, lambda idx=scroll_to: self._scroll_anchor_into_view(idx))
            QTimer.singleShot(60, lambda idx=scroll_to: self._scroll_anchor_into_view(idx))

    def result_shot(self) -> dict[str, Any] | None:
        return self._result

    def chose_custom(self) -> bool:
        return bool(self._want_custom)

    def _swatch(self, kind: str, label: str) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        chip = QFrame()
        chip.setFixedSize(12, 12)
        chip.setObjectName(
            {
                "owned": "RecapChunkSwatchOwned",
                "used": "RecapChunkSwatchUsed",
                "free": "RecapChunkSwatchFree",
                "pick": "RecapChunkSwatchPick",
            }.get(kind, "RecapChunkSwatchFree")
        )
        text = QLabel(str(label))
        text.setObjectName("InlineFieldLabel")
        row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(text, 0, Qt.AlignmentFlag.AlignVCenter)
        return host

    def _scroll_anchor_into_view(self, index: int) -> None:
        self.timeline.scroll_index_into_view(int(index), force=True)

    def _first_unit_chunk_index(self, focus_sec: float | None) -> int:
        """Earliest chunk already in this narration unit (first shot on the axis)."""
        owned = sorted(i for i, kind in self._usage.items() if kind == "unit")
        if owned:
            return int(owned[0])
        return self._nearest_chunk_index(focus_sec)

    def _nearest_chunk_index(self, focus_sec: float | None) -> int:
        if not self._chunks:
            return -1
        if focus_sec is None:
            return 0
        best = 0
        best_dist = abs(float(self._chunks[0].get("start") or 0.0) - float(focus_sec))
        for index in range(1, len(self._chunks)):
            start = float(self._chunks[index].get("start") or 0.0)
            end = float(self._chunks[index].get("end") or start)
            if start <= float(focus_sec) <= end:
                return index
            dist = abs(start - float(focus_sec))
            if dist < best_dist:
                best = index
                best_dist = dist
        return best

    def _default_index(self, focus_sec: float | None) -> int:
        free = [i for i in range(len(self._chunks)) if i not in self._blocked]
        if not free:
            return 0 if self._chunks else -1
        if focus_sec is None:
            return free[0]
        best = free[0]
        best_dist = abs(float(self._chunks[best].get("start") or 0.0) - float(focus_sec))
        for index in free[1:]:
            start = float(self._chunks[index].get("start") or 0.0)
            dist = abs(start - float(focus_sec))
            if dist < best_dist:
                best = index
                best_dist = dist
        return best

    def _chunk_range(self, index: int) -> tuple[float, float] | None:
        if index < 0 or index >= len(self._chunks):
            return None
        chunk = self._chunks[index]
        start = float(chunk.get("start") or chunk.get("src_in") or 0.0)
        end = float(chunk.get("end") or chunk.get("src_out") or start)
        if end <= start + 0.04:
            return None
        return start, end

    def _sync_status(self, index: int) -> None:
        rang = self._chunk_range(index)
        kind = self._usage.get(index, "")
        if rang is None:
            self.status.setText(
                self.texts.get(
                    "understanding_recap_review_chunk_pick_empty",
                    "No chunks for this video.",
                )
            )
            self._add_btn.setEnabled(False)
            return
        start, end = rang
        cap = str(
            self._chunks[index].get("cap")
            or self._chunks[index].get("text")
            or self._chunks[index].get("caption")
            or ""
        ).strip()
        if kind == "unit":
            msg = self.texts.get(
                "understanding_recap_review_chunk_pick_status_owned",
                "Chunk #{n} · {range} — already in this unit.",
            ).format(n=index + 1, range=format_recap_clock_range(start, end))
            self._add_btn.setEnabled(False)
        elif kind == "used":
            msg = self.texts.get(
                "understanding_recap_review_chunk_pick_status_used",
                "Chunk #{n} · {range} — already used in another unit (would duplicate).",
            ).format(n=index + 1, range=format_recap_clock_range(start, end))
            self._add_btn.setEnabled(False)
        else:
            msg = self.texts.get(
                "understanding_recap_review_chunk_pick_status_free",
                "Chunk #{n} · {range} — click Add to insert.",
            ).format(n=index + 1, range=format_recap_clock_range(start, end))
            self._add_btn.setEnabled(True)
        if cap:
            msg = f"{msg}\n{cap[:120]}"
        self.status.setText(msg)

    def _on_chunk_clicked(self, index: int) -> None:
        self._sync_status(int(index))

    def _choose_custom(self) -> None:
        self._want_custom = True
        self._result = None
        self.accept()

    def _accept_pick(self) -> None:
        index = int(self.timeline.selected_index())
        if index in self._blocked:
            return
        rang = self._chunk_range(index)
        if rang is None:
            return
        self._want_custom = False
        self._result = {
            "chunk_index": index,
            "src_in": float(rang[0]),
            "src_out": float(rang[1]),
        }
        self.accept()
