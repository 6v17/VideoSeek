"""Hot-path scans: one neighbor read per video, chunk ranges cached on the library token."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.storage.lance_search_index import (
    LanceTableSearchIndex,
    invalidate_lance_runtime_caches,
    load_lance_chunk_time_ranges,
)


class _Column:
    def __init__(self, values):
        self._values = values

    def to_pylist(self):
        return list(self._values)


class _Arrow:
    def __init__(self, rows):
        self.num_rows = len(rows)
        self._rows = rows

    def __getitem__(self, key):
        return _Column([row[key] for row in self._rows])


class _Query:
    def __init__(self, owner, rows):
        self.owner = owner
        self.rows = rows

    def where(self, sql):
        self.owner.where_sql.append(sql)
        return self

    def select(self, _columns):
        return self

    def limit(self, _count):
        return self

    def to_arrow(self):
        return _Arrow(self.rows)


class _Table:
    def __init__(self):
        self.where_sql = []
        self._reads = 0

    def search(self, *_args, **_kwargs):
        self._reads += 1
        if self._reads == 1:
            rows = [
                {"timestamp": 1.0, "video_path": "D:/a.mp4", "vector": [1.0, 0.0]},
                {"timestamp": 40.0, "video_path": "D:/a.mp4", "vector": [0.0, 1.0]},
            ]
        else:
            rows = []
        return _Query(self, rows)

    def count_rows(self, filter=None):
        return 2


class SearchHotPathScanTests(unittest.TestCase):
    def test_neighbor_windows_on_one_video_share_one_read(self):
        table = _Table()
        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=2):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=2):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=False):
                    index = LanceTableSearchIndex(table, config={"lance_ann_enabled": False})
        grouped = index.fetch_neighbor_rows_grouped(
            [("D:/a.mp4", 1.0), ("D:/a.mp4", 40.0), ("D:/b.mp4", 3.0)],
            window_sec=2.0,
        )
        self.assertEqual(len(table.where_sql), 2)
        self.assertEqual(len(grouped[0]), 1)
        self.assertEqual(grouped[0][0].timestamp, 1.0)
        self.assertEqual(grouped[1][0].timestamp, 40.0)
        self.assertEqual(grouped[2], [])
        self.assertIn("timestamp >= -1.0", table.where_sql[0])
        self.assertIn("timestamp >= 38.0", table.where_sql[0])

    def test_neighbor_read_does_not_repeat_a_video_id_list(self):
        table = _Table()
        huge = "video_id IN (" + ", ".join(f"'v{i}'" for i in range(40)) + ")"
        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=2):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=2):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=False):
                    index = LanceTableSearchIndex(table, where=huge, config={"lance_ann_enabled": False})
        index.fetch_neighbor_rows_grouped(
            [("D:/a.mp4", 1.0, "v3")],
            window_sec=2.0,
        )
        self.assertEqual(len(table.where_sql), 1)
        self.assertNotIn("v0", table.where_sql[0])
        self.assertIn("video_id = 'v3'", table.where_sql[0])
        self.assertIn("video_path = 'D:/a.mp4'", table.where_sql[0])

    def test_chunk_time_ranges_reuse_the_library_token(self):
        invalidate_lance_runtime_caches("D:/profile")
        arrow = _Arrow([{"video_path": "D:/a.mp4", "start": 0.0, "end": 4.0}])
        with patch("src.storage.lance_search_index.lance_search_is_ready", return_value=True):
            with patch("src.storage.lance_search_index._lance_state_mtime", return_value=7.0):
                with patch("src.storage.lance_search_index._open_lance_table", return_value=object()) as open_table:
                    with patch("src.storage.lance_search_index._load_columns_arrow", return_value=arrow) as load_cols:
                        first = load_lance_chunk_time_ranges("D:/profile")
                        second = load_lance_chunk_time_ranges("D:/profile")
        self.assertEqual(first["D:/a.mp4"], [(0.0, 4.0)])
        self.assertEqual(second, first)
        open_table.assert_called_once()
        load_cols.assert_called_once()
        invalidate_lance_runtime_caches("D:/profile")
