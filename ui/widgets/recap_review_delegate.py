"""Recap review tree: clear unit / shot grouping without heavy chrome."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem


def _theme_colors() -> dict[str, str]:
    try:
        from PySide6.QtWidgets import QApplication

        from ui.widgets.styles import theme_color_map

        app = QApplication.instance()
        is_dark = True
        if app is not None:
            prop = app.property("videoseek_is_dark")
            if prop is None:
                is_dark = app.palette().color(app.palette().ColorRole.Window).lightness() < 128
            else:
                is_dark = bool(prop)
        return theme_color_map(is_dark)
    except Exception:
        return {
            "TEXT": "#e5e5e5",
            "MUTED": "#a3a3a3",
            "HEADLINE": "#ffffff",
            "ACCENT": "#60a5fa",
            "ACCENT_SOFT": "#1e3a5f",
            "BUTTON_SOFT": "#323232",
            "LINE": "#3a3a3a",
            "LINE_STRONG": "#525252",
            "FIELD": "#242424",
            "PANEL": "#2b2b2b",
        }


def _payload_kind(index: QModelIndex) -> str:
    if not index.isValid():
        return ""
    root = index.siblingAtColumn(0) if hasattr(index, "siblingAtColumn") else index.sibling(index.row(), 0)
    payload = root.data(Qt.ItemDataRole.UserRole)
    if isinstance(payload, dict):
        return str(payload.get("kind") or "")
    return ""


def _is_last_child(index: QModelIndex) -> bool:
    parent = index.parent()
    if not parent.isValid():
        return False
    model = index.model()
    if model is None:
        return False
    return index.row() == model.rowCount(parent) - 1


class RecapReviewItemDelegate(QStyledItemDelegate):
    """Unit = field band + strong rule; shot = indented + guide; selection = accent rail."""

    _UNIT_HEIGHT = 36
    _SHOT_HEIGHT = 32
    _RAIL = 3
    _SHOT_INDENT = 20
    _GUIDE_X = 14

    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        kind = _payload_kind(index)
        height = self._UNIT_HEIGHT if kind == "unit" else self._SHOT_HEIGHT
        hint.setHeight(max(int(hint.height()), height))
        return hint

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        colors = _theme_colors()
        is_unit = _payload_kind(index) == "unit"
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = bool(opt.state & QStyle.StateFlag.State_MouseOver) and not selected
        rect = opt.rect

        field = QColor(str(colors.get("FIELD") or "#242424"))
        panel = QColor(str(colors.get("PANEL") or "#2b2b2b"))
        line = QColor(str(colors.get("LINE") or "#3a3a3a"))
        line_strong = QColor(str(colors.get("LINE_STRONG") or "#525252"))
        accent = QColor(str(colors.get("ACCENT") or "#60a5fa"))
        accent_soft = QColor(str(colors.get("ACCENT_SOFT") or "#1e3a5f"))
        button_soft = QColor(str(colors.get("BUTTON_SOFT") or "#323232"))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Base fill: units sit on FIELD so the group reads as a header band.
        if selected:
            painter.fillRect(rect, accent_soft)
            painter.fillRect(QRect(rect.left(), rect.top(), self._RAIL, rect.height()), accent)
        elif is_unit:
            painter.fillRect(rect, field)
        elif hovered:
            painter.fillRect(rect, button_soft)
        else:
            painter.fillRect(rect, panel)

        # Group rules: strong top edge on each unit; solid bottom on last shot / unit.
        if is_unit:
            painter.fillRect(QRect(rect.left(), rect.top(), rect.width(), 2), line_strong)
            painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1), line)
        else:
            # Nested guide under column 0 area.
            if index.column() == 0:
                gx = rect.left() + self._GUIDE_X
                painter.setPen(QPen(line_strong, 1))
                painter.drawLine(gx, rect.top(), gx, rect.bottom() if not _is_last_child(index) else rect.center().y())
                painter.drawLine(gx, rect.center().y(), gx + 10, rect.center().y())
            if _is_last_child(index):
                painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 2), line_strong)
            else:
                painter.fillRect(QRect(rect.left(), rect.bottom(), rect.width(), 1), line)

        font = QFont(opt.font)
        font.setPointSizeF(opt.font.pointSizeF())
        if is_unit:
            font.setWeight(QFont.Weight.DemiBold if index.column() == 0 else QFont.Weight.Normal)
            text_color = QColor(str(colors.get("HEADLINE") if index.column() == 0 else colors.get("TEXT") or "#e5e5e5"))
        else:
            font.setWeight(QFont.Weight.Normal)
            text_color = QColor(
                str(
                    colors.get("TEXT")
                    if index.column() == 0
                    else colors.get("MUTED") or "#a3a3a3"
                )
            )
        if selected:
            text_color = QColor(str(colors.get("HEADLINE") or "#ffffff"))

        left_pad = 10 + (self._RAIL if selected else 0)
        if not is_unit:
            left_pad += self._SHOT_INDENT
        text_rect = rect.adjusted(left_pad, 0, -10, 0)
        painter.setFont(font)
        painter.setPen(text_color)
        elided = painter.fontMetrics().elidedText(
            str(opt.text or ""),
            Qt.TextElideMode.ElideRight,
            max(0, text_rect.width()),
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            elided,
        )
        painter.restore()
