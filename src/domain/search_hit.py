from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Tuple, Union


@dataclass(frozen=True)
class SearchHit:
    """One ranked match from local frame/chunk search (shared UI + worker protocol)."""

    start_sec: float
    end_sec: float
    score: float
    video_path: str
    match_kind: str = "frame"
    video_id: str = ""

    def as_tuple(self) -> Tuple[float, float, float, str]:
        return (self.start_sec, self.end_sec, self.score, self.video_path)


RowLike = Union[SearchHit, Tuple[Any, Any, Any, Any]]


def coerce_search_hit(row: RowLike) -> SearchHit:
    """Deprecated at call sites: prefer SearchHit end-to-end; tuple input is legacy-only."""
    if isinstance(row, SearchHit):
        return row
    if isinstance(row, tuple) and len(row) >= 4:
        match_kind = str(row[4]) if len(row) >= 5 else "frame"
        return SearchHit(float(row[0]), float(row[1]), float(row[2]), str(row[3]), match_kind=match_kind)
    raise TypeError(f"Expected SearchHit or 4-tuple, got {type(row).__name__}")


def coerce_search_hits(rows: Iterable[RowLike]) -> List[SearchHit]:
    return [coerce_search_hit(r) for r in rows]
