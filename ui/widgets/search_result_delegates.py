"""Delegates for virtualized search-result QTableView.

- Thumb: paints fitted pixmap (no QLabel per row)
- Video: paints optional rich-text HTML for dialogue/tag hits
- Actions: createEditor builds real QPushButtons only when the view opens a
  persistent editor for a visible row (off-screen rows stay widget-free)
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap, QTextDocument
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from ui.views.table_views import _build_result_actions
from ui.widgets.search_result_table_model import ThumbRole, VideoHtmlRole
from ui.widgets.table_specs import LocalSearchCol
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
    return {"FIELD": "#242424", "LINE": "#454545", "MUTED": "#a3a3a3", "TEXT": "#e5e5e5"}


class SearchResultThumbDelegate(QStyledItemDelegate):
    """Paint preview frames; loading placeholder when no pixmap yet."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
        self.initStyleOption(option, index)
        painter.save()
        if option.state & QStyle.StateFlag.State_Selected:
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

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: N802
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
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
