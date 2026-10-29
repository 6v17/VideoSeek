"""Delegates for virtualized search-result QTableView.

- Thumb: paints fitted pixmap (no QLabel per row)
- Video: paints optional rich-text HTML for dialogue/tag hits
- Actions: createEditor builds real QPushButtons only when the view opens a
  persistent editor for a visible row (off-screen rows stay widget-free)
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap, QTextDocument
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui.views.table_views import _build_result_actions
from ui.widgets.search_result_table_model import GroupMetaRole, ThumbRole, VideoHtmlRole
from ui.widgets.thumb_cell import fit_thumb_pixmap


def _theme_colors() -> dict:
    try:
        from PySide6.QtWidgets import QApplication

        from ui.widgets.styles import THEME_COLORS_DARK, THEME_COLORS_LIGHT

        app = QApplication.instance()
        if app is not None:
            bg = app.palette().color(app.palette().ColorRole.Window)
            return THEME_COLORS_DARK if bg.lightness() < 128 else THEME_COLORS_LIGHT
    except Exception:
        pass
    return {"FIELD": "#242424", "LINE": "#454545", "MUTED": "#a3a3a3", "TEXT": "#e5e5e5", "ACCENT": "#0078d4"}


def _accent_color() -> QColor:
    return QColor(str(_theme_colors().get("ACCENT") or "#0078d4"))


def _member_wash() -> QColor:
    color = QColor(_accent_color())
    color.setAlpha(46)
    return color


def paint_member_wash(painter: QPainter, rect: QRect, *, selected: bool, palette) -> None:
    """Tint an expanded duplicate row so it is not another ordinary hit."""
    if selected:
        painter.fillRect(rect, palette.highlight())
        return
    painter.fillRect(rect, _member_wash())
    painter.fillRect(QRect(rect.left(), rect.top(), 3, rect.height()), _accent_color())


def group_badge_chip_rect(cell: QRect, badge: str, metrics) -> QRect:
    text_w = metrics.horizontalAdvance(str(badge or ""))
    name_h = metrics.height()
    chip_w = min(max(1, cell.width() - 16), text_w + 16)
    chip_h = min(name_h + 4, max(1, cell.height() - name_h - 12))
    return QRect(cell.left() + 8, cell.top() + 8 + name_h + 2, chip_w, chip_h)


class SearchResultPlainDelegate(QStyledItemDelegate):
    """Default cells. Expanded group members get a wash instead of a plain row."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        meta = index.data(GroupMetaRole) or {}
        if not isinstance(meta, dict) or not meta.get("member"):
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, index)
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        paint_member_wash(painter, option.rect, selected=selected, palette=option.palette)
        painter.setPen(option.palette.highlightedText().color() if selected else option.palette.text().color())
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.drawText(
            option.rect.adjusted(10, 0, -8, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, max(1, option.rect.width() - 18)),
        )
        painter.restore()


class SearchResultThumbDelegate(QStyledItemDelegate):
    """Paint preview frames; loading placeholder when no pixmap yet."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        self.initStyleOption(option, index)
        painter.save()
        meta = index.data(GroupMetaRole) or {}
        member = isinstance(meta, dict) and bool(meta.get("member"))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if member:
            paint_member_wash(painter, option.rect, selected=selected, palette=option.palette)
        elif selected:
            painter.fillRect(option.rect, option.palette.highlight())
        colors = _theme_colors()
        margin = 6
        box = option.rect.adjusted(margin, margin, -margin, -margin)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QColor(str(colors.get("LINE") or "#454545")))
        painter.setBrush(QColor(str(colors.get("FIELD") or "#242424")))
        painter.drawRoundedRect(box, 6, 6)

        thumb = index.data(ThumbRole)
        if isinstance(thumb, QPixmap) and not thumb.isNull():
            fitted = fit_thumb_pixmap(thumb, max(1, box.width() - 4), max(1, box.height() - 4))
            x = box.x() + (box.width() - fitted.width() // max(1, int(fitted.devicePixelRatio() or 1))) // 2
            y = box.y() + (box.height() - fitted.height() // max(1, int(fitted.devicePixelRatio() or 1))) // 2
            # devicePixelRatio-aware target size in logical pixels
            dpr = float(fitted.devicePixelRatio() or 1.0)
            logical_w = int(round(fitted.width() / dpr))
            logical_h = int(round(fitted.height() / dpr))
            x = box.x() + max(0, (box.width() - logical_w) // 2)
            y = box.y() + max(0, (box.height() - logical_h) // 2)
            painter.drawPixmap(x, y, logical_w, logical_h, fitted)
        else:
            text = str(index.data(Qt.ItemDataRole.DisplayRole) or "—")
            painter.setPen(QColor(str(colors.get("MUTED") or "#a3a3a3")))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:  # noqa: N802
        del index
        return QSize(max(120, option.rect.width()), max(56, option.rect.height()))


class SearchResultVideoDelegate(QStyledItemDelegate):
    """Plain text by default; rich HTML for dialogue/tag highlight rows."""

    group_toggle_requested = Signal(int)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        meta = index.data(GroupMetaRole) or {}
        if isinstance(meta, dict) and meta.get("member"):
            self._paint_member_name(painter, option, index)
            return
        if isinstance(meta, dict) and meta.get("show_badge") and meta.get("badge"):
            self._paint_grouped_name(painter, option, index, str(meta.get("badge") or ""))
            return
        html = index.data(VideoHtmlRole)
        if not html:
            super().paint(painter, option, index)
            return
        self.initStyleOption(option, index)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        doc = QTextDocument()
        doc.setHtml(str(html))
        doc.setTextWidth(max(1, option.rect.width() - 8))
        painter.translate(option.rect.x() + 4, option.rect.y() + max(0, (option.rect.height() - doc.size().height()) / 2))
        doc.drawContents(painter)
        painter.restore()

    def _paint_member_name(self, painter: QPainter, option, index) -> None:
        self.initStyleOption(option, index)
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        paint_member_wash(painter, option.rect, selected=selected, palette=option.palette)
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.setPen(option.palette.highlightedText().color() if selected else option.palette.text().color())
        painter.drawText(
            option.rect.adjusted(12, 0, -8, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            option.fontMetrics.elidedText(name, Qt.TextElideMode.ElideMiddle, max(1, option.rect.width() - 20)),
        )
        painter.restore()

    def _paint_grouped_name(self, painter: QPainter, option, index, badge: str) -> None:
        self.initStyleOption(option, index)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillRect(option.rect, option.palette.highlight())
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        metrics = option.fontMetrics
        name_rect = QRect(option.rect.left() + 8, option.rect.top() + 6, option.rect.width() - 16, metrics.height())
        chip = group_badge_chip_rect(option.rect, badge, metrics)
        painter.setPen(option.palette.highlightedText().color() if selected else option.palette.text().color())
        painter.drawText(
            name_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, max(1, name_rect.width())),
        )
        accent = option.palette.highlightedText().color() if selected else _accent_color()
        fill = QColor(accent)
        fill.setAlpha(36 if selected else 255)
        if not selected:
            soft = QColor(str(_theme_colors().get("ACCENT_SOFT") or "#e8f3fc"))
            fill = soft
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(accent)
        painter.drawText(
            chip.adjusted(8, 0, -6, 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(badge, Qt.TextElideMode.ElideRight, max(1, chip.width() - 14)),
        )
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        del model
        meta = index.data(GroupMetaRole) or {}
        if not isinstance(meta, dict) or not meta.get("show_badge"):
            return False
        if event.type() not in {QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick}:
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        badge = str(meta.get("badge") or "")
        chip = group_badge_chip_rect(option.rect, badge, option.fontMetrics)
        if not chip.contains(pos):
            return False
        if event.type() == QEvent.Type.MouseButtonRelease:
            self.group_toggle_requested.emit(int(meta.get("group_id", -1)))
        return True


class SearchResultActionsDelegate(QStyledItemDelegate):
    """Paint empty action cells; ResultTable attaches buttons via setIndexWidget for visible rows.

    createEditor remains available as a fallback, but the live path uses setIndexWidget
    so offscreen Qt platforms still parent buttons under the viewport.
    """

    def createEditor(self, parent, option, index):  # noqa: N802
        del option
        model = index.model()
        ent = index.data(Qt.ItemDataRole.UserRole) or {}
        if not isinstance(ent, dict):
            ent = {}
        handlers = {}
        texts = {}
        if model is not None and hasattr(model, "action_handlers"):
            handlers = model.action_handlers()
            texts = dict(getattr(model, "texts", {}) or {})
        on_preview = handlers.get("on_preview") or (lambda *_a, **_k: None)
        on_locate = handlers.get("on_locate") or (lambda *_a, **_k: None)
        on_export = handlers.get("on_export") or (lambda *_a, **_k: None)
        return _build_result_actions(
            ent.get("video_path") or "",
            float(ent.get("start_sec") or 0.0),
            float(ent.get("end_sec") or 0.0),
            on_preview,
            on_locate,
            on_export,
            texts,
            match_kind=str(ent.get("match_kind") or "frame"),
            on_deep_locate=handlers.get("on_deep_locate"),
            on_add_to_shot_list=handlers.get("on_add_to_shot_list"),
            anchor_score=float(ent.get("score") or 0.0),
            preview_sec=ent.get("preview_sec"),
        )

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        del index
        editor.setGeometry(option.rect)

    def setEditorData(self, editor, index) -> None:  # noqa: N802
        del editor, index

    def setModelData(self, editor, model, index) -> None:  # noqa: N802
        del editor, model, index

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        # Persistent editors cover visible rows; for off-screen / not-yet-opened rows
        # leave the cell empty (no button forest).
        self.initStyleOption(option, index)
        meta = index.data(GroupMetaRole) or {}
        if isinstance(meta, dict) and meta.get("member"):
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            paint_member_wash(painter, option.rect, selected=selected, palette=option.palette)
            return
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
