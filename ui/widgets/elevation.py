"""Limited drop shadows for surfaces that sit above the window."""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect

_SHADOWS = {
    1: (8, (0, 1), 38),
    2: (16, (0, 3), 55),
    3: (28, (0, 6), 75),
}


def apply_elevation(widget, level: int = 1) -> bool:
    """Attach a drop shadow. Returns False when the widget already has an effect."""
    if widget is None or widget.graphicsEffect() is not None:
        return False
    blur, (dx, dy), alpha = _SHADOWS.get(level, _SHADOWS[1])
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(dx, dy)
    effect.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(effect)
    return True
