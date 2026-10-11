"""Action-button roles used across the desktop UI.

Every clickable ``QPushButton`` that is not a dialog/table helper should use one
of these objectNames. Specialized chrome (nav, wizard steps, toggles) keeps the
role objectName and sets a ``chrome`` Qt property for QSS overrides.
"""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractButton, QLineEdit, QToolButton

ACTION_ROLES = frozenset(
    {
        "PrimaryButton",
        "AccentGhostButton",
        "GhostButton",
        "DangerGhostButton",
        "SuccessGhostButton",
    }
)


def set_button_role(button: QAbstractButton, role: str, *, chrome: str = "") -> None:
    """Assign an action role objectName and optional chrome property."""
    role_name = str(role or "").strip()
    if role_name not in ACTION_ROLES:
        raise ValueError(f"unknown button role: {role_name!r}")
    button.setObjectName(role_name)
    button.setProperty("chrome", str(chrome or "").strip())


def name_line_edit_clear_button(edit: QLineEdit, object_name: str = "FieldClearButton") -> None:
    """Name Qt's built-in clear ``QToolButton`` so audits do not see an empty objectName."""
    if edit is None:
        return
    for button in edit.findChildren(QToolButton):
        if not str(button.objectName() or "").strip():
            button.setObjectName(object_name)


def name_table_corner_button(table, object_name: str = "TableCornerButton") -> None:
    """Name the QTableView top-left corner control (a bare QAbstractButton)."""
    if table is None:
        return
    for button in table.findChildren(QAbstractButton):
        if type(button) is not QAbstractButton:
            continue
        if not str(button.objectName() or "").strip():
            button.setObjectName(object_name)
