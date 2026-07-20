import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np


class LanceAnnIndexTests(unittest.TestCase):
    def test_ensure_lance_vector_indexes_skips_small_tables(self):
        from src.storage import lance_store

        with tempfile.TemporaryDirectory() as temp_dir:
            result = lance_store.ensure_lance_vector_indexes(temp_dir, min_rows=2000)
        self.assertEqual(result["built"], [])
        self.assertIn("disabled", result["skipped"])

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
            CHUNKS_TABLE_NAME,
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
        from lancedb.index import IvfPq

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

            result = ensure_lance_vector_indexes(temp_dir, min_rows=2000)

            self.assertIn(FRAMES_TABLE_NAME, result["built"])
            frame_table = db.open_table(FRAMES_TABLE_NAME)
            indices = frame_table.list_indices()
            self.assertTrue(any("vector" in list(getattr(item, "columns", []) or []) for item in indices))


if __name__ == "__main__":
    unittest.main()
