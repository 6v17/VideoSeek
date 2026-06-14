"""In-session shot list (material basket) for collecting search hits."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional

from src.domain.search_hit import SearchHit, RowLike, coerce_search_hit


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shot_list_dedupe_key(video_path: str, start_sec: float, end_sec: float) -> tuple[str, float, float]:
    normalized = os.path.normpath(os.path.abspath(os.path.expanduser(str(video_path or "").strip())))
    return (normalized, round(float(start_sec), 2), round(float(end_sec), 2))


@dataclass(frozen=True)
class ShotListItem:
    id: str
    video_path: str
    start_sec: float
    end_sec: float
    score: float | None
    match_kind: str = "frame"
    source_query: str = ""
    added_at: str = ""

    @classmethod
    def from_hit(cls, hit: SearchHit, *, source_query: str = "") -> "ShotListItem":
        return cls(
            id=str(uuid.uuid4()),
            video_path=str(hit.video_path),
            start_sec=float(hit.start_sec),
            end_sec=float(hit.end_sec),
            score=float(hit.score) if hit.score is not None else None,
            match_kind=str(getattr(hit, "match_kind", "frame") or "frame"),
            source_query=str(source_query or "").strip(),
            added_at=_now_iso(),
        )


class ShotListStore:
    """Process-local shot list; cleared when the app exits."""

    def __init__(self) -> None:
        self._items: List[ShotListItem] = []
        self._keys: set[tuple[str, float, float]] = set()

    def count(self) -> int:
        return len(self._items)

    def list_items(self) -> List[ShotListItem]:
        return list(self._items)

    def add_from_hit(self, hit: RowLike, *, source_query: str = "") -> bool:
        coerced = coerce_search_hit(hit)
        key = shot_list_dedupe_key(coerced.video_path, coerced.start_sec, coerced.end_sec)
        if key in self._keys:
            return False
        item = ShotListItem.from_hit(coerced, source_query=source_query)
        self._items.append(item)
        self._keys.add(key)
        return True

    def remove(self, item_id: str) -> bool:
        target = str(item_id or "").strip()
        if not target:
            return False
        for index, item in enumerate(self._items):
            if item.id != target:
                continue
            self._keys.discard(shot_list_dedupe_key(item.video_path, item.start_sec, item.end_sec))
            del self._items[index]
            return True
        return False

    def move_up(self, item_id: str) -> bool:
        index = self._index_of(item_id)
        if index is None or index <= 0:
            return False
        self._items[index - 1], self._items[index] = self._items[index], self._items[index - 1]
        return True

    def move_down(self, item_id: str) -> bool:
        index = self._index_of(item_id)
        if index is None or index >= len(self._items) - 1:
            return False
        self._items[index + 1], self._items[index] = self._items[index], self._items[index + 1]
        return True

    def clear(self) -> None:
        self._items.clear()
        self._keys.clear()

    def get(self, item_id: str) -> Optional[ShotListItem]:
        index = self._index_of(item_id)
        if index is None:
            return None
        return self._items[index]

    def _index_of(self, item_id: str) -> Optional[int]:
        target = str(item_id or "").strip()
        if not target:
            return None
        for index, item in enumerate(self._items):
            if item.id == target:
                return index
        return None

    def replace_items(self, items: Iterable[ShotListItem]) -> None:
        self.clear()
        for item in items:
            key = shot_list_dedupe_key(item.video_path, item.start_sec, item.end_sec)
            if key in self._keys:
                continue
            self._items.append(item)
            self._keys.add(key)
