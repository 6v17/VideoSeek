"""Central column layout specs for result tables (Figma / QSS alignment)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

ResizeMode = Literal["fixed", "stretch"]


class LocalSearchCol(IntEnum):
    ORDER = 0
    PREVIEW = 1
    VIDEO = 2
    RANGE = 3
    MODE = 4
    SCORE = 5
    ACTIONS = 6


class NetworkLinkCol(IntEnum):
    ORDER = 0
    TITLE = 1
    TIME = 2
    SCORE = 3
    SOURCE = 4
    ACTIONS = 5


@dataclass(frozen=True)
class TableColumnSpec:
    key: str
    width: int | None = None
    resize: ResizeMode = "fixed"


@dataclass(frozen=True)
class TableSpec:
    """Describes a result QTableWidget layout."""

    columns: tuple[TableColumnSpec, ...]
    row_height: int = 88
    object_name: str = "ResultTable"
    scroll_per_pixel: bool = True
    texts_header_key: str = ""

    @property
    def column_count(self) -> int:
        return len(self.columns)

    @property
    def thumb_column(self) -> int | None:
        for index, col in enumerate(self.columns):
            if col.key == "preview":
                return index
        return None


LOCAL_SEARCH_TABLE_SPEC = TableSpec(
    texts_header_key="result_headers",
    row_height=88,
    columns=(
        TableColumnSpec("order", width=46),
        TableColumnSpec("preview", width=164),
        TableColumnSpec("video", resize="stretch"),
        TableColumnSpec("range", width=108),
        TableColumnSpec("mode", width=74),
        TableColumnSpec("score", width=74),
        TableColumnSpec("actions", width=360),
    ),
)

NETWORK_LINK_TABLE_SPEC = TableSpec(
    texts_header_key="network_result_headers",
    row_height=72,
    columns=(
        TableColumnSpec("order", width=46),
        TableColumnSpec("title", resize="stretch"),
        TableColumnSpec("time", width=90),
        TableColumnSpec("score", width=74),
        TableColumnSpec("source", width=300),
        TableColumnSpec("actions", width=116),
    ),
)
