"""Group visual search hits for display. Same-video neighbors stay loose; cross-video merge is strict."""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from src.app.path_display import video_display_name
from src.domain.search_hit import SearchHit

_NEAR_GAP_SEC = 8.0
_NEAR_GAP_WITHOUT_VECTOR_SEC = 4.0
_NEAR_COSINE = 0.82
_CROSS_COSINE = {
    "loose": 0.90,
    "standard": 0.94,
    "strict": 0.97,
}


@dataclass(frozen=True)
class ResultGroup:
    representative: SearchHit
    members: tuple[SearchHit, ...]
    kind: str
    unique_videos: int
    lead_name: str


@dataclass(frozen=True)
class GroupDisplayRow(SearchHit):
    """One visible result row. Members keep the hit fields so preview and thumbs still work."""

    group_id: int = -1
    group_kind: str = "single"
    member_count: int = 1
    is_representative: bool = True
    show_badge: bool = False
    unique_videos: int = 1
    lead_name: str = ""
    display_rank: int = 0


def group_search_hits(
    hits,
    vectors=None,
    *,
    enabled: bool = True,
    sensitivity: str = "standard",
) -> list[ResultGroup]:
    rows = [hit for hit in (hits or []) if isinstance(hit, SearchHit)]
    if not rows:
        return []
    if not enabled:
        return [_singleton(hit) for hit in rows]

    units = _align_units(rows, vectors)
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    buckets: dict[tuple, list[int]] = {}
    for index, hit in enumerate(rows):
        buckets.setdefault(_video_key(hit), []).append(index)
    for indices in buckets.values():
        indices.sort(key=lambda item: float(rows[item].start_sec))
        for pos, left in enumerate(indices):
            left_time = float(rows[left].start_sec)
            for right in reversed(indices[:pos]):
                gap = left_time - float(rows[right].start_sec)
                if gap > _NEAR_GAP_SEC:
                    break
                if _near_match(units[left], units[right], gap):
                    union(left, right)

    clusters: dict[int, list[int]] = {}
    for index in range(len(rows)):
        clusters.setdefault(find(index), []).append(index)
    preliminary = [_cluster_group(rows, units, members) for members in clusters.values()]

    threshold = _CROSS_COSINE.get(str(sensitivity or "").strip().lower(), _CROSS_COSINE["standard"])
    group_parent = list(range(len(preliminary)))

    def find_group(index: int) -> int:
        while group_parent[index] != index:
            group_parent[index] = group_parent[group_parent[index]]
            index = group_parent[index]
        return index

    def union_group(left: int, right: int) -> None:
        left_root = find_group(left)
        right_root = find_group(right)
        if left_root != right_root:
            group_parent[right_root] = left_root

    usable = [(index, group.representative_unit) for index, group in enumerate(preliminary) if group.representative_unit is not None]
    if len(usable) >= 2:
        matrix = np.stack([unit for _index, unit in usable])
        similarity = matrix @ matrix.T
        for left_pos, (left_index, _left_unit) in enumerate(usable):
            for right_pos in range(left_pos + 1, len(usable)):
                right_index = usable[right_pos][0]
                if preliminary[left_index].video_key == preliminary[right_index].video_key:
                    continue
                if float(similarity[left_pos, right_pos]) >= threshold:
                    union_group(left_index, right_index)

    merged: dict[int, list[int]] = {}
    for index in range(len(preliminary)):
        merged.setdefault(find_group(index), []).append(index)
    groups: list[ResultGroup] = []
    for parts in merged.values():
        member_indexes: list[int] = []
        for part in parts:
            member_indexes.extend(preliminary[part].member_indexes)
        groups.append(_finish_group(rows, member_indexes))
    groups.sort(key=lambda group: (-float(group.representative.score), float(group.representative.start_sec), group.lead_name))
    return groups


def flatten_result_groups(groups, *, expanded: set[int] | None = None) -> list[GroupDisplayRow]:
    open_ids = expanded or set()
    rows: list[GroupDisplayRow] = []
    for group_id, group in enumerate(groups or []):
        count = len(group.members)
        rows.append(
            _display_row(
                group.representative,
                group_id=group_id,
                group_kind=group.kind,
                member_count=count,
                is_representative=True,
                show_badge=count > 1,
                unique_videos=group.unique_videos,
                lead_name=group.lead_name,
                display_rank=group_id + 1,
            )
        )
        if count <= 1 or group_id not in open_ids:
            continue
        for hit in _ordered_members(group):
            if _same_hit(hit, group.representative):
                continue
            rows.append(
                _display_row(
                    hit,
                    group_id=group_id,
                    group_kind=group.kind,
                    member_count=count,
                    is_representative=False,
                    show_badge=False,
                    unique_videos=group.unique_videos,
                    lead_name=group.lead_name,
                    display_rank=group_id + 1,
                )
            )
    return rows


def focus_group_rows(group: ResultGroup, *, group_id: int) -> list[GroupDisplayRow]:
    return [
        _display_row(
            hit,
            group_id=group_id,
            group_kind=group.kind,
            member_count=1,
            is_representative=True,
            show_badge=False,
            unique_videos=1,
            lead_name="",
            display_rank=index + 1,
        )
        for index, hit in enumerate(_ordered_members(group))
    ]


def fetch_hit_frame_vectors(hits, config) -> list[np.ndarray | None]:
    """Best-effort frame vectors for the hits. Missing rows stay None so time grouping still works."""
    rows = list(hits or [])
    empty: list[np.ndarray | None] = [None] * len(rows)
    if not rows:
        return []
    try:
        from src.services.search_assets import load_search_assets

        index, _timestamps, _paths = load_search_assets(config)
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/services/search_result_groups.py:load_assets")
        return empty
    fetch = getattr(index, "fetch_neighbor_rows_grouped", None)
    if not callable(fetch):
        return empty
    seeds = [
        (str(hit.video_path or ""), float(hit.start_sec), str(getattr(hit, "video_id", "") or ""))
        for hit in rows
    ]
    try:
        grouped = fetch(seeds, window_sec=0.45)
    except Exception as exc:
        from src.app.logging_utils import note_swallowed

        note_swallowed(exc, "src/services/search_result_groups.py:fetch_vectors")
        return empty
    found: list[np.ndarray | None] = []
    for hit, neighbors in zip(rows, grouped):
        found.append(_closest_vector(float(hit.start_sec), neighbors))
    if len(found) < len(rows):
        found.extend([None] * (len(rows) - len(found)))
    return found[: len(rows)]


@dataclass
class _Cluster:
    member_indexes: list[int]
    representative_unit: np.ndarray | None
    video_key: tuple


def _singleton(hit: SearchHit) -> ResultGroup:
    name = video_display_name(hit.video_path)
    return ResultGroup(hit, (hit,), "single", 1, name)


def _align_units(rows: list[SearchHit], vectors) -> list[np.ndarray | None]:
    if vectors is None or len(list(vectors)) != len(rows):
        return [None] * len(rows)
    return [_as_unit(vector) for vector in vectors]


def _as_unit(vector) -> np.ndarray | None:
    if vector is None:
        return None
    array = np.asarray(vector, dtype=np.float32).reshape(-1)
    if array.size == 0:
        return None
    norm = float(np.linalg.norm(array))
    if norm < 1e-8:
        return None
    return array / norm


def _video_key(hit: SearchHit) -> tuple:
    video_id = str(getattr(hit, "video_id", "") or "").strip()
    if video_id:
        return ("id", video_id)
    path = os.path.normcase(os.path.normpath(str(hit.video_path or "").strip()))
    if path:
        return ("path", path)
    return ("hit", id(hit))


def _near_match(left, right, gap: float) -> bool:
    if left is None or right is None:
        return gap <= _NEAR_GAP_WITHOUT_VECTOR_SEC
    return float(np.dot(left, right)) >= _NEAR_COSINE


def _cluster_group(rows: list[SearchHit], units, member_indexes: list[int]) -> _Cluster:
    best = max(member_indexes, key=lambda index: (float(rows[index].score), -float(rows[index].start_sec)))
    return _Cluster(member_indexes, units[best], _video_key(rows[best]))


def _finish_group(rows: list[SearchHit], member_indexes: list[int]) -> ResultGroup:
    members = tuple(rows[index] for index in member_indexes)
    representative = max(members, key=lambda hit: (float(hit.score), -float(hit.start_sec)))
    names: list[str] = []
    seen: set[str] = set()
    for hit in sorted(members, key=lambda item: os.path.normcase(str(item.video_path or ""))):
        name = video_display_name(hit.video_path)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    unique = len(names) or 1
    if len(members) <= 1:
        kind = "single"
    elif unique <= 1:
        kind = "near"
    else:
        kind = "cross"
    return ResultGroup(representative, members, kind, unique, names[0] if names else "")


def _ordered_members(group: ResultGroup) -> tuple[SearchHit, ...]:
    if group.kind == "cross":
        return tuple(sorted(group.members, key=lambda hit: (os.path.normcase(str(hit.video_path or "")), float(hit.start_sec))))
    return tuple(sorted(group.members, key=lambda hit: (float(hit.start_sec), -float(hit.score))))


def _same_hit(left: SearchHit, right: SearchHit) -> bool:
    return (
        str(left.video_path or "") == str(right.video_path or "")
        and abs(float(left.start_sec) - float(right.start_sec)) < 1e-3
        and abs(float(left.end_sec) - float(right.end_sec)) < 1e-3
    )


def _display_row(hit: SearchHit, **kwargs) -> GroupDisplayRow:
    return GroupDisplayRow(
        start_sec=float(hit.start_sec),
        end_sec=float(hit.end_sec),
        score=float(hit.score),
        video_path=str(hit.video_path or ""),
        match_kind=str(hit.match_kind or "frame"),
        video_id=str(getattr(hit, "video_id", "") or ""),
        matched_text=str(getattr(hit, "matched_text", "") or ""),
        peak_sec=getattr(hit, "peak_sec", None),
        **kwargs,
    )


def _closest_vector(target: float, neighbors) -> np.ndarray | None:
    best = None
    best_gap = 1e9
    for row in neighbors or []:
        vector = getattr(row, "vector", None)
        if vector is None:
            continue
        stamp = getattr(row, "timestamp", None)
        gap = 0.0 if stamp is None else abs(float(stamp) - float(target))
        if gap < best_gap:
            best_gap = gap
            best = np.asarray(vector, dtype=np.float32).reshape(-1)
    return best
