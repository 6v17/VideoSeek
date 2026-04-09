import sys
import types
import unittest
from unittest.mock import patch

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None
if np is not None and not hasattr(np, "asarray"):  # pragma: no cover
    np = None

sys.modules.setdefault("cv2", types.SimpleNamespace())
sys.modules.setdefault("onnxruntime", types.SimpleNamespace())
sys.modules.setdefault("faiss", types.SimpleNamespace())
sys.modules.setdefault("ftfy", types.SimpleNamespace(fix_text=lambda text: text))
sys.modules.setdefault("regex", __import__("re"))

if np is not None:
    from src.core.semantic_chunking import build_semantic_chunks, unpack_chunks
    from src.services import indexing_service
    from src.services import search_service
else:  # pragma: no cover
    build_semantic_chunks = None
    unpack_chunks = None
    indexing_service = None
    search_service = None


@unittest.skipIf(np is None, "numpy is required for semantic chunking tests")
class SemanticChunkingTests(unittest.TestCase):
    def test_build_semantic_chunks_splits_on_low_chunk_similarity(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.02, 0.98],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0, 3.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.85,
            max_chunk_duration=10.0,
            min_chunk_size=2,
            similarity_mode="chunk",
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 1.0))
        self.assertEqual((chunks[1]["start"], chunks[1]["end"]), (2.0, 3.0))

    def test_build_semantic_chunks_supports_frame_similarity_mode(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [0.9, 0.1],
                [0.8, 0.2],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 1.0, 2.0]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.7,
            max_chunk_duration=10.0,
            min_chunk_size=1,
            similarity_mode="frame",
        )

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 2.0))

    def test_build_semantic_chunks_respects_max_duration(self):
        embeddings = np.asarray(
            [
                [1.0, 0.0],
                [1.0, 0.0],
                [1.0, 0.0],
            ],
            dtype=np.float32,
        )
        timestamps = [0.0, 3.0, 6.5]

        chunks = build_semantic_chunks(
            embeddings,
            timestamps,
            similarity_threshold=0.1,
            max_chunk_duration=5.0,
            min_chunk_size=1,
            similarity_mode="chunk",
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 3.0))
        self.assertEqual((chunks[1]["start"], chunks[1]["end"]), (6.5, 6.5))


@unittest.skipIf(np is None, "numpy is required for semantic chunking tests")
class IndexingChunkUpgradeTests(unittest.TestCase):
    @patch("src.services.indexing_service.save_vectors")
    @patch("src.services.indexing_service.load_vectors")
    def test_load_video_chunks_by_id_builds_chunks_from_existing_vectors(self, mock_load_vectors, mock_save_vectors):
        mock_load_vectors.return_value = {
            "vector": np.asarray([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
            "timestamps": np.asarray([0.0, 1.0], dtype=np.float32),
        }
        config = {
            "vector_dir": "data/vector",
            "similarity_threshold": 0.85,
            "max_chunk_duration": 5.0,
            "min_chunk_size": 2,
            "chunk_similarity_mode": "chunk",
        }

        chunks = indexing_service.load_video_chunks_by_id("video-1", config)

        self.assertEqual(len(chunks), 1)
        self.assertEqual((chunks[0]["start"], chunks[0]["end"]), (0.0, 1.0))
        mock_save_vectors.assert_called_once()

    @patch("src.services.indexing_service.save_vectors")
    @patch("src.services.indexing_service.load_vectors")
    def test_load_video_chunks_by_id_rebuilds_when_chunk_config_changes(self, mock_load_vectors, mock_save_vectors):
        mock_load_vectors.return_value = {
            "vector": np.asarray([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
            "timestamps": np.asarray([0.0, 1.0], dtype=np.float32),
            "chunks": {
                "start": np.asarray([0.0], dtype=np.float32),
                "end": np.asarray([1.0], dtype=np.float32),
                "embedding": np.asarray([[1.0, 0.0]], dtype=np.float32),
            },
            "chunk_config": {
                "similarity_threshold": 0.9,
                "max_chunk_duration": 5.0,
                "min_chunk_size": 2,
                "similarity_mode": "chunk",
            },
        }
        config = {
            "vector_dir": "data/vector",
            "similarity_threshold": 0.85,
            "max_chunk_duration": 5.0,
            "min_chunk_size": 2,
            "chunk_similarity_mode": "chunk",
        }

        indexing_service.load_video_chunks_by_id("video-1", config)

        mock_save_vectors.assert_called_once()
        saved_chunk_config = mock_save_vectors.call_args.kwargs["chunk_config"]
        self.assertEqual(saved_chunk_config["similarity_threshold"], 0.85)

    def test_unpack_chunks_reconstructs_chunk_list(self):
        payload = {
            "start": np.asarray([0.0, 2.0], dtype=np.float32),
            "end": np.asarray([1.0, 3.0], dtype=np.float32),
            "embedding": np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        }

        chunks = unpack_chunks(payload)

        self.assertEqual(len(chunks), 2)
        self.assertEqual((chunks[0]["start"], chunks[1]["end"]), (0.0, 3.0))

    @patch("src.services.indexing_service.create_clip_index")
    @patch("src.services.indexing_service.np.save")
    @patch("src.services.indexing_service.ensure_folder_exists")
    def test_merge_and_save_all_chunks_persists_ranges(self, _mock_ensure_folder, mock_np_save, mock_create_index):
        config = {
            "cross_chunk_index_file": "data/global/cross_chunk_index.faiss",
            "cross_chunk_vector_file": "data/global/cross_chunk_vectors.npy",
        }
        vectors = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        ranges = [(0.0, 1.0), (2.0, 3.0)]
        paths = ["a.mp4", "b.mp4"]

        indexing_service.merge_and_save_all_chunks(vectors, ranges, paths, config)

        mock_create_index.assert_called_once()
        saved_payload = mock_np_save.call_args[0][1]
        self.assertEqual(saved_payload["ranges"].shape, (2, 2))
        self.assertEqual(saved_payload["paths"], paths)


@unittest.skipIf(np is None, "numpy is required for semantic chunking tests")
class ChunkSearchTests(unittest.TestCase):
    @patch("src.services.search_service.load_clip_index")
    @patch("src.services.search_service.np.load")
    @patch("src.services.search_service.os.path.exists", return_value=True)
    def test_load_chunk_search_assets_reads_ranges(self, _mock_exists, mock_np_load, mock_load_index):
        mock_load_index.return_value = object()
        mock_np_load.return_value.item.return_value = {
            "ranges": np.asarray([[0.0, 1.0]], dtype=np.float32),
            "paths": ["video.mp4"],
        }

        index, ranges, paths = search_service.load_chunk_search_assets(
            {
                "cross_chunk_index_file": "cross_chunk_index.faiss",
                "cross_chunk_vector_file": "cross_chunk_vectors.npy",
            }
        )

        self.assertIsNotNone(index)
        self.assertEqual(ranges.shape, (1, 2))
        self.assertEqual(paths, ["video.mp4"])

    @patch("src.services.search_service.run_chunk_search", return_value=[("chunk",)])
    @patch("src.services.search_service.load_config", return_value={"search_mode": "chunk", "search_top_k": 20})
    def test_run_search_dispatches_to_chunk_mode(self, _mock_load_config, mock_run_chunk_search):
        result = search_service.run_search("query", is_text=True, top_k=5)

        self.assertEqual(result, [("chunk",)])
        mock_run_chunk_search.assert_called_once_with("query", is_text=True, top_k=5)


if __name__ == "__main__":
    unittest.main()
