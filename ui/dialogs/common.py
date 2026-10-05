from PySide6.QtWidgets import QTableWidgetItem

from ui.widgets.styles import theme_color_map


def dialog_palette(is_dark):
    """Semantic colors aligned with `styles.THEME_COLORS_*` (for legacy callers)."""
    c = theme_color_map(is_dark)
    return {
        "bg": c["PANEL"],
        "card": c["FIELD"],
        "text": c["HEADLINE"],
        "muted": c["MUTED"],
        "accent": c["ACCENT"],
        "border": c["LINE"],
    }


class SortableTableWidgetItem(QTableWidgetItem):
    def __init__(self, value):
        super().__init__("" if value is None else str(value))
        self._sort_key = self._build_sort_key(value)

    @staticmethod
    def _build_sort_key(value):
        if value is None:
            return (2, "")
        if isinstance(value, bool):
            return (0, int(value))
        if isinstance(value, (int, float)):
            return (0, float(value))

        text = str(value).strip()
        if not text:
            return (2, "")

        try:
            return (0, int(text))
        except ValueError:
            pass

        try:
            return (0, float(text))
        except ValueError:
            pass

        return (1, text.lower())

    def __lt__(self, other):
        if isinstance(other, SortableTableWidgetItem):
            return self._sort_key < other._sort_key
        return super().__lt__(other)
