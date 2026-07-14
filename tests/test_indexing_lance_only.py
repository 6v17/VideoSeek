"""Indexing reads are Lance-only (legacy npy is migration sidecar)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from src.services import indexing_service


class LoadVectorsLanceOnlyTests(unittest.TestCase):
    @patch("src.storage.lance_search_index.load_lance_video_frame_arrays")
    @patch("src.services.indexing_service.get_local_model_asset_dirs")
    def test_load_vectors_prefers_lance_and_ignores_npy(
        self,
        mock_model_dirs,
        mock_load_lance,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            vector_dir = os.path.join(temp_dir, "vector")
            os.makedirs(vector_dir)
            npy_path = os.path.join(vector_dir, "vid_vectors.npy")
            with open(npy_path, "wb") as handle:
                handle.write(b"not-a-real-npy")
            mock_model_dirs.return_value = {
                "base_dir": temp_dir,
                "vector_dir": vector_dir,
                "index_dir": os.path.join(temp_dir, "index"),
            }
            expected_vectors = np.asarray([[1.0, 0.0]], dtype=np.float32)
            expected_timestamps = np.asarray([1.5], dtype=np.float32)
            mock_load_lance.return_value = (expected_vectors, expected_timestamps)

            vectors, timestamps, reported_path = indexing_service._load_vectors_from_disk("vid", {})

        self.assertTrue(np.allclose(vectors, expected_vectors))
        self.assertTrue(np.allclose(timestamps, expected_timestamps))
        self.assertEqual(reported_path, npy_path)
        mock_load_lance.assert_called_once_with(temp_dir, "vid")

    @patch("src.storage.lance_search_index.load_lance_video_frame_arrays", return_value=(None, None))
    @patch("src.services.indexing_service.get_local_model_asset_dirs")
    def test_load_vectors_miss_when_only_legacy_npy_remains(
        self,
        mock_model_dirs,
        _mock_load_lance,
    ):
        with tempfile.TemporaryDirectory() as temp_dir:
            vector_dir = os.path.join(temp_dir, "vector")
            os.makedirs(vector_dir)
            npy_path = os.path.join(vector_dir, "vid_vectors.npy")
            with open(npy_path, "wb") as handle:
                handle.write(b"legacy")
            mock_model_dirs.return_value = {
                "base_dir": temp_dir,
                "vector_dir": vector_dir,
                "index_dir": os.path.join(temp_dir, "index"),
            }

            vectors, timestamps, reported_path = indexing_service._load_vectors_from_disk("vid", {})

        self.assertIsNone(vectors)
        self.assertIsNone(timestamps)
        self.assertEqual(reported_path, npy_path)


if __name__ == "__main__":
    unittest.main()
