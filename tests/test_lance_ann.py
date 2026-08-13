import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


class LanceAnnIndexTests(unittest.TestCase):
    def test_ensure_lance_vector_indexes_skips_when_disabled(self):
        from src.storage import lance_store

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(lance_store, "LANCE_ANN_ENABLED", False):
                result = lance_store.ensure_lance_vector_indexes(temp_dir, min_rows=2000)
        self.assertEqual(result["built"], [])
        self.assertIn("disabled", result["skipped"])

    def test_is_lance_ann_enabled_reads_config_when_override_unset(self):
        from src.storage import lance_store

        with patch.object(lance_store, "LANCE_ANN_ENABLED", None):
            self.assertFalse(lance_store.is_lance_ann_enabled({"lance_ann_enabled": False}))
            self.assertTrue(lance_store.is_lance_ann_enabled({"lance_ann_enabled": True}))

    def test_ensure_lance_vector_indexes_builds_for_large_tables_when_enabled(self):
        from src.storage import lance_store

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(lance_store, "LANCE_ANN_ENABLED", True):
                with patch.object(lance_store, "_connect_lance") as mock_connect:
                    table = MagicMock()
                    table.count_rows.return_value = 5000
                    table.list_indices.return_value = []
                    db = MagicMock()
                    db.open_table.return_value = table
                    mock_connect.return_value = db
                    with patch.object(lance_store, "_list_table_names", return_value=[lance_store.FRAMES_TABLE_NAME]):
                        with patch.object(lance_store, "get_lance_dir", return_value=temp_dir):
                            result = lance_store.ensure_lance_vector_indexes(temp_dir, min_rows=2000)

        self.assertEqual(result["built"], [lance_store.FRAMES_TABLE_NAME])
        table.create_index.assert_called_once()

    def test_drop_lance_vector_indexes_removes_vector_index(self):
        import lancedb
        from lancedb.index import IvfPq

        from src.storage.lance_store import (
            FRAMES_TABLE_NAME,
            drop_lance_vector_indexes,
            get_lance_dir,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            db = lancedb.connect(get_lance_dir(temp_dir))
            rows = [
                {
                    "vector": np.random.rand(32).astype(np.float32).tolist(),
                    "video_id": f"vid_{index // 10}",
                    "video_path": f"/tmp/vid_{index // 10}.mp4",
                    "library_path": "/tmp",
                    "timestamp": float(index),
                }
                for index in range(2500)
            ]
            db.create_table(FRAMES_TABLE_NAME, data=rows)
            table = db.open_table(FRAMES_TABLE_NAME)
            table.create_index(
                "vector",
                config=IvfPq(distance_type="cosine", num_partitions=64, num_sub_vectors=16),
            )
            self.assertTrue(table.list_indices())

            result = drop_lance_vector_indexes(temp_dir)

            self.assertTrue(result["dropped"])
            self.assertFalse(db.open_table(FRAMES_TABLE_NAME).list_indices())

    @unittest.skip("ANN index disabled by default for search accuracy")
    def test_ensure_lance_vector_indexes_integration(self):
        import lancedb

        from src.storage.lance_store import (
            CHUNKS_TABLE_NAME,
            FRAMES_TABLE_NAME,
            ensure_lance_vector_indexes,
            get_lance_dir,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            db = lancedb.connect(get_lance_dir(temp_dir))
            rows = [
                {
                    "vector": np.random.rand(32).astype(np.float32).tolist(),
                    "video_id": f"vid_{index // 10}",
                    "video_path": f"/tmp/vid_{index // 10}.mp4",
                    "library_path": "/tmp",
                    "timestamp": float(index),
                }
                for index in range(2500)
            ]
            db.create_table(FRAMES_TABLE_NAME, data=rows)
            db.create_table(
                CHUNKS_TABLE_NAME,
                data=[
                    {
                        "vector": np.random.rand(32).astype(np.float32).tolist(),
                        "video_id": "vid_0",
                        "video_path": "/tmp/vid_0.mp4",
                        "library_path": "/tmp",
                        "start": 0.0,
                        "end": 1.0,
                    }
                ],
            )

            with patch("src.storage.lance_store.LANCE_ANN_ENABLED", True):
                result = ensure_lance_vector_indexes(temp_dir, min_rows=2000)

            self.assertIn(FRAMES_TABLE_NAME, result["built"])
            frame_table = db.open_table(FRAMES_TABLE_NAME)
            indices = frame_table.list_indices()
            self.assertTrue(any("vector" in list(getattr(item, "columns", []) or []) for item in indices))


class LanceAnnSearchRefineTests(unittest.TestCase):
    def test_build_vector_search_bypasses_when_ann_off(self):
        from src.storage.lance_search_index import LanceTableSearchIndex

        builder = MagicMock()
        builder.where.return_value = builder
        builder.metric.return_value = builder
        builder.bypass_vector_index.return_value = builder
        table = MagicMock()
        table.search.return_value = builder
        table.count_rows.return_value = 10
        table.search.return_value.select.return_value.limit.return_value.to_arrow.return_value = MagicMock(
            num_rows=0
        )

        # Probe paths used by __init__
        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=10):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=4):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=True):
                    index = LanceTableSearchIndex(table, config={"lance_ann_enabled": False})

        out = index._build_vector_search(np.ones(4, dtype=np.float32), use_ann=False)
        self.assertIs(out, builder)
        builder.bypass_vector_index.assert_called_once()

    def test_build_vector_search_skips_bypass_when_ann_on(self):
        from src.storage.lance_search_index import LanceTableSearchIndex

        builder = MagicMock()
        builder.where.return_value = builder
        builder.metric.return_value = builder
        builder.nprobes = MagicMock(return_value=builder)
        table = MagicMock()
        table.search.return_value = builder

        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=10):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=4):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=True):
                    index = LanceTableSearchIndex(table, config={"lance_ann_enabled": True})

        out = index._build_vector_search(np.ones(4, dtype=np.float32), use_ann=True)
        self.assertIs(out, builder)
        builder.bypass_vector_index.assert_not_called()
        builder.nprobes.assert_called()

    def test_refine_rows_exact_cosine_restores_order(self):
        from src.storage.lance_search_index import LanceSearchRow, LanceTableSearchIndex

        query = np.asarray([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
        rows = [
            LanceSearchRow(score=0.1, video_path="/a", video_id="a", vector=np.asarray([0.0, 1.0, 0.0, 0.0])),
            LanceSearchRow(score=0.2, video_path="/b", video_id="b", vector=np.asarray([1.0, 0.0, 0.0, 0.0])),
            LanceSearchRow(score=0.3, video_path="/c", video_id="c", vector=np.asarray([0.5, 0.5, 0.0, 0.0])),
        ]
        refined = LanceTableSearchIndex._refine_rows_exact_cosine(query, rows, top_k=2)
        self.assertEqual([row.video_id for row in refined], ["b", "c"])
        self.assertGreater(refined[0].score, refined[1].score)

    def test_search_rows_uses_ann_fetch_then_refine(self):
        from src.storage.lance_search_index import LanceTableSearchIndex

        table = MagicMock()
        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=100):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=2):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=True):
                    index = LanceTableSearchIndex(
                        table,
                        config={"lance_ann_enabled": True, "lance_ann_refine_multiplier": 3},
                    )

        query = np.asarray([1.0, 0.0], dtype=np.float32)

        class _Arrow:
            num_rows = 3
            column_names = ["timestamp", "video_path", "video_id", "_distance", "vector"]

            def __getitem__(self, key):
                mapping = {
                    "timestamp": MagicMock(to_pylist=lambda: [0.0, 1.0, 2.0]),
                    "video_path": MagicMock(to_pylist=lambda: ["/a", "/b", "/c"]),
                    "video_id": MagicMock(to_pylist=lambda: ["a", "b", "c"]),
                    "_distance": MagicMock(to_pylist=lambda: [0.9, 0.1, 0.5]),
                    "vector": MagicMock(
                        to_pylist=lambda: [
                            [0.0, 1.0],
                            [1.0, 0.0],
                            [0.7, 0.7],
                        ]
                    ),
                }
                return mapping[key]

        captured = {}

        def fake_build(query_vector, *, use_ann=False):
            captured["use_ann"] = use_ann
            builder = MagicMock()
            builder.limit.return_value.to_arrow.return_value = _Arrow()
            return builder

        index._build_vector_search = fake_build
        rows = index.search_rows(query, top_k=2)
        self.assertTrue(captured["use_ann"])
        self.assertEqual([row.video_id for row in rows], ["b", "c"])
        self.assertEqual(len(rows), 2)

    def test_search_rows_default_path_stays_exact_without_ann(self):
        from src.storage.lance_search_index import LanceTableSearchIndex

        table = MagicMock()
        with patch.object(LanceTableSearchIndex, "_count_rows", return_value=3):
            with patch.object(LanceTableSearchIndex, "_read_dimension", return_value=2):
                with patch.object(LanceTableSearchIndex, "_detect_vector_index", return_value=False):
                    index = LanceTableSearchIndex(table, config={"lance_ann_enabled": True})

        class _Arrow:
            num_rows = 2
            column_names = ["timestamp", "video_path", "video_id", "_distance", "vector"]

            def __getitem__(self, key):
                mapping = {
                    "timestamp": MagicMock(to_pylist=lambda: [0.0, 1.0]),
                    "video_path": MagicMock(to_pylist=lambda: ["/a", "/b"]),
                    "video_id": MagicMock(to_pylist=lambda: ["a", "b"]),
                    "_distance": MagicMock(to_pylist=lambda: [0.2, 0.1]),
                    "vector": MagicMock(to_pylist=lambda: [[1.0, 0.0], [0.0, 1.0]]),
                }
                return mapping[key]

        captured = {}

        def fake_build(query_vector, *, use_ann=False):
            captured["use_ann"] = use_ann
            builder = MagicMock()
            builder.limit.return_value.to_arrow.return_value = _Arrow()
            return builder

        index._build_vector_search = fake_build
        rows = index.search_rows(np.asarray([1.0, 0.0], dtype=np.float32), top_k=2)
        self.assertFalse(captured["use_ann"])
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
