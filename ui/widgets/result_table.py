"""Result table factories (layouts defined in table_specs.py)."""

from ui.widgets.data_table import DataTable
from ui.widgets.table_specs import LOCAL_SEARCH_TABLE_SPEC, NETWORK_LINK_TABLE_SPEC


class ResultTable(DataTable):
    """Local vector search results (7 columns, preview column)."""

    def __init__(self, parent=None):
        super().__init__(parent, spec=LOCAL_SEARCH_TABLE_SPEC)


class LinkResultTable(DataTable):
    """Remote / network link search results (6 columns, no preview)."""

    def __init__(self, parent=None):
        super().__init__(parent, spec=NETWORK_LINK_TABLE_SPEC)
