"""Floating host for the search results card (detach / dock like an IDE panel)."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QDialog, QSizePolicy, QVBoxLayout, QWidget


def force_widget_foreground(widget) -> None:
    """Raise ``widget`` above other windows; Windows needs SetForegroundWindow."""
    if widget is None:
        return
    if hasattr(widget, "isMinimized") and widget.isMinimized():
        widget.showNormal()
    widget.show()
    widget.raise_()
    widget.activateWindow()
    app = QApplication.instance()
    if app is not None:
        app.setActiveWindow(widget)
    if sys.platform == "win32":
        try:
            import ctypes

            hwnd = int(widget.winId())
            user32 = ctypes.windll.user32
            # ASFW_ANY = -1: allow this process to steal foreground.
            user32.AllowSetForegroundWindow(-1)
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass


class ResultsFloatWindow(QDialog):
    """Independent window that temporarily hosts ``results_card``.

    Closing the window emits ``dock_requested`` so the owner can re-embed the card.
    The card itself is never deleted here — only reparented.
    """

    dock_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResultsFloatWindow")
        self.setWindowTitle("Results")
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setMinimumSize(720, 480)
        self.resize(960, 720)
        self._card: QWidget | None = None
        self._closing_for_dock = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(0)
        self.host = QWidget()
        self.host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.host_layout = QVBoxLayout(self.host)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setSpacing(0)
        root.addWidget(self.host, 1)

    def is_hosting(self) -> bool:
        return self._card is not None

    def take_card(self, card: QWidget) -> None:
        """Reparent ``card`` into this window (caller must remove it from prior layout)."""
        if self._card is not None and self._card is not card:
            self.release_card()
        self._card = card
        card.setParent(self.host)
        self.host_layout.addWidget(card, 1)
        card.show()

    def release_card(self) -> QWidget | None:
        """Remove the hosted card from this window without deleting it."""
        card = self._card
        self._card = None
        if card is None:
            return None
        self.host_layout.removeWidget(card)
        card.setParent(None)
        return card

    def request_dock(self) -> None:
        """Programmatic close that docks instead of discarding."""
        self._closing_for_dock = True
        self.dock_requested.emit()
        self.hide()
        self._closing_for_dock = False

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._closing_for_dock and self._card is not None:
            event.ignore()
            self.dock_requested.emit()
            return
        event.accept()
