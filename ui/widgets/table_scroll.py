"""Wheel-delta math for DataTable. Kept Qt-free so tests can run without PySide6."""

from __future__ import annotations

# One mouse-wheel notch should move a few rows, not a whole episode of cues.
WHEEL_ROWS_PER_NOTCH = 3
WHEEL_MAX_ROWS = 4


def table_wheel_pixel_delta(pixel_y: int, angle_y: int, *, row_height: int) -> int:
    """Convert a wheel tick into pixels. Caps huge precision-touchpad bursts."""
    row = max(12, int(row_height))
    pixel = int(pixel_y or 0)
    angle = int(angle_y or 0)
    if pixel:
        delta = pixel
    elif angle:
        delta = int(round(angle / 120.0 * WHEEL_ROWS_PER_NOTCH * row))
        if delta == 0:
            delta = row if angle > 0 else -row
    else:
        return 0
    cap = WHEEL_MAX_ROWS * row
    return max(-cap, min(cap, delta))
