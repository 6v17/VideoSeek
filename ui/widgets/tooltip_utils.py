"""Wrap Qt tooltips so long / CJK text is not clipped by styled QToolTip."""

from __future__ import annotations

from html import escape

from PySide6.QtGui import QStandardItem
from PySide6.QtWidgets import QListWidgetItem, QTableWidgetItem, QTreeWidgetItem, QWidget

_DEFAULT_WIDTH_PX = 360
_WRAPPED_MARK = "data-videoseek-tooltip=\"1\""


def format_wrapped_tooltip(text: str | None, *, width: int = _DEFAULT_WIDTH_PX) -> str:
    """Return rich-text tooltip that wraps within ``width`` (incl. CJK)."""
    raw = str(text or "")
    if not raw:
        return ""
    stripped = raw.lstrip().lower()
    if _WRAPPED_MARK in raw or stripped.startswith("<qt") or stripped.startswith("<html"):
        return raw
    body = escape(raw).replace("\n", "<br/>")
    return (
        f"<qt {_WRAPPED_MARK}>"
        f'<p style="max-width:{int(width)}px; white-space:pre-wrap; margin:0;">'
        f"{body}</p></qt>"
    )


def _patch_set_tooltip(cls, *, has_column: bool) -> None:
    if getattr(cls, "_videoseek_tooltip_wrapped", False):
        return
    original = cls.setToolTip

    if has_column:

        def setToolTip(self, column, text):  # noqa: N802 - Qt API
            original(self, column, format_wrapped_tooltip(text))

    else:

        def setToolTip(self, text):  # noqa: N802 - Qt API
            original(self, format_wrapped_tooltip(text))

    cls.setToolTip = setToolTip
    cls._videoseek_tooltip_wrapped = True


def install_wrapped_tooltips() -> None:
    """Patch common setToolTip entry points once per process."""
    _patch_set_tooltip(QWidget, has_column=False)
    _patch_set_tooltip(QTreeWidgetItem, has_column=True)
    _patch_set_tooltip(QTableWidgetItem, has_column=False)
    _patch_set_tooltip(QListWidgetItem, has_column=False)
    _patch_set_tooltip(QStandardItem, has_column=False)
