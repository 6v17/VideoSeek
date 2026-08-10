"""Fluent busy / progress dialog (replaces native QProgressDialog chrome)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QProgressBar

from ui.dialogs.shell import VSDialogShell
from ui.widgets.layout import COMPONENT_SIZES


class AppBusyDialog(VSDialogShell):
    """Modal progress shell with title + status text + progress bar; no cancel."""

    def __init__(
        self,
        parent=None,
        *,
        title: str = "",
        label: str = "",
        maximum: int = 0,
        minimum_width: int = 420,
    ):
        super().__init__(
            parent,
            title=str(title or ""),
            body=str(label or ""),
            minimum_width=int(minimum_width),
            card_margins=(20, 18, 20, 18),
            card_spacing=14,
        )
        self._allow_close = False
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setObjectName("AppBusyDialog")
        # Hide title-bar close; Esc is ignored in reject().
        flags = self.windowFlags()
        flags &= ~Qt.WindowType.WindowCloseButtonHint
        flags &= ~Qt.WindowType.WindowContextHelpButtonHint
        self.setWindowFlags(flags)
        self._footer.hide()

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("DialogBusyProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(
            max(8, int(COMPONENT_SIZES.get("progress_bar_height", 18)) - 6)
        )
        self.content_layout.addWidget(self.progress_bar)
        self.setRange(0, int(maximum or 0))

    def setLabelText(self, text: str) -> None:
        """QProgressDialog-compatible status update."""
        self.set_body(str(text or ""))

    def set_status(self, text: str) -> None:
        self.setLabelText(text)

    def setRange(self, minimum: int, maximum: int) -> None:
        lo = int(minimum or 0)
        hi = int(maximum or 0)
        if hi <= lo:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(lo, hi)

    def setValue(self, value: int) -> None:
        if self.progress_bar.maximum() <= self.progress_bar.minimum():
            return
        self.progress_bar.setValue(max(0, int(value)))

    def value(self) -> int:
        return int(self.progress_bar.value())

    def maximum(self) -> int:
        return int(self.progress_bar.maximum())

    def reject(self) -> None:
        if self._allow_close:
            super().reject()

    def accept(self) -> None:
        if self._allow_close:
            super().accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            super().closeEvent(event)
            return
        event.ignore()

    def close(self) -> bool:
        self._allow_close = True
        self.hide()
        return super().close()
