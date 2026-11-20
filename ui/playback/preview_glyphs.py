"""Icon-only transport buttons for the preview chrome."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QPushButton, QStyle, QStyleOptionButton

from ui.widgets.button_roles import set_button_role
from ui.widgets.styles import repolish_widget

_GLYPHS = frozenset(
    {"play", "pause", "continue", "replay", "clear", "fullscreen", "exit_fullscreen"}
)
_ACTIVE_GLYPHS = frozenset({"pause", "exit_fullscreen"})


def _theme_colors():
    from PySide6.QtWidgets import QApplication

    from ui.widgets.styles import theme_color_map

    app = QApplication.instance()
    is_dark = False
    if app is not None:
        prop = app.property("videoseek_is_dark")
        if prop is None:
            is_dark = app.palette().color(app.palette().ColorRole.Window).lightness() < 128
        else:
            is_dark = bool(prop)
    return theme_color_map(is_dark)


def _glyph_ink(button: QPushButton) -> QColor:
    colors = _theme_colors()
    if not button.isEnabled():
        key = "MUTED"
    elif button.isDown() or str(button.property("active") or "") == "true":
        key = "ACCENT"
    elif button.underMouse():
        key = "HEADLINE"
    else:
        key = "HEADLINE"
    return QColor(str(colors.get(key) or colors.get("TEXT") or "#3d3d3d"))


def _glyph_center(rect: QRect) -> tuple[float, float, float]:
    side = float(min(rect.width(), rect.height()))
    return (
        rect.x() + rect.width() / 2.0,
        rect.y() + rect.height() / 2.0,
        side / 28.0,
    )


def _paint_glyph(painter: QPainter, rect: QRect, color: QColor, kind: str) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    cx, cy, s = _glyph_center(rect)
    if kind == "play":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        path = QPainterPath()
        path.moveTo(cx - 3.4 * s, cy - 5.4 * s)
        path.lineTo(cx - 3.4 * s, cy + 5.4 * s)
        path.lineTo(cx + 6.2 * s, cy)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "pause":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(cx - 4.4 * s, cy - 5.4 * s, 2.8 * s, 10.8 * s), 0.9 * s, 0.9 * s)
        painter.drawRoundedRect(QRectF(cx + 1.6 * s, cy - 5.4 * s, 2.8 * s, 10.8 * s), 0.9 * s, 0.9 * s)
    elif kind == "continue":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        path = QPainterPath()
        path.moveTo(cx - 5.4 * s, cy - 5.4 * s)
        path.lineTo(cx - 5.4 * s, cy + 5.4 * s)
        path.lineTo(cx + 3.4 * s, cy)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawRoundedRect(QRectF(cx + 4.4 * s, cy - 5.4 * s, 1.8 * s, 10.8 * s), 0.7 * s, 0.7 * s)
    elif kind == "replay":
        radius = 5.2 * s
        pen = QPen(
            color,
            1.7 * s,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        box = QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0)
        ring = QPainterPath()
        ring.arcMoveTo(box, 50)
        ring.arcTo(box, 50, 268)
        painter.strokePath(ring, pen)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        tip = QPainterPath()
        tip.moveTo(cx + 0.2 * s, cy - 7.0 * s)
        tip.lineTo(cx + 4.4 * s, cy - 5.2 * s)
        tip.lineTo(cx + 0.2 * s, cy - 3.4 * s)
        tip.closeSubpath()
        painter.drawPath(tip)
    elif kind == "clear":
        painter.translate(cx, cy)
        painter.rotate(36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(-1.0 * s, -7.0 * s, 2.0 * s, 8.6 * s), 1.0 * s, 1.0 * s)
        painter.drawRoundedRect(QRectF(-2.8 * s, 1.0 * s, 5.6 * s, 1.5 * s), 0.6 * s, 0.6 * s)
        for x in (-3.8, -1.7, 0.4, 2.5):
            painter.drawRoundedRect(QRectF(x * s, 2.2 * s, 1.5 * s, 5.2 * s), 0.6 * s, 0.6 * s)
    elif kind in {"fullscreen", "exit_fullscreen"}:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                color,
                1.55 * s,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.SquareCap,
                Qt.PenJoinStyle.MiterJoin,
            )
        )
        inset, arm = 3.3 * s, 2.2 * s
        corners = ((-inset, -inset), (inset, -inset), (-inset, inset), (inset, inset))
        for sx, sy in corners:
            ox, oy = cx + sx, cy + sy
            if kind == "fullscreen":
                hx = arm if sx > 0 else -arm
                vy = arm if sy > 0 else -arm
            else:
                hx = -arm if sx > 0 else arm
                vy = -arm if sy > 0 else arm
            painter.drawLine(QLineF(ox, oy, ox + hx, oy))
            painter.drawLine(QLineF(ox, oy, ox, oy + vy))
    painter.restore()


class PreviewGlyphButton(QPushButton):
    """28px Ghost pill. The tooltip keeps the word."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        if kind not in _GLYPHS:
            raise ValueError(f"unknown preview glyph: {kind!r}")
        self._kind = kind
        set_button_role(self, "GhostButton", chrome="previewIcon")
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._sync_active()

    def glyph(self) -> str:
        return self._kind

    def set_glyph(self, kind: str) -> None:
        if kind not in _GLYPHS:
            raise ValueError(f"unknown preview glyph: {kind!r}")
        if kind == self._kind:
            return
        self._kind = kind
        self._sync_active()
        self.update()

    def _sync_active(self) -> None:
        active = "true" if self._kind in _ACTIVE_GLYPHS else "false"
        if str(self.property("active") or "") == active:
            return
        self.setProperty("active", active)
        repolish_widget(self)

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        _paint_glyph(painter, option.rect, _glyph_ink(self), self._kind)
        painter.end()
