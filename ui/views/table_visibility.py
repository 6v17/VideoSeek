"""Helpers for visible rows in result tables."""

from __future__ import annotations

from PySide6.QtWidgets import QTableWidget


def visible_table_row_range(table: QTableWidget) -> range:
    if table is None or table.rowCount() <= 0:
        return range(0)

    top = table.rowAt(0)
    if top < 0:
        top = 0

    viewport = table.viewport()
    bottom = table.rowAt(max(0, viewport.height() - 1))
    if bottom < 0:
        bottom = table.rowCount() - 1

    bottom = min(bottom, table.rowCount() - 1)
    return range(top, bottom + 1)
