"""Fixed-size search chain. A few thousand hits must not grow filters or grouping."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from src.domain.search_hit import SearchHit
from src.services.search_result_groups import group_hit_batches, group_search_hits

_SCALE = 2048


class _Query:
    def __init__(self, owner):
        self.owner = owner

    def where(self, sql):
        self.owner.where_sql.append(sql)
        return self

    def select(self, _columns):
        return self

    def limit(self, _count):
        return self

    def to_arrow(self):
        return _EmptyArrow()


class _EmptyArrow:
    num_rows = 0

    def __getitem__(self, _key):
        return self

    def to_pylist(self):
        return []


class _Table:
    def __init__(self):
        self.where_sql = []

    def search(self, *_args, **_kwargs):
        return _Query(self)


class _Conn:
    def __init__(self):
        self.sql = []

    def execute(self, sql, _params=()):
        self.sql.append(str(sql))
        return []


def _hits(count: int, *, gap: float) -> list[SearchHit]:
    return [
        SearchHit(index * gap, index * gap, 0.5, f"v{index}.mp4", video_id=str(index))
        for index in range(count)
    ]


class SearchScaleTests(unittest.TestCase):
    def test_neighbor_filters_stay_short_for_thousands_of_seeds(self):
        from src.storage.lance_search_index import LanceTableSearchIndex, _NEIGHBOR_CLAUSE_BATCH

        table = _Table()
        seeds = [("D:/one.mp4", float(index)) for index in range(_SCALE)]
        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=1):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=2):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=False):
                    index = LanceTableSearchIndex(table, config={"lance_ann_enabled": False})
        grouped = index.fetch_neighbor_rows_grouped(seeds, window_sec=0.45)
        self.assertEqual(len(grouped), _SCALE)
        self.assertEqual(len(table.where_sql), (_SCALE + _NEIGHBOR_CLAUSE_BATCH - 1) // _NEIGHBOR_CLAUSE_BATCH)
        for sql in table.where_sql:
            self.assertLessEqual(sql.count("timestamp >="), _NEIGHBOR_CLAUSE_BATCH)
            self.assertLess(len(sql), 8000)

    def test_tag_statements_stay_short_for_a_long_id_list(self):
        from src.storage.evidence_tags_store import (
            _TAG_IN_BATCH,
            _TAG_OR_BATCH,
            _aggregate_and_hits,
            _attach_full_chunk_tags,
            _fetch_tag_rows_exact,
        )

        conn = _Conn()
        want_ids = [f"vid-{index}" for index in range(_TAG_IN_BATCH + 50)]
        _fetch_tag_rows_exact(conn, "chair", want_ids)
        in_sql = [sql for sql in conn.sql if " IN (" in sql]
        self.assertGreater(len(in_sql), 1)
        for sql in in_sql:
            self.assertLessEqual(sql.count("?"), _TAG_IN_BATCH + 1)

        conn.sql.clear()
        keys = {(f"vid-{index}", index) for index in range(_TAG_OR_BATCH * 3 + 5)}
        _aggregate_and_hits(conn, keys, ["chair"], "exact", keep=10)
        or_sql = [sql for sql in conn.sql if " OR " in sql]
        self.assertGreater(len(or_sql), 1)
        for sql in or_sql:
            self.assertLessEqual(sql.count("video_id = ?"), _TAG_OR_BATCH)

        hits = [
            {"video_id": f"vid-{index}", "chunk_index": index, "matched_tags": ["chair"]}
            for index in range(_TAG_OR_BATCH + 10)
        ]
        conn.sql.clear()
        attached = _attach_full_chunk_tags(conn, hits)
        self.assertEqual(len(attached), _TAG_OR_BATCH + 10)
        for sql in conn.sql:
            self.assertLessEqual(sql.count("video_id = ?"), _TAG_OR_BATCH)

    def test_a_short_ceiling_of_thousands_says_the_list_ended(self):
        from PySide6.QtCore import QObject

        from src.storage.config_store import SEARCH_TOP_K_MAX
        from ui.controllers.search_controller import SearchController

        parent = QObject()
        parent.texts = {
            "search_done": "Done {duration:.2f}s · {count}",
            "search_window_end_hint": "End of the results",
            "search_window_cap_hint": "Reached the 10,000 limit",
        }
        parent.search_page = MagicMock()
        controller = SearchController(parent)
        controller.worker = MagicMock()
        controller._last_search_duration = 0.71
        controller._result_display_context = {"search_kind": "image"}
        controller._window_epoch = 0
        prior = _hits(3000, gap=30.0)
        extra = [
            SearchHit(index * 30.0, index * 30.0, 0.18, f"new{index}.mp4", video_id=f"new{index}")
            for index in range(1000)
        ]
        incoming = prior + extra
        controller._source_hits = list(prior)
        controller._more_worker = MagicMock(
            window_epoch=0,
            window_limit=SEARCH_TOP_K_MAX,
            hit_vectors=None,
        )
        seen = {}

        def _append(rows, vectors):
            seen["count"] = len(rows)
            controller._all_results = list(incoming)
            controller._update_results_status_text(incoming, {"search_kind": "image"})

        with patch.object(controller, "sender", return_value=controller._more_worker), patch.object(
            controller, "_append_grouped_batch", side_effect=_append
        ), patch.object(controller, "_maybe_grow_window"):
            controller._on_window_ready(incoming)

        self.assertEqual(seen["count"], 1000)
        self.assertTrue(controller._window_ended)
        self.assertTrue(controller._window_exhausted)
        self.assertFalse(controller._window_capped)
        parent.search_page.lbl_status.setText.assert_called_with(
            f"Done 0.71s · {len(incoming)} · End of the results"
        )

    def test_grouping_thousands_of_videos_stays_block_shaped(self):
        count = _SCALE
        hits = _hits(count, gap=30.0)
        vectors = np.eye(count, dtype=np.float32)
        started = time.perf_counter()
        groups = group_search_hits(
            hits,
            [row.copy() for row in vectors],
            enabled=True,
            sensitivity="strict",
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(len(groups), count)
        self.assertTrue(all(group.kind == "single" for group in groups))
        self.assertLess(elapsed, 5.0)

        same = [
            SearchHit(index * 30.0, index * 30.0, 0.5, "same.mp4", video_id="same")
            for index in range(count)
        ]
        started = time.perf_counter()
        spread = group_search_hits(same, enabled=True)
        self.assertEqual(len(spread), count)
        self.assertLess(time.perf_counter() - started, 5.0)

        vector = np.zeros(8, dtype=np.float32)
        vector[0] = 1.0
        first = _hits(600, gap=30.0)
        second = [
            SearchHit(index * 30.0, index * 30.0, 0.4, f"b{index}.mp4", video_id=f"b{index}")
            for index in range(600)
        ]
        batches = group_hit_batches(
            [first, second],
            [[vector.copy() for _ in first], [vector.copy() for _ in second]],
            enabled=True,
            sensitivity="loose",
        )
        self.assertEqual(len(batches), 2)
        self.assertEqual(sorted(len(group.members) for group in batches), [600, 600])
