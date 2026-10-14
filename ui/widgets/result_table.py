"""Result table factories (layouts defined in table_specs.py)."""

from PySide6.QtCore import QSize

from ui.widgets.data_table import DataTable
from ui.widgets.table_specs import LOCAL_SEARCH_TABLE_SPEC


class ResultTable(DataTable):
    """Local vector search results (7 columns, preview column)."""

    def __init__(self, parent=None):
        super().__init__(parent, spec=LOCAL_SEARCH_TABLE_SPEC)
        self.setMinimumWidth(0)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        hint = super().minimumSizeHint()
        # Fit the results pane and scroll, instead of forcing every column on screen.
        return QSize(0, hint.height())
