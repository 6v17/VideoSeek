import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.modules.setdefault("cv2", object())

from src.core.faiss_index import save_vectors
from src.core.semantic_chunking import pack_chunks
from src.storage.asset_store import save_metadata
from src.storage.lance_store import (
    CHUNKS_TABLE_NAME,
    FRAMES_TABLE_NAME,
    build_video_lookup,
    get_lance_dir,
    import_npy_to_lance,
)


class LanceImportTests(unittest.TestCase):
    def _write_profile(self, root: str, video_id: str, vectors, timestamps, chunks=None):
        vector_dir = os.path.join(root, "vector")
        os.makedirs(vector_dir, exist_ok=True)
        vector_file = os.path.join(vector_dir, f"{video_id}_vectors.npy")
        save_vectors(vectors, timestamps, vector_file, chunks=chunks)
        return vector_file

    def test_build_video_lookup(self):
        meta = {
            "libraries": {
                "D:/Anime": {
                    "files": {
                        "ep01.mp4": {"vid": "vid001", "asset_state": "ready"},
                    }
                }
            }
        }
        lookup = build_video_lookup(meta)
        self.assertIn("vid001", lookup)
        self.assertTrue(lookup["vid001"]["library_path"])
        self.assertTrue(lookup["vid001"]["video_path"].endswith("ep01.mp4"))

    def test_import_npy_to_lance_creates_tables(self):
        try:
            import lancedb
        except ImportError:
            self.skipTest("lancedb not installed")

        vectors = np.random.randn(4, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
        chunks = [
            {"start": 0.0, "end": 1.5, "embedding": vectors[0]},
            {"start": 1.5, "end": 3.0, "embedding": vectors[2]},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            profile_dir = os.path.join(tmp, "data", "model_assets", "openai-clip", "vit-base-patch32")
            os.makedirs(profile_dir, exist_ok=True)
            save_metadata(
                {
                    "libraries": {
                        tmp: {
                            "files": {
                                "clip.mp4": {"vid": "abc123", "asset_state": "ready"},
                            }
                        }
                    }
                },
                os.path.join(profile_dir, "meta.json"),
            )
            self._write_profile(profile_dir, "abc123", vectors, timestamps, chunks=chunks)

            summary = import_npy_to_lance(profile_dir)
            self.assertEqual(summary["videos_total"], 1)
            self.assertEqual(summary["videos_imported"], 1)
            self.assertEqual(summary["frame_rows"], 4)
            self.assertEqual(summary["chunk_rows"], 2)

            lance_dir = get_lance_dir(profile_dir)
            self.assertTrue(os.path.isdir(lance_dir))
            db = lancedb.connect(lance_dir)
            from src.storage.lance_store import _list_table_names

            names = _list_table_names(db)
            self.assertIn(FRAMES_TABLE_NAME, names)
            self.assertIn(CHUNKS_TABLE_NAME, names)
            self.assertEqual(db.open_table(FRAMES_TABLE_NAME).count_rows(), 4)
            self.assertEqual(db.open_table(CHUNKS_TABLE_NAME).count_rows(), 2)

            state_file = os.path.join(lance_dir, "import_state.json")
            self.assertTrue(os.path.isfile(state_file))
            with open(state_file, "r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["videos_imported"], 1)


if __name__ == "__main__":
    unittest.main()
