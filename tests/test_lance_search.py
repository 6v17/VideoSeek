import os
import sys
import tempfile
import unittest

import numpy as np

sys.modules.setdefault("cv2", object())

from src.core.faiss_index import create_clip_index, load_clip_index, save_vectors
from src.services.search_assets import invalidate_search_asset_caches, load_chunk_search_assets, load_search_assets
from src.services.search_frame_query import _search_frame_results_with_ids
from src.storage.asset_store import save_metadata
from src.storage.lance_search_index import InMemoryFlatSearchIndex, get_lance_video_row_counts, load_lance_frame_search_assets
from src.storage.lance_store import (
    allocate_lance_dir_bytes_by_weight,
    format_byte_size,
    import_npy_to_lance,
    upsert_profile_video_vectors,
)


class LanceSearchTests(unittest.TestCase):
    def test_in_memory_flat_search_matches_faiss(self):
        try:
            import faiss
        except ImportError:
            self.skipTest("faiss not installed")

        vectors = np.random.randn(32, 16).astype(np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            index_file = os.path.join(tmp, "sample.faiss")
            faiss_index = create_clip_index(vectors, index_file)
            lance_index = InMemoryFlatSearchIndex(vectors)
            query = np.random.randn(1, 16).astype(np.float32)

            faiss_dist, faiss_ids = faiss_index.search(query, 5)
            lance_dist, lance_ids = lance_index.search(query, 5)
            np.testing.assert_allclose(faiss_dist, lance_dist, rtol=1e-5, atol=1e-5)
            np.testing.assert_array_equal(faiss_ids, lance_ids)

    def test_load_search_assets_prefers_lance_when_ready(self):
        try:
            import lancedb
        except ImportError:
            self.skipTest("lancedb not installed")

        vectors = np.random.randn(6, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)

        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            profile_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
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
            vector_file = os.path.join(profile_dir, "vector", "abc123_vectors.npy")
            os.makedirs(os.path.dirname(vector_file), exist_ok=True)
            save_vectors(vectors, timestamps, vector_file)
            import_npy_to_lance(profile_dir)

            config = {
                "schema_version": 2,
                "vector_search_backend": "auto",
                "data_root": tmp,
                "meta_file": os.path.join(data_dir, "meta.json"),
                "models": {
                    "active_profile": "clip_test",
                    "profiles": [
                        {
                            "id": "clip_test",
                            "provider": "clip_onnx",
                            "runtime": {"model_dir": os.path.join(tmp, "models"), "model_variant": "vit-base-patch32"},
                        }
                    ],
                },
            }
            os.makedirs(data_dir, exist_ok=True)

            invalidate_search_asset_caches()
            search_index, loaded_ts, loaded_paths = load_search_assets(config)
            self.assertIsNotNone(search_index)
            self.assertEqual(int(search_index.ntotal), 6)
            self.assertEqual(len(loaded_ts), 6)
            self.assertEqual(len(loaded_paths), 6)

            query = np.asarray(vectors[2], dtype=np.float32).reshape(1, -1)
            hits, _ids = _search_frame_results_with_ids(
                query,
                search_index,
                loaded_ts,
                loaded_paths,
                top_k=3,
            )
            self.assertTrue(hits)
            self.assertEqual(hits[0].video_path, loaded_paths[2])

    def test_upsert_profile_video_vectors_updates_lance(self):
        try:
            import lancedb
        except ImportError:
            self.skipTest("lancedb not installed")

        vectors = np.random.randn(3, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0, 2.0], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            profile_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(profile_dir, "vector")
            os.makedirs(vector_dir, exist_ok=True)
            save_metadata({"libraries": {}}, os.path.join(profile_dir, "meta.json"))
            save_vectors(vectors, timestamps, os.path.join(vector_dir, "vid999_vectors.npy"))

            config = {
                "schema_version": 2,
                "vector_search_backend": "lance",
                "data_root": tmp,
                "meta_file": os.path.join(data_dir, "meta.json"),
                "models": {
                    "active_profile": "clip_test",
                    "profiles": [
                        {
                            "id": "clip_test",
                            "provider": "clip_onnx",
                            "runtime": {"model_dir": os.path.join(tmp, "models"), "model_variant": "vit-base-patch32"},
                        }
                    ],
                },
            }
            os.makedirs(data_dir, exist_ok=True)

            result = upsert_profile_video_vectors(
                "vid999",
                config=config,
                library_path=tmp,
                video_path=os.path.join(tmp, "clip.mp4"),
            )
            self.assertFalse(result.get("error"))
            loaded = load_lance_frame_search_assets(profile_dir, video_id="vid999")
            self.assertIsNotNone(loaded[0])
            self.assertEqual(int(loaded[0].ntotal), 3)

    def test_get_lance_video_row_counts_returns_per_video_totals(self):
        try:
            import lancedb
        except ImportError:
            self.skipTest("lancedb not installed")

        vectors = np.random.randn(4, 8).astype(np.float32)
        timestamps = np.asarray([0.0, 1.0, 2.0, 3.0], dtype=np.float32)
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = os.path.join(tmp, "data")
            profile_dir = os.path.join(data_dir, "model_assets", "openai-clip", "vit-base-patch32")
            vector_dir = os.path.join(profile_dir, "vector")
            os.makedirs(vector_dir, exist_ok=True)
            save_metadata({"libraries": {}}, os.path.join(profile_dir, "meta.json"))
            save_vectors(vectors, timestamps, os.path.join(vector_dir, "vid999_vectors.npy"))

            config = {
                "schema_version": 2,
                "vector_search_backend": "lance",
                "data_root": tmp,
                "meta_file": os.path.join(data_dir, "meta.json"),
                "models": {
                    "active_profile": "clip_test",
                    "profiles": [
                        {
                            "id": "clip_test",
                            "provider": "clip_onnx",
                            "runtime": {"model_dir": os.path.join(tmp, "models"), "model_variant": "vit-base-patch32"},
                        }
                    ],
                },
            }
            os.makedirs(data_dir, exist_ok=True)

            result = upsert_profile_video_vectors(
                "vid999",
                config=config,
                library_path=tmp,
                video_path=os.path.join(tmp, "clip.mp4"),
            )
            self.assertFalse(result.get("error"))

            counts = get_lance_video_row_counts(profile_dir)
            self.assertEqual(counts["vid999"]["frame_count"], 4)
            self.assertGreaterEqual(counts["vid999"]["chunk_count"], 0)


class LanceStorageHelperTests(unittest.TestCase):
    def test_format_byte_size(self):
        self.assertEqual(format_byte_size(0), "0 B")
        self.assertEqual(format_byte_size(500), "500 B")
        self.assertEqual(format_byte_size(1024), "1.0 KB")
        self.assertEqual(format_byte_size(1536), "1.5 KB")

    def test_allocate_lance_dir_bytes_by_weight_splits_proportionally(self):
        allocated = allocate_lance_dir_bytes_by_weight(
            1001,
            {"vid_a": 300, "vid_b": 700},
        )
        self.assertEqual(sum(allocated.values()), 1001)
        self.assertEqual(allocated["vid_a"], 300)
        self.assertEqual(allocated["vid_b"], 701)

    def test_allocate_lance_dir_bytes_by_weight_returns_zeros_without_weight(self):
        allocated = allocate_lance_dir_bytes_by_weight(1000, {"vid_a": 0})
        self.assertEqual(allocated, {"vid_a": 0})


if __name__ == "__main__":
    unittest.main()
