"""Shared keyboard helpers for preview play/pause and seek nudges."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

# Single tap: coarse jump. Hold: smaller steps on a steady timer (not OS auto-repeat).
DEFAULT_SEEK_STEP_MS = 3000
DEFAULT_HOLD_SEEK_STEP_MS = 500
DEFAULT_HOLD_TICK_MS = 100


def focus_blocks_preview_keys(widget: QWidget | None) -> bool:
    """Return True when Space/arrows should stay with the focused editor widget."""
    current = widget
    while current is not None:
        if bool(current.property("previewKeyboardPassthrough")):
            return True
        if isinstance(current, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)):
            return True
        if isinstance(current, QComboBox) and current.isEditable():
            return True
        if current.isWindow() and current is not widget:
            break
        current = current.parentWidget()
    return False


def clamp_seek_ms(current_ms: int, delta_ms: int, total_ms: int = 0) -> int:
    target = max(0, int(current_ms) + int(delta_ms))
    if int(total_ms) > 0:
        target = min(target, int(total_ms))
    return target


def resolve_seek_base_ms(player_time_ms: int, pending_ui_seek_ms: int | None) -> int:
    """Prefer in-flight UI seek target so rapid/hold nudges accumulate correctly."""
    if pending_ui_seek_ms is not None:
        return max(0, int(pending_ui_seek_ms))
    return max(0, int(player_time_ms))


def resolve_display_time_ms(current_ms: int, pending_ui_seek_ms: int | None) -> tuple[int, int | None]:
    """Map player clock + pending seek to a stable UI time.

    Returns ``(display_ms, updated_pending)``. Cleared pending means the player
    has caught up; otherwise keep showing / seeking from the pending target.
    """
    if pending_ui_seek_ms is None:
        return max(0, int(current_ms)), None
    current_ms = max(0, int(current_ms))
    pending = int(pending_ui_seek_ms)
    if abs(current_ms - pending) <= 800 or current_ms > pending:
        return current_ms, None
    # VLC often reports ~0 while a deep seek is still applying.
    return pending, pending


class PreviewTransportKeyFilter(QObject):
    """Strong-bind Space / Left / Right while a preview session is active.

    Installed on QApplication so Space is not swallowed by a focused QPushButton.
    Arrow hold uses an internal timer — OS auto-repeat is ignored (too bursty and
    fights in-flight VLC seeks).
    """

    def __init__(
        self,
        host: QWidget,
        *,
        is_active: Callable[[], bool],
        on_toggle: Callable[[], None],
        on_seek: Callable[[int], None],
        seek_step_ms: int = DEFAULT_SEEK_STEP_MS,
        hold_seek_step_ms: int = DEFAULT_HOLD_SEEK_STEP_MS,
        hold_tick_ms: int = DEFAULT_HOLD_TICK_MS,
        parent: QObject | None = None,
    ):
        super().__init__(parent or host)
        self._host = host
        self._is_active = is_active
        self._on_toggle = on_toggle
        self._on_seek = on_seek
        self._seek_step_ms = int(seek_step_ms)
        self._hold_seek_step_ms = int(hold_seek_step_ms)
        self._held_dir = 0
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(max(30, int(hold_tick_ms)))
        self._hold_timer.timeout.connect(self._on_hold_tick)

    def _stop_hold(self) -> None:
        self._held_dir = 0
        if self._hold_timer.isActive():
            self._hold_timer.stop()

    def _on_hold_tick(self) -> None:
        if self._held_dir == 0 or not self._can_handle_transport():
            self._stop_hold()
            return
        self._on_seek(self._held_dir * self._hold_seek_step_ms)

    def _can_handle_transport(self) -> bool:
        host = self._host
        if host is None:
            return False
        window = host.window()
        if window is None or not window.isVisible():
            return False
        active = QApplication.activeWindow()
        if active is not None and window is not active:
            return False
        if not self._is_active():
            return False
        if focus_blocks_preview_keys(QApplication.focusWidget()):
            return False
        return True

    def eventFilter(self, watched, event):  # noqa: N802
        if event is None:
            return False
        etype = event.type()
        if etype not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        key = event.key()
        if key not in (Qt.Key.Key_Space, Qt.Key.Key_Left, Qt.Key.Key_Right):
            return False

        if etype == QEvent.Type.KeyRelease:
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not event.isAutoRepeat():
                if self._held_dir != 0:
                    self._stop_hold()
                    return True
            return False

        if not self._can_handle_transport():
            return False

        if key == Qt.Key.Key_Space:
            if event.isAutoRepeat():
                return True
            self._on_toggle()
            return True

        # Ignore OS auto-repeat; continuous scrub is owned by _hold_timer.
        if event.isAutoRepeat():
            return True

        direction = -1 if key == Qt.Key.Key_Left else 1
        self._on_seek(direction * self._seek_step_ms)
        self._held_dir = direction
        if not self._hold_timer.isActive():
            self._hold_timer.start()
        return True
