"""Thumbnail table cell QLabel (#ThumbPreview)."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


def screen_thumb_scale() -> float:
    """Physical pixels per logical pixel, capped so a card does not decode a 4K frame."""
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return 1.0
    return min(2.0, max(1.0, float(screen.devicePixelRatio() or 1.0)))


def fit_thumb_pixmap(pixmap: QPixmap, logical_w: int, logical_h: int, dpr: float | None = None) -> QPixmap:
    """Scale for the screen so Qt does not enlarge a small bitmap on a high-DPI display."""
    if pixmap is None or pixmap.isNull():
        return pixmap
    scale = screen_thumb_scale() if dpr is None else min(2.0, max(1.0, float(dpr or 1.0)))
    target_w = max(1, int(round(max(1, logical_w) * scale)))
    target_h = max(1, int(round(max(1, logical_h) * scale)))
    scaled = pixmap.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.setDevicePixelRatio(scale)
    return scaled


def make_thumb_label(*, text: str = "", pixmap: QPixmap | None = None) -> QLabel:
    label = QLabel()
    label.setObjectName("ThumbPreview")
    label.setAlignment(Qt.AlignCenter)
    if pixmap is not None and not pixmap.isNull():
        label.setPixmap(pixmap)
    elif text:
        label.setText(text)
    return label
