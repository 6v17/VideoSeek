"""Virtualized local-search result rows (QAbstractTableModel).

Mirrors LibraryVideoTableModel: data lives in the model; QTableView only realizes
visible cells. Thumbnails / action widgets are applied via roles + delegates.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QPixmap

from src.app.path_display import video_display_name
from src.domain.search_hit import coerce_search_hit
from src.services.search_locate import format_clip_score_percent, resolve_clip_confidence_label, resolve_clip_confidence_tier_key
from ui.views.dialogue_highlight import highlight_dialogue_html
from ui.views.table_views import format_time_range, result_mode_label
from ui.widgets.table_specs import LocalSearchCol

# Custom roles for delegates.
ThumbRole = int(Qt.ItemDataRole.UserRole) + 10
VideoHtmlRole = int(Qt.ItemDataRole.UserRole) + 11
HitPayloadRole = int(Qt.ItemDataRole.UserRole)  # same as ORDER cell payload historically
GroupMetaRole = int(Qt.ItemDataRole.UserRole) + 12


def _escape_html(text: str) -> str:
    from html import escape

    return escape(str(text or ""))


def _score_display(
    score: float,
    texts: dict,
    *,
    clip_mode: bool,
    low_confidence: bool,
) -> tuple[str, str]:
    pct_label = format_clip_score_percent(score) if clip_mode else f"{int(float(score) * 100)}%"
    if clip_mode:
        tier_label = resolve_clip_confidence_label(score, texts)
        label = f"{pct_label} · {tier_label}" if tier_label else pct_label
    else:
        label = pct_label
    if low_confidence:
        label = f"{label} ⚠"
    tip_key = "score_clip_tip" if clip_mode else "score_similarity_tip"
    tip_template = texts.get(tip_key, "")
    tooltip = ""
    if tip_template:
        confidence_tip = texts.get("score_clip_confidence_tip", "")
        tier_key = resolve_clip_confidence_tier_key(score)
        tier_label = texts.get(tier_key, "")
        tooltip = tip_template.format(score=float(score), percent=format_clip_score_percent(score))
        if clip_mode and confidence_tip and tier_label:
            tooltip = f"{tooltip}\n{confidence_tip.format(level=tier_label)}"
    return label, tooltip


def _video_cell_parts(
    *,
    base_name: str,
    video_path: str,
    match_kind: str,
    matched_text: str,
    highlight_query: str,
    dialogue_match_mode: str,
) -> tuple[str, str, str]:
    """Return (plain_text, optional_html, tooltip)."""
    query = str(highlight_query or "").strip()
    mode = str(dialogue_match_mode or "").strip().lower()
    kind = str(match_kind or "frame")
    matched = str(matched_text or "").strip()

    if kind == "tags" and matched and query:
        html = highlight_dialogue_html(
            matched,
            query,
            match_mode=mode or "exact",
            max_len=72,
        )
        wrapped = (
            "<div style='text-align:center;line-height:1.25'>"
            f"{html}"
            "</div>"
        )
        return "", wrapped, f"{video_path}\n\n{matched}"
    if kind == "tags" and matched:
        snippet = matched if len(matched) <= 72 else f"{matched[:71]}…"
        return snippet, "", f"{video_path}\n\n{matched}"
    if kind == "dialogue" and matched and query:
        html = highlight_dialogue_html(
            matched,
            query,
            match_mode=mode or "fuzzy",
            max_len=40,
        )
        wrapped = (
            "<div style='text-align:center'>"
            f"<div>{_escape_html(base_name)}</div>"
            f"<div style='margin-top:2px;line-height:1.25'>{html}</div>"
            "</div>"
        )
        return "", wrapped, f"{video_path}\n\n{matched}"
    if kind == "dialogue" and matched:
        snippet = matched if len(matched) <= 40 else f"{matched[:39]}…"
        return f"{base_name}\n{snippet}", "", f"{video_path}\n\n{matched}"
    return base_name, "", video_path


def group_badge_text(hit, texts: dict) -> str:
    kind = str(getattr(hit, "group_kind", "") or "")
    count = int(getattr(hit, "member_count", 1) or 1)
    if kind == "cross":
        template = str(texts.get("search_group_cross") or "跨集 · {count}")
    else:
        template = str(texts.get("search_group_near") or "邻近 · {count}")
    try:
        return template.format(count=count)
    except (KeyError, IndexError, ValueError):
        return template


def group_subtitle_text(hit, texts: dict) -> str:
    if str(getattr(hit, "group_kind", "") or "") != "cross":
        return ""
    unique = int(getattr(hit, "unique_videos", 1) or 1)
    if unique <= 1:
        return ""
    template = str(texts.get("search_group_cross_more") or "{name} · {count}")
    try:
        return template.format(name=str(getattr(hit, "lead_name", "") or ""), count=unique)
    except (KeyError, IndexError, ValueError):
        return template


def build_result_row(
    raw,
    *,
    rank: int,
    texts: dict,
    clip_score_mode: bool = False,
    low_confidence: bool = False,
    highlight_query: str = "",
    dialogue_match_mode: str = "",
) -> dict[str, Any]:
    hit = coerce_search_hit(raw)
    match_kind = str(getattr(hit, "match_kind", "frame") or "frame")
    matched_text = str(getattr(hit, "matched_text", "") or "").strip()
    base_name = video_display_name(hit.video_path)
    video_text, video_html, video_tip = _video_cell_parts(
        base_name=base_name,
        video_path=str(hit.video_path or ""),
        match_kind=match_kind,
        matched_text=matched_text,
        highlight_query=highlight_query,
        dialogue_match_mode=dialogue_match_mode,
    )
    score_text, score_tip = _score_display(
        float(hit.score),
        texts,
        clip_mode=clip_score_mode,
        low_confidence=low_confidence,
    )
    range_tip = matched_text if match_kind in {"dialogue", "tags"} and matched_text else ""
    show_badge = bool(getattr(hit, "show_badge", False))
    badge = group_badge_text(hit, texts) if show_badge else ""
    subtitle = group_subtitle_text(hit, texts) if show_badge else ""
    if badge and not getattr(hit, "is_representative", True):
        show_badge = False
        badge = ""
    video_tip = video_tip if not subtitle else f"{video_tip}\n{subtitle}"
    order_text = str(int(rank))
    display_rank = int(getattr(hit, "display_rank", 0) or 0)
    if display_rank > 0:
        order_text = str(display_rank)
    raw_group_id = getattr(hit, "group_id", None)
    group_id = -1 if raw_group_id is None else int(raw_group_id)
    if group_id >= 0 and not bool(getattr(hit, "is_representative", True)):
        order_text = "└"
    return {
        "rank": int(rank),
        "start_sec": float(hit.start_sec),
        "preview_sec": float(hit.peak_sec) if getattr(hit, "peak_sec", None) is not None else float(hit.start_sec),
        "end_sec": float(hit.end_sec),
        "score": float(hit.score),
        "video_path": str(hit.video_path or ""),
        "match_kind": match_kind,
        "matched_text": matched_text,
        "order_text": order_text,
        "video_text": video_text,
        "video_html": video_html,
        "video_tip": video_tip,
        "range_text": format_time_range(
            float(hit.start_sec), float(hit.end_sec), texts, match_kind=match_kind
        ),
        "range_tip": range_tip,
        "mode_text": result_mode_label(
            float(hit.start_sec), float(hit.end_sec), texts, match_kind=match_kind
        ),
        "mode_tip": range_tip,
        "score_text": score_text,
        "score_tip": score_tip,
        "thumb": None,
        "low_confidence": bool(low_confidence),
        "group_id": group_id,
        "group_member_count": int(getattr(hit, "member_count", 1) or 1),
        "group_is_representative": bool(getattr(hit, "is_representative", True)),
        "group_show_badge": bool(show_badge and badge),
        "group_badge": badge,
        "group_subtitle": subtitle,
    }


class SearchResultTableModel(QAbstractTableModel):
    """One search hit per row; no per-row QWidget until a delegate asks for an editor."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._headers: list[str] = ["", "", "", "", "", "", ""]
        self._texts: dict = {}
        self._thumb_loading = "…"
        self._on_preview: Callable | None = None
        self._on_locate: Callable | None = None
        self._on_export: Callable | None = None
        self._on_deep_locate: Callable | None = None
        self._on_add_to_shot_list: Callable | None = None

    # --- configuration -------------------------------------------------

    def set_headers(self, labels: list[str] | None) -> None:
        next_headers = [str(x) for x in (labels or [])]
        while len(next_headers) < self.columnCount():
            next_headers.append("")
        next_headers = next_headers[: self.columnCount()]
        if next_headers == self._headers:
            return
        self._headers = next_headers
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)

    def set_texts(self, texts: dict | None) -> None:
        self._texts = dict(texts or {})
        self._thumb_loading = str(self._texts.get("thumb_loading") or "…")

    @property
    def texts(self) -> dict:
        return self._texts

    @property
    def thumb_loading_text(self) -> str:
        return self._thumb_loading

    def set_action_handlers(
        self,
        *,
        on_preview=None,
        on_locate=None,
        on_export=None,
        on_deep_locate=None,
        on_add_to_shot_list=None,
    ) -> None:
        self._on_preview = on_preview
        self._on_locate = on_locate
        self._on_export = on_export
        self._on_deep_locate = on_deep_locate
        self._on_add_to_shot_list = on_add_to_shot_list

    def action_handlers(self) -> dict:
        return {
            "on_preview": self._on_preview,
            "on_locate": self._on_locate,
            "on_export": self._on_export,
            "on_deep_locate": self._on_deep_locate,
            "on_add_to_shot_list": self._on_add_to_shot_list,
        }

    # --- bulk updates --------------------------------------------------

    def clear_rows(self) -> None:
        self.beginResetModel()
        self._rows = []
        self.endResetModel()

    def set_hits(
        self,
        results,
        *,
        texts: dict,
        rank_offset: int = 0,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
        highlight_query: str = "",
        dialogue_match_mode: str = "",
    ) -> None:
        self.set_texts(texts)
        rows: list[dict[str, Any]] = []
        for offset, raw in enumerate(results or []):
            low_confidence = (
                low_confidence_score is not None
                and rank_offset + offset == 0
                and float(coerce_search_hit(raw).score) < float(low_confidence_score)
            )
            rows.append(
                build_result_row(
                    raw,
                    rank=rank_offset + offset + 1,
                    texts=self._texts,
                    clip_score_mode=clip_score_mode,
                    low_confidence=low_confidence,
                    highlight_query=highlight_query,
                    dialogue_match_mode=dialogue_match_mode,
                )
            )
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def append_hits(
        self,
        results,
        *,
        texts: dict | None = None,
        rank_offset: int = 0,
        clip_score_mode: bool = False,
        low_confidence_score: float | None = None,
        highlight_query: str = "",
        dialogue_match_mode: str = "",
    ) -> None:
        if texts is not None:
            self.set_texts(texts)
        rows = list(results or [])
        if not rows:
            return
        start = len(self._rows)
        built: list[dict[str, Any]] = []
        for offset, raw in enumerate(rows):
            low_confidence = (
                low_confidence_score is not None
                and rank_offset + offset == 0
                and float(coerce_search_hit(raw).score) < float(low_confidence_score)
            )
            built.append(
                build_result_row(
                    raw,
                    rank=rank_offset + offset + 1,
                    texts=self._texts,
                    clip_score_mode=clip_score_mode,
                    low_confidence=low_confidence,
                    highlight_query=highlight_query,
                    dialogue_match_mode=dialogue_match_mode,
                )
            )
        self.beginInsertRows(QModelIndex(), start, start + len(built) - 1)
        self._rows.extend(built)
        self.endInsertRows()

    def set_thumbnail(self, row: int, pixmap) -> None:
        if row < 0 or row >= len(self._rows):
            return
        if pixmap is None or (isinstance(pixmap, QPixmap) and pixmap.isNull()):
            self._rows[row]["thumb"] = None
        else:
            self._rows[row]["thumb"] = pixmap
        index = self.index(row, int(LocalSearchCol.PREVIEW))
        self.dataChanged.emit(index, index, [ThumbRole, Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.DecorationRole])

    def row_dict(self, row: int) -> dict[str, Any] | None:
        if row < 0 or row >= len(self._rows):
            return None
        return self._rows[row]

    # --- QAbstractTableModel -------------------------------------------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 7

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if orientation != Qt.Orientation.Horizontal:
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            if 0 <= section < len(self._headers):
                return self._headers[section]
            return ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        return None

    def flags(self, index: QModelIndex):  # noqa: N802
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        # Persistent action editors need the editable flag.
        if index.column() == int(LocalSearchCol.ACTIONS):
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._rows):
            return None
        ent = self._rows[row]
        col = index.column()

        if role == HitPayloadRole and col == int(LocalSearchCol.ORDER):
            return {
                "video_path": ent["video_path"],
                "start_sec": float(ent["start_sec"]),
                "end_sec": float(ent["end_sec"]),
                "preview_sec": float(ent.get("preview_sec", ent["start_sec"])),
                "score": float(ent["score"]),
                "match_kind": ent["match_kind"],
                "matched_text": ent["matched_text"],
            }
        if role == GroupMetaRole:
            stored_group = ent.get("group_id", -1)
            group_id = -1 if stored_group is None else int(stored_group)
            return {
                "group_id": group_id,
                "show_badge": bool(ent.get("group_show_badge")),
                "badge": str(ent.get("group_badge") or ""),
                "subtitle": str(ent.get("group_subtitle") or ""),
                "member": group_id >= 0 and not bool(ent.get("group_is_representative", True)),
            }
        if role == ThumbRole and col == int(LocalSearchCol.PREVIEW):
            return ent.get("thumb")
        if role == VideoHtmlRole and col == int(LocalSearchCol.VIDEO):
            return ent.get("video_html") or ""
        if role == Qt.ItemDataRole.UserRole and col == int(LocalSearchCol.ACTIONS):
            return dict(ent)

        if role == Qt.ItemDataRole.DisplayRole:
            if col == int(LocalSearchCol.ORDER):
                return ent["order_text"]
            if col == int(LocalSearchCol.PREVIEW):
                thumb = ent.get("thumb")
                if thumb is None or (isinstance(thumb, QPixmap) and thumb.isNull()):
                    return self._thumb_loading
                return ""
            if col == int(LocalSearchCol.VIDEO):
                return ent["video_text"]
            if col == int(LocalSearchCol.RANGE):
                return ent["range_text"]
            if col == int(LocalSearchCol.MODE):
                return ent["mode_text"]
            if col == int(LocalSearchCol.SCORE):
                return ent["score_text"]
            if col == int(LocalSearchCol.ACTIONS):
                return ""
        if role == Qt.ItemDataRole.ToolTipRole:
            if col == int(LocalSearchCol.VIDEO):
                tip = str(ent.get("video_tip") or "")
                subtitle = str(ent.get("group_subtitle") or "")
                if subtitle and subtitle not in tip:
                    tip = f"{tip}\n{subtitle}" if tip else subtitle
                return tip
            if col == int(LocalSearchCol.RANGE):
                return ent.get("range_tip") or ""
            if col == int(LocalSearchCol.MODE):
                return ent.get("mode_tip") or ""
            if col == int(LocalSearchCol.SCORE):
                return ent.get("score_tip") or ""
            if col == int(LocalSearchCol.ORDER):
                return ent.get("video_path") or ""
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return int(Qt.AlignmentFlag.AlignCenter)
        if role == Qt.ItemDataRole.DecorationRole and col == int(LocalSearchCol.PREVIEW):
            thumb = ent.get("thumb")
            if isinstance(thumb, QPixmap) and not thumb.isNull():
                return thumb
        return None
